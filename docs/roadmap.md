# Roadmap

The 0.2 release — *"the router for skill bloat"* — ships in six independently
mergeable stages. This file tracks their status; the stage numbers match the
release plan and the PR titles.

SKILL.md became an open standard in Dec 2025 and marketplaces followed, so
discovery stopped being the bottleneck and judgment became it. 0.1 solved the
judgment problem but could not reach it: it was not installable outside a git
checkout, adding a harness cost ~7 edit sites, detection was macOS-only, and
route traces were write-only with no caller identity. 0.2 closes those.

| Stage | What | Status |
| --- | --- | --- |
| S0 | Catalog schema v2, migrations, attribution, outcomes | done |
| S1 | Harness pack engine — 14 declarative manifests | done |
| S2 | Distribution — PyPI, npm, Homebrew, `uvx`/`npx` configs | next |
| S3 | Harness depth — deep packs, skills-dir sync, ACP server | not started |
| S4 | Analytics + reports — `skillroute stats`, three renderers | not started |
| S5 | Atlas — SSE live feed, semantic layout | not started |
| S6 | Router intelligence — decomposition, `report_outcome`, registry gaps | not started |

**Minimum coherent 0.2 if it has to ship early:** S0 + S1 + S2 + the CLI half of
S4 — "harness packs, real distribution, and `skillroute stats`". Drop in this
order: S6 → S5 → S4's HTML/CI renderers → S3's non-MCP install modes.

## S0 — Foundations (done)

Ordered, named migrations in `skillroute.migrations`; `Catalog.initialize()`
detects the on-disk version, takes `BEGIN IMMEDIATE`, backs the file up before
altering it, and refuses a catalog written by a newer build. Schema v2 records
caller attribution and denormalizes ranked candidates into
`route_trace_candidates` so analytics can use SQL. `route_outcomes`,
`route_plans`, and `skill_projection` are created here even though S4–S6 are
what read them, so no later stage needs a second migration on a file users keep.

## S1 — Harness pack engine (done)

Each harness is one `harnesses/<id>.toml` declaring detection, per-platform
config paths, and install modes; the per-client quirks the old if/elif chain
encoded became a closed set of named emitters. Adding a harness that fits an
existing shape is a data change. Verified byte-identical to the 0.1 builder
across all seven legacy clients before the old code was removed.

`skillroute harness doctor` verifies a pack still matches reality — including
running the configured server and confirming it answers an MCP `initialize`.
See [harnesses.md](harnesses.md).

## S2 — Distribution (next)

The single biggest adoption unlock: nothing outside a git checkout can run
SkillRoute today, because generated configs hardcode
`node <repo>/mcp/build/index.js`.

- Publish `skillroute` to PyPI and `@skillroute/mcp-server` to npm
  (`PYPI_PUBLISH` / `NPM_PUBLISH` repo variables currently gate this).
- Default generated configs to `uvx skillroute` / `npx -y @skillroute/mcp-server`,
  with checkout paths behind `--local`.
- Homebrew formula.

## S3 — Harness depth

Deep packs for `claude-code`, `codex`, `pi`, `hermes`, `opencode` with every
applicable mode. Skills-dir tri-mode: read-only discovery, opt-in projection,
and `router_skill`. ACP server (`skillroute acp serve`, Python — ACP is plain
JSON-RPC over stdio and needs no SDK). Harness attribution from the MCP
`clientInfo` handshake.

Standing risk: these tools move fast and paths drift. `harness doctor` and the
`unverified` tier are how that stays honest.

## S4 — Analytics and reports

`skillroute.analytics` as pure SQL over the v2 tables, answering four question
families: library health (which skills never win, which are near-duplicates,
where the coverage holes are), routing quality, per-harness breakdown, and
change over time. One report model, three renderers — terminal, self-contained
`atlas.html`, and a GitHub Action that comments on skill-library PRs.

## S5 — Atlas

SSE live route feed, a zero-dependency semantic layout (sparse random projection
then power-iteration PCA, cached on the catalog fingerprint), analytics views,
and a harness filter. The facet layout stays the default.

## S6 — Router intelligence

Task decomposition into a `RoutePlan` with per-subtask steps and explicit gaps;
`report_outcome` on MCP and ACP so agents close the loop; opt-in registry
suggestions when decomposition finds a gap. 0.2 collects the outcome signal;
learned routing from it is 0.3.

## Out of scope for 0.2

- Built-in LLM reranker (`ExternalCommandReranker` remains the seam)
- Optional embedding-model extra
- Indexing remote registries into the catalog — gap *suggestions* only
- A long-lived `skillroute serve` daemon
- Learned routing from outcome data
