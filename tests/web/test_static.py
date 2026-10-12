from pathlib import Path

from fastapi.testclient import TestClient

from ai_trader.web.app import create_app


def test_serves_built_frontend_and_keeps_api(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>AI Trader</title><div id=root></div>", encoding="utf-8")
    client = TestClient(create_app(dist_dir=dist))
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200 and "AI Trader" in r.text


def test_no_dist_dir_means_no_root_route(tmp_path: Path):
    client = TestClient(create_app(dist_dir=tmp_path / "missing"))
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_spa_fallback_serves_index_for_client_routes(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>AI Trader</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    client = TestClient(create_app(dist_dir=dist))
    assert client.get("/analysis").status_code == 200 and "AI Trader" in client.get("/analysis").text
    assert client.get("/dca").status_code == 200
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/nope").status_code == 404
