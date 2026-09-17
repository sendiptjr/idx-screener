"""Ubah data mentah (OHLCV + fundamental) menjadi satu baris metrik per emiten.

Kunci pada dict hasil itulah "nama variabel" yang bisa dipakai di ekspresi
filter, misalnya `per < 10 and rsi14 < 30`.
"""

from __future__ import annotations

import math

import pandas as pd

from . import indicators as ind
from .providers.yahoo import SEKTOR_ID
from .universe import Emiten

# Perkiraan jumlah hari bursa.
LOOKBACK = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252}

# Deskripsi tiap metrik, dipakai perintah `idxscreen fields`.
FIELD_DOCS: dict[str, str] = {
    "ticker": "Kode emiten",
    "name": "Nama perusahaan",
    "sector": "Sektor",
    "industry": "Sub-industri menurut Yahoo Finance",
    "close": "Harga penutupan terakhir (Rp)",
    "prev_close": "Harga penutupan sebelumnya (Rp)",
    "change_pct": "Perubahan harga harian (%)",
    "ara_limit": "Batas auto reject atas hari ini (%), menurut tingkat harga acuan",
    "dist_ara": "Sisa ruang ke batas ARA (%); 0 berarti terkunci",
    "at_ara": "Penutupan terkunci di ARA (True/False) - tidak bisa dibeli di harga itu",
    "volume": "Volume lembar hari terakhir",
    "value_traded": "Nilai transaksi hari terakhir (Rp)",
    "avg_volume_20": "Rata-rata volume 20 hari (lembar)",
    "avg_value_20": "Rata-rata nilai transaksi 20 hari (Rp) - ukuran likuiditas",
    "volume_ratio": "Volume terakhir dibagi rata-rata 20 hari",
    "market_cap": "Kapitalisasi pasar (Rp)",
    "per": "Price to Earnings Ratio (x)",
    "forward_per": "PER berbasis proyeksi laba (x)",
    "peg": "PEG ratio (x)",
    "pbv": "Price to Book Value (x)",
    "psr": "Price to Sales Ratio (x)",
    "ev_ebitda": "Enterprise Value / EBITDA (x)",
    "roe": "Return on Equity (%)",
    "roa": "Return on Assets (%)",
    "npm": "Net Profit Margin (%)",
    "opm": "Operating Margin (%)",
    "gpm": "Gross Margin (%)",
    "der": "Debt to Equity Ratio (x)",
    "current_ratio": "Current ratio (x)",
    "quick_ratio": "Quick ratio (x)",
    "revenue_growth": "Pertumbuhan pendapatan YoY (%)",
    "earnings_growth": "Pertumbuhan laba YoY (%)",
    "dividend_yield": "Dividend yield indikatif menurut Yahoo (%)",
    "dividend_yield_ttm": "Dividend yield 12 bulan terakhir, dihitung dari nominal dividen (%)",
    "payout_ratio": "Dividend payout ratio (%)",
    "eps": "Laba per saham (Rp)",
    "bvps": "Nilai buku per saham (Rp)",
    "beta": "Beta terhadap pasar",
    "sma20": "Simple moving average 20 hari",
    "sma50": "Simple moving average 50 hari",
    "sma200": "Simple moving average 200 hari",
    "ema9": "Exponential moving average 9 hari",
    "dist_sma20": "Jarak harga ke SMA20 (%)",
    "dist_sma50": "Jarak harga ke SMA50 (%)",
    "dist_sma200": "Jarak harga ke SMA200 (%)",
    "above_sma20": "Harga di atas SMA20 (True/False)",
    "above_sma50": "Harga di atas SMA50 (True/False)",
    "above_sma200": "Harga di atas SMA200 (True/False)",
    "golden_cross": "SMA50 baru memotong ke atas SMA200 dalam 10 hari terakhir",
    "death_cross": "SMA50 baru memotong ke bawah SMA200 dalam 10 hari terakhir",
    "rsi14": "RSI 14 hari",
    "macd": "Garis MACD",
    "macd_signal": "Garis sinyal MACD",
    "macd_hist": "Histogram MACD",
    "macd_cross_up": "Histogram MACD baru berubah positif dalam 5 hari terakhir",
    "stoch_k": "Stochastic %K (14,3)",
    "stoch_d": "Stochastic %D (14,3)",
    "mfi14": "Money Flow Index 14 hari",
    "atr14": "Average True Range 14 hari (Rp)",
    "atr_pct": "ATR14 terhadap harga (%) - ukuran volatilitas",
    "bb_upper": "Batas atas Bollinger Band (20,2)",
    "bb_lower": "Batas bawah Bollinger Band (20,2)",
    "bb_width": "Lebar Bollinger Band terhadap harga",
    "bb_pct_b": "Posisi harga dalam Bollinger Band (0 = batas bawah, 1 = batas atas)",
    "bb_squeeze": "Lebar BB berada di 20% tersempit selama 6 bulan terakhir",
    "high_52w": "Harga tertinggi 52 minggu",
    "low_52w": "Harga terendah 52 minggu",
    "dist_52w_high": "Jarak ke harga tertinggi 52 minggu (%, negatif = di bawah)",
    "dist_52w_low": "Jarak dari harga terendah 52 minggu (%)",
    "ret_1w": "Return 1 minggu (%)",
    "ret_1m": "Return 1 bulan (%)",
    "ret_3m": "Return 3 bulan (%)",
    "ret_6m": "Return 6 bulan (%)",
    "ret_1y": "Return 1 tahun (%)",
    "ret_ytd": "Return year to date (%)",
    "volatility_1y": "Deviasi standar return harian disetahunkan (%)",
    "max_drawdown_1y": "Penurunan terdalam dari puncak dalam 1 tahun (%)",
    "up_days_1m": "Porsi hari naik dalam 1 bulan terakhir (%)",
    "data_points": "Jumlah hari bursa yang tersedia",
    "last_date": "Tanggal data harga terakhir",
    "stale_days": "Selisih hari kalender antara data terakhir dan hari ini",
}

