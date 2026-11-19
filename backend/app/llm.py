"""Provider-agnostic LLM client (Groq / Ollama / any OpenAI-compatible API).

Every structured call:  JSON mode -> Pydantic validation -> one retry with the
validation error fed back -> otherwise log + return None (caller skips).
Every call is logged to `agent_runs`.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypeVar

from openai import BadRequestError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from app.config import get_settings

log = logging.getLogger("veyra.llm")
T = TypeVar("T", bound=BaseModel)
Role = Literal["strong", "fast"]

_client: OpenAI | None = None


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


def client() -> OpenAI:
    global _client
    if _client is None:
        s = get_settings()
        _client = OpenAI(
            base_url=s.resolved_base_url,
            api_key=s.llm_api_key or "ollama",  # local ollama ignores the key
            timeout=s.llm_timeout_s,
            max_retries=5,  # Groq free tier 429s: SDK backs off using retry-after
        )
    return _client


def model_for(role: Role) -> str:
    s = get_settings()
    return s.model_strong if role == "strong" else s.model_fast


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
    """Ask for JSON matching `schema`. Validate; retry once; else log and return None.

    Rate limits: wait up to `max_wait_s` (default config.llm_max_wait_s; interactive callers pass ~20 s). If the
    wait would be longer and `fallback_role` is given, switch to that model once (separate quota on Groq)."""
    from app.db.session import log_agent_run  # local import avoids cycles

    budget = current_budget()
    if budget is not None and budget.exhausted:
        log.warning("llm %s skipped: run token budget exhausted (%s/%s)", kind, budget.used, budget.limit)
        return None
    sys_prompt = (
        f"{system}\n\nRespond with ONLY a JSON object matching this JSON Schema. "
        f"No prose, no markdown.\n{json.dumps(schema.model_json_schema())}"
    )
    sys_prompt, user = mask(sys_prompt), mask(user)  # contamination control (no-op unless masking is active)
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    started = datetime.now(timezone.utc)
    tokens_in = tokens_out = 0
    last_err = ""
    raw = ""
    attempt = waits = 0  # rate-limit waits do NOT use up the one validation retry
    limit_wait = get_settings().llm_max_wait_s if max_wait_s is None else max_wait_s
    role_requested = role
    while attempt < 2:
        try:
            prompt_est = sum(len(m["content"]) for m in messages) // 3  # conservative chars->tokens
            max_out = get_settings().llm_max_tokens
            if _tpm_limit():  # Groq counts max_tokens toward the per-minute limit: keep prompt + reservation under it
                max_out = max(800, min(max_out, int(_tpm_limit() * 0.95) - prompt_est))
            throttle(prompt_est + max_out)
            t0 = time.perf_counter()
            extra = {}
            if "gpt-oss" in model_for(role) and get_settings().llm_provider == "groq":
                extra["reasoning_effort"] = "medium" if role == "strong" else "low"
            resp = client().chat.completions.create(
                model=model_for(role),
                messages=messages,
                temperature=temperature,
                max_tokens=max_out,
                response_format={"type": "json_object"},
                extra_body=extra or None,
            )
            log.debug("llm %s %.1fs", kind, time.perf_counter() - t0)
            if resp.usage:
                record_usage((resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0))
                tokens_in += resp.usage.prompt_tokens or 0
                tokens_out += resp.usage.completion_tokens or 0
                if budget is not None:
                    budget.used += (resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0)
                    budget.calls += 1
            raw = unmask(resp.choices[0].message.content or "")
            parsed = schema.model_validate_json(_wrap_bare_list(_extract_json(raw), schema))
            log_agent_run(kind, started, {"user": user[:4000], **({"fell_back_from": role_requested} if role != role_requested else {})},
                          parsed.model_dump(mode="json"), tokens_in=tokens_in, tokens_out=tokens_out, model=model_for(role))
            return parsed
        except RateLimitError as e:
            # Daily (TPD) limits come back as 429 with "try again in 9m58s": wait it out instead of degrading results.
            wait = _retry_after_s(str(e))
            waits += 1
            if (wait is None or wait > limit_wait) and fallback_role and role != fallback_role:
                log.warning("llm %s: %s rate-limited (%.0fs); falling back to %s", kind, role, wait or -1, fallback_role)
                role, waits = fallback_role, 0
                continue
            if wait is None or wait > limit_wait or waits > 8:
                last_err = f"RateLimitError: {str(e)[:300]}"
                LAST_RATE_LIMIT.update(kind=kind, wait_s=wait, at=time.time())
                break
            log.warning("llm %s rate-limited (%s); waiting %.0fs", kind, "daily" if "per day" in str(e) else "minute", wait)
            time.sleep(wait + 2)
            last_err = "rate limited; retried after wait"
            continue
        except BadRequestError as e:
            # Tool-trained models (gpt-oss) sometimes emit a native function call instead of JSON; Groq rejects it.
            # ...or produces malformed JSON, which Groq's JSON mode rejects server-side ("Failed to validate JSON").
            msg = str(e)
            translated = _translate_native_call(e, schema) if "tool_use_failed" in msg else None
            if translated is not None:  # the model's intent is unambiguous: use it instead of re-asking
                raw = json.dumps(translated)
                try:
                    parsed = schema.model_validate(translated)
                    log_agent_run(kind, started, {"user": user[:4000], "translated_native_tool_call": True},
                                  parsed.model_dump(mode="json"), tokens_in=tokens_in, tokens_out=tokens_out, model=model_for(role))
                    return parsed
                except ValidationError:
                    pass
            retryable = any(x in msg for x in ("tool_use_failed", "Failed to validate JSON", "json_validate_failed",
                                                 "output_parse_failed", "Parsing failed"))
            if not retryable or attempt == 1:
                last_err = f"BadRequestError: {e}"
                break
            if "tool_use_failed" in msg:
                last_err = "model attempted a native tool call"
                messages += [{"role": "user", "content": "You cannot call functions. Reply with the JSON object only; "
                              "put a tool name in the `action` field and its arguments in `args`."}]
            else:
                last_err = "provider rejected malformed JSON"
                messages += [{"role": "user", "content": "Your previous reply was not valid JSON. Reply with one valid "
                              "JSON object only: double-quoted keys and strings, no comments, no trailing commas."}]
            attempt += 1
        except ValidationError as e:
            last_err = f"validation: {e}"
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your JSON failed validation:\n{e}\nReturn corrected JSON only."},
            ]
            attempt += 1
        except Exception as e:  # network / provider errors: no point retrying the same prompt twice
            last_err = f"{type(e).__name__}: {e}"
            break
    log.warning("llm %s failed: %s", kind, last_err)
    log_agent_run(kind, started, {"user": user[:4000]}, {"raw": raw[:4000]},
                  tokens_in=tokens_in, tokens_out=tokens_out, error=last_err, model=model_for(role))
    return None


LAST_RATE_LIMIT: dict = {}  # last call that gave up on a rate limit (for user-facing messages)


# ---------------- rate limiting (client-side; Groq free tier = 8k tokens/min/model) ----------------
_usage: deque[tuple[float, int]] = deque()
_usage_lock = threading.Lock()


def _tpm_limit() -> int:
    s = get_settings()
    return s.llm_tpm_limit or (8000 if s.llm_provider == "groq" else 0)


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


def record_usage(tokens: int) -> None:
    with _usage_lock:
        _usage.append((time.monotonic(), tokens))


def throttle(estimate: int) -> None:
    """Block until the last 60 s of usage + this call's estimate fits under the TPM limit."""
    limit = _tpm_limit()
    if not limit:
        return
    estimate = min(estimate, int(limit * 0.95))
    while True:
        with _usage_lock:
            cutoff = time.monotonic() - 60
            while _usage and _usage[0][0] < cutoff:
                _usage.popleft()
            used = sum(t for _, t in _usage)
            wait = 0.0 if used + estimate <= limit * 0.95 or not _usage else _usage[0][0] - cutoff + 0.5
        if wait <= 0:
            return
        log.info("throttling %.1fs to stay under %d tokens/min", wait, limit)
        time.sleep(wait)


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
    """Tiny live check used by /health?llm=1."""
    s = get_settings()
    if not s.llm_configured:
        return {"ok": False, "error": "LLM not configured (set LLM_PROVIDER / LLM_API_KEY in .env)"}
    try:
        r = client().chat.completions.create(
            model=s.model_fast, messages=[{"role": "user", "content": "Reply with: ok"}], max_tokens=200
        )
        return {"ok": True, "reply": (r.choices[0].message.content or "").strip()[:20]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
