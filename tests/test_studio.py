import socket
import time
from datetime import date

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from pydantic import ValidationError

from tradingagents.studio import services
from tradingagents.studio.app import create_app
from tradingagents.studio.models import Backtest, Portfolio, Scan
from tradingagents.studio.store import Store

TOKEN = "test-studio-access-token-12345678"
_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def windows_event_loop_socketpair(monkeypatch, _no_network):
    # Windows implements asyncio's self-pipe with a loopback socket pair.
    # Permit only that local connection, keeping external network prohibited.
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return _CONNECT(sock, address)
        raise OSError("External network disabled in Studio tests")
    monkeypatch.setattr(socket.socket, "connect", local_only)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, TOKEN)) as c:
        c.headers["Authorization"] = "Bearer " + TOKEN
        yield c


def test_auth_and_origin(client):
    assert client.get("/api/jobs", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/jobs", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.get("/api/jobs", headers={"Host": "evil.test"}).status_code == 403
    response = client.get("/api/jobs")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_short_secret_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_app(tmp_path, "short")


def test_profiles_and_references(client):
    analyst = client.put("/api/records/analysts/new", json={"name": "Skeptic", "instructions": "Find missing evidence."}).json()
    setup = client.put("/api/records/setups/new", json={"name": "Review", "custom_analysts": [analyst["id"]]}).json()
    assert setup["custom_analysts"] == [analyst["id"]]
    assert client.delete(f"/api/records/analysts/{analyst['id']}").status_code == 409
    assert client.put("/api/records/setups/new", json={"name": "Bad", "custom_analysts": ["missing"]}).status_code == 404
    assert client.put("/api/records/setups/new", json={"name": "Bad", "llm_provider": "openai"}).status_code == 422
    client.delete(f"/api/records/setups/{setup['id']}")
    assert client.delete(f"/api/records/analysts/{analyst['id']}").status_code == 200


@pytest.mark.parametrize("change", [{"start": "2026-02-01", "end": "2026-01-01"},
                                   {"end": "2099-01-01"}, {"every_n_days": 0},
                                   {"tickers": ["../../secret"]}, {"every_n_days": 1}])
def test_grid_restrictions(change):
    values = {"tickers": ["AAPL"], "start": "2020-01-01", "end": "2020-12-31", "every_n_days": 30, "setup_id": "s"}
    with pytest.raises(ValidationError):
        Backtest(**(values | change))


def test_portfolio_restrictions():
    with pytest.raises(ValidationError):
        Portfolio(as_of=date.today(), cash=float("nan"))
    with pytest.raises(ValidationError):
        Portfolio(as_of=date.today(), positions=[{"ticker": "AAPL", "quantity": -1, "average_price": 2}])


def wait_job(client, job):
    for _ in range(100):
        result = client.get("/api/jobs/" + job["id"]).json()
        if result["status"] in ("completed", "failed"):
            return result
        time.sleep(.01)
    pytest.fail("Job did not finish")


def test_analysis_snapshot_and_job(client, monkeypatch):
    setup = client.put("/api/records/setups/new", json={"name": "Core"}).json()
    portfolio = client.put("/api/records/portfolios/new", json={"as_of": "2020-01-01"}).json()
    request = {"ticker": "AAPL", "as_of": "2020-01-02", "setup_id": setup["id"], "portfolio_id": portfolio["id"]}
    assert client.post("/api/analyze", json=request).status_code == 422
    captured = []
    def analyze(*args):
        captured.append(args)
        return {"rating": "Hold"}
    monkeypatch.setattr(services, "analyze", analyze)
    request["as_of"] = "2020-01-01"
    response = client.post("/api/analyze", json=request)
    assert response.status_code == 202
    job = wait_job(client, response.json())
    assert job["result"]["rating"] == "Hold"
    assert captured[0][3]["as_of"] == request["as_of"]


def test_failed_job(client, monkeypatch):
    def broken(*args):
        raise RuntimeError("secret vendor response")
    monkeypatch.setattr(services, "scan", broken)
    job = wait_job(client, client.post("/api/scan", json={"tickers": ["AAPL"]}).json())
    assert job["status"] == "failed"
    assert "secret" not in job["error"]


def test_restart_marks_interrupted(tmp_path):
    store = Store(tmp_path / "studio.sqlite3")
    job = store.put("jobs", {"status": "running"})
    with TestClient(create_app(tmp_path, TOKEN)):
        assert store.get("jobs", job["id"])["status"] == "interrupted"


def test_subscription_config_ignores_paid_provider_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_PROVIDER", "anthropic")
    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "https://other.test")
    config = services.studio_config({"quick_model": "q", "deep_model": "d", "debate_rounds": 1}, tmp_path)
    assert all(config[key] == "chatgpt" for key in ("llm_provider", "quick_think_provider", "deep_think_provider"))
    assert config["backend_url"] is None


def quote(ticker, period):
    if ticker == "FAIL":
        raise ValueError("No data")
    return {"currency": "USD", "bars": [{"close": 100, "volume": 10, "date": "2020-01-01"},
                                         {"close": 110, "volume": 50, "date": "2020-01-02"}]}


def test_scanner_partial_failure(monkeypatch):
    monkeypatch.setattr(services, "history", quote)
    result = services.scan(Scan(tickers=["AAPL", "FAIL"], min_change=5, min_volume=20))
    assert result["matches"][0]["ticker"] == "AAPL"
    assert result["matches"][0]["change"] == pytest.approx(10)
    assert result["errors"][0]["ticker"] == "FAIL"


def test_portfolio_pnl_and_missing_currency(monkeypatch):
    monkeypatch.setattr(services, "history", quote)
    portfolio = {"cash": 50, "currency": "USD", "positions": [{"ticker": "AAPL", "quantity": 2, "average_price": 100, "currency": "USD"}]}
    result = services.value_portfolio(portfolio)
    assert result["equity"] == 270
    assert result["unrealized_pnl"] == 20
    portfolio["currency"] = "INR"
    result = services.value_portfolio(portfolio)
    assert result["equity"] is None
    assert result["complete"] is False


def test_custom_reviewers_excluded_from_backtest(client):
    analyst = client.put("/api/records/analysts/new", json={"name": "Test", "instructions": "Review research."}).json()
    setup = client.put("/api/records/setups/new", json={"name": "Custom", "custom_analysts": [analyst["id"]]}).json()
    response = client.post("/api/backtest", json={"tickers": ["AAPL"], "start": "2020-01-01", "end": "2020-01-01", "setup_id": setup["id"]})
    assert response.status_code == 422
