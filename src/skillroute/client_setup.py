from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from skillroute.catalog import default_catalog_path
from skillroute.mcp_setup import MCP_CLIENT_CHOICES, build_mcp_setup


CLIENT_ORDER = (
    "ibm-bob",
    "codex",
    "claude-code",
    "claude-desktop",
    "vscode",
    "windsurf",
    "cursor",
)
CLIENT_SETUP_CHOICES = ("prompt", "0", "1")


@dataclass(frozen=True, slots=True)
class ClientDetection:
    id: str
    name: str
    detected: bool
    reason: str
    setup_method: str
    command: str | None = None
    config_path: str | None = None


@dataclass(frozen=True, slots=True)
class SetupResult:
    client: str
    status: str
    message: str
    backup_path: str | None = None


class ClientEnvironment:
    def __init__(
        self,
        *,
        home: Path | None = None,
        commands: dict[str, str | None] | None = None,
        existing_paths: set[Path] | None = None,
    ) -> None:
        self.home = (home or Path.home()).expanduser()
        self._commands = commands
        self._existing_paths = {path.expanduser() for path in existing_paths} if existing_paths is not None else None

    def which(self, command: str) -> str | None:
        if self._commands is not None:
            return self._commands.get(command)
        return shutil.which(command)

    def exists(self, path: Path) -> bool:
        expanded = path.expanduser()
        if self._existing_paths is not None:
            return expanded in self._existing_paths
        return expanded.exists()

    def bob_config_path(self) -> Path:
        return self.home / ".bob" / "mcp.json"

    def claude_desktop_config_path(self) -> Path:
        return self.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"

    def windsurf_config_path(self) -> Path:
        return self.home / ".codeium" / "windsurf" / "mcp_config.json"

    def cursor_config_path(self) -> Path:
        return self.home / ".cursor" / "mcp.json"


def detect_clients(env: ClientEnvironment | None = None) -> list[ClientDetection]:
    env = env or ClientEnvironment()
    detections = [
        detect_bob(env),
        detect_codex(env),
        detect_claude_code(env),
        detect_claude_desktop(env),
        detect_vscode(env),
        detect_windsurf(env),
        detect_cursor(env),
    ]
    return sorted(detections, key=lambda detection: CLIENT_ORDER.index(detection.id))


def detect_bob(env: ClientEnvironment) -> ClientDetection:
    config_path = env.bob_config_path()
    app_path = Path("/Applications/IBM Bob.app")
    detected = env.exists(config_path) or env.exists(app_path)
    reason = (
        f"found {config_path if env.exists(config_path) else app_path}"
        if detected
        else "not found"
    )
    return ClientDetection("ibm-bob", "IBM Bob", detected, reason, "json_merge", config_path=str(config_path))


def detect_codex(env: ClientEnvironment) -> ClientDetection:
    command = env.which("codex")
    return ClientDetection(
        "codex",
        "Codex",
        bool(command),
        f"found {command}" if command else "codex command not found",
        "command",
        command=command,
    )


def detect_claude_code(env: ClientEnvironment) -> ClientDetection:
    command = env.which("claude")
    return ClientDetection(
        "claude-code",
        "Claude Code",
        bool(command),
        f"found {command}" if command else "claude command not found",
        "command",
        command=command,
    )


def detect_claude_desktop(env: ClientEnvironment) -> ClientDetection:
    config_path = env.claude_desktop_config_path()
    app_path = Path("/Applications/Claude.app")
    detected = env.exists(config_path) or env.exists(app_path)
    reason = (
        f"found {config_path if env.exists(config_path) else app_path}"
        if detected
        else "not found"
    )
    return ClientDetection(
        "claude-desktop",
        "Claude Desktop",
        detected,
        reason,
        "json_merge",
        config_path=str(config_path),
    )


def detect_vscode(env: ClientEnvironment) -> ClientDetection:
    command = env.which("code") or env.which("code-insiders")
    return ClientDetection(
        "vscode",
        "VS Code",
        bool(command),
        f"found {command}" if command else "code/code-insiders command not found",
        "command",
        command=command,
    )


def detect_windsurf(env: ClientEnvironment) -> ClientDetection:
    config_path = env.windsurf_config_path()
    app_path = Path("/Applications/Windsurf.app")
    command = env.which("windsurf")
    detected = bool(command) or env.exists(config_path) or env.exists(app_path)
    if command:
        reason = f"found {command}"
    elif env.exists(config_path):
        reason = f"found {config_path}"
    elif env.exists(app_path):
        reason = f"found {app_path}"
    else:
        reason = "not found"
    return ClientDetection("windsurf", "Windsurf", detected, reason, "json_merge", config_path=str(config_path))


def detect_cursor(env: ClientEnvironment) -> ClientDetection:
    config_path = env.cursor_config_path()
    app_path = Path("/Applications/Cursor.app")
    command = env.which("cursor")
    detected = bool(command) or env.exists(config_path) or env.exists(app_path)
    if command:
        reason = f"found {command}"
    elif env.exists(config_path):
        reason = f"found {config_path}"
    elif env.exists(app_path):
        reason = f"found {app_path}"
    else:
        reason = "not found"
    return ClientDetection(
        "cursor",
        "Cursor",
        detected,
        reason,
        "print_only",
        command=command,
        config_path=str(config_path),
    )


