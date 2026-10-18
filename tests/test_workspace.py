from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli import run, workspace
from cli.main import app
from cli.models import AnalystType
from tradingagents.studio import services
from tradingagents.studio.models import Run, Setup
from tradingagents.studio.store import Store


def test_launcher_menu_dispatch_and_return(monkeypatch, tmp_path):
    choices = iter(["quote", "original", "exit"])
    monkeypatch.setattr(workspace, "choose", lambda *args: next(choices))
    monkeypatch.setattr(workspace, "text", lambda *args: "")
    calls = []
    def launch(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(workspace.subprocess, "run", launch)
    result = CliRunner().invoke(app, ["workspace", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert calls[0][-2:] == ["--action", "quote"]
    assert calls[1][-2:] == ["-m", "cli.main"]


def test_profile_empty_and_optional(tmp_path, monkeypatch):
    ctx = SimpleNamespace(obj=tmp_path)
    with pytest.raises(ValueError, match="No saved setups"):
        workspace.profile(ctx, "setups")
    monkeypatch.setattr(workspace, "choose", lambda label, options: options[0][1])
    assert workspace.profile(ctx, "portfolios", optional=True) is None


def test_edit_existing_analyst_keeps_id(tmp_path, monkeypatch):
    ctx = SimpleNamespace(obj=tmp_path)
    db = Store(tmp_path / "studio.sqlite3")
    row = db.put("analysts", {"name": "Skeptic", "instructions": "Find missing evidence."})
    monkeypatch.setattr(workspace, "profile", lambda *args, **kwargs: row)
    answers = iter(["Reviewer", "Challenge all assumptions."])
    monkeypatch.setattr(workspace, "text", lambda *args: next(answers))
    workspace.edit_analyst(ctx)
    assert len(db.list("analysts")) == 1
    assert db.get("analysts", row["id"])["name"] == "Reviewer"


def test_saved_research_routes_through_live_runner(tmp_path, monkeypatch):
    ctx = SimpleNamespace(obj=tmp_path)
    setup = {**Setup(name="Core").model_dump(), "id": "core"}
    monkeypatch.setattr(workspace, "profile", lambda ctx, kind, **kwargs: setup if kind == "setups" else None)
    answers = iter(["AAPL", "2020-01-01"])
    monkeypatch.setattr(workspace, "text", lambda *args: next(answers))
    monkeypatch.setattr(workspace, "ensure_signed_in", lambda *args: None)
    seen = []
    def analyze(*args, **kwargs):
        seen.append(kwargs["runner"])
        return {"ticker": "AAPL", "as_of": "2020-01-01", "rating": "Hold", "reports": {}, "custom_reviews": []}
    monkeypatch.setattr(services, "analyze", analyze)
    workspace.perform(ctx, "research")
    assert seen == [workspace.live_runner]
    assert Store(tmp_path / "studio.sqlite3").list("jobs")[0]["status"] == "completed"


def test_live_runner_streams_original_display_without_second_graph(tmp_path, monkeypatch):
    recorded = []
    class Graph:
        def __init__(self, analysts, config, **kwargs):
            recorded.append((analysts, config))
            self.propagator = SimpleNamespace(get_graph_args=lambda **kwargs: {})
        def create_run_state(self, *args):
            return {}
        def begin_checkpoint(self, *args):
            return None
        def checkpoint_input(self, value):
            return value
        def stream_run(self, *args, **kwargs):
            yield [], {"market_report": "Dated evidence", "final_trade_decision": "Hold"}
        def record_decision(self, *args):
            recorded.append("recorded")
        def clear_checkpoint_on_success(self, *args):
            pass
        def end_checkpoint(self):
            pass
    monkeypatch.setattr(run, "TradingAgentsGraph", Graph)
    monkeypatch.setattr(run, "Live", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(run, "update_display", lambda *args, **kwargs: None)
    monkeypatch.setattr(run, "_offer_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(run, "run_rating", lambda state: "Hold")
    monkeypatch.setattr(run, "get_user_selections", lambda *args: pytest.fail("Saved setup prompted again"))
    # Restore the original logging hooks after exercising the upstream live path.
    for name in ("add_message", "add_tool_call", "update_report_section"):
        monkeypatch.setattr(run.message_buffer, name, getattr(run.message_buffer, name))
    config = {"results_dir": str(tmp_path)}
    request = Run(ticker="aapl", as_of="2020-01-01", setup_id="core")
    state, rating = workspace.live_runner(request, {"analysts": ["market"]}, None, config)
    assert state["market_report"] == "Dated evidence"
    assert rating == "Hold"
    assert recorded[0] == ([AnalystType.MARKET.value], config)
    assert recorded[1] == "recorded"


def test_services_use_injected_runner(tmp_path, monkeypatch):
    from tradingagents.graph import trading_graph

    monkeypatch.setattr(trading_graph, "TradingAgentsGraph", lambda *args, **kwargs: pytest.fail("Created a second graph"))
    seen = []
    def runner(request, setup, portfolio, config):
        seen.append(config)
        return {"market_report": "Evidence"}, "Hold"
    result = services.analyze(Run(ticker="AAPL", as_of="2020-01-01", setup_id="core"),
                              Setup(name="Core").model_dump(), [], None, tmp_path, runner=runner)
    assert seen[0]["llm_provider"] == "chatgpt"
    assert result["reports"] == {"market_report": "Evidence"}
