"""Who asked for a route, and over which surface.

v0.1 recorded nothing about the caller, so every trace looked alike and
per-harness quality was unanswerable. Attribution is resolved from whatever the
calling surface can offer, best source first, and is always allowed to come back
empty -- an unknown caller is normal (a hand-written MCP config, a direct library
call) and must never be an error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Surfaces a route can arrive through. Recorded on every trace so analytics can
# separate "an agent asked" from "a human ran the CLI" from "an eval did it".
SURFACES = ("cli", "mcp", "acp", "ui", "eval", "bridge")

HARNESS_ENV_VAR = "SKILLROUTE_HARNESS"
HARNESS_VERSION_ENV_VAR = "SKILLROUTE_HARNESS_VERSION"


@dataclass(frozen=True, slots=True)
class Attribution:
    harness_id: str | None = None
    harness_version: str | None = None
    surface: str = "cli"

    def to_json(self) -> dict[str, str | None]:
        return {
            "harness_id": self.harness_id,
            "harness_version": self.harness_version,
            "surface": self.surface,
        }


def resolve_attribution(
    *,
    explicit: str | None = None,
    explicit_version: str | None = None,
    client_name: str | None = None,
    surface: str = "cli",
    client_name_lookup: object | None = None,
    environ: dict[str, str] | None = None,
) -> Attribution:
    """Resolve the calling harness, most trustworthy source first.

    1. ``explicit`` -- the caller told us outright (bridge payload, ``--harness``).
    2. ``client_name`` -- the MCP ``initialize`` handshake's ``clientInfo.name``,
       mapped to a harness id through the manifests.
    3. ``SKILLROUTE_HARNESS`` -- stamped into generated configs at install time,
       which covers ACP and direct CLI use where no handshake exists.

    ``client_name_lookup`` is injected rather than imported so this module stays
    free of a dependency on the harness manifests (and so tests can drive it
    without loading them).
    """
    env = os.environ if environ is None else environ
    resolved_surface = surface if surface in SURFACES else "cli"

    harness_id = _clean(explicit)
    version = _clean(explicit_version)

    if harness_id is None and client_name and callable(client_name_lookup):
        harness_id = _clean(client_name_lookup(client_name))

    if harness_id is None:
        harness_id = _clean(env.get(HARNESS_ENV_VAR))

    if version is None:
        version = _clean(env.get(HARNESS_VERSION_ENV_VAR))

    return Attribution(
        harness_id=harness_id, harness_version=version, surface=resolved_surface
    )


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
