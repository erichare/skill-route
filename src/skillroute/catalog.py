from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from skillroute.attribution import Attribution
from skillroute.backends import LocalTokenBackend
from skillroute.migrations import (
    V2_INDEXES_SQL,
    V2_TABLES_SQL,
    V2_TRACE_COLUMNS,
    CatalogVersionError,
    apply_pending,
    detect_schema_version,
)
from skillroute.models import (
    RouteResponse,
    SkillExcerpt,
    SkillRecord,
    SkillReference,
    SkillRelationship,
    to_jsonable,
)
from skillroute.overlays import load_overlays, overlay_for_skill
from skillroute.parser import discover_skill_files, parse_frontmatter, parse_skill_bundle
from skillroute.spec import SkillSpecReport, summarize_reports, validate_skill_file

SCHEMA_VERSION = 2

# Raw traces are capped; the daily rollup is not. v0.1 kept 1000 rows, which is
# a few days of one active harness -- far too short a horizon for "clarification
# rate over time" to mean anything. Aggregates in route_trace_daily survive
# pruning, so the raw cap only bounds how far back full detail is available.
DEFAULT_MAX_ROUTE_TRACES = 20_000
# Module-level so tests (and anyone embedding SkillRoute) can override it;
# max_route_traces() layers the SKILLROUTE_MAX_TRACES env var on top.
MAX_ROUTE_TRACES = DEFAULT_MAX_ROUTE_TRACES

# Pruning runs an OFFSET subquery that is no longer free at 20k rows, so amortize
# it instead of paying on every single insert.
PRUNE_INTERVAL = 64

# The v1 core. A fresh catalog gets this plus the v2 additions imported from
# migrations, so the "create current shape" and "migrate up to it" paths share
# the v2 DDL verbatim instead of drifting apart. tests/test_migrations.py asserts
# a fresh database and a migrated one end up structurally identical.
BASE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    skill_path TEXT NOT NULL,
    bundle_path TEXT NOT NULL,
    root_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    facets_json TEXT NOT NULL,
    references_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS excerpts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS relationships (
    from_skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    to_ref TEXT NOT NULL,
    PRIMARY KEY (from_skill_id, type, to_ref)
);

CREATE TABLE IF NOT EXISTS backend_index_refs (
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    backend TEXT NOT NULL,
    ref TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (skill_id, backend)
);

CREATE TABLE IF NOT EXISTS route_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP{v2_trace_columns}
);

CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
CREATE INDEX IF NOT EXISTS idx_skills_root ON skills(root_path);
CREATE INDEX IF NOT EXISTS idx_excerpts_skill ON excerpts(skill_id);
CREATE INDEX IF NOT EXISTS idx_backend_refs_skill ON backend_index_refs(skill_id);
"""

CREATE_SCHEMA_SQL = (
    BASE_SCHEMA_SQL.format(
        v2_trace_columns="".join(
            f",\n    {column} {column_type}" for column, column_type in V2_TRACE_COLUMNS
        )
    )
    + V2_TABLES_SQL
    + V2_INDEXES_SQL
)


def max_route_traces() -> int:
    """Raw-trace retention. ``SKILLROUTE_MAX_TRACES=0`` disables pruning."""
    configured = os.environ.get("SKILLROUTE_MAX_TRACES")
    if configured:
        try:
            return max(0, int(configured))
        except ValueError:
            print(
                f"skillroute: ignoring invalid SKILLROUTE_MAX_TRACES={configured!r}",
                file=sys.stderr,
            )
    return MAX_ROUTE_TRACES


def user_catalog_path() -> Path:
    """The catalog a machine-wide install uses: ``~/.skillroute/catalog.db``.

    Matches where the installer already keeps its checkout (``~/.skillroute/``),
    so SkillRoute owns one directory in $HOME rather than two.
    """
    return (Path.home() / ".skillroute" / "catalog.db").resolve()


def default_catalog_path(base: Path | None = None) -> Path:
    """Where to read or write the catalog when the caller did not say.

    v0.1 and v0.2 resolved this against the working directory, which was fine
    when a git checkout was the only way to run SkillRoute. Since 0.2 publishes
    to PyPI and npm, `uvx skillroute` has no checkout at all and a
    checkout-relative default names a directory that does not exist.

    So the default is now user-scoped -- except that an *existing* project
    catalog still wins. Anyone who indexed into their checkout under 0.1 or 0.2
    keeps using it; switching them to an empty catalog under $HOME would look
    exactly like their library disappearing.
    """
    configured = os.environ.get("SKILLROUTE_CATALOG_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    project = ((base or Path.cwd()) / ".skillroute" / "catalog.db").resolve()
    if project.exists():
        return project
    return user_catalog_path()


def _report_spec_summary(root: Path, reports: list[SkillSpecReport], *, spec_strict: bool) -> None:
    """Surface Agent Skills spec findings from an indexing run.

    Errors are named individually (a non-compliant bundle is not portable, so
    it should never pass silently); warnings are counted only, with
    `skillroute validate` as the tool for working through them. Everything
    goes to stderr so stdout stays reserved for the command's actual output.
    """
    summary = summarize_reports(reports)
    if not summary["errors"] and not summary["warnings"]:
        return
    shown = 0
    for report in reports:
        for finding in report.errors:
            if shown >= 5:
                break
            print(
                f"skillroute: spec error[{finding.field}] {report.skill_path}: "
                f"{finding.message}",
                file=sys.stderr,
            )
            shown += 1
        if shown >= 5:
            break
    remaining = summary["errors"] - shown
    if remaining > 0:
        print(f"skillroute: ... and {remaining} more spec errors", file=sys.stderr)
    action = "non-compliant bundles refused" if spec_strict else "bundles with errors indexed"
    print(
        f"skillroute: spec check on {root}: {summary['errors']} errors, "
        f"{summary['warnings']} warnings across {summary['bundles']} bundles "
        f"({action}; run `skillroute validate {root}` for details)",
        file=sys.stderr,
    )


class Catalog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else default_catalog_path()
        self._initialized = False

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # WAL lets readers (the UI server) run concurrently with a writer (CLI
        # index), and a busy timeout avoids immediate "database is locked".
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create, migrate, or accept the catalog on disk.

        Three paths, decided by :func:`detect_schema_version`:

        * fresh (no tables) -- create the current shape directly and stamp it;
        * older -- back the file up, then apply migrations in order;
        * newer -- refuse, rather than corrupt a catalog this build cannot read.

        ``BEGIN IMMEDIATE`` takes the write lock up front so a concurrent
        ``skillroute index`` and UI server cannot both try to migrate. The
        existing ``busy_timeout`` makes the loser wait instead of failing.
        """
        if self._initialized:
            return
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = detect_schema_version(connection)
            if current > SCHEMA_VERSION:
                raise CatalogVersionError(
                    f"Catalog {self.path} is schema v{current}, but this SkillRoute "
                    f"understands up to v{SCHEMA_VERSION}. Upgrade SkillRoute, or point "
                    "--catalog / SKILLROUTE_CATALOG_PATH at a different file."
                )
            if current == 0:
                connection.executescript(CREATE_SCHEMA_SQL)
            elif current < SCHEMA_VERSION:
                self._backup_before_migration(current)
                current = apply_pending(connection, current)
            self._stamp_version(connection, SCHEMA_VERSION)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        self._initialized = True

    def _backup_before_migration(self, from_version: int) -> Path:
        """Copy the catalog aside before altering it.

        Same reasoning and naming shape as ``merge_json_config``'s config
        backups: a schema upgrade is the highest-blast-radius thing SkillRoute
        does to a file the user owns, so leave them a way back.
        """
        timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
        backup_path = self.path.with_name(f"{self.path.name}.bak-v{from_version}-{timestamp}")
        shutil.copy2(self.path, backup_path)
        print(f"skillroute: backed up catalog to {backup_path}", file=sys.stderr)
        return backup_path

    @staticmethod
    def _stamp_version(connection: sqlite3.Connection, version: int) -> None:
        # Replace rather than append: the v1 code only inserted when the table
        # was empty, which is why reads had to ORDER BY version DESC.
        connection.execute("DELETE FROM schema_version")
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
        # Mirrored so external tooling can read the version without a query.
        connection.execute(f"PRAGMA user_version = {int(version)}")

    def schema_version(self) -> int | None:
        self.initialize()
        with self._session() as connection:
            row = connection.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return int(row[0]) if row else None

    def index_root(self, root: Path | str, *, spec_strict: bool = False) -> list[SkillRecord]:
        root_path = Path(root).expanduser().resolve()
        overlays = load_overlays(root_path)
        skills: list[SkillRecord] = []
        spec_reports: list[SkillSpecReport] = []
        for skill_file in discover_skill_files(root_path):
            try:
                # Every bundle is checked against the Agent Skills spec as it
                # is indexed. Errors are reported (and, with spec_strict, the
                # bundle is refused) because a non-compliant skill is not
                # portable across clients; warnings are summarized only --
                # `skillroute validate` is the tool for working through them.
                report = validate_skill_file(skill_file)
                spec_reports.append(report)
                if spec_strict and report.errors:
                    print(
                        f"skillroute: refusing spec-noncompliant bundle {skill_file} "
                        f"({len(report.errors)} errors)",
                        file=sys.stderr,
                    )
                    continue
                raw_text = skill_file.read_text(encoding="utf-8")
                metadata, _ = parse_frontmatter(raw_text)
                name = str(metadata.get("name") or skill_file.parent.name)
                overlay = overlay_for_skill(overlays, skill_file, name, root=root_path)
                skills.append(parse_skill_bundle(skill_file, root=root_path, overlay=overlay))
            except (OSError, ValueError, KeyError) as exc:
                # Isolate failures so one malformed SKILL.md cannot abort the run.
                print(f"skillroute: skipping {skill_file}: {exc}", file=sys.stderr)
        _report_spec_summary(root_path, spec_reports, spec_strict=spec_strict)
        self.replace_root(root_path, skills)
        for backend_ref in LocalTokenBackend().upsert_skills(skills):
            self.save_backend_ref(
                backend_ref["skill_id"],
                backend_ref["backend"],
                backend_ref["ref"],
                backend_ref.get("status", "indexed"),
            )
        return skills

    def replace_root(self, root: Path, skills: Iterable[SkillRecord]) -> None:
        self.initialize()
        root_path = str(root.resolve())
        with self._session() as connection:
            # ON DELETE CASCADE (with foreign_keys ON) removes the dependent
            # excerpts, relationships, and backend refs in one statement.
            connection.execute("DELETE FROM skills WHERE root_path = ?", (root_path,))
            for skill in skills:
                self._upsert_skill(connection, skill)

    def upsert_skill(self, skill: SkillRecord) -> None:
        self.initialize()
        with self._session() as connection:
            self._upsert_skill(connection, skill)

    def _upsert_skill(self, connection: sqlite3.Connection, skill: SkillRecord) -> None:
        connection.execute(
            """
            INSERT INTO skills (
                id, name, description, skill_path, bundle_path, root_path, content_hash,
                metadata_json, tags_json, facets_json, references_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                skill_path = excluded.skill_path,
                bundle_path = excluded.bundle_path,
                root_path = excluded.root_path,
                content_hash = excluded.content_hash,
                metadata_json = excluded.metadata_json,
                tags_json = excluded.tags_json,
                facets_json = excluded.facets_json,
                references_json = excluded.references_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                skill.id,
                skill.name,
                skill.description,
                skill.skill_path,
                skill.bundle_path,
                skill.root_path,
                skill.content_hash,
                json.dumps(skill.metadata, sort_keys=True),
                json.dumps(skill.tags, sort_keys=True),
                json.dumps(skill.facets, sort_keys=True),
                json.dumps(to_jsonable(skill.references), sort_keys=True),
            ),
        )
        connection.execute("DELETE FROM excerpts WHERE skill_id = ?", (skill.id,))
        connection.execute("DELETE FROM relationships WHERE from_skill_id = ?", (skill.id,))
        for excerpt in skill.excerpts:
            connection.execute(
                """
                INSERT INTO excerpts (skill_id, kind, text, source_path, start_line, end_line)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    skill.id,
                    excerpt.kind,
                    excerpt.text,
                    excerpt.source_path,
                    excerpt.start_line,
                    excerpt.end_line,
                ),
            )
        for relationship in skill.relationships:
            connection.execute(
                """
                INSERT OR REPLACE INTO relationships (from_skill_id, type, to_ref)
                VALUES (?, ?, ?)
                """,
                (skill.id, relationship.type, relationship.target),
            )

    def list_skills(self) -> list[SkillRecord]:
        self.initialize()
        with self._session() as connection:
            rows = connection.execute("SELECT * FROM skills ORDER BY name").fetchall()
            return [self._record_from_row(connection, row) for row in rows]

    def get_skill(self, skill_ref: str) -> SkillRecord | None:
        self.initialize()
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT * FROM skills
                WHERE id = ? OR name = ? OR lower(name) = lower(?)
                ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (skill_ref, skill_ref, skill_ref, skill_ref),
            ).fetchone()
            return self._record_from_row(connection, row) if row else None

    def find_by_name_or_id(self, skill_ref: str) -> SkillRecord | None:
        return self.get_skill(skill_ref)

    def record_route_trace(
        self,
        request: dict[str, Any],
        response: RouteResponse,
        *,
        attribution: Attribution | None = None,
        plan_id: str | None = None,
        subtask_index: int | None = None,
        subtask_text: str | None = None,
        catalog_fingerprint: str | None = None,
        weights: dict[str, float] | None = None,
    ) -> str:
        """Persist one routing call and return its stable ``trace_uid``.

        The JSON blobs stay (they are the full record, and the UI reads them),
        but the fields analytics groups and filters on are promoted to columns
        and to ``route_trace_candidates``. Reported outcomes reference the
        returned uid, which survives trace pruning even though the row does not.
        """
        self.initialize()
        trace_uid = uuid.uuid4().hex
        attribution = attribution or Attribution()
        harness_id = attribution.harness_id
        harness_version = attribution.harness_version
        surface = attribution.surface
        confidences = [candidate.confidence for candidate in response.candidates]
        top = response.candidates[0] if response.candidates else None
        with self._session() as connection:
            cursor = connection.execute(
                """
                INSERT INTO route_traces (
                    request_json, response_json, trace_uid, harness_id, harness_version,
                    surface, request_text, backend, repo_path, top_skill_id, top_confidence,
                    second_confidence, candidate_count, clarification_needed,
                    plan_id, subtask_index, subtask_text, catalog_fingerprint, weights_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    json.dumps(request, sort_keys=True),
                    json.dumps(to_jsonable(response), sort_keys=True),
                    trace_uid,
                    harness_id,
                    harness_version,
                    surface,
                    response.request,
                    request.get("backend"),
                    request.get("repo"),
                    top.skill_id if top else None,
                    confidences[0] if confidences else None,
                    confidences[1] if len(confidences) > 1 else None,
                    len(response.candidates),
                    int(bool(response.clarification_needed)),
                    plan_id,
                    subtask_index,
                    subtask_text,
                    catalog_fingerprint,
                    json.dumps(weights, sort_keys=True) if weights else None,
                ),
            )
            trace_id = int(cursor.lastrowid or 0)
            for position, candidate in enumerate(response.candidates, start=1):
                breakdown = candidate.score_breakdown
                connection.execute(
                    """
                    INSERT INTO route_trace_candidates (
                        trace_id, position, skill_id, content_hash, name, confidence,
                        lexical, semantic, repo_context, graph, total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace_id,
                        position,
                        candidate.skill_id,
                        candidate.content_hash,
                        candidate.name,
                        candidate.confidence,
                        breakdown.lexical,
                        breakdown.semantic,
                        breakdown.repo_context,
                        breakdown.graph,
                        breakdown.total,
                    ),
                )
            self._bump_daily_rollup(
                connection,
                harness_id=harness_id or "",
                confidence=confidences[0] if confidences else 0.0,
                clarification=bool(response.clarification_needed),
            )
            self._prune_route_traces(connection, trace_id)
        return trace_uid

    @staticmethod
    def _bump_daily_rollup(
        connection: sqlite3.Connection,
        *,
        harness_id: str,
        confidence: float,
        clarification: bool,
    ) -> None:
        """Fold one route into today's aggregate.

        This is what makes "change over time" survive the raw-trace cap: the
        rollup is never pruned, so a year-old day still reports its route count,
        clarification rate, and mean confidence long after the traces are gone.
        """
        bucket = str(min(9, max(0, int(confidence * 10))))
        connection.execute(
            """
            INSERT INTO route_trace_daily (
                day, harness_id, route_count, clarification_count,
                confidence_sum, confidence_min, confidence_max, histogram_json
            )
            VALUES (DATE('now'), ?, 1, ?, ?, ?, ?, '{}')
            ON CONFLICT(day, harness_id) DO UPDATE SET
                route_count = route_count + 1,
                clarification_count = clarification_count + excluded.clarification_count,
                confidence_sum = confidence_sum + excluded.confidence_sum,
                confidence_min = MIN(confidence_min, excluded.confidence_min),
                confidence_max = MAX(confidence_max, excluded.confidence_max)
            """,
            (harness_id, int(clarification), confidence, confidence, confidence),
        )
        # The histogram merges in Python: SQLite has no JSON object merge, and
        # json_patch() is not available on every bundled build. The row above
        # always starts it empty so this read-modify-write is the only place
        # buckets are ever incremented.
        row = connection.execute(
            "SELECT histogram_json FROM route_trace_daily WHERE day = DATE('now') AND harness_id = ?",
            (harness_id,),
        ).fetchone()
        if row is None:
            return
        try:
            histogram = json.loads(row["histogram_json"])
            if not isinstance(histogram, dict):
                histogram = {}
        except (json.JSONDecodeError, TypeError):
            histogram = {}
        histogram[bucket] = int(histogram.get(bucket, 0)) + 1
        connection.execute(
            "UPDATE route_trace_daily SET histogram_json = ? WHERE day = DATE('now') AND harness_id = ?",
            (json.dumps(histogram, sort_keys=True), harness_id),
        )

    @staticmethod
    def _prune_route_traces(connection: sqlite3.Connection, trace_id: int) -> None:
        """Bound raw-trace growth, amortized.

        The OFFSET subquery is not free at 20k rows, so it runs once every
        ``PRUNE_INTERVAL`` inserts rather than on every one. The table can
        therefore sit up to ``PRUNE_INTERVAL`` rows above the cap between
        prunes, which is fine -- readers always pass their own LIMIT.
        """
        cap = max_route_traces()
        if cap <= 0 or PRUNE_INTERVAL <= 0 or trace_id % PRUNE_INTERVAL != 0:
            return
        connection.execute(
            """
            DELETE FROM route_traces
            WHERE id <= (
                SELECT id FROM route_traces ORDER BY id DESC LIMIT 1 OFFSET ?
            )
            """,
            (cap,),
        )

    def list_route_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, request_json, response_json, created_at
                FROM route_traces
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [route_trace_summary(row) for row in rows]

    def get_route_trace(self, trace_id: int) -> dict[str, Any] | None:
        self.initialize()
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT id, request_json, response_json, created_at
                FROM route_traces
                WHERE id = ?
                """,
                (trace_id,),
            ).fetchone()
            return route_trace_detail(row) if row else None

    def record_outcome(
        self,
        trace_uid: str,
        *,
        skill_id: str | None = None,
        used: bool = True,
        helpful: bool | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Record what an agent actually did with a route.

        Closes the loop that makes precision measurable rather than assumed.
        ``rank_used`` is resolved here rather than trusted from the caller: the
        agent knows which skill it used, but only the catalog knows what rank
        that skill was offered at.
        """
        self.initialize()
        with self._session() as connection:
            row = connection.execute(
                "SELECT id, harness_id FROM route_traces WHERE trace_uid = ?",
                (trace_uid,),
            ).fetchone()
            if row is None:
                return {"recorded": False, "reason": f"unknown trace_uid: {trace_uid}"}
            rank_used: int | None = None
            if skill_id:
                rank_row = connection.execute(
                    """
                    SELECT position FROM route_trace_candidates
                    WHERE trace_id = ? AND skill_id = ?
                    """,
                    (row["id"], skill_id),
                ).fetchone()
                rank_used = int(rank_row["position"]) if rank_row else None
            connection.execute(
                """
                INSERT INTO route_outcomes (
                    trace_uid, skill_id, used, helpful, rank_used, harness_id, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_uid,
                    skill_id,
                    int(bool(used)),
                    None if helpful is None else int(helpful),
                    rank_used,
                    row["harness_id"],
                    note,
                ),
            )
        return {"recorded": True, "trace_uid": trace_uid, "rank_used": rank_used}

    def save_backend_ref(self, skill_id: str, backend: str, ref: str, status: str) -> None:
        self.initialize()
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO backend_index_refs (skill_id, backend, ref, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(skill_id, backend) DO UPDATE SET
                    ref = excluded.ref,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (skill_id, backend, ref, status),
            )

    def backend_refs(self, skill_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._session() as connection:
            rows = connection.execute(
                "SELECT backend, ref, status, updated_at FROM backend_index_refs WHERE skill_id = ?",
                (skill_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def all_backend_refs(self) -> dict[str, list[dict[str, Any]]]:
        """Return every skill's backend refs in a single query, keyed by skill_id.

        Avoids the N+1 pattern of calling backend_refs() once per skill when
        building the atlas payload or catalog summary.
        """
        self.initialize()
        refs: dict[str, list[dict[str, Any]]] = {}
        with self._session() as connection:
            rows = connection.execute(
                "SELECT skill_id, backend, ref, status, updated_at FROM backend_index_refs"
            ).fetchall()
        for row in rows:
            refs.setdefault(row["skill_id"], []).append(
                {
                    "backend": row["backend"],
                    "ref": row["ref"],
                    "status": row["status"],
                    "updated_at": row["updated_at"],
                }
            )
        return refs

    def backend_ref_summary(self, backend: str) -> dict[str, Any]:
        self.initialize()
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM backend_index_refs
                WHERE backend = ?
                GROUP BY status
                ORDER BY status
                """,
                (backend,),
            ).fetchall()
            status_counts = {row["status"]: row["count"] for row in rows}
            return {"ref_count": sum(status_counts.values()), "status_counts": status_counts}

    def _record_from_row(self, connection: sqlite3.Connection, row: sqlite3.Row) -> SkillRecord:
        excerpts = [
            SkillExcerpt(
                kind=excerpt["kind"],
                text=excerpt["text"],
                source_path=excerpt["source_path"],
                start_line=excerpt["start_line"],
                end_line=excerpt["end_line"],
            )
            for excerpt in connection.execute(
                "SELECT * FROM excerpts WHERE skill_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
        ]
        relationships = [
            SkillRelationship(type=relationship["type"], target=relationship["to_ref"])
            for relationship in connection.execute(
                "SELECT * FROM relationships WHERE from_skill_id = ? ORDER BY type, to_ref",
                (row["id"],),
            ).fetchall()
        ]
        references = [
            SkillReference(**reference)
            for reference in json.loads(row["references_json"])
        ]
        return SkillRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            skill_path=row["skill_path"],
            bundle_path=row["bundle_path"],
            root_path=row["root_path"],
            content_hash=row["content_hash"],
            metadata=json.loads(row["metadata_json"]),
            tags=json.loads(row["tags_json"]),
            facets=json.loads(row["facets_json"]),
            excerpts=excerpts,
            relationships=relationships,
            references=references,
        )


def route_trace_detail(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "request": json.loads(row["request_json"]),
        "response": json.loads(row["response_json"]),
    }


def route_trace_summary(row: sqlite3.Row) -> dict[str, Any]:
    trace = route_trace_detail(row)
    response = trace["response"]
    candidates = response.get("candidates", [])
    top_candidate = candidates[0] if candidates else None
    return {
        "id": trace["id"],
        "created_at": trace["created_at"],
        "request": trace["request"],
        "backend": trace["request"].get("backend"),
        "candidate_count": len(candidates),
        "top_candidate": summarize_trace_candidate(top_candidate),
        "clarification_needed": bool(response.get("clarification_needed")),
    }


def summarize_trace_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    return {
        "skill_id": candidate.get("skill_id"),
        "name": candidate.get("name"),
        "confidence": candidate.get("confidence"),
    }
