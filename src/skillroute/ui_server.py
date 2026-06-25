from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from skillroute.atlas import build_atlas_payload, catalog_summary, route_preview_payload, skill_detail_payload
from skillroute.backends import AstraDataAPIBackend, LocalTokenBackend, RetrievalBackend
from skillroute.catalog import Catalog, default_catalog_path
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


def create_app(catalog_path: Path | str | None = None, web_dist: Path | None = None) -> FastAPI:
    catalog = Catalog(catalog_path or default_catalog_path())
    dist = web_dist or default_web_dist()
    app = FastAPI(title="SkillRoute UI", version="0.1.0")

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
        router = Router(catalog, backend=backend)
        return route_preview_payload(
            catalog,
            request=request.request,
            repo=request.repo,
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
            "SkillRoute UI build not found. Run `npm --prefix web install && npm --prefix web run build`."
        )
    app = create_app(catalog_path=catalog_path, web_dist=dist)
    url = f"http://{host}:{port}"
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="info")


def default_web_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def backend_from_name(name: str | None) -> RetrievalBackend:
    configured = (name or "local").strip().lower()
    if configured in {"local", "local-token"}:
        return LocalTokenBackend()
    if configured in {"astra", "astra-data-api"}:
        return AstraDataAPIBackend.from_env()
    raise ValueError(f"Unsupported SkillRoute backend {configured!r}")
