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
uv run skillroute eval run --cases examples/evals/golden_routes.json
```

The default catalog lives at `.skillroute/catalog.db` in the current directory.
Use `--catalog <path>` or `SKILLROUTE_CATALOG_PATH` to point at another catalog.

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

