"""Tests for ``skillroute harness doctor``.

The conformance tests here are parametrized over whatever is in ``harnesses/``,
matching ``test_harnesses.py``: a new manifest is checked automatically.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from skillroute.harness_doctor import (
    STATUS_FAIL,
    STATUS_OK,
    STATUS_SKIP,
    STATUS_WARN,
    DoctorCheck,
    DoctorReport,
    check_config,
    check_platform,
    check_render,
    probe_server,
    run_doctor,
    worst_status,
)
from skillroute.harness_setup import HarnessEnvironment
from skillroute.harnesses import current_platform, load_manifests

MANIFESTS = sorted(load_manifests())


def fake_server(tmp_path: Path, body: str) -> list[str]:
    """A stdio server stand-in, so the probe is exercised for real."""
    script = tmp_path / "fake_server.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


ANSWERS = """
    import json, sys
    sys.stdin.readline()
    sys.stdout.write(json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"serverInfo": {"name": "skillroute", "version": "0.2.0"}},
    }) + "\\n")
    sys.stdout.flush()
"""

CRASHES = """
    import sys
    sys.stderr.write("boom\\n")
    sys.exit(3)
"""

HANGS = """
    import time
    time.sleep(30)
"""

GARBAGE = """
    import sys
    sys.stdout.write("not json at all\\n")
    sys.stdout.flush()
"""

ERROR_REPLY = """
    import json, sys
    sys.stdin.readline()
    sys.stdout.write(json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "method not found"},
    }) + "\\n")
    sys.stdout.flush()
"""


# --- worst_status ---------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((), STATUS_OK),
        ((STATUS_OK, STATUS_OK), STATUS_OK),
        ((STATUS_OK, STATUS_SKIP), STATUS_OK),
        ((STATUS_OK, STATUS_WARN), STATUS_WARN),
        ((STATUS_WARN, STATUS_FAIL), STATUS_FAIL),
        ((STATUS_FAIL, STATUS_OK), STATUS_FAIL),
    ],
)
def test_worst_status(statuses: tuple[str, ...], expected: str) -> None:
    assert worst_status(statuses) == expected


# --- probe ----------------------------------------------------------------


def test_probe_accepts_a_server_that_answers_initialize(tmp_path: Path) -> None:
    check = probe_server(fake_server(tmp_path, ANSWERS), env={}, timeout=10.0)
    assert check.status == STATUS_OK
    assert "skillroute" in check.detail


def test_probe_fails_when_the_server_exits_nonzero(tmp_path: Path) -> None:
    check = probe_server(fake_server(tmp_path, CRASHES), env={}, timeout=10.0)
    assert check.status == STATUS_FAIL
    assert "exit" in check.detail.lower()


def test_probe_fails_when_the_server_hangs(tmp_path: Path) -> None:
    check = probe_server(fake_server(tmp_path, HANGS), env={}, timeout=0.5)
    assert check.status == STATUS_FAIL
    assert "did not answer" in check.detail


def test_probe_fails_on_non_json_output(tmp_path: Path) -> None:
    check = probe_server(fake_server(tmp_path, GARBAGE), env={}, timeout=10.0)
    assert check.status == STATUS_FAIL


def test_probe_fails_on_a_jsonrpc_error_reply(tmp_path: Path) -> None:
    check = probe_server(fake_server(tmp_path, ERROR_REPLY), env={}, timeout=10.0)
    assert check.status == STATUS_FAIL
    assert "method not found" in check.detail


def test_probe_fails_when_the_command_is_missing(tmp_path: Path) -> None:
    check = probe_server(["definitely-not-a-real-binary-xyz"], env={}, timeout=5.0)
    assert check.status == STATUS_FAIL


# --- platform coverage ----------------------------------------------------


@pytest.mark.parametrize("harness", MANIFESTS)
def test_every_manifest_has_a_path_on_this_platform(harness: str) -> None:
    """The macOS-only detection bug in v0.1, as a standing check."""
    manifest = load_manifests()[harness]
    check = check_platform(manifest, current_platform())
    assert check.status != STATUS_FAIL, check.detail


def test_platform_check_fails_when_no_path_is_declared() -> None:
    from skillroute.harnesses import parse_manifest

    manifest = parse_manifest(
        {
            "schema": 1,
            "id": "ghost",
            "display_name": "Ghost",
            "modes": {
                "mcp": {
                    "setup_method": "json_merge",
                    "emitter": "mcp_servers",
                    "write_path": {"macos": "~/.ghost/mcp.json"},
                }
            },
        }
    )
    assert check_platform(manifest, "macos").status == STATUS_OK
    assert check_platform(manifest, "linux").status == STATUS_FAIL


# --- render ---------------------------------------------------------------


@pytest.mark.parametrize("harness", MANIFESTS)
def test_every_mode_of_every_manifest_renders(harness: str, tmp_path: Path) -> None:
    """Placeholder drift is a fail, not a traceback at a user's terminal."""
    for check in check_render(harness, repo_root=tmp_path, catalog=tmp_path / "c.db"):
        assert check.status != STATUS_FAIL, f"{harness}: {check.detail}"


