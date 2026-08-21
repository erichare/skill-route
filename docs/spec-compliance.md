# Agent Skills Spec Compliance

SkillRoute is built around the [Agent Skills](https://agentskills.io/home) open
standard: a skill is a folder containing a `SKILL.md` with YAML frontmatter
(`name` and `description`, at minimum) plus optional `scripts/`,
`references/`, and `assets/` directories. The
[specification](https://agentskills.io/specification) defines the frontmatter
contract and the progressive-disclosure guidance that makes skills load
cheaply across agents.

Routing a library you cannot trust is guesswork with extra steps, so
SkillRoute checks every bundle against the spec — as a standalone command, and
on every indexing run.

## `skillroute validate`

```bash
skillroute validate                      # scan . recursively
skillroute validate examples/skills      # scan a root
skillroute validate ./my-skill           # one bundle directory
skillroute validate ./my-skill/SKILL.md  # one file
skillroute validate --strict             # fail on warnings too
skillroute validate --json               # machine-readable report
```

Every bundle is reported against the spec with two severities:

- **error** — violates a spec MUST. The bundle is not portable;
  spec-conforming clients are entitled to refuse it. `validate` exits
  non-zero, so it works as a CI gate.
- **warning** — violates a spec recommendation. The bundle loads, but the
  guidance exists because real agents degrade on it (overlong files crowd the
  context window; thin descriptions route poorly).

```text
$ skillroute validate ./skills
skills/BadName/SKILL.md
  error[name]: name 'Bad_Name' must match the parent directory name 'BadName'
  error[metadata]: metadata value 'stable' must be a string; quote it (e.g. stable: "true")
  warning[references]: reference 'references/legal/REFERENCE.md' is more than one level deep; ...
Spec check (https://agentskills.io/specification): 12 bundles, 2 errors, 1 warning
```

## What is checked

Errors (the spec's MUSTs):

| Field | Rule |
| --- | --- |
| frontmatter | `SKILL.md` opens with a `---` YAML block |
| `name` | Required; 1–64 characters; lowercase `a-z`, `0-9`, `-` only; no leading, trailing, or consecutive hyphens; matches the parent directory name |
| `description` | Required, non-empty, ≤ 1024 characters |
| `compatibility` | ≤ 500 characters when present |
| `metadata` | A mapping of string keys to string values (quote numbers and booleans) |
| `allowed-tools` | A space-separated string, not a YAML list (experimental field) |

Warnings (the spec's recommendations):

- `description` long enough to say what the skill does **and** when to use it
- `SKILL.md` body under 500 lines / ~5000 tokens (estimated) — move detail
  into `references/`
- File references one level deep from `SKILL.md`, never escaping the bundle

Unknown top-level frontmatter fields are **not** flagged. The spec defines
its six fields but does not forbid others, and SkillRoute's own extensions
(`tags`, `requires`, `complements`, …) are load-bearing. For data meant to
travel between ecosystems, prefer the spec's `metadata` map.

## Spec checks during indexing

`skillroute index` validates every bundle it discovers:

- By default, errors and warnings are reported on stderr and the bundle is
  indexed anyway — SkillRoute routes the library you have, not the library
  you wish you had.
- `skillroute index --root <dir> --strict` refuses bundles with spec errors,
  so a catalog can be kept compliant by construction.

```text
$ skillroute index --root examples/skills
Indexed 4 skills into /Users/you/.skillroute/catalog.db
# (stderr, when findings exist)
skillroute: spec check on examples/skills: 0 errors, 2 warnings across 4 bundles ...
```

## Spec fields in the catalog

The optional spec fields are indexed with the bundle and surfaced by
`skillroute inspect` (and in `--json` output, the MCP `inspect_skill` tool,
and the Atlas detail data): `license`, `compatibility`, `allowed-tools`, and
the `metadata` map.

## Relationship to `skills-ref`

The spec points at the reference validator (`skills-ref validate
./my-skill`). SkillRoute's checker is dependency-free and built in, so it
runs anywhere SkillRoute runs — including inside `index` — without a separate
install. If you already use `skills-ref`, both tools check the same
frontmatter contract; `skillroute validate` adds the routing-relevant
advisories (description quality, body size) that SkillRoute is in a position
to care about.
