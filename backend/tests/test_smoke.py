
import pytest



@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok" and "provider" in body["llm"]


def test_competitor_crud_derives_sources(client):
    r = client.post("/competitors", json={
        "name": "TestCo", "domain": "testco.example", "pricing_url": "https://testco.example/pricing",
        "product_urls": [], "careers_provider": "lever", "careers_token": "testco", "news_query": "TestCo",
    })
    assert r.status_code == 201, r.text
    c = r.json()
    types = sorted(s["source_type"] for s in c["sources"])
    assert types == ["early_signal", "early_signal", "jobs", "news", "page"]
    assert client.post("/competitors", json={"name": "TestCo", "domain": "x.io"}).status_code == 409
    assert client.delete(f"/competitors/{c['id']}").status_code == 204
    assert client.get(f"/competitors/{c['id']}").status_code == 404


def test_extract_json_handles_fences_and_think():
    from app.llm import _extract_json

    assert _extract_json('```json\n{"a":1}\n```') == '{"a":1}'
    assert _extract_json('<think>hmm</think>{"a":1}') == '{"a":1}'
    assert _extract_json('Sure! {"a":1}') == '{"a":1}'