# --- config ---------------------------------------------------------------


def test_config_check_warns_when_the_file_is_absent(tmp_path: Path) -> None:
    check = check_config(tmp_path / "nope.json", server_name="skillroute", config_format="json")
    assert check.status == STATUS_WARN
    assert "not configured" in check.detail


def test_config_check_passes_when_the_server_entry_is_present(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"skillroute": {"command": "node"}}}), "utf-8")
    assert check_config(path, server_name="skillroute", config_format="json").status == STATUS_OK


def test_config_check_warns_when_another_server_is_configured(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "node"}}}), "utf-8")
    check = check_config(path, server_name="skillroute", config_format="json")
    assert check.status == STATUS_WARN


def test_config_check_fails_on_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("{not json", encoding="utf-8")
    check = check_config(path, server_name="skillroute", config_format="json")
    assert check.status == STATUS_FAIL
    assert "parse" in check.detail.lower()


def test_config_check_skips_non_json_formats(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("mcp_servers: {}", encoding="utf-8")
    check = check_config(path, server_name="skillroute", config_format="yaml")
    assert check.status == STATUS_SKIP


# --- end to end -----------------------------------------------------------


def test_run_doctor_reports_every_requested_harness(tmp_path: Path) -> None:
    reports = run_doctor(
        ["claude-code", "codex"],
        env=HarnessEnvironment(home=tmp_path, commands={}, existing_paths=set()),
        repo_root=tmp_path,
        catalog=tmp_path / "catalog.db",
        probe=False,
    )
    assert [report.harness for report in reports] == ["claude-code", "codex"]
    for report in reports:
        assert report.checks
        assert report.status in {STATUS_OK, STATUS_WARN, STATUS_FAIL}


def test_run_doctor_marks_an_absent_harness_as_a_warning_not_a_failure(
    tmp_path: Path,
) -> None:
    (report,) = run_doctor(
        ["claude-code"],
        env=HarnessEnvironment(home=tmp_path, commands={}, existing_paths=set()),
        repo_root=tmp_path,
        catalog=tmp_path / "catalog.db",
        probe=False,
    )
    assert report.status == STATUS_WARN
    detect = next(check for check in report.checks if check.name == "detect")
    assert detect.status == STATUS_WARN


def test_run_doctor_skips_the_probe_when_asked(tmp_path: Path) -> None:
    (report,) = run_doctor(
        ["claude-code"],
        env=HarnessEnvironment(home=tmp_path, commands={}, existing_paths=set()),
        repo_root=tmp_path,
        catalog=tmp_path / "catalog.db",
        probe=False,
    )
    probe = next((check for check in report.checks if check.name == "server"), None)
    assert probe is None or probe.status == STATUS_SKIP


def test_run_doctor_rejects_an_unknown_harness(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nope"):
        run_doctor(["nope"], repo_root=tmp_path, probe=False)


def test_doctor_report_is_json_serializable(tmp_path: Path) -> None:
    reports = run_doctor(
        ["claude-code"],
        env=HarnessEnvironment(home=tmp_path, commands={}, existing_paths=set()),
        repo_root=tmp_path,
        catalog=tmp_path / "catalog.db",
        probe=False,
    )
    payload = json.dumps([report.to_dict() for report in reports])
    restored = json.loads(payload)
    assert restored[0]["harness"] == "claude-code"
    assert isinstance(restored[0]["checks"], list)


def test_report_status_is_the_worst_check() -> None:
    report = DoctorReport(
        harness="x",
        name="X",
        checks=(
            DoctorCheck("a", STATUS_OK, ""),
            DoctorCheck("b", STATUS_FAIL, ""),
            DoctorCheck("c", STATUS_WARN, ""),
        ),
    )
    assert report.status == STATUS_FAIL
