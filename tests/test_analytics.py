"""Tests for the analytics layer.

These build traces through the real ``Catalog.record_route_trace`` path rather
than inserting rows by hand, so the SQL here is tested against the shape the
router actually writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillroute.analytics import (
    harness_breakdown,
    library_health,
    parse_since,
    routing_quality,
)
from skillroute.attribution import Attribution
from skillroute.catalog import Catalog
from skillroute.models import RouteCandidate, RouteResponse, ScoreBreakdown, SkillRecord


def make_skill(skill_id: str, name: str, description: str) -> SkillRecord:
    return SkillRecord(
        id=skill_id,
        name=name,
        description=description,
        skill_path=f"/tmp/{skill_id}/SKILL.md",
        bundle_path=f"/tmp/{skill_id}",
        root_path="/tmp",
        content_hash=skill_id,
    )


def candidate(
    skill: SkillRecord, confidence: float, *, position: int = 0, lexical: float = 0.5
) -> RouteCandidate:
    return RouteCandidate(
        skill_id=skill.id,
        name=skill.name,
        description=skill.description,
        confidence=confidence,
        reasons=[],
        evidence=[],
        score_breakdown=ScoreBreakdown(
            lexical=lexical, semantic=0.2, repo_context=0.1, graph=0.0, total=confidence
        ),
        suggested_position=position,
        content_hash=skill.content_hash,
    )


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    cat = Catalog(tmp_path / "catalog.db")
    cat.initialize()
    return cat


@pytest.fixture
def skills() -> list[SkillRecord]:
    return [
        make_skill("a", "deploy-app", "deploy the application to production"),
        make_skill("b", "deploy-application", "deploy an application to prod"),
        make_skill("c", "write-tests", "write unit tests for python code"),
        make_skill("d", "never-used", "a skill nothing ever routes to"),
    ]


def record(
    catalog: Catalog,
    skills: list[SkillRecord],
    request: str,
    ranked: list[RouteCandidate],
    *,
    harness: str | None = None,
    clarify: bool = False,
) -> None:
    response = RouteResponse(
        request=request,
        repo_context={},
        candidates=ranked,
        suggested_order=[c.skill_id for c in ranked],
        clarification_needed=clarify,
        clarification_questions=["which one?"] if clarify else [],
    )
    catalog.record_route_trace(
        {"request": request},
        response,
        attribution=Attribution(harness_id=harness, surface="cli"),
    )


# --- parse_since ----------------------------------------------------------


@pytest.mark.parametrize("spec", ["30d", "7d", "1d", "12h", "2w"])
def test_parse_since_accepts_relative_spans(spec: str) -> None:
    assert parse_since(spec) is not None


def test_parse_since_accepts_an_iso_date() -> None:
    assert parse_since("2026-01-01").startswith("2026-01-01")


def test_parse_since_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="since"):
        parse_since("last tuesday")


def test_parse_since_none_means_no_bound() -> None:
    assert parse_since(None) is None


# --- library health -------------------------------------------------------


def test_library_health_counts_indexed_skills(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    health = library_health(catalog)
    assert health.total_skills == 4


def test_library_health_flags_skills_that_are_never_offered(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(catalog, skills, "deploy it", [candidate(skills[0], 0.9)])
    health = library_health(catalog)
    never = {s.skill_id for s in health.never_offered}
    assert "d" in never
    assert "a" not in never


def test_library_health_separates_offered_but_never_won(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(
        catalog,
        skills,
        "deploy it",
        [candidate(skills[0], 0.9), candidate(skills[1], 0.4)],
    )
    health = library_health(catalog)
    never_won = {s.skill_id for s in health.never_won}
    assert "b" in never_won, "offered at rank 2 only"
    assert "a" not in never_won
    assert "d" not in never_won, "never offered is a different category"


def test_library_health_finds_near_duplicate_descriptions(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    health = library_health(catalog)
    pairs = {tuple(sorted((p.left_id, p.right_id))) for p in health.near_duplicates}
    assert ("a", "b") in pairs, "deploy-app and deploy-application compete"
    assert ("a", "c") not in pairs


def test_library_health_reports_win_counts(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    for _ in range(3):
        record(catalog, skills, "deploy", [candidate(skills[0], 0.9)])
    usage = {u.skill_id: u for u in health_usage(catalog)}
    assert usage["a"].won == 3
    assert usage["a"].offered == 3


def health_usage(catalog: Catalog) -> list:
    return library_health(catalog).top_skills


# --- routing quality ------------------------------------------------------


def test_routing_quality_counts_routes_and_clarifications(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(catalog, skills, "deploy", [candidate(skills[0], 0.9)])
    record(catalog, skills, "huh", [candidate(skills[0], 0.1)], clarify=True)
    quality = routing_quality(catalog)
    assert quality.routes == 2
    assert quality.clarification_rate == pytest.approx(0.5)


def test_routing_quality_reports_mean_top_confidence(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(catalog, skills, "a", [candidate(skills[0], 1.0)])
    record(catalog, skills, "b", [candidate(skills[0], 0.0)])
    assert routing_quality(catalog).mean_top_confidence == pytest.approx(0.5)


def test_routing_quality_buckets_confidence(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    for conf in (0.05, 0.15, 0.95):
        record(catalog, skills, "q", [candidate(skills[0], conf)])
    buckets = routing_quality(catalog).confidence_buckets
    assert sum(buckets.values()) == 3
    assert buckets["0.9-1.0"] == 1


def test_routing_quality_averages_score_components(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(catalog, skills, "q", [candidate(skills[0], 0.8, lexical=1.0)])
    components = routing_quality(catalog).component_means
    assert components["lexical"] == pytest.approx(1.0)
    assert components["graph"] == pytest.approx(0.0)


def test_routing_quality_on_an_empty_catalog_does_not_divide_by_zero(
    catalog: Catalog,
) -> None:
    quality = routing_quality(catalog)
    assert quality.routes == 0
    assert quality.clarification_rate == 0.0
    assert quality.mean_top_confidence == 0.0


# --- harness breakdown ----------------------------------------------------


def test_harness_breakdown_groups_by_caller(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(catalog, skills, "x", [candidate(skills[0], 0.9)], harness="claude-code")
    record(catalog, skills, "y", [candidate(skills[0], 0.5)], harness="claude-code")
    record(catalog, skills, "z", [candidate(skills[0], 0.7)], harness="pi")
    stats = {s.harness_id: s for s in harness_breakdown(catalog)}
    assert stats["claude-code"].routes == 2
    assert stats["pi"].routes == 1


def test_harness_breakdown_labels_unattributed_routes(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(catalog, skills, "x", [candidate(skills[0], 0.9)], harness=None)
    stats = harness_breakdown(catalog)
    assert any(s.harness_id == "unknown" for s in stats), (
        "an unattributed route must still be counted, not silently dropped"
    )


def test_harness_filter_narrows_every_family(
    catalog: Catalog, skills: list[SkillRecord]
) -> None:
    for skill in skills:
        catalog.upsert_skill(skill)
    record(catalog, skills, "x", [candidate(skills[0], 0.9)], harness="claude-code")
    record(catalog, skills, "y", [candidate(skills[1], 0.9)], harness="pi")
    assert routing_quality(catalog, harness="pi").routes == 1
    assert library_health(catalog, harness="pi").top_skills[0].skill_id == "b"
