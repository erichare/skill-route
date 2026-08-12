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

## Tuning Routing Weights

The hybrid route blend (lexical, semantic, repo context, graph) and the
clarification thresholds are weights, not magic numbers. Tune them against
your eval cases:

```bash
uv run skillroute eval tune \
  --fresh \
  --index-root examples/skills \
  --cases examples/evals/golden_routes.json \
  --top 5
```

The tuner grid-searches blend weights on the unit simplex (step size via
`--step`) together with confidence-floor and clarification-gap thresholds,
scoring each set by `passed/total + mean reciprocal rank + 0.25 *
clarification accuracy`. The built-in defaults are always evaluated first and
win ties, so tuning only changes behavior when the evidence supports it.

Apply a winning weight set with the `SKILLROUTE_WEIGHTS` environment variable
(the tuner prints the exact value):

```bash
SKILLROUTE_WEIGHTS='{"lexical": 0.6, "semantic": 0.2, "repo_context": 0.1, "graph": 0.1}' \
  uv run skillroute route "Build an MCP server"
```

Valid keys: `lexical`, `semantic`, `repo_context`, `graph`,
`confidence_floor`, `clarification_gap`. Unknown keys or negative values are
rejected.
