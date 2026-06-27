from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from skillroute.catalog import Catalog
from skillroute.models import SkillRecord, SkillRelationship, to_jsonable
from skillroute.routing import Router


DOMAIN_COLORS = {
    "agentic": "#60a5fa",
    "api": "#22d3ee",
    "astra": "#34d399",
    "backend": "#a3e635",
    "cli": "#f59e0b",
    "cloudflare": "#f97316",
    "database": "#2dd4bf",
    "evals": "#fde047",
    "frontend": "#f472b6",
    "github": "#c084fc",
    "langchain": "#818cf8",
    "mcp": "#38bdf8",
    "review": "#fb7185",
    "routing": "#fb923c",
    "security": "#f87171",
    "skills": "#c084fc",
    "testing": "#a3e635",
    "typescript": "#60a5fa",
    "vector-search": "#22d3ee",
    "uncategorized": "#94a3b8",
}
RELATIONSHIP_COLORS = {
    "requires": "#60a5fa",
    "complements": "#34d399",
    "conflicts": "#f87171",
    "supersedes": "#f59e0b",
    "same_domain": "#c084fc",
}


def build_atlas_payload(catalog: Catalog) -> dict[str, Any]:
    skills = catalog.list_skills()
    resolver = RelationshipResolver(skills)
    domains = domain_summary(skills)
    edges, unresolved, incoming = relationship_graph(skills, resolver)
    backend_refs = catalog.all_backend_refs()
    nodes = [
        atlas_node(skill, backend_refs.get(skill.id, []), unresolved[skill.id], incoming[skill.id])
        for skill in skills
    ]
    relationship_counts = Counter(edge["type"] for edge in edges)
    return {
        "catalog": {
            **catalog_summary(
                catalog, skills=skills, edges=edges, unresolved=unresolved, backend_refs=backend_refs
            ),
            "fingerprint": catalog_fingerprint(catalog, skills),
        },
        "domains": domains,
        "relationshipTypes": [
            {"type": relationship_type, "count": relationship_counts[relationship_type], "color": color}
            for relationship_type, color in RELATIONSHIP_COLORS.items()
        ],
        "nodes": nodes,
        "edges": edges,
        "warnings": [
            {
                "skillId": skill_id,
                "relationshipType": relationship.type,
                "target": relationship.target,
            }
            for skill_id, relationships in unresolved.items()
            for relationship in relationships
        ],
    }


