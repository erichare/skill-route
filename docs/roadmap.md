# Roadmap

This is a working roadmap for the next implementation slices.

## Slice 1: Real Catalog Fixtures

Goal: index a broader local skill corpus and create realistic golden cases.

- Add fixture generation for a mixed skill catalog.
- Add route cases for overlapping domains, conflicts, and complements.
- Add eval deltas that explain rank/confidence movement.

## Slice 2: Backend-Aware Route Traces

Goal: make traces explain retrieval behavior without reading raw JSON.

- Show backend hit ids, raw scores, and normalized semantic scores.
- Mark local-only fallback when remote backend is selected but not configured.
- Add trace comparison between two route ids.

## Slice 3: Astra Integration Contract

Goal: make live Astra setup safer and easier to verify.

- Add dry-run document preview before sync.
- Add collection readiness checks.
- Add small live smoke command gated by explicit credentials.

## Slice 4: MCP Observability Tools

Goal: expose debug surfaces to agents, not only humans at the CLI.

- Add `skillroute.backend_status`.
- Add `skillroute.list_traces`.
- Add `skillroute.inspect_trace`.

## Slice 5: Router Scoring Review

Goal: make the hybrid score easier to tune.

- Extract scoring weights into a config object.
- Add per-component eval reporting.
- Add confidence band assertions to golden cases.

## Slice 6: Packaging Pass

Goal: make local install and MCP registration smooth.

- Add package metadata polish.
- Add installation docs for agents.
- Add a small release checklist.
