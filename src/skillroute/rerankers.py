from __future__ import annotations

import json
import os
import subprocess
from typing import Protocol

from skillroute.models import RouteCandidate, to_jsonable


class Reranker(Protocol):
    def rerank(self, request: str, candidates: list[RouteCandidate]) -> list[RouteCandidate]:
        ...


class HeuristicReranker:
    def rerank(self, request: str, candidates: list[RouteCandidate]) -> list[RouteCandidate]:
        return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)


class ExternalCommandReranker:
    """LLM-compatible reranker hook using a local command contract.

    The command receives JSON on stdin with the request and candidates, and must
    return JSON with `ordered_skill_ids`. This keeps the core provider-neutral
    while allowing OpenAI, local models, or custom rerankers to plug in later.
    """

    def __init__(self, command: str) -> None:
        self.command = command

    def rerank(self, request: str, candidates: list[RouteCandidate]) -> list[RouteCandidate]:
        payload = {"request": request, "candidates": to_jsonable(candidates)}
        completed = subprocess.run(
            self.command,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            shell=True,
            check=False,
        )
        if completed.returncode != 0:
            return candidates
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return candidates
        ordered_ids = result.get("ordered_skill_ids")
        if not isinstance(ordered_ids, list):
            return candidates
        by_id = {candidate.skill_id: candidate for candidate in candidates}
        ordered = [by_id[skill_id] for skill_id in ordered_ids if skill_id in by_id]
        ordered.extend(candidate for candidate in candidates if candidate.skill_id not in ordered_ids)
        for index, candidate in enumerate(ordered, start=1):
            candidate.suggested_position = index
        return ordered


def default_reranker() -> Reranker:
    command = os.environ.get("SKILLROUTE_RERANKER_CMD")
    if command:
        return ExternalCommandReranker(command)
    return HeuristicReranker()

