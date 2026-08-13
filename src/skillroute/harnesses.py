"""Declarative harness packs.

A *harness* is an agent tool that can consume SkillRoute -- Claude Code, Codex,
Pi, Hermes, OpenCode, and so on. v0.1 supported seven of them through a hardcoded
if/elif chain plus a per-client ``detect_*`` function, so adding one meant
editing about seven places across two modules and three docs.

Here each harness is one TOML file under ``harnesses/``. The file declares how to
detect the tool, where its config lives on each platform, and which install modes
it supports. Adding a harness that fits an existing config shape is pure data;
only a genuinely novel shape needs Python, and then only one named emitter plus
its test.

``tomllib`` is stdlib on 3.11+, and manifests are read-only at runtime, so this
costs no dependency.
"""

from __future__ import annotations

import fnmatch
import os
import sys
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

MANIFEST_SCHEMA = 1

Platform = Literal["macos", "linux", "windows"]
PLATFORMS: tuple[Platform, ...] = ("macos", "linux", "windows")

# Capability a harness can offer. `mcp` is the baseline every harness supports;
# the rest are how a given tool prefers to be extended.
INSTALL_MODES = ("mcp", "acp", "skills", "hook", "extension", "router_skill")

# Mechanism used to apply a mode. Deliberately closed: `toml_merge` is absent
# because SkillRoute never rewrites a user's TOML (tomllib cannot write, and
# hand-merging someone's config.toml is not worth the blast radius). TOML-backed
# harnesses use `command` or `print_only` instead.
SETUP_METHODS = ("command", "json_merge", "print_only", "dir_sync", "package")

TIERS = ("first-party", "breadth", "unverified")


class ManifestError(ValueError):
    """A harness manifest is malformed. Raised at load time, not at a user's terminal."""


@dataclass(frozen=True, slots=True)
class Detect:
    commands: tuple[str, ...] = ()
    # MCP `initialize` clientInfo.name values that mean "this harness".
    client_names: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    apps: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def paths_for(self, platform: str) -> tuple[str, ...]:
        return self.paths.get(platform, ()) + self.paths.get("all", ())

    def apps_for(self, platform: str) -> tuple[str, ...]:
        return self.apps.get(platform, ()) + self.apps.get("all", ())


@dataclass(frozen=True, slots=True)
class InstallMode:
    mode: str
    setup_method: str
    # Human-facing location, shown in `harness show` output. Deliberately
    # separate from write_path: several harnesses display something like
    # "~/.bob/mcp.json or .bob/mcp.json" that is not a single real path.
    config_path_display: str = ""
    config_format: str = "json"
    emitter: str = ""
    argv: tuple[str, ...] = ()
    # Real per-platform path SkillRoute reads or writes. Keys are platforms or "all".
    write_path: dict[str, str] = field(default_factory=dict)
    # Per-scope overrides, e.g. Claude Code's project scope writing .mcp.json.
    scope_paths: dict[str, str] = field(default_factory=dict)
    scopes: tuple[str, ...] = ()
    default_scope: str = ""
    # Extra literal keys folded into the emitted server config (cwd, disabled,
    # startup_timeout_sec, ...). This is what absorbs most per-harness quirk.
    extra: dict[str, Any] = field(default_factory=dict)
    # Directories SkillRoute can read skills from, for `skills` mode.
    skills_dirs: dict[str, str] = field(default_factory=dict)
    project_dir: str = ""
    discovery: tuple[str, ...] = ()
    # Some harnesses let you register an extra skills directory instead of
    # copying files into theirs. Registration beats sync: no duplication, no drift.
    register_in: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def path_for(self, platform: str, scope: str = "") -> str:
        if scope and scope in self.scope_paths:
            return self.scope_paths[scope]
        return self.write_path.get(platform) or self.write_path.get("all", "")

    def skills_dir_for(self, platform: str) -> str:
        return self.skills_dirs.get(platform) or self.skills_dirs.get("all", "")


@dataclass(frozen=True, slots=True)
class HarnessManifest:
    id: str
    display_name: str
    tier: str
    homepage: str
    detect: Detect
    modes: dict[str, InstallMode]
    notes: tuple[str, ...] = ()

    def mode(self, name: str) -> InstallMode | None:
        return self.modes.get(name)

    def supports(self, name: str) -> bool:
        return name in self.modes


