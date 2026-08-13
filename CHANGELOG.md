# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The default catalog is now `~/.skillroute/catalog.db` instead of
  `.skillroute/catalog.db` under the working directory. v0.1 and v0.2 resolved
  it against a checkout, which was fine when a git clone was the only way to run
  SkillRoute; since 0.2 publishes to PyPI and npm, `uvx skillroute` has no
  checkout and a checkout-relative default names a directory that does not
  exist. An **existing** project catalog still wins, so anyone who indexed into
  their checkout keeps using it rather than finding an empty library.
  `--catalog` and `SKILLROUTE_CATALOG_PATH` are unchanged and still take
  precedence.
- Generated configs for a published server (`--server-source npx`) now point at
  the user catalog rather than resolving one against the checkout that happened
  to generate them. This was the last checkout-bound path in an npx config.

### Added

- `skillroute stats` and a `skillroute.analytics` module answering three
  question families from recorded routes: **library health** (which skills are
  never offered, which are offered but never win, which descriptions compete
  closely enough to shadow each other), **routing quality** (confidence
  distribution, clarification rate, and which score component is carrying the
  ranking), and a **per-harness breakdown**. Schema v2 denormalized every ranked
  candidate into `route_trace_candidates` for exactly this, so it is SQL over
  columns rather than parsing twenty thousand JSON blobs. `--since` accepts a
  span (`30d`, `12h`, `2w`) or an ISO date, `--harness` narrows to one caller,
  and `--json` emits the same numbers for tooling. Routes with no recorded
  harness are reported as `unknown` rather than dropped.

### Fixed

- `skillroute stats` on a catalog that was never indexed reports zero routes
  instead of failing with a missing-table SQL error.

## [0.2.0] - 2026-08-13

### Added

- **Harness packs.** Every agent tool SkillRoute supports is now one declarative
  manifest in `harnesses/*.toml` describing detection, per-platform config paths,
  and which install modes it offers. v0.1 encoded this as a hardcoded if/elif
  chain plus a per-client detection function, so adding a tool meant editing
  around seven places across two modules and three docs; adding one that fits an
  existing config shape is now a data change with no Python. Six of the fourteen
  shipped harnesses reuse the same shape unchanged. `tests/test_harnesses.py` is
  parametrized over whatever is in `harnesses/`, so a new manifest is covered
  automatically.
- Seven new harnesses: `pi`, `hermes`, `opencode`, `goose`, `gemini-cli`, `zed`,
  and `amp` — joining the seven from v0.1, all migrated to manifests with
  byte-identical generated output.
- Install modes beyond MCP: `acp`, `skills` (native skills-directory discovery
  and projection), `hook`, `extension`, and `router_skill`. Where a harness lets
  you register an extra skills directory (Hermes `external_dirs`, Pi's settings),
  SkillRoute registers rather than copying — no duplication, no sync drift.
- Cross-platform config paths. Manifests declare `macos`/`linux`/`windows`
  variants and the most specific match wins; `skillroute harness show --platform`
  renders for a platform you are not on. v0.1 detection was macOS-only.
- `skillroute harness list | detect | show | install | doctor`, plus
  [docs/harnesses.md](docs/harnesses.md) covering how to add a harness.
- `skillroute harness doctor` verifies a pack still matches reality: the manifest
  declares a path for the current platform, every mode still renders, and the
  config on disk names our server. It then runs the exact server command the
  config points at and confirms it answers an MCP `initialize` handshake — the
  one check that inspection cannot fake. Config paths for fourteen tools rot
  silently, because `harness install` keeps reporting success while writing to a
  file the tool no longer reads. An absent or unconfigured harness warns rather
  than fails, so a non-zero exit means real breakage and the command works as a
  CI gate (`--json`, `--no-probe`).
- `--server-source {local,npx}` on `harness show` and `harness install` chooses
  whether a generated config starts the MCP server from a built checkout or from
  the published `@skillroute/mcp-server` via `npx -y`. v0.1 hardcoded the
  checkout path, which is why nothing outside a git clone could run SkillRoute.
  The default stays `local` until the package is actually on npm, so this adds
  the capability without emitting configs that resolve to nothing.
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
- SQLite FTS5 retrieval backend (`--backend fts5`, alias `sqlite-fts5`):
  local BM25 ranking with term-frequency and document-length normalization on
  top of the existing token-overlap lexical score. Query input is escaped so
  FTS5 syntax in requests is treated as literal terms. Available in the CLI,
  bridge, and MCP server backend choices.
- Routing weights are now explicit and tunable: `RouteWeights` replaces the
  hardcoded blend constants, `SKILLROUTE_WEIGHTS` overrides them per process,
  and `skillroute eval tune` grid-searches weights against golden route cases
  so changes are backed by eval evidence. Defaults are unchanged.

### Changed

- The npm release job publishes via npm trusted publishing (OIDC) instead of a
  long-lived `NPM_TOKEN` secret, so there is no static credential in repo
  secrets to leak or rotate, and provenance attestations are generated
  automatically. Requires `id-token: write` and npm ≥ 11.5.1; the job runs on
  Node 24, whose bundled npm clears that floor without an install step (Node 22
  still bundles npm 10.x at its latest patch).
- The release workflow now fails if the pushed tag disagrees with the version in
  `pyproject.toml` or `mcp/package.json`. The published version comes from
  package metadata rather than the tag, so tagging `v0.2.0` against a `0.1.0`
  pyproject would have published `0.1.0` under a release titled `v0.2.0` — and
  a PyPI version can never be reused, so there is no clean recovery.
- Skill discovery is derived from the harness manifests instead of a hardcoded
  three-entry tuple, growing from 3 roots to 10 — including `~/.claude/skills`,
  which v0.1 never scanned.
- Raw route-trace retention raised from 1,000 to 20,000, configurable via
  `SKILLROUTE_MAX_TRACES` (`0` disables pruning). 1,000 rows was a few days of
  one active harness — too short a horizon for any question about change over
  time. Pruning is now amortized across inserts rather than run on every one, so
  the table may sit slightly above the cap between prunes.

### Deprecated

- `skillroute mcp config --client <id>` in favour of `skillroute harness show`
  and `skillroute harness install`. Output is unchanged and the deprecation
  notice goes to stderr, so `--json` stdout stays machine-parseable. The
  `skillroute.client_setup` and `skillroute.mcp_setup` modules are now shims
  re-exporting `skillroute.harness_setup` and `skillroute.harness_render`. They
  are removed in a later release; 0.3 keeps them.

### Security

- The Skill Atlas `POST /api/route-preview` endpoint no longer accepts an
  arbitrary `repo` filesystem path. Any caller who could reach the local UI
  server could use it to probe the disk: the response reports whether a
  directory exists, its resolved absolute path, which marker files it holds,
  and how many files it contains. A `repo` is now honored only when
  `SKILLROUTE_REPO_ROOT` names a base directory, and only for paths that
  resolve inside it (CodeQL `py/path-injection`). The bundled UI never sent
  `repo`, and the CLI's `--repo` is unaffected.

[Unreleased]: https://github.com/erichare/skillroute/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/erichare/skillroute/compare/v0.1.0...v0.2.0

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

[0.1.0]: https://github.com/erichare/skillroute/releases/tag/v0.1.0
