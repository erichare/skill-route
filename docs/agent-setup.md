# Agent Setup

SkillRoute exposes a local stdio MCP server, so agent clients can route skill
requests without a hosted service.

## One Command First

```bash
./scripts/bootstrap.sh
```

The bootstrap script:

- installs the Python dev environment
- installs Node dependencies for the MCP server
- builds `mcp/build/index.js`
- indexes the example skills into `.skillroute/catalog.db`
- prints setup commands for IBM Bob, Codex, Claude Code, and Claude Desktop

## IBM Bob

IBM Bob is the primary first integration for SkillRoute. Bob already supports MCP,
and SkillRoute's local stdio server gives Bob three tools:

- `skillroute.route`
- `skillroute.search`
- `skillroute.inspect_skill`

Generate a Bob-ready `mcpServers` block:

```bash
uv run skillroute mcp config --client ibm-bob
```

Paste the generated JSON into one of Bob's MCP config files:

```text
Global:  ~/.bob/mcp.json
Project: .bob/mcp.json
```

Use global config for your own machine. Use project config only when the paths
are team-safe, for example through environment variables or a shared install
location.

In Bob, open the MCP settings panel and make sure MCP servers are enabled.
SkillRoute does not add `alwaysAllow`; Bob should ask before using tools unless
you explicitly change tool approval settings.

See the official [IBM Bob MCP docs](https://bob.ibm.com/docs/ide/configuration/mcp/mcp-in-bob)
and [transport guide](https://bob.ibm.com/docs/ide/configuration/mcp/server-transports).

## Codex

Generate a reviewed setup command and TOML snippet:

```bash
uv run skillroute mcp config --client codex
```

Run the printed `codex mcp add ...` command, or paste the TOML into:

```text
~/.codex/config.toml
```

Codex stores MCP servers in `config.toml`, and the CLI and IDE extension share
that config. See the official [Codex MCP docs](https://developers.openai.com/codex/mcp).

## Claude Code

Generate a Claude Code setup command:

```bash
uv run skillroute mcp config --client claude-code
```

The default scope is `user`, which makes SkillRoute available across your
projects while keeping the config private to your machine.

For a team-shared project config:

```bash
uv run skillroute mcp config --client claude-code --scope project
```

That emits a `.mcp.json`-compatible snippet. The generated snippet uses absolute
local paths, so replace those with team-safe environment variables before
checking it in. See the official [Claude Code MCP docs](https://code.claude.com/docs/en/mcp).

## Claude Desktop

Generate the JSON block:

```bash
uv run skillroute mcp config --client claude-desktop
```

Paste the generated `mcpServers` block into Claude Desktop's config file:

```text
macOS:   ~/Library/Application Support/Claude/claude_desktop_config.json
Windows: %APPDATA%\Claude\claude_desktop_config.json
```

Restart Claude Desktop after editing the file. See the official
[local MCP server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

## Codex Plugin Status

V1 uses direct MCP setup because the server currently points at a local source
checkout. That is the least surprising path for early users.

The next packaging step is a Codex plugin that bundles:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- friendly assets and screenshots
- a package entrypoint that does not require editing paths by hand

Codex plugins can bundle MCP servers through an `.mcp.json` file, so the setup
generator is intentionally close to that future shape. See the official
[Codex plugin docs](https://developers.openai.com/codex/plugins/build).

## Useful Options

```bash
uv run skillroute mcp config --client ibm-bob --backend astra
uv run skillroute mcp config --client codex --backend astra
uv run skillroute mcp config --client claude-code --catalog /path/to/catalog.db
uv run skillroute mcp config --client claude-desktop --server-name skillroute-dev
```

Generated config includes only local paths and SkillRoute backend selection. Keep
remote backend credentials in your shell or client-specific private config, not
in checked-in project files.

## Troubleshooting

```bash
./scripts/bootstrap.sh
npm --prefix mcp run smoke
uv run skillroute backend status --backend local
uv run skillroute route "Build an MCP server"
```

If a client cannot start the server, regenerate config and check that
`mcp/build/index.js` exists at the absolute path shown in the output.
