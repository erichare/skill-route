from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from skillroute import client_setup
from skillroute.client_setup import (
    ClientDetection,
    ClientEnvironment,
    NO_TTY_SETUP_MESSAGE,
    apply_client_setup,
    detect_clients,
    merge_json_config,
    run_detect_command,
    run_setup_command,
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


def test_setup_command_skips_prompt_mode_without_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    detection = ClientDetection(
        "codex",
        "Codex",
        True,
        "found /bin/codex",
        "command",
        command="/bin/codex",
    )

    monkeypatch.setattr("skillroute.client_setup.detect_clients", lambda _env: [detection])
    monkeypatch.setattr("skillroute.client_setup.can_prompt", lambda: False)

    def fail_setup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("client setup should not run without a promptable terminal")

    monkeypatch.setattr("skillroute.client_setup.apply_client_setup", fail_setup)

    run_setup_command(
        Namespace(
            repo_root=tmp_path / "repo",
            catalog=None,
            backend=None,
            clients="auto",
            mode="prompt",
            yes=False,
        )
    )

    output = capsys.readouterr().out
    assert "Detected agent clients:" in output
    assert NO_TTY_SETUP_MESSAGE in output

def test_apply_json_merge_client_writes_config(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = tmp_path / "bob" / "mcp.json"
    detection = ClientDetection(
        "ibm-bob", "IBM Bob", True, "found", "json_merge", config_path=str(config_path)
    )

    result = apply_client_setup(
        detection,
        repo_root=repo_root,
        catalog=tmp_path / "catalog.db",
        yes=True,
    )

    assert result.status == "configured"
    assert result.backup_path is None
    assert config_path.exists()


def test_apply_client_setup_mode_zero_skips_without_writing(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    detection = ClientDetection(
        "ibm-bob", "IBM Bob", True, "found", "json_merge", config_path=str(config_path)
    )

    result = apply_client_setup(detection, repo_root=tmp_path, mode="0")

    assert result.status == "skipped"
    assert result.message == "client setup disabled"
    assert not config_path.exists()


def test_merge_json_config_rejects_non_object_existing(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError, match="not a JSON object"):
        merge_json_config(config_path, {"mcpServers": {}})


def test_merge_json_config_rejects_non_object_field(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({"mcpServers": "oops"}), encoding="utf-8")

    with pytest.raises(ValueError, match="not an object"):
        merge_json_config(config_path, {"mcpServers": {"skillroute": {}}})


def test_merge_json_config_sets_scalar_values_without_backup(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"

    backup = merge_json_config(config_path, {"schemaVersion": 2})

    assert backup is None
    assert json.loads(config_path.read_text(encoding="utf-8"))["schemaVersion"] == 2


def test_run_detect_command_json_lists_all_clients(capsys: pytest.CaptureFixture[str]) -> None:
    run_detect_command(Namespace(as_json=True))

    payload = json.loads(capsys.readouterr().out)
    assert {entry["id"] for entry in payload} == {
        "ibm-bob",
        "codex",
        "claude-code",
        "claude-desktop",
        "vscode",
        "windsurf",
        "cursor",
    }


def test_client_setup_module_main_detect_json(capsys: pytest.CaptureFixture[str]) -> None:
    client_setup.main(["detect", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert any(entry["id"] == "ibm-bob" for entry in payload)


def test_run_setup_command_applies_all_clients_in_disabled_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_setup_command(
        Namespace(
            repo_root=tmp_path / "repo",
            catalog=tmp_path / "catalog.db",
            backend=None,
            clients="all",
            mode="0",
            yes=False,
        )
    )

    output = capsys.readouterr().out
    assert "Detected agent clients:" in output
    assert "skipped - client setup disabled" in output
