"""Deprecated compatibility shim over the harness pack engine.

v0.1 called these tools "clients" and built their config with a hand-written
if/elif chain. 0.2 calls them *harnesses* and declares them in
``harnesses/*.toml``; see :mod:`skillroute.harnesses` and
:mod:`skillroute.harness_render`.

Everything here forwards to the new engine and produces identical output --
``tests/test_harness_render.py`` asserts that byte-for-byte for every harness
and scope. This module exists so pre-0.2 callers keep working for one release,
and will be removed in 0.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skillroute.harness_render import (
    build_harness_setup,
    default_repo_root,
    harness_display_name,
    render_harness_setup,
    shell_command,
)
from skillroute.harnesses import harness_ids, manifest_for

__all__ = [
    "CLAUDE_SCOPE_CHOICES",
    "MCP_CLIENT_CHOICES",
    "build_mcp_setup",
    "client_display_name",
    "default_repo_root",
    "render_mcp_setup",
    "shell_command",
]

CLAUDE_SCOPE_CHOICES = ("local", "project", "user")


def _client_choices() -> tuple[str, ...]:
    return harness_ids()


# Kept as a module-level name because callers (and the CLI's argparse choices)
# read it directly. Ordered to match the manifests on disk.
MCP_CLIENT_CHOICES: tuple[str, ...] = _client_choices()


def build_mcp_setup(
    *,
    client: str,
    repo_root: Path | None = None,
    catalog: Path | None = None,
    backend: str | None = None,
    server_name: str = "skillroute",
    claude_scope: str = "user",
) -> dict[str, Any]:
    """Deprecated. Use ``harness_render.build_harness_setup`` instead."""
    if client not in MCP_CLIENT_CHOICES:
        valid = ", ".join(MCP_CLIENT_CHOICES)
        raise ValueError(f"Unsupported MCP client {client!r}; expected one of: {valid}")
    if claude_scope not in CLAUDE_SCOPE_CHOICES:
        valid = ", ".join(CLAUDE_SCOPE_CHOICES)
        raise ValueError(
            f"Unsupported Claude Code scope {claude_scope!r}; expected one of: {valid}"
        )
    # Only harnesses that actually declare scopes accept one; passing the
    # default through unconditionally would reject every other harness.
    manifest = manifest_for(client)
    mode = manifest.mode("mcp")
    scope = claude_scope if mode is not None and mode.scopes else None
    return build_harness_setup(
        harness=client,
        mode="mcp",
        repo_root=repo_root,
        catalog=catalog,
        backend=backend,
        server_name=server_name,
        scope=scope,
    )


def render_mcp_setup(payload: dict[str, Any]) -> str:
    """Deprecated. Use ``harness_render.render_harness_setup`` instead."""
    return render_harness_setup(payload)


def client_display_name(client: str) -> str:
    """Deprecated. Use ``harness_render.harness_display_name`` instead."""
    return harness_display_name(client)
