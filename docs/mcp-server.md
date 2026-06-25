# MCP Server

SkillRoute includes a TypeScript stdio MCP server that wraps the Python bridge.

## Build

```bash
cd mcp
npm install
npm run build
```

Or run the full local bootstrap:

```bash
./scripts/bootstrap.sh
```

## Client Setup

Generate reviewed setup for your agent client:

```bash
uv run skillroute mcp config --client codex
uv run skillroute mcp config --client claude-code
uv run skillroute mcp config --client claude-desktop
```

See [Agent Setup](agent-setup.md) for client-specific paths, scopes, and plugin
packaging notes.

## Run

```bash
node build/index.js
```

The server sets `PYTHONPATH` to the repo `src` directory for local development
and invokes:

```bash
python3 -m skillroute bridge <operation>
```

## Tools

### `skillroute.route`

Inputs:

- `request`
- `repo` optional
- `catalog` optional
- `backend` optional: `local` or `astra`
- `limit` optional

Returns ranked skills, reasons, confidence, evidence snippets, suggested order,
and clarification questions.

### `skillroute.search`

Inputs:

- `query`
- `catalog` optional
- `backend` optional: `local` or `astra`
- `limit` optional

Returns search rows with lexical/backend scores and evidence snippets.

### `skillroute.inspect_skill`

Inputs:

- `skill_id`
- `catalog` optional

Returns metadata, facets, relationships, excerpts, references, and backend refs.

## Smoke Test

```bash
cd mcp
npm run smoke
```
