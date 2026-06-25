from __future__ import annotations

from pathlib import Path

from skillroute.catalog import Catalog
from skillroute.routing import Router


class FixedBackend:
    name = "astra-data-api"

    def __init__(self, skill_id: str, score: float) -> None:
        self.skill_id = skill_id
        self.score = score

    def upsert_skills(self, skills):
        return []

    def search(self, query, skills, limit=10):
        return [{"skill_id": self.skill_id, "backend": self.name, "score": self.score}]


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


def test_router_uses_remote_backend_similarity_as_semantic_signal(indexed_catalog: Catalog) -> None:
    skill = indexed_catalog.get_skill("astra-vector-backend")
    assert skill is not None

    response = Router(indexed_catalog, backend=FixedBackend(skill.id, 0.92)).route(
        "remote-only embedding match",
        limit=3,
    )

    assert response.candidates[0].name == "astra-vector-backend"
    assert response.candidates[0].score_breakdown.semantic == 0.92
    assert response.candidates[0].confidence > 0.5
    assert any("astra-data-api" in reason for reason in response.candidates[0].reasons)


def test_router_and_search_collapse_duplicate_skill_names(tmp_path: Path) -> None:
    for root_name in ("first", "second"):
        skill_dir = tmp_path / root_name / "duplicate-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: duplicate-skill
description: Build duplicate MCP routing fixtures.
---

# Duplicate Skill

Use this skill for MCP routing.
""",
            encoding="utf-8",
        )
    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(tmp_path / "first")
    catalog.index_root(tmp_path / "second")

    response = Router(catalog).route("MCP routing duplicate skill", limit=5)
    rows = Router(catalog).search("MCP routing duplicate skill", limit=5)

    assert [candidate.name for candidate in response.candidates].count("duplicate-skill") == 1
    assert [row["name"] for row in rows].count("duplicate-skill") == 1
