from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillroute.atlas import build_atlas_payload, primary_domain, route_preview_payload, skill_detail_payload
from skillroute.catalog import Catalog
from skillroute.ui_server import create_app, run_ui


def test_atlas_resolves_relationships_and_reports_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    source = root / "source-skill"
    target = root / "target-skill"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        """---
name: source-skill
description: Source workflow skill.
requires: [target-skill]
conflicts: [missing-skill]
---

# Source Skill
""",
        encoding="utf-8",
    )
    (target / "SKILL.md").write_text(
        """---
name: target-skill
description: Target workflow skill.
tags: [review]
---

# Target Skill
""",
        encoding="utf-8",
    )
    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(root)

    payload = build_atlas_payload(catalog)

    assert payload["catalog"]["skillCount"] == 2
    assert payload["catalog"]["relationshipCount"] == 1
    assert payload["catalog"]["unresolvedRelationshipCount"] == 1
    assert payload["edges"][0]["sourceName"] == "source-skill"
    assert payload["edges"][0]["targetName"] == "target-skill"
    assert payload["warnings"][0]["target"] == "missing-skill"


def test_primary_domain_falls_back_to_root_name(tmp_path: Path) -> None:
    root = tmp_path / "plain-root"
    skill_dir = root / "plainthing"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: plainthing
description: Plain workflow.
---

# Plain Thing
""",
        encoding="utf-8",
    )
    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(root)
    skill = catalog.get_skill("plainthing")

    assert skill is not None
    assert primary_domain(skill) == "plain-root"


def test_skill_detail_includes_incoming_and_backend_refs(indexed_catalog: Catalog) -> None:
    skill = indexed_catalog.get_skill("mcp-server-patterns")
    assert skill is not None
    indexed_catalog.save_backend_ref(skill.id, "local-token", "abc", "indexed")

    payload = skill_detail_payload(indexed_catalog, skill.id)

    assert payload is not None
    assert payload["name"] == "mcp-server-patterns"
    assert payload["backend_refs"][0]["status"] == "indexed"
    assert payload["unresolved_relationships"][0]["target"] == "python-patterns"


def test_route_preview_does_not_record_trace(indexed_catalog: Catalog) -> None:
    payload = route_preview_payload(indexed_catalog, request="Build an MCP server", limit=2)

    assert payload["candidates"][0]["name"] == "mcp-server-patterns"
    assert indexed_catalog.list_route_traces(limit=10) == []


def test_ui_api_serves_atlas_and_errors(indexed_catalog: Catalog, tmp_path: Path) -> None:
    app = create_app(catalog_path=indexed_catalog.path, web_dist=tmp_path / "missing-dist")
    client = TestClient(app)

    health = client.get("/api/health")
    atlas = client.get("/api/atlas")
    missing_skill = client.get("/api/skills/not-a-skill")
    invalid_route = client.post("/api/route-preview", json={"request": "Build", "backend": "nope"})

    assert health.status_code == 200
    assert health.json()["webDistExists"] is False
    assert atlas.status_code == 200
    assert atlas.json()["catalog"]["skillCount"] == 3
    assert missing_skill.status_code == 404
    assert invalid_route.status_code == 400


def test_ui_command_reports_missing_web_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skillroute.ui_server.default_web_dist", lambda: tmp_path / "missing-dist")

    with pytest.raises(SystemExit) as exc_info:
        run_ui(catalog_path=tmp_path / "catalog.db", open_browser=False)

    assert "npm --prefix web install && npm --prefix web run build" in str(exc_info.value)