TEXT_FIELDS = {"ticker", "name", "sector", "industry", "last_date"}

# Metrik yang hanya tersedia lewat Ticker.info (satu permintaan per emiten),
# bukan dari screener massal. Screener menundanya sampai kandidat mengerucut.
DEEP_FIELDS = {
    "industry", "forward_per", "peg", "psr", "ev_ebitda", "roa", "npm", "opm",
    "gpm", "der", "current_ratio", "quick_ratio", "revenue_growth",
    "earnings_growth", "payout_ratio", "beta",
}
NUMERIC_FIELDS = [k for k in FIELD_DOCS if k not in TEXT_FIELDS]


def build_row(
    emiten: Emiten,
    prices: pd.DataFrame,
    fundamental: dict | None = None,
    *,
    asof: pd.Timestamp | None = None,
) -> dict | None:
    """Hitung seluruh metrik untuk satu emiten.

    `asof` memotong data harga sampai tanggal tersebut; dipakai backtest.
    Mengembalikan None bila data harga terlalu pendek untuk dihitung.
    """
    df = prices.dropna(subset=["Close"])
    if asof is not None:
        df = df[df.index <= asof]
    if len(df) < 25:
        return None

    close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
    fundamental = fundamental or {}
    last = close.iloc[-1]

    row: dict = {
        "ticker": emiten.ticker,
        "name": emiten.name or fundamental.get("name") or "",
        "sector": emiten.sector or _sektor(fundamental.get("sector")),
        "industry": fundamental.get("industry") or "",
        "close": _v(last),
        "prev_close": _v(close.iloc[-2]),
        "change_pct": _v((last / close.iloc[-2] - 1) * 100),
        "volume": _v(volume.iloc[-1]),
        "value_traded": _v(last * volume.iloc[-1]),
    }

    # Batas ARA ditentukan tingkat harga acuan (penutupan hari sebelumnya).
    batas = _batas_ara(close.iloc[-2])
    row["ara_limit"] = batas
    row["dist_ara"] = _v(max(batas - row["change_pct"], 0.0)) if row["change_pct"] is not None else None
    row["at_ara"] = (
        bool(row["change_pct"] >= batas - 0.4) if row["change_pct"] is not None else None
    )

    avg_vol20 = volume.tail(20).mean()
    row["avg_volume_20"] = _v(avg_vol20)
    row["avg_value_20"] = _v((close * volume).tail(20).mean())
    row["volume_ratio"] = _v(volume.iloc[-1] / avg_vol20) if avg_vol20 else None

    # ---- fundamental ----
    for key in (
        "market_cap", "per", "forward_per", "peg", "pbv", "psr", "ev_ebitda",
        "roe", "roa", "npm", "opm", "gpm", "der", "current_ratio", "quick_ratio",
        "revenue_growth", "earnings_growth", "dividend_yield", "dividend_yield_ttm",
        "payout_ratio", "eps", "bvps", "beta",
    ):
        row[key] = fundamental.get(key)

    # ---- moving average ----
    s20, s50, s200 = ind.sma(close, 20), ind.sma(close, 50), ind.sma(close, 200)
    row["sma20"], row["sma50"], row["sma200"] = _v(s20.iloc[-1]), _v(s50.iloc[-1]), _v(s200.iloc[-1])
    row["ema9"] = _v(ind.ema(close, 9).iloc[-1])
    for tag, series in (("20", s20), ("50", s50), ("200", s200)):
        ma = series.iloc[-1]
        row[f"dist_sma{tag}"] = _v((last / ma - 1) * 100) if _ok(ma) else None
        row[f"above_sma{tag}"] = bool(last > ma) if _ok(ma) else None

    row["golden_cross"] = _crossed(s50, s200, up=True, window=10)
    row["death_cross"] = _crossed(s50, s200, up=False, window=10)

    # ---- osilator ----
    row["rsi14"] = _v(ind.rsi(close, 14).iloc[-1])
    macd_df = ind.macd(close)
    row["macd"] = _v(macd_df["macd"].iloc[-1])
    row["macd_signal"] = _v(macd_df["signal"].iloc[-1])
    row["macd_hist"] = _v(macd_df["hist"].iloc[-1])
    row["macd_cross_up"] = _turned_positive(macd_df["hist"], window=5)

    stoch = ind.stochastic(high, low, close)
    row["stoch_k"], row["stoch_d"] = _v(stoch["k"].iloc[-1]), _v(stoch["d"].iloc[-1])
    row["mfi14"] = _v(ind.money_flow_index(high, low, close, volume).iloc[-1])

    atr14 = ind.atr(high, low, close).iloc[-1]
    row["atr14"] = _v(atr14)
    row["atr_pct"] = _v(atr14 / last * 100) if _ok(atr14) and last else None

    bb = ind.bollinger(close)
    row["bb_upper"], row["bb_lower"] = _v(bb["upper"].iloc[-1]), _v(bb["lower"].iloc[-1])
    row["bb_width"], row["bb_pct_b"] = _v(bb["width"].iloc[-1]), _v(bb["pct_b"].iloc[-1])
    width_hist = bb["width"].tail(126).dropna()
    row["bb_squeeze"] = (
        bool(bb["width"].iloc[-1] <= width_hist.quantile(0.2))
        if len(width_hist) >= 40 and _ok(bb["width"].iloc[-1])
        else None
    )

    # ---- posisi 52 minggu ----
    window_52w = close.tail(252)
    hi, lo = window_52w.max(), window_52w.min()
    row["high_52w"], row["low_52w"] = _v(hi), _v(lo)
    row["dist_52w_high"] = _v((last / hi - 1) * 100) if _ok(hi) and hi else None
    row["dist_52w_low"] = _v((last / lo - 1) * 100) if _ok(lo) and lo else None

    # ---- return ----
    for label, periods in LOOKBACK.items():
        row[f"ret_{label}"] = (
            _v((last / close.iloc[-periods - 1] - 1) * 100) if len(close) > periods else None
        )
    row["ret_ytd"] = _ytd_return(close)

    daily = close.pct_change().tail(252).dropna()
    row["volatility_1y"] = _v(daily.std() * math.sqrt(252) * 100) if len(daily) > 20 else None
    row["max_drawdown_1y"] = _max_drawdown(close.tail(252))
    last_month = close.pct_change().tail(21).dropna()
    row["up_days_1m"] = _v((last_month > 0).mean() * 100) if len(last_month) else None

    row["data_points"] = len(df)
    last_date = df.index[-1]
    row["last_date"] = last_date.strftime("%Y-%m-%d")
    reference = asof if asof is not None else pd.Timestamp.now(tz=last_date.tz)
    row["stale_days"] = int((reference.normalize() - last_date.normalize()).days)
    return row


