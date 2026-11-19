"""LLM client control flow with a fake provider (no network)."""
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError
from pydantic import BaseModel

from app import llm
from app import llm_pool as pool


class Out(BaseModel):
    ok: bool


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def _rate_limit(msg: str) -> RateLimitError:
    req = httpx.Request("POST", "https://x")
    return RateLimitError(msg, response=httpx.Response(429, request=req), body=None)


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _resp(item)


def ep(name: str) -> pool.Endpoint:
    provider, _, model = name.partition(":")
    return pool.Endpoint(provider, model, "https://fake/" + provider, "k")


@pytest.fixture()
def fake(monkeypatch):
    """One scripted client behind a fake pool: strong = [groq:strong-a], fast = [groq:fast-b] unless overridden."""
    pool.reset()
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    monkeypatch.setattr("app.db.session.log_agent_run", lambda *a, **k: 0)
    chains = {"strong": [ep("groq:strong-a")], "fast": [ep("groq:fast-b")]}
    monkeypatch.setattr(pool, "chain", lambda role: chains.get(role, []) if role else [])

    def install(script, **override):
        chains.update(override)
        c = FakeClient(script)
        monkeypatch.setattr(pool, "client_for", lambda _ep: c)
        return c
    yield install
    pool.reset()


def _call():
    return llm.complete_json(role="fast", system="s", user="u", schema=Out, kind="t")


def test_validation_retry_once_then_give_up(fake):
    c = fake(['{"nope": 1}', '{"still": "bad"}', '{"ok": true}'])
    assert _call() is None and c.calls == 2  # no infinite loop: exactly one retry


def test_rate_limit_wait_does_not_consume_the_retry(fake):
    c = fake([_rate_limit("Please try again in 1.5s"), '{"bad": 1}', '{"ok": true}'])
    assert _call() == Out(ok=True) and c.calls == 3


def test_rate_limit_beyond_max_wait_fails(fake):
    c = fake([_rate_limit("Please try again in 23h59m0s")])
    assert _call() is None and c.calls == 1


def test_masking_round_trip(fake):
    c = fake(['{"ok": true}'])
    llm.set_mask({"Acme": "CompanyA"})
    try:
        assert llm.mask("Acme ships Acme Cloud") == "CompanyA ships CompanyA Cloud"
        assert llm.unmask("CompanyA wins") == "Acme wins"
    finally:
        llm.set_mask(None)
    assert llm.mask("Acme") == "Acme"


def test_provider_json_rejection_is_retried(fake):
    from openai import BadRequestError

    req = httpx.Request("POST", "https://x")
    err = BadRequestError("Failed to validate JSON. Please adjust your prompt.", response=httpx.Response(400, request=req), body=None)
    c = fake([err, '{"ok": true}'])
    assert _call() == Out(ok=True) and c.calls == 2


def test_bare_list_is_wrapped(fake):
    class Many(BaseModel):
        items: list[int]

    c = fake(['[1, 2, 3]'])
    assert llm.complete_json(role="fast", system="s", user="u", schema=Many, kind="t") == Many(items=[1, 2, 3])


def test_long_rate_limit_falls_back_to_other_model(fake, monkeypatch):
    seen = []
    c = fake([_rate_limit("Please try again in 5m16s"), '{"ok": true}'])
    orig = c._create

    def spy(**kw):
        seen.append(kw["model"])
        return orig(**kw)
    c.chat.completions.create = spy
    out = llm.complete_json(role="strong", system="s", user="u", schema=Out, kind="chat", max_wait_s=20, fallback_role="fast")
    assert out == Out(ok=True) and seen == ["strong-a", "fast-b"]


def test_interactive_call_fails_fast_without_fallback(fake):
    c = fake([_rate_limit("Please try again in 5m16s")])
    assert llm.complete_json(role="strong", system="s", user="u", schema=Out, kind="chat", max_wait_s=20) is None
    assert 300 < llm.LAST_RATE_LIMIT["wait_s"] <= 316 and c.calls == 1


def test_native_tool_call_is_translated_for_action_schemas(fake):
    from openai import BadRequestError

    from app.agents.chat import ChatStep

    req = httpx.Request("POST", "https://x")
    body = {"error": {"code": "tool_use_failed", "message": "Tool choice is none, but model called a tool",
                      "failed_generation": '{"name": "search_evidence", "arguments": {"keywords": ["pricing"]}}'}}
    err = BadRequestError("Error code: 400 - tool_use_failed", response=httpx.Response(400, request=req), body=body)
    c = fake([err])
    out = llm.complete_json(role="fast", system="s", user="u", schema=ChatStep, kind="chat")
    assert out.action == "search_evidence" and out.args == {"keywords": ["pricing"]} and c.calls == 1



# ---------------- free-tier pool failover ----------------
def _status(code: int, msg: str):
    from openai import APIStatusError, NotFoundError

    req = httpx.Request("POST", "https://x")
    cls = NotFoundError if code == 404 else APIStatusError
    return cls(msg, response=httpx.Response(code, request=req), body=None)


