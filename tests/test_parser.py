from __future__ import annotations

from pathlib import Path

import pytest

from skillroute.models import SkillRelationship
from skillroute.parser import parse_skill_bundle


def test_parse_skill_bundle_includes_metadata_excerpts_and_references(fixture_skills_root: Path) -> None:
    skill = parse_skill_bundle(
        fixture_skills_root / "mcp-server-patterns" / "SKILL.md",
        root=fixture_skills_root,
    )

    assert skill.name == "mcp-server-patterns"
    assert "MCP servers" in skill.description
    assert "mcp" in skill.tags
    assert skill.facets["language"] == ["typescript"]
    assert any(excerpt.kind == "triggers" for excerpt in skill.excerpts)
    assert any(reference.kind == "templates" for reference in skill.references)
    assert skill.relationships[0].type == "complements"
    assert skill.relationships[0].target == "python-patterns"


def test_content_hash_changes_when_referenced_file_changes(tmp_path: Path) -> None:
    skill_dir = tmp_path / "hash-skill"
    template_dir = skill_dir / "templates"
    template_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    template = template_dir / "example.md"
    skill_file.write_text(
        """---
name: hash-skill
description: Hash referenced templates.
---

# Hash Skill

See [example](templates/example.md).
""",
        encoding="utf-8",
    )
    template.write_text("first", encoding="utf-8")
    first = parse_skill_bundle(skill_file, root=tmp_path)

    template.write_text("second", encoding="utf-8")
    second = parse_skill_bundle(skill_file, root=tmp_path)

    assert first.content_hash != second.content_hash
    assert first.id != second.id


def test_relationship_validation_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unknown relationship type"):
        SkillRelationship(type="nearby", target="other")

