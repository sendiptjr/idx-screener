"""Cache SQLite untuk harga harian dan data fundamental.

Tujuannya sederhana: sekali ambil dari Yahoo, sesi berikutnya jalan offline
selama data belum kedaluwarsa (lihat TTL di config).
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from .config import CACHE_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date   TEXT NOT NULL,
    open   REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker     TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    payload    TEXT NOT NULL,
    depth      TEXT NOT NULL DEFAULT 'bulk'
);
CREATE TABLE IF NOT EXISTS price_fetch (
    ticker     TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    period     TEXT NOT NULL DEFAULT ''
);
"""


class Cache:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else CACHE_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- harga ----------

    def put_prices(self, ticker: str, df: pd.DataFrame, period: str = "") -> None:
        """Simpan OHLCV. Index df harus DatetimeIndex."""
        if df is None or df.empty:
            self.mark_price_fetch(ticker, period)
            return
        rows = [
            (
                ticker,
                idx.strftime("%Y-%m-%d"),
                _f(row.get("Open")),
                _f(row.get("High")),
                _f(row.get("Low")),
                _f(row.get("Close")),
                _f(row.get("Volume")),
            )
            for idx, row in df.iterrows()
        ]
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", rows
            )
        self.mark_price_fetch(ticker, period)

    def get_prices(self, ticker: str) -> pd.DataFrame:
        with self._conn() as conn:
            df = pd.read_sql(
                "SELECT date, open, high, low, close, volume FROM prices "
                "WHERE ticker = ? ORDER BY date",
                conn,
                params=(ticker,),
            )
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        return df

    def mark_price_fetch(self, ticker: str, period: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_fetch VALUES (?, ?, ?)",
                (ticker, time.time(), period),
            )

    def price_fetch_info(self, ticker: str) -> tuple[float, str] | None:
        """(umur_jam, periode_yang_diambil) atau None bila belum pernah diambil."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT fetched_at, period FROM price_fetch WHERE ticker = ?", (ticker,)
            ).fetchone()
        return None if row is None else ((time.time() - row[0]) / 3600, row[1] or "")

    def price_age_hours(self, ticker: str) -> float | None:
        info = self.price_fetch_info(ticker)
        return None if info is None else info[0]

    # ---------- fundamental ----------

    def put_fundamentals(self, ticker: str, payload: dict, depth: str = "bulk") -> None:
        """Gabungkan payload baru ke yang lama.

        Data `bulk` (dari screener, murah) dan `deep` (dari Ticker.info, mahal)
        saling melengkapi, jadi yang baru hanya menimpa field yang ia isi dan
        tidak boleh menurunkan tingkat kedalaman yang sudah tersimpan.
        """
        lama = self.get_fundamentals(ticker)
        gabungan = dict(lama[0]) if lama else {}
        gabungan.update({k: v for k, v in payload.items() if v is not None})
        if lama and lama[2] == "deep":
            depth = "deep"
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fundamentals VALUES (?,?,?,?)",
                (ticker, time.time(), json.dumps(gabungan, default=str), depth),
            )

    def get_fundamentals(self, ticker: str) -> tuple[dict, float, str] | None:
        """Kembalikan (payload, umur_jam, kedalaman) atau None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, fetched_at, depth FROM fundamentals WHERE ticker = ?",
                (ticker,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0]), (time.time() - row[1]) / 3600, row[2]

    def tickers_by_depth(self, depth: str) -> set[str]:
        with self._conn() as conn:
            return {
                r[0] for r in conn.execute(
                    "SELECT ticker FROM fundamentals WHERE depth = ?", (depth,)
                )
            }

    # ---------- utilitas ----------

    def stats(self) -> dict:
        with self._conn() as conn:
            price_rows = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
            tickers = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM prices"
            ).fetchone()[0]
            funda = conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
            deep = conn.execute(
                "SELECT COUNT(*) FROM fundamentals WHERE depth = 'deep'"
            ).fetchone()[0]
            last = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        return {
            "path": str(self.path),
            "size_mb": round(self.path.stat().st_size / 1e6, 2) if self.path.exists() else 0,
            "price_rows": price_rows,
            "tickers": tickers,
            "fundamentals": funda,
            "fundamentals_deep": deep,
            "last_date": last,
        }

    def clear(self) -> None:
        with self._conn() as conn:
            for table in ("prices", "fundamentals", "price_fetch"):
                conn.execute(f"DELETE FROM {table}")


def _f(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
