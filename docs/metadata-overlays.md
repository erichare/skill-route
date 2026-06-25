# Metadata Overlays

SkillRoute keeps source skill files unchanged. Inferred or reviewed metadata
lives in overlay JSON files beside the indexed skill root.

## Suggest Metadata

```bash
uv run skillroute metadata suggest --root examples/skills
```

By default, suggestions are written to:

```text
examples/skills/.skillroute/overlays/suggested.json
```

## Review Metadata

Edit the overlay to review descriptions, tags, facets, and relationships. Mark
reviewed entries with:

```json
{
  "metadata": {
    "review_status": "reviewed"
  }
}
```

Then validate:

```bash
uv run skillroute metadata review --root examples/skills
```

## Reindex

```bash
uv run skillroute index --root examples/skills
```

Reindexing applies reviewed overlay metadata into the SQLite catalog.

## Relationship Types

- `requires`
- `complements`
- `conflicts`
- `supersedes`
- `same_domain`
