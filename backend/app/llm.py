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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypeVar

from openai import BadRequestError, OpenAI
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


def complete_json(
    *,
    role: Role,
    system: str,
    user: str,
    schema: type[T],
    kind: str,
    temperature: float = 0.2,
) -> T | None:
    """Ask for JSON matching `schema`. Validate; retry once; else log and return None."""
    from app.db.session import log_agent_run  # local import avoids cycles

    budget = current_budget()
    if budget is not None and budget.exhausted:
        log.warning("llm %s skipped: run token budget exhausted (%s/%s)", kind, budget.used, budget.limit)
        return None
    sys_prompt = (
        f"{system}\n\nRespond with ONLY a JSON object matching this JSON Schema. "
        f"No prose, no markdown.\n{json.dumps(schema.model_json_schema())}"
    )
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    started = datetime.now(timezone.utc)
    tokens_in = tokens_out = 0
    last_err = ""
    raw = ""
    for attempt in range(2):
        try:
            t0 = time.perf_counter()
            extra = {}
            if "gpt-oss" in model_for(role) and get_settings().llm_provider == "groq":
                extra["reasoning_effort"] = "medium" if role == "strong" else "low"
            resp = client().chat.completions.create(
                model=model_for(role),
                messages=messages,
                temperature=temperature,
                max_tokens=get_settings().llm_max_tokens,
                response_format={"type": "json_object"},
                extra_body=extra or None,
            )
            log.debug("llm %s %.1fs", kind, time.perf_counter() - t0)
            if resp.usage:
                tokens_in += resp.usage.prompt_tokens or 0
                tokens_out += resp.usage.completion_tokens or 0
                if budget is not None:
                    budget.used += (resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0)
                    budget.calls += 1
            raw = resp.choices[0].message.content or ""
            parsed = schema.model_validate_json(_extract_json(raw))
            log_agent_run(kind, started, {"user": user[:4000]}, parsed.model_dump(mode="json"),
                          tokens_in=tokens_in, tokens_out=tokens_out, model=model_for(role))
            return parsed
        except BadRequestError as e:
            # Tool-trained models (gpt-oss) sometimes emit a native function call instead of JSON; Groq rejects it.
            if "tool_use_failed" not in str(e) or attempt == 1:
                last_err = f"BadRequestError: {e}"
                break
            last_err = "model attempted a native tool call"
            messages += [{"role": "user", "content": "You cannot call functions. Reply with the JSON object only; "
                          "put a tool name in the `action` field and its arguments in `args`."}]
        except ValidationError as e:
            last_err = f"validation: {e}"
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your JSON failed validation:\n{e}\nReturn corrected JSON only."},
            ]
        except Exception as e:  # network / provider errors: no point retrying the same prompt twice
            last_err = f"{type(e).__name__}: {e}"
            break
    log.warning("llm %s failed: %s", kind, last_err)
    log_agent_run(kind, started, {"user": user[:4000]}, {"raw": raw[:4000]},
                  tokens_in=tokens_in, tokens_out=tokens_out, error=last_err, model=model_for(role))
    return None


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
