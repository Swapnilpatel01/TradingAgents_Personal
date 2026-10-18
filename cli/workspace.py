"""Arrow-key workspace for the original Windows launcher and live CLI display."""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.panel import Panel

from cli import studio
from cli.display import console
from cli.models import AnalystType
from cli.prompts import _MENU_STYLE, ensure_signed_in, select_chatgpt_model
from tradingagents.studio import services
from tradingagents.studio.models import Analyst, Backtest, Portfolio, Run, Scan, Setup

app = typer.Typer(help="Original-style arrow-key workspace, including all Studio tools.")
ACTIONS = [
    ("Run analysis — original setup and live agent display", "original"),
    ("Run a saved setup — live agent display + custom reviewers", "research"),
    ("Stock dashboard", "quote"),
    ("Stock scanner", "scan"),
    ("Historical backtesting", "backtest"),
    ("Create / edit custom AI analysts", "analysts"),
    ("Create / edit trading setups", "setups"),
    ("Create / edit portfolio snapshots", "portfolios"),
    ("Value portfolio holdings", "value"),
    ("Research history and saved results", "history"),
    ("Exit", "exit"),
]


def ask(prompt):
    answer = prompt.ask()
    if answer is None:
        raise typer.Abort()
    return answer


def text(label, default=""):
    return ask(questionary.text(label, default=str(default), style=_MENU_STYLE))


def choose(label, options):
    return ask(questionary.select(label, choices=[questionary.Choice(title, value=value) for title, value in options], style=_MENU_STYLE))


def profile(ctx, kind, optional=False, editing=False):
    rows = studio.store(ctx).list(kind)
    options = []
    if editing:
        options.append(("Create new", None))
    elif optional:
        options.append(("No portfolio context", None))
    if not rows and not options:
        raise ValueError(f"No saved {kind}. Create one from the workspace menu first.")
    options += [(f"{row['name']} ({row['id'][:8]})", row) for row in rows]
    return choose(f"Select {kind}:", options)


def live_runner(request, setup, portfolio, config):
    """Use the existing streaming monitor, rather than running a second graph."""
    from cli.run import run_analysis

    return run_analysis(portfolio=portfolio, flags={"save": True, "show": False, "html": False},
                        prepared={"config": config, "selections": {
                            "ticker": request.ticker.upper(), "analysis_date": str(request.as_of),
                            "asset_type": "stock", "analysts": [AnalystType(a) for a in setup["analysts"]],
                        }})


def edit_analyst(ctx):
    old = profile(ctx, "analysts", editing=True) or {}
    value = Analyst(name=text("Analyst name:", old.get("name", "")),
                    instructions=text("Review instructions:", old.get("instructions", "")))
    studio.store(ctx).put("analysts", value.model_dump(), old.get("id"))
    typer.echo("Analyst saved. Select it in a trading setup to include its review.")


def edit_setup(ctx):
    old = profile(ctx, "setups", editing=True) or {}
    name = text("Setup name:", old.get("name", ""))
    analysts = ask(questionary.checkbox("Core analysts (Space to toggle, Enter to confirm):", choices=[
        questionary.Choice(label, value=key, checked=key in old.get("analysts", ["market", "news"]))
        for label, key in [("Technical", "market"), ("News", "news"), ("Fundamentals", "fundamentals"), ("Sentiment", "social")]], style=_MENU_STYLE))
    rows = studio.store(ctx).list("analysts")
    custom = ask(questionary.checkbox("Custom reviewers:", choices=[
        questionary.Choice(row["name"], value=row["id"], checked=row["id"] in old.get("custom_analysts", []))
        for row in rows], style=_MENU_STYLE)) if rows else []
    quick, deep = old.get("quick_model", "gpt-6-luna"), old.get("deep_model", "gpt-6-sol")
    if choose("ChatGPT models:", [(f"Keep {quick} / {deep}", "keep"), ("Choose from my ChatGPT plan", "choose")]) == "choose":
        ensure_signed_in("chatgpt")
        quick, deep = select_chatgpt_model("quick", quick), select_chatgpt_model("deep", deep)
    rounds = choose("Debate rounds:", [("1 — quick", 1), ("2 — balanced", 2), ("3 — thorough", 3)])
    value = Setup(name=name, analysts=analysts, custom_analysts=custom, quick_model=quick,
                  deep_model=deep, debate_rounds=rounds, notes=text("Notes:", old.get("notes", "")))
    studio.store(ctx).put("setups", value.model_dump(), old.get("id"))
    typer.echo("Setup saved.")


