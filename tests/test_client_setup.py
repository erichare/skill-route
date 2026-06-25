from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from skillroute.client_setup import (
    ClientDetection,
    ClientEnvironment,
    apply_client_setup,
    detect_clients,
    merge_json_config,
    select_clients,
)


def test_detect_clients_uses_commands_and_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bob_config = home / ".bob" / "mcp.json"
    windsurf_config = home / ".codeium" / "windsurf" / "mcp_config.json"
    env = ClientEnvironment(
        home=home,
        commands={
            "codex": "/usr/local/bin/codex",
            "claude": None,
            "code": None,
            "code-insiders": "/usr/local/bin/code-insiders",
            "windsurf": None,
            "cursor": "/usr/local/bin/cursor",
        },
        existing_paths={bob_config, Path("/Applications/Claude.app"), windsurf_config},
    )

    detections = {detection.id: detection for detection in detect_clients(env)}

    assert detections["ibm-bob"].detected is True
    assert detections["codex"].command == "/usr/local/bin/codex"
    assert detections["claude-code"].detected is False
    assert detections["claude-desktop"].detected is True
    assert detections["vscode"].command == "/usr/local/bin/code-insiders"
    assert detections["windsurf"].detected is True
    assert detections["cursor"].setup_method == "print_only"


def test_select_clients_auto_all_and_requested(tmp_path: Path) -> None:
    env = ClientEnvironment(
        home=tmp_path,
        commands={"codex": "/bin/codex"},
        existing_paths=set(),
    )
    detections = detect_clients(env)

    assert [detection.id for detection in select_clients("auto", detections)] == ["codex"]
    assert [detection.id for detection in select_clients("codex,cursor", detections)] == ["codex", "cursor"]
    assert len(select_clients("all", detections)) == 7
    with pytest.raises(SystemExit):
        select_clients("not-a-client", detections)


def test_merge_json_config_preserves_existing_servers_and_creates_backup(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"existing": {"command": "node"}}, "theme": "dark"}),
        encoding="utf-8",
    )

    backup_path = merge_json_config(
        config_path,
        {"mcpServers": {"skillroute": {"command": "node", "args": ["mcp/build/index.js"]}}},
    )

    merged = json.loads(config_path.read_text(encoding="utf-8"))
    assert backup_path is not None
    assert backup_path.exists()
    assert merged["mcpServers"]["existing"]["command"] == "node"
    assert merged["mcpServers"]["skillroute"]["args"] == ["mcp/build/index.js"]
    assert merged["theme"] == "dark"


def test_apply_cursor_setup_prints_snippet_without_writing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    cursor_config = tmp_path / "cursor" / "mcp.json"
    detection = ClientDetection(
        "cursor",
        "Cursor",
        True,
        "found cursor",
        "print_only",
        command="/bin/cursor",
        config_path=str(cursor_config),
    )

    result = apply_client_setup(
        detection,
        repo_root=repo_root,
        catalog=tmp_path / "catalog.db",
        mode="1",
    )

    assert result.status == "printed"
    assert '"mcpServers"' in result.message
    assert not cursor_config.exists()


def test_apply_vscode_setup_uses_detected_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command_parts: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append((command_parts, check))
        return subprocess.CompletedProcess(command_parts, 0)

    monkeypatch.setattr("skillroute.client_setup.subprocess.run", fake_run)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    detection = ClientDetection(
        "vscode",
        "VS Code",
        True,
        "found code-insiders",
        "command",
        command="/usr/local/bin/code-insiders",
    )

    result = apply_client_setup(
        detection,
        repo_root=repo_root,
        catalog=tmp_path / "catalog.db",
        mode="1",
    )

    assert result.status == "configured"
    assert calls[0][0][0] == "/usr/local/bin/code-insiders"
    assert calls[0][0][1] == "--add-mcp"
    assert calls[0][1] is True


def test_apply_missing_command_client_skips_without_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run should not be called for a missing command client")

    monkeypatch.setattr("skillroute.client_setup.subprocess.run", fake_run)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    detection = ClientDetection(
        "codex",
        "Codex",
        False,
        "codex command not found",
        "command",
        command="codex",
    )

    result = apply_client_setup(
        detection,
        repo_root=repo_root,
        catalog=tmp_path / "catalog.db",
        mode="1",
    )

    assert result.status == "skipped"
    assert result.message == "codex command not found"
