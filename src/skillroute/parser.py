from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from skillroute.models import (
    RELATIONSHIP_TYPES,
    SkillExcerpt,
    SkillRecord,
    SkillReference,
    SkillRelationship,
)
from skillroute.text import top_terms


FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,4})\s+(?P<title>.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((?P<target>[^)]+)\)")
KNOWN_BUNDLE_DIRS = {"assets", "examples", "references", "scripts", "templates"}

DOMAIN_KEYWORDS = {
    "agent": "agentic",
    "agents": "agentic",
    "api": "api",
    "astra": "astra",
    "backend": "backend",
    "cli": "cli",
    "cloudflare": "cloudflare",
    "database": "database",
    "eval": "evals",
    "evaluation": "evals",
    "frontend": "frontend",
    "github": "github",
    "langchain": "langchain",
    "mcp": "mcp",
    "postgres": "database",
    "review": "review",
    "routing": "routing",
    "security": "security",
    "skill": "skills",
    "skills": "skills",
    "testing": "testing",
    "vector": "vector-search",
}

LANGUAGE_KEYWORDS = {
    "go": "go",
    "golang": "go",
    "java": "java",
    "javascript": "javascript",
    "kotlin": "kotlin",
    "python": "python",
    "rust": "rust",
    "swift": "swift",
    "typescript": "typescript",
}


def discover_skill_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("SKILL.md") if path.is_file())


def parse_skill_bundle(skill_file: Path, root: Path | None = None, overlay: dict[str, Any] | None = None) -> SkillRecord:
    skill_file = skill_file.resolve()
    root_path = (root or skill_file.parent).resolve()
    bundle_path = skill_file.parent.resolve()
    text = skill_file.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)
    overlay = overlay or {}

    name = str(overlay.get("name") or metadata.get("name") or first_heading(body) or bundle_path.name)
    description = str(
        overlay.get("description")
        or metadata.get("description")
        or first_paragraph(body)
        or f"Skill bundle at {bundle_path.name}"
    )

    references = find_references(skill_file, body)
    content_hash = compute_bundle_hash(skill_file, references)
    skill_id = make_skill_id(skill_file, content_hash)
    excerpts = extract_excerpts(skill_file, body, description)
    tags, facets = infer_metadata(name, description, body, metadata, overlay)
    relationships = parse_relationships(metadata, overlay)
    merged_metadata = {**metadata, **overlay.get("metadata", {})}
    if overlay:
        merged_metadata["overlay_applied"] = True

    return SkillRecord(
        id=skill_id,
        name=name,
        description=description.strip(),
        skill_path=str(skill_file),
        bundle_path=str(bundle_path),
        root_path=str(root_path),
        content_hash=content_hash,
        tags=tags,
        facets=facets,
        metadata=merged_metadata,
        excerpts=excerpts,
        relationships=relationships,
        references=references,
    )


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    metadata = parse_simple_yaml(match.group("body"))
    return metadata, text[match.end() :]


def parse_simple_yaml(text: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and current_key:
            value = line.strip()
            if value.startswith("- "):
                metadata.setdefault(current_key, []).append(parse_scalar(value[2:].strip()))
            continue
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        current_key = key
        if not value:
            metadata[key] = []
        else:
            metadata[key] = parse_scalar(value)
    return metadata


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value.replace("'", '"'))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return [item.strip() for item in value[1:-1].split(",") if item.strip()]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value.strip('"').strip("'")


def first_heading(body: str) -> str | None:
    match = HEADING_RE.search(body)
    return match.group("title").strip() if match else None


def first_paragraph(body: str) -> str | None:
    paragraphs = re.split(r"\n\s*\n", body.strip())
    for paragraph in paragraphs:
        cleaned = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
        if cleaned and not cleaned.startswith("#"):
            return cleaned[:500]
    return None


def extract_excerpts(skill_file: Path, body: str, description: str) -> list[SkillExcerpt]:
    lines = body.splitlines()
    excerpts = [
        SkillExcerpt(
            kind="description",
            text=description[:600],
            source_path=str(skill_file),
            start_line=1,
            end_line=1,
        )
    ]
    heading_titles = [match.group("title").strip() for match in HEADING_RE.finditer(body)]
    if heading_titles:
        excerpts.append(
            SkillExcerpt(
                kind="headings",
                text="; ".join(heading_titles[:12])[:600],
                source_path=str(skill_file),
                start_line=1,
                end_line=min(len(lines), 12),
            )
        )

    trigger = extract_trigger_section(lines)
    if trigger:
        excerpts.append(
            SkillExcerpt(
                kind="triggers",
                text=trigger[:700],
                source_path=str(skill_file),
                start_line=1,
                end_line=min(len(lines), 80),
            )
        )

    paragraph = first_paragraph(body)
    if paragraph and paragraph != description:
        excerpts.append(
            SkillExcerpt(
                kind="body",
                text=paragraph[:700],
                source_path=str(skill_file),
                start_line=1,
                end_line=min(len(lines), 40),
            )
        )
    return excerpts


