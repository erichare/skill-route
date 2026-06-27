from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from skillroute.catalog import Catalog
from skillroute.routing import Router
from skillroute.ui_server import backend_from_name, create_app, default_web_dist


def build_client(catalog: Catalog, dist: Path) -> TestClient:
    return TestClient(create_app(catalog_path=catalog.path, web_dist=dist))


def test_health_and_summary(indexed_catalog: Catalog, tmp_path: Path) -> None:
    client = build_client(indexed_catalog, tmp_path / "empty-dist")
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    summary = client.get("/api/catalog/summary").json()
    assert summary["skillCount"] >= 1


def test_atlas_and_skill_detail(indexed_catalog: Catalog, tmp_path: Path) -> None:
    client = build_client(indexed_catalog, tmp_path / "empty-dist")
    atlas = client.get("/api/atlas").json()
    assert atlas["nodes"]
    skill_id = atlas["nodes"][0]["id"]
    detail = client.get(f"/api/skills/{skill_id}").json()
    assert detail["id"] == skill_id


def test_skill_detail_404(indexed_catalog: Catalog, tmp_path: Path) -> None:
    client = build_client(indexed_catalog, tmp_path / "empty-dist")
    response = client.get("/api/skills/no-such-skill")
    assert response.status_code == 404


def test_traces_endpoint(indexed_catalog: Catalog, tmp_path: Path) -> None:
    Router(indexed_catalog).route("Build an MCP server", limit=3)
    client = build_client(indexed_catalog, tmp_path / "empty-dist")
    traces = client.get("/api/traces?limit=5").json()
    assert isinstance(traces, list)
    assert traces and traces[0]["request"]["request"] == "Build an MCP server"


def test_route_preview_endpoint(indexed_catalog: Catalog, tmp_path: Path) -> None:
    client = build_client(indexed_catalog, tmp_path / "empty-dist")
    response = client.post("/api/route-preview", json={"request": "Build an MCP server"})
    assert response.status_code == 200
    assert "candidates" in response.json()


def test_route_preview_rejects_unknown_backend(indexed_catalog: Catalog, tmp_path: Path) -> None:
    client = build_client(indexed_catalog, tmp_path / "empty-dist")
    response = client.post(
        "/api/route-preview", json={"request": "Build an MCP server", "backend": "bogus"}
    )
    assert response.status_code == 400


def test_spa_routes_served_when_dist_exists(indexed_catalog: Catalog, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Atlas</title>", encoding="utf-8")
    client = build_client(indexed_catalog, dist)
    assert client.get("/").status_code == 200
    assert "Atlas" in client.get("/some/spa/route").text
    assert client.get("/api/unknown").status_code == 404


def test_backend_from_name_defaults_to_local() -> None:
    assert backend_from_name(None).name == "local-token"


def test_default_web_dist_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SKILLROUTE_WEB_DIST", str(tmp_path))
    assert default_web_dist() == tmp_path.resolve()
