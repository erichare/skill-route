from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from skillroute.catalog import default_catalog_path


MCP_CLIENT_CHOICES = (
    "ibm-bob",
    "codex",
    "claude-code",
    "claude-desktop",
    "vscode",
    "windsurf",
    "cursor",
)
CLAUDE_SCOPE_CHOICES = ("local", "project", "user")


def build_mcp_setup(
    *,
    client: str,
    repo_root: Path | None = None,
    catalog: Path | None = None,
    backend: str | None = None,
    server_name: str = "skillroute",
    claude_scope: str = "user",
) -> dict[str, Any]:
    if client not in MCP_CLIENT_CHOICES:
        valid = ", ".join(MCP_CLIENT_CHOICES)
        raise ValueError(f"Unsupported MCP client {client!r}; expected one of: {valid}")
    if claude_scope not in CLAUDE_SCOPE_CHOICES:
        valid = ", ".join(CLAUDE_SCOPE_CHOICES)
        raise ValueError(f"Unsupported Claude Code scope {claude_scope!r}; expected one of: {valid}")

    resolved_repo_root = (repo_root or default_repo_root()).expanduser().resolve()
    catalog_path = (catalog.expanduser().resolve() if catalog else default_catalog_path(resolved_repo_root))
    selected_backend = (backend or os.environ.get("SKILLROUTE_BACKEND") or "local").strip().lower()
    entrypoint = resolved_repo_root / "mcp" / "build" / "index.js"
    env = {
        "SKILLROUTE_CATALOG_PATH": str(catalog_path),
        "SKILLROUTE_BACKEND": selected_backend,
    }
    stdio_server_config = {
        "command": "node",
        "args": [str(entrypoint)],
        "env": env,
    }
    notes = [
        "Run ./scripts/bootstrap.sh first if mcp/build/index.js does not exist.",
        "The generated config points at this local checkout and catalog.",
    ]
    if not entrypoint.exists():
        notes.append(f"MCP entrypoint not found yet: {entrypoint}")

    payload: dict[str, Any] = {
        "client": client,
        "server_name": server_name,
        "repo_root": str(resolved_repo_root),
        "mcp_entrypoint": str(entrypoint),
        "catalog": str(catalog_path),
        "backend": selected_backend,
        "server_config": stdio_server_config,
        "notes": notes,
    }

    if client == "ibm-bob":
        payload.update(
            {
                "install_command": None,
                "install_command_parts": None,
                "config_path": "~/.bob/mcp.json or .bob/mcp.json",
                "config_format": "json",
                "setup_method": "json_merge",
                "config": {
                    "mcpServers": {
                        server_name: {
                            **stdio_server_config,
                            "cwd": str(resolved_repo_root),
                            "disabled": False,
                        }
                    }
                },
            }
        )
    elif client == "codex":
        command_parts = codex_command_parts(server_name, catalog_path, selected_backend, entrypoint)
        payload.update(
            {
                "install_command": shell_command(command_parts),
                "install_command_parts": command_parts,
                "config_path": "~/.codex/config.toml",
                "config_format": "toml",
                "setup_method": "command",
                "config": codex_toml(server_name, entrypoint, resolved_repo_root, env),
            }
        )
    elif client == "claude-code":
        command_parts = claude_code_command_parts(
            server_name,
            catalog_path,
            selected_backend,
            entrypoint,
            claude_scope,
        )
        payload.update(
            {
                "scope": claude_scope,
                "install_command": shell_command(command_parts),
                "install_command_parts": command_parts,
                "config_path": claude_code_config_path(claude_scope),
                "config_format": "json",
                "setup_method": "command",
                "config": {"mcpServers": {server_name: stdio_server_config}},
            }
        )
    elif client == "claude-desktop":
        payload.update(
            {
                "install_command": None,
                "install_command_parts": None,
                "config_path": (
                    "~/Library/Application Support/Claude/claude_desktop_config.json "
                    "or %APPDATA%\\Claude\\claude_desktop_config.json"
                ),
                "config_format": "json",
                "setup_method": "json_merge",
                "config": {"mcpServers": {server_name: stdio_server_config}},
            }
        )
    elif client == "vscode":
        server_config = {"name": server_name, **stdio_server_config}
        command_parts = ["code", "--add-mcp", json.dumps(server_config, sort_keys=True)]
        payload.update(
            {
                "install_command": shell_command(command_parts),
                "install_command_parts": command_parts,
                "config_path": "VS Code user profile mcp.json",
                "config_format": "json",
                "setup_method": "command",
                "config": {"servers": {server_name: stdio_server_config}},
                "server_config": server_config,
            }
        )
    elif client == "windsurf":
        payload.update(
            {
                "install_command": None,
                "install_command_parts": None,
                "config_path": "~/.codeium/windsurf/mcp_config.json",
                "config_format": "json",
                "setup_method": "json_merge",
                "config": {"mcpServers": {server_name: stdio_server_config}},
            }
        )
    else:
        payload.update(
            {
                "install_command": None,
                "install_command_parts": None,
                "config_path": "Cursor MCP settings",
                "config_format": "json",
                "setup_method": "print_only",
                "config": {"mcpServers": {server_name: stdio_server_config}},
                "notes": [
                    *payload["notes"],
                    "Cursor setup is snippet-only until a stable official write target is confirmed.",
                ],
            }
        )

    return payload


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def shell_command(parts: list[str]) -> str:
    return shlex.join(parts)


