"""Strict input contracts for the personal Studio server."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Symbol = str


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Analyst(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    instructions: str = Field(min_length=10, max_length=8000)


class Setup(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    analysts: list[Literal["market", "social", "news", "fundamentals"]] = Field(
        default_factory=lambda: ["market", "news"], min_length=1, max_length=4)
    custom_analysts: list[str] = Field(default_factory=list, max_length=8)
    quick_model: str = Field(default="gpt-6-luna", min_length=1, max_length=100)
    deep_model: str = Field(default="gpt-6-sol", min_length=1, max_length=100)
    debate_rounds: int = Field(default=1, ge=1, le=3)
    notes: str = Field(default="", max_length=4000)


class Holding(StrictModel):
    ticker: str = Field(pattern=r"^[A-Za-z0-9^][A-Za-z0-9.^=\-]{0,24}$")
    quantity: float = Field(gt=0, le=1e12)
    average_price: float = Field(gt=0, le=1e12)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class Portfolio(StrictModel):
    name: str = Field(default="My portfolio", min_length=1, max_length=80)
    cash: float = Field(default=0, ge=0, le=1e15)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    as_of: date
    positions: list[Holding] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_symbols(self):
        symbols = [p.ticker.upper() for p in self.positions]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Combine duplicate symbols into a single holding")
        if self.as_of > date.today():
            raise ValueError("Portfolio date cannot be in the future")
        return self


class Run(StrictModel):
    ticker: str = Field(pattern=r"^[A-Za-z0-9^][A-Za-z0-9.^=\-]{0,24}$")
    as_of: date
    setup_id: str
    portfolio_id: str | None = None

    @model_validator(mode="after")
    def past_only(self):
        if self.as_of > date.today():
            raise ValueError("Analysis date cannot be in the future")
        return self


class Backtest(StrictModel):
    tickers: list[str] = Field(min_length=1, max_length=10)
    start: date
    end: date
    every_n_days: int = Field(default=7, ge=1, le=365)
    setup_id: str

    @model_validator(mode="after")
    def bounded_grid(self):
        if self.start > self.end or self.end > date.today():
            raise ValueError("Choose an ordered date range ending no later than today")
        for ticker in self.tickers:
            Run(ticker=ticker, as_of=self.start, setup_id=self.setup_id)
        if ((self.end-self.start).days // self.every_n_days + 1) * len(self.tickers) > 30:
            raise ValueError("A backtest is limited to 30 analysis cells")
        return self


class Scan(StrictModel):
    tickers: list[str] = Field(min_length=1, max_length=30)
    min_price: float = Field(default=0, ge=0)
    min_volume: float = Field(default=0, ge=0)
    min_change: float = Field(default=-100, ge=-100, le=10000)

    @model_validator(mode="after")
    def symbols(self):
        for ticker in self.tickers:
            Run(ticker=ticker, as_of=date.today(), setup_id="scan")
        return self
