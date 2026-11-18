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
