"""Verify that a harness pack still describes reality.

The manifests in ``harnesses/`` encode config paths for fourteen tools that each
move on their own schedule. A path that was right when the pack was written is
the kind of thing that rots silently: ``harness install`` keeps reporting
success while writing to a file the tool no longer reads.

``skillroute harness doctor`` is the check that catches that. It walks a pack
end to end -- the manifest declares a path on this platform, every mode still
renders, the config on disk actually names our server -- and then does the part
that cannot be faked by inspection: it runs the configured server command and
confirms it answers an MCP ``initialize`` handshake.

Statuses are deliberately four-valued. Not having a tool installed is not a
failure (you can doctor a pack for a harness you do not use), so absence is a
warning and only real breakage is a failure.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skillroute.catalog import default_catalog_path
from skillroute.harness_render import build_harness_setup, default_repo_root
from skillroute.harness_setup import HarnessDetection, HarnessEnvironment, detect_harness
from skillroute.harnesses import (
    HarnessManifest,
    load_manifests,
    manifest_for,
)

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"

# Ordered by severity; worst_status() takes the max.
_SEVERITY = {STATUS_SKIP: 0, STATUS_OK: 1, STATUS_WARN: 2, STATUS_FAIL: 3}

DEFAULT_PROBE_TIMEOUT = 20.0

# Minimal MCP handshake. We send `initialize` and then EOF: a stdio server
# answers and exits on a closed stdin, which lets one communicate() call cover
# both the reply and the timeout without a reader thread.
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "skillroute-doctor", "version": "1"},
    },
}


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class DoctorReport:
    harness: str
    name: str
    checks: tuple[DoctorCheck, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        return worst_status(check.status for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness": self.harness,
            "name": self.name,
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
        }


def worst_status(statuses: Any) -> str:
    """The most severe status present, defaulting to ok for an empty run."""
    worst = STATUS_OK
    for status in statuses:
        if _SEVERITY.get(status, 0) > _SEVERITY[worst]:
            worst = status
    return worst


# --- individual checks ----------------------------------------------------


def check_manifest(manifest: HarnessManifest) -> DoctorCheck:
    if not manifest.modes:
        return DoctorCheck("manifest", STATUS_FAIL, "declares no install modes")
    modes = ", ".join(sorted(manifest.modes))
    if manifest.tier == "unverified":
        return DoctorCheck(
            "manifest", STATUS_WARN, f"tier=unverified; modes: {modes}"
        )
    return DoctorCheck("manifest", STATUS_OK, f"tier={manifest.tier}; modes: {modes}")


def check_platform(manifest: HarnessManifest, platform: str) -> DoctorCheck:
    """Every mode that writes a file must name a path for this platform.

    v0.1 detection was macOS-only. Encoding that as a check means a pack that
    quietly omits Linux or Windows is caught by CI on that platform rather than
    by a user.
    """
    missing = []
    for name, mode in sorted(manifest.modes.items()):
        # `command` and `print_only` modes drive the harness's own CLI or just
        # print a snippet, so they legitimately have no path of ours to write.
        if mode.setup_method in {"command", "print_only", "package"}:
            continue
        if not mode.path_for(platform) and not mode.skills_dir_for(platform):
            missing.append(name)
    if missing:
        return DoctorCheck(
            "platform",
            STATUS_FAIL,
            f"no {platform} path for mode(s): {', '.join(missing)}",
        )
    return DoctorCheck("platform", STATUS_OK, f"paths declared for {platform}")


def check_detect(detection: HarnessDetection) -> DoctorCheck:
    if detection.detected:
        return DoctorCheck("detect", STATUS_OK, detection.reason)
    # Not installed is a fact about this machine, not a defect in the pack.
    return DoctorCheck("detect", STATUS_WARN, f"not installed ({detection.reason})")


def check_render(
    harness: str,
    *,
    repo_root: Path,
    catalog: Path | None = None,
    backend: str | None = None,
    server_name: str = "skillroute",
    platform: str | None = None,
) -> list[DoctorCheck]:
    """Render every declared mode; an unresolvable placeholder is a failure."""
    manifest = manifest_for(harness)
    checks: list[DoctorCheck] = []
    for mode in sorted(manifest.modes):
        try:
            build_harness_setup(
                harness=harness,
                mode=mode,
                repo_root=repo_root,
                catalog=catalog,
                backend=backend,
                server_name=server_name,
                platform=platform,
            )
        except Exception as exc:  # noqa: BLE001 -- any render failure is a pack defect
            checks.append(
                DoctorCheck(f"render:{mode}", STATUS_FAIL, f"{type(exc).__name__}: {exc}")
            )
        else:
            checks.append(DoctorCheck(f"render:{mode}", STATUS_OK, "renders"))
    return checks


def check_config(path: Path, *, server_name: str, config_format: str) -> DoctorCheck:
    """Does the on-disk config actually name our server?

    This is the check that catches a path the harness stopped reading: install
    reports success, the file exists, and the tool never sees it. We can only
    assert this for JSON; YAML and TOML configs are reported as unverified
    rather than guessed at.
    """
    if config_format != "json":
        return DoctorCheck(
            "config", STATUS_SKIP, f"{config_format} config not inspected"
        )
    if not path.exists():
        return DoctorCheck("config", STATUS_WARN, f"not configured yet: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        return DoctorCheck("config", STATUS_FAIL, f"cannot parse {path}: {exc}")
    if not isinstance(raw, dict):
        return DoctorCheck("config", STATUS_FAIL, f"cannot parse {path}: not an object")
    if _names_server(raw, server_name):
        return DoctorCheck("config", STATUS_OK, f"{server_name} present in {path}")
    return DoctorCheck(
        "config", STATUS_WARN, f"{server_name} not found in {path}"
    )


def _names_server(raw: Any, server_name: str) -> bool:
    """Look for the server key anywhere; emitters nest it under varying roots."""
    if isinstance(raw, dict):
        if server_name in raw:
            return True
        return any(_names_server(value, server_name) for value in raw.values())
    if isinstance(raw, list):
        return any(_names_server(item, server_name) for item in raw)
    return False


def probe_server(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> DoctorCheck:
    """Run the configured server and confirm it answers ``initialize``.

    This is the only check that proves the config points at something that
    works, rather than at a path that merely exists.
    """
    if not argv:
        return DoctorCheck("server", STATUS_SKIP, "no server command to probe")
    request = json.dumps(_INITIALIZE) + "\n"
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **env},
        )
    except (OSError, ValueError) as exc:
        return DoctorCheck("server", STATUS_FAIL, f"cannot start {argv[0]}: {exc}")

    try:
        stdout, stderr = process.communicate(input=request, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return DoctorCheck(
            "server", STATUS_FAIL, f"did not answer initialize within {timeout:g}s"
        )

    reply = _first_json_object(stdout)
    if reply is None:
        summary = _error_summary(stderr or stdout)
        if process.returncode:
            return DoctorCheck(
                "server", STATUS_FAIL, f"exit {process.returncode}: {summary}"
            )
        return DoctorCheck("server", STATUS_FAIL, f"no JSON-RPC reply: {summary}")
    if "error" in reply:
        message = reply["error"].get("message", "unknown error")
        return DoctorCheck("server", STATUS_FAIL, f"initialize failed: {message}")
    info = (reply.get("result") or {}).get("serverInfo") or {}
    label = " ".join(part for part in (info.get("name"), info.get("version")) if part)
    return DoctorCheck("server", STATUS_OK, f"answered initialize: {label or 'ok'}")


def _error_summary(stream: str) -> str:
    """Pick the most diagnostic line from a failed server's output.

    Node prints ``Error: Cannot find module ...`` and then several lines of
    version banner, so the last line is the least useful thing available.
    """
    lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
    if not lines:
        return "no output"
    for line in lines:
        if "error" in line.casefold():
            return line
    return lines[0]


def _first_json_object(stream: str) -> dict[str, Any] | None:
    for line in (stream or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# --- driver ---------------------------------------------------------------


def run_doctor(
    harnesses: list[str] | tuple[str, ...] | None = None,
    *,
    env: HarnessEnvironment | None = None,
    repo_root: Path | None = None,
    catalog: Path | None = None,
    backend: str | None = None,
    server_name: str = "skillroute",
    mode: str = "mcp",
    probe: bool = True,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> list[DoctorReport]:
    """Check one or more harness packs. Empty selection means every pack."""
    manifests = load_manifests()
    selected = list(harnesses) if harnesses else sorted(manifests)
    unknown = [item for item in selected if item not in manifests]
    if unknown:
        valid = ", ".join(sorted(manifests))
        raise ValueError(
            f"Unsupported harness {', '.join(unknown)!r}; expected one of: {valid}"
        )

    env = env or HarnessEnvironment()
    resolved_root = (repo_root or default_repo_root()).expanduser().resolve()
    resolved_catalog = (
        catalog.expanduser().resolve() if catalog else default_catalog_path(resolved_root)
    )

    reports: list[DoctorReport] = []
    for harness in selected:
        manifest = manifests[harness]
        detection = detect_harness(manifest, env)
        checks: list[DoctorCheck] = [
            check_manifest(manifest),
            check_platform(manifest, env.platform),
            check_detect(detection),
        ]
        checks.extend(
            check_render(
                harness,
                repo_root=resolved_root,
                catalog=resolved_catalog,
                backend=backend,
                server_name=server_name,
                platform=env.platform,
            )
        )
        checks.append(
            _config_check_for(manifest, detection, mode=mode, server_name=server_name)
        )
        checks.append(
            _probe_check_for(
                harness,
                detection,
                mode=mode,
                repo_root=resolved_root,
                catalog=resolved_catalog,
                backend=backend,
                server_name=server_name,
                probe=probe,
                timeout=timeout,
            )
        )
        reports.append(
            DoctorReport(harness=harness, name=manifest.display_name, checks=tuple(checks))
        )
    return reports


def _config_check_for(
    manifest: HarnessManifest,
    detection: HarnessDetection,
    *,
    mode: str,
    server_name: str,
) -> DoctorCheck:
    install = manifest.mode(mode)
    if install is None:
        return DoctorCheck("config", STATUS_SKIP, f"no {mode} mode")
    if detection.config_path is None:
        return DoctorCheck("config", STATUS_SKIP, "no config path on this platform")
    return check_config(
        Path(detection.config_path),
        server_name=server_name,
        config_format=install.config_format,
    )


def _probe_check_for(
    harness: str,
    detection: HarnessDetection,
    *,
    mode: str,
    repo_root: Path,
    catalog: Path,
    backend: str | None,
    server_name: str,
    probe: bool,
    timeout: float,
) -> DoctorCheck:
    if not probe:
        return DoctorCheck("server", STATUS_SKIP, "probe disabled")
    if not detection.detected:
        return DoctorCheck("server", STATUS_SKIP, "harness not installed")
    try:
        payload = build_harness_setup(
            harness=harness,
            mode=mode,
            repo_root=repo_root,
            catalog=catalog,
            backend=backend,
            server_name=server_name,
        )
    except Exception as exc:  # noqa: BLE001 -- already reported by check_render
        return DoctorCheck("server", STATUS_SKIP, f"cannot build config: {exc}")
    server = payload.get("server_config") or {}
    command = server.get("command")
    if not command:
        return DoctorCheck("server", STATUS_SKIP, "no stdio server command")
    argv = [command, *server.get("args", [])]
    return probe_server(argv, env=dict(server.get("env") or {}), timeout=timeout)


def render_doctor_reports(reports: list[DoctorReport]) -> str:
    """Plain-text rendering. Kept here so the CLI stays a thin caller."""
    marks = {STATUS_OK: "ok", STATUS_WARN: "warn", STATUS_FAIL: "FAIL", STATUS_SKIP: "--"}
    lines: list[str] = []
    for report in reports:
        lines.append(f"{report.name} ({report.harness}): {marks[report.status]}")
        width = max((len(check.name) for check in report.checks), default=0)
        for check in report.checks:
            lines.append(
                f"  {marks[check.status]:<4} {check.name:<{width}}  {check.detail}"
            )
        lines.append("")
    failed = [report.harness for report in reports if report.status == STATUS_FAIL]
    if failed:
        lines.append(f"{len(failed)} harness(es) failed: {', '.join(failed)}")
    else:
        lines.append(f"{len(reports)} harness(es) checked, no failures.")
    return "\n".join(lines)