def catalog_summary(
    catalog: Catalog,
    *,
    skills: list[SkillRecord] | None = None,
    edges: list[dict[str, Any]] | None = None,
    unresolved: dict[str, list[SkillRelationship]] | None = None,
    backend_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    skills = skills if skills is not None else catalog.list_skills()
    domains = {primary_domain(skill) for skill in skills}
    if edges is None or unresolved is None:
        resolver = RelationshipResolver(skills)
        edges, unresolved, _ = relationship_graph(skills, resolver)
    if backend_refs is None:
        backend_refs = catalog.all_backend_refs()
    backend_counts: Counter[str] = Counter()
    for skill in skills:
        for ref in backend_refs.get(skill.id, []):
            backend_counts[f"{ref['backend']}:{ref['status']}"] += 1
    return {
        "path": str(catalog.path),
        "skillCount": len(skills),
        "domainCount": len(domains),
        "relationshipCount": len(edges),
        "unresolvedRelationshipCount": sum(len(items) for items in unresolved.values()),
        "orphanCount": orphan_count(skills, edges),
        "conflictCount": sum(1 for edge in edges if edge["type"] == "conflicts"),
        "backendRefCounts": dict(sorted(backend_counts.items())),
    }


def skill_detail_payload(catalog: Catalog, skill_ref: str) -> dict[str, Any] | None:
    skill = catalog.get_skill(skill_ref)
    if skill is None:
        return None
    skills = catalog.list_skills()
    resolver = RelationshipResolver(skills)
    edges, unresolved, incoming = relationship_graph(skills, resolver)
    incoming_relationships = [
        edge for edge in edges if edge["target"] == skill.id
    ]
    outgoing_relationships = [
        edge for edge in edges if edge["source"] == skill.id
    ]
    return {
        **to_jsonable(skill),
        "domain": primary_domain(skill),
        "backend_refs": catalog.backend_refs(skill.id),
        "incoming_relationships": incoming_relationships,
        "outgoing_relationships": outgoing_relationships,
        "unresolved_relationships": [to_jsonable(relationship) for relationship in unresolved[skill.id]],
        "relationship_summary": {
            "incoming": len(incoming[skill.id]),
            "outgoing": len(outgoing_relationships),
        },
    }


def route_preview_payload(
    catalog: Catalog,
    *,
    request: str,
    repo: Path | str | None = None,
    limit: int = 5,
    router: Router | None = None,
) -> dict[str, Any]:
    response = (router or Router(catalog)).route(request, repo=repo, limit=limit, record_trace=False)
    return to_jsonable(response)


class RelationshipResolver:
    def __init__(self, skills: list[SkillRecord]) -> None:
        self._by_ref: dict[str, str] = {}
        for skill in skills:
            self._by_ref[skill.id] = skill.id
            self._by_ref[skill.name] = skill.id
            self._by_ref[skill.name.casefold()] = skill.id

    def resolve(self, target: str) -> str | None:
        return self._by_ref.get(target) or self._by_ref.get(target.casefold())


def relationship_graph(
    skills: list[SkillRecord],
    resolver: RelationshipResolver,
) -> tuple[list[dict[str, Any]], dict[str, list[SkillRelationship]], dict[str, list[dict[str, Any]]]]:
    names = {skill.id: skill.name for skill in skills}
    edges: list[dict[str, Any]] = []
    unresolved: dict[str, list[SkillRelationship]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for skill in skills:
        for relationship in skill.relationships:
            target_id = resolver.resolve(relationship.target)
            if target_id is None or target_id == skill.id:
                unresolved[skill.id].append(relationship)
                continue
            edge = {
                "id": f"{skill.id}:{relationship.type}:{target_id}",
                "source": skill.id,
                "sourceName": skill.name,
                "target": target_id,
                "targetName": names.get(target_id, relationship.target),
                "type": relationship.type,
                "label": relationship.type.replace("_", " "),
                "color": RELATIONSHIP_COLORS.get(relationship.type, "#94a3b8"),
            }
            edges.append(edge)
            incoming[target_id].append(edge)
    edges.sort(key=lambda edge: (edge["sourceName"].casefold(), edge["type"], edge["targetName"].casefold()))
    return edges, unresolved, incoming


def atlas_node(
    skill: SkillRecord,
    backend_refs: list[dict[str, Any]],
    unresolved: list[SkillRelationship],
    incoming: list[dict[str, Any]],
) -> dict[str, Any]:
    domain = primary_domain(skill)
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "domain": domain,
        "color": domain_color(domain),
        "tags": skill.tags,
        "facets": skill.facets,
        "skillPath": skill.skill_path,
        "bundlePath": skill.bundle_path,
        "rootPath": skill.root_path,
        "contentHash": skill.content_hash,
        "excerptCount": len(skill.excerpts),
        "referenceCount": len(skill.references),
        "relationshipSummary": {
            "incoming": len(incoming),
            "outgoing": len(skill.relationships) - len(unresolved),
            "unresolved": len(unresolved),
            "conflicts": sum(1 for relationship in skill.relationships if relationship.type == "conflicts"),
        },
        "backendRefs": backend_refs,
    }


def primary_domain(skill: SkillRecord) -> str:
    domains = skill.facets.get("domain", [])
    if domains:
        return domains[0]
    if skill.tags:
        return skill.tags[0]
    root_name = Path(skill.root_path).name
    return root_name or "uncategorized"


def domain_summary(skills: list[SkillRecord]) -> list[dict[str, Any]]:
    counts = Counter(primary_domain(skill) for skill in skills)
    return [
        {"id": domain, "name": titleize(domain), "count": count, "color": domain_color(domain)}
        for domain, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def domain_color(domain: str) -> str:
    if domain in DOMAIN_COLORS:
        return DOMAIN_COLORS[domain]
    digest = hashlib.sha256(domain.encode("utf-8")).hexdigest()
    hue = int(digest[:2], 16) % 360
    return f"hsl({hue} 78% 68%)"


def titleize(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


def catalog_fingerprint(catalog: Catalog, skills: list[SkillRecord]) -> str:
    digest = hashlib.sha256(str(catalog.path).encode("utf-8"))
    for skill in sorted(skills, key=lambda item: item.id):
        digest.update(skill.id.encode("utf-8"))
        digest.update(skill.content_hash.encode("utf-8"))
    return digest.hexdigest()[:16]


def orphan_count(skills: list[SkillRecord], edges: list[dict[str, Any]]) -> int:
    connected = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
    return sum(1 for skill in skills if skill.id not in connected)
