# SkillRoute MCP Server

Stdio MCP server exposing [SkillRoute](https://github.com/erichare/skillroute) routing tools to agent clients: `skillroute.route`, `skillroute.search`, and `skillroute.inspect_skill`.

The server bridges to the SkillRoute Python package, so install that first:

```bash
pip install skillroute
```

Then configure your MCP client to run:

```bash
npx @skillroute/mcp-server
```

In a SkillRoute source checkout the server autodetects the repo and runs against the checkout instead. Environment overrides:

- `SKILLROUTE_REPO_ROOT` — force a specific checkout
- `SKILLROUTE_PYTHON` — interpreter to run `-m skillroute` with
- `SKILLROUTE_BRIDGE_TIMEOUT_MS` — bridge call timeout (default 30000)

See the [main repository](https://github.com/erichare/skillroute) for full documentation, including `skillroute mcp config --client <client>` which generates client configuration for you.
