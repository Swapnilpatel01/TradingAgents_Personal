"""Daily adjusted market data for the optional Studio interface."""

import math
from datetime import UTC, datetime


def history(ticker, period="6mo"):
    import yfinance as yf

    instrument = yf.Ticker(ticker)
    frame = instrument.history(period=period, auto_adjust=True, timeout=15)
    if frame.empty:
        raise ValueError(f"No price history available for {ticker}")
    bars = []
    for index, row in frame.iterrows():
        values = [float(row[k]) for k in ("Open", "High", "Low", "Close", "Volume")]
        if all(math.isfinite(v) for v in values):
            bars.append(dict(zip(("open", "high", "low", "close", "volume"), values, strict=True)))
            bars[-1]["date"] = index.date().isoformat()
    if not bars:
        raise ValueError(f"No valid bars available for {ticker}")
    metadata = instrument.history_metadata or {}
    return {"ticker": ticker.upper(), "currency": metadata.get("currency"), "bars": bars,
            "source": "Yahoo Finance via yfinance; adjusted daily bars, may be delayed",
            "fetched_at": datetime.now(UTC).isoformat()}

