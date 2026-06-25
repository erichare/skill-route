from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillroute.catalog import Catalog
from skillroute.cli import main
from skillroute.metadata import (
    build_metadata_overlay,
    review_metadata_overlay,
    validate_metadata_overlay,
    write_metadata_overlay,
)


def test_build_metadata_overlay_uses_relative_skill_keys(fixture_skills_root: Path) -> None:
    overlay = build_metadata_overlay(fixture_skills_root)

    assert "mcp-server-patterns/SKILL.md" in overlay["skills"]
    suggestion = overlay["skills"]["mcp-server-patterns/SKILL.md"]
    assert "mcp" in suggestion["tags"]
    assert suggestion["metadata"]["review_status"] == "suggested"


def test_write_metadata_overlay_does_not_modify_skill_source(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_dir = root / "sample-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_text = """---
name: sample-skill
description: Original skill text.
---

# Sample Skill
"""
    skill_file.write_text(skill_text, encoding="utf-8")

    result = write_metadata_overlay(root)

    assert result.skill_count == 1
    assert result.output_path.exists()
    assert skill_file.read_text(encoding="utf-8") == skill_text


def test_metadata_overlay_round_trip_updates_indexed_skill(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_dir = root / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: sample-skill
description: Original description.
---

# Sample Skill
""",
        encoding="utf-8",
    )
    result = write_metadata_overlay(root)
    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    payload["skills"]["sample-skill/SKILL.md"]["description"] = "Reviewed description."
    payload["skills"]["sample-skill/SKILL.md"]["tags"].append("reviewed")
    payload["skills"]["sample-skill/SKILL.md"]["metadata"]["review_status"] = "reviewed"
    result.output_path.write_text(json.dumps(payload), encoding="utf-8")

    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(root)
    skill = catalog.get_skill("sample-skill")

    assert skill is not None
    assert skill.description == "Reviewed description."
    assert "reviewed" in skill.tags
    assert skill.metadata["overlay_applied"] is True


def test_validate_metadata_overlay_reports_bad_relationship_type(fixture_skills_root: Path) -> None:
    overlay = build_metadata_overlay(fixture_skills_root)
    overlay["skills"]["mcp-server-patterns/SKILL.md"]["relationships"]["nearby"] = ["other"]

    issues = validate_metadata_overlay(overlay)

    assert any("unknown relationship type nearby" in issue for issue in issues)


def test_review_metadata_overlay_summarizes_statuses(tmp_path: Path, fixture_skills_root: Path) -> None:
    result = write_metadata_overlay(fixture_skills_root, output=tmp_path / "overlay.json")

    review = review_metadata_overlay(result.output_path)

    assert review.skill_count == 3
    assert review.status_counts == {"suggested": 3}
    assert review.issues == []


def test_metadata_suggest_refuses_to_overwrite_without_force(tmp_path: Path, fixture_skills_root: Path) -> None:
    output = tmp_path / "overlay.json"
    write_metadata_overlay(fixture_skills_root, output=output)

    with pytest.raises(FileExistsError):
        write_metadata_overlay(fixture_skills_root, output=output)


def test_cli_metadata_suggest_and_review_json(tmp_path: Path, fixture_skills_root: Path, capsys) -> None:
    output = tmp_path / "overlay.json"

    main(
        [
            "metadata",
            "suggest",
            "--root",
            str(fixture_skills_root),
            "--output",
            str(output),
            "--json",
        ]
    )
    suggest_payload = json.loads(capsys.readouterr().out)
    assert suggest_payload["skill_count"] == 3

    main(["metadata", "review", "--overlay", str(output), "--json"])
    review_payload = json.loads(capsys.readouterr().out)
    assert review_payload["status_counts"] == {"suggested": 3}
    assert review_payload["issues"] == []

