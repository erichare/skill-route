from __future__ import annotations

from pathlib import Path

from skillroute.catalog import Catalog
from skillroute.evals import run_golden_routes
from skillroute.routing import Router


def test_golden_route_eval_passes(indexed_catalog: Catalog) -> None:
    cases = Path(__file__).parent / "fixtures" / "golden_routes.json"

    results = run_golden_routes(Router(indexed_catalog), cases)

    assert len(results) == 4
    assert all(result.passed for result in results)

