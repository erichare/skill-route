from __future__ import annotations

from pathlib import Path
from typing import Any

from skillroute.backends import LocalTokenBackend, RetrievalBackend
from skillroute.catalog import Catalog
from skillroute.context import collect_repo_context
from skillroute.models import RouteCandidate, RouteResponse, ScoreBreakdown, SkillExcerpt
from skillroute.rerankers import Reranker, default_reranker
from skillroute.text import best_snippets, keyword_score, unique_tokens


class Router:
    def __init__(
        self,
        catalog: Catalog,
        backend: RetrievalBackend | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.catalog = catalog
        self.backend = backend or LocalTokenBackend()
        self.reranker = reranker or default_reranker()

    def route(
        self,
        request: str,
        repo: Path | str | None = None,
        limit: int = 5,
        *,
        record_trace: bool = True,
    ) -> RouteResponse:
        repo_path = Path(repo).expanduser() if repo else None
        repo_context = collect_repo_context(repo_path)
        skills = self.catalog.list_skills()
        candidates = self._score_candidates(request, repo_context, skills, limit=max(limit, 8))
        candidates = self.reranker.rerank(request, candidates)[:limit]
        for index, candidate in enumerate(candidates, start=1):
            candidate.suggested_position = index
        clarification_needed = self._needs_clarification(candidates)
        response = RouteResponse(
            request=request,
            repo_context=repo_context,
            candidates=candidates,
            suggested_order=[candidate.skill_id for candidate in candidates],
            clarification_needed=clarification_needed,
            clarification_questions=self._clarification_questions(request, repo_context, candidates)
            if clarification_needed
            else [],
        )
        if record_trace:
            self.catalog.record_route_trace(
                {
                    "request": request,
                    "repo": str(repo_path) if repo_path else None,
                    "limit": limit,
                    "backend": self.backend.name,
                },
                response,
            )
        return response

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        skills = self.catalog.list_skills()
        backend_hits = {row["skill_id"]: row for row in self.backend.search(query, skills, limit=limit * 2)}
        query_tokens = unique_tokens(query)
        rows: list[dict[str, Any]] = []
        for skill in skills:
            lexical = lexical_score(query_tokens, skill)
            backend_hit = backend_hits.get(skill.id, {})
            backend_score = float(backend_hit.get("score", 0.0))
            total = lexical + backend_score
            if total <= 0:
                continue
            snippets = best_snippets(query_tokens, [excerpt.text for excerpt in skill.excerpts], limit=2)
            rows.append(
                {
                    "skill_id": skill.id,
                    "name": skill.name,
                    "description": skill.description,
                    "score": round(total, 4),
                    "lexical_score": round(lexical, 4),
                    "backend": backend_hit.get("backend"),
                    "backend_score": round(backend_score, 4),
                    "tags": skill.tags,
                    "evidence": snippets,
                }
            )
        rows.sort(key=lambda row: row["score"], reverse=True)
        return dedupe_search_rows(rows)[:limit]

    def _score_candidates(
        self,
        request: str,
        repo_context: dict[str, Any],
        skills: list,
        limit: int,
    ) -> list[RouteCandidate]:
        query = " ".join([request, " ".join(repo_context.get("languages", [])), " ".join(repo_context.get("signals", []))])
        query_tokens = unique_tokens(query)
        backend_hits = {row["skill_id"]: row for row in self.backend.search(query, skills, limit=limit * 2)}
        candidates: list[RouteCandidate] = []
        for skill in skills:
            lexical = lexical_score(query_tokens, skill)
            backend_hit = backend_hits.get(skill.id)
            semantic = semantic_score(backend_hit)
            repo_context_score = repo_score(repo_context, skill)
            graph = graph_score(skill)
            total = (lexical * 0.5) + (semantic * 0.25) + (repo_context_score * 0.15) + (graph * 0.10)
            if total <= 0:
                continue
            evidence = evidence_for(query_tokens, skill.excerpts)
            confidence = confidence_for(total, semantic)
            candidates.append(
                RouteCandidate(
                    skill_id=skill.id,
                    name=skill.name,
                    description=skill.description,
                    confidence=round(confidence, 4),
                    reasons=reasons_for(
                        skill,
                        lexical,
                        semantic,
                        repo_context_score,
                        graph,
                        backend_name=str(backend_hit.get("backend")) if backend_hit else None,
                    ),
                    evidence=evidence,
                    score_breakdown=ScoreBreakdown(
                        lexical=round(lexical, 4),
                        semantic=round(semantic, 4),
                        repo_context=round(repo_context_score, 4),
                        graph=round(graph, 4),
                        total=round(total, 4),
                    ),
                    suggested_position=0,
                )
            )
        candidates.sort(key=lambda candidate: candidate.score_breakdown.total, reverse=True)
        return dedupe_candidates(candidates)[:limit]

    def _needs_clarification(self, candidates: list[RouteCandidate]) -> bool:
        if not candidates:
            return True
        if candidates[0].confidence < 0.18:
            return True
        if len(candidates) > 1 and abs(candidates[0].confidence - candidates[1].confidence) < 0.025:
            return True
        return False

    def _clarification_questions(
        self,
        request: str,
        repo_context: dict[str, Any],
        candidates: list[RouteCandidate],
    ) -> list[str]:
        questions = []
        if not candidates:
            questions.append("Which domain, toolchain, or target workflow should SkillRoute prioritize?")
        else:
            names = ", ".join(candidate.name for candidate in candidates[:3])
            questions.append(f"Should the route favor one of these close matches: {names}?")
        if not repo_context.get("languages"):
            questions.append("Is there repository or runtime context that should influence this skill choice?")
        if "risky" in request.lower() or "production" in request.lower():
            questions.append("Should SkillRoute prefer governance/review skills before implementation skills?")
        return questions[:3]


def lexical_score(query_tokens: set[str], skill: Any) -> float:
    facets_text = " ".join(value for values in skill.facets.values() for value in values)
    fields = [
        (skill.name, 2.5),
        (skill.description, 2.0),
        (" ".join(skill.tags), 1.5),
        (facets_text, 1.2),
        (" ".join(excerpt.text for excerpt in skill.excerpts), 1.0),
    ]
    return keyword_score(query_tokens, fields)


def semantic_score(backend_hit: dict[str, Any] | None) -> float:
    if not backend_hit:
        return 0.0
    score = max(float(backend_hit.get("score", 0.0)), 0.0)
    backend = str(backend_hit.get("backend", ""))
    if backend == "local-token":
        return min(score / 5.0, 1.0)
    return min(score, 1.0)


def confidence_for(total: float, semantic: float) -> float:
    return max(0.0, min(max(total / 2.5, semantic * 0.65), 0.99))


def repo_score(repo_context: dict[str, Any], skill: Any) -> float:
    languages = set(repo_context.get("languages", []))
    skill_languages = set(skill.facets.get("language", []))
    if not languages or not skill_languages:
        return 0.0
    return len(languages & skill_languages) / len(languages)


def graph_score(skill: Any) -> float:
    if not skill.relationships:
        return 0.0
    relation_weights = {
        "requires": 0.05,
        "complements": 0.04,
        "same_domain": 0.03,
        "supersedes": 0.02,
        "conflicts": -0.05,
    }
    return max(-0.2, min(0.2, sum(relation_weights.get(rel.type, 0.0) for rel in skill.relationships)))


def evidence_for(query_tokens: set[str], excerpts: list[SkillExcerpt]) -> list[SkillExcerpt]:
    ranked: list[tuple[int, SkillExcerpt]] = []
    for excerpt in excerpts:
        overlap = len(query_tokens & unique_tokens(excerpt.text))
        if overlap:
            ranked.append((overlap, excerpt))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [excerpt for _, excerpt in ranked[:3]]


def reasons_for(
    skill: Any,
    lexical: float,
    semantic: float,
    repo_context_score: float,
    graph: float,
    backend_name: str | None = None,
) -> list[str]:
    reasons = []
    if lexical > 0:
        reasons.append("Matched request terms against skill name, description, tags, or excerpts.")
    if semantic > 0:
        source = backend_name or "Retrieval backend"
        reasons.append(f"{source} retrieval returned this skill as a candidate.")
    if repo_context_score > 0:
        reasons.append("Repository language signals align with this skill's language facets.")
    if graph > 0:
        reasons.append("Skill graph relationships provide supporting context.")
    if graph < 0:
        reasons.append("Skill graph relationships include a conflict signal; review before use.")
    if skill.relationships:
        relation_names = sorted({relationship.type for relationship in skill.relationships})
        reasons.append(f"Known relationships: {', '.join(relation_names)}.")
    return reasons or ["Selected by fallback ranking."]


def dedupe_candidates(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    seen: set[str] = set()
    unique: list[RouteCandidate] = []
    for candidate in candidates:
        key = candidate.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def dedupe_search_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = str(row["name"]).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique
