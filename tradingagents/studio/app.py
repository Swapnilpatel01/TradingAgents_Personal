"""Authenticated personal server with a serialized, persistent research queue."""

import hmac
import logging
import mimetypes
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import services
from .models import Analyst, Backtest, Portfolio, Run, Scan, Setup
from .store import Store

logger = logging.getLogger(__name__)
KINDS = {"analysts": Analyst, "setups": Setup, "portfolios": Portfolio}


def create_app(data_dir=None, token=None):
    root = Path(data_dir or os.environ.get("STUDIO_DATA_DIR", "./studio-data")).resolve()
    secret = token or os.environ.get("STUDIO_TOKEN")
    if not secret or len(secret) < 24:
        raise ValueError("STUDIO_TOKEN must contain at least 24 characters")
    store = Store(root / "studio.sqlite3")
    executor = ThreadPoolExecutor(max_workers=1)
    queue_lock = threading.Lock()
    for job in store.list("jobs"):
        if job["status"] in ("queued", "running"):
            store.put("jobs", {**job, "status": "interrupted", "error": "Server restarted; submit again."}, job["id"])

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="TradingAgents Studio", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.store = store
    hosts = {"localhost", "127.0.0.1", "testserver"}
    hosts.update(h.strip().lower() for h in os.environ.get("STUDIO_ALLOWED_HOSTS", "").split(",") if h.strip())

    @app.middleware("http")
    async def protect(request: Request, call_next):
        host = urlsplit("//" + request.headers.get("host", "")).hostname
        if host not in hosts:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + secret).encode()):
                return JSONResponse({"detail": "Enter the Studio access key shown in your terminal"}, status_code=401)
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin requests are disabled"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        return response

    def get(kind, key):
        try:
            return store.get(kind, key)
        except KeyError:
            raise HTTPException(404, "Record not found") from None

    def submit(kind, payload, work):
        with queue_lock:
            if sum(j["status"] in ("queued", "running") for j in store.list("jobs")) >= 5:
                raise HTTPException(429, "Queue full; wait for research to finish")
            job = store.put("jobs", {"kind": kind, "status": "queued", "request": payload})

            def execute():
                store.put("jobs", {**job, "status": "running"}, job["id"])
                try:
                    result = work(root / "runs" / job["id"])
                    store.put("jobs", {**job, "status": "completed", "result": result}, job["id"])
                except Exception:
                    logger.exception("Studio job %s failed", job["id"])
                    store.put("jobs", {**job, "status": "failed",
                                      "error": "Research failed. Check terminal logs, data availability and ChatGPT sign-in."}, job["id"])
            executor.submit(execute)
        return job

    def setup_for(key):
        setup = get("setups", key)
        return setup, [get("analysts", a) for a in setup["custom_analysts"]]

    @app.get("/api/status")
    def status():
        from tradingagents.llm_clients.chatgpt_auth import signed_in_as
        return {"signed_in": bool(signed_in_as()), "provider": "chatgpt", "live_trades": False,
                "login_command": "tradingagents login chatgpt"}

    @app.get("/api/models")
    def models():
        from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuthError, list_models
        try:
            return {"models": list_models()}
        except ChatGPTAuthError as exc:
            raise HTTPException(401, str(exc)) from None

    @app.get("/api/records/{kind}")
    def records(kind: str):
        if kind not in KINDS:
            raise HTTPException(404)
        return store.list(kind)

    @app.put("/api/records/{kind}/{key}")
    def save(kind: str, key: str, body: dict):
        from pydantic import ValidationError
        if kind not in KINDS:
            raise HTTPException(404)
        try:
            value = KINDS[kind].model_validate(body).model_dump(mode="json")
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        if kind == "setups":
            for analyst_id in value["custom_analysts"]:
                get("analysts", analyst_id)
        return store.put(kind, value, None if key == "new" else key)

    @app.delete("/api/records/{kind}/{key}")
    def delete(kind: str, key: str):
        if kind not in KINDS:
            raise HTTPException(404)
        if kind == "analysts" and any(key in s["custom_analysts"] for s in store.list("setups")):
            raise HTTPException(409, "Remove this analyst from saved setups first")
        store.delete(kind, key)
        return {"deleted": key}

    @app.get("/api/history/{ticker}")
    def history(ticker: str, period: str = "6mo"):
        from datetime import date

        from pydantic import ValidationError
        try:
            Run(ticker=ticker, as_of=date.today(), setup_id="chart")
        except ValidationError:
            raise HTTPException(422, "Invalid symbol") from None
        if period not in ("1mo", "3mo", "6mo", "1y", "5y"):
            raise HTTPException(422, "Unsupported range")
        try:
            return services.history(ticker, period)
        except Exception:
            raise HTTPException(502, "Price provider unavailable or symbol has no data") from None

    @app.post("/api/scan", status_code=202)
    def scan(request: Scan):
        return submit("scan", request.model_dump(mode="json"), lambda root: services.scan(request))

    @app.post("/api/analyze", status_code=202)
    def analyze(request: Run):
        setup, custom = setup_for(request.setup_id)
        portfolio = get("portfolios", request.portfolio_id) if request.portfolio_id else None
        if portfolio and portfolio["as_of"] != str(request.as_of):
            raise HTTPException(422, "Portfolio snapshot date must match the analysis date")
        return submit("analysis", request.model_dump(mode="json"),
                      lambda root: services.analyze(request, setup, custom, portfolio, root))

    @app.post("/api/backtest", status_code=202)
    def backtest(request: Backtest):
        setup, custom = setup_for(request.setup_id)
        if custom:
            raise HTTPException(422, "Use a setup without custom reviewers for upstream backtests")
        return submit("backtest", request.model_dump(mode="json"), lambda root: services.backtest(request, setup, root))

    @app.post("/api/portfolios/{key}/value", status_code=202)
    def portfolio_value(key: str):
        portfolio = get("portfolios", key)
        return submit("portfolio", {"portfolio_id": key}, lambda root: services.value_portfolio(portfolio))

    @app.get("/api/jobs")
    def jobs():
        return [{k: v for k, v in j.items() if k != "result"} for j in store.list("jobs")[:100]]

    @app.get("/api/jobs/{key}")
    def job(key: str):
        return get("jobs", key)

    static = Path(__file__).parent / "static"
    if static.exists():
        # Windows registry associations can otherwise label JavaScript text/plain.
        mimetypes.add_type("text/javascript", ".js")
        mimetypes.add_type("application/manifest+json", ".webmanifest")
        app.mount("/", StaticFiles(directory=static, html=True), name="studio")
    return app


def main():
    import uvicorn
    token = os.environ.get("STUDIO_TOKEN") or secrets.token_urlsafe(32)
    print(f"Studio: http://127.0.0.1:8765\nAccess key: {token}\nSign in separately: tradingagents login chatgpt")
    uvicorn.run(create_app(token=token), host=os.environ.get("STUDIO_HOST", "127.0.0.1"), port=8765)


if __name__ == "__main__":
    main()
