from __future__ import annotations

import shlex
import sys

from skillroute.models import RouteCandidate, ScoreBreakdown
from skillroute.rerankers import (
    ExternalCommandReranker,
    HeuristicReranker,
    default_reranker,
)


def make_candidate(skill_id: str, confidence: float) -> RouteCandidate:
    return RouteCandidate(
        skill_id=skill_id,
        name=skill_id,
        description="",
        confidence=confidence,
        reasons=[],
        evidence=[],
        score_breakdown=ScoreBreakdown(0.0, 0.0, 0.0, 0.0, confidence),
        suggested_position=0,
        content_hash=skill_id,
    )


def command_for(script: str) -> str:
    return f"{sys.executable} -c {shlex.quote(script)}"


def test_heuristic_reranker_sorts_by_confidence() -> None:
    candidates = [make_candidate("a", 0.2), make_candidate("b", 0.9)]
    ordered = HeuristicReranker().rerank("req", candidates)
    assert [candidate.skill_id for candidate in ordered] == ["b", "a"]


def test_external_reranker_applies_returned_order() -> None:
    script = (
        "import sys, json; data = json.load(sys.stdin); "
        "ids = [candidate['skill_id'] for candidate in data['candidates']][::-1]; "
        "print(json.dumps({'ordered_skill_ids': ids}))"
    )
    reranker = ExternalCommandReranker(command_for(script))
    ordered = reranker.rerank("req", [make_candidate("a", 0.5), make_candidate("b", 0.5)])
    assert [candidate.skill_id for candidate in ordered] == ["b", "a"]


def test_external_reranker_keeps_unlisted_candidates_at_end() -> None:
    script = "import sys, json; json.load(sys.stdin); print(json.dumps({'ordered_skill_ids': ['b']}))"
    reranker = ExternalCommandReranker(command_for(script))
    ordered = reranker.rerank("req", [make_candidate("a", 0.5), make_candidate("b", 0.5)])
    assert [candidate.skill_id for candidate in ordered] == ["b", "a"]


def test_external_reranker_falls_back_on_nonzero_exit() -> None:
    reranker = ExternalCommandReranker(command_for("import sys; sys.exit(3)"))
    candidates = [make_candidate("a", 0.5), make_candidate("b", 0.5)]
    ordered = reranker.rerank("req", candidates)
    assert ordered == candidates


def test_external_reranker_falls_back_on_invalid_json() -> None:
    reranker = ExternalCommandReranker(command_for("print('not json')"))
    candidates = [make_candidate("a", 0.5), make_candidate("b", 0.5)]
    ordered = reranker.rerank("req", candidates)
    assert ordered == candidates


def test_external_reranker_falls_back_when_command_missing() -> None:
    reranker = ExternalCommandReranker("definitely-not-a-real-binary-xyz")
    candidates = [make_candidate("a", 0.5)]
    assert reranker.rerank("req", candidates) == candidates


def test_external_reranker_ignores_non_list_order() -> None:
    script = "import sys, json; json.load(sys.stdin); print(json.dumps({'ordered_skill_ids': 'nope'}))"
    reranker = ExternalCommandReranker(command_for(script))
    candidates = [make_candidate("a", 0.5)]
    assert reranker.rerank("req", candidates) == candidates


def test_default_reranker_selects_external_when_env_set(monkeypatch) -> None:
    monkeypatch.setenv("SKILLROUTE_RERANKER_CMD", "true")
    assert isinstance(default_reranker(), ExternalCommandReranker)


def test_default_reranker_is_heuristic_without_env(monkeypatch) -> None:
    monkeypatch.delenv("SKILLROUTE_RERANKER_CMD", raising=False)
    assert isinstance(default_reranker(), HeuristicReranker)
