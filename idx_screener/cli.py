"""Antarmuka baris perintah: `idxscreen ...`"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel

from . import __version__
from .backtest import LookAheadError, backtest as run_backtest
from .cache import Cache
from .config import HISTORY_PERIOD, UNIVERSE_CSV
from .metrics import FIELD_DOCS
from .presets import load_presets
from .providers.yahoo import YahooProvider, bulk_sectors, list_equities
from .report import console, export, fmt, render_funnel, render_table
from .rules import RuleError
from .screener import Screener, rank_score
from .universe import Emiten, load_universe, parse_tickers, save_universe

app = typer.Typer(
    help="Screener saham Bursa Efek Indonesia (IDX). Data: Yahoo Finance.",
    no_args_is_help=True,
    add_completion=False,
)


def _build_screener(
    tickers: str | None,
    universe_file: str | None,
    offline: bool,
    refresh: bool,
    period: str = HISTORY_PERIOD,
) -> Screener:
    if tickers:
        emiten = parse_tickers(tickers)
    else:
        emiten = load_universe(universe_file)
    provider = YahooProvider(offline=offline, force_refresh=refresh, period=period)
    return Screener(provider=provider, universe=emiten)


def _progress_printer():
    """Cetak kemajuan unduhan; di luar terminal cukup satu baris per tahap."""
    state: dict[str, int] = {}
    live = console.is_terminal

    def report(tahap: str, done: int, total: int) -> None:
        if state.get(tahap) == done:
            return
        state[tahap] = done
        if live and done < total:
            console.print(f"[dim]  mengambil {tahap}: {done}/{total}[/dim]", end="\r")
        elif done >= total:
            console.print(f"[dim]  {tahap}: {total} selesai[/dim]" + " " * 12)

    return report


# --------------------------------------------------------------------------


@app.command()
def screen(
    preset: Optional[str] = typer.Option(None, "--preset", "-p", help="Nama strategi siap pakai."),
    filter_: list[str] = typer.Option([], "--filter", "-f", help="Ekspresi filter tambahan, bisa diulang."),
    sort: Optional[str] = typer.Option(None, "--sort", "-s", help="Urutkan menurut metrik ini."),
    asc: bool = typer.Option(False, "--asc", help="Urut menaik (default menurun)."),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Jumlah baris maksimum."),
    columns: Optional[str] = typer.Option(None, "--columns", "-c", help="Kolom tampil, dipisah koma."),
    tickers: Optional[str] = typer.Option(None, "--tickers", "-t", help="Batasi ke kode tertentu, mis. BBCA,TLKM."),
    universe_file: Optional[str] = typer.Option(None, "--universe", "-u", help="CSV daftar emiten sendiri."),
    export_to: Optional[str] = typer.Option(None, "--export", "-o", help="Simpan hasil ke .csv/.json/.xlsx/.md"),
    funnel: bool = typer.Option(False, "--funnel", help="Tampilkan berapa emiten gugur di tiap filter."),
    include_unknown: bool = typer.Option(False, "--include-unknown", help="Loloskan emiten yang datanya tidak lengkap."),
    max_deep: int = typer.Option(400, "--max-deep", help="Batas emiten yang ditarik data rincinya."),
    offline: bool = typer.Option(False, "--offline", help="Hanya pakai cache, tanpa jaringan."),
    refresh: bool = typer.Option(False, "--refresh", help="Paksa ambil ulang dari Yahoo."),
):
    """Jalankan screening dan tampilkan hasilnya."""
    presets = load_presets()
    chosen = None
    if preset:
        if preset not in presets:
            console.print(f"[red]Preset '{preset}' tidak ada.[/red] Tersedia: {', '.join(sorted(presets))}")
            raise typer.Exit(2)
        chosen = presets[preset]

    if not chosen and not filter_:
        console.print("[yellow]Tentukan --preset atau minimal satu --filter.[/yellow] "
                      "Lihat `idxscreen presets` dan `idxscreen fields`.")
        raise typer.Exit(2)

    screener = _build_screener(tickers, universe_file, offline, refresh)
    console.print(f"[dim]Memindai {len(screener.universe)} emiten...[/dim]")

    try:
        result = screener.run(
            preset=chosen,
            filters=list(filter_),
            sort_by=sort,
            ascending=asc if sort else None,
            limit=limit,
            columns=columns.split(",") if columns else None,
            include_unknown=include_unknown,
            max_deep=max_deep,
            progress=_progress_printer(),
        )
    except (RuleError, KeyError) as exc:
        console.print(f"[red]Filter bermasalah:[/red] {exc}")
        raise typer.Exit(2) from exc

    if chosen:
        console.print(Panel(
            f"[bold]{chosen.title}[/bold]\n{chosen.description.strip()}"
            + (f"\n\n[yellow]{chosen.note.strip()}[/yellow]" if chosen.note else ""),
            title=f"preset: {chosen.name}", border_style="cyan",
        ))

    if funnel:
        console.print(render_funnel(result.funnel, result.total_scanned))

    if result.matched.empty:
        console.print("[yellow]Tidak ada emiten yang lolos semua filter.[/yellow] "
                      "Coba longgarkan syarat atau jalankan dengan --funnel untuk melihat penyebabnya.")
    else:
        console.print(render_table(
            result.matched,
            result.columns or None,
            title=f"{len(result.matched)} dari {result.total_scanned} emiten lolos",
        ))

    if result.deep_terpotong:
        console.print(f"[yellow]{result.deep_terpotong} kandidat dilewati[/yellow] karena batas "
                      f"--max-deep {max_deep}; yang diambil adalah yang paling likuid.")
    if result.errors:
        console.print(f"[dim]{len(result.errors)} emiten dilewati (data tidak tersedia). "
                      f"Contoh: {', '.join(list(result.errors)[:6])}[/dim]")

    if export_to and not result.matched.empty:
        path = export(result.matched, export_to, result.columns or None)
        console.print(f"[green]Tersimpan:[/green] {path}")


@app.command()
def rank(
    weights: str = typer.Option(
        "roe=1,per=-1,pbv=-0.5,ret_3m=0.5,dividend_yield=0.5",
        "--weights", "-w",
        help="Bobot metrik, mis. 'roe=1,per=-1'. Negatif = makin kecil makin baik.",
    ),
    preset: Optional[str] = typer.Option(None, "--preset", "-p", help="Saring dulu dengan preset ini."),
    filter_: list[str] = typer.Option([], "--filter", "-f"),
    limit: int = typer.Option(25, "--limit", "-n"),
    tickers: Optional[str] = typer.Option(None, "--tickers", "-t"),
    universe_file: Optional[str] = typer.Option(None, "--universe", "-u"),
    export_to: Optional[str] = typer.Option(None, "--export", "-o"),
    offline: bool = typer.Option(False, "--offline"),
    refresh: bool = typer.Option(False, "--refresh"),
):
    """Beri skor gabungan 0-100 dari beberapa metrik sekaligus."""
    try:
        parsed = {
            k.strip(): float(v)
            for k, v in (pair.split("=") for pair in weights.split(","))
        }
    except ValueError as exc:
        console.print("[red]Format bobot salah.[/red] Contoh: --weights 'roe=1,per=-1'")
        raise typer.Exit(2) from exc

    unknown = set(parsed) - set(FIELD_DOCS)
    if unknown:
        console.print(f"[red]Metrik tidak dikenal:[/red] {', '.join(sorted(unknown))}")
        raise typer.Exit(2)

    screener = _build_screener(tickers, universe_file, offline, refresh)
    presets = load_presets()
    result = screener.run(
        preset=presets.get(preset) if preset else None,
        filters=list(filter_),
        limit=None,
        progress=_progress_printer(),
    )
    frame = result.matched
    if frame.empty:
        console.print("[yellow]Tidak ada emiten untuk diberi skor.[/yellow]")
        raise typer.Exit(0)

    frame = frame.copy()
    frame["skor"] = rank_score(frame, parsed)
    frame = frame.sort_values("skor", ascending=False).head(limit)
    columns = ["ticker", "name", "sector", "skor", *parsed.keys()]
    console.print(render_table(frame, columns, title=f"Peringkat gabungan ({', '.join(f'{k}:{v:g}' for k, v in parsed.items())})"))
    if export_to:
        console.print(f"[green]Tersimpan:[/green] {export(frame, export_to, columns)}")


@app.command()
def show(
    ticker: str = typer.Argument(..., help="Kode emiten, mis. BBCA"),
    offline: bool = typer.Option(False, "--offline"),
    refresh: bool = typer.Option(False, "--refresh"),
):
    """Tampilkan seluruh metrik satu emiten."""
    screener = _build_screener(ticker, None, offline, refresh)
    kode = {e.ticker for e in screener.universe}
    # Untuk satu emiten, data rinci selalu layak ditarik.
    frame = screener.snapshot(_progress_printer(), deep_tickers=kode)
    if frame.empty:
        console.print(f"[red]Data untuk {ticker.upper()} tidak tersedia.[/red]")
        for code, message in screener.provider.errors.items():
            console.print(f"[dim]{code}: {message}[/dim]")
        raise typer.Exit(1)

    row = frame.iloc[0]
    from rich.table import Table

    table = Table(title=f"{row['ticker']} - {row['name'] or '-'}", title_style="bold", header_style="bold cyan")
    table.add_column("Metrik")
    table.add_column("Nilai", justify="right")
    table.add_column("Keterangan", style="dim", overflow="fold")
    for key, doc in FIELD_DOCS.items():
        if key in row.index:
            table.add_row(key, fmt(row[key], key), doc)
    console.print(table)


@app.command()
def backtest(
    preset: Optional[str] = typer.Option(None, "--preset", "-p"),
    filter_: list[str] = typer.Option([], "--filter", "-f"),
    periods: int = typer.Option(12, "--periods", help="Jumlah tanggal rebalancing."),
    step: int = typer.Option(21, "--step", help="Jarak antar rebalancing (hari bursa)."),
    hold: int = typer.Option(21, "--hold", help="Lama posisi ditahan (hari bursa)."),
    top: int = typer.Option(10, "--top", help="Ambil berapa saham teratas tiap periode."),
    sort: Optional[str] = typer.Option(None, "--sort", "-s"),
    asc: bool = typer.Option(False, "--asc"),
    allow_fundamentals: bool = typer.Option(False, "--allow-fundamentals", help="Izinkan filter fundamental meski bias."),
    tickers: Optional[str] = typer.Option(None, "--tickers", "-t"),
    universe_file: Optional[str] = typer.Option(None, "--universe", "-u"),
    export_to: Optional[str] = typer.Option(None, "--export", "-o"),
    offline: bool = typer.Option(False, "--offline"),
):
    """Uji strategi berbasis harga ke data historis (perkiraan kasar)."""
    presets = load_presets()
    filters = list(filter_)
    chosen = presets.get(preset) if preset else None
    if preset and not chosen:
        console.print(f"[red]Preset '{preset}' tidak ada.[/red]")
        raise typer.Exit(2)
    if chosen:
        filters = list(chosen.filters) + filters
        sort = sort or chosen.sort_by
        asc = chosen.ascending if sort == chosen.sort_by else asc
    if not filters:
        console.print("[yellow]Tentukan --preset atau --filter.[/yellow]")
        raise typer.Exit(2)

    screener = _build_screener(tickers, universe_file, offline, False, period="5y")
    console.print(f"[dim]Menyiapkan data {len(screener.universe)} emiten...[/dim]")
    try:
        result = run_backtest(
            screener, filters, periods=periods, step_days=step, hold_days=hold,
            top_n=top, sort_by=sort, ascending=asc, allow_fundamentals=allow_fundamentals,
        )
    except LookAheadError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if result.periods.empty:
        console.print("[yellow]Tidak ada periode dengan saham terpilih.[/yellow]")
        raise typer.Exit(0)

    console.print(render_table(
        result.periods,
        ["tanggal", "terpilih", "return_strategi", "return_pasar", "selisih", "win_rate"],
        title=f"Backtest per periode (tahan {hold} hari bursa)",
    ))
    lines = "\n".join(f"{k.replace('_', ' ')}: [bold]{v}[/bold]" for k, v in result.summary.items())
    console.print(Panel(lines, title="Ringkasan", border_style="cyan"))
    console.print("[dim]Backtest ini mengabaikan biaya transaksi, slippage, dividen, "
                  "dan bias survivorship (emiten delisting tidak ikut terhitung).[/dim]")
    if export_to:
        console.print(f"[green]Tersimpan:[/green] {export(result.trades, export_to)}")


@app.command()
def presets():
    """Daftar strategi siap pakai."""
    from rich.table import Table

    table = Table(title="Preset tersedia", header_style="bold cyan", title_style="bold")
    table.add_column("Nama", style="bold")
    table.add_column("Judul")
    table.add_column("Filter", style="dim", overflow="fold")
    for name, preset in sorted(load_presets().items()):
        table.add_row(name, preset.title, "; ".join(preset.filters))
    console.print(table)
    console.print("[dim]File preset bisa disalin/diubah di idx_screener/presets/*.yaml[/dim]")


@app.command()
def fields(search: Optional[str] = typer.Argument(None, help="Saring nama metrik.")):
    """Daftar metrik yang bisa dipakai di filter."""
    from rich.table import Table

    table = Table(title="Metrik yang tersedia", header_style="bold cyan", title_style="bold")
    table.add_column("Nama", style="bold")
    table.add_column("Arti", overflow="fold")
    for key, doc in FIELD_DOCS.items():
        if not search or search.lower() in key.lower() or search.lower() in doc.lower():
            table.add_row(key, doc)
    console.print(table)


@app.command()
def update(
    universe_file: Optional[str] = typer.Option(None, "--universe", "-u"),
    tickers: Optional[str] = typer.Option(None, "--tickers", "-t"),
    deep: int = typer.Option(
        300, "--deep",
        help="Berapa emiten paling likuid yang juga ditarik data rincinya (0 = tidak ada).",
    ),
):
    """Ambil ulang harga dan fundamental ke cache.

    Fundamental dasar (PER, PBV, ROE, kapitalisasi, dividen) diambil untuk
    seluruh daftar sekaligus lewat screener Yahoo. Data rinci (DER, margin,
    pertumbuhan) butuh satu permintaan per emiten, jadi dibatasi ke emiten
    paling likuid agar tidak kena rate limit.
    """
    screener = _build_screener(tickers, universe_file, False, True)
    frame = screener.snapshot(_progress_printer())
    console.print(f"[green]Harga & fundamental dasar:[/green] {len(frame)} emiten.")

    if deep and not frame.empty:
        terpilih = frame.nlargest(min(deep, len(frame)), "avg_value_20")["ticker"]
        screener.provider.force_refresh = False
        screener.provider.fundamentals(
            [Emiten(ticker=t) for t in terpilih],
            _progress_printer(),
            deep_tickers=set(terpilih),
        )
        console.print(f"[green]Fundamental rinci:[/green] {len(terpilih)} emiten paling likuid.")

    gagal = screener.provider.errors
    if gagal:
        console.print(f"[yellow]{len(gagal)} emiten bermasalah:[/yellow] "
                      + ", ".join(list(gagal)[:10]) + (" ..." if len(gagal) > 10 else ""))


@app.command("sync-universe")
def sync_universe(
    universe_file: Optional[str] = typer.Option(None, "--universe", "-u"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Tulis ke file lain."),
):
    """Perbarui nama dan sektor emiten pada CSV daftar emiten dari Yahoo."""
    emiten = load_universe(universe_file)
    provider = YahooProvider(force_refresh=True)
    data = provider.fundamentals(emiten, _progress_printer())
    updated = [
        Emiten(
            ticker=e.ticker,
            name=(data.get(e.ticker, {}).get("name") or e.name),
            sector=(data.get(e.ticker, {}).get("sector") or e.sector),
        )
        for e in emiten
    ]
    path = save_universe(updated, output or universe_file)
    console.print(f"[green]Daftar emiten diperbarui:[/green] {path} ({len(updated)} baris)")
    if provider.errors:
        console.print(f"[yellow]Tidak terjawab:[/yellow] {', '.join(list(provider.errors)[:10])}")


@app.command("fetch-universe")
def fetch_universe(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Berkas tujuan (default: daftar bawaan)."),
    prune: bool = typer.Option(False, "--prune", help="Buang emiten lama yang tidak ada di hasil screener."),
):
    """Ambil daftar emiten IDX dari screener Yahoo dan gabungkan ke CSV.

    Screener Yahoo tidak selalu lengkap - beberapa emiten yang masih aktif
    (ADHI, WIKA, ...) pernah absen dari hasilnya. Karena itu daftar lama
    dipertahankan secara bawaan, dan hanya dibuang bila diminta --prune.
    """
    path = Path(output) if output else UNIVERSE_CSV
    lama: dict[str, Emiten] = {e.ticker: e for e in load_universe(path)} if path.exists() else {}

    hasil = list_equities(progress=_progress_printer())
    if not hasil:
        console.print("[red]Screener Yahoo tidak mengembalikan apa pun.[/red] Coba lagi nanti.")
        raise typer.Exit(1)

    dari_screener = {row["ticker"]: row for row in hasil}
    gabungan: dict[str, Emiten] = {}

    for ticker, row in dari_screener.items():
        sebelumnya = lama.get(ticker)
        gabungan[ticker] = Emiten(
            ticker=ticker,
            name=(sebelumnya.name if sebelumnya and sebelumnya.name else row["name"]),
            sector=(sebelumnya.sector if sebelumnya else ""),
        )

    sektor = bulk_sectors(progress=_progress_printer())
    for ticker, emiten_baru in gabungan.items():
        if not emiten_baru.sector and ticker in sektor:
            gabungan[ticker] = Emiten(ticker, emiten_baru.name, sektor[ticker])

    tidak_terdaftar = sorted(set(lama) - set(dari_screener))
    if not prune:
        for ticker in tidak_terdaftar:
            gabungan[ticker] = lama[ticker]

    baru = sorted(set(dari_screener) - set(lama))
    save_universe(list(gabungan.values()), path)

    console.print(f"[green]Tersimpan:[/green] {path} ({len(gabungan)} emiten)")
    if baru:
        console.print(f"[cyan]{len(baru)} emiten baru:[/cyan] " + ", ".join(baru[:15])
                      + (" ..." if len(baru) > 15 else ""))
    if tidak_terdaftar:
        aksi = "dibuang" if prune else "dipertahankan"
        console.print(f"[yellow]{len(tidak_terdaftar)} tidak muncul di screener, {aksi}:[/yellow] "
                      + ", ".join(tidak_terdaftar[:15]) + (" ..." if len(tidak_terdaftar) > 15 else ""))
    berlabel = sum(1 for e in gabungan.values() if e.sector)
    console.print(f"[dim]Sektor terisi untuk {berlabel} dari {len(gabungan)} emiten.[/dim]")


@app.command()
def cache(
    clear: bool = typer.Option(False, "--clear", help="Kosongkan cache."),
):
    """Informasi cache lokal."""
    store = Cache()
    if clear:
        store.clear()
        console.print("[green]Cache dikosongkan.[/green]")
    stats = store.stats()
    console.print(Panel(
        "\n".join(f"{k}: [bold]{v}[/bold]" for k, v in stats.items()),
        title="Cache", border_style="cyan",
    ))


@app.command()
def version():
    """Tampilkan versi."""
    console.print(f"idx-screener {__version__}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
