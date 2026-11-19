"""Auto-discovery against a fake website (no network)."""
import json

import pytest

from app.collectors import discover as disc
from app.collectors.base import FetchError

HOME = """<html><head><title>Acme Coffee | Fresh roasts</title>
<link rel="alternate" type="application/rss+xml" href="/blog/feed.xml"></head><body>
<a href="/menu">Menu</a> <a href="/pricing/">Plans & pricing</a> <a href="/pricing/enterprise">Enterprise</a>
<a href="/whats-new">What's new</a> <a href="/careers">Careers</a> <a href="https://other.com/pricing">x</a></body></html>"""
CAREERS = '<a href="https://job-boards.greenhouse.io/acmecoffee/jobs/123">Barista</a>'


@pytest.fixture()
def site(monkeypatch):
    pages = {"https://acme.example/": HOME, "https://acme.example/careers": CAREERS,
             "https://boards-api.greenhouse.io/v1/boards/acmecoffee/jobs": json.dumps({"jobs": []})}

    class Fake:
        def get(self, url, **_):
            if url not in pages:
                raise FetchError(f"HTTP 404 for {url}")
            return type("R", (), {"text": pages[url]})()
    monkeypatch.setattr(disc, "fetcher", lambda: Fake())
    return pages


def test_discovers_everything_from_the_homepage(site):
    d = disc.discover("https://www.acme.example/")
    assert d.domain == "acme.example" and d.name == "Acme Coffee"
    assert d.pricing_url == "https://acme.example/pricing/"  # shortest same-site pricing link, not other.com
    assert "https://acme.example/whats-new" in d.product_urls
    assert d.feed_urls == ["https://acme.example/blog/feed.xml"]
    assert (d.careers_provider, d.careers_token) == ("greenhouse", "acmecoffee")  # found via the careers page, verified


def test_unreachable_site_degrades_to_manual(monkeypatch):
    class Down:
        def get(self, url, **_):
            raise FetchError("robots-blocked")
    monkeypatch.setattr(disc, "fetcher", lambda: Down())
    d = disc.discover("nowhere.example")
    assert d.name == "Nowhere" and d.pricing_url is None and "by hand" in d.notes[0]


def test_slogan_title_falls_back_to_domain_label(site):
    site["https://acme.example/"] = "<title>Build faster - the platform</title>"
    assert disc.discover("acme.example").name == "Acme"


def test_discover_route_is_not_captured_by_competitor_id(site):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.get("/discover", params={"domain": "acme.example"})
        assert r.status_code == 200 and r.json()["careers_token"] == "acmecoffee"
        assert c.get("/discover", params={"domain": "not a domain"}).status_code == 422
