from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from skillroute.models import (
    RouteResponse,
    SkillExcerpt,
    SkillRecord,
    SkillReference,
    SkillRelationship,
    to_jsonable,
)
from skillroute.backends import LocalTokenBackend
from skillroute.overlays import load_overlays, overlay_for_skill
from skillroute.parser import discover_skill_files, parse_skill_bundle, parse_frontmatter


SCHEMA_VERSION = 1


def default_catalog_path(base: Path | None = None) -> Path:
    configured = os.environ.get("SKILLROUTE_CATALOG_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return ((base or Path.cwd()) / ".skillroute" / "catalog.db").resolve()


class Catalog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else default_catalog_path()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS eval_cases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    request TEXT NOT NULL,
                    expected_skill_ids_json TEXT NOT NULL,
                    expected_skill_names_json TEXT NOT NULL,
                    expect_clarification INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
                CREATE INDEX IF NOT EXISTS idx_skills_root ON skills(root_path);
                CREATE INDEX IF NOT EXISTS idx_excerpts_skill ON excerpts(skill_id);
                """
            )
            existing = connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            if not existing:
                connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))

    def index_root(self, root: Path | str) -> list[SkillRecord]:
        root_path = Path(root).expanduser().resolve()
        overlays = load_overlays(root_path)
        skills: list[SkillRecord] = []
        for skill_file in discover_skill_files(root_path):
            raw_text = skill_file.read_text(encoding="utf-8")
            metadata, _ = parse_frontmatter(raw_text)
            name = str(metadata.get("name") or skill_file.parent.name)
            overlay = overlay_for_skill(overlays, skill_file, name)
            skills.append(parse_skill_bundle(skill_file, root=root_path, overlay=overlay))
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
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM skills WHERE root_path = ?",
                (root_path,),
            ).fetchall()
            for row in existing:
                connection.execute("DELETE FROM skills WHERE id = ?", (row["id"],))
            for skill in skills:
                self._upsert_skill(connection, skill)

    def upsert_skill(self, skill: SkillRecord) -> None:
        self.initialize()
        with self.connect() as connection:
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
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM skills ORDER BY name").fetchall()
            return [self._record_from_row(connection, row) for row in rows]

    def get_skill(self, skill_ref: str) -> SkillRecord | None:
        self.initialize()
        with self.connect() as connection:
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

    def record_route_trace(self, request: dict[str, Any], response: RouteResponse) -> None:
        self.initialize()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO route_traces (request_json, response_json) VALUES (?, ?)",
                (json.dumps(request, sort_keys=True), json.dumps(to_jsonable(response), sort_keys=True)),
            )

    def save_backend_ref(self, skill_id: str, backend: str, ref: str, status: str) -> None:
        self.initialize()
        with self.connect() as connection:
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
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT backend, ref, status, updated_at FROM backend_index_refs WHERE skill_id = ?",
                (skill_id,),
            ).fetchall()
            return [dict(row) for row in rows]

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
