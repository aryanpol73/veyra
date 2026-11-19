"""LLM client control flow with a fake provider (no network)."""
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError
from pydantic import BaseModel

from app import llm


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


@pytest.fixture()
def fake(monkeypatch):
    monkeypatch.setattr(llm, "throttle", lambda *_: None)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    monkeypatch.setattr("app.db.session.log_agent_run", lambda *a, **k: 0)

    def install(script):
        c = FakeClient(script)
        monkeypatch.setattr(llm, "client", lambda: c)
        return c
    return install


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
    assert out == Out(ok=True) and seen == [llm.model_for("strong"), llm.model_for("fast")]


def test_interactive_call_fails_fast_without_fallback(fake):
    c = fake([_rate_limit("Please try again in 5m16s")])
    assert llm.complete_json(role="strong", system="s", user="u", schema=Out, kind="chat", max_wait_s=20) is None
    assert llm.LAST_RATE_LIMIT["wait_s"] == 316 and c.calls == 1


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
