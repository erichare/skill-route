from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

from skillroute.backends import RetrievalBackend
from skillroute.catalog import Catalog
from skillroute.evals import load_cases
from skillroute.routing import DEFAULT_WEIGHTS, Router, RouteWeights

# Threshold grids explored alongside the blend weights. Small on purpose: the
# eval corpora are small, so coarse steps avoid overfitting to a handful of
# cases while still moving the clarification behavior.
CONFIDENCE_FLOORS = (0.10, 0.15, 0.18, 0.22, 0.28)
CLARIFICATION_GAPS = (0.01, 0.025, 0.05)


@dataclass(frozen=True, slots=True)
class TuneResult:
    weights: dict[str, float]
    passed: int
    total: int
    mean_reciprocal_rank: float
    clarification_accuracy: float
    score: float

    def to_json(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "passed": self.passed,
            "total": self.total,
            "mean_reciprocal_rank": round(self.mean_reciprocal_rank, 4),
            "clarification_accuracy": round(self.clarification_accuracy, 4),
            "score": round(self.score, 4),
        }


def iter_blend_grid(step: float = 0.2) -> Iterator[dict[str, float]]:
    """Yield blend weights on the unit simplex at the given step.

    lexical + semantic + repo_context + graph always sum to 1.0 so confidence
    calibration stays comparable across the whole grid.
    """
    if step <= 0 or step > 1:
        raise ValueError("step must be in (0, 1]")
    steps = round(1.0 / step)
    for lexical_index in range(steps + 1):
        for semantic_index in range(steps + 1 - lexical_index):
            for repo_index in range(steps + 1 - lexical_index - semantic_index):
                graph_index = steps - lexical_index - semantic_index - repo_index
                yield {
                    "lexical": round(lexical_index * step, 6),
                    "semantic": round(semantic_index * step, 6),
                    "repo_context": round(repo_index * step, 6),
                    "graph": round(graph_index * step, 6),
                }


def evaluate_weights(
    catalog: Catalog,
    backend: RetrievalBackend | None,
    cases: list[dict[str, Any]],
    weights: RouteWeights,
) -> tuple[int, float, float]:
    """Score one weight set against eval cases.

    Returns (passed_count, mean_reciprocal_rank, clarification_accuracy).
    Routes are run with record_trace=False so tuning never pollutes traces.
    """
    router = Router(catalog, backend=backend, weights=weights)
    passed = 0
    reciprocal_ranks: list[float] = []
    clarification_hits = 0
    for case in cases:
        response = router.route(
            case["request"],
            repo=case.get("repo"),
            limit=int(case.get("limit", 5)),
            record_trace=False,
        )
        expected_names = case.get("expected_skill_names", [])
        expected_ids = case.get("expected_skill_ids", [])
        candidate_names = [candidate.name for candidate in response.candidates]
        candidate_ids = [candidate.skill_id for candidate in response.candidates]

        rank_pass = all(name in candidate_names for name in expected_names) and all(
            skill_id in candidate_ids for skill_id in expected_ids
        )
        expected_clarification = bool(case.get("expect_clarification", False))
        clarification_ok = response.clarification_needed is expected_clarification
        if rank_pass and clarification_ok:
            passed += 1
        if clarification_ok:
            clarification_hits += 1
        reciprocal_ranks.append(
            reciprocal_rank(candidate_names, candidate_ids, expected_names, expected_ids)
        )
    total = len(cases) or 1
    mean_reciprocal_rank = sum(reciprocal_ranks) / total
    clarification_accuracy = clarification_hits / total
    return passed, mean_reciprocal_rank, clarification_accuracy


def reciprocal_rank(
    candidate_names: list[str],
    candidate_ids: list[str],
    expected_names: list[str],
    expected_ids: list[str],
) -> float:
    """Reciprocal rank of the first expected candidate; 1.0 for empty expectations."""
    if not expected_names and not expected_ids:
        return 1.0
    for position, (name, skill_id) in enumerate(zip(candidate_names, candidate_ids), start=1):
        if name in expected_names or skill_id in expected_ids:
            return 1.0 / position
    return 0.0


def tune_weights(
    catalog: Catalog,
    cases_path: Path,
    backend: RetrievalBackend | None = None,
    step: float = 0.2,
) -> list[TuneResult]:
    """Grid-search blend weights and thresholds against golden-route cases.

    The built-in default weights are always evaluated first so they can only be
    displaced by a weight set that scores strictly better (or ties and sits
    closer to the defaults, which the defaults always win). Results are sorted
    best-first; ties prefer weight sets closer to the built-in defaults so
    tuning never changes behavior without evidence.
    """
    cases = load_cases(cases_path)
    if not cases:
        return []
    results: list[TuneResult] = []
    default_weights = RouteWeights()
    passed, mrr, clarification_accuracy = evaluate_weights(catalog, backend, cases, default_weights)
    results.append(
        TuneResult(
            weights=default_weights.to_json(),
            passed=passed,
            total=len(cases),
            mean_reciprocal_rank=mrr,
            clarification_accuracy=clarification_accuracy,
            score=passed / len(cases) + mrr + 0.25 * clarification_accuracy,
        )
    )
    for blend in iter_blend_grid(step):
        if blend == {name: DEFAULT_WEIGHTS[name] for name in ("lexical", "semantic", "repo_context", "graph")}:
            continue  # evaluated above
        for floor, gap in product(CONFIDENCE_FLOORS, CLARIFICATION_GAPS):
            weights = RouteWeights.from_overrides(
                {**blend, "confidence_floor": floor, "clarification_gap": gap}
            )
            passed, mrr, clarification_accuracy = evaluate_weights(catalog, backend, cases, weights)
            score = passed / len(cases) + mrr + 0.25 * clarification_accuracy
            results.append(
                TuneResult(
                    weights=weights.to_json(),
                    passed=passed,
                    total=len(cases),
                    mean_reciprocal_rank=mrr,
                    clarification_accuracy=clarification_accuracy,
                    score=score,
                )
            )
    results.sort(key=lambda result: (-result.score, distance_from_defaults(result.weights)))
    return results


def distance_from_defaults(weights: dict[str, float]) -> float:
    """L2 distance from the built-in defaults, used as a deterministic tiebreak."""
    return sum(
        (weights.get(name, default) - default) ** 2 for name, default in DEFAULT_WEIGHTS.items()
    ) ** 0.5
