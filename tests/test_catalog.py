from __future__ import annotations

import json
from pathlib import Path

from skillroute.catalog import (
    DEFAULT_MAX_ROUTE_TRACES as SCHEMA_DEFAULT_TRACES,
)
from skillroute.catalog import (
    SCHEMA_VERSION,
    Catalog,
    max_route_traces,
)
from skillroute.routing import Router


def test_catalog_persists_skills_excerpts_and_relationships(indexed_catalog: Catalog) -> None:
    skill = indexed_catalog.get_skill("mcp-server-patterns")

    assert skill is not None
    assert skill.name == "mcp-server-patterns"
    assert skill.excerpts
    assert skill.relationships[0].type == "complements"

    reopened = Catalog(indexed_catalog.path)
    same_skill = reopened.get_skill(skill.id)
    assert same_skill is not None
    assert same_skill.content_hash == skill.content_hash


def test_catalog_applies_metadata_overlay(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_dir = root / "overlay-skill"
    overlay_dir = root / ".skillroute" / "overlays"
    overlay_dir.mkdir(parents=True)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: overlay-skill
description: Original description.
---

# Overlay Skill
""",
        encoding="utf-8",
    )
    (overlay_dir / "reviewed.json").write_text(
        json.dumps(
            {
                "skills": {
                    "overlay-skill": {
                        "description": "Reviewed description.",
                        "tags": ["reviewed"],
                        "relationships": {"same_domain": ["python-testing"]},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(root)
    skill = catalog.get_skill("overlay-skill")

    assert skill is not None
    assert skill.description == "Reviewed description."
    assert "reviewed" in skill.tags
    assert skill.relationships[0].type == "same_domain"

def test_backend_refs_are_saved(indexed_catalog: Catalog) -> None:
    skill = indexed_catalog.get_skill("mcp-server-patterns")
    assert skill is not None

    indexed_catalog.save_backend_ref(skill.id, "local-token", "abc", "indexed")

    assert indexed_catalog.backend_refs(skill.id)[0]["status"] == "indexed"


def test_route_traces_can_be_listed_and_loaded(indexed_catalog: Catalog) -> None:
    Router(indexed_catalog).route("Build an MCP server with tools", limit=2)

    traces = indexed_catalog.list_route_traces(limit=10)
    assert traces[0]["request"]["request"] == "Build an MCP server with tools"
    assert traces[0]["backend"] == "local-token"
    assert traces[0]["top_candidate"]["name"] == "mcp-server-patterns"

    trace = indexed_catalog.get_route_trace(traces[0]["id"])
    assert trace is not None
    assert trace["response"]["candidates"][0]["name"] == "mcp-server-patterns"


def test_all_backend_refs_returns_one_query_keyed_by_skill(indexed_catalog: Catalog) -> None:
    skills = indexed_catalog.list_skills()
    indexed_catalog.save_backend_ref(skills[0].id, "astra-data-api", "ref-1", "indexed")

    all_refs = indexed_catalog.all_backend_refs()

    assert all_refs[skills[0].id]
    backends = {ref["backend"] for ref in all_refs[skills[0].id]}
    assert "astra-data-api" in backends
    assert all_refs[skills[0].id] == indexed_catalog.backend_refs(skills[0].id)


def test_schema_version_is_readable(indexed_catalog: Catalog) -> None:
    assert indexed_catalog.schema_version() == SCHEMA_VERSION


def test_route_traces_are_pruned_to_max(tmp_path: Path, monkeypatch) -> None:
    # PRUNE_INTERVAL amortizes the OFFSET subquery; force it every insert so the
    # cap can be asserted exactly.
    monkeypatch.setattr("skillroute.catalog.MAX_ROUTE_TRACES", 3)
    monkeypatch.setattr("skillroute.catalog.PRUNE_INTERVAL", 1)
    catalog = Catalog(tmp_path / "catalog.db")
    router = Router(catalog)
    for index in range(6):
        router.route(f"Build an MCP server variant {index}", limit=1)

    traces = catalog.list_route_traces(limit=100)
    assert len(traces) == 3


def test_route_trace_pruning_is_amortized(tmp_path: Path, monkeypatch) -> None:
    """Between prunes the table may exceed the cap -- bounded by the interval."""
    monkeypatch.setattr("skillroute.catalog.MAX_ROUTE_TRACES", 2)
    monkeypatch.setattr("skillroute.catalog.PRUNE_INTERVAL", 4)
    catalog = Catalog(tmp_path / "catalog.db")
    router = Router(catalog)
    for index in range(6):
        router.route(f"Build an MCP server variant {index}", limit=1)

    # Pruned at insert 4 (down to 2), then 5 and 6 accumulated on top.
    assert len(catalog.list_route_traces(limit=100)) == 4


def test_max_route_traces_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SKILLROUTE_MAX_TRACES", "77")
    assert max_route_traces() == 77
    # 0 means "never prune", not "keep nothing".
    monkeypatch.setenv("SKILLROUTE_MAX_TRACES", "0")
    assert max_route_traces() == 0
    monkeypatch.setenv("SKILLROUTE_MAX_TRACES", "not-a-number")
    assert max_route_traces() == SCHEMA_DEFAULT_TRACES


def test_daily_rollup_survives_trace_pruning(tmp_path: Path, monkeypatch) -> None:
    """The point of the rollup: aggregates outlive the raw rows."""
    monkeypatch.setattr("skillroute.catalog.MAX_ROUTE_TRACES", 2)
    monkeypatch.setattr("skillroute.catalog.PRUNE_INTERVAL", 1)
    catalog = Catalog(tmp_path / "catalog.db")
    router = Router(catalog)
    for index in range(5):
        router.route(f"Build an MCP server variant {index}", limit=1)

    assert len(catalog.list_route_traces(limit=100)) == 2
    with catalog._session() as connection:
        row = connection.execute(
            "SELECT SUM(route_count) AS routes FROM route_trace_daily"
        ).fetchone()
    assert row["routes"] == 5


def test_daily_rollup_histogram_counts_each_route_once(indexed_catalog: Catalog) -> None:
    """Regression: the first route of a day was counted twice.

    The INSERT seeded the bucket at 1 and the Python read-modify-write then
    incremented it again, so a single route reported two.
    """
    router = Router(indexed_catalog)
    router.route("Build an MCP server with stdio transport", limit=1)

    with indexed_catalog._session() as connection:
        row = connection.execute(
            "SELECT route_count, histogram_json FROM route_trace_daily"
        ).fetchone()
    assert row["route_count"] == 1
    assert sum(json.loads(row["histogram_json"]).values()) == 1

    router.route("Test a Python application with pytest", limit=1)
    with indexed_catalog._session() as connection:
        row = connection.execute(
            "SELECT route_count, histogram_json FROM route_trace_daily"
        ).fetchone()
    assert row["route_count"] == 2
    assert sum(json.loads(row["histogram_json"]).values()) == 2


def test_record_outcome_resolves_rank_and_rejects_unknown_uid(
    indexed_catalog: Catalog,
) -> None:
    catalog = indexed_catalog
    router = Router(catalog)
    response = router.route("Build an MCP server with stdio transport", limit=3)
    with catalog._session() as connection:
        trace_uid = connection.execute(
            "SELECT trace_uid FROM route_traces ORDER BY id DESC LIMIT 1"
        ).fetchone()["trace_uid"]

    second = response.candidates[1]
    result = catalog.record_outcome(trace_uid, skill_id=second.skill_id, helpful=True)
    assert result["recorded"] is True
    # Rank comes from the recorded candidates, not from the caller.
    assert result["rank_used"] == 2

    missing = catalog.record_outcome("does-not-exist", skill_id="whatever")
    assert missing["recorded"] is False


def test_index_root_skips_malformed_skill(tmp_path: Path, capsys) -> None:
    good = tmp_path / "good"
    good.mkdir()
    (good / "SKILL.md").write_text(
        "---\nname: good-skill\ndescription: A valid skill.\n---\n\n# Good\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad"
    bad.mkdir()
    # Invalid UTF-8 bytes raise UnicodeDecodeError while reading the bundle.
    (bad / "SKILL.md").write_bytes(b"---\nname: bad-skill\n---\n\xff\xfe not utf-8\n")

    catalog = Catalog(tmp_path / "catalog.db")
    skills = catalog.index_root(tmp_path)

    names = {skill.name for skill in skills}
    assert "good-skill" in names
    assert len(skills) == 1
    assert "skipping" in capsys.readouterr().err
