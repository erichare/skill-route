# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Catalog schema v2 with real migration machinery. `skillroute.migrations`
  defines ordered, named migrations; `Catalog.initialize()` detects the on-disk
  version, takes a write lock (`BEGIN IMMEDIATE`) so a concurrent index and UI
  server cannot both migrate, backs the file up before altering it, and refuses
  a catalog written by a newer SkillRoute instead of corrupting it. Existing v1
  catalogs upgrade in place; their traces are unpacked into the new columns
  rather than discarded.
- Route traces now record who asked and what happened: `harness_id`,
  `harness_version`, `surface`, `request_text`, `top_confidence`,
  `second_confidence`, `catalog_fingerprint`, and the routing weights in effect.
  A new `route_trace_candidates` table denormalizes every ranked candidate and
  its score breakdown so analytics can use SQL instead of parsing response
  blobs. `skillroute route --harness <id>` and `SKILLROUTE_HARNESS` set the
  attribution; an unknown caller stays unknown rather than erroring.
- `Catalog.record_outcome()` and a `route_outcomes` table, so an agent can
  report which skill it actually used. The rank it was offered at is resolved
  from the recorded candidates rather than trusted from the caller.
- `route_trace_daily` aggregates every route on the day it happens. Raw traces
  are still capped, but the rollup is not, so route counts, clarification rates,
  and confidence distributions survive pruning and remain answerable over time.

### Changed

- Raw route-trace retention raised from 1,000 to 20,000, configurable via
  `SKILLROUTE_MAX_TRACES` (`0` disables pruning). 1,000 rows was a few days of
  one active harness — too short a horizon for any question about change over
  time. Pruning is now amortized across inserts rather than run on every one, so
  the table may sit slightly above the cap between prunes.

### Added

- SQLite FTS5 retrieval backend (`--backend fts5`, alias `sqlite-fts5`):
  local BM25 ranking with term-frequency and document-length normalization on
  top of the existing token-overlap lexical score. Query input is escaped so
  FTS5 syntax in requests is treated as literal terms. Available in the CLI,
  bridge, and MCP server backend choices.
- Routing weights are now explicit and tunable: `RouteWeights` replaces the
  hardcoded blend constants, `SKILLROUTE_WEIGHTS` overrides them per process,
  and `skillroute eval tune` grid-searches weights against golden route cases
  so changes are backed by eval evidence. Defaults are unchanged.

### Security

- The Skill Atlas `POST /api/route-preview` endpoint no longer accepts an
  arbitrary `repo` filesystem path. Any caller who could reach the local UI
  server could use it to probe the disk: the response reports whether a
  directory exists, its resolved absolute path, which marker files it holds,
  and how many files it contains. A `repo` is now honored only when
  `SKILLROUTE_REPO_ROOT` names a base directory, and only for paths that
  resolve inside it (CodeQL `py/path-injection`). The bundled UI never sent
  `repo`, and the CLI's `--repo` is unaffected.

[Unreleased]: https://github.com/erichare/skill-route/compare/v0.1.0...HEAD

## [0.1.0] - 2026-08-10

First release.

### Added

- SKILL.md bundle indexing into a local SQLite catalog (`skillroute index`)
- Semantic routing with ranked skills, confidence, evidence snippets, suggested
  order, and clarification questions (`skillroute route`)
- Hybrid search over indexed skills (`skillroute search`) and per-skill
  inspection (`skillroute inspect`)
- Pluggable retrieval backends: local token backend and Astra Data API backend,
  plus a LangChain retriever adapter
- Metadata overlays for curating tags, domains, and languages without editing
  skill sources
- Route observability: persisted route traces (`skillroute traces list`)
- Golden route evals (`skillroute eval run`)
- Skill Atlas web UI (`skillroute ui`), bundled into the Python wheel
- MCP stdio server (`@skillroute/mcp-server`) exposing `skillroute.route`,
  `skillroute.search`, and `skillroute.inspect_skill`, with client setup via
  `skillroute mcp config --client <client>`

[0.1.0]: https://github.com/erichare/skill-route/releases/tag/v0.1.0
