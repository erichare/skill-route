from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any


class RelationshipType(StrEnum):
    REQUIRES = "requires"
    COMPLEMENTS = "complements"
    CONFLICTS = "conflicts"
    SUPERSEDES = "supersedes"
    SAME_DOMAIN = "same_domain"


RELATIONSHIP_TYPES = {relationship.value for relationship in RelationshipType}


@dataclass(slots=True)
class SkillReference:
    kind: str
    path: str


@dataclass(slots=True)
class SkillExcerpt:
    kind: str
    text: str
    source_path: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class SkillRelationship:
    type: str
    target: str

    def __post_init__(self) -> None:
        if self.type not in RELATIONSHIP_TYPES:
            valid = ", ".join(sorted(RELATIONSHIP_TYPES))
            raise ValueError(f"Unknown relationship type {self.type!r}; expected one of: {valid}")


@dataclass(slots=True)
class SkillRecord:
    id: str
    name: str
    description: str
    skill_path: str
    bundle_path: str
    root_path: str
    content_hash: str
    tags: list[str] = field(default_factory=list)
    facets: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    excerpts: list[SkillExcerpt] = field(default_factory=list)
    relationships: list[SkillRelationship] = field(default_factory=list)
    references: list[SkillReference] = field(default_factory=list)


@dataclass(slots=True)
class ScoreBreakdown:
    lexical: float
    semantic: float
    repo_context: float
    graph: float
    total: float


@dataclass(slots=True)
class RouteCandidate:
    skill_id: str
    name: str
    description: str
    confidence: float
    reasons: list[str]
    evidence: list[SkillExcerpt]
    score_breakdown: ScoreBreakdown
    suggested_position: int
    content_hash: str = ""


@dataclass(slots=True)
class RouteResponse:
    request: str
    repo_context: dict[str, Any]
    candidates: list[RouteCandidate]
    suggested_order: list[str]
    clarification_needed: bool
    clarification_questions: list[str]


def to_jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value

