from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from skillroute.backends import AstraDataAPIBackend, AstraDataAPIError, LocalTokenBackend, RetrievalBackend
from skillroute.catalog import Catalog, default_catalog_path
from skillroute.dogfood import discover_default_skill_roots, index_default_skill_roots
from skillroute.evals import run_golden_routes
from skillroute.metadata import default_overlay_path, review_metadata_overlay, write_metadata_overlay
from skillroute.models import to_jsonable
from skillroute.routing import Router


BACKEND_CHOICES = ("local", "local-token", "astra", "astra-data-api")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        if getattr(args, "bridge", False):
            print(json.dumps({"error": {"type": exc.__class__.__name__, "message": str(exc)}}))
            raise SystemExit(1) from exc
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillroute")
    parser.add_argument("--catalog", type=Path, default=None, help="Path to the SQLite catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Index SKILL.md bundles under a root")
    index_parser.add_argument("--root", type=Path, required=True)
    index_parser.set_defaults(func=cmd_index)

    route_parser = subparsers.add_parser("route", help="Route a request to ranked skills")
    route_parser.add_argument("request")
    route_parser.add_argument("--repo", type=Path, default=None)
    route_parser.add_argument("--limit", type=int, default=5)
    add_backend_argument(route_parser)
    route_parser.add_argument("--json", action="store_true", dest="as_json")
    route_parser.set_defaults(func=cmd_route)

    search_parser = subparsers.add_parser("search", help="Search indexed skills")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    add_backend_argument(search_parser)
    search_parser.add_argument("--json", action="store_true", dest="as_json")
    search_parser.set_defaults(func=cmd_search)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one skill by id or name")
    inspect_parser.add_argument("skill_id")
    inspect_parser.add_argument("--json", action="store_true", dest="as_json")
    inspect_parser.set_defaults(func=cmd_inspect)

    eval_parser = subparsers.add_parser("eval", help="Run eval commands")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run", help="Run golden route evals")
    eval_run_parser.add_argument("--cases", type=Path, required=True)
    eval_run_parser.add_argument(
        "--index-root",
        type=Path,
        action="append",
        default=[],
        help="Index a skill root before running evals. Can be passed multiple times.",
    )
    eval_run_parser.add_argument(
        "--fresh",
        action="store_true",
        help="Run evals against a temporary isolated catalog.",
    )
    add_backend_argument(eval_run_parser)
    eval_run_parser.add_argument("--json", action="store_true", dest="as_json")
    eval_run_parser.set_defaults(func=cmd_eval_run)

    dogfood_parser = subparsers.add_parser("dogfood", help="Dogfood SkillRoute against local skill roots")
    dogfood_subparsers = dogfood_parser.add_subparsers(dest="dogfood_command", required=True)
    dogfood_roots_parser = dogfood_subparsers.add_parser("roots", help="List discoverable local skill roots")
    dogfood_roots_parser.add_argument("--home", type=Path, default=None)
    dogfood_roots_parser.add_argument("--json", action="store_true", dest="as_json")
    dogfood_roots_parser.set_defaults(func=cmd_dogfood_roots)
    dogfood_index_parser = dogfood_subparsers.add_parser("index", help="Index discoverable local skill roots")
    dogfood_index_parser.add_argument("--home", type=Path, default=None)
    dogfood_index_parser.add_argument("--json", action="store_true", dest="as_json")
    dogfood_index_parser.set_defaults(func=cmd_dogfood_index)

    metadata_parser = subparsers.add_parser("metadata", help="Create and review skill metadata overlays")
    metadata_subparsers = metadata_parser.add_subparsers(dest="metadata_command", required=True)
    metadata_suggest_parser = metadata_subparsers.add_parser(
        "suggest",
        help="Write reviewable metadata suggestions as an overlay JSON file",
    )
    metadata_suggest_parser.add_argument("--root", type=Path, required=True)
    metadata_suggest_parser.add_argument("--output", type=Path, default=None)
    metadata_suggest_parser.add_argument("--force", action="store_true")
    metadata_suggest_parser.add_argument("--json", action="store_true", dest="as_json")
    metadata_suggest_parser.set_defaults(func=cmd_metadata_suggest)
    metadata_review_parser = metadata_subparsers.add_parser(
        "review",
        help="Validate and summarize a metadata overlay JSON file",
    )
    metadata_review_parser.add_argument("--root", type=Path, default=None)
    metadata_review_parser.add_argument("--overlay", type=Path, default=None)
    metadata_review_parser.add_argument("--json", action="store_true", dest="as_json")
    metadata_review_parser.set_defaults(func=cmd_metadata_review)

    traces_parser = subparsers.add_parser("traces", help="Inspect recorded route traces")
    traces_subparsers = traces_parser.add_subparsers(dest="traces_command", required=True)
    traces_list_parser = traces_subparsers.add_parser("list", help="List recent route traces")
    traces_list_parser.add_argument("--limit", type=int, default=20)
    traces_list_parser.add_argument("--json", action="store_true", dest="as_json")
    traces_list_parser.set_defaults(func=cmd_traces_list)
    traces_show_parser = traces_subparsers.add_parser("show", help="Show one route trace")
    traces_show_parser.add_argument("trace_id", type=int)
    traces_show_parser.add_argument("--json", action="store_true", dest="as_json")
    traces_show_parser.set_defaults(func=cmd_traces_show)

    backend_parser = subparsers.add_parser("backend", help="Work with external retrieval backends")
    backend_subparsers = backend_parser.add_subparsers(dest="backend_command", required=True)
    backend_status_parser = backend_subparsers.add_parser("status", help="Show selected retrieval backend status")
    add_backend_argument(backend_status_parser)
    backend_status_parser.add_argument("--json", action="store_true", dest="as_json")
    backend_status_parser.set_defaults(func=cmd_backend_status)
    astra_parser = backend_subparsers.add_parser("astra", help="Use Astra DB Data API as a retrieval backend")
    astra_subparsers = astra_parser.add_subparsers(dest="astra_command", required=True)
    astra_create_parser = astra_subparsers.add_parser(
        "create-collection",
        help="Create the configured Astra collection",
    )
    astra_create_parser.add_argument(
        "--options-json",
        default=None,
        help="Optional JSON object passed as createCollection.options.",
    )
    astra_create_parser.add_argument("--json", action="store_true", dest="as_json")
    astra_create_parser.set_defaults(func=cmd_backend_astra_create_collection)
    astra_upsert_parser = astra_subparsers.add_parser(
        "upsert",
        help="Upsert indexed catalog skills into the configured Astra collection",
    )
    astra_upsert_parser.add_argument(
        "--include-refs",
        action="store_true",
        help="Include per-skill backend refs in JSON output.",
    )
    astra_upsert_parser.add_argument("--json", action="store_true", dest="as_json")
    astra_upsert_parser.set_defaults(func=cmd_backend_astra_upsert)
    astra_search_parser = astra_subparsers.add_parser(
        "search",
        help="Search the configured Astra collection with vectorize.",
    )
    astra_search_parser.add_argument("query")
    astra_search_parser.add_argument("--limit", type=int, default=10)
    astra_search_parser.add_argument("--json", action="store_true", dest="as_json")
    astra_search_parser.set_defaults(func=cmd_backend_astra_search)

    bridge_parser = subparsers.add_parser("bridge", help="JSON stdin/stdout bridge for MCP wrappers")
    bridge_parser.add_argument("operation", choices=["route", "search", "inspect"])
    bridge_parser.set_defaults(func=cmd_bridge, bridge=True)

    return parser


