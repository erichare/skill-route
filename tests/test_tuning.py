from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillroute.catalog import Catalog
from skillroute.routing import DEFAULT_WEIGHTS, Router, RouteWeights
from skillroute.tuning import (
    distance_from_defaults,
    evaluate_weights,
    iter_blend_grid,
    reciprocal_rank,
    tune_weights,
)


def test_route_weights_defaults_match_history() -> None:
    weights = RouteWeights()
    assert weights.to_json() == DEFAULT_WEIGHTS
    assert weights.lexical == 0.5
    assert weights.semantic == 0.25
    assert weights.confidence_floor == 0.18
    assert weights.clarification_gap == 0.025


def test_route_weights_from_overrides_partial() -> None:
    weights = RouteWeights.from_overrides({"lexical": 0.7, "semantic": 0.3})
    assert weights.lexical == 0.7
    assert weights.semantic == 0.3
    assert weights.repo_context == DEFAULT_WEIGHTS["repo_context"]


def test_route_weights_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="Unknown route weight keys"):
        RouteWeights.from_overrides({"lexical": 0.5, "bogus": 1.0})


def test_route_weights_rejects_negative_and_non_numeric() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        RouteWeights.from_overrides({"graph": -0.1})
    with pytest.raises(ValueError, match="must be a number"):
        RouteWeights.from_overrides({"graph": "lots"})


def test_route_weights_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLROUTE_WEIGHTS", json.dumps({"lexical": 0.8, "semantic": 0.2}))
    weights = RouteWeights.from_env()
    assert weights.lexical == 0.8
    assert weights.semantic == 0.2

    monkeypatch.setenv("SKILLROUTE_WEIGHTS", "")
    assert RouteWeights.from_env() == RouteWeights()


def test_route_weights_from_env_rejects_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLROUTE_WEIGHTS", "{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        RouteWeights.from_env()

    monkeypatch.setenv("SKILLROUTE_WEIGHTS", "[1, 2]")
    with pytest.raises(TypeError, match="JSON object"):
        RouteWeights.from_env()


def test_router_weights_change_ranking(indexed_catalog: Catalog) -> None:
    """Zeroing the lexical weight must change the score blend."""
    request = "Build an MCP server with tools"
    baseline = Router(indexed_catalog).route(request, record_trace=False)
    reweighted = Router(
        indexed_catalog,
        weights=RouteWeights.from_overrides({"lexical": 0.0, "semantic": 1.0}),
    ).route(request, record_trace=False)

    baseline_scores = [c.score_breakdown.total for c in baseline.candidates]
    reweighted_scores = [c.score_breakdown.total for c in reweighted.candidates]
    assert baseline_scores != reweighted_scores


def test_iter_blend_grid_covers_simplex() -> None:
    grid = list(iter_blend_grid(step=0.5))
    # Compositions of 1.0 into 4 parts at step 0.5 (2 units): C(2+3, 3) = 10.
    assert len(grid) == 10
    for blend in grid:
        assert sum(blend.values()) == pytest.approx(1.0)
        assert all(value >= 0 for value in blend.values())
    assert {"lexical": 1.0, "semantic": 0.0, "repo_context": 0.0, "graph": 0.0} in grid


def test_iter_blend_grid_rejects_bad_step() -> None:
    with pytest.raises(ValueError, match="step"):
        list(iter_blend_grid(step=0.0))
    with pytest.raises(ValueError, match="step"):
        list(iter_blend_grid(step=1.5))


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["a", "b"], ["a-id", "b-id"], ["b"], []) == 0.5
    assert reciprocal_rank(["a", "b"], ["a-id", "b-id"], [], ["b-id"]) == 0.5
    assert reciprocal_rank(["a"], ["a-id"], ["missing"], []) == 0.0
    assert reciprocal_rank([], [], [], []) == 1.0


def test_evaluate_weights_counts_passes(indexed_catalog: Catalog) -> None:
    cases = json.loads(
        (Path(__file__).parent / "fixtures" / "golden_routes.json").read_text(encoding="utf-8")
    )
    passed, mrr, clarification_accuracy = evaluate_weights(
        indexed_catalog, None, cases, RouteWeights()
    )
    assert passed == len(cases)
    assert mrr > 0
    assert clarification_accuracy == 1.0


def test_distance_from_defaults() -> None:
    assert distance_from_defaults(DEFAULT_WEIGHTS) == 0.0
    moved = dict(DEFAULT_WEIGHTS)
    moved["lexical"] = DEFAULT_WEIGHTS["lexical"] + 0.3
    assert distance_from_defaults(moved) == pytest.approx(0.3)


def test_tune_weights_prefers_defaults_when_all_pass(
    tmp_path: Path, fixture_skills_root: Path
) -> None:
    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(fixture_skills_root)
    cases_path = Path(__file__).parent / "fixtures" / "golden_routes.json"

    results = tune_weights(catalog, cases_path, step=0.5)

    assert results
    best = results[0]
    assert best.passed == best.total
    scores = [result.score for result in results]
    assert scores == sorted(scores, reverse=True)
    # Default weights pass every case, so the tiebreak keeps them on top.
    assert best.weights == DEFAULT_WEIGHTS


def test_tune_weights_empty_cases(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.db")
    empty_cases = tmp_path / "empty.json"
    empty_cases.write_text("[]", encoding="utf-8")

    assert tune_weights(catalog, empty_cases) == []
