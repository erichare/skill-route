from __future__ import annotations

import json
from pathlib import Path

from skillroute.catalog import Catalog
from skillroute.cli import main
from skillroute.dogfood import discover_default_skill_roots, index_default_skill_roots


def write_skill(root: Path, name: str, description: str = "Example skill.") -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
---

# {name}

Use this skill for dogfood routing tests.
""",
        encoding="utf-8",
    )


def test_discover_default_skill_roots_counts_skills(tmp_path: Path) -> None:
    write_skill(tmp_path / ".codex" / "skills", "codex-skill")
    write_skill(tmp_path / ".agents" / "skills", "agent-skill")
    (tmp_path / ".codex" / "plugins" / "cache").mkdir(parents=True)

    roots = discover_default_skill_roots(tmp_path)

    assert [(root.path.name, root.skill_count) for root in roots] == [
        ("skills", 1),
        ("skills", 1),
    ]


def test_index_default_skill_roots_indexes_each_root(tmp_path: Path) -> None:
    write_skill(tmp_path / ".codex" / "skills", "codex-skill")
    write_skill(tmp_path / ".agents" / "skills", "agent-skill")
    catalog = Catalog(tmp_path / "catalog.db")

    result = index_default_skill_roots(catalog, home=tmp_path)

    assert result.indexed_count == 2
    assert catalog.get_skill("codex-skill") is not None
    assert catalog.get_skill("agent-skill") is not None


def test_cli_dogfood_roots_json(tmp_path: Path, capsys) -> None:
    write_skill(tmp_path / ".codex" / "skills", "codex-skill")

    main(["dogfood", "roots", "--home", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"path": str(tmp_path / ".codex" / "skills"), "skill_count": 1}]


def test_cli_dogfood_index_json(tmp_path: Path, capsys) -> None:
    write_skill(tmp_path / ".agents" / "skills", "agent-skill")
    catalog_path = tmp_path / "catalog.db"

    main(["--catalog", str(catalog_path), "dogfood", "index", "--home", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["indexed_count"] == 1
    assert payload["roots"][0]["skill_count"] == 1
    assert Catalog(catalog_path).get_skill("agent-skill") is not None

