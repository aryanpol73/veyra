"""Production server: API under /api, PWA static files, SPA fallback, headers, no path traversal."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>veyra shell</html>")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    (dist / "manifest.webmanifest").write_text('{"name": "Veyra"}')
    (dist / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    (tmp_path / "secret.txt").write_text("do not serve")
    monkeypatch.setenv("VEYRA_STATIC_DIR", str(dist))
    import app.server as server

    server = importlib.reload(server)
    with TestClient(server.root) as c:
        yield c


def test_api_is_mounted_under_api(client):
    assert client.get("/api/healthz").json() == {"status": "ok"}
    assert client.get("/api/competitors").status_code == 200
    assert client.get("/api/competitors").headers["cache-control"] == "no-store"


def test_static_and_spa_fallback(client):
    r = client.get("/assets/app-abc123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert client.get("/manifest.webmanifest").headers["content-type"].startswith("application/manifest+json")
    assert client.get("/sw.js").headers["cache-control"] == "no-cache"
    deep = client.get("/hypotheses")  # client-side route -> app shell
    assert deep.status_code == 200 and "veyra shell" in deep.text


def test_unknown_api_path_is_a_json_404_not_the_shell(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and "veyra shell" not in r.text


def test_security_headers(client):
    h = client.get("/").headers
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "script-src 'self'" in h["content-security-policy"]


def test_no_path_traversal(client):
    for p in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        assert "do not serve" not in client.get(p).text


def test_head_requests_and_strict_font_csp(client):
    assert client.head("/").status_code == 200 and client.head("/healthz").status_code == 200
    assert "googleapis" not in client.get("/").headers["content-security-policy"]  # fonts are self-hosted


def test_fresh_database_is_initialised_on_startup(tmp_path, monkeypatch):
    """Regression: under app.server the API is mounted, and Starlette skips mounted lifespans, so a fresh
    database had no tables ('no such table: hypotheses' on the first page load)."""
    import app.server as server
    from app.db.models import Base
    from app.db.session import engine

    Base.metadata.drop_all(engine)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    monkeypatch.setenv("VEYRA_STATIC_DIR", str(dist))
    server = importlib.reload(server)
    with TestClient(server.root) as c:
        assert c.get("/api/overview").status_code == 200
