from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skillroute.models import to_jsonable
from skillroute.routing import Router


@dataclass(slots=True)
class EvalResult:
    name: str
    passed: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    notes: list[str]


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_golden_routes(router: Router, cases_path: Path) -> list[EvalResult]:
    results: list[EvalResult] = []
    for case in load_cases(cases_path):
        response = router.route(
            case["request"],
            repo=case.get("repo"),
            limit=int(case.get("limit", 5)),
        )
        candidate_names = [candidate.name for candidate in response.candidates]
        candidate_ids = [candidate.skill_id for candidate in response.candidates]
        expected_names = case.get("expected_skill_names", [])
        expected_ids = case.get("expected_skill_ids", [])
        notes: list[str] = []

        rank_pass = True
        for expected_name in expected_names:
            if expected_name not in candidate_names:
                rank_pass = False
                notes.append(f"missing expected skill name: {expected_name}")
        for expected_id in expected_ids:
            if expected_id not in candidate_ids:
                rank_pass = False
                notes.append(f"missing expected skill id: {expected_id}")

        expected_clarification = bool(case.get("expect_clarification", False))
        clarification_pass = response.clarification_needed is expected_clarification
        if not clarification_pass:
            notes.append(
                f"clarification expected {expected_clarification}, got {response.clarification_needed}"
            )

        results.append(
            EvalResult(
                name=case.get("name", case["request"]),
                passed=rank_pass and clarification_pass,
                expected={
                    "skill_names": expected_names,
                    "skill_ids": expected_ids,
                    "clarification_needed": expected_clarification,
                },
                actual=to_jsonable(response),
                notes=notes,
            )
        )
    return results

