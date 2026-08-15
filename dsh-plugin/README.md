# @skillroute/dsh-plugin

A [DeepSeek Harness](https://deepseek.com/harness/en/) (`dsh`) bundle that wires
SkillRoute into your agents. It registers the SkillRoute MCP server
([`@skillroute/mcp-server`](https://www.npmjs.com/package/@skillroute/mcp-server))
through `dsh`'s built-in `@deepseek-ai/dsh-mcp-client`, so the model can route
requests to skills, search the catalog, and inspect skills.

## Install

```bash
dsh plugin --profile web add @skillroute/dsh-plugin
```

Restart `dsh web` and your agents gain three tools:

- `mcp__skillroute__route`
- `mcp__skillroute__search`
- `mcp__skillroute__inspect_skill`

### Prerequisite: the Python core (optional)

The MCP server shells out to SkillRoute's Python routing engine. It's
**zero-install** when you have `uv` (which ships `uvx`) — the bridge runs
`uvx --from skillroute` automatically. Otherwise install the console script
once:

```bash
pipx install skillroute          # or: uv tool install skillroute / pip install skillroute
```

If neither `skillroute` nor `uvx` is on your PATH, the tools return a clear
"install skillroute or uv" error instead of failing silently.

Then index your skills once (`skillroute index --root <dir>`) or point the tools
at an existing catalog. With no catalog, the tools default to
`~/.skillroute/catalog.db` and return clarification questions until you index.

### Manual install (no pnpm)

`dsh plugin` forwards to pnpm. If you don't have pnpm, append this package's
`cordis.patch.yml` block to `~/.dsh/cordis.patch.yml` instead.

## How it works

`dsh` loads every capability as a plugin. This package is a **bundle**: its
`package.json` declares `dsh.bundle.patch`, and `dsh plugin add` reconciles that
into your profile's layer stack. The patch inserts one entry —
`@deepseek-ai/dsh-mcp-client` — which discovers SkillRoute's three MCP tools and
registers them as native tools.

## License

MIT
