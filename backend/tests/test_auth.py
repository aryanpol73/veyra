"""Admin-password auth: sessions, tampering, expiry, throttling, CSRF header, production start checks."""
import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings, get_settings

PW = "correct horse battery staple"


@pytest.fixture()
def client(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "admin_password", PW)
    monkeypatch.setattr(s, "secret_key", "x" * 40)
    auth._failures.clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    auth._failures.clear()


def test_everything_requires_login(client):
    assert client.get("/competitors").status_code == 401
    assert client.get("/health").status_code == 401
    assert client.get("/healthz").status_code == 200  # docker healthcheck stays public
    assert client.get("/auth/status").json() == {"enabled": True, "authenticated": False}


def test_login_sets_httponly_strict_cookie_and_unlocks(client):
    assert client.post("/auth/login", json={"password": "nope"}).status_code == 401
    r = client.post("/auth/login", json={"password": PW})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/competitors").status_code == 200
    assert client.get("/auth/status").json()["authenticated"] is True


def test_writes_need_the_csrf_header(client):
    client.post("/auth/login", json={"password": PW})
    body = {"name": f"CsrfCo-{time.time_ns()}", "domain": "csrf.example"}
    assert client.post("/competitors", json=body).status_code == 403
    assert client.post("/competitors", json=body, headers={"X-Veyra": "1"}).status_code == 201


def test_tampered_and_expired_tokens_are_rejected(client):
    good = auth.make_token()
    payload, sig = good.split(".")
    assert auth.valid_token(good)
    assert not auth.valid_token(payload + "." + sig[:-2] + "AA")
    assert not auth.valid_token(auth._b64(b'{"exp": 9999999999}') + "." + sig)
    assert not auth.valid_token(auth.make_token(now=time.time() - auth.SESSION_SECONDS - 5))
    assert not auth.valid_token("garbage") and not auth.valid_token(None)


def test_brute_force_is_throttled(client):
    for _ in range(auth.MAX_FAILURES):
        client.post("/auth/login", json={"password": "wrong"})
    assert client.post("/auth/login", json={"password": PW}).status_code == 429


def test_logout_clears_the_session(client):
    client.post("/auth/login", json={"password": PW})
    client.post("/auth/logout", headers={"X-Veyra": "1"})
    assert client.get("/competitors").status_code == 401


def test_production_refuses_weak_config():
    s = Settings(VEYRA_ENV="production", VEYRA_ADMIN_PASSWORD="short", VEYRA_SECRET_KEY="")
    assert len(s.check_production()) == 2
    ok = Settings(VEYRA_ENV="production", VEYRA_ADMIN_PASSWORD="a-long-password", VEYRA_SECRET_KEY="k" * 40)
    assert ok.check_production() == [] and ok.cookie_secure is True
    assert Settings(VEYRA_ENV="production", VEYRA_COOKIE_SECURE="false").cookie_secure is False