def add_backend_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        choices=BACKEND_CHOICES,
        default=None,
        help="Retrieval backend for route/search. Defaults to SKILLROUTE_BACKEND or local.",
    )


def catalog_from_args(args: argparse.Namespace) -> Catalog:
    return Catalog(args.catalog or default_catalog_path())


def backend_from_args(args: argparse.Namespace) -> RetrievalBackend:
    try:
        return backend_from_name(getattr(args, "backend", None))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def backend_from_name(name: str | None) -> RetrievalBackend:
    configured = (name or os.environ.get("SKILLROUTE_BACKEND") or "local").strip().lower()
    if configured in {"local", "local-token"}:
        return LocalTokenBackend()
    if configured in {"astra", "astra-data-api"}:
        return AstraDataAPIBackend.from_env()
    valid = ", ".join(BACKEND_CHOICES)
    raise ValueError(f"Unsupported SkillRoute backend {configured!r}; expected one of: {valid}")


def cmd_index(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    skills = catalog.index_root(args.root)
    print(f"Indexed {len(skills)} skills into {catalog.path}")


def cmd_route(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    response = Router(catalog, backend=backend_from_args(args)).route(args.request, repo=args.repo, limit=args.limit)
    if args.as_json:
        print_json(response)
        return
    print_route(response)


def cmd_search(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    rows = Router(catalog, backend=backend_from_args(args)).search(args.query, limit=args.limit)
    if args.as_json:
        print_json(rows)
        return
    if not rows:
        print("No matching skills.")
        return
    for row in rows:
        print(f"{row['name']} ({row['skill_id']}) score={row['score']}")
        print(f"  {row['description']}")
        for snippet in row["evidence"]:
            print(f"  evidence: {snippet}")


def cmd_inspect(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    skill = catalog.get_skill(args.skill_id)
    if skill is None:
        raise SystemExit(f"Skill not found: {args.skill_id}")
    payload = to_jsonable(skill)
    payload["backend_refs"] = catalog.backend_refs(skill.id)
    if args.as_json:
        print_json(payload)
        return
    print(f"{skill.name} ({skill.id})")
    print(skill.description)
    print(f"path: {skill.skill_path}")
    if skill.tags:
        print(f"tags: {', '.join(skill.tags)}")
    if skill.facets:
        print(f"facets: {json.dumps(skill.facets, sort_keys=True)}")
    if skill.relationships:
        print("relationships:")
        for relationship in skill.relationships:
            print(f"  {relationship.type}: {relationship.target}")
    if skill.excerpts:
        print("excerpts:")
        for excerpt in skill.excerpts:
            print(f"  [{excerpt.kind}] {excerpt.text}")


def cmd_eval_run(args: argparse.Namespace) -> None:
    context = TemporaryDirectory() if args.fresh else nullcontext(None)
    with context as temp_dir:
        catalog = Catalog(Path(temp_dir) / "catalog.db") if temp_dir else catalog_from_args(args)
        for root in args.index_root:
            catalog.index_root(root)
        results = run_golden_routes(Router(catalog, backend=backend_from_args(args)), args.cases)
    if args.as_json:
        print_json(results)
        return
    passed = sum(1 for result in results if result.passed)
    print(f"{passed}/{len(results)} golden route cases passed")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.name}")
        for note in result.notes:
            print(f"  {note}")
    if passed != len(results):
        raise SystemExit(1)


def cmd_dogfood_roots(args: argparse.Namespace) -> None:
    roots = discover_default_skill_roots(args.home)
    payload = [
        {"path": str(root.path), "skill_count": root.skill_count}
        for root in roots
    ]
    if args.as_json:
        print_json(payload)
        return
    if not roots:
        print("No default skill roots found.")
        return
    for root in roots:
        print(f"{root.path} ({root.skill_count} skills)")


def cmd_dogfood_index(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    result = index_default_skill_roots(catalog, home=args.home)
    payload = {
        "catalog": str(catalog.path),
        "indexed_count": result.indexed_count,
        "roots": [
            {"path": str(root.path), "skill_count": root.skill_count}
            for root in result.roots
        ],
    }
    if args.as_json:
        print_json(payload)
        return
    if not result.roots:
        print("No default skill roots found.")
        return
    print(f"Indexed {result.indexed_count} skills into {catalog.path}")
    for root in result.roots:
        print(f"- {root.path} ({root.skill_count} skills)")


def cmd_metadata_suggest(args: argparse.Namespace) -> None:
    try:
        result = write_metadata_overlay(args.root, output=args.output, force=args.force)
    except FileExistsError as exc:
        raise SystemExit(str(exc)) from exc
    payload = {"output_path": str(result.output_path), "skill_count": result.skill_count}
    if args.as_json:
        print_json(payload)
        return
    print(f"Wrote metadata suggestions for {result.skill_count} skills to {result.output_path}")


def cmd_metadata_review(args: argparse.Namespace) -> None:
    if args.overlay is None and args.root is None:
        raise SystemExit("Provide --overlay or --root.")
    overlay_path = args.overlay or default_overlay_path(args.root)
    result = review_metadata_overlay(overlay_path)
    payload = to_jsonable(result)
    payload["overlay_path"] = str(result.overlay_path)
    if args.as_json:
        print_json(payload)
        return
    print(f"Overlay: {result.overlay_path}")
    print(f"Skills: {result.skill_count}")
    print(f"Relationships: {result.relationship_count}")
    if result.status_counts:
        print(f"Review status: {json.dumps(result.status_counts, sort_keys=True)}")
    if result.issues:
        print("Issues:")
        for issue in result.issues:
            print(f"- {issue}")
        raise SystemExit(1)
    print("No validation issues.")


def cmd_traces_list(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    traces = catalog.list_route_traces(limit=args.limit)
    if args.as_json:
        print_json(traces)
        return
    if not traces:
        print("No route traces recorded.")
        return
    for trace in traces:
        top = trace["top_candidate"]
        top_text = f"{top['name']} confidence={top['confidence']}" if top else "no candidates"
        request_text = trace["request"].get("request", "")
        print(f"{trace['id']} {trace['created_at']} backend={trace.get('backend') or 'unknown'}")
        print(f"  request: {request_text}")
        print(f"  top: {top_text}")
        print(f"  clarification_needed: {trace['clarification_needed']}")


def cmd_traces_show(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    trace = catalog.get_route_trace(args.trace_id)
    if trace is None:
        raise SystemExit(f"Route trace not found: {args.trace_id}")
    if args.as_json:
        print_json(trace)
        return
    print_trace(trace)


def cmd_backend_status(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    backend = backend_from_args(args)
    payload = backend_status_payload(catalog, backend)
    if args.as_json:
        print_json(payload)
        return
    print_backend_status(payload)


def cmd_backend_astra_create_collection(args: argparse.Namespace) -> None:
    backend = AstraDataAPIBackend.from_env()
    options = json.loads(args.options_json) if args.options_json else None
    result = run_astra_command(lambda: backend.create_collection(options))
    if args.as_json:
        print_json(result)
        return
    print("Astra collection create command completed.")


def cmd_backend_astra_upsert(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    backend = AstraDataAPIBackend.from_env()
    skills = catalog.list_skills()
    refs = run_astra_command(lambda: backend.upsert_skills(skills))
    for ref in refs:
        catalog.save_backend_ref(ref["skill_id"], ref["backend"], ref["ref"], ref.get("status", "indexed"))
    statuses = count_ref_statuses(refs)
    payload = {
        "backend": backend.name,
        "collection": backend.collection,
        "keyspace": backend.keyspace,
        "skill_count": len(skills),
        "ref_count": len(refs),
        "status_counts": statuses,
    }
    if args.include_refs:
        payload["refs"] = refs
    if args.as_json:
        print_json(payload)
        return
    print(f"Astra upsert processed {len(refs)} skills: {json.dumps(statuses, sort_keys=True)}")


def cmd_backend_astra_search(args: argparse.Namespace) -> None:
    catalog = catalog_from_args(args)
    backend = AstraDataAPIBackend.from_env()
    rows = run_astra_command(lambda: backend.search(args.query, catalog.list_skills(), limit=args.limit))
    if args.as_json:
        print_json(rows)
        return
    if not rows:
        print("No Astra results.")
        return
    for row in rows:
        skill = catalog.get_skill(row["skill_id"])
        name = skill.name if skill else row["skill_id"]
        print(f"{name} ({row['skill_id']}) score={row['score']}")


def run_astra_command(operation):
    try:
        return operation()
    except AstraDataAPIError as exc:
        raise SystemExit(str(exc)) from exc


def count_ref_statuses(refs: list[dict[str, Any]]) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for ref in refs:
        status = ref.get("status", "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    return statuses


def backend_status_payload(catalog: Catalog, backend: RetrievalBackend) -> dict[str, Any]:
    skills = catalog.list_skills()
    status = backend.status(skills)
    ref_summary = catalog.backend_ref_summary(backend.name)
    return {
        "backend": backend.name,
        "configured": bool(status.get("configured")),
        "status": status.get("status", "unknown"),
        "search_available": bool(status.get("search_available")),
        "write_available": bool(status.get("write_available")),
        "catalog": str(catalog.path),
        "skill_count": len(skills),
        "ref_count": ref_summary["ref_count"],
        "ref_status_counts": ref_summary["status_counts"],
        "details": {
            key: value
            for key, value in status.items()
            if key not in {"configured", "status", "search_available", "write_available"}
        },
    }


def print_backend_status(payload: dict[str, Any]) -> None:
    print(f"{payload['backend']} status={payload['status']}")
    print(f"configured: {payload['configured']}")
    print(f"search_available: {payload['search_available']}")
    print(f"write_available: {payload['write_available']}")
    print(f"catalog: {payload['catalog']}")
    print(f"skills: {payload['skill_count']}")
    print(f"backend refs: {payload['ref_count']} {json.dumps(payload['ref_status_counts'], sort_keys=True)}")
    if payload["details"]:
        print(f"details: {json.dumps(payload['details'], sort_keys=True)}")


def print_trace(trace: dict[str, Any]) -> None:
    request = trace["request"]
    response = trace["response"]
    print(f"Trace {trace['id']} {trace['created_at']}")
    print(f"backend: {request.get('backend', 'unknown')}")
    print(f"request: {request.get('request', '')}")
    print(f"clarification_needed: {response.get('clarification_needed')}")
    for index, candidate in enumerate(response.get("candidates", []), start=1):
        score_breakdown = candidate.get("score_breakdown", {})
        print(f"{index}. {candidate.get('name')} confidence={candidate.get('confidence')}")
        print(f"   skill_id: {candidate.get('skill_id')}")
        print(f"   scores: {json.dumps(score_breakdown, sort_keys=True)}")


def cmd_bridge(args: argparse.Namespace) -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    catalog = Catalog(payload.get("catalog") or args.catalog or default_catalog_path())
    router = Router(catalog, backend=backend_from_name(payload.get("backend")))
    if args.operation == "route":
        result = router.route(
            payload["request"],
            repo=payload.get("repo"),
            limit=int(payload.get("limit", 5)),
        )
    elif args.operation == "search":
        result = router.search(payload["query"], limit=int(payload.get("limit", 10)))
    else:
        skill = catalog.get_skill(payload["skill_id"])
        if skill is None:
            raise ValueError(f"Skill not found: {payload['skill_id']}")
        result = to_jsonable(skill)
        result["backend_refs"] = catalog.backend_refs(skill.id)
    print_json(result)


def print_route(response: Any) -> None:
    if response.clarification_needed:
        print("Clarification recommended:")
        for question in response.clarification_questions:
            print(f"- {question}")
    if not response.candidates:
        print("No matching skills.")
        return
    print("Ranked skills:")
    for candidate in response.candidates:
        print(f"{candidate.suggested_position}. {candidate.name} ({candidate.skill_id}) confidence={candidate.confidence}")
        print(f"   {candidate.description}")
        for reason in candidate.reasons[:3]:
            print(f"   reason: {reason}")
        for excerpt in candidate.evidence[:2]:
            print(f"   evidence[{excerpt.kind}]: {excerpt.text}")


def print_json(value: Any) -> None:
    print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
