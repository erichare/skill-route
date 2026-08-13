"""Schema migrations for the SkillRoute catalog.

The catalog is a plain SQLite file users keep across upgrades, so schema changes
need a forward path rather than a rebuild. Each :class:`Migration` moves the
database from ``version - 1`` to ``version``; :func:`apply_pending` runs the ones
a given database has not seen yet, in order, inside the caller's transaction.

A *fresh* catalog never runs migrations -- ``Catalog.initialize()`` creates the
current shape directly from ``CREATE_SCHEMA_SQL`` and stamps the version. That
means the DDL exists twice: once as the current shape, once as the steps to get
there. ``tests/test_migrations.py`` guards the duplication by asserting a freshly
created database and a migrated one end up with identical ``sqlite_master``.

Adding a migration means appending one entry to :data:`MIGRATIONS`, updating
``CREATE_SCHEMA_SQL``, and bumping ``catalog.SCHEMA_VERSION``. Never edit a
released migration in place -- databases in the wild have already applied it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass

# --- v2 -----------------------------------------------------------------
#
# Promotes the fields analytics needs out of the two opaque JSON blobs a v1
# trace stored, and adds the tables that make routing measurable: denormalized
# candidates, reported outcomes, multi-step plans, a daily rollup that outlives
# trace pruning, catalog snapshots for change-over-time, and the cached 2D
# projection.

V2_TRACE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("trace_uid", "TEXT"),
    ("harness_id", "TEXT"),
    ("harness_version", "TEXT"),
    ("surface", "TEXT"),
    ("request_text", "TEXT"),
    ("backend", "TEXT"),
    ("repo_path", "TEXT"),
    ("top_skill_id", "TEXT"),
    ("top_confidence", "REAL"),
    ("second_confidence", "REAL"),
    ("candidate_count", "INTEGER"),
    ("clarification_needed", "INTEGER"),
    ("plan_id", "TEXT"),
    ("subtask_index", "INTEGER"),
    ("subtask_text", "TEXT"),
    ("catalog_fingerprint", "TEXT"),
    ("weights_json", "TEXT"),
)

V2_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS route_trace_candidates (
    trace_id INTEGER NOT NULL REFERENCES route_traces(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    skill_id TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    lexical REAL NOT NULL DEFAULT 0,
    semantic REAL NOT NULL DEFAULT 0,
    repo_context REAL NOT NULL DEFAULT 0,
    graph REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (trace_id, position)
);

CREATE TABLE IF NOT EXISTS route_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_uid TEXT NOT NULL,
    skill_id TEXT,
    used INTEGER NOT NULL DEFAULT 0,
    helpful INTEGER,
    rank_used INTEGER,
    harness_id TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS route_plans (
    plan_id TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    harness_id TEXT,
    surface TEXT,
    subtask_count INTEGER NOT NULL DEFAULT 0,
    gap_count INTEGER NOT NULL DEFAULT 0,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS route_trace_daily (
    day TEXT NOT NULL,
    harness_id TEXT NOT NULL DEFAULT '',
    route_count INTEGER NOT NULL DEFAULT 0,
    clarification_count INTEGER NOT NULL DEFAULT 0,
    confidence_sum REAL NOT NULL DEFAULT 0,
    confidence_min REAL,
    confidence_max REAL,
    histogram_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (day, harness_id)
);

CREATE TABLE IF NOT EXISTS catalog_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    label TEXT,
    skill_count INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skill_projection (
    fingerprint TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    method TEXT NOT NULL DEFAULT 'hashed-pca',
    PRIMARY KEY (fingerprint, skill_id)
);
"""

V2_INDEXES_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_traces_uid ON route_traces(trace_uid);
CREATE INDEX IF NOT EXISTS idx_traces_created ON route_traces(created_at);
CREATE INDEX IF NOT EXISTS idx_traces_harness_created
    ON route_traces(harness_id, created_at);
