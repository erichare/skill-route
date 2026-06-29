from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from skillroute.backends import AstraDataAPIBackend
from skillroute.cli import (
    clamp_limit,
    main,
    parse_options_json,
    require_payload_key,
)


def test_cli_index_and_route_json(tmp_path: Path, fixture_skills_root: Path, capsys) -> None:
    catalog_path = tmp_path / "catalog.db"

    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    main(
        [
            "--catalog",
            str(catalog_path),
            "route",
            "Build an MCP server with tools",
            "--json",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output.split("Indexed", 1)[1].split("\n", 1)[1])
    assert payload["candidates"][0]["name"] == "mcp-server-patterns"


def test_bridge_route_outputs_json(tmp_path: Path, fixture_skills_root: Path) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])

    completed = subprocess.run(
        [sys.executable, "-m", "skillroute", "bridge", "route"],
        input=json.dumps({"catalog": str(catalog_path), "request": "Astra vector backend"}),
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["candidates"][0]["name"] == "astra-vector-backend"


def test_cli_eval_fresh_index_root_ignores_existing_catalog(
    tmp_path: Path,
    fixture_skills_root: Path,
    capsys,
) -> None:
    noisy_root = tmp_path / "noisy"
    noisy_skill = noisy_root / "mcp-distractor"
    noisy_skill.mkdir(parents=True)
    (noisy_skill / "SKILL.md").write_text(
        """---
name: mcp-distractor
description: Build MCP servers with route search inspect tools over and over.
---

# MCP Distractor
""",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.db"
    cases = Path(__file__).parent / "fixtures" / "golden_routes.json"
    main(["--catalog", str(catalog_path), "index", "--root", str(noisy_root)])

    main(
        [
            "--catalog",
            str(catalog_path),
            "eval",
            "run",
            "--fresh",
            "--index-root",
            str(fixture_skills_root),
            "--cases",
            str(cases),
        ]
    )

    output = capsys.readouterr().out
    assert "4/4 golden route cases passed" in output


def test_cli_backend_astra_upsert_saves_backend_refs(
    tmp_path: Path,
    fixture_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])

    def fake_from_env():
        return AstraDataAPIBackend(endpoint=None, token=None, collection="skills")

    monkeypatch.setattr("skillroute.cli.AstraDataAPIBackend.from_env", fake_from_env)

    main(["--catalog", str(catalog_path), "backend", "astra", "upsert", "--json"])

    payload = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert payload["backend"] == "astra-data-api"
    assert payload["skill_count"] == 3
    assert payload["ref_count"] == 3
    assert payload["status_counts"] == {"not_configured": 3}
    assert "refs" not in payload

    main(["--catalog", str(catalog_path), "backend", "astra", "upsert", "--json", "--include-refs"])

    detailed_payload = json.loads(capsys.readouterr().out)
    assert {ref["status"] for ref in detailed_payload["refs"]} == {"not_configured"}


def test_cli_backend_astra_search_prints_catalog_skill_name(
    tmp_path: Path,
    fixture_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    catalog_skill = json.loads(
        subprocess.run(
            [
                sys.executable,
                "-m",
                "skillroute",
                "--catalog",
                str(catalog_path),
                "inspect",
                "mcp-server-patterns",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    class FakeAstra:
        name = "astra-data-api"
        collection = "skills"
        keyspace = "default_keyspace"

        def search(self, query, skills, limit=10):
            return [{"skill_id": catalog_skill["id"], "backend": self.name, "score": 0.9}]

    monkeypatch.setattr("skillroute.cli.AstraDataAPIBackend.from_env", lambda: FakeAstra())

    main(["--catalog", str(catalog_path), "backend", "astra", "search", "mcp", "--limit", "1"])

    assert "mcp-server-patterns" in capsys.readouterr().out


def test_cli_route_uses_selected_astra_backend(
    tmp_path: Path,
    fixture_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    catalog_skill = json.loads(
        subprocess.run(
            [
                sys.executable,
                "-m",
                "skillroute",
                "--catalog",
                str(catalog_path),
                "inspect",
                "astra-vector-backend",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    class FakeAstra:
        name = "astra-data-api"

        def search(self, query, skills, limit=10):
            return [{"skill_id": catalog_skill["id"], "backend": self.name, "score": 0.94}]

    monkeypatch.setattr("skillroute.cli.AstraDataAPIBackend.from_env", lambda: FakeAstra())

    main(
        [
            "--catalog",
            str(catalog_path),
            "route",
            "remote-only embedding match",
            "--backend",
            "astra",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert payload["candidates"][0]["name"] == "astra-vector-backend"
    assert payload["candidates"][0]["score_breakdown"]["semantic"] == 0.94


def test_cli_search_uses_selected_astra_backend(
    tmp_path: Path,
    fixture_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    catalog_skill = json.loads(
        subprocess.run(
            [
                sys.executable,
                "-m",
                "skillroute",
                "--catalog",
                str(catalog_path),
                "inspect",
                "astra-vector-backend",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    class FakeAstra:
        name = "astra-data-api"

        def search(self, query, skills, limit=10):
            return [{"skill_id": catalog_skill["id"], "backend": self.name, "score": 0.94}]

    monkeypatch.setattr("skillroute.cli.AstraDataAPIBackend.from_env", lambda: FakeAstra())

    main(
        [
            "--catalog",
            str(catalog_path),
            "search",
            "remote-only embedding match",
            "--backend",
            "astra",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert payload[0]["name"] == "astra-vector-backend"
    assert payload[0]["backend_score"] == 0.94


def test_cli_mcp_config_codex_outputs_install_command_and_toml(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    catalog_path = tmp_path / "catalog.db"

    main(
        [
            "mcp",
            "config",
            "--client",
            "codex",
            "--repo-root",
            str(repo_root),
            "--catalog",
            str(catalog_path),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    entrypoint = repo_root / "mcp" / "build" / "index.js"
    assert payload["client"] == "codex"
    assert payload["config_path"] == "~/.codex/config.toml"
    assert payload["install_command"].startswith("codex mcp add skillroute")
    assert f"SKILLROUTE_CATALOG_PATH={catalog_path}" in payload["install_command"]
    assert str(entrypoint) in payload["install_command"]
    assert "[mcp_servers.skillroute]" in payload["config"]
    assert f'args = ["{entrypoint}"]' in payload["config"]
    assert f'SKILLROUTE_CATALOG_PATH = "{catalog_path}"' in payload["config"]
    assert any("MCP entrypoint not found yet" in note for note in payload["notes"])


def test_cli_mcp_config_ibm_bob_outputs_bob_json(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    catalog_path = tmp_path / "catalog.db"

    main(
        [
            "mcp",
            "config",
            "--client",
            "ibm-bob",
            "--repo-root",
            str(repo_root),
            "--catalog",
            str(catalog_path),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    server = payload["config"]["mcpServers"]["skillroute"]
    assert payload["client"] == "ibm-bob"
    assert payload["config_path"] == "~/.bob/mcp.json or .bob/mcp.json"
    assert payload["install_command"] is None
    assert server["command"] == "node"
    assert server["args"] == [str(repo_root / "mcp" / "build" / "index.js")]
    assert server["cwd"] == str(repo_root)
    assert server["disabled"] is False
    assert server["env"]["SKILLROUTE_CATALOG_PATH"] == str(catalog_path)
    assert "alwaysAllow" not in server


def test_cli_mcp_config_claude_code_outputs_scoped_command_and_json(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    main(
        [
            "mcp",
            "config",
            "--client",
            "claude-code",
            "--repo-root",
            str(repo_root),
            "--scope",
            "project",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    server = payload["config"]["mcpServers"]["skillroute"]
    assert payload["scope"] == "project"
    assert payload["config_path"] == ".mcp.json"
    assert "claude mcp add --transport stdio --scope project" in payload["install_command"]
    assert server["command"] == "node"
    assert server["args"] == [str(repo_root / "mcp" / "build" / "index.js")]
    assert server["env"]["SKILLROUTE_BACKEND"] == "local"


def test_cli_mcp_config_claude_desktop_prints_config_snippet(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    catalog_path = tmp_path / "catalog.db"

    main(
        [
            "mcp",
            "config",
            "--client",
            "claude-desktop",
            "--repo-root",
            str(repo_root),
            "--catalog",
            str(catalog_path),
            "--backend",
            "astra",
        ]
    )

    output = capsys.readouterr().out
    assert "SkillRoute MCP setup for Claude Desktop" in output
    assert "claude_desktop_config.json" in output
    assert '"SKILLROUTE_BACKEND": "astra"' in output
    assert str(repo_root / "mcp" / "build" / "index.js") in output


def test_cli_mcp_config_vscode_outputs_add_mcp_command(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    catalog_path = tmp_path / "catalog.db"

    main(
        [
            "mcp",
            "config",
            "--client",
            "vscode",
            "--repo-root",
            str(repo_root),
            "--catalog",
            str(catalog_path),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["client"] == "vscode"
    assert payload["setup_method"] == "command"
    assert payload["install_command"].startswith("code --add-mcp")
    assert payload["install_command_parts"][0:2] == ["code", "--add-mcp"]
    add_payload = json.loads(payload["install_command_parts"][2])
    assert add_payload["name"] == "skillroute"
    assert add_payload["command"] == "node"
    assert add_payload["args"] == [str(repo_root / "mcp" / "build" / "index.js")]
    assert payload["config"]["servers"]["skillroute"]["env"]["SKILLROUTE_CATALOG_PATH"] == str(catalog_path)


def test_cli_mcp_config_windsurf_outputs_config_path(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    main(
        [
            "mcp",
            "config",
            "--client",
            "windsurf",
            "--repo-root",
            str(repo_root),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    server = payload["config"]["mcpServers"]["skillroute"]
    assert payload["client"] == "windsurf"
    assert payload["setup_method"] == "json_merge"
    assert payload["config_path"] == "~/.codeium/windsurf/mcp_config.json"
    assert server["command"] == "node"
    assert server["args"] == [str(repo_root / "mcp" / "build" / "index.js")]


def test_cli_mcp_config_cursor_is_print_only(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    main(
        [
            "mcp",
            "config",
            "--client",
            "cursor",
            "--repo-root",
            str(repo_root),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["client"] == "cursor"
    assert payload["setup_method"] == "print_only"
    assert payload["install_command"] is None
    assert any("snippet-only" in note for note in payload["notes"])


def test_cli_backend_status_reports_astra_without_secrets(
    tmp_path: Path,
    fixture_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    for name in (
        "ASTRA_DB_API_ENDPOINT",
        "ASTRA_DB_APPLICATION_TOKEN",
        "SKILLROUTE_ASTRA_EMBEDDING_API_KEY",
        "SKILLROUTE_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])

    main(["--catalog", str(catalog_path), "backend", "status", "--backend", "astra", "--json"])

    payload = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert payload["backend"] == "astra-data-api"
    assert payload["status"] == "not_configured"
    assert payload["configured"] is False
    assert payload["skill_count"] == 3
    assert payload["details"]["token_configured"] is False
    assert "AstraCS" not in json.dumps(payload)


def test_cli_traces_list_and_show(
    tmp_path: Path,
    fixture_skills_root: Path,
    capsys,
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    capsys.readouterr()
    main(["--catalog", str(catalog_path), "route", "Build an MCP server with tools", "--json"])
    capsys.readouterr()

    main(["--catalog", str(catalog_path), "traces", "list", "--json"])

    traces = json.loads(capsys.readouterr().out)
    assert traces[0]["backend"] == "local-token"
    assert traces[0]["top_candidate"]["name"] == "mcp-server-patterns"

    main(["--catalog", str(catalog_path), "traces", "show", str(traces[0]["id"]), "--json"])

    trace = json.loads(capsys.readouterr().out)
    assert trace["request"]["request"] == "Build an MCP server with tools"
    assert trace["response"]["candidates"][0]["name"] == "mcp-server-patterns"


def test_parse_options_json_rejects_invalid_json() -> None:
    with pytest.raises(SystemExit, match="not valid JSON"):
        parse_options_json("{bad json}")
    assert parse_options_json(None) is None
    assert parse_options_json('{"a": 1}') == {"a": 1}


def test_clamp_limit_bounds_values() -> None:
    assert clamp_limit(0) == 1
    assert clamp_limit(5) == 5
    assert clamp_limit(9999) == 50
    with pytest.raises(ValueError, match="Invalid limit"):
        clamp_limit("not-a-number")


def test_require_payload_key_reports_missing_key() -> None:
    assert require_payload_key({"request": "x"}, "request") == "x"
    with pytest.raises(ValueError, match="missing required key"):
        require_payload_key({}, "request")


def test_cli_route_text_output(tmp_path: Path, fixture_skills_root: Path, capsys) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    capsys.readouterr()
    main(["--catalog", str(catalog_path), "route", "Build an MCP server with tools"])
    output = capsys.readouterr().out
    assert "Ranked skills:" in output
    assert "mcp-server-patterns" in output


def test_cli_search_and_inspect_text_output(tmp_path: Path, fixture_skills_root: Path, capsys) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    capsys.readouterr()
    main(["--catalog", str(catalog_path), "search", "Astra vector backend"])
    assert "astra-vector-backend" in capsys.readouterr().out
    main(["--catalog", str(catalog_path), "inspect", "mcp-server-patterns"])
    inspect_output = capsys.readouterr().out
    assert "relationships:" in inspect_output


def test_cli_inspect_missing_skill_exits(tmp_path: Path, fixture_skills_root: Path) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    with pytest.raises(SystemExit, match="Skill not found"):
        main(["--catalog", str(catalog_path), "inspect", "no-such-skill"])


def test_cli_eval_run_missing_cases_file_exits(tmp_path: Path, fixture_skills_root: Path) -> None:
    catalog_path = tmp_path / "catalog.db"
    with pytest.raises(SystemExit, match="Could not run eval cases"):
        main(
            [
                "--catalog",
                str(catalog_path),
                "eval",
                "run",
                "--fresh",
                "--index-root",
                str(fixture_skills_root),
                "--cases",
                str(tmp_path / "missing.json"),
            ]
        )


def test_cli_create_collection_invalid_options_json_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASTRA_DB_API_ENDPOINT", "https://example.com")
    monkeypatch.setenv("ASTRA_DB_APPLICATION_TOKEN", "token")
    with pytest.raises(SystemExit, match="not valid JSON"):
        main(["backend", "astra", "create-collection", "--options-json", "{bad}"])


def test_cli_unknown_backend_env_exits(
    tmp_path: Path, fixture_skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKILLROUTE_BACKEND", "bogus")
    catalog_path = tmp_path / "catalog.db"
    with pytest.raises(SystemExit, match="Unsupported SkillRoute backend"):
        main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])


def test_cli_bridge_route_search_inspect_in_process(
    tmp_path: Path,
    fixture_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"request": "Astra vector backend"})))
    main(["--catalog", str(catalog_path), "bridge", "route"])
    route_payload = json.loads(capsys.readouterr().out)
    assert route_payload["candidates"][0]["name"] == "astra-vector-backend"

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"query": "MCP server tools"})))
    main(["--catalog", str(catalog_path), "bridge", "search"])
    search_payload = json.loads(capsys.readouterr().out)
    assert any(row["name"] == "mcp-server-patterns" for row in search_payload)

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"skill_id": "mcp-server-patterns"})))
    main(["--catalog", str(catalog_path), "bridge", "inspect"])
    inspect_payload = json.loads(capsys.readouterr().out)
    assert inspect_payload["name"] == "mcp-server-patterns"
    assert "backend_refs" in inspect_payload


def test_cli_bridge_error_is_reported_as_json_and_exits(
    tmp_path: Path,
    fixture_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"skill_id": "does-not-exist"})))
    with pytest.raises(SystemExit) as exc_info:
        main(["--catalog", str(catalog_path), "bridge", "inspect"])

    assert exc_info.value.code == 1
    error_payload = json.loads(capsys.readouterr().out)
    assert error_payload["error"]["type"] == "ValueError"
    assert "does-not-exist" in error_payload["error"]["message"]


def test_cli_route_empty_catalog_recommends_clarification(tmp_path: Path, capsys) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "route", "nothing matches this request"])
    output = capsys.readouterr().out
    assert "Clarification recommended:" in output
    assert "No matching skills." in output


def test_cli_search_empty_catalog_reports_no_matches(tmp_path: Path, capsys) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "search", "nothing matches this query"])
    assert "No matching skills." in capsys.readouterr().out


def test_cli_backend_status_text_output(
    tmp_path: Path, fixture_skills_root: Path, capsys
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    capsys.readouterr()
    main(["--catalog", str(catalog_path), "backend", "status"])
    output = capsys.readouterr().out
    assert "status=" in output
    assert "configured:" in output
    assert "catalog:" in output


def test_cli_traces_list_and_show_text_output(
    tmp_path: Path, fixture_skills_root: Path, capsys
) -> None:
    catalog_path = tmp_path / "catalog.db"
    main(["--catalog", str(catalog_path), "index", "--root", str(fixture_skills_root)])
    main(["--catalog", str(catalog_path), "route", "Build an MCP server with tools"])
    capsys.readouterr()

    main(["--catalog", str(catalog_path), "traces", "list"])
    list_output = capsys.readouterr().out
    assert "request: Build an MCP server with tools" in list_output

    main(["--catalog", str(catalog_path), "traces", "show", "1"])
    show_output = capsys.readouterr().out
    assert "Trace 1" in show_output
    assert "request: Build an MCP server with tools" in show_output
