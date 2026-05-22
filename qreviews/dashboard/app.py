"""FastAPI app: read-only metrics dashboard for qreviews.

Serves a single-page React/Mantine SPA built by Vite (under
``qreviews/dashboard/web/``) and a small JSON API consumed by the page.
Reads the same SQLite file the poller writes to (WAL mode lets us coexist).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from qreviews.config import Config, load_config
from qreviews.metrics import compute_summary, daily_throughput, row_to_detail, score_histograms
from qreviews.state import Store
from qreviews.webhook import build_router as build_webhook_router

log = logging.getLogger(__name__)

WEB_DIST = Path(__file__).parent / "web_dist"

_MISSING_BUNDLE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>qreviews — dashboard bundle missing</title>
<style>body{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#0B1220;color:#E8ECF4;padding:48px;line-height:1.6}
code{background:#121A2B;padding:2px 6px;border-radius:2px;color:#FF6A3D}
h1{color:#FF6A3D;font-family:Georgia,serif;font-weight:800;letter-spacing:-0.02em}</style></head>
<body><h1>dashboard bundle missing</h1>
<p>The React bundle under <code>qreviews/dashboard/web_dist/</code> was not found.</p>
<p>Build it with:</p>
<pre><code>npm --prefix qreviews/dashboard/web install
npm --prefix qreviews/dashboard/web run build</code></pre>
<p>Then restart <code>python -m qreviews dashboard</code>.</p>
<p>API routes are still served — try <code>/api/groups</code>.</p>
</body></html>"""


def create_app(*, config_path: str = "config.yaml") -> FastAPI:
    config: Config = load_config(config_path)
    store = Store(config.storage.db_path)
    store.init_schema()

    app = FastAPI(title="qreviews dashboard", docs_url=None, redoc_url=None)

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

    # Phabricator Herald webhook (POST /phabricator/herald) — same FastAPI app.
    app.include_router(build_webhook_router(config, store))

    # ------------------------------------------------------------ spa
    # Mount the built React bundle last so /api/* and /phabricator/* still
    # win. ``html=True`` makes StaticFiles serve index.html for ``/`` and
    # for any path that doesn't match a real file.
    if WEB_DIST.is_dir() and (WEB_DIST / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
    else:
        log.warning("web_dist/ not found at %s — serving fallback page at /", WEB_DIST)

        @app.get("/", response_class=HTMLResponse)
        def _missing_bundle() -> HTMLResponse:
            return HTMLResponse(_MISSING_BUNDLE_HTML, status_code=503)

    return app
