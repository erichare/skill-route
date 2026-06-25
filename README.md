# SkillRoute

SkillRoute is a local-first skill catalog and router for agent builders. It indexes
`SKILL.md` bundles, stores reviewed metadata in SQLite, models relationships as a
small graph, and returns ranked skill plans with evidence and clarification
questions when the match is uncertain.

## Quick Start

```bash
uv run skillroute index --root examples/skills
uv run skillroute route "Build an MCP server that exposes routing tools"
uv run skillroute inspect mcp-server-patterns
uv run skillroute eval run --fresh --index-root examples/skills --cases examples/evals/golden_routes.json
```

The default catalog lives at `.skillroute/catalog.db` in the current directory.
Use `--catalog <path>` or `SKILLROUTE_CATALOG_PATH` to point at another catalog.

## Dogfooding Local Skills

SkillRoute can discover the local skill roots used by Codex-style workflows:

```bash
uv run skillroute dogfood roots
uv run skillroute dogfood index
uv run skillroute route "Review a GitHub PR with exact file and line evidence"
```

The dogfood command looks for:

- `~/.codex/skills`
- `~/.agents/skills`
- `~/.codex/plugins/cache`

Use the example dogfood cases as a template for real routing regressions:

```bash
uv run skillroute eval run --fresh --index-root examples/skills --cases examples/evals/dogfood_routes.json
```

## Metadata Review

Generate a reviewable overlay without editing source `SKILL.md` files:

```bash
uv run skillroute metadata suggest --root examples/skills
uv run skillroute metadata review --root examples/skills
```

The default overlay path is `.skillroute/overlays/suggested.json` under the
indexed root. Edit that JSON to mark `metadata.review_status` as `reviewed`,
adjust tags/facets/relationships, then re-run `skillroute index --root <root>`.

## Astra Data API Backend

SkillRoute can sync the local catalog into an Astra DB Data API collection and
query it with server-side vectorize search. Configure credentials with
environment variables:

```bash
export ASTRA_DB_API_ENDPOINT="https://DATABASE_ID-REGION.apps.astra.datastax.com"
export ASTRA_DB_APPLICATION_TOKEN="AstraCS:..."
export SKILLROUTE_ASTRA_KEYSPACE="default_keyspace"
export SKILLROUTE_ASTRA_COLLECTION="skillroute_skills"
# Optional if your vectorize collection uses header authentication:
export SKILLROUTE_ASTRA_EMBEDDING_API_KEY="..."
```

The default document shape includes `$vectorize`, so the target collection must
be vectorize-enabled. You can pass collection options directly when creating it:

```bash
uv run skillroute backend astra create-collection --options-json '{"vector": {"service": {"provider": "YOUR_PROVIDER", "modelName": "YOUR_MODEL"}}}'
uv run skillroute backend astra upsert
uv run skillroute backend astra upsert --json --include-refs
uv run skillroute backend astra search "build an MCP server"
uv run skillroute route "build an MCP server" --backend astra
```

`skillroute route`, `skillroute search`, and the MCP `skillroute.route` /
`skillroute.search` tools accept `backend: "astra"` to use Astra retrieval in
the hybrid candidate set. Set `SKILLROUTE_BACKEND=astra` to make Astra the
default backend for route/search calls.

## MCP Server

The MCP package is a thin TypeScript stdio wrapper around the Python bridge:

```bash
cd mcp
npm install
npm run build
node build/index.js
```

The server exposes:

- `skillroute.route`
- `skillroute.search`
- `skillroute.inspect_skill`

The wrapper invokes `python3 -m skillroute bridge ...` and sets `PYTHONPATH` to
the repository `src` directory for local development.

## Architecture

- Python core: parsing, catalog persistence, routing, adapters, evals, and CLI.
- SQLite catalog: durable local store for skills, excerpts, relationships,
  backend refs, route traces, and eval cases.
- TypeScript MCP: local stdio transport using the official MCP TypeScript SDK.
- Retrieval adapters: local token backend now, with Astra DB/Data API and
  LangChain-compatible adapter contracts ready for real remote indexing.

## Continuous Integration

GitHub Actions runs Python tests/lint, example golden-route evals, and the MCP
build/typecheck/smoke suite on pushes and pull requests.
