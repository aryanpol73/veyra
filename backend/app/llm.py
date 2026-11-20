"""LLM client over the free-tier provider pool (app/llm_pool.py): Groq, Mistral, Gemini, OpenRouter, Ollama.

Every structured call:  JSON mode -> Pydantic validation -> one retry with the
validation error fed back -> otherwise log + return None (caller skips).
Every call is logged to `agent_runs`.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypeVar

from openai import (APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, BadRequestError,
                    NotFoundError, PermissionDeniedError, RateLimitError)
from pydantic import BaseModel, ValidationError

from app import llm_pool as pool
from app.config import get_settings

log = logging.getLogger("veyra.llm")
T = TypeVar("T", bound=BaseModel)
Role = Literal["strong", "fast"]

@dataclass
class TokenBudget:
    """Per-run hard token budget (config.run_max_tokens). Calls beyond it are refused, not made."""
    limit: int
    used: int = 0
    calls: int = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


_budget: contextvars.ContextVar[TokenBudget | None] = contextvars.ContextVar("llm_budget", default=None)


def start_budget(limit: int | None = None) -> TokenBudget:
    b = TokenBudget(limit=limit or get_settings().run_max_tokens)
    _budget.set(b)
    return b


def current_budget() -> TokenBudget | None:
    return _budget.get()


def model_for(role: Role) -> str:
    """First configured endpoint for a role (for display/logging)."""
    eps = pool.chain(role)
    return eps[0].name if eps else "not configured"


def _extract_json(text: str) -> str:
    """Models sometimes wrap JSON in ```json fences or add <think> blocks."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        return m.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    return text[start:] if start > 0 else text


def _wrap_bare_list(text: str, schema: type[BaseModel]) -> str:
    """Models sometimes return `[...]` when the schema is `{"items": [...]}`: wrap it if that's unambiguous."""
    if not text.lstrip().startswith("["):
        return text
    list_fields = [n for n, f in schema.model_fields.items() if getattr(f.annotation, "__origin__", None) is list]
    required = [n for n, f in schema.model_fields.items() if f.is_required()]
    if len(list_fields) == 1 and set(required) <= set(list_fields):
        return json.dumps({list_fields[0]: json.loads(text)})
    return text


def _translate_native_call(e: Exception, schema: type[BaseModel]) -> dict | None:
    """Groq returns a rejected native tool call as failed_generation '{"name": X, "arguments": {...}}'.
    For our action/args schemas that's the same intent: {"action": X, "args": {...}}."""
    if not {"action", "args"} <= set(schema.model_fields):
        return None
    body = getattr(e, "body", None) or {}
    err = body.get("error", body) if isinstance(body, dict) else {}
    gen = err.get("failed_generation") if isinstance(err, dict) else None
    if not gen:
        m = re.search(r"'failed_generation': '(.*)'\}", str(e))
        gen = m.group(1) if m else None
    try:
        call = json.loads(gen) if isinstance(gen, str) else gen
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(call, dict) or "name" not in call:
        return None
    args = call.get("arguments") or call.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    return {"action": call["name"], "args": args if isinstance(args, dict) else {}}


def complete_json(
    *,
    role: Role,
    system: str,
    user: str,
    schema: type[T],
    kind: str,
    temperature: float = 0.2,
    max_wait_s: float | None = None,
    fallback_role: Role | None = None,
) -> T | None:
    """Ask for JSON matching `schema` from the free-tier pool. Validate; retry once; else log and return None.

    Endpoints are tried in order (app/llm_pool.py). A short rate-limit wait is waited out on the same endpoint;
    a long one (a daily cap) rests that endpoint and moves to the next. `fallback_role` appends the other role's
    endpoints. If every endpoint is resting, wait for the soonest only if that fits in `max_wait_s`
    (default config.llm_max_wait_s; interactive callers pass ~20 s)."""
    from app.db.session import log_agent_run  # local import avoids cycles

    budget = current_budget()
    if budget is not None and budget.exhausted:
        log.warning("llm %s skipped: run token budget exhausted (%s/%s)", kind, budget.used, budget.limit)
        return None
    primary = pool.chain(role)
    extra = [e for e in pool.chain(fallback_role) if e not in primary] if fallback_role else []
    eps = primary + extra
    if not eps:
        log.warning("llm %s skipped: no LLM endpoint configured (add a key to .env)", kind)
        return None
    sys_prompt = (
        f"{system}\n\nRespond with ONLY a JSON object matching this JSON Schema. "
        f"No prose, no markdown.\n{json.dumps(schema.model_json_schema())}"
    )
    sys_prompt, user = mask(sys_prompt), mask(user)  # contamination control (no-op unless masking is active)
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    started = datetime.now(timezone.utc)
    tokens_in = tokens_out = 0
    last_err, raw, used = "", "", None
    attempt = 0  # validation/format retries (one), shared across endpoints; rate limits never consume it
    limit_wait = get_settings().llm_max_wait_s if max_wait_s is None else max_wait_s
    short_wait = min(limit_wait, 30.0)
    hops = 0
    while attempt < 2 and hops < 40:
        hops += 1
        ep = next((e for e in eps if pool.available(e)), None)
        if ep is None:
            soon = pool.soonest_available(eps)
            if soon and soon[1] <= limit_wait:
                log.warning("llm %s: all %d endpoints resting; waiting %.0fs for %s", kind, len(eps), soon[1], soon[0].name)
                time.sleep(soon[1] + 1)
                continue
            last_err = "every LLM endpoint is rate-limited or unavailable"
            LAST_RATE_LIMIT.update(kind=kind, wait_s=soon[1] if soon else None, at=time.time())
            break
        used = ep
        try:
            prompt_est = sum(len(m["content"]) for m in messages) // 3  # conservative chars->tokens
            max_out = pool.max_output(ep, prompt_est)
            pool.throttle(ep, prompt_est + max_out)
            kwargs = dict(model=ep.model, messages=messages, temperature=temperature, max_tokens=max_out,
                          extra_body=ep.extra_body(role))
            if ep.json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = pool.client_for(ep).chat.completions.create(**kwargs)
            if resp.usage:
                n = (resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0)
                pool.record_usage(ep, n)
                tokens_in += resp.usage.prompt_tokens or 0
                tokens_out += resp.usage.completion_tokens or 0
                if budget is not None:
                    budget.used += n
                    budget.calls += 1
            raw = unmask((resp.choices[0].message.content or "") if resp.choices else "")
            if not raw.strip():  # empty reply (overloaded provider, length cut-off): fail over, don't burn the retry
                pool.cool_down(ep, 300, "empty reply")
                last_err = f"empty reply from {ep.name}"
                continue
            parsed = schema.model_validate_json(_wrap_bare_list(_extract_json(raw), schema))
            meta = {"user": user[:4000]}
            if ep is not eps[0]:
                meta["failed_over_to"] = ep.name
            log_agent_run(kind, started, meta, parsed.model_dump(mode="json"),
                          tokens_in=tokens_in, tokens_out=tokens_out, model=ep.name)
            return parsed
        except RateLimitError as e:
            wait = _retry_after_s(str(e))
            if wait is not None and wait <= short_wait and "per day" not in str(e):
                log.info("llm %s: %s per-minute limit; waiting %.0fs", kind, ep.name, wait)
                time.sleep(wait + 1)
            else:  # daily cap or unknown: rest this endpoint, the next one takes over
                pool.cool_down(ep, wait if wait is not None else 3600, "daily cap" if "per day" in str(e) else "rate limited")
            last_err = f"RateLimitError on {ep.name}"
            continue
        except (AuthenticationError, PermissionDeniedError, NotFoundError) as e:
            pool.cool_down(ep, 6 * 3600, f"{type(e).__name__}: check the key/model ({str(e)[:120]})")
            last_err = f"{type(e).__name__} on {ep.name}"
            continue
        except BadRequestError as e:
            action, parsed, last_err = _bad_request(e, ep, schema, messages, attempt)
            if parsed is not None:
                log_agent_run(kind, started, {"user": user[:4000], "translated_native_tool_call": True},
                              parsed.model_dump(mode="json"), tokens_in=tokens_in, tokens_out=tokens_out, model=ep.name)
                return parsed
            if action == "retry_same":
                continue
            if action == "retry_counted":
                attempt += 1
                continue
            break
        except APIStatusError as e:
            if e.status_code == 402:  # e.g. Ollama Cloud without credits
                pool.cool_down(ep, 6 * 3600, "needs paid credits (402)")
                last_err = f"402 on {ep.name}"
                continue
            if e.status_code >= 500:
                pool.cool_down(ep, 120, f"provider error {e.status_code}")
                last_err = f"{e.status_code} on {ep.name}"
                continue
            last_err = f"{type(e).__name__}: {str(e)[:300]}"
            break
        except (APIConnectionError, APITimeoutError) as e:
            pool.cool_down(ep, 60, f"unreachable: {type(e).__name__}")
            last_err = f"{type(e).__name__} on {ep.name}"
            continue
        except ValidationError as e:
            last_err = f"validation: {e}"
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your JSON failed validation:\n{e}\nReturn corrected JSON only."},
            ]
            attempt += 1
        except Exception as e:  # unexpected: don't hammer, report
            last_err = f"{type(e).__name__}: {e}"
            break
    log.warning("llm %s failed: %s", kind, last_err)
    log_agent_run(kind, started, {"user": user[:4000]}, {"raw": raw[:4000]},
                  tokens_in=tokens_in, tokens_out=tokens_out, error=last_err, model=used.name if used else None)
    return None


def _bad_request(e: BadRequestError, ep, schema, messages: list, attempt: int):
    """-> (action, translated_result_or_None, last_err). action: done | retry_same | retry_counted | fail."""
    msg = str(e)
    if "tool_use_failed" in msg:  # gpt-oss emitted a native function call; Groq rejected it
        translated = _translate_native_call(e, schema)
        if translated is not None:
            try:
                return "done", schema.model_validate(translated), ""
            except ValidationError:
                pass
    if ep.json_mode and "response_format" in msg:  # provider/model lacks JSON mode: rely on the prompt instead
        ep.json_mode = False
        return "retry_same", None, f"{ep.name} rejected response_format; retrying without it"
    retryable = any(x in msg for x in ("tool_use_failed", "Failed to validate JSON", "json_validate_failed",
                                       "output_parse_failed", "Parsing failed"))
    if not retryable or attempt == 1:
        return "fail", None, f"BadRequestError: {msg[:300]}"
    if "tool_use_failed" in msg:
        messages += [{"role": "user", "content": "You cannot call functions. Reply with the JSON object only; "
                      "put a tool name in the `action` field and its arguments in `args`."}]
        return "retry_counted", None, "model attempted a native tool call"
    messages += [{"role": "user", "content": "Your previous reply was not valid JSON. Reply with one valid "
                  "JSON object only: double-quoted keys and strings, no comments, no trailing commas."}]
    return "retry_counted", None, "provider rejected malformed JSON"


LAST_RATE_LIMIT: dict = {}  # last call that gave up on a rate limit (for user-facing messages)


def _retry_after_s(msg: str) -> float | None:
    """Parse Groq's "try again in 9m58.3s" / "929ms" / "1h2m3s" into seconds."""
    ms = re.search(r"try again in ([\d.]+)ms", msg)
    if ms:
        return float(ms.group(1)) / 1000
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)?s?", msg)
    if not m or not any(m.groups()):
        return None
    h, mnt, sec = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mnt * 60 + sec


# ---------------- contamination control: name masking ----------------
_mask: contextvars.ContextVar[list[tuple[re.Pattern, str, str]] | None] = contextvars.ContextVar("llm_mask", default=None)


def set_mask(aliases: dict[str, str] | None) -> None:
    """aliases: real term -> neutral token (e.g. {"Vercel": "CompanyA", "vercel.com": "companya.example"}).
    Prompts are masked before sending; replies are unmasked before validation, so the model never sees the names."""
    if not aliases:
        _mask.set(None)
        return
    items = sorted(aliases.items(), key=lambda kv: -len(kv[0]))  # longest first: "vercel.com" before "Vercel"
    _mask.set([(re.compile(rf"(?<![\w.]){re.escape(real)}(?![\w])", re.I), real, tok) for real, tok in items])


def mask(text: str) -> str:
    for rx, _, tok in _mask.get() or []:
        text = rx.sub(tok, text)
    return text


def unmask(text: str) -> str:
    for _, real, tok in _mask.get() or []:
        text = re.sub(rf"(?<![\w]){re.escape(tok)}(?![\w])", real, text)
    return text


def ping() -> dict:
    """Live check for /health?llm_check=true: the first endpoint that answers."""
    fast = pool.chain("fast")
    eps = fast + [e for e in pool.chain("strong") if e not in fast]
    if not eps:
        return {"ok": False, "error": "no LLM key configured: add GROQ_API_KEY, MISTRAL_API_KEY or GEMINI_API_KEY to .env"}
    errors = []
    for ep in eps:
        try:
            r = pool.client_for(ep).chat.completions.create(
                model=ep.model, messages=[{"role": "user", "content": "Reply with: ok"}], max_tokens=200)
            reply = (r.choices[0].message.content or "") if r.choices else ""
            return {"ok": True, "endpoint": ep.name, "reply": reply.strip()[:20]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ep.name}: {type(e).__name__}")
    return {"ok": False, "error": "; ".join(errors)[:300]}
