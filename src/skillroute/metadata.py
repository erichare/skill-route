from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skillroute.models import RELATIONSHIP_TYPES, SkillRecord
from skillroute.parser import discover_skill_files, parse_skill_bundle


OVERLAY_VERSION = 1
REVIEW_STATUSES = {"suggested", "reviewed", "rejected"}


@dataclass(slots=True)
class MetadataWriteResult:
    output_path: Path
    skill_count: int


@dataclass(slots=True)
class MetadataReviewResult:
    overlay_path: Path
    skill_count: int
    status_counts: dict[str, int]
    relationship_count: int
    issues: list[str]


def default_overlay_path(root: Path) -> Path:
    return root.resolve() / ".skillroute" / "overlays" / "suggested.json"


def build_metadata_overlay(root: Path | str) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    skills = [
        parse_skill_bundle(skill_file, root=root_path)
        for skill_file in discover_skill_files(root_path)
    ]
    return {
        "version": OVERLAY_VERSION,
        "generated_by": "skillroute",
        "root": str(root_path),
        "skills": {
            overlay_key(root_path, skill): suggestion_for_skill(skill)
            for skill in sorted(skills, key=lambda item: item.name.casefold())
        },
    }


def write_metadata_overlay(
    root: Path | str,
    output: Path | str | None = None,
    force: bool = False,
) -> MetadataWriteResult:
    root_path = Path(root).expanduser().resolve()
    output_path = Path(output).expanduser().resolve() if output else default_overlay_path(root_path)
    if output_path.exists() and not force:
        raise FileExistsError(f"Overlay already exists: {output_path}. Use --force to replace it.")
    overlay = build_metadata_overlay(root_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(overlay, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return MetadataWriteResult(output_path=output_path, skill_count=len(overlay["skills"]))


def review_metadata_overlay(overlay_path: Path | str) -> MetadataReviewResult:
    path = Path(overlay_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    issues = validate_metadata_overlay(payload)
    skills = payload.get("skills", {})
    status_counts: Counter[str] = Counter()
    relationship_count = 0
    if isinstance(skills, dict):
        for suggestion in skills.values():
            if not isinstance(suggestion, dict):
                continue
            status = suggestion.get("metadata", {}).get("review_status", "unknown")
            status_counts[str(status)] += 1
            relationships = suggestion.get("relationships", {})
            if isinstance(relationships, dict):
                relationship_count += sum(len(values) for values in relationships.values() if isinstance(values, list))
    return MetadataReviewResult(
        overlay_path=path,
        skill_count=len(skills) if isinstance(skills, dict) else 0,
        status_counts=dict(sorted(status_counts.items())),
        relationship_count=relationship_count,
        issues=issues,
    )


def validate_metadata_overlay(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if payload.get("version") != OVERLAY_VERSION:
        issues.append(f"version must be {OVERLAY_VERSION}")
    skills = payload.get("skills")
    if not isinstance(skills, dict):
        return [*issues, "skills must be an object"]
    for key, suggestion in skills.items():
        if not isinstance(suggestion, dict):
            issues.append(f"{key}: suggestion must be an object")
            continue
        tags = suggestion.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            issues.append(f"{key}: tags must be a list of strings")
        facets = suggestion.get("facets", {})
        if not isinstance(facets, dict):
            issues.append(f"{key}: facets must be an object")
        else:
            for facet_key, values in facets.items():
                if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                    issues.append(f"{key}: facet {facet_key} must be a list of strings")
        relationships = suggestion.get("relationships", {})
        if not isinstance(relationships, dict):
            issues.append(f"{key}: relationships must be an object")
        else:
            for relationship_type, targets in relationships.items():
                if relationship_type not in RELATIONSHIP_TYPES:
                    issues.append(f"{key}: unknown relationship type {relationship_type}")
                if not isinstance(targets, list) or not all(isinstance(target, str) for target in targets):
                    issues.append(f"{key}: relationship {relationship_type} must be a list of strings")
        status = suggestion.get("metadata", {}).get("review_status", "suggested")
        if status not in REVIEW_STATUSES:
            issues.append(f"{key}: metadata.review_status must be one of {sorted(REVIEW_STATUSES)}")
    return issues


def overlay_key(root: Path, skill: SkillRecord) -> str:
    skill_path = Path(skill.skill_path)
    try:
        return str(skill_path.relative_to(root))
    except ValueError:
        return skill.name


def suggestion_for_skill(skill: SkillRecord) -> dict[str, Any]:
    relationships: dict[str, list[str]] = {}
    for relationship in skill.relationships:
        relationships.setdefault(relationship.type, []).append(relationship.target)
    return {
        "description": skill.description,
        "tags": sorted(skill.tags),
        "facets": {key: sorted(values) for key, values in sorted(skill.facets.items())},
        "relationships": {key: sorted(values) for key, values in sorted(relationships.items())},
        "metadata": {
            "review_status": "suggested",
            "source_path": skill.skill_path,
            "source_content_hash": skill.content_hash,
            "source_skill_id": skill.id,
        },
    }

