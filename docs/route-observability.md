# Route Observability

SkillRoute records route decisions in the local SQLite catalog so scoring
changes can be inspected and compared.

## Backend Status

```bash
uv run skillroute backend status --backend local
uv run skillroute backend status --backend astra
```

Status includes:

- backend name
- configured/readiness flags
- search/write availability
- catalog path and skill count
- backend ref counts
- non-secret backend details

## List Recent Traces

```bash
uv run skillroute traces list
uv run skillroute traces list --limit 5 --json
```

Each trace summary includes backend, request, top candidate, confidence, and
whether clarification was recommended.

## Show One Trace

```bash
uv run skillroute traces show 1
uv run skillroute traces show 1 --json
```

The full trace contains the stored request, repo context, ranked candidates,
evidence snippets, reasons, and score breakdowns.

## Useful Workflow

```bash
uv run skillroute route "Build an MCP server"
uv run skillroute traces list
uv run skillroute traces show 1
```

Use trace inspection before and after scoring changes to understand why rank or
confidence moved.
