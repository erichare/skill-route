from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillroute.catalog import Catalog
from skillroute.routing import DEFAULT_WEIGHTS, Router, RouteWeights
from skillroute.tuning import (
    CLARIFICATION_GAPS,
    CONFIDENCE_FLOORS,
    distance_from_defaults,
    evaluate_weights,
    grid_divisions,
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


def test_route_weights_rejects_non_finite() -> None:
    """inf/NaN slip past a >= 0 check and would poison every score."""
    for bad in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError, match="must be finite"):
            RouteWeights.from_overrides({"lexical": bad})


def test_route_weights_from_env_rejects_non_finite(monkeypatch: pytest.MonkeyPatch) -> None:
    # Python's json accepts both of these spellings even though neither is
    # standard JSON, so the env path has to reject them itself.
    monkeypatch.setenv("SKILLROUTE_WEIGHTS", '{"lexical": 1e999}')
    with pytest.raises(ValueError, match="must be finite"):
        RouteWeights.from_env()

    monkeypatch.setenv("SKILLROUTE_WEIGHTS", '{"lexical": NaN}')
    with pytest.raises(ValueError, match="must be finite"):
        RouteWeights.from_env()


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


def test_iter_blend_grid_stays_on_simplex_for_awkward_steps() -> None:
    """A step that does not divide 1 evenly must still sum to 1.0, not 0.9/1.2.

    Multiplying an index by the raw step made every blend sum to 0.9 at
    step=0.3 and 1.2 at step=0.6, silently rescaling confidence across runs.
    """
    for step in (0.3, 0.4, 0.6, 0.7):
        grid = list(iter_blend_grid(step=step))
        assert grid
        for blend in grid:
            assert sum(blend.values()) == pytest.approx(1.0, abs=1e-6)
            assert all(value >= 0 for value in blend.values())


def test_grid_divisions_snaps_step_to_nearest_reciprocal() -> None:
    assert grid_divisions(0.2) == 5
    assert grid_divisions(0.5) == 2
    assert grid_divisions(0.3) == 3  # snapped to 1/3
    assert grid_divisions(0.7) == 1  # snapped to 1/1
    assert grid_divisions(1.0) == 1


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


def test_tune_weights_explores_thresholds_for_the_default_blend(
    tmp_path: Path, fixture_skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default blend with non-default thresholds must stay reachable.

    Skipping the default blend wholesale (rather than the exact default weight
    set) meant a corpus whose best result is a clarification-threshold change
    at the default ranking weights could never surface it. Only steps that put
    the default blend on the grid hit this, so the grid is stubbed to it.
    """
    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(fixture_skills_root)
    cases_path = Path(__file__).parent / "fixtures" / "golden_routes.json"
    default_blend = {
        name: DEFAULT_WEIGHTS[name]
        for name in ("lexical", "semantic", "repo_context", "graph")
    }
    monkeypatch.setattr(
        "skillroute.tuning.iter_blend_grid", lambda step=0.2: iter([dict(default_blend)])
    )

    results = tune_weights(catalog, cases_path)

    # The default weight set, plus every other floor x gap pairing of the same
    # blend -- 5 floors x 3 gaps, with the exact default deduped out.
    assert len(results) == len(CONFIDENCE_FLOORS) * len(CLARIFICATION_GAPS)
    assert all(
        {name: result.weights[name] for name in default_blend} == default_blend
        for result in results
    )
    thresholds = {
        (result.weights["confidence_floor"], result.weights["clarification_gap"])
        for result in results
    }
    assert len(thresholds) == len(results), "duplicate threshold pairs were scored"
    assert (DEFAULT_WEIGHTS["confidence_floor"], DEFAULT_WEIGHTS["clarification_gap"]) in thresholds


def test_tune_weights_empty_cases(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.db")
    empty_cases = tmp_path / "empty.json"
    empty_cases.write_text("[]", encoding="utf-8")

    assert tune_weights(catalog, empty_cases) == []
