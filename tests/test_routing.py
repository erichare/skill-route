from __future__ import annotations

from pathlib import Path

from skillroute.catalog import Catalog
from skillroute.routing import Router


def test_router_ranks_expected_skill_for_mcp_request(indexed_catalog: Catalog, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text("{}", encoding="utf-8")
    response = Router(indexed_catalog).route(
        "Build a TypeScript MCP stdio server with registered tools",
        repo=repo,
    )

    assert response.candidates[0].name == "mcp-server-patterns"
    assert response.candidates[0].evidence
    assert not response.clarification_needed
    assert response.repo_context["languages"] == ["javascript"]


def test_router_asks_for_clarification_when_no_candidate(indexed_catalog: Catalog) -> None:
    response = Router(indexed_catalog).route("purple lunch calendar weather", limit=3)

    assert response.clarification_needed
    assert response.clarification_questions


def test_search_returns_evidence(indexed_catalog: Catalog) -> None:
    rows = Router(indexed_catalog).search("Astra vector LangChain backend")

    assert rows[0]["name"] == "astra-vector-backend"
    assert rows[0]["evidence"]

