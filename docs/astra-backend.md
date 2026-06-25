# Astra Data API Backend

SkillRoute can sync the local catalog into an Astra DB Data API collection and
use server-side vectorize search during route/search.

## Configure

```bash
export ASTRA_DB_API_ENDPOINT="https://DATABASE_ID-REGION.apps.astra.datastax.com"
export ASTRA_DB_APPLICATION_TOKEN="AstraCS:..."
export SKILLROUTE_ASTRA_KEYSPACE="default_keyspace"
export SKILLROUTE_ASTRA_COLLECTION="skillroute_skills"
```

Optional for vectorize collections that use header authentication:

```bash
export SKILLROUTE_ASTRA_EMBEDDING_API_KEY="..."
```

SkillRoute status output reports credential presence as booleans and does not
print token values.

## Create A Collection

The default document shape includes `$vectorize`, so the target collection must
be vectorize-enabled.

```bash
uv run skillroute backend astra create-collection \
  --options-json '{"vector": {"service": {"provider": "YOUR_PROVIDER", "modelName": "YOUR_MODEL"}}}'
```

## Sync Skills

```bash
uv run skillroute backend astra upsert
uv run skillroute backend astra upsert --json --include-refs
```

The upsert path keys documents by SkillRoute skill id and uses repeatable
`findOneAndReplace` writes.

## Search Or Route With Astra

```bash
uv run skillroute backend astra search "build an MCP server"
uv run skillroute search "build an MCP server" --backend astra
uv run skillroute route "build an MCP server" --backend astra
```

To make Astra the default route/search backend:

```bash
export SKILLROUTE_BACKEND=astra
```

## Status

```bash
uv run skillroute backend status --backend astra
```

This reports readiness, catalog skill count, backend ref counts, and
non-secret Astra configuration details.
