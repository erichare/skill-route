# Skill Atlas UI

Skill Atlas is SkillRoute's read-only local web UI for exploring skills as a
facet-clustered graph.

## Launch

```bash
uv run skillroute ui
```

By default this serves the UI at:

```text
http://127.0.0.1:8765
```

Useful options:

```bash
uv run skillroute ui --catalog .skillroute/catalog.db
uv run skillroute ui --host 127.0.0.1 --port 8777 --no-open
```

If the web build is missing, run:

```bash
npm --prefix web install
npm --prefix web run build
```

## What It Shows

- a React Flow skill graph clustered by `facets.domain`
- relationship edges for `requires`, `complements`, `conflicts`,
  `supersedes`, and `same_domain`
- domain filters, relationship filters, orphan/conflict toggles, and search
- selected skill/domain metadata, excerpts, source references, backend refs, and
  unresolved relationship warnings
- a route preview strip that highlights candidate skills without recording a
  route trace

V1 is read-only. It does not edit skill bundles or metadata overlays.

## Development

```bash
npm --prefix web install
npm --prefix web run dev
npm --prefix web run typecheck
npm --prefix web run test
npm --prefix web run build
```

Run the Python API and built UI together:

```bash
uv run skillroute ui --no-open
```
