"""Production entrypoint: one origin serves the API under /api and the built PWA everywhere else.

    uvicorn app.server:root --host 0.0.0.0 --port 8000 --proxy-headers

Run with ONE worker: the cycle/eval status and the SQLite writer live in-process.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import REPO_DIR, get_settings
from app.main import app as api
from app.main import lifespan as api_lifespan

log = logging.getLogger("veyra.server")
DIST = Path(__import__("os").environ.get("VEYRA_STATIC_DIR", REPO_DIR / "frontend" / "dist")).resolve()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "  # inline styles: React style props
       "font-src 'self' data:; img-src 'self' data: blob:; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
       "object-src 'none'")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Content-Security-Policy", CSP)
        if get_settings().cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        path = request.url.path
        if path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")  # private data: never cached by browsers or proxies
        elif path.startswith("/assets/"):
            h.setdefault("Cache-Control", "public, max-age=31536000, immutable")  # hashed filenames
        elif path in ("/sw.js", "/index.html", "/", "/manifest.webmanifest") or "." not in path.rsplit("/", 1)[-1]:
            h.setdefault("Cache-Control", "no-cache")  # always revalidate the shell and service worker
        return resp


def _check() -> None:
    s = get_settings()
    problems = s.check_production()
    if problems:
        for p in problems:
            log.critical("refusing to start: %s", p)
        sys.exit(1)
    if not (DIST / "index.html").exists():
        log.critical("frontend build not found at %s (run `npm run build` in frontend/)", DIST)
        sys.exit(1)


logging.basicConfig(level=get_settings().log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
_check()

# Starlette doesn't run a MOUNTED app's lifespan, so the root runs the API's (create tables, start the scheduler).
root = FastAPI(title="Veyra", docs_url=None, redoc_url=None, openapi_url=None, lifespan=api_lifespan)
root.add_middleware(SecurityHeaders)
root.mount("/api", api)


@api.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):  # never leak stack traces to clients
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "internal error"}, status_code=500)


@root.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
def healthz():
    return {"status": "ok"}


@root.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(path: str):
    """Static files from the build; any other path is a client-side route -> index.html."""
    candidate = (DIST / path).resolve()
    if path and candidate.is_file() and DIST in candidate.parents:
        media = "application/manifest+json" if candidate.suffix == ".webmanifest" else None
        return FileResponse(candidate, media_type=media)
    if path.startswith("api/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(DIST / "index.html", media_type="text/html")
