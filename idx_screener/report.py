"""Penyajian hasil: tabel terminal, CSV, JSON, dan Markdown."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

# Kolom yang ditampilkan sebagai persen.
PERCENT_COLUMNS = {
    "change_pct", "roe", "roa", "npm", "opm", "gpm", "revenue_growth",
    "earnings_growth", "dividend_yield", "dividend_yield_ttm", "payout_ratio", "dist_sma20",
    "dist_sma50", "dist_sma200", "dist_52w_high", "dist_52w_low", "atr_pct",
    "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y", "ret_ytd",
    "volatility_1y", "max_drawdown_1y", "up_days_1m", "fwd_return",
    "ara_limit", "dist_ara",
    "return_strategi", "return_pasar", "selisih", "win_rate",
}
# Kolom yang selalu bilangan bulat.
INT_COLUMNS = {"terpilih", "data_points", "stale_days", "lolos", "gugur"}
# Kolom nominal besar (rupiah atau lembar saham).
BIG_COLUMNS = {
    "market_cap", "avg_value_20", "value_traded", "volume", "avg_volume_20",
    "shares_out", "float_shares", "total_cash", "total_debt", "free_cashflow",
}
# Kolom harga.
PRICE_COLUMNS = {
    "close", "prev_close", "sma20", "sma50", "sma200", "ema9", "high_52w",
    "low_52w", "bb_upper", "bb_lower", "atr14", "eps", "bvps",
}
# Kolom yang diwarnai hijau/merah sesuai tanda.
SIGNED_COLUMNS = {
    "change_pct", "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y", "ret_ytd",
    "dist_52w_high", "dist_sma20", "dist_sma50", "dist_sma200", "macd_hist",
    "earnings_growth", "revenue_growth", "fwd_return",
}

# Kolom teks; sisanya diratakan ke kanan sebagai angka.
TEXT_COLUMNS = {"ticker", "name", "sector", "industry", "last_date", "tanggal", "filter", "metrik"}

HEADERS = {
    "ticker": "Kode", "name": "Nama", "sector": "Sektor", "industry": "Sub-industri",
    "close": "Harga", "change_pct": "% Hari", "market_cap": "Kap. Pasar",
    "avg_value_20": "Nilai/hari", "value_traded": "Nilai", "volume": "Volume",
    "dividend_yield": "Div Yield", "volume_ratio": "Vol x", "per": "PER",
    "pbv": "PBV", "roe": "ROE", "der": "DER", "rsi14": "RSI",
}


def fmt(value, column: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if isinstance(value, bool):
        return "ya" if value else "-"
    if hasattr(value, "item") and not isinstance(value, str):
        value = value.item()  # numpy int64/float64 -> tipe Python
    if isinstance(value, str):
        return value
    if not isinstance(value, (int, float)):
        return str(value)
    if column in INT_COLUMNS:
        return f"{int(round(value)):,}".replace(",", ".")
    if column in PERCENT_COLUMNS:
        return f"{value:,.2f}%".replace(",", "@").replace(".", ",").replace("@", ".")
    if column in BIG_COLUMNS:
        return compact(value)
    if column in PRICE_COLUMNS:
        return f"{value:,.0f}".replace(",", ".") if abs(value) >= 100 else f"{value:,.2f}".replace(".", ",")
    return f"{value:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def compact(value: float) -> str:
    """1.2e12 -> '1,20 T' (satuan Indonesia: T/M/jt/rb)."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    for limit, suffix in ((1e12, " T"), (1e9, " M"), (1e6, " jt"), (1e3, " rb")):
        if value >= limit:
            return f"{sign}{value / limit:,.2f}".replace(".", ",") + suffix
    return f"{sign}{value:,.0f}"


def render_table(
    frame: pd.DataFrame,
    columns: list[str] | None = None,
    title: str = "",
    max_rows: int | None = None,
) -> Table:
    columns = [c for c in (columns or list(frame.columns)) if c in frame.columns]
    table = Table(title=title or None, header_style="bold cyan", title_style="bold")
    table.add_column("#", justify="right", style="dim")
    for column in columns:
        justify = "left" if column in TEXT_COLUMNS else "right"
        table.add_column(HEADERS.get(column, column), justify=justify, no_wrap=(column != "name"))

    view = frame.head(max_rows) if max_rows else frame
    for i, (_, row) in enumerate(view.iterrows(), start=1):
        cells = [str(i)]
        for column in columns:
            text = fmt(row[column], column)
            value = row[column]
            if column in SIGNED_COLUMNS and isinstance(value, (int, float)) and not isinstance(value, bool) and not pd.isna(value):
                color = "green" if value > 0 else "red" if value < 0 else ""
                text = f"[{color}]{text}[/{color}]" if color else text
            elif column == "ticker":
                text = f"[bold]{text}[/bold]"
            cells.append(text)
        table.add_row(*cells)
    return table


def render_funnel(funnel: list[dict], total: int) -> Table:
    table = Table(title="Corong filter", header_style="bold cyan", title_style="bold")
    table.add_column("Filter", overflow="fold")
    table.add_column("Lolos", justify="right")
    table.add_column("Gugur", justify="right")
    table.add_column("Data kosong", justify="right")
    table.add_row("[dim]semua emiten[/dim]", str(total), "-", "-")
    for step in funnel:
        table.add_row(step["filter"], str(step["lolos"]), str(step["gugur"]), str(step["data_kosong"]))
    return table


def export(frame: pd.DataFrame, path: str | Path, columns: list[str] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    view = frame[[c for c in columns if c in frame.columns]] if columns else frame
    suffix = path.suffix.lower()
    if suffix == ".csv":
        view.to_csv(path, index=False)
    elif suffix == ".json":
        path.write_text(
            json.dumps(view.to_dict(orient="records"), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    elif suffix in {".xlsx", ".xls"}:
        view.to_excel(path, index=False)
    elif suffix == ".md":
        path.write_text(view.to_markdown(index=False), encoding="utf-8")
    else:
        raise ValueError(f"Format ekspor tidak didukung: {suffix} (pakai .csv/.json/.xlsx/.md)")
    return path
