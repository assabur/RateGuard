from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import Settings
from .storage import Repository

Mode = Literal["live", "demo"]


def current_view(report, settings, today=None):
    """Recompute current freshness when reading; a historical OK never means OK today."""
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    report = deepcopy(report)
    age = (today - date.fromisoformat(report["as_of"])).days
    fresh = 0 <= age <= settings.max_age_days
    for item in report.get("reconciliation", []):
        item["usable_today"] = item["usable_as_of"] and fresh
    return {
        **report,
        "freshness": {
            "checked_on": str(today),
            "calendar_age_days": age,
            "max_age_days": settings.max_age_days,
            "is_current": fresh,
        },
        "usable_today": report["usable_as_of"] and fresh,
    }


def create_app(settings=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.repository = Repository(settings)
        try:
            yield
        finally:
            app.state.repository.close()

    app = FastAPI(
        title="RateGuard",
        version="0.1.0",
        lifespan=lifespan,
        description="US par yield curve monitoring and same-date FRED reconciliation. "
        "Yields in percent, spreads in basis points. Demo data requires mode=demo.",
    )
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(static_dir / "index.html")

    def latest(as_of, mode):
        result = app.state.repository.latest(as_of, mode)
        if result is None:
            raise HTTPException(404, "No run for the requested date and mode. Run ingestion first.")
        return current_view(result, settings)

    @app.get("/health")
    def health():
        with app.state.repository.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/runs")
    def history(mode: Mode = "live", limit: Annotated[int, Query(ge=1, le=365)] = 30):
        return app.state.repository.history(mode, limit)

    @app.get("/runs/{run_id}")
    def run(run_id: str):
        result = app.state.repository.by_id(run_id)
        if result is None:
            raise HTTPException(404, "Run not found")
        return current_view(result, settings)

    @app.get("/report")
    def report(as_of: date | None = None, mode: Mode = "live"):
        return latest(as_of, mode)

    @app.get("/reconciliation")
    def reconciliation(as_of: date | None = None, mode: Mode = "live"):
        result = latest(as_of, mode)
        return {
            key: result[key]
            for key in (
                "run_id",
                "as_of",
                "mode",
                "status",
                "usable_as_of",
                "usable_today",
                "freshness",
                "reconciliation",
            )
        }

    @app.get("/curves")
    def curves(as_of: date | None = None, mode: Mode = "live"):
        result = latest(as_of, mode)
        return {
            key: result[key]
            for key in (
                "run_id",
                "as_of",
                "mode",
                "status",
                "usable_as_of",
                "usable_today",
                "curves",
            )
        }

    @app.get("/quality")
    def quality(as_of: date | None = None, mode: Mode = "live"):
        result = latest(as_of, mode)
        return {
            key: result[key]
            for key in (
                "run_id",
                "as_of",
                "mode",
                "status",
                "ingestion_errors",
                "points",
                "quality",
            )
        }

    return app