def codex_command_parts(
    server_name: str,
    catalog_path: Path,
    selected_backend: str,
    entrypoint: Path,
) -> list[str]:
    return [
        "codex",
        "mcp",
        "add",
        server_name,
        "--env",
        f"SKILLROUTE_CATALOG_PATH={catalog_path}",
        "--env",
        f"SKILLROUTE_BACKEND={selected_backend}",
        "--",
        "node",
        str(entrypoint),
    ]


def claude_code_command_parts(
    server_name: str,
    catalog_path: Path,
    selected_backend: str,
    entrypoint: Path,
    claude_scope: str,
) -> list[str]:
    return [
        "claude",
        "mcp",
        "add",
        "--transport",
        "stdio",
        "--scope",
        claude_scope,
        "--env",
        f"SKILLROUTE_CATALOG_PATH={catalog_path}",
        "--env",
        f"SKILLROUTE_BACKEND={selected_backend}",
        server_name,
        "--",
        "node",
        str(entrypoint),
    ]


def codex_toml(server_name: str, entrypoint: Path, repo_root: Path, env: dict[str, str]) -> str:
    args = ", ".join(toml_string(part) for part in [str(entrypoint)])
    env_pairs = ", ".join(f"{key} = {toml_string(value)}" for key, value in sorted(env.items()))
    table_name = toml_table_name(server_name)
    return "\n".join(
        [
            f"[mcp_servers.{table_name}]",
            'command = "node"',
            f"args = [{args}]",
            f"cwd = {toml_string(str(repo_root))}",
            f"env = {{ {env_pairs} }}",
            "startup_timeout_sec = 20",
            "tool_timeout_sec = 60",
        ]
    )


def claude_code_config_path(scope: str) -> str:
    if scope == "project":
        return ".mcp.json"
    return "~/.claude.json"


def toml_table_name(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return toml_string(value)


def toml_string(value: str) -> str:
    return json.dumps(value)


def render_mcp_setup(payload: dict[str, Any]) -> str:
    lines = [
        f"SkillRoute MCP setup for {client_display_name(payload['client'])}",
        f"server: {payload['server_name']}",
        f"catalog: {payload['catalog']}",
        f"backend: {payload['backend']}",
        "",
    ]
    if payload.get("install_command"):
        lines.extend(["Install command:", payload["install_command"], ""])
    lines.extend([f"Config path: {payload['config_path']}", f"Config format: {payload['config_format']}", ""])
    lines.append("Config snippet:")
    config = payload["config"]
    if isinstance(config, str):
        lines.append(config)
    else:
        lines.append(json.dumps(config, indent=2, sort_keys=True))
    if payload.get("notes"):
        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in payload["notes"])
    return "\n".join(lines)


def client_display_name(client: str) -> str:
    names = {
        "ibm-bob": "IBM Bob",
        "codex": "Codex",
        "claude-code": "Claude Code",
        "claude-desktop": "Claude Desktop",
        "vscode": "VS Code",
        "cursor": "Cursor",
        "windsurf": "Windsurf",
    }
    return names.get(client, client)
