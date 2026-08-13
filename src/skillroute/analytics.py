"""Answer questions about a skill library from recorded routes.

Schema v2 denormalized every ranked candidate into ``route_trace_candidates``
precisely so this module could be SQL over columns rather than a loop that
parses twenty thousand JSON blobs. Everything here is a pure function of the
catalog: no rendering, no I/O beyond the query, so the CLI, the report package,
and the UI can each present the same numbers their own way.

The questions worth answering, per the 0.2 plan:

- *Library health* -- which skills never win, which ones compete with each
  other, and which are dead weight. This is the "skill bloat" story: a library
  of 400 skills where 37 have never once been offered is a fact you cannot see
  without this.
- *Routing quality* -- confidence distribution, clarification rate, and which
  score component is actually carrying the ranking.
- *Per-harness* -- who asked, and how well it went for them.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from skillroute.catalog import Catalog
from skillroute.text import unique_tokens

# A pair of skills whose descriptions overlap this much competes for the same
# requests. Jaccard over description tokens: at 0.5 half the vocabulary is
# shared, which in practice is where two skills start shadowing each other.
DUPLICATE_THRESHOLD = 0.5

CONFIDENCE_BUCKETS = (
    (0.0, 0.1, "0.0-0.1"),
    (0.1, 0.3, "0.1-0.3"),
    (0.3, 0.5, "0.3-0.5"),
    (0.5, 0.7, "0.5-0.7"),
    (0.7, 0.9, "0.7-0.9"),
    (0.9, 1.01, "0.9-1.0"),
)

SCORE_COMPONENTS = ("lexical", "semantic", "repo_context", "graph")

# Routes with no harness recorded (pre-0.2 traces, or a caller that did not
# identify itself) are reported under this label rather than dropped.
UNKNOWN_HARNESS = "unknown"

_SPAN = re.compile(r"^(\d+)([hdw])$")
_SPAN_UNITS = {"h": "hours", "d": "days", "w": "weeks"}


@dataclass(frozen=True, slots=True)
class SkillUsage:
    skill_id: str
    name: str
    offered: int
    won: int
    mean_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "offered": self.offered,
            "won": self.won,
            "mean_confidence": round(self.mean_confidence, 4),
        }


@dataclass(frozen=True, slots=True)
class DuplicatePair:
    left_id: str
    right_id: str
    left_name: str
    right_name: str
    similarity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_id": self.left_id,
            "right_id": self.right_id,
            "left_name": self.left_name,
            "right_name": self.right_name,
            "similarity": round(self.similarity, 4),
        }


@dataclass(frozen=True, slots=True)
class LibraryHealth:
    total_skills: int
    offered_skills: int
    never_offered: tuple[SkillUsage, ...] = ()
    never_won: tuple[SkillUsage, ...] = ()
    top_skills: tuple[SkillUsage, ...] = ()
    near_duplicates: tuple[DuplicatePair, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_skills": self.total_skills,
            "offered_skills": self.offered_skills,
            "never_offered": [s.to_dict() for s in self.never_offered],
            "never_won": [s.to_dict() for s in self.never_won],
            "top_skills": [s.to_dict() for s in self.top_skills],
            "near_duplicates": [p.to_dict() for p in self.near_duplicates],
        }


@dataclass(frozen=True, slots=True)
class RoutingQuality:
    routes: int
    clarification_rate: float
    mean_top_confidence: float
    confidence_buckets: dict[str, int] = field(default_factory=dict)
    component_means: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "routes": self.routes,
            "clarification_rate": round(self.clarification_rate, 4),
            "mean_top_confidence": round(self.mean_top_confidence, 4),
            "confidence_buckets": self.confidence_buckets,
            "component_means": {k: round(v, 4) for k, v in self.component_means.items()},
        }


@dataclass(frozen=True, slots=True)
class HarnessStats:
    harness_id: str
    routes: int
    clarification_rate: float
    mean_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness_id": self.harness_id,
            "routes": self.routes,
            "clarification_rate": round(self.clarification_rate, 4),
            "mean_confidence": round(self.mean_confidence, 4),
        }


def parse_since(spec: str | None) -> str | None:
    """Turn ``30d`` or ``2026-01-01`` into an ISO timestamp bound.

    Returns None for None, meaning "no lower bound" -- callers pass the result
    straight into a query that skips the predicate when it is None.
    """
    if spec is None:
        return None
    text = spec.strip()
    match = _SPAN.match(text)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        delta = dt.timedelta(**{_SPAN_UNITS[unit]: amount})
        return (dt.datetime.now(dt.UTC) - delta).strftime("%Y-%m-%d %H:%M:%S")
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"Cannot parse --since {spec!r}; expected a span like 30d, 12h, 2w "
            "or an ISO date like 2026-01-01."
        ) from exc
    return f"{parsed.isoformat()} 00:00:00"


def _trace_filter(since: str | None, harness: str | None) -> tuple[str, list[Any]]:
    """Shared WHERE fragment so every family filters identically."""
    clauses: list[str] = []
    params: list[Any] = []
    if since:
        clauses.append("t.created_at >= ?")
        params.append(since)
    if harness:
        # An explicit `unknown` filter has to match NULL, which is how an
        # unattributed route is stored.
        if harness == UNKNOWN_HARNESS:
            clauses.append("(t.harness_id IS NULL OR t.harness_id = '')")
        else:
            clauses.append("t.harness_id = ?")
            params.append(harness)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def library_health(
    catalog: Catalog,
    *,
    since: str | None = None,
    harness: str | None = None,
    limit: int = 10,
) -> LibraryHealth:
    where, params = _trace_filter(since, harness)
    with catalog._session() as connection:
        total = connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT c.skill_id AS skill_id,
                   MAX(c.name) AS name,
                   COUNT(*) AS offered,
                   SUM(CASE WHEN c.position = 1 THEN 1 ELSE 0 END) AS won,
                   AVG(c.confidence) AS mean_confidence
            FROM route_trace_candidates c
            JOIN route_traces t ON t.id = c.trace_id
            {where}
            GROUP BY c.skill_id
            """,
            params,
        ).fetchall()
        usage = [
            SkillUsage(
                skill_id=row["skill_id"],
                name=row["name"] or row["skill_id"],
                offered=row["offered"],
                won=row["won"] or 0,
                mean_confidence=row["mean_confidence"] or 0.0,
            )
            for row in rows
        ]
        seen = {item.skill_id for item in usage}
        dead = connection.execute(
            "SELECT id, name FROM skills ORDER BY name"
        ).fetchall()
        never_offered = tuple(
            SkillUsage(row["id"], row["name"], 0, 0, 0.0)
            for row in dead
            if row["id"] not in seen
        )
        duplicates = _near_duplicates(connection)

    ranked = sorted(usage, key=lambda item: (-item.won, -item.offered, item.skill_id))
    return LibraryHealth(
        total_skills=total,
        offered_skills=len(usage),
        never_offered=never_offered,
        never_won=tuple(
            item for item in ranked if item.won == 0 and item.offered > 0
        )[:limit],
        top_skills=tuple(ranked[:limit]),
        near_duplicates=duplicates[:limit],
    )


