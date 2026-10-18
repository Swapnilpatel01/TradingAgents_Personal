"""Deterministic browser-test server. Never import this in the real launcher."""

from datetime import UTC, datetime
from tempfile import TemporaryDirectory

import uvicorn

from tradingagents.llm_clients import chatgpt_auth
from tradingagents.studio import services
from tradingagents.studio.app import create_app


def history(ticker, period="6mo"):
    return {"ticker": ticker, "currency": "USD", "source": "TEST FIXTURE — not market data",
            "fetched_at": datetime.now(UTC).isoformat(),
            "bars": [{"date": f"2020-01-{i:02}", "open": 100+i, "high": 104+i,
                      "low": 99+i, "close": 102+i, "volume": 10000*i} for i in range(1, 29)]}


if __name__ == "__main__":
    chatgpt_auth.signed_in_as = lambda: "fixture@example.test"
    chatgpt_auth.list_models = lambda: [("Test model", "test-model")]
    services.history = history
    services.analyze = lambda request, setup, custom, portfolio, root: {
        "ticker": request.ticker, "as_of": str(request.as_of), "rating": "Hold",
        "reports": {"market_report": "Fixture research. No inference was performed."},
        "custom_reviews": [{"name": a["name"], "report": a["instructions"]} for a in custom]}
    services.backtest = lambda request, setup, root: {
        "cells_run": 1, "failures": [], "settlement_failures": [], "summary": {},
        "explanation": "Fixture evaluation: one resolved cell."}
    with TemporaryDirectory() as root:
        uvicorn.run(create_app(root, "studio-browser-test-key-12345678"), host="127.0.0.1", port=8766)
