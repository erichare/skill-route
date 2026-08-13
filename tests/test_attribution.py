from __future__ import annotations

from pathlib import Path

from skillroute.attribution import Attribution, resolve_attribution
from skillroute.catalog import Catalog
from skillroute.cli import main
from skillroute.routing import Router


def test_explicit_wins_over_everything() -> None:
    attribution = resolve_attribution(
        explicit="pi",
        client_name="claude-code",
        environ={"SKILLROUTE_HARNESS": "codex"},
        surface="mcp",
    )
    assert attribution.harness_id == "pi"
    assert attribution.surface == "mcp"


def test_client_name_is_mapped_through_the_lookup() -> None:
    attribution = resolve_attribution(
        client_name="claude-code",
        client_name_lookup={"claude-code": "claude-code"}.get,
        environ={"SKILLROUTE_HARNESS": "codex"},
        surface="mcp",
    )
    assert attribution.harness_id == "claude-code"


def test_unmapped_client_name_falls_through_to_env() -> None:
    attribution = resolve_attribution(
        client_name="some-unknown-editor",
        client_name_lookup={}.get,
        environ={"SKILLROUTE_HARNESS": "codex"},
        surface="mcp",
    )
    assert attribution.harness_id == "codex"


def test_env_stamp_is_the_fallback() -> None:
    attribution = resolve_attribution(
        environ={"SKILLROUTE_HARNESS": "hermes", "SKILLROUTE_HARNESS_VERSION": "2.1.0"},
        surface="acp",
    )
    assert attribution.harness_id == "hermes"
    assert attribution.harness_version == "2.1.0"
    assert attribution.surface == "acp"


def test_unknown_caller_is_normal_not_an_error() -> None:
    attribution = resolve_attribution(environ={})
    assert attribution.harness_id is None
    assert attribution.surface == "cli"


def test_blank_values_are_treated_as_absent() -> None:
    attribution = resolve_attribution(explicit="   ", environ={"SKILLROUTE_HARNESS": ""})
    assert attribution.harness_id is None


def test_unrecognized_surface_falls_back_to_cli() -> None:
    assert resolve_attribution(surface="telepathy", environ={}).surface == "cli"


def test_route_records_attribution_on_the_trace(
    indexed_catalog: Catalog, tmp_path: Path
) -> None:
    router = Router(indexed_catalog)
    router.route(
        "Build an MCP server with stdio transport",
        limit=3,
        attribution=Attribution(harness_id="pi", harness_version="0.9.2", surface="mcp"),
    )

    with indexed_catalog._session() as connection:
        row = connection.execute(
            "SELECT harness_id, harness_version, surface, weights_json FROM route_traces"
        ).fetchone()
    assert row["harness_id"] == "pi"
    assert row["harness_version"] == "0.9.2"
    assert row["surface"] == "mcp"
    # Weights are recorded so an eval trend can attribute movement to a config.
    assert '"lexical"' in row["weights_json"]


def test_route_without_attribution_records_unknown_harness(
    indexed_catalog: Catalog,
) -> None:
    Router(indexed_catalog).route("Build an MCP server", limit=2)

    with indexed_catalog._session() as connection:
        row = connection.execute(
            "SELECT harness_id, surface FROM route_traces"
        ).fetchone()
    assert row["harness_id"] is None
    assert row["surface"] == "cli"


def test_cli_route_honors_the_harness_env_stamp(
    indexed_catalog: Catalog, monkeypatch, capsys
) -> None:
    """Regression: SKILLROUTE_HARNESS was set by generated configs but ignored.

    The env stamp is the fallback attribution path for ACP and direct CLI use,
    where there is no MCP handshake to read a client name from.
    """
    monkeypatch.setenv("SKILLROUTE_HARNESS", "pi")
    main(["--catalog", str(indexed_catalog.path), "route", "Build an MCP server"])
    capsys.readouterr()

    with indexed_catalog._session() as connection:
        row = connection.execute("SELECT harness_id FROM route_traces").fetchone()
    assert row["harness_id"] == "pi"


def test_cli_harness_flag_overrides_the_env_stamp(
    indexed_catalog: Catalog, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("SKILLROUTE_HARNESS", "pi")
    main(
        [
            "--catalog",
            str(indexed_catalog.path),
            "route",
            "Build an MCP server",
            "--harness",
            "hermes",
        ]
    )
    capsys.readouterr()

    with indexed_catalog._session() as connection:
        row = connection.execute("SELECT harness_id FROM route_traces").fetchone()
    assert row["harness_id"] == "hermes"
