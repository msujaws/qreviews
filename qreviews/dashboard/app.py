"""FastAPI app: read-only metrics dashboard for qreviews.

Serves a single-page Jinja template + a small JSON API consumed by the page.
Reads the same SQLite file the poller writes to (WAL mode lets us coexist).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from qreviews.config import Config, load_config
from qreviews.metrics import compute_summary, daily_throughput, row_to_detail, score_histograms
from qreviews.state import Store
from qreviews.webhook import build_router as build_webhook_router

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(*, config_path: str = "config.yaml") -> FastAPI:
    config: Config = load_config(config_path)
    store = Store(config.storage.db_path)
    store.init_schema()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    app = FastAPI(title="qreviews dashboard", docs_url=None, redoc_url=None)

    enabled_group_slugs = [g.slug for g in config.reviewer_groups]

    # ------------------------------------------------------------ page

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "groups": enabled_group_slugs,
                "default_thresholds": {
                    "risk": config.defaults.risk_threshold,
                    "complexity": config.defaults.complexity_threshold,
                },
            },
        )

    # ------------------------------------------------------------ api

    @app.get("/api/summary")
    def api_summary(group: str | None = None, since: int | None = None) -> JSONResponse:
        rows = list(store.iter_for_metrics(group_slug=group))
        summary = compute_summary(rows, group_slug=group, since=since)
        return JSONResponse(summary.to_dict())

    @app.get("/api/histograms")
    def api_histograms(group: str | None = None) -> JSONResponse:
        rows = list(store.iter_for_metrics(group_slug=group))
        return JSONResponse(score_histograms(rows))

    @app.get("/api/timeseries")
    def api_timeseries(group: str | None = None, days: int = 30) -> JSONResponse:
        rows = list(store.iter_for_metrics(group_slug=group))
        return JSONResponse(daily_throughput(rows, days=days))

    @app.get("/api/revisions")
    def api_revisions(
        group: str | None = None, limit: int = 50, offset: int = 0
    ) -> JSONResponse:
        rows = store.list_recent(group_slug=group, limit=limit, offset=offset)
        return JSONResponse([row_to_detail(r) for r in rows])

    @app.get("/api/revision/{revision_id}")
    def api_revision(revision_id: int) -> JSONResponse:
        row = store.get_by_revision_id(revision_id)
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return JSONResponse(row_to_detail(row))

    # Phabricator Herald webhook (POST /phabricator/herald) — same FastAPI app.
    app.include_router(build_webhook_router(config, store))

    @app.get("/api/groups")
    def api_groups() -> JSONResponse:
        return JSONResponse(
            [
                {
                    "slug": g.slug,
                    "enabled": g.enabled,
                    "risk_threshold": g.effective_risk_threshold(config.defaults),
                    "complexity_threshold": g.effective_complexity_threshold(config.defaults),
                    "has_skill": bool(g.skill_path),
                }
                for g in config.reviewer_groups
            ]
        )

    return app
