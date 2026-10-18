# TradingAgents Studio

An optional personal research interface for this fork. No broker credentials,
order endpoints or live trading are implemented. Core CLI behavior is unchanged.

Prefer a terminal? Run `tradingagents studio` for the action menu, or see
[terminal commands](STUDIO_TERMINAL.md). No web server or Studio extras are needed.

## Install and start

Use Python 3.11 or newer (3.12 recommended):

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[studio,dev]" httpx
tradingagents login chatgpt
tradingagents-studio
```

Open http://127.0.0.1:8765 and enter the access key printed in the terminal.
The server defaults to loopback. The access key protects the local research API;
it is separate from ChatGPT sign-in. Tokens remain in upstream's protected local
credential store and are never sent to the browser. Studio explicitly selects the
`chatgpt` provider for both model tiers; no API-key fallback is used.

Subscription access is subject to your plan, model availability and usage limits.
See [OpenAI's documented plan usage flow](https://developers.openai.com/siwc/token-sharing-open-source).
Sign in on the machine running the server. Studio reports stored sign-in presence;
a successful inference confirms usable access. Models can be loaded from the account.

## Features and boundaries

- Dashboard: adjusted daily price history, range selection, chart inspection and
  queued upstream analyst research. Data comes from Yahoo via yfinance and can be delayed.
- Custom analysts: named instructions saved in SQLite, selected in a setup. They
  review the upstream dated reports using the ChatGPT quick model. Their reports
  are supplements, not inputs that silently alter the upstream rating.
- Trading setups: named analyst selections, models, debate depth and notes.
  Notes are descriptive; setups do not place orders or implement automatic triggers.
- Scanner: an explicit universe of up to 30 symbols, price, daily change and volume
  filters, with individual data failures preserved.
- Historical backtests: upstream independent decision-quality evaluation, up to
  30 ticker/date cells. Outcomes use upstream settlement from the first close
  after the decision. This is not a filled-order portfolio simulation. Custom
  reviewers are excluded; use a core-only setup. Missing/pending outcomes are visible.
- iPhone PWA: responsive interface with install metadata and offline shell. Research
  needs the running server and network. Financial results and access keys are not
  cached by the service worker.
- Portfolio tracking: dated, manually entered long-only holdings and cash; latest
  available valuation and unrealized P/L. No brokerage sync, realized P/L, corporate
  action ledger or FX conversion. Currency mismatches and missing quotes suppress
  the total instead of reporting an incomplete total as complete. An analysis can
  use a snapshot only on that snapshot's exact date. Backtests never inject today's book.

## Data and reliability

`STUDIO_DATA_DIR` defaults to `./studio-data`. Back up the whole folder while the
server is stopped. SQLite holds profiles, snapshots and jobs; upstream research
files live beneath `runs/`. Jobs execute one at a time to avoid upstream global
configuration races. Five queued/running jobs are allowed. Interrupted jobs are
marked on restart and must be submitted again; they are not silently rerun.
Keep this as a single-process server (no multiple uvicorn workers). Failed jobs
show a brief browser message; inspect terminal logs for the cause.

## iPhone access

Run the server on a trusted computer and provide HTTPS using a private reverse
proxy or VPN with HTTPS. Configure `STUDIO_HOST` for the listening interface and
`STUDIO_ALLOWED_HOSTS` with the exact hostname (comma-separated if needed). Set a
stable random `STUDIO_TOKEN` of at least 24 characters in the server environment.
Do not put tokens in URLs. Forward the original Host header. Do not expose this
single-user service as a public multi-user application. In iPhone Safari, open
the HTTPS address, unlock Studio, then Share → Add to Home Screen. Localhost is
secure for desktop development; a plain LAN HTTP address does not support PWA
service workers. The phone does not run Python or the research engine itself.

## Verify and update

```sh
python -m pytest
ruff check tradingagents/studio tests/test_studio.py
```

Tests use mocked market/inference calls and do not consume subscription usage.
Real ChatGPT login, live data and physical iPhone installation require manual checks.

Development is split into `studio/backend` (API/adapters/tests) and
`studio/dashboard-pwa` (interface, dependent on backend). Review/merge the backend
first, then retarget the interface PR to main. Never merge either into upstream
without a separate review. Keep an `upstream` remote for TauricResearch/TradingAgents;
fetch and merge upstream main into a maintenance branch, resolve conflicts, and
run the full suite before opening a fork PR. Studio lives in its own package and
uses public upstream entry points; upstream engine/auth sources are unchanged.
