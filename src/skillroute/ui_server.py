from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import skillroute
from skillroute.atlas import (
    build_atlas_payload,
    catalog_summary,
    route_preview_payload,
    skill_detail_payload,
)
from skillroute.backends import backend_from_name
from skillroute.catalog import Catalog, default_catalog_path
from skillroute.context import REPO_ROOT_ENV, allowed_repo_root, resolve_repo_within
from skillroute.routing import Router

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only in misconfigured installs.
    raise SystemExit(
        "The SkillRoute UI requires FastAPI and Uvicorn. "
        "Run `uv sync --extra dev` or reinstall SkillRoute."
    ) from exc


class RoutePreviewRequest(BaseModel):
    request: str = Field(min_length=1)
    repo: str | None = None
    backend: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


def resolve_preview_repo(repo: str | None) -> Path | None:
    """Validate a caller-supplied repo path arriving over HTTP.

    The bundled UI never sends one. Honoring an arbitrary path here turns
    route-preview into a filesystem probe: the response echoes the resolved
    absolute path, which marker files exist, the languages present, and a file
    count, so an unauthenticated local caller could walk the disk with it. A
    repo is therefore only accepted when SKILLROUTE_REPO_ROOT names a base
    directory to confine it to. The CLI is unaffected -- a user naming their
    own checkout on their own machine is not this boundary.
    """
    if not repo:
        return None
    root = allowed_repo_root()
    if root is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"repo is not accepted over the HTTP API. Set {REPO_ROOT_ENV} to a base "
                "directory to allow repo paths confined to it."
            ),
        )
    try:
        return resolve_repo_within(repo, root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_app(catalog_path: Path | str | None = None, web_dist: Path | None = None) -> FastAPI:
    catalog = Catalog(catalog_path or default_catalog_path())
    dist = web_dist or default_web_dist()
    app = FastAPI(title="SkillRoute UI", version=skillroute.__version__)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "catalog": str(catalog.path),
            "webDist": str(dist),
            "webDistExists": dist.exists(),
        }

    @app.get("/api/catalog/summary")
    def summary() -> dict[str, Any]:
        return catalog_summary(catalog)

    @app.get("/api/atlas")
    def atlas() -> dict[str, Any]:
        return build_atlas_payload(catalog)

    @app.get("/api/skills/{skill_id}")
    def skill(skill_id: str) -> dict[str, Any]:
        payload = skill_detail_payload(catalog, skill_id)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
        return payload

    @app.get("/api/traces")
    def traces(limit: int = 20) -> list[dict[str, Any]]:
        return catalog.list_route_traces(limit=max(1, min(limit, 100)))

    @app.post("/api/route-preview")
    def route_preview(request: RoutePreviewRequest) -> dict[str, Any]:
        try:
            backend = backend_from_name(request.backend)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repo = resolve_preview_repo(request.repo)
        router = Router(catalog, backend=backend)
        return route_preview_payload(
            catalog,
            request=request.request,
            repo=repo,
            limit=request.limit,
            router=router,
        )

    if dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            return FileResponse(dist / "index.html")

    return app


def run_ui(
    *,
    catalog_path: Path | str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    dist = default_web_dist()
    if not (dist / "index.html").exists():
        raise SystemExit(
            "SkillRoute UI assets not found. In a source checkout run "
            "`npm --prefix web ci && npm --prefix web run build`, or set "
            "SKILLROUTE_WEB_DIST to a built UI directory."
        )
    app = create_app(catalog_path=catalog_path, web_dist=dist)
    if open_browser:
        _open_browser_when_ready(host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


def _open_browser_when_ready(host: str, port: int, timeout: float = 10.0) -> None:
    """Open the browser only after the server accepts connections.

    uvicorn.run blocks, so opening the browser beforehand races the server
    startup and can land on a connection-refused page.
    """
    connect_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    url = f"http://{connect_host}:{port}"

    def wait_and_open() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((connect_host, port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        webbrowser.open(url)

    threading.Thread(target=wait_and_open, daemon=True).start()


def default_web_dist() -> Path:
    override = os.environ.get("SKILLROUTE_WEB_DIST")
    if override:
        return Path(override).expanduser().resolve()
    packaged = _packaged_web_dist()
    if packaged is not None:
        return packaged
    return _repo_web_dist()


def _packaged_web_dist() -> Path | None:
    """Web assets bundled into the wheel by the hatch build hook (see hatch_build.py)."""
    candidate = Path(__file__).resolve().parent / "_web"
    if (candidate / "index.html").exists():
        return candidate
    return None


def _repo_web_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "web" / "dist"
