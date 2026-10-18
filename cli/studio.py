"""Terminal access to Studio without FastAPI, a browser or a running server."""

import json
import os
import subprocess
import sys
from datetime import date
from functools import wraps
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from tradingagents.studio import services
from tradingagents.studio.models import Analyst, Backtest, Portfolio, Run, Scan, Setup
from tradingagents.studio.store import Store

app = typer.Typer(help="Personal Studio research tools. Uses your ChatGPT subscription; no live trades.")
console = Console()
KINDS = {"analysts": Analyst, "setups": Setup, "portfolios": Portfolio}


def handled(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, KeyError, OSError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from None
    return wrapped


def parts(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def store(ctx):
    return Store(ctx.obj / "studio.sqlite3")


def resolve(ctx, kind, name):
    records = store(ctx).list(kind)
    exact = [r for r in records if r["id"] == name]
    matches = exact or [r for r in records if r.get("name", "").casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Choose a unique {kind} name or ID; use 'records {kind}' to list them")
    return matches[0]


def show(value, as_json=False):
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=True, indent=2))
    elif isinstance(value, list):
        if not value:
            typer.echo("No records yet.")
            return
        keys = [k for k in value[0] if all(not isinstance(r.get(k), (dict, list)) for r in value)]
        table = Table(*keys)
        for row in value:
            table.add_row(*(f"{row[k]:,.2f}" if isinstance(row.get(k), float) and not row[k].is_integer()
                            else f"{row[k]:,.0f}" if isinstance(row.get(k), float)
                            else str(row.get(k, "")) for k in keys))
        console.print(table)
    else:
        console.print_json(json.dumps(value, ensure_ascii=True))


def execute(ctx, kind, request, work, as_json):
    db = store(ctx)
    job = db.put("jobs", {"kind": kind, "status": "running", "request": request})
    typer.echo(f"Running {kind}. Saved job: {job['id']}", err=True)
    try:
        result = work(ctx.obj / "runs" / job["id"])
        job = db.put("jobs", {**job, "status": "completed", "result": result}, job["id"])
    except KeyboardInterrupt:
        db.put("jobs", {**job, "status": "interrupted", "error": "Interrupted from terminal."}, job["id"])
        raise typer.Exit(130) from None
    except Exception as exc:
        db.put("jobs", {**job, "status": "failed", "error": "Research failed; see terminal output."}, job["id"])
        typer.echo(f"Research failed: {exc}", err=True)
        raise typer.Exit(1) from None
    if as_json:
        show(job, True)
    elif kind == "analysis":
        typer.echo(f"\n{result['ticker']} | {result['as_of']} | {result['rating']}")
        for title, report in result["reports"].items():
            typer.echo(f"\n{title.replace('_', ' ').upper()}\n{report}")
        for analyst in result["custom_reviews"]:
            typer.echo(f"\nCUSTOM REVIEW: {analyst['name']}\n{analyst['report']}")
    elif kind == "scan":
        show(result["matches"])
        if result["errors"]:
            typer.echo("Data errors:")
            show(result["errors"])
    elif kind == "backtest":
        typer.echo(result["explanation"])
        if result["failures"] or result["settlement_failures"]:
            show(result)
    else:
        show(result)


@app.callback(invoke_without_command=True)
@handled
def main(ctx: typer.Context, data_dir: Annotated[Path | None, typer.Option("--data-dir", help="Shared Studio data folder; defaults to STUDIO_DATA_DIR or ./studio-data.")] = None):
    ctx.obj = (data_dir or Path(os.environ.get("STUDIO_DATA_DIR") or "./studio-data")).resolve()
    if ctx.invoked_subcommand:
        return
    choices = {"1": ["quote"], "2": ["analyze"], "3": ["scan"], "4": ["backtest"],
               "5": ["analyst-add"], "6": ["setup-add"], "7": ["portfolio-add"],
               "8": ["portfolio-value"], "9": ["jobs"], "10": ["records", "setups"]}
    typer.echo("\nTradingAgents Studio — terminal workspace\n"
               "1 Stock dashboard   2 AI research      3 Stock scanner\n"
               "4 Backtest          5 Create analyst   6 Create setup\n"
               "7 Add portfolio     8 Value portfolio  9 Research history\n"
               "10 List setups      0 Exit\n"
               "AI research uses your existing ChatGPT sign-in. No live trades.\n")
    choice = typer.prompt("Choose an action", default="0")
    if choice == "0":
        return
    if choice not in choices:
        raise ValueError("Choose a number from 0 to 10")
    if choice == "7":
        choices[choice] += ["--cash", str(typer.prompt("Cash", default=0.0)),
                            "--currency", typer.prompt("Currency", default="USD")]
        while True:
            holding = typer.prompt("Holding SYMBOL:QUANTITY:AVERAGE_PRICE (blank to finish)", default="", show_default=False)
            if not holding:
                break
            choices[choice] += ["--holding", holding]
    result = subprocess.run([sys.executable, "-m", "cli.main", "studio", "--data-dir",
                             str(ctx.obj), *choices[choice]], check=False)
    raise typer.Exit(result.returncode)


@app.command()
@handled
def quote(ticker: str = typer.Option(..., prompt="Stock symbol"), period: str = "6mo", as_json: bool = typer.Option(False, "--json")):
    """Display adjusted daily OHLCV and range performance."""
    Run(ticker=ticker, as_of=date.today(), setup_id="quote")
    if period not in ("1mo", "3mo", "6mo", "1y", "5y"):
        raise ValueError("Range must be 1mo, 3mo, 6mo, 1y or 5y")
    result = services.history(ticker.upper(), period)
    if as_json:
        show(result, True)
    else:
        bars = result["bars"]
        change = (bars[-1]["close"] / bars[0]["close"] - 1) * 100
        typer.echo(f"{result['ticker']} | {result['currency']} | last close {bars[-1]['close']:.2f} | range {change:+.2f}%")
        show(bars[-10:])
        typer.echo(result["source"] + " | fetched " + result["fetched_at"])


@app.command()
@handled
def analyst_add(ctx: typer.Context, name: str = typer.Option(..., prompt=True), instructions: str = typer.Option(..., prompt=True)):
    """Save a supplemental AI reviewer."""
    show(store(ctx).put("analysts", Analyst(name=name, instructions=instructions).model_dump()))


@app.command()
@handled
def setup_add(ctx: typer.Context, name: str = typer.Option(..., prompt=True), analysts: str = "market,news",
              custom: str = "", quick_model: str = "gpt-6-luna", deep_model: str = "gpt-6-sol",
              debate_rounds: int = 1):
    """Save a research template; --custom accepts reviewer names or IDs."""
    ids = [resolve(ctx, "analysts", value)["id"] for value in parts(custom)]
    value = Setup(name=name, analysts=parts(analysts), custom_analysts=ids,
                  quick_model=quick_model, deep_model=deep_model, debate_rounds=debate_rounds)
    show(store(ctx).put("setups", value.model_dump()))


@app.command()
@handled
def records(ctx: typer.Context, kind: str, as_json: bool = typer.Option(False, "--json")):
    """List analysts, setups or portfolios (names and IDs)."""
    if kind not in KINDS:
        raise ValueError("Choose analysts, setups or portfolios")
    show(store(ctx).list(kind), as_json)


@app.command("import")
@handled
def import_record(ctx: typer.Context, kind: str, file: Path, record_id: str | None = None):
    """Create or replace a profile from JSON. Use --record-id to update one."""
    if kind not in KINDS:
        raise ValueError("Choose analysts, setups or portfolios")
    value = KINDS[kind].model_validate(json.loads(file.read_text(encoding="utf-8-sig")))
    if record_id:
        store(ctx).get(kind, record_id)
    if kind == "setups":
        for analyst_id in value.custom_analysts:
            store(ctx).get("analysts", analyst_id)
    show(store(ctx).put(kind, value.model_dump(mode="json"), record_id))


@app.command("export")
@handled
def export_record(ctx: typer.Context, kind: str, name: str):
    """Print editable profile JSON to stdout (redirect it to a file)."""
    if kind not in KINDS:
        raise ValueError("Choose analysts, setups or portfolios")
    value = resolve(ctx, kind, name)
    show({k: v for k, v in value.items() if k not in ("id", "updated_at")}, True)


@app.command()
@handled
def portfolio_add(ctx: typer.Context, name: str = typer.Option(..., prompt=True), as_of: str = typer.Option(None, "--date"),
                  currency: str = "USD", cash: float = 0,
                  holding: Annotated[list[str] | None, typer.Option("--holding", help="Repeat SYMBOL:QUANTITY:AVERAGE_PRICE; omit for cash-only.")] = None):
    """Save a dated long-only portfolio snapshot."""
    positions = []
    for item in holding or []:
        values = item.split(":")
        if len(values) != 3:
            raise ValueError("Each holding must be SYMBOL:QUANTITY:AVERAGE_PRICE")
        positions.append({"ticker": values[0].upper(), "quantity": float(values[1]),
                          "average_price": float(values[2]), "currency": currency})
    value = Portfolio(name=name, as_of=as_of or str(date.today()), currency=currency, cash=cash, positions=positions)
    show(store(ctx).put("portfolios", value.model_dump(mode="json")))


@app.command()
@handled
def portfolio_value(ctx: typer.Context, portfolio: str = typer.Option(..., prompt="Portfolio name or ID"), as_json: bool = typer.Option(False, "--json")):
    """Value saved holdings at latest available prices; no FX conversion."""
    value = resolve(ctx, "portfolios", portfolio)
    execute(ctx, "portfolio", {"portfolio_id": value["id"]}, lambda root: services.value_portfolio(value), as_json)


@app.command()
@handled
def analyze(ctx: typer.Context, ticker: str = typer.Option(..., prompt="Stock symbol"), setup: str = typer.Option(..., prompt="Setup name or ID"),
            as_of: str = typer.Option(None, "--date"), portfolio: str | None = None, as_json: bool = typer.Option(False, "--json")):
    """Run the upstream research team plus saved custom reviewers."""
    template = resolve(ctx, "setups", setup)
    custom = [store(ctx).get("analysts", key) for key in template["custom_analysts"]]
    book = resolve(ctx, "portfolios", portfolio) if portfolio else None
    request = Run(ticker=ticker, as_of=as_of or str(date.today()), setup_id=template["id"], portfolio_id=book["id"] if book else None)
    if book and book["as_of"] != str(request.as_of):
        raise ValueError("Portfolio snapshot date must match the analysis date")
    execute(ctx, "analysis", request.model_dump(mode="json"), lambda root: services.analyze(request, template, custom, book, root), as_json)


@app.command()
@handled
def scan(ctx: typer.Context, tickers: str = typer.Option(..., prompt="Symbols, separated by commas"), min_price: float = 0,
         min_volume: float = 0, min_change: float = -100, as_json: bool = typer.Option(False, "--json")):
    """Screen up to 30 stocks by price, volume and daily change."""
    request = Scan(tickers=parts(tickers), min_price=min_price, min_volume=min_volume, min_change=min_change)
    execute(ctx, "scan", request.model_dump(mode="json"), lambda root: services.scan(request), as_json)


@app.command()
@handled
def backtest(ctx: typer.Context, tickers: str = typer.Option(..., prompt="Symbols, separated by commas"),
             start: str = typer.Option(..., prompt="Start date YYYY-MM-DD"), end: str = typer.Option(..., prompt="End date YYYY-MM-DD"),
             setup: str = typer.Option(..., prompt="Core-only setup name or ID"), every_n_days: int = 7, as_json: bool = typer.Option(False, "--json")):
    """Evaluate historical decisions, limited to 30 ticker/date cells."""
    template = resolve(ctx, "setups", setup)
    if template["custom_analysts"]:
        raise ValueError("Use a setup without custom reviewers for upstream backtests")
    request = Backtest(tickers=parts(tickers), start=start, end=end, every_n_days=every_n_days, setup_id=template["id"])
    execute(ctx, "backtest", request.model_dump(mode="json"), lambda root: services.backtest(request, template, root), as_json)


@app.command()
@handled
def jobs(ctx: typer.Context, job_id: str | None = None, as_json: bool = typer.Option(False, "--json")):
    """List research history or retrieve a saved job and result."""
    value = store(ctx).get("jobs", job_id) if job_id else [
        {k: r[k] for k in ("id", "kind", "status", "updated_at")} for r in store(ctx).list("jobs")]
    show(value, as_json)
