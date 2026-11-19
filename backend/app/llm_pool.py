"""Free-tier LLM pool: several OpenAI-compatible providers/models with automatic failover.

No single free tier is big enough for Veyra (Groq: ~200k tokens/day PER MODEL). The pool chains them:
each role ("strong", "fast") has an ordered list of endpoints. A call uses the first one that is available;
when one hits a daily cap it rests until its reset and the next takes over. Bad keys, unknown models and
"needs credits" (402) responses park an endpoint for a few hours instead of failing the call.

Keys (set whichever you have; every one is optional, and more keys = more free capacity):
  GROQ_API_KEY (or LLM_API_KEY with LLM_PROVIDER=groq)   console.groq.com/keys
  MISTRAL_API_KEY                                          console.mistral.ai  (free "Experiment" plan)
  GEMINI_API_KEY                                           aistudio.google.com/apikey
  OPENROUTER_API_KEY                                       openrouter.ai/keys  (":free" models)
  OLLAMA_API_KEY                                           ollama.com (cloud models need credits)
  OLLAMA_LOCAL=true                                        a local `ollama serve`, unlimited and offline

OpenRouter's free list changes often, so "@free" in a chain means "the best currently-free models" (looked up live).
Override the order with LLM_STRONG_CHAIN / LLM_FAST_CHAIN, e.g. "groq:openai/gpt-oss-120b,mistral:mistral-medium-latest".
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from openai import OpenAI

from app.config import get_settings

log = logging.getLogger("veyra.llm.pool")

PROVIDERS: dict[str, dict] = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "tpm": 8000},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "tpm": 0},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "tpm": 0},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "tpm": 0},
    "ollama_cloud": {"base_url": "https://ollama.com/v1", "tpm": 0},
    "ollama_local": {"base_url": "http://localhost:11434/v1", "tpm": 0},
}

# Ordered by quality for the role, interleaving providers so one provider's outage doesn't stall a run.
DEFAULT_CHAINS: dict[str, list[tuple[str, str]]] = {
    "strong": [("groq", "openai/gpt-oss-120b"), ("mistral", "mistral-medium-latest"), ("gemini", "gemini-flash-latest"),
               ("groq", "qwen/qwen3.8-27b"), ("openrouter", "@free"), ("ollama_cloud", "gpt-oss:120b"),
               ("ollama_local", "llama3.1:8b")],
    "fast": [("groq", "openai/gpt-oss-20b"), ("mistral", "mistral-small-latest"), ("gemini", "gemini-flash-lite-latest"),
             ("groq", "qwen/qwen3.8-27b"), ("openrouter", "@free"), ("ollama_cloud", "gpt-oss:20b"),
             ("ollama_local", "llama3.1:8b")],
}


@dataclass
class Endpoint:
    provider: str
    model: str
    base_url: str
    api_key: str
    tpm: int = 0
    json_mode: bool = True  # switched off automatically if the provider rejects response_format
    _usage: deque = field(default_factory=deque, repr=False)

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    def extra_body(self, role: str) -> dict | None:
        if self.provider == "groq" and "gpt-oss" in self.model:
            return {"reasoning_effort": "medium" if role == "strong" else "low"}
        return None


_clients: dict[tuple[str, str], OpenAI] = {}
_cool: dict[str, tuple[float, str]] = {}  # endpoint name -> (available again at, reason)
_lock = threading.Lock()


def provider_key(provider: str) -> str:
    s = get_settings()
    if provider == "groq":
        return s.groq_api_key or (s.llm_api_key if s.llm_provider == "groq" else "")
    if provider == "ollama_cloud":
        return s.ollama_api_key or (s.llm_api_key if s.llm_provider == "ollama_cloud" else "")
    if provider == "ollama_local":
        return "ollama" if (s.ollama_local or s.llm_provider == "ollama_local") else ""
    return {"mistral": s.mistral_api_key, "gemini": s.gemini_api_key, "openrouter": s.openrouter_api_key}.get(provider, "")


def _parse_chain(spec: str) -> list[tuple[str, str]]:
    out = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        provider, _, model = part.partition(":")
        if provider in PROVIDERS and model:
            out.append((provider, model))
        else:
            log.warning("ignoring bad chain entry %r (use provider:model)", part)
    return out


# ---------------- OpenRouter: which models are free changes often, so ask its public catalogue ----------------
_OR_CACHE: dict = {"at": 0.0, "models": []}
_OR_TTL = 6 * 3600
REPUTABLE = ("google/", "nvidia/", "meta-llama/", "mistralai/", "qwen/", "deepseek/", "moonshotai/", "z-ai/", "openai/",
             "microsoft/", "cohere/")
# tiny or code-only models; sizes need a boundary so "31b" isn't mistaken for "1b"
_TOO_SMALL = re.compile(r"(?<![\d.])(?:1\.7|1|2|3)b\b|nano|tiny|mini|-code|coder", re.I)


def openrouter_free_models(role: str, limit: int = 2) -> list[str]:
    """Current ':free' model ids from openrouter.ai/api/v1/models, best first for the role (cached 6 h)."""
    import httpx

    now = time.time()
    if now - _OR_CACHE["at"] > _OR_TTL:
        try:
            data = httpx.get("https://openrouter.ai/api/v1/models", timeout=8).json().get("data", [])
            _OR_CACHE.update(at=now, models=[m for m in data if str(m.get("id", "")).endswith(":free")])
        except Exception as e:  # noqa: BLE001 - offline: just no OpenRouter endpoints this time
            log.warning("couldn't list OpenRouter free models: %s", e)
            _OR_CACHE.update(at=now - _OR_TTL + 600, models=_OR_CACHE["models"])  # retry in 10 min
    strong_words, fast_words = ("ultra", "super", "large", "pro", "31b", "70b", "120b", "405b"), ("lightning", "flash", "lite", "small", "a4b", "26b", "8b")

    def score(m: dict) -> tuple:
        mid = m["id"].lower()
        words = strong_words if role == "strong" else fast_words
        return (mid.startswith(REPUTABLE), "response_format" in (m.get("supported_parameters") or []),
                any(w in mid for w in words), m.get("context_length") or 0)

    pool_ = [m for m in _OR_CACHE["models"] if not _TOO_SMALL.search(m["id"])]
    return [m["id"] for m in sorted(pool_, key=score, reverse=True)[:limit]]


def chain(role: str) -> list[Endpoint]:
    """Endpoints for a role that have credentials, in order."""
    s = get_settings()
    spec = s.llm_strong_chain if role == "strong" else s.llm_fast_chain
    pairs = _parse_chain(spec) if spec else list(DEFAULT_CHAINS[role])
    legacy = s.llm_strong if role == "strong" else s.llm_fast  # older single-provider config goes first
    if legacy and not spec and s.llm_provider in PROVIDERS:
        pairs = [(s.llm_provider, legacy)] + [p for p in pairs if p != (s.llm_provider, legacy)]
    expanded = []
    for provider, model in pairs:  # "@free" = whatever OpenRouter lists as free right now
        if provider == "openrouter" and model == "@free":
            if provider_key("openrouter"):
                expanded += [("openrouter", m) for m in openrouter_free_models(role)]
        else:
            expanded.append((provider, model))
    out, seen = [], set()
    for provider, model in expanded:
        key = provider_key(provider)
        if not key or (provider, model) in seen:
            continue
        seen.add((provider, model))
        base = s.llm_base_url if (s.llm_base_url and provider == s.llm_provider) else PROVIDERS[provider]["base_url"]
        tpm = s.llm_tpm_limit if (s.llm_tpm_limit and provider == "groq") else PROVIDERS[provider]["tpm"]
        out.append(_endpoint(provider, model, base, key, tpm))
    return out


_endpoints: dict[str, Endpoint] = {}


def _endpoint(provider: str, model: str, base: str, key: str, tpm: int) -> Endpoint:
    name = f"{provider}:{model}"
    ep = _endpoints.get(name)
    if ep is None or ep.api_key != key or ep.base_url != base:
        ep = Endpoint(provider, model, base, key, tpm)
        _endpoints[name] = ep
    return ep


def client_for(ep: Endpoint) -> OpenAI:
    k = (ep.base_url, ep.api_key)
    if k not in _clients:
        # max_retries=0: the pool decides whether to wait or fail over, not the SDK
        _clients[k] = OpenAI(base_url=ep.base_url, api_key=ep.api_key, timeout=get_settings().llm_timeout_s, max_retries=0)
    return _clients[k]


def available(ep: Endpoint) -> bool:
    with _lock:
        until = _cool.get(ep.name, (0.0, ""))[0]
    return time.time() >= until


def cool_down(ep: Endpoint, seconds: float, reason: str) -> None:
    with _lock:
        _cool[ep.name] = (time.time() + seconds, reason)
    log.warning("llm endpoint %s resting %.0fs: %s", ep.name, seconds, reason)


def soonest_available(eps: list[Endpoint]) -> tuple[Endpoint, float] | None:
    with _lock:
        waits = [(ep, max(0.0, _cool.get(ep.name, (0.0, ""))[0] - time.time())) for ep in eps]
    return min(waits, key=lambda x: x[1]) if waits else None


def status() -> list[dict]:
    """For /health and `python -m app.llm_check`: every configured endpoint and whether it is resting."""
    out = []
    for role in ("strong", "fast"):
        for ep in chain(role):
            with _lock:
                until, reason = _cool.get(ep.name, (0.0, ""))
            out.append({"role": role, "endpoint": ep.name, "available": time.time() >= until,
                        "rests_for_s": max(0, round(until - time.time())), "reason": reason or None})
    return out


def reset() -> None:
    with _lock:
        _cool.clear()
    _endpoints.clear()
    _clients.clear()


# ---------------- per-endpoint tokens/minute throttle (Groq free tier: 8k TPM per model) ----------------
def record_usage(ep: Endpoint, tokens: int) -> None:
    with _lock:
        ep._usage.append((time.monotonic(), tokens))


def throttle(ep: Endpoint, estimate: int) -> None:
    if not ep.tpm:
        return
    estimate = min(estimate, int(ep.tpm * 0.95))
    while True:
        with _lock:
            cutoff = time.monotonic() - 60
            while ep._usage and ep._usage[0][0] < cutoff:
                ep._usage.popleft()
            used = sum(t for _, t in ep._usage)
            wait = 0.0 if used + estimate <= ep.tpm * 0.95 or not ep._usage else ep._usage[0][0] - cutoff + 0.5
        if wait <= 0:
            return
        log.info("throttling %.1fs on %s to stay under %d tokens/min", wait, ep.name, ep.tpm)
        time.sleep(wait)


def max_output(ep: Endpoint, prompt_est: int) -> int:
    cap = get_settings().llm_max_tokens
    if ep.tpm:  # Groq counts max_tokens toward the per-minute limit: keep prompt + reservation under it
        cap = max(800, min(cap, int(ep.tpm * 0.95) - prompt_est))
    return cap
