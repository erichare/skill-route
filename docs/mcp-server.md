# MCP Server

SkillRoute includes a TypeScript stdio MCP server that wraps the Python bridge.

## Build

```bash
cd mcp
npm install
npm run build
```

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
