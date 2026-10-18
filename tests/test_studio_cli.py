import json

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.studio import services
from tradingagents.studio.store import Store

runner = CliRunner()


@pytest.fixture
def invoke(tmp_path):
    def run(*args, **kwargs):
        return runner.invoke(app, ["studio", "--data-dir", str(tmp_path), *args], **kwargs)
    return run


def test_menu_and_original_help(invoke):
    result = invoke(input="0\n")
    assert result.exit_code == 0, result.output
    assert "Stock dashboard" in result.output
    assert runner.invoke(app, ["--help"]).exit_code == 0


def test_create_export_import_and_duplicate_names(invoke, tmp_path):
    assert invoke("analyst-add", "--name", "Skeptic", "--instructions", "Find gaps in evidence.").exit_code == 0
    assert invoke("setup-add", "--name", "Review", "--custom", "Skeptic").exit_code == 0
    exported = invoke("export", "setups", "Review")
    value = json.loads(exported.stdout)
    assert len(value["custom_analysts"]) == 1
    file = tmp_path / "setup.json"
    file.write_text(json.dumps(value), encoding="utf-8")
    assert invoke("import", "setups", str(file)).exit_code == 0
    assert invoke("export", "setups", "Review").exit_code == 1
    assert len(json.loads(invoke("records", "setups", "--json").stdout)) == 2


def test_scan_result_and_shared_history(invoke, tmp_path, monkeypatch):
    monkeypatch.setattr(services, "scan", lambda request: {"matches": [{"ticker": request.tickers[0]}], "errors": []})
    result = invoke("scan", "--tickers", "AAPL,MSFT", "--json")
    assert result.exit_code == 0, result.output
    job = json.loads(result.stdout)
    assert job["result"]["matches"][0]["ticker"] == "AAPL"
    assert Store(tmp_path / "studio.sqlite3").get("jobs", job["id"])["status"] == "completed"
    assert json.loads(invoke("jobs", "--job-id", job["id"], "--json").stdout) == job


def test_analysis_uses_profile_and_rejects_wrong_snapshot(invoke, monkeypatch):
    invoke("setup-add", "--name", "Core")
    invoke("portfolio-add", "--name", "Book", "--date", "2020-01-01", "--holding", "AAPL:2:100")
    bad = invoke("analyze", "--ticker", "AAPL", "--setup", "Core", "--date", "2020-01-02", "--portfolio", "Book")
    assert bad.exit_code == 1
    seen = []
    def analyze(request, setup, custom, portfolio, root):
        seen.append((request, setup, portfolio))
        return {"ticker": "AAPL", "as_of": str(request.as_of), "rating": "Hold", "reports": {}, "custom_reviews": []}
    monkeypatch.setattr(services, "analyze", analyze)
    result = invoke("analyze", "--ticker", "AAPL", "--setup", "Core", "--date", "2020-01-01", "--portfolio", "Book", "--json")
    assert result.exit_code == 0, result.output
    assert seen[0][1]["name"] == "Core"
    assert seen[0][2]["positions"][0]["quantity"] == 2


def test_failed_and_interrupted_jobs(invoke, monkeypatch, tmp_path):
    def fail(request):
        raise RuntimeError("Provider unavailable")
    monkeypatch.setattr(services, "scan", fail)
    assert invoke("scan", "--tickers", "AAPL").exit_code == 1
    assert Store(tmp_path / "studio.sqlite3").list("jobs")[0]["status"] == "failed"
    def interrupt(request):
        raise KeyboardInterrupt()
    monkeypatch.setattr(services, "scan", interrupt)
    assert invoke("scan", "--tickers", "AAPL").exit_code == 130
    assert Store(tmp_path / "studio.sqlite3").list("jobs")[0]["status"] == "interrupted"


def test_backtest_validation_and_execution(invoke, monkeypatch):
    invoke("setup-add", "--name", "Core")
    monkeypatch.setattr(services, "backtest", lambda *args: {"explanation": "Evaluation complete", "failures": [], "settlement_failures": []})
    result = invoke("backtest", "--tickers", "AAPL", "--setup", "Core", "--start", "2020-01-01", "--end", "2020-01-02")
    assert result.exit_code == 0, result.output
    assert "Evaluation complete" in result.output
    result = invoke("backtest", "--tickers", "AAPL", "--setup", "Core", "--start", "2020-01-01", "--end", "2099-01-01")
    assert result.exit_code == 1


def test_portfolio_value(invoke, monkeypatch):
    invoke("portfolio-add", "--name", "Book", "--holding", "AAPL:2:100")
    monkeypatch.setattr(services, "value_portfolio", lambda value: {"quantity": value["positions"][0]["quantity"]})
    result = invoke("portfolio-value", "--portfolio", "Book", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["result"]["quantity"] == 2


def test_quote_and_bad_input(invoke, monkeypatch):
    monkeypatch.setattr(services, "history", lambda *args: {"ticker": "AAPL", "bars": []})
    assert json.loads(invoke("quote", "--ticker", "AAPL", "--json").stdout)["ticker"] == "AAPL"
    assert invoke("quote", "--ticker", "../../secret").exit_code == 1
    assert invoke("records", "secrets").exit_code == 1


def test_interactive_dispatch(invoke, monkeypatch):
    from types import SimpleNamespace

    import cli.studio
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cli.studio.subprocess, "run", run)
    assert invoke(input="3\n").exit_code == 0
    assert calls[0][-1] == "scan"
