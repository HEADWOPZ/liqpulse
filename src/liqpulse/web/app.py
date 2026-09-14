from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from liqpulse import __version__
from liqpulse.brief import desk_payload, last_stored_brief
from liqpulse.cards import generate_and_store
from liqpulse.db import init_db
from liqpulse.ingest.runner import run_ingest
from liqpulse.ledger import status

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="LiqPulse desk", version=__version__)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def desk(request: Request) -> HTMLResponse:
        payload = desk_payload()
        return templates.TemplateResponse(
            "desk.html",
            {
                "request": request,
                "version": __version__,
                "cards": payload["cards"],
                "snapshots": payload["snapshots"],
                "ledger": payload["ledger"],
                "disclaimer": payload["disclaimer"],
            },
        )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__, "paper_only": True}

    @app.get("/api/cards")
    def api_cards() -> JSONResponse:
        return JSONResponse(desk_payload()["cards"])

    @app.get("/api/snapshots")
    def api_snaps() -> JSONResponse:
        return JSONResponse(desk_payload()["snapshots"])

    @app.get("/api/ledger")
    def api_ledger() -> JSONResponse:
        return JSONResponse(status().model_dump(mode="json"))

    @app.get("/api/brief")
    def api_brief() -> dict:
        return {"text": last_stored_brief()}

    @app.post("/api/ingest")
    def api_ingest() -> dict:
        snaps, report = run_ingest()
        cards = generate_and_store(snaps) if snaps else []
        return {
            "report": report.model_dump(),
            "cards": len(cards),
            "snapshots": len(snaps),
        }

    return app
