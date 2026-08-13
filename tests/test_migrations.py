from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from skillroute.catalog import SCHEMA_VERSION, Catalog
from skillroute.migrations import CatalogVersionError, detect_schema_version

V1_SCHEMA = Path(__file__).parent / "fixtures" / "schema_v1.sql"


def build_v1_catalog(path: Path, *, traces: list[tuple[dict, dict]] | None = None) -> None:
    """Create a database in the exact shape v0.1.0 shipped."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(V1_SCHEMA.read_text(encoding="utf-8"))
        for request, response in traces or []:
            connection.execute(
                "INSERT INTO route_traces (request_json, response_json) VALUES (?, ?)",
                (json.dumps(request, sort_keys=True), json.dumps(response, sort_keys=True)),
            )
        connection.commit()
    finally:
        connection.close()


def sample_trace(request_text: str, *, clarification: bool = False) -> tuple[dict, dict]:
    request = {"request": request_text, "repo": None, "limit": 5, "backend": "local-token"}
    response = {
        "request": request_text,
        "repo_context": {},
        "candidates": [
            {
                "skill_id": "mcp-server-patterns-abc123",
                "name": "mcp-server-patterns",
                "description": "Build MCP servers.",
                "confidence": 0.42,
                "content_hash": "hash-a",
                "reasons": [],
                "evidence": [],
                "score_breakdown": {
                    "lexical": 0.30,
                    "semantic": 0.10,
                    "repo_context": 0.05,
                    "graph": 0.02,
                    "total": 0.47,
                },
                "suggested_position": 1,
            },
            {
                "skill_id": "python-testing-def456",
                "name": "python-testing",
                "description": "Test Python apps.",
                "confidence": 0.13,
                "content_hash": "hash-b",
                "reasons": [],
                "evidence": [],
                "score_breakdown": {
                    "lexical": 0.10,
                    "semantic": 0.02,
                    "repo_context": 0.0,
                    "graph": 0.01,
                    "total": 0.13,
                },
                "suggested_position": 2,
            },
        ],
        "suggested_order": ["mcp-server-patterns-abc123", "python-testing-def456"],
        "clarification_needed": clarification,
        "clarification_questions": ["Which one?"] if clarification else [],
    }
    return request, response


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def test_detects_fresh_v1_and_current_databases(tmp_path: Path) -> None:
    empty = sqlite3.connect(tmp_path / "empty.db")
    assert detect_schema_version(empty) == 0
    empty.close()

    build_v1_catalog(tmp_path / "v1.db")
    v1 = sqlite3.connect(tmp_path / "v1.db")
    assert detect_schema_version(v1) == 1
    v1.close()


def test_v1_catalog_without_version_table_reads_as_v1(tmp_path: Path) -> None:
    """Tables but no version row means a catalog from before versioning landed."""
    path = tmp_path / "unversioned.db"
    build_v1_catalog(path)
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE schema_version")
    connection.commit()
    assert detect_schema_version(connection) == 1
    connection.close()


def test_migrates_v1_to_current_and_backfills_traces(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    build_v1_catalog(
        path,
        traces=[
            sample_trace("Build an MCP server"),
            sample_trace("Ambiguous request", clarification=True),
        ],
    )

    Catalog(path).initialize()

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        assert connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == (
            SCHEMA_VERSION
        )
        traces = connection.execute(
            "SELECT * FROM route_traces ORDER BY id"
        ).fetchall()
        assert len(traces) == 2

        first = traces[0]
        assert first["trace_uid"]
        assert first["request_text"] == "Build an MCP server"
        assert first["backend"] == "local-token"
        assert first["top_skill_id"] == "mcp-server-patterns-abc123"
        assert first["top_confidence"] == pytest.approx(0.42)
        assert first["second_confidence"] == pytest.approx(0.13)
        assert first["candidate_count"] == 2
        assert first["clarification_needed"] == 0
        # v1 never recorded a caller, so attribution is genuinely unknown.
        assert first["harness_id"] is None
        assert traces[1]["clarification_needed"] == 1

        # Every trace got a distinct uid.
        assert len({row["trace_uid"] for row in traces}) == 2

        candidates = connection.execute(
            """
            SELECT * FROM route_trace_candidates
            WHERE trace_id = ? ORDER BY position
            """,
            (first["id"],),
        ).fetchall()
        assert [row["position"] for row in candidates] == [1, 2]
        assert candidates[0]["skill_id"] == "mcp-server-patterns-abc123"
        assert candidates[0]["content_hash"] == "hash-a"
        assert candidates[0]["lexical"] == pytest.approx(0.30)
        assert candidates[1]["name"] == "python-testing"
    finally:
        connection.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    build_v1_catalog(path, traces=[sample_trace("Build an MCP server")])

    Catalog(path).initialize()
    # A second Catalog object re-opens the file and must be a no-op.
    Catalog(path).initialize()

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM route_traces").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM route_trace_candidates").fetchone()[0] == 2
        )
    finally:
        connection.close()


def test_migration_writes_a_backup(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    build_v1_catalog(path, traces=[sample_trace("Build an MCP server")])

    Catalog(path).initialize()

    backups = list(tmp_path.glob("catalog.db.bak-v1-*"))
    assert len(backups) == 1
    # The backup is still readable as the original v1 database.
    connection = sqlite3.connect(backups[0])
    try:
        assert "route_trace_candidates" not in table_names(connection)
    finally:
        connection.close()


def test_unreadable_trace_is_skipped_not_fatal(tmp_path: Path, capsys) -> None:
    path = tmp_path / "catalog.db"
    build_v1_catalog(path, traces=[sample_trace("Good trace")])
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO route_traces (request_json, response_json) VALUES (?, ?)",
        ("{not json", "{also not json"),
    )
    connection.commit()
    connection.close()

    Catalog(path).initialize()

    assert "skipped 1 unreadable route trace" in capsys.readouterr().err
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT trace_uid FROM route_traces ORDER BY id"
        ).fetchall()
        # The good row migrated; the corrupt one survived without a uid.
        assert rows[0]["trace_uid"]
        assert rows[1]["trace_uid"] is None
    finally:
        connection.close()


def test_refuses_a_newer_catalog(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    build_v1_catalog(path)
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM schema_version")
    connection.execute("INSERT INTO schema_version(version) VALUES (99)")
    connection.commit()
    connection.close()

    with pytest.raises(CatalogVersionError, match="schema v99"):
        Catalog(path).initialize()


def test_fresh_and_migrated_schemas_match(tmp_path: Path) -> None:
    """The DDL exists twice -- as the current shape and as the steps to reach it.

    This is the guard that keeps the two from drifting apart.
    """
    fresh_path = tmp_path / "fresh.db"
    Catalog(fresh_path).initialize()

    migrated_path = tmp_path / "migrated.db"
    build_v1_catalog(migrated_path)
    Catalog(migrated_path).initialize()

    fresh = sqlite3.connect(fresh_path)
    migrated = sqlite3.connect(migrated_path)
    try:
        assert table_names(fresh) == table_names(migrated)
        for table in sorted(table_names(fresh)):
            assert column_names(fresh, table) == column_names(migrated, table), table

        def index_names(connection: sqlite3.Connection) -> set[str]:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            return {row[0] for row in rows}

        assert index_names(fresh) == index_names(migrated)
    finally:
        fresh.close()
        migrated.close()


def test_user_version_pragma_mirrors_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    Catalog(path).initialize()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        connection.close()
