# Harness Packs

A **harness** is an agent tool that can consume SkillRoute — Claude Code, Codex,
Pi, Hermes, OpenCode, and the rest. Each one is described by a single declarative
manifest in [`harnesses/`](../harnesses), so adding support for a new tool is
usually a data change with no Python at all.

```bash
skillroute harness list                  # everything SkillRoute knows about
skillroute harness list --mode skills    # only harnesses with a skills directory
skillroute harness detect                # what is actually installed here
skillroute harness show pi               # what setup would look like
skillroute harness install pi --dry-run  # print, change nothing
skillroute harness install pi --yes      # apply it
skillroute harness doctor pi             # prove the pack still works
```

## Supported harnesses

`first-party` harnesses support every mode that makes sense for them and are
exercised end to end. `breadth` harnesses are MCP-only.

| id | Name | Tier | Modes | Config shape |
| --- | --- | --- | --- | --- |
| `claude-code` | Claude Code | first-party | `hook` · `mcp` · `router_skill` · `skills` | `mcp_servers` |
| `codex` | Codex | first-party | `mcp` · `router_skill` · `skills` | `codex_toml` |
| `pi` | Pi | first-party | `extension` · `mcp` · `router_skill` · `skills` | `mcp_servers` |
| `hermes` | Hermes Agent | first-party | `acp` · `mcp` · `router_skill` · `skills` | `yaml_map` |
| `opencode` | OpenCode | first-party | `mcp` · `router_skill` · `skills` | `opencode_mcp` |
| `amp` | Amp | breadth | `mcp` | `amp_mcp_servers` |
| `claude-desktop` | Claude Desktop | breadth | `mcp` | `mcp_servers` |
| `cursor` | Cursor | breadth | `mcp` | `mcp_servers` |
| `deepseek` | DeepSeek Harness | breadth | `mcp` | `dsh_cordis_patch` |
| `gemini-cli` | Gemini CLI | breadth | `mcp` | `mcp_servers` |
| `goose` | Goose | breadth | `mcp` | `yaml_map` |
| `ibm-bob` | IBM Bob | breadth | `mcp` | `mcp_servers` |
| `vscode` | VS Code | breadth | `mcp` | `vscode_servers` |
| `windsurf` | Windsurf | breadth | `mcp` | `mcp_servers` |
| `zed` | Zed | breadth | `acp` · `mcp` | `zed_context_servers` |

The manifests are the source of truth; `skillroute harness list --json` always
reflects what is actually installed.

## Install modes

A harness declares which of these it supports. `mcp` is the baseline.

