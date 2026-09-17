"""Daftar emiten yang akan di-screen."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import UNIVERSE_CSV


@dataclass(frozen=True)
class Emiten:
    ticker: str          # kode 4 huruf, mis. "BBCA"
    name: str = ""
    sector: str = ""

    @property
    def yahoo(self) -> str:
        from .config import YAHOO_SUFFIX

        return f"{self.ticker}{YAHOO_SUFFIX}"


def load_universe(path: str | Path | None = None) -> list[Emiten]:
    """Baca daftar emiten dari CSV berkolom ticker,name,sector."""
    path = Path(path) if path else UNIVERSE_CSV
    if not path.exists():
        raise FileNotFoundError(f"Daftar emiten tidak ditemukan: {path}")

    out: list[Emiten] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ticker = (row.get("ticker") or "").strip().upper().removesuffix(".JK")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            out.append(
                Emiten(
                    ticker=ticker,
                    name=(row.get("name") or "").strip(),
                    sector=(row.get("sector") or "").strip(),
                )
            )
    return out


def save_universe(emiten: list[Emiten], path: str | Path | None = None) -> Path:
    path = Path(path) if path else UNIVERSE_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "name", "sector"])
        for e in sorted(emiten, key=lambda x: x.ticker):
            writer.writerow([e.ticker, e.name, e.sector])
    return path


def parse_tickers(raw: str) -> list[Emiten]:
    """Ubah "BBCA,BBRI bbni" menjadi daftar Emiten."""
    parts = [p.strip().upper().removesuffix(".JK") for p in raw.replace(",", " ").split()]
    return [Emiten(ticker=p) for p in parts if p]
