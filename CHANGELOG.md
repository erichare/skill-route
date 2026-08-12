# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