| Mode | What it does |
| --- | --- |
| `mcp` | Register the SkillRoute MCP server |
| `acp` | Attach SkillRoute as an ACP routing-advisor agent |
| `skills` | Read the harness's native skills directory, and optionally project a routed subset back |
| `hook` | Install a lifecycle hook (Claude Code's `SessionStart`) |
| `extension` | Install a harness-native extension package (Pi) |
| `router_skill` | Drop in a generated `SKILL.md` that teaches the agent to ask SkillRoute first |

## Adding a harness

Most of the time this is one file.

**1. Write `harnesses/<id>.toml`.** The filename stem must match `id`.

```toml
schema = 1
id = "my-harness"
display_name = "My Harness"
tier = "unverified"          # first-party | breadth | unverified
homepage = "https://example.com/docs"

[detect]
commands = ["my-harness"]                  # looked up on PATH
client_names = ["my-harness"]              # MCP initialize clientInfo.name
paths.all = ["~/.my-harness/config.json"]  # or paths.macos / .linux / .windows
apps.macos = ["/Applications/My Harness.app"]

[modes.mcp]
setup_method = "json_merge"                # command | json_merge | print_only | dir_sync | package
emitter = "mcp_servers"                    # a named config shape (see below)
config_format = "json"
config_path = "~/.my-harness/config.json"  # shown to the user
write_path.all = "~/.my-harness/config.json"
```

**2. Run the conformance suite.** It is parametrized over whatever is in
`harnesses/`, so your new file is picked up automatically:

```bash
uv run --extra dev pytest tests/test_harnesses.py -v
```

That checks the manifest validates, every placeholder resolves, the mode renders
on all three platforms, detection finds it from its own declared paths, and it
does not try to merge a format SkillRoute cannot write.

**3. Verify against the real tool.**

```bash
skillroute harness show my-harness       # eyeball the snippet
skillroute harness install my-harness    # then confirm the tool sees it
```

Once confirmed against the tool's own docs, promote `tier` off `unverified`.

### Placeholders

Any string value may contain these; anything else is a validation error.

`{harness_id}` `{server_name}` `{catalog}` `{backend}` `{repo_root}` `{scope}`
`{server_json}`, plus `{server_argv}`, which expands to multiple argv entries
and is therefore only valid as a whole array element.

### Config shapes (emitters)

A manifest picks a shape by name. Six of the fifteen shipped harnesses reuse
`mcp_servers` unchanged — if yours matches an existing shape, you write no code.

| Emitter | Shape |
| --- | --- |
| `mcp_servers` | `{"mcpServers": {name: {...}}}` — the de facto standard |
| `vscode_servers` | top-level `servers`, name embedded in the object |
| `opencode_mcp` | nested under `mcp` with an explicit `type` |
| `zed_context_servers` | `context_servers` |
| `amp_mcp_servers` | `amp.mcpServers` |
| `codex_toml` | a TOML snippet |
| `yaml_map` | a YAML map under a configurable key |
| `dsh_cordis_patch` | a DeepSeek Harness `cordis.patch.yml` MCP insert |
| `claude_session_start_hook` | a Claude Code hook entry |

Extra literal keys go in `[modes.<mode>.extra]` and are folded into the emitted
server object — that is how IBM Bob gets `cwd`/`disabled` and Codex gets its
timeouts, without either needing its own emitter.

If your harness genuinely needs a new shape, add one function to `EMITTERS` in
`src/skillroute/harness_render.py` and a test pinning it. That is a deliberate,
reviewable addition rather than routine work.

### Two rules worth knowing

**SkillRoute never rewrites your TOML or YAML.** `tomllib` cannot write, there
is no YAML dependency, and hand-merging someone's config file is not worth the
blast radius. Harnesses configured in those formats use `setup_method =
"command"` (drive their own CLI) or `"print_only"` (print a snippet to paste).
A conformance test enforces this.

**Prefer registering a directory over copying files into one.** Hermes exposes
`external_dirs` and Pi declares skill paths in its settings, so `[modes.skills]
register_in` points SkillRoute's directory at them instead of duplicating
bundles. No duplication, no sync drift.

## Cross-platform paths

Every path table accepts `all`, `macos`, `linux`, and `windows` keys, and the
most specific match wins:

```toml
write_path.macos   = "~/.config/goose/config.yaml"
write_path.linux   = "~/.config/goose/config.yaml"
write_path.windows = "%APPDATA%/Block/goose/config/config.yaml"
```

Render for another platform without being on it:

```bash
skillroute harness show goose --platform windows --json
```

## Verifying a pack: `harness doctor`

Manifests encode config paths for fifteen tools that each move on their own
schedule, and a stale path fails quietly — `harness install` reports success
while writing to a file the tool no longer reads. `doctor` is how that stays
honest.

```bash
skillroute harness doctor                  # every pack
skillroute harness doctor claude-code pi   # just these
skillroute harness doctor --no-probe       # static checks only, no subprocess
skillroute harness doctor --json           # for CI
```

Each pack gets six kinds of check:

| Check | Fails when |
| --- | --- |
| `manifest` | the pack declares no install modes (`unverified` tier warns) |
| `platform` | a file-writing mode has no path for the current platform |
| `detect` | never — an absent tool warns, since you can doctor a pack you do not use |
| `render:<mode>` | a mode no longer renders, e.g. an unresolvable placeholder |
| `config` | the config exists but cannot be parsed |
| `server` | the configured server command does not answer an MCP `initialize` |

The `server` check is the one that cannot be faked by inspection: it runs the
exact command the config names, sends `initialize`, and waits for a JSON-RPC
reply. Everything else proves the pack is *describable*; this proves it *works*.

Absent and unconfigured harnesses warn rather than fail, so the command exits
non-zero only on real breakage and is usable as a CI gate:

```bash
skillroute harness doctor --no-probe --json > packs.json || echo "a pack is broken"
```

Run it on Linux and Windows too — `platform` is what catches a pack that was
written against macOS paths only, which is exactly how v0.1 detection went wrong.

## Migrating from `skillroute mcp config`

`skillroute mcp config --client <id>` still works and emits identical output,
but it is deprecated and will be removed in 0.3. The deprecation notice goes to
stderr, so `--json` stdout stays machine-parseable.

| Before | Now |
| --- | --- |
| `skillroute mcp config --client codex` | `skillroute harness show codex` |
| `skillroute mcp config --client claude-code --scope project` | `skillroute harness show claude-code --scope project` |
| — | `skillroute harness install codex` |

The `client` → `harness` rename runs through the Python API too:
`skillroute.client_setup` re-exports the old names from
`skillroute.harness_setup` for one release.