def edit_portfolio(ctx):
    old = profile(ctx, "portfolios", editing=True) or {}
    name = text("Portfolio name:", old.get("name", "My portfolio"))
    as_of = text("Snapshot date (YYYY-MM-DD):", old.get("as_of", date.today()))
    currency = text("Currency:", old.get("currency", "USD")).upper()
    cash = float(text("Cash:", old.get("cash", 0)))
    positions = old.get("positions", [])
    if positions and choose("Existing holdings:", [("Keep existing holdings", "keep"), ("Replace holdings", "replace")]) == "replace":
        positions = []
    while ask(questionary.confirm("Add a holding?", default=not positions, style=_MENU_STYLE)):
        positions.append({"ticker": text("Symbol:").upper(), "quantity": float(text("Quantity:")),
                          "average_price": float(text("Average entry price:")), "currency": currency})
    value = Portfolio(name=name, as_of=as_of, currency=currency, cash=cash, positions=positions)
    studio.store(ctx).put("portfolios", value.model_dump(mode="json"), old.get("id"))
    typer.echo("Portfolio snapshot saved.")


def perform(ctx, action):
    if action == "analysts":
        return edit_analyst(ctx)
    if action == "setups":
        return edit_setup(ctx)
    if action == "portfolios":
        return edit_portfolio(ctx)
    if action == "quote":
        ticker = text("Stock symbol:", "AAPL")
        period = choose("History range:", [("1 month", "1mo"), ("3 months", "3mo"), ("6 months", "6mo"), ("1 year", "1y"), ("5 years", "5y")])
        return studio.quote(ticker=ticker, period=period, as_json=False)
    if action == "scan":
        request = Scan(tickers=studio.parts(text("Symbols separated by commas:", "AAPL,MSFT,NVDA")),
                       min_price=float(text("Minimum price:", 0)), min_volume=float(text("Minimum daily volume:", 0)),
                       min_change=float(text("Minimum daily change (%):", -100)))
        return studio.execute(ctx, "scan", request.model_dump(mode="json"), lambda root: services.scan(request), False)
    if action == "value":
        book = profile(ctx, "portfolios")
        return studio.execute(ctx, "portfolio", {"portfolio_id": book["id"]}, lambda root: services.value_portfolio(book), False)
    if action == "history":
        jobs = studio.store(ctx).list("jobs")
        if not jobs:
            typer.echo("No research runs yet.")
            return
        job = choose("Select a research run:", [(f"{j['kind']} | {j['status']} | {j['updated_at']} | {j['id'][:8]}", j) for j in jobs])
        return studio.show(job)
    if action in ("research", "backtest"):
        setup = profile(ctx, "setups")
        if action == "backtest":
            if setup["custom_analysts"]:
                raise ValueError("Choose a core-only setup without custom reviewers for backtests.")
            request = Backtest(tickers=studio.parts(text("Symbols separated by commas:", "AAPL")),
                               start=text("Start date (YYYY-MM-DD):"), end=text("End date:", date.today()),
                               every_n_days=int(text("Calendar days between runs:", 7)), setup_id=setup["id"])
            ensure_signed_in("chatgpt")
            return studio.execute(ctx, "backtest", request.model_dump(mode="json"), lambda root: services.backtest(request, setup, root), False)
        book = profile(ctx, "portfolios", optional=True)
        request = Run(ticker=text("Stock symbol:", "AAPL"), as_of=text("Analysis date:", date.today()),
                      setup_id=setup["id"], portfolio_id=book["id"] if book else None)
        if book and book["as_of"] != str(request.as_of):
            raise ValueError("Portfolio snapshot date must match the analysis date.")
        custom = [studio.store(ctx).get("analysts", key) for key in setup["custom_analysts"]]
        ensure_signed_in("chatgpt")
        return studio.execute(ctx, "analysis", request.model_dump(mode="json"),
                              lambda root: services.analyze(request, setup, custom, book, root, runner=live_runner), False)
    raise ValueError("Unknown workspace action")


@app.callback(invoke_without_command=True)
@studio.handled
def main(ctx: typer.Context, data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
         action: Annotated[str | None, typer.Option("--action", hidden=True)] = None):
    ctx.obj = (data_dir or Path(os.environ.get("STUDIO_DATA_DIR") or "./studio-data")).resolve()
    if action:
        return perform(ctx, action)
    while True:
        console.print(Panel("TradingAgents — Personal Workspace\n"
                            "Original live analysis + saved setups, analysts, scanning and portfolios\n"
                            "Use arrow keys and Enter. Research only; no live trades.", border_style="cyan"))
        selected = choose("What would you like to do?", ACTIONS)
        if selected == "exit":
            return
        # A fresh process per action preserves the original live display's
        # per-run logging wrappers and separates global engine configuration.
        args = [] if selected == "original" else ["workspace", "--data-dir", str(ctx.obj), "--action", selected]
        result = subprocess.run([sys.executable, "-m", "cli.main", *args], check=False)
        if result.returncode:
            typer.echo("The action ended without completing. Review the message above, then try again.")
        text("Press Enter to return to the workspace menu")