def extract_trigger_section(lines: list[str]) -> str:
    capture = False
    captured: list[str] = []
    for line in lines:
        normalized = line.strip().lower()
        if normalized.startswith("#") and any(
            phrase in normalized for phrase in ("when to use", "use when", "trigger", "routing")
        ):
            capture = True
            continue
        if capture and normalized.startswith("#"):
            break
        if capture and line.strip():
            captured.append(line.strip())
        if len(captured) >= 8:
            break
    return " ".join(captured)


def find_references(skill_file: Path, body: str) -> list[SkillReference]:
    bundle_path = skill_file.parent.resolve()
    references: dict[str, SkillReference] = {
        str(skill_file): SkillReference(kind="skill", path=str(skill_file))
    }
    for child in bundle_path.iterdir():
        if child.name in KNOWN_BUNDLE_DIRS and child.is_dir():
            for file_path in child.rglob("*"):
                if file_path.is_file():
                    references[str(file_path.resolve())] = SkillReference(
                        kind=child.name, path=str(file_path.resolve())
                    )

    for match in MARKDOWN_LINK_RE.finditer(body):
        target = match.group("target").split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        target_path = (bundle_path / target).resolve()
        try:
            target_path.relative_to(bundle_path)
        except ValueError:
            continue
        if target_path.is_file():
            references.setdefault(
                str(target_path),
                SkillReference(kind="markdown_link", path=str(target_path)),
            )
    return sorted(references.values(), key=lambda reference: reference.path)


def compute_bundle_hash(skill_file: Path, references: list[SkillReference]) -> str:
    digest = hashlib.sha256()
    for reference in sorted(references, key=lambda item: item.path):
        file_path = Path(reference.path)
        if not file_path.is_file():
            continue
        digest.update(str(file_path.relative_to(skill_file.parent)).encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def make_skill_id(skill_file: Path, content_hash: str) -> str:
    canonical = str(skill_file.resolve())
    digest = hashlib.sha256(f"{canonical}\0{content_hash}".encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", skill_file.parent.name.lower()).strip("-")
    return f"{slug}-{digest}"


def infer_metadata(
    name: str,
    description: str,
    body: str,
    metadata: dict[str, Any],
    overlay: dict[str, Any],
) -> tuple[list[str], dict[str, list[str]]]:
    explicit_tags = as_list(metadata.get("tags")) + as_list(overlay.get("tags"))
    text = " ".join([name, description, body])
    inferred = top_terms([name, description, body], limit=16)

    domains = sorted({DOMAIN_KEYWORDS[token] for token in inferred if token in DOMAIN_KEYWORDS})
    languages = sorted({LANGUAGE_KEYWORDS[token] for token in inferred if token in LANGUAGE_KEYWORDS})
    tags = sorted({*explicit_tags, *domains, *languages})

    facets: dict[str, list[str]] = {
        "domain": domains,
        "language": languages,
    }
    if "mcp" in text.lower():
        facets.setdefault("protocol", []).append("mcp")
    for key, value in dict(overlay.get("facets", {})).items():
        facets[key] = sorted({*facets.get(key, []), *as_list(value)})
    return tags, {key: values for key, values in facets.items() if values}


def parse_relationships(metadata: dict[str, Any], overlay: dict[str, Any]) -> list[SkillRelationship]:
    relationships: list[SkillRelationship] = []
    sources = [
        metadata,
        overlay,
        relationship_mapping(metadata.get("relationships")),
        relationship_mapping(overlay.get("relationships")),
    ]
    for source in sources:
        for relationship_type in RELATIONSHIP_TYPES:
            for target in as_list(source.get(relationship_type)):
                relationships.append(SkillRelationship(type=relationship_type, target=str(target)))
    seen: set[tuple[str, str]] = set()
    unique: list[SkillRelationship] = []
    for relationship in relationships:
        key = (relationship.type, relationship.target)
        if key not in seen:
            seen.add(key)
            unique.append(relationship)
    return unique


def relationship_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value] if value.strip() else []
    return [str(value)]
