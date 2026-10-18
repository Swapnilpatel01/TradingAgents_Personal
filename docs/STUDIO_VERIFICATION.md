# Studio verification

Verified on Windows with Python 3.12 and headless Microsoft Edge.

| Boundary | Evidence |
| --- | --- |
| Browser → API → SQLite | Saved analysts, two setups and portfolio; reloaded and checked persistence |
| Browser → research queue → result | Mocked analysis, custom review, scanner, backtest and valuation rendered successfully |
| Untrusted report → UI | Script-like analyst content rendered as text, no page errors |
| Desktop and phone layout | 1440px desktop and 390px mobile screenshots inspected; no horizontal page overflow |
| PWA | Offline shell reload succeeded; Cache Storage contains no API responses |
| Market provider | Real AAPL history returned 22 daily bars through 2026-10-16, currency USD |
| ChatGPT subscription | Existing sign-in listed seven models; small `gpt-6-luna` inference returned the requested connection-check text |
| API contracts | 16 Studio tests pass, including authentication, origin/host checks, date bounds, reference integrity, provider selection, job failure/restart and incomplete valuations |
| Upstream regression suite | 1,369 passed, 4 skipped, 1 deselected, 100 subtests passed; five failures reproduced on unchanged upstream checkout |

The five existing Windows failures concern POSIX permission assertions (two),
upgrade-command path assumptions (two), and Windows' temporary directory being
beneath the user's home (one). No upstream sources were changed to hide these.
Linux CI is configured to run the full suite.

Browser tests substitute deterministic market and inference data at the service
boundary. This verifies the complete local UI/API/storage flow without pretending
to validate model quality. Full live graph research/backtests, physical iPhone
installation, and deployment behind an HTTPS proxy were not exercised.

## Reproduce browser tests

Install the Python extras from STUDIO.md, plus Node.js and Playwright:

```sh
npm install --no-save playwright
npx playwright install chromium
python tests/studio_browser_server.py
# In another terminal:
node tests/studio_browser.cjs
```

The fixture server is loopback-only on port 8766 with a fixed test key and temporary
database. It never runs the real inference provider. Restart it for a fresh test.
Set `STUDIO_BROWSER_CHANNEL=msedge` to use installed Edge instead of Chromium.
Optional `STUDIO_SCREENSHOTS` writes screenshots to the selected directory.
Never deploy the test server; use `tradingagents-studio` for actual research.

## Scope to review

Custom analysts are supplemental reviews, not custom graph nodes. Setups are
research templates, not automatic trade triggers. Backtesting scores independent
historical decisions, not a strategy equity curve. Portfolio tracking is manually
entered long holdings with current unrealized P/L, without FX, transaction history
or broker synchronization. The PWA runs research on its host computer, not on iOS.
