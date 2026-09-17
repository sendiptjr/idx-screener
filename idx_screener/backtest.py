"""Uji cepat sebuah strategi ke data masa lalu.

Batas penting: data fundamental dari Yahoo hanya tersedia versi terkini, bukan
versi pada tanggal rebalancing. Karena itu filter fundamental ditolak secara
default - memakainya berarti memasukkan informasi masa depan (look-ahead bias)
dan hasil backtest jadi terlalu bagus.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .metrics import build_row
from .rules import compile_rules
from .screener import Screener

FUNDAMENTAL_FIELDS = {
    "market_cap", "per", "forward_per", "peg", "pbv", "psr", "ev_ebitda",
    "roe", "roa", "npm", "opm", "gpm", "der", "current_ratio", "quick_ratio",
    "revenue_growth", "earnings_growth", "dividend_yield", "dividend_yield_ttm", "payout_ratio",
    "eps", "bvps", "beta", "industry",
}


class LookAheadError(ValueError):
    pass


@dataclass
class BacktestResult:
    periods: pd.DataFrame        # ringkasan per tanggal rebalancing
    trades: pd.DataFrame         # tiap saham terpilih dan return-nya
    summary: dict


def backtest(
    screener: Screener,
    filters: list[str],
    *,
    periods: int = 12,
    step_days: int = 21,
    hold_days: int = 21,
    top_n: int | None = 10,
    sort_by: str | None = None,
    ascending: bool = False,
    allow_fundamentals: bool = False,
) -> BacktestResult:
    rules = compile_rules(filters)
    used: set[str] = set()
    for rule in rules:
        used |= rule.fields
    risky = used & FUNDAMENTAL_FIELDS
    if risky and not allow_fundamentals:
        raise LookAheadError(
            "Filter fundamental tidak bisa di-backtest jujur karena nilainya "
            f"hanya tersedia untuk hari ini: {', '.join(sorted(risky))}. "
            "Buang filter itu, atau pakai --allow-fundamentals bila sadar biasnya."
        )

    prices = screener.provider.prices(screener.universe)
    if not prices:
        raise ValueError("Tidak ada data harga untuk di-backtest.")

    calendar = _trading_calendar(prices)
    if len(calendar) < step_days * 2 + hold_days:
        raise ValueError("Riwayat harga terlalu pendek untuk jumlah periode yang diminta.")

    marks = _rebalance_dates(calendar, periods, step_days, hold_days)
    by_ticker = {e.ticker: e for e in screener.universe}

    period_rows, trade_rows = [], []
    for asof in marks:
        rows = []
        for ticker, df in prices.items():
            row = build_row(by_ticker[ticker], df, None, asof=asof)
            if row:
                rows.append(row)
        frame = pd.DataFrame(rows)
        if frame.empty:
            continue

        selected = frame
        for rule in rules:
            verdict = selected.apply(lambda r, rule=rule: rule.evaluate(r.to_dict()), axis=1)
            selected = selected[verdict.map(lambda v: v is True)]
            if selected.empty:
                break
        if sort_by and sort_by in selected.columns and not selected.empty:
            selected = selected.sort_values(sort_by, ascending=ascending, na_position="last")
        if top_n:
            selected = selected.head(top_n)

        universe_returns = [
            _forward_return(prices[t], asof, hold_days) for t in frame["ticker"]
        ]
        universe_returns = [r for r in universe_returns if r is not None]

        picks = []
        for ticker in selected["ticker"]:
            fwd = _forward_return(prices[ticker], asof, hold_days)
            if fwd is None:
                continue
            picks.append(fwd)
            trade_rows.append(
                {"tanggal": asof.date().isoformat(), "ticker": ticker, "fwd_return": fwd}
            )

        period_rows.append(
            {
                "tanggal": asof.date().isoformat(),
                "terpilih": len(picks),
                "return_strategi": _mean(picks),
                "return_pasar": _mean(universe_returns),
                "selisih": _diff(_mean(picks), _mean(universe_returns)),
                "win_rate": (
                    round(sum(1 for r in picks if r > 0) / len(picks) * 100, 1)
                    if picks else None
                ),
            }
        )

    period_frame = pd.DataFrame(period_rows)
    trade_frame = pd.DataFrame(trade_rows)
    summary = _summarize(period_frame, trade_frame, hold_days)
    return BacktestResult(periods=period_frame, trades=trade_frame, summary=summary)


def _summarize(periods: pd.DataFrame, trades: pd.DataFrame, hold_days: int) -> dict:
    if periods.empty:
        return {"periode": 0, "catatan": "tidak ada periode yang menghasilkan pilihan"}
    strategy = periods["return_strategi"].dropna()
    market = periods["return_pasar"].dropna()
    return {
        "periode": int(len(periods)),
        "hari_tahan": hold_days,
        "total_pilihan": int(periods["terpilih"].sum()),
        "rata2_pilihan_per_periode": round(periods["terpilih"].mean(), 1),
        "return_rata2_strategi": round(strategy.mean(), 2) if len(strategy) else None,
        "return_rata2_pasar": round(market.mean(), 2) if len(market) else None,
        "selisih_rata2": (
            round(strategy.mean() - market.mean(), 2) if len(strategy) and len(market) else None
        ),
        "periode_menang": (
            int((periods["selisih"].dropna() > 0).sum()) if "selisih" in periods else 0
        ),
        "win_rate_saham": (
            round((trades["fwd_return"] > 0).mean() * 100, 1) if not trades.empty else None
        ),
        "return_terbaik": round(trades["fwd_return"].max(), 2) if not trades.empty else None,
        "return_terburuk": round(trades["fwd_return"].min(), 2) if not trades.empty else None,
    }


def _trading_calendar(prices: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """Gabungan tanggal bursa dari emiten dengan riwayat terpanjang."""
    longest = max(prices.values(), key=len)
    return longest.index


def _rebalance_dates(
    calendar: pd.DatetimeIndex, periods: int, step_days: int, hold_days: int
) -> list[pd.Timestamp]:
    last_usable = len(calendar) - hold_days - 1
    marks = [
        calendar[last_usable - i * step_days]
        for i in range(periods)
        if last_usable - i * step_days >= 220  # sisakan data untuk SMA200
    ]
    return sorted(marks)


def _forward_return(df: pd.DataFrame, asof: pd.Timestamp, hold_days: int) -> float | None:
    window = df[df.index <= asof]
    if window.empty:
        return None
    start_pos = df.index.get_loc(window.index[-1])
    end_pos = start_pos + hold_days
    if end_pos >= len(df):
        return None
    start, end = df["Close"].iloc[start_pos], df["Close"].iloc[end_pos]
    if not start or pd.isna(start) or pd.isna(end):
        return None
    return float((end / start - 1) * 100)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 2)