def _batas_ara(harga_acuan: float) -> float:
    """Batas auto reject atas IDX menurut tingkat harga acuan, dalam persen.

    Terverifikasi dari data: kenaikan intraday mentok persis di 20,0% untuk
    saham di atas Rp5.000 dan di 25% untuk Rp200-5.000.
    """
    if harga_acuan < 200:
        return 35.0
    return 25.0 if harga_acuan <= 5000 else 20.0


def _sektor(yahoo_sector: str | None) -> str:
    """Label sektor Yahoo -> padanan IDX-IC dalam bahasa Indonesia."""
    if not yahoo_sector:
        return ""
    return SEKTOR_ID.get(yahoo_sector, yahoo_sector)


def _ytd_return(close: pd.Series) -> float | None:
    year = close.index[-1].year
    prior = close[close.index.year < year]
    if prior.empty:
        return None
    base = prior.iloc[-1]
    return _v((close.iloc[-1] / base - 1) * 100) if base else None


def _max_drawdown(close: pd.Series) -> float | None:
    if close.empty:
        return None
    running_max = close.cummax()
    return _v((close / running_max - 1).min() * 100)


def _crossed(fast: pd.Series, slow: pd.Series, *, up: bool, window: int) -> bool | None:
    diff = (fast - slow).dropna()
    if len(diff) < window + 1:
        return None
    recent = diff.tail(window + 1)
    now, before = recent.iloc[-1], recent.iloc[0]
    return bool(now > 0 and before <= 0) if up else bool(now < 0 and before >= 0)


def _turned_positive(series: pd.Series, *, window: int) -> bool | None:
    s = series.dropna()
    if len(s) < window + 1:
        return None
    recent = s.tail(window + 1)
    return bool(recent.iloc[-1] > 0 and recent.iloc[0] <= 0)


def _ok(value) -> bool:
    return value is not None and not pd.isna(value)


def _v(value) -> float | None:
    """Bersihkan NaN/inf agar hasil aman diserialisasi ke JSON."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) or math.isinf(out) else out
