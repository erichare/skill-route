from __future__ import annotations

import json
from pathlib import Path

from skillroute.catalog import Catalog


def test_catalog_persists_skills_excerpts_and_relationships(indexed_catalog: Catalog) -> None:
    skill = indexed_catalog.get_skill("mcp-server-patterns")

    assert skill is not None
    assert skill.name == "mcp-server-patterns"
    assert skill.excerpts
    assert skill.relationships[0].type == "complements"

    reopened = Catalog(indexed_catalog.path)
    same_skill = reopened.get_skill(skill.id)
    assert same_skill is not None
    assert same_skill.content_hash == skill.content_hash


def test_catalog_applies_metadata_overlay(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_dir = root / "overlay-skill"
    overlay_dir = root / ".skillroute" / "overlays"
    overlay_dir.mkdir(parents=True)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: overlay-skill
description: Original description.
---

# Overlay Skill
""",
        encoding="utf-8",
    )
    (overlay_dir / "reviewed.json").write_text(
        json.dumps(
            {
                "skills": {
                    "overlay-skill": {
                        "description": "Reviewed description.",
                        "tags": ["reviewed"],
                        "relationships": {"same_domain": ["python-testing"]},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(root)
    skill = catalog.get_skill("overlay-skill")

    assert skill is not None
    assert skill.description == "Reviewed description."
    assert "reviewed" in skill.tags
    assert skill.relationships[0].type == "same_domain"

def test_backend_refs_are_saved(indexed_catalog: Catalog) -> None:
    skill = indexed_catalog.get_skill("mcp-server-patterns")
    assert skill is not None

    indexed_catalog.save_backend_ref(skill.id, "local-token", "abc", "indexed")

    assert indexed_catalog.backend_refs(skill.id)[0]["status"] == "indexed"

