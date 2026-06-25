# Golden Route Evals

Golden-route evals protect routing behavior as scoring, metadata, and backend
retrieval change.

## Run Example Evals

```bash
uv run skillroute eval run \
  --fresh \
  --index-root examples/skills \
  --cases examples/evals/golden_routes.json
```

Dogfood cases:

```bash
uv run skillroute eval run \
  --fresh \
  --index-root examples/skills \
  --cases examples/evals/dogfood_routes.json
```

## Case Shape

```json
[
  {
    "id": "mcp-server-route",
    "name": "mcp server route",
    "request": "Build a TypeScript MCP stdio server with tools",
    "expected_skill_names": ["mcp-server-patterns"],
    "expect_clarification": false
  }
]
```

## What Evals Check

- expected top skills by id or name
- clarification behavior
- route notes for failures

## When To Add Cases

Add a case when:

- a route regresses
- a new skill domain is introduced
- scoring weights change
- a backend adapter starts influencing candidate retrieval
