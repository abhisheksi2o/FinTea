import pytest
from fastapi.testclient import TestClient

from fintea.main import app

client = TestClient(app)


def test_health_and_providers():
    assert client.get("/api/health").json()["status"] == "ok"
    ps = client.get("/api/providers").json()["providers"]
    ids = {p["id"] for p in ps}
    assert {"yahoo", "sample", "bloomberg", "fmp", "alphavantage"} <= ids


def test_search_sample():
    r = client.get("/api/search", params={"q": "apple", "provider": "sample"})
    assert r.status_code == 200 and r.json()["results"][0]["symbol"] == "AAPL"


def test_build_rebuild_download():
    r = client.post("/api/models", json={"query": "MSFT", "provider": "sample", "years": 5, "verify": False})
    assert r.status_code == 200, r.text
    js = r.json()
    assert js["summary"]["symbol"] == "MSFT" and js["summary"]["implied_price"] > 0
    assert [s["name"] for s in js["sheets"]][:3] == ["Cover", "Assumptions", "Historicals"]
    assert any(c.get("f", "").startswith("=") for s in js["sheets"] for row in s["rows"] for c in row["cells"])
    mid = js["id"]
    r2 = client.post(f"/api/models/{mid}/rebuild", json={"overrides": {"terminal_growth": 0.03}, "verify": False, "include_sheets": False})
    assert r2.status_code == 200
    js2 = r2.json()
    assert js2["summary"]["implied_price"] > js["summary"]["implied_price"]
    assert "sheets" not in js2
    d = client.get(f"/api/models/{mid}/download")
    assert d.status_code == 200 and d.content[:2] == b"PK"
    assert "FinTea_MSFT" in d.headers["content-disposition"]
    bad = client.post(f"/api/models/{mid}/rebuild", json={"overrides": {"tax_rate": 5}})
    assert bad.status_code == 422
    assert client.get("/api/models/nope").status_code == 404
