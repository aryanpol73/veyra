"""Single-admin authentication for self-hosted deployments.

* Enabled when VEYRA_ADMIN_PASSWORD is set (required when VEYRA_ENV=production).
* POST /auth/login checks the password in constant time and sets an HMAC-signed, HttpOnly, SameSite=Strict
  session cookie (Secure in production). No server-side session store: the cookie carries its own expiry.
* Brute force: 5 failed attempts per client IP within 15 minutes -> HTTP 429 until the window passes.
* CSRF: state-changing requests must send the X-Veyra header, which browsers never add cross-site
  (on top of SameSite=Strict).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings

COOKIE = "veyra_session"
SESSION_SECONDS = 7 * 24 * 3600
PUBLIC_PATHS = {"/auth/login", "/auth/status", "/auth/logout", "/healthz"}
CSRF_HEADER = "x-veyra"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_FAILURES, WINDOW_S = 5, 15 * 60

_dev_secret = secrets.token_hex(32)  # used only when no VEYRA_SECRET_KEY (dev): sessions reset on restart
_failures: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def enabled() -> bool:
    return bool(get_settings().admin_password)


def _secret() -> bytes:
    return (get_settings().secret_key or _dev_secret).encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(now: float | None = None) -> str:
    now = now or time.time()
    payload = _b64(json.dumps({"iat": int(now), "exp": int(now + SESSION_SECONDS)}).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def valid_token(token: str | None, now: float | None = None) -> bool:
    if not token or token.count(".") != 1:
        return False
    payload, sig = token.split(".")
    expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and float(data.get("exp", 0)) > (now or time.time())


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttled(ip: str) -> bool:
    with _lock:
        q = _failures[ip]
        while q and q[0] < time.time() - WINDOW_S:
            q.popleft()
        return len(q) >= MAX_FAILURES


def _record_failure(ip: str) -> None:
    with _lock:
        _failures[ip].append(time.time())


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        root = request.scope.get("root_path", "")  # mounted under /api in production
        if root and path.startswith(root):
            path = path[len(root):] or "/"
        if not enabled() or path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        if not valid_token(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "missing X-Veyra header"}, status_code=403)
        return await call_next(request)


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict",
                        secure=get_settings().cookie_secure, path="/")


@router.get("/status")
def status(request: Request):
    return {"enabled": enabled(), "authenticated": (not enabled()) or valid_token(request.cookies.get(COOKIE))}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    if not enabled():
        return {"ok": True, "enabled": False}
    ip = _client_ip(request)
    if _throttled(ip):
        raise HTTPException(429, "too many failed attempts; try again in 15 minutes")
    if not hmac.compare_digest(body.password.encode(), get_settings().admin_password.encode()):
        _record_failure(ip)
        raise HTTPException(401, "wrong password")
    with _lock:
        _failures.pop(ip, None)
    _set_cookie(response, make_token())
    return {"ok": True, "enabled": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/", samesite="strict", secure=get_settings().cookie_secure, httponly=True)
    return {"ok": True}