CREATE INDEX IF NOT EXISTS idx_traces_top_skill ON route_traces(top_skill_id);
CREATE INDEX IF NOT EXISTS idx_traces_plan ON route_traces(plan_id, subtask_index);
CREATE INDEX IF NOT EXISTS idx_trace_candidates_skill
    ON route_trace_candidates(skill_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_uid ON route_outcomes(trace_uid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_label
    ON catalog_snapshots(fingerprint, label);
"""


class CatalogVersionError(RuntimeError):
    """Raised when a catalog was written by a newer SkillRoute than this one."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def migrate_v2(connection: sqlite3.Connection) -> None:
    for column, column_type in V2_TRACE_COLUMNS:
        _add_column(connection, "route_traces", column, column_type)
    connection.executescript(V2_TABLES_SQL)
    _backfill_v2_traces(connection)
    # Indexes come last: idx_traces_uid is UNIQUE, and every pre-existing row
    # needs its trace_uid populated by the backfill before it can be enforced.
    connection.executescript(V2_INDEXES_SQL)


def _backfill_v2_traces(connection: sqlite3.Connection) -> None:
    """Unpack v1 JSON blobs into the promoted columns and candidate rows.

    Pre-0.2 traces stored everything as two opaque JSON documents. Analytics
    queries columns, so existing history is unpacked once here instead of being
    discarded. ``harness_id`` stays NULL for these rows -- v1 never recorded a
    caller -- and readers render that as "unknown".

    Best effort per row: a trace whose JSON is unreadable is skipped with a
    warning rather than failing the upgrade and locking the user out of their
    catalog.
    """
    rows = connection.execute(
        "SELECT id, request_json, response_json FROM route_traces ORDER BY id"
    ).fetchall()
    skipped = 0
    for row in rows:
        try:
            request = json.loads(row["request_json"])
            response = json.loads(row["response_json"])
        except (json.JSONDecodeError, TypeError, ValueError):
            skipped += 1
            continue
        if not isinstance(request, dict) or not isinstance(response, dict):
            skipped += 1
            continue

        raw_candidates = response.get("candidates")
        candidates = [item for item in raw_candidates if isinstance(item, dict)] if (
            isinstance(raw_candidates, list)
        ) else []
        confidences = [_as_float(item.get("confidence")) for item in candidates]
        connection.execute(
            """
            UPDATE route_traces
            SET trace_uid = ?,
                surface = ?,
                request_text = ?,
                backend = ?,
                repo_path = ?,
                top_skill_id = ?,
                top_confidence = ?,
                second_confidence = ?,
                candidate_count = ?,
                clarification_needed = ?
            WHERE id = ?
            """,
            (
                uuid.uuid4().hex,
                "legacy",
                _as_text(request.get("request") or response.get("request")),
                _as_text(request.get("backend")),
                _as_text(request.get("repo")),
                _as_text(candidates[0].get("skill_id")) if candidates else None,
                confidences[0] if confidences else None,
                confidences[1] if len(confidences) > 1 else None,
                len(candidates),
                int(bool(response.get("clarification_needed"))),
                row["id"],
            ),
        )
        for position, candidate in enumerate(candidates, start=1):
            raw_breakdown = candidate.get("score_breakdown")
            breakdown = raw_breakdown if isinstance(raw_breakdown, dict) else {}
            connection.execute(
                """
                INSERT OR REPLACE INTO route_trace_candidates (
                    trace_id, position, skill_id, content_hash, name, confidence,
                    lexical, semantic, repo_context, graph, total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    position,
                    _as_text(candidate.get("skill_id")) or "",
                    _as_text(candidate.get("content_hash")) or "",
                    _as_text(candidate.get("name")) or "",
                    _as_float(candidate.get("confidence")),
                    _as_float(breakdown.get("lexical")),
                    _as_float(breakdown.get("semantic")),
                    _as_float(breakdown.get("repo_context")),
                    _as_float(breakdown.get("graph")),
                    _as_float(breakdown.get("total")),
                ),
            )
    if skipped:
        print(
            f"skillroute: skipped {skipped} unreadable route trace(s) during schema upgrade",
            file=sys.stderr,
        )


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _as_text(value: object) -> str | None:
    return None if value is None else str(value)


def _add_column(
    connection: sqlite3.Connection, table: str, column: str, column_type: str
) -> None:
    """Add a column, tolerating one that is already present.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``, and a partially-upgraded
    database (a migration interrupted before its version was stamped) would
    otherwise be unrecoverable. Any other OperationalError is a real problem and
    propagates.
    """
    try:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=2, name="trace_analytics", apply=migrate_v2),
)


def detect_schema_version(connection: sqlite3.Connection) -> int:
    """Return the on-disk schema version.

    Three cases matter, and the middle one is why this cannot just read the
    version table: a v1 catalog predates nothing, but a database with no tables
    at all is *fresh* rather than v0-needing-migration.
    """
    if not _table_exists(connection, "skills"):
        return 0
    if not _table_exists(connection, "schema_version"):
        # Tables but no version row: a v1 catalog from before versioning landed.
        return 1
    row = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
    version = row[0] if row else None
    return int(version) if version is not None else 1


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def pending_migrations(current: int) -> tuple[Migration, ...]:
    return tuple(migration for migration in MIGRATIONS if migration.version > current)


def apply_pending(connection: sqlite3.Connection, current: int) -> int:
    """Apply every migration newer than ``current`` and return the new version.

    Runs inside the caller's transaction, so a failure part-way leaves the
    database at its original version rather than half-upgraded.
    """
    version = current
    for migration in pending_migrations(current):
        migration.apply(connection)
        version = migration.version
    return version