def _near_duplicates(connection: sqlite3.Connection) -> tuple[DuplicatePair, ...]:
    """Skills whose descriptions compete for the same requests.

    Jaccard over description tokens: no new dependency, and it reuses the same
    tokenizer and stopword list the router scores with, so "similar" here means
    similar to the thing actually doing the ranking.
    """
    rows = connection.execute("SELECT id, name, description FROM skills").fetchall()
    tokens = {row["id"]: unique_tokens(row["description"] or "") for row in rows}
    names = {row["id"]: row["name"] for row in rows}
    pairs: list[DuplicatePair] = []
    ids = sorted(tokens)
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            left_tokens, right_tokens = tokens[left], tokens[right]
            if not left_tokens or not right_tokens:
                continue
            union = left_tokens | right_tokens
            similarity = len(left_tokens & right_tokens) / len(union)
            if similarity >= DUPLICATE_THRESHOLD:
                pairs.append(
                    DuplicatePair(left, right, names[left], names[right], similarity)
                )
    return tuple(sorted(pairs, key=lambda p: -p.similarity))


def routing_quality(
    catalog: Catalog, *, since: str | None = None, harness: str | None = None
) -> RoutingQuality:
    where, params = _trace_filter(since, harness)
    with catalog._session() as connection:
        summary = connection.execute(
            f"""
            SELECT COUNT(*) AS routes,
                   SUM(COALESCE(t.clarification_needed, 0)) AS clarifications,
                   AVG(COALESCE(t.top_confidence, 0)) AS mean_confidence
            FROM route_traces t
            {where}
            """,
            params,
        ).fetchone()
        routes = summary["routes"] or 0
        if not routes:
            return RoutingQuality(0, 0.0, 0.0, {label: 0 for *_, label in CONFIDENCE_BUCKETS}, {})

        confidences = [
            row[0]
            for row in connection.execute(
                f"SELECT COALESCE(t.top_confidence, 0) FROM route_traces t {where}",
                params,
            ).fetchall()
        ]
        components = connection.execute(
            f"""
            SELECT AVG(c.lexical) AS lexical,
                   AVG(c.semantic) AS semantic,
                   AVG(c.repo_context) AS repo_context,
                   AVG(c.graph) AS graph
            FROM route_trace_candidates c
            JOIN route_traces t ON t.id = c.trace_id
            {where}
            """,
            params,
        ).fetchone()

    return RoutingQuality(
        routes=routes,
        clarification_rate=(summary["clarifications"] or 0) / routes,
        mean_top_confidence=summary["mean_confidence"] or 0.0,
        confidence_buckets=_bucket(confidences),
        component_means={
            name: (components[name] if components and components[name] else 0.0)
            for name in SCORE_COMPONENTS
        },
    )


