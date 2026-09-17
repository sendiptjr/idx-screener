"""Pengambil data dari Yahoo Finance (ticker IDX memakai akhiran .JK).

Semua hasil diendapkan ke cache SQLite, jadi pemanggilan berikutnya dalam
rentang TTL tidak menyentuh jaringan sama sekali.
"""

from __future__ import annotations

import random
import time
import warnings
from collections.abc import Callable, Iterable

import pandas as pd

from ..cache import Cache
from ..config import (
    DOWNLOAD_CHUNK,
    FUNDAMENTAL_WORKERS,
    FUNDAMENTAL_TTL_HOURS,
    HISTORY_PERIOD,
    PRICE_TTL_HOURS,
    RETRY_DELAYS,
    YAHOO_SUFFIX,
)
from ..universe import Emiten

warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

Progress = Callable[[str, int, int], None]

# Yahoo memakai 11 sektor GICS; IDX memakai IDX-IC. Pemetaan ini pendekatan:
# "Communication Services" misalnya mencakup telko (Infrastruktur di IDX)
# sekaligus media (Konsumen Non-Primer), dan Yahoo tidak membedakannya.
SEKTOR_ID = {
    "Financial Services": "Keuangan",
    "Technology": "Teknologi",
    "Communication Services": "Infrastruktur",
    "Consumer Cyclical": "Konsumen Non-Primer",
    "Consumer Defensive": "Konsumen Primer",
    "Energy": "Energi",
    "Basic Materials": "Barang Baku",
    "Industrials": "Perindustrian",
    "Real Estate": "Properti",
    "Healthcare": "Kesehatan",
    "Utilities": "Infrastruktur",
}

SCREEN_PAGE = 250  # batas maksimum satu permintaan screener Yahoo


def list_equities(region: str = "id", progress: Progress | None = None) -> list[dict]:
    """Ambil seluruh saham yang terdaftar di satu bursa lewat screener Yahoo.

    Dipakai untuk menyusun daftar emiten IDX tanpa kurasi manual - endpoint
    resmi IDX sendiri diblokir Cloudflare untuk akses otomatis.
    """
    return _screen_all(region, progress)


def _screen_all(
    region: str, progress: Progress | None = None, keep_quote: bool = False
) -> list[dict]:
    import yfinance as yf

    query = yf.EquityQuery("eq", ["region", region])
    hasil: dict[str, dict] = {}
    offset, total = 0, None

    while total is None or offset < total:
        page = yf.screen(query, size=SCREEN_PAGE, offset=offset)
        total = page.get("total", 0)
        quotes = page.get("quotes") or []
        if not quotes:
            break
        for q in quotes:
            symbol = q.get("symbol") or ""
            if not symbol.endswith(YAHOO_SUFFIX):
                continue
            row = {
                "ticker": symbol.removesuffix(YAHOO_SUFFIX),
                "name": _clean_name(q.get("longName") or q.get("shortName") or ""),
                "market_cap": q.get("marketCap"),
                "price": q.get("regularMarketPrice"),
                "avg_volume_3m": q.get("averageDailyVolume3Month"),
            }
            if keep_quote:
                row["_quote"] = q
            hasil[symbol] = row
        offset += len(quotes)
        if progress:
            progress("daftar emiten", min(offset, total), total)

    return sorted(hasil.values(), key=lambda x: x["ticker"])