def select_clients(client_spec: str, detections: list[ClientDetection]) -> list[ClientDetection]:
    by_id = {detection.id: detection for detection in detections}
    if client_spec == "auto":
        return [detection for detection in detections if detection.detected]
    if client_spec == "all":
        return detections
    requested = [client.strip() for client in client_spec.split(",") if client.strip()]
    unknown = sorted(set(requested) - set(MCP_CLIENT_CHOICES))
    if unknown:
        valid = ", ".join(MCP_CLIENT_CHOICES)
        raise SystemExit(f"Unknown client(s): {', '.join(unknown)}. Expected: auto, all, or one of {valid}.")
    return [by_id[client] for client in requested]


def apply_client_setup(
    detection: ClientDetection,
    *,
    repo_root: Path,
    catalog: Path | None = None,
    backend: str | None = None,
    server_name: str = "skillroute",
    yes: bool = False,
    mode: str = "prompt",
) -> SetupResult:
    if mode == "0":
        return SetupResult(detection.id, "skipped", "client setup disabled")
    payload = build_mcp_setup(
        client=detection.id,
        repo_root=repo_root,
        catalog=catalog,
        backend=backend,
        server_name=server_name,
    )
    if payload["setup_method"] == "print_only":
        return SetupResult(detection.id, "printed", json.dumps(payload["config"], indent=2, sort_keys=True))
    if mode == "prompt" and not yes and not confirm(f"Set up {detection.name} for SkillRoute"):
        return SetupResult(detection.id, "skipped", "user skipped setup")
    if payload["setup_method"] == "command":
        if not detection.detected:
            return SetupResult(detection.id, "skipped", detection.reason)
        command_parts = list(payload["install_command_parts"])
        if detection.id == "vscode" and detection.command:
            command_parts[0] = detection.command
        subprocess.run(command_parts, check=True)
        return SetupResult(detection.id, "configured", payload["install_command"])
    if detection.config_path is None:
        return SetupResult(detection.id, "skipped", "no config path available")
    backup_path = merge_json_config(Path(detection.config_path), payload["config"])
    message = f"wrote {detection.config_path}"
    return SetupResult(detection.id, "configured", message, backup_path=str(backup_path) if backup_path else None)


def merge_json_config(path: Path, incoming: dict[str, Any]) -> Path | None:
    path = path.expanduser()
    existing: dict[str, Any] = {}
    backup_path: Path | None = None
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8") or "{}")
        if not isinstance(existing, dict):
            raise ValueError(f"Existing config is not a JSON object: {path}")
        timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
        shutil.copy2(path, backup_path)

    for key, value in incoming.items():
        if isinstance(value, dict):
            target = existing.setdefault(key, {})
            if not isinstance(target, dict):
                raise ValueError(f"Existing config field is not an object: {key}")
            target.update(value)
        else:
            existing[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return backup_path


def confirm(prompt: str) -> bool:
    try:
        tty = open("/dev/tty", "r+", encoding="utf-8")
    except OSError as exc:
        raise SystemExit("No terminal is available for prompts. Re-run with --yes or SKILLROUTE_CLIENT_SETUP=1.") from exc
    with tty:
        tty.write(f"? {prompt} [y/N] ")
        tty.flush()
        reply = tty.readline().strip().lower()
    return reply in {"y", "yes"}


def print_detection_summary(detections: list[ClientDetection]) -> None:
    print("Detected agent clients:")
    for detection in detections:
        marker = "found" if detection.detected else "missing"
        print(f"- {detection.name}: {marker} ({detection.reason})")


def run_setup_command(args: argparse.Namespace) -> None:
    env = ClientEnvironment()
    detections = detect_clients(env)
    print_detection_summary(detections)
    selected = select_clients(args.clients, detections)
    if not selected:
        print("No clients selected for setup.")
        return
    repo_root = args.repo_root.expanduser().resolve()
    catalog = args.catalog.expanduser().resolve() if args.catalog else default_catalog_path(repo_root)
    for detection in selected:
        if args.clients == "auto" and not detection.detected:
            continue
        result = apply_client_setup(
            detection,
            repo_root=repo_root,
            catalog=catalog,
            backend=args.backend,
            yes=args.yes,
            mode=args.mode,
        )
        print(f"{detection.name}: {result.status} - {result.message}")
        if result.backup_path:
            print(f"{detection.name}: backup - {result.backup_path}")


def run_detect_command(args: argparse.Namespace) -> None:
    detections = detect_clients(ClientEnvironment())
    if args.as_json:
        print(json.dumps([asdict(detection) for detection in detections], indent=2, sort_keys=True))
        return
    print_detection_summary(detections)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m skillroute.client_setup")
    subparsers = parser.add_subparsers(dest="command", required=True)
    detect_parser = subparsers.add_parser("detect", help="Detect supported agent clients")
    detect_parser.add_argument("--json", action="store_true", dest="as_json")
    detect_parser.set_defaults(func=run_detect_command)

    setup_parser = subparsers.add_parser("setup", help="Detect and optionally configure agent clients")
    setup_parser.add_argument("--repo-root", type=Path, required=True)
    setup_parser.add_argument("--catalog", type=Path, default=None)
    setup_parser.add_argument("--backend", default=None)
    setup_parser.add_argument("--clients", default="auto")
    setup_parser.add_argument("--mode", choices=CLIENT_SETUP_CHOICES, default="prompt")
    setup_parser.add_argument("--yes", action="store_true")
    setup_parser.set_defaults(func=run_setup_command)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