def _bucket(values: list[float]) -> dict[str, int]:
    buckets = {label: 0 for *_, label in CONFIDENCE_BUCKETS}
    for value in values:
        for low, high, label in CONFIDENCE_BUCKETS:
            if low <= value < high:
                buckets[label] += 1
                break
    return buckets


def harness_breakdown(
    catalog: Catalog, *, since: str | None = None
) -> list[HarnessStats]:
    where, params = _trace_filter(since, None)
    with catalog._session() as connection:
        rows = connection.execute(
            f"""
            SELECT COALESCE(NULLIF(t.harness_id, ''), '{UNKNOWN_HARNESS}') AS harness_id,
                   COUNT(*) AS routes,
                   SUM(COALESCE(t.clarification_needed, 0)) AS clarifications,
                   AVG(COALESCE(t.top_confidence, 0)) AS mean_confidence
            FROM route_traces t
            {where}
            GROUP BY 1
            ORDER BY routes DESC, harness_id
            """,
            params,
        ).fetchall()
    return [
        HarnessStats(
            harness_id=row["harness_id"],
            routes=row["routes"],
            clarification_rate=(row["clarifications"] or 0) / row["routes"],
            mean_confidence=row["mean_confidence"] or 0.0,
        )
        for row in rows
    ]


def render_stats(
    health: LibraryHealth,
    quality: RoutingQuality,
    harnesses: list[HarnessStats],
    *,
    since: str | None = None,
) -> str:
    """Plain-text rendering. The report package (S4's other half) will replace
    this with a proper renderer; this keeps `skillroute stats` useful now."""
    lines: list[str] = []
    scope = f" since {since}" if since else ""
    lines.append(f"Routes{scope}: {quality.routes}")
    if quality.routes:
        lines.append(
            f"  mean top confidence {quality.mean_top_confidence:.2f}"
            f" | clarification rate {quality.clarification_rate:.0%}"
        )
        spread = " ".join(
            f"{label}:{count}" for label, count in quality.confidence_buckets.items()
        )
        lines.append(f"  confidence  {spread}")
        mix = " ".join(f"{k}:{v:.2f}" for k, v in quality.component_means.items())
        lines.append(f"  components  {mix}")

    lines.append("")
    lines.append(
        f"Library: {health.total_skills} skills, {health.offered_skills} ever offered"
    )
    if health.never_offered:
        names = ", ".join(s.name for s in health.never_offered[:8])
        more = "" if len(health.never_offered) <= 8 else f" (+{len(health.never_offered) - 8} more)"
        lines.append(f"  never offered ({len(health.never_offered)}): {names}{more}")
    if health.never_won:
        lines.append(
            "  offered but never first: "
            + ", ".join(f"{s.name} x{s.offered}" for s in health.never_won)
        )
    if health.top_skills:
        lines.append("  most routed:")
        width = max(len(s.name) for s in health.top_skills)
        for skill in health.top_skills:
            lines.append(
                f"    {skill.name:<{width}}  won {skill.won:>4}"
                f"  offered {skill.offered:>4}  conf {skill.mean_confidence:.2f}"
            )
    if health.near_duplicates:
        lines.append("  competing descriptions:")
        for pair in health.near_duplicates:
            lines.append(
                f"    {pair.left_name} ~ {pair.right_name}  ({pair.similarity:.0%})"
            )

    if harnesses:
        lines.append("")
        lines.append("By harness:")
        width = max(len(h.harness_id) for h in harnesses)
        for stats in harnesses:
            lines.append(
                f"  {stats.harness_id:<{width}}  {stats.routes:>5} routes"
                f"  conf {stats.mean_confidence:.2f}"
                f"  clarify {stats.clarification_rate:.0%}"
            )
    return "\n".join(lines)
