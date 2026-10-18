# Studio in a terminal

## Original-style Windows launcher

Double-click `Start TradingAgents.cmd` at the repository root. It opens an
arrow-key workspace menu in the same terminal interface as the original CLI.
Choose **Run analysis — original setup and live agent display** for the original
workflow. Other entries expose saved setups, custom reviewers, scanner, historical
backtests, portfolio snapshots and research history using arrow-key selections
and guided input forms. You return to the workspace menu after each action.

**Run a saved setup** uses the original streaming live-agent display and then
adds custom reviewer reports to the saved result. Create a setup first using the
workspace menu. Custom reviewers remain supplemental to the upstream rating.
No separate website is involved. The original bare `tradingagents` command and
all scriptable `tradingagents studio` commands remain available.

You can also open this interface with `tradingagents workspace`. The launcher
uses the checkout beside it and requires its `.venv`. Passing arguments to the
launcher forwards them to the original CLI, for example `"Start TradingAgents.cmd" --help`.

## Scriptable terminal commands

Studio works directly in PowerShell, Command Prompt, Windows Terminal, or a Unix
shell. No browser, web server, Studio access key, FastAPI or uvicorn is required.
The original `tradingagents` interactive workflow remains available unchanged.

Activate your virtual environment, install this checkout, and use the same
ChatGPT subscription sign-in as the original CLI:

```sh
pip install -e .
tradingagents login chatgpt
tradingagents studio
```

The last command shows an action menu. After an action completes, run it again
for another action. All commands are also available without the menu:

```sh
tradingagents studio --help
tradingagents studio quote --ticker AAPL --period 6mo
tradingagents studio analyst-add --name Skeptic --instructions "Find unsupported assumptions and missing evidence."
tradingagents studio setup-add --name Core --analysts market,news,fundamentals
tradingagents studio setup-add --name Review --custom Skeptic
tradingagents studio analyze --ticker AAPL --setup Review
tradingagents studio scan --tickers AAPL,MSFT,NVDA --min-volume 1000000 --min-change 1
tradingagents studio backtest --tickers AAPL --setup Core --start 2026-09-01 --end 2026-09-15 --every-n-days 7
tradingagents studio portfolio-add --name Holdings --cash 1000 --currency USD --holding AAPL:10:200 --holding MSFT:5:400
tradingagents studio portfolio-value --portfolio Holdings
tradingagents studio jobs
```

`quote` shows recent daily bars and range performance in a terminal table. It
replaces the browser chart for command-line use. The PWA itself is only relevant
to the optional web interface. All other Studio research services are shared.
Required options prompt when omitted; use `--help` on a command for all options.
For historical analysis use `--date YYYY-MM-DD`. Optional `--portfolio Holdings`
requires a snapshot dated exactly on the analysis date. Historical backtests use
core-only setups and remain limited to 30 independent decision cells.

## Shared data and scripts

The terminal uses `STUDIO_DATA_DIR` or `./studio-data`, exactly like the web app.
Run both from the same directory or explicitly choose the same absolute path:

```sh
tradingagents studio --data-dir "C:\path\to\studio-data" records setups
tradingagents studio records analysts --json
tradingagents studio export setups Core > core.json
tradingagents studio import setups core.json
tradingagents studio import setups core.json --record-id EXISTING_ID
tradingagents studio scan --tickers AAPL,MSFT --json > scan.json
tradingagents studio jobs --job-id JOB_ID --json > research.json
```

`import` accepts the same validated profile JSON as the web interface. `export`
omits metadata so the result can be edited and reimported. Duplicate names require
using the record ID. Use the IDs printed by `records` to disambiguate.
Terminal research runs synchronously and saves jobs/results in the shared SQLite
history. Ctrl+C records an interrupted job and exits with code 130; provider
failures record a failed job and return nonzero. Retry by running the command again.
Use one terminal research run at a time and avoid restarting the web server while
a terminal job is running, because startup marks unfinished jobs interrupted.

No live trading or broker connections are introduced. Authentication, custom
reviewer scope, price delays, valuation limits and historical scoring rules are
the same as documented in [STUDIO.md](STUDIO.md).
