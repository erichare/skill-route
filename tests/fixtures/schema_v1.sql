-- The v0.1.0 catalog schema, verbatim.
--
-- Committed as reviewable SQL rather than a binary .db so the migration tests
-- exercise a real pre-0.2 database that a reader can actually inspect. Do not
-- edit this file to match schema changes -- it is a historical record of what
-- shipped, and editing it would make the migration tests stop testing anything.

CREATE TABLE schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE skills (
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

CREATE TABLE excerpts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL
);

CREATE TABLE relationships (
    from_skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    to_ref TEXT NOT NULL,
    PRIMARY KEY (from_skill_id, type, to_ref)
);

CREATE TABLE backend_index_refs (
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    backend TEXT NOT NULL,
    ref TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (skill_id, backend)
);

CREATE TABLE route_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_skills_name ON skills(name);
CREATE INDEX idx_skills_root ON skills(root_path);
CREATE INDEX idx_excerpts_skill ON excerpts(skill_id);
CREATE INDEX idx_backend_refs_skill ON backend_index_refs(skill_id);

INSERT INTO schema_version(version) VALUES (1);
