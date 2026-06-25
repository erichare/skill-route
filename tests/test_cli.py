from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