def test_daily_cap_fails_over_through_the_chain(fake):
    seen = []
    chain = [ep("groq:a"), ep("mistral:b"), ep("gemini:c")]
    c = fake([_rate_limit("Rate limit reached ... tokens per day (TPD) ... try again in 11m0s"),
              _rate_limit("try again in 2h0m0s"), '{"ok": true}'], fast=chain)
    orig = c._create
    c.chat.completions.create = lambda **kw: (seen.append(kw["model"]), orig(**kw))[1]
    assert _call() == Out(ok=True) and seen == ["a", "b", "c"]
    assert not pool.available(chain[0]) and not pool.available(chain[1]) and pool.available(chain[2])


def test_resting_endpoint_is_skipped_on_the_next_call(fake):
    chain = [ep("groq:a"), ep("mistral:b")]
    c = fake([_rate_limit("tokens per day: try again in 30m0s"), '{"ok": true}', '{"ok": true}'], fast=chain)
    seen = []
    orig = c._create
    c.chat.completions.create = lambda **kw: (seen.append(kw["model"]), orig(**kw))[1]
    _call()
    _call()
    assert seen == ["a", "b", "b"]  # the capped one isn't retried until it resets


def test_needs_credits_and_unknown_model_park_the_endpoint(fake):
    chain = [ep("ollama_cloud:x"), ep("openrouter:y"), ep("groq:z")]
    fake([_status(402, "Add usage credits"), _status(404, "model not found"), '{"ok": true}'], fast=chain)
    assert _call() == Out(ok=True)
    assert not pool.available(chain[0]) and not pool.available(chain[1])


def test_json_mode_rejection_retries_without_response_format(fake):
    from openai import BadRequestError

    req = httpx.Request("POST", "https://x")
    err = BadRequestError("response_format is not supported for this model", response=httpx.Response(400, request=req), body=None)
    chain = [ep("gemini:g")]
    c = fake([err, '{"ok": true}'], fast=chain)
    kinds = []
    orig = c._create
    c.chat.completions.create = lambda **kw: (kinds.append("response_format" in kw), orig(**kw))[1]
    assert _call() == Out(ok=True) and kinds == [True, False] and chain[0].json_mode is False


def test_chain_uses_only_providers_with_keys(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    pool.reset()
    for k, v in {"llm_api_key": "", "llm_provider": "groq", "groq_api_key": "g", "mistral_api_key": "m", "gemini_api_key": "",
                 "openrouter_api_key": "", "ollama_api_key": "", "ollama_local": False, "llm_strong": "", "llm_fast": "",
                 "llm_strong_chain": "", "llm_fast_chain": ""}.items():
        monkeypatch.setattr(s, k, v)
    assert [e.name for e in pool.chain("strong")] == ["groq:openai/gpt-oss-120b", "mistral:mistral-medium-latest",
                                                      "groq:qwen/qwen3.8-27b"]
    monkeypatch.setattr(s, "llm_fast_chain", "mistral:mistral-small-latest,bogus,gemini:gemini-flash-lite-latest")
    assert [e.name for e in pool.chain("fast")] == ["mistral:mistral-small-latest"]  # gemini has no key; bogus ignored
    pool.reset()


def test_openrouter_free_models_are_discovered_and_ranked(monkeypatch):
    import time as _t

    pool._OR_CACHE.update(at=_t.time(), models=[
        {"id": "liquid/lfm-3-1.7b:free", "supported_parameters": ["response_format"], "context_length": 262144},
        {"id": "google/gemma-4-31b-it:free", "supported_parameters": ["response_format"], "context_length": 262144},
        {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "supported_parameters": [], "context_length": 1000000},
        {"id": "google/gemma-4-26b-a4b-it:free", "supported_parameters": ["response_format"], "context_length": 262144},
        {"id": "cohere/north-mini-code:free", "supported_parameters": [], "context_length": 256000},
    ])
    strong = pool.openrouter_free_models("strong")
    fast = pool.openrouter_free_models("fast")
    assert strong == ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"]  # JSON-capable first, no tiny/code
    assert fast[0] == "google/gemma-4-26b-a4b-it:free"
    pool._OR_CACHE.update(at=0.0, models=[])


def test_too_small_filter_respects_size_boundaries():
    keep = ["google/gemma-4-31b-it:free", "qwen/qwen-32b:free", "google/gemma-4-26b-a4b-it:free"]
    drop = ["liquid/lfm-3-1.7b:free", "meta-llama/llama-3b:free", "nvidia/nemotron-nano:free", "cohere/north-mini-code:free"]
    assert not any(pool._TOO_SMALL.search(m) for m in keep)  # regression: "31b" once matched "1b"
    assert all(pool._TOO_SMALL.search(m) for m in drop)