def _clean_name(name: str) -> str:
    """'PT Bank Central Asia Tbk.' -> 'Bank Central Asia'."""
    name = name.strip().removeprefix("PT ").strip()
    for suffix in (" Tbk.", " Tbk", " (Persero) Tbk.", " (Persero) Tbk"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name.removesuffix(" (Persero)").strip()


def bulk_sectors(region: str = "id", progress: Progress | None = None) -> dict[str, str]:
    """Peta ticker -> sektor (bahasa Indonesia), satu kueri screener per sektor.

    Hasil screener biasa tidak memuat sektor, tapi screener bisa disaring
    menurut sektor - jadi 11 kueri sudah cukup untuk melabeli seluruh bursa.
    """
    import yfinance as yf

    peta: dict[str, str] = {}
    for i, (sektor_yahoo, sektor_id) in enumerate(SEKTOR_ID.items(), start=1):
        query = yf.EquityQuery("and", [
            yf.EquityQuery("eq", ["region", region]),
            yf.EquityQuery("eq", ["sector", sektor_yahoo]),
        ])
        offset, total = 0, None
        while total is None or offset < total:
            try:
                page = yf.screen(query, size=SCREEN_PAGE, offset=offset)
            except Exception:
                break  # sektor ini dilewati; emitennya tetap dapat data lain
            total = page.get("total", 0)
            quotes = page.get("quotes") or []
            if not quotes:
                break
            for q in quotes:
                symbol = q.get("symbol") or ""
                if symbol.endswith(YAHOO_SUFFIX):
                    peta[symbol.removesuffix(YAHOO_SUFFIX)] = sektor_id
            offset += len(quotes)
        if progress:
            progress("sektor", i, len(SEKTOR_ID))
    return peta


def bulk_fundamentals(region: str = "id", progress: Progress | None = None) -> dict[str, dict]:
    """Fundamental dasar seluruh bursa dalam beberapa permintaan saja.

    Hasil screener Yahoo sudah memuat PER, PBV, EPS, nilai buku, kapitalisasi,
    dan dividen. Mengambilnya begini jauh lebih hemat daripada memanggil
    Ticker.info satu per satu, yang kena rate limit di sekitar emiten ke-600.
    """
    hasil = {
        row["ticker"]: normalize_quote(row["_quote"])
        for row in _screen_all(region, progress, keep_quote=True)
    }
    for ticker, sektor in bulk_sectors(region, progress).items():
        if ticker in hasil:
            hasil[ticker]["sector"] = sektor
    return hasil


def normalize_quote(q: dict) -> dict:
    """Field screener -> bentuk yang sama dengan normalize_info()."""
    eps = _num(q.get("epsTrailingTwelveMonths"))
    bvps = _num(q.get("bookValue"))
    price = _num(q.get("regularMarketPrice"))
    rate = _num(q.get("trailingAnnualDividendRate"))

    return {
        "name": _clean_name(q.get("longName") or q.get("shortName") or ""),
        "market_cap": _num(q.get("marketCap")),
        "per": _num(q.get("trailingPE")),
        "pbv": _num(q.get("priceToBook")),
        "eps": eps,
        "bvps": bvps,
        # ROE turunan: laba per saham dibagi nilai buku per saham. Perhitungan
        # resmi memakai rata-rata ekuitas, jadi angka ini pendekatan.
        "roe": (eps / bvps * 100) if eps is not None and bvps else None,
        "dividend_yield": _num(q.get("dividendYield")),
        "dividend_yield_ttm": (rate / price * 100) if rate and price else None,
        "shares_out": _num(q.get("sharesOutstanding")),
    }


def _kena_rate_limit(exc: Exception) -> bool:
    pesan = str(exc).lower()
    return "too many requests" in pesan or "rate limit" in pesan


class YahooProvider:
    def __init__(
        self,
        cache: Cache | None = None,
        *,
        offline: bool = False,
        force_refresh: bool = False,
        period: str = HISTORY_PERIOD,
    ):
        self.cache = cache or Cache()
        self.offline = offline
        self.force_refresh = force_refresh
        self.period = period
        self.errors: dict[str, str] = {}

    # ---------------- harga ----------------

    def prices(
        self, emiten: Iterable[Emiten], progress: Progress | None = None
    ) -> dict[str, pd.DataFrame]:
        emiten = list(emiten)
        stale = [e for e in emiten if self._price_is_stale(e.ticker)]

        if stale and not self.offline:
            chunks = [
                stale[i : i + DOWNLOAD_CHUNK]
                for i in range(0, len(stale), DOWNLOAD_CHUNK)
            ]
            done = 0
            for chunk in chunks:
                self._download_chunk(chunk)
                done += len(chunk)
                if progress:
                    progress("harga", done, len(stale))

        out: dict[str, pd.DataFrame] = {}
        for e in emiten:
            df = self.cache.get_prices(e.ticker)
            if not df.empty:
                out[e.ticker] = df
            elif e.ticker not in self.errors:
                self.errors[e.ticker] = "tidak ada data harga"
        return out

    def _price_is_stale(self, ticker: str) -> bool:
        if self.offline:
            return False
        if self.force_refresh:
            return True
        info = self.cache.price_fetch_info(ticker)
        if info is None:
            return True
        age, cached_period = info
        # Cache dari periode lebih pendek tidak cukup untuk permintaan yang panjang.
        if _period_days(cached_period) < _period_days(self.period):
            return True
        return age > PRICE_TTL_HOURS

    def _download_chunk(self, chunk: list[Emiten]) -> None:
        import yfinance as yf

        symbols = [e.yahoo for e in chunk]
        try:
            raw = yf.download(
                symbols,
                period=self.period,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=True,
            )
        except Exception as exc:  # jaringan putus, rate limit, dll.
            for e in chunk:
                self.errors[e.ticker] = f"unduh gagal: {exc}"
            return

        if raw is None or raw.empty:
            for e in chunk:
                self.errors[e.ticker] = "respons kosong dari Yahoo"
            return

        for e in chunk:
            df = _slice_symbol(raw, e.yahoo, len(symbols))
            if df is None or df.dropna(how="all").empty:
                self.errors[e.ticker] = "tidak ada data harga"
                self.cache.mark_price_fetch(e.ticker, self.period)
                continue
            self.cache.put_prices(e.ticker, df, self.period)

    # ---------------- fundamental ----------------

    def fundamentals(
        self,
        emiten: Iterable[Emiten],
        progress: Progress | None = None,
        deep_tickers: Iterable[str] | None = None,
    ) -> dict[str, dict]:
        """Fundamental dua lapis.

        Lapis `bulk` (PER, PBV, EPS, kapitalisasi, dividen) diambil untuk
        seluruh bursa sekaligus dan murah. Lapis `deep` (sektor, DER, margin,
        pertumbuhan) butuh satu permintaan per emiten, jadi hanya diambil untuk
        ticker yang benar-benar diminta.
        """
        emiten = list(emiten)
        diminta_deep = set(deep_tickers or ())
        perlu_bulk: list[Emiten] = []
        perlu_deep: list[Emiten] = []

        for e in emiten:
            hit = self.cache.get_fundamentals(e.ticker)
            basi = hit is None or self.force_refresh or hit[1] > FUNDAMENTAL_TTL_HOURS
            if basi:
                perlu_bulk.append(e)
            if e.ticker in diminta_deep and (basi or hit[2] != "deep"):
                perlu_deep.append(e)

        if not self.offline:
            if perlu_bulk:
                perlu_deep += self._isi_bulk(perlu_bulk, progress)
            if perlu_deep:
                self._isi_deep(perlu_deep, progress)

        hasil: dict[str, dict] = {}
        for e in emiten:
            hit = self.cache.get_fundamentals(e.ticker)
            if hit:
                hasil[e.ticker] = hit[0]
        return hasil

    def _isi_bulk(self, emiten: list[Emiten], progress: Progress | None) -> list[Emiten]:
        """Isi lapis murah; kembalikan emiten yang tidak ada di hasil screener."""
        try:
            bulk = bulk_fundamentals(progress=progress)
        except Exception as exc:
            for e in emiten:
                self.errors.setdefault(e.ticker, f"fundamental massal gagal: {exc}")
            return []

        tertinggal: list[Emiten] = []
        for i, e in enumerate(emiten, start=1):
            payload = bulk.get(e.ticker)
            if payload is None:
                # Screener Yahoo tidak selalu memuat semua emiten aktif.
                tertinggal.append(e)
                continue
            self.cache.put_fundamentals(e.ticker, payload, depth="bulk")
            if progress:
                progress("fundamental dasar", i, len(emiten))
        return tertinggal

    def _isi_deep(self, emiten: list[Emiten], progress: Progress | None) -> None:
        """Isi lapis mahal lewat Ticker.info, satu permintaan per emiten."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=FUNDAMENTAL_WORKERS) as pool:
            futures = {pool.submit(self._fetch_info, e): e for e in emiten}
            for i, fut in enumerate(as_completed(futures), start=1):
                e = futures[fut]
                try:
                    payload = fut.result()
                except Exception as exc:
                    self.errors.setdefault(e.ticker, f"fundamental rinci gagal: {exc}")
                    payload = None
                if payload:
                    self.cache.put_fundamentals(e.ticker, payload, depth="deep")
                if progress:
                    progress("fundamental rinci", i, len(emiten))

    @staticmethod
    def _fetch_info(e: Emiten) -> dict | None:
        import yfinance as yf

        terakhir: Exception | None = None
        for percobaan, jeda in enumerate((0.0, *RETRY_DELAYS)):
            if jeda:
                # Jitter supaya para pekerja tidak mengulang serentak.
                time.sleep(jeda * random.uniform(0.8, 1.3))
            try:
                info = yf.Ticker(e.yahoo).info or {}
            except Exception as exc:
                if not _kena_rate_limit(exc):
                    raise
                terakhir = exc
                continue
            if not info.get("regularMarketPrice") and not info.get("marketCap"):
                # Yahoo kadang mengembalikan stub kosong untuk emiten tidak likuid.
                if len(info) < 5:
                    return None
            return normalize_info(info)
        raise terakhir if terakhir else RuntimeError("gagal tanpa sebab jelas")


_PERIOD_DAYS = {
    "1d": 1, "5d": 5, "1mo": 30, "3mo": 91, "6mo": 182,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "ytd": 365, "max": 36500,
}


def _period_days(period: str) -> int:
    return _PERIOD_DAYS.get(period, 0)


def _slice_symbol(raw: pd.DataFrame, symbol: str, n_symbols: int) -> pd.DataFrame | None:
    """Ambil blok OHLCV satu simbol dari hasil yf.download."""
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol in raw.columns.get_level_values(0):
            return raw[symbol]
        if symbol in raw.columns.get_level_values(1):
            return raw.xs(symbol, axis=1, level=1)
        return None
    return raw if n_symbols == 1 else None


def normalize_info(info: dict) -> dict:
    """Peras dict `Ticker.info` yang gemuk menjadi field yang dipakai screener.

    Satuan diseragamkan: rasio profitabilitas & pertumbuhan dalam persen,
    DER dalam kali (x), harga dalam rupiah.
    """

    def pct(key: str) -> float | None:
        """Nilai yang dikirim Yahoo sebagai pecahan (0.21) -> persen (21.0)."""
        v = _num(info.get(key))
        return None if v is None else v * 100

    # yfinance >= 0.2.40 mengirim dividendYield dalam persen (6.02 = 6,02%),
    # versi lama mengirim pecahan. trailingAnnualDividendYield selalu pecahan,
    # jadi dipakai sebagai pembanding untuk menebak satuannya.
    div_yield = _num(info.get("dividendYield"))
    trailing_yield = _num(info.get("trailingAnnualDividendYield"))
    if (
        div_yield is not None
        and div_yield <= 1
        and trailing_yield is not None
        and abs(div_yield - trailing_yield) < 1e-6
    ):
        div_yield *= 100

    price = _num(info.get("regularMarketPrice")) or _num(info.get("currentPrice"))
    rate = _num(info.get("trailingAnnualDividendRate"))
    div_yield_ttm = (rate / price * 100) if rate and price else None

    der = _num(info.get("debtToEquity"))

    return {
        "name": _clean_name(info.get("longName") or info.get("shortName") or "") or None,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": _num(info.get("marketCap")),
        "per": _num(info.get("trailingPE")),
        "forward_per": _num(info.get("forwardPE")),
        "peg": _num(info.get("trailingPegRatio")),
        "pbv": _num(info.get("priceToBook")),
        "psr": _num(info.get("priceToSalesTrailing12Months")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        "roe": pct("returnOnEquity"),
        "roa": pct("returnOnAssets"),
        "npm": pct("profitMargins"),
        "opm": pct("operatingMargins"),
        "gpm": pct("grossMargins"),
        "der": None if der is None else der / 100,  # Yahoo kirim dalam persen
        "current_ratio": _num(info.get("currentRatio")),
        "quick_ratio": _num(info.get("quickRatio")),
        "revenue_growth": pct("revenueGrowth"),
        "earnings_growth": pct("earningsGrowth"),
        "dividend_yield": div_yield,
        "dividend_yield_ttm": div_yield_ttm,
        "payout_ratio": pct("payoutRatio"),
        "eps": _num(info.get("trailingEps")),
        "bvps": _num(info.get("bookValue")),
        "beta": _num(info.get("beta")),
        "shares_out": _num(info.get("sharesOutstanding")),
        "float_shares": _num(info.get("floatShares")),
        "total_cash": _num(info.get("totalCash")),
        "total_debt": _num(info.get("totalDebt")),
        "free_cashflow": _num(info.get("freeCashflow")),
    }


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out or out in (float("inf"), float("-inf")) else out
