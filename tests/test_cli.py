from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from skillroute.backends import AstraDataAPIBackend
from skillroute.cli import main


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
    assert "1/1 golden route cases passed" in output


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