def default_manifest_root() -> Path:
    """Locate ``harnesses/`` in a wheel install or a source checkout.

    Mirrors how ``ui_server.default_web_dist()`` resolves bundled assets.
    """
    override = os.environ.get("SKILLROUTE_HARNESS_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    packaged = Path(__file__).resolve().parent / "_harnesses"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "harnesses"


def current_platform() -> Platform:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


@lru_cache(maxsize=8)
def load_manifests(root: Path | None = None) -> dict[str, HarnessManifest]:
    """Parse every ``harnesses/*.toml``, keyed by harness id.

    Cached because the CLI, the bridge, and the UI server all load these and the
    files never change within a process.
    """
    manifest_root = root or default_manifest_root()
    manifests: dict[str, HarnessManifest] = {}
    if not manifest_root.is_dir():
        return manifests
    for path in sorted(manifest_root.glob("*.toml")):
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        manifest = parse_manifest(raw, source=path)
        if manifest.id != path.stem:
            raise ManifestError(f"{path}: id {manifest.id!r} does not match filename stem")
        manifests[manifest.id] = manifest
    return manifests


def parse_manifest(raw: dict[str, Any], *, source: Path | str = "<memory>") -> HarnessManifest:
    schema = raw.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise ManifestError(f"{source}: schema must be {MANIFEST_SCHEMA}, got {schema!r}")
    for key in ("id", "display_name"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ManifestError(f"{source}: missing required string field {key!r}")
    tier = raw.get("tier", "breadth")
    if tier not in TIERS:
        raise ManifestError(f"{source}: tier {tier!r} must be one of {', '.join(TIERS)}")

    detect_raw = raw.get("detect", {})
    if not isinstance(detect_raw, dict):
        raise ManifestError(f"{source}: [detect] must be a table")
    detect = Detect(
        commands=_str_tuple(detect_raw.get("commands"), source, "detect.commands"),
        client_names=_str_tuple(detect_raw.get("client_names"), source, "detect.client_names"),
        env=_str_tuple(detect_raw.get("env"), source, "detect.env"),
        paths=_platform_lists(detect_raw.get("paths"), source, "detect.paths"),
        apps=_platform_lists(detect_raw.get("apps"), source, "detect.apps"),
    )

    modes_raw = raw.get("modes", {})
    if not isinstance(modes_raw, dict):
        raise ManifestError(f"{source}: [modes] must be a table")
    modes: dict[str, InstallMode] = {}
    for mode_name, mode_raw in modes_raw.items():
        if mode_name not in INSTALL_MODES:
            raise ManifestError(
                f"{source}: unknown install mode {mode_name!r}; "
                f"expected one of {', '.join(INSTALL_MODES)}"
            )
        if not isinstance(mode_raw, dict):
            raise ManifestError(f"{source}: [modes.{mode_name}] must be a table")
        modes[mode_name] = _parse_mode(mode_name, mode_raw, source)

    return HarnessManifest(
        id=raw["id"],
        display_name=raw["display_name"],
        tier=tier,
        homepage=str(raw.get("homepage", "")),
        detect=detect,
        modes=modes,
        notes=_str_tuple(raw.get("notes"), source, "notes"),
    )


def _parse_mode(mode_name: str, raw: dict[str, Any], source: Path | str) -> InstallMode:
    setup_method = raw.get("setup_method", "")
    if setup_method not in SETUP_METHODS:
        raise ManifestError(
            f"{source}: [modes.{mode_name}] setup_method {setup_method!r} must be one of "
            f"{', '.join(SETUP_METHODS)}"
        )
    scopes = _str_tuple(raw.get("scopes"), source, f"modes.{mode_name}.scopes")
    default_scope = str(raw.get("default_scope", ""))
    if scopes and default_scope and default_scope not in scopes:
        raise ManifestError(
            f"{source}: [modes.{mode_name}] default_scope {default_scope!r} is not in scopes"
        )
    if setup_method == "command" and not raw.get("argv"):
        raise ManifestError(f"{source}: [modes.{mode_name}] setup_method=command requires argv")
    return InstallMode(
        mode=mode_name,
        setup_method=setup_method,
        config_path_display=str(raw.get("config_path", "")),
        config_format=str(raw.get("config_format", "json")),
        emitter=str(raw.get("emitter", "")),
        argv=_str_tuple(raw.get("argv"), source, f"modes.{mode_name}.argv"),
        write_path=_platform_strings(
            raw.get("write_path"), source, f"modes.{mode_name}.write_path"
        ),
        scope_paths=_string_map(raw.get("scope_paths"), source, f"modes.{mode_name}.scope_paths"),
        scopes=scopes,
        default_scope=default_scope,
        extra=dict(raw.get("extra", {})),
        skills_dirs=_platform_strings(raw.get("dir"), source, f"modes.{mode_name}.dir"),
        project_dir=str(raw.get("project_dir", "")),
        discovery=_str_tuple(raw.get("discovery"), source, f"modes.{mode_name}.discovery"),
        register_in=_string_map(
            raw.get("register_in"), source, f"modes.{mode_name}.register_in"
        ),
        notes=_str_tuple(raw.get("notes"), source, f"modes.{mode_name}.notes"),
    )


def _str_tuple(value: Any, source: Path | str, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestError(f"{source}: {label} must be a list of strings")
    return tuple(value)


def _platform_lists(
    value: Any, source: Path | str, label: str
) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ManifestError(f"{source}: {label} must be a table keyed by platform")
    result: dict[str, tuple[str, ...]] = {}
    for key, items in value.items():
        _check_platform_key(key, source, label)
        result[key] = _str_tuple(items, source, f"{label}.{key}")
    return result


def _platform_strings(value: Any, source: Path | str, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ManifestError(f"{source}: {label} must be a table keyed by platform")
    result: dict[str, str] = {}
    for key, item in value.items():
        _check_platform_key(key, source, label)
        if not isinstance(item, str):
            raise ManifestError(f"{source}: {label}.{key} must be a string")
        result[key] = item
    return result


def _string_map(value: Any, source: Path | str, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(item, str) for item in value.values()
    ):
        raise ManifestError(f"{source}: {label} must be a table of strings")
    return dict(value)


def _check_platform_key(key: str, source: Path | str, label: str) -> None:
    if key != "all" and key not in PLATFORMS:
        raise ManifestError(
            f"{source}: {label} key {key!r} must be 'all' or one of {', '.join(PLATFORMS)}"
        )


# --- lookups -------------------------------------------------------------


def harness_ids(root: Path | None = None) -> tuple[str, ...]:
    return tuple(load_manifests(root))


def manifest_for(harness: str, root: Path | None = None) -> HarnessManifest:
    manifests = load_manifests(root)
    if harness not in manifests:
        valid = ", ".join(sorted(manifests))
        raise ValueError(f"Unsupported harness {harness!r}; expected one of: {valid}")
    return manifests[harness]


def harness_for_client_name(name: str, root: Path | None = None) -> str | None:
    """Map an MCP ``clientInfo.name`` onto a harness id.

    Matching is case-insensitive and accepts the glob patterns manifests declare,
    because clients report names like ``claude-code`` and ``Claude Code`` and
    sometimes append a channel suffix.
    """
    if not name:
        return None
    needle = name.strip().casefold()
    for harness_id, manifest in load_manifests(root).items():
        for candidate in manifest.detect.client_names:
            pattern = candidate.casefold()
            if needle == pattern or fnmatch.fnmatch(needle, pattern):
                return harness_id
    return None


def skill_discovery_globs(
    root: Path | None = None, platform: str | None = None
) -> tuple[str, ...]:
    """Every skills directory any known harness reads from.

    Replaces ``dogfood.DEFAULT_SKILL_ROOTS``, which was a hardcoded three-entry
    tuple that notably did not include ``.claude/skills``.
    """
    resolved = platform or current_platform()
    globs: list[str] = []
    for manifest in load_manifests(root).values():
        mode = manifest.mode("skills")
        if mode is None:
            continue
        for candidate in (mode.skills_dir_for(resolved), *mode.discovery):
            if candidate and candidate not in globs:
                globs.append(candidate)
    return tuple(globs)
