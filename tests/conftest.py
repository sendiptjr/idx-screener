"""Data sintetis supaya test tidak pernah menyentuh jaringan."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from idx_screener.universe import Emiten


def make_prices(
    n: int = 600, start: float = 1000.0, drift: float = 0.0006, seed: int = 0
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-09-17", periods=n)
    steps = rng.normal(drift, 0.015, n)
    close = start * np.exp(np.cumsum(steps))
    high = close * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.008, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(1_000_000, 20_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


class FakeProvider:
    """Pengganti YahooProvider dengan data tetap."""

    def __init__(self, prices: dict[str, pd.DataFrame], fundamentals: dict[str, dict] | None = None):
        self._prices = prices
        self._fundamentals = fundamentals or {}
        self.errors: dict[str, str] = {}
        self.deep_diminta: set[str] = set()

    def prices(self, emiten, progress=None):
        return {e.ticker: self._prices[e.ticker] for e in emiten if e.ticker in self._prices}

    def fundamentals(self, emiten, progress=None, deep_tickers=None):
        self.deep_diminta = set(deep_tickers or ())
        return {e.ticker: self._fundamentals[e.ticker] for e in emiten if e.ticker in self._fundamentals}


@pytest.fixture
def universe() -> list[Emiten]:
    return [
        Emiten("MURAH", "Emiten Murah", "Keuangan"),
        Emiten("MAHAL", "Emiten Mahal", "Teknologi"),
        Emiten("SEPI", "Emiten Sepi", "Properti"),
    ]


@pytest.fixture
def provider(universe) -> FakeProvider:
    prices = {
        "MURAH": make_prices(seed=1, drift=0.0008),
        "MAHAL": make_prices(seed=2, drift=-0.0004),
        "SEPI": make_prices(seed=3, drift=0.0),
    }
    prices["SEPI"]["Volume"] = 100.0  # tidak likuid
    fundamentals = {
        "MURAH": {"name": "Emiten Murah", "sector": "Keuangan", "per": 8.0, "pbv": 1.1,
                  "roe": 18.0, "der": 0.4, "dividend_yield": 6.5, "market_cap": 8e13},
        "MAHAL": {"name": "Emiten Mahal", "sector": "Teknologi", "per": 45.0, "pbv": 7.5,
                  "roe": 6.0, "der": 2.2, "dividend_yield": 0.0, "market_cap": 2e13},
        # SEPI sengaja tanpa fundamental untuk menguji penanganan data kosong.
    }
    return FakeProvider(prices, fundamentals)
