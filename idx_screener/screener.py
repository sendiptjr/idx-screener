"""Mesin screening: ambil data -> hitung metrik -> terapkan filter."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import pandas as pd

from .metrics import DEEP_FIELDS, FIELD_DOCS, build_row
from .presets import Preset
from .providers.yahoo import YahooProvider
from .rules import Rule, compile_rules, unknown_fields
from .universe import Emiten, load_universe

Progress = Callable[[str, int, int], None]


@dataclass
class ScreenResult:
    snapshot: pd.DataFrame          # semua emiten beserta metriknya
    matched: pd.DataFrame           # yang lolos filter, sudah diurutkan
    funnel: list[dict] = field(default_factory=list)   # sisa emiten per filter
    unknown: pd.DataFrame | None = None                # gugur karena data kosong
    errors: dict[str, str] = field(default_factory=dict)
    filters: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    deep_diambil: int = 0          # berapa emiten yang ditarik data rincinya
    deep_terpotong: int = 0        # berapa kandidat dilewati karena batas

    @property
    def total_scanned(self) -> int:
        return len(self.snapshot)


class Screener:
    def __init__(
        self,
        provider: YahooProvider | None = None,
        universe: Iterable[Emiten] | None = None,
    ):
        self.provider = provider or YahooProvider()
        self.universe = list(universe) if universe is not None else load_universe()

    # ---------------- data ----------------

    def snapshot(
        self,
        progress: Progress | None = None,
        *,
        asof: pd.Timestamp | None = None,
        only: set[str] | None = None,
        deep_tickers: set[str] | None = None,
    ) -> pd.DataFrame:
        """Satu baris metrik per emiten.

        `only` membatasi ke sebagian emiten, `deep_tickers` meminta data
        fundamental rinci untuk ticker tertentu saja.
        """
        emiten = [e for e in self.universe if only is None or e.ticker in only]
        prices = self.provider.prices(emiten, progress)
        fundamentals = self.provider.fundamentals(emiten, progress, deep_tickers=deep_tickers)

        rows = []
        for e in emiten:
            df = prices.get(e.ticker)
            if df is None or df.empty:
                continue
            row = build_row(e, df, fundamentals.get(e.ticker), asof=asof)
            if row is None:
                self.provider.errors.setdefault(e.ticker, "riwayat harga terlalu pendek")
                continue
            rows.append(row)

        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.set_index("ticker", drop=False)
        return frame

    # ---------------- screening ----------------

    def run(
        self,
        *,
        preset: Preset | None = None,
        filters: list[str] | None = None,
        sort_by: str | None = None,
        ascending: bool | None = None,
        limit: int | None = None,
        columns: list[str] | None = None,
        include_unknown: bool = False,
        max_deep: int = 400,
        snapshot: pd.DataFrame | None = None,
        progress: Progress | None = None,
    ) -> ScreenResult:
        expressions = list(filters or [])
        if preset:
            expressions = list(preset.filters) + expressions
            sort_by = sort_by or preset.sort_by
            ascending = preset.ascending if ascending is None else ascending
            limit = preset.limit if limit is None else limit
            columns = columns or preset.columns

        frame = self.snapshot(progress) if snapshot is None else snapshot
        result = ScreenResult(
            snapshot=frame,
            matched=frame,
            errors=dict(self.provider.errors),
            filters=expressions,
            columns=columns or [],
        )
        if frame.empty:
            result.matched = frame
            return result

        rules = compile_rules(expressions)
        missing = unknown_fields(rules, set(frame.columns) | set(FIELD_DOCS))
        if missing:
            raise KeyError(
                "Metrik tidak dikenal: " + ", ".join(sorted(missing))
                + ". Jalankan `idxscreen fields` untuk daftar lengkap."
            )

        # Aturan yang menyentuh metrik mahal ditunda: saring dulu dengan data
        # murah, baru tarik Ticker.info untuk kandidat yang tersisa.
        murah = [r for r in rules if not (r.fields & DEEP_FIELDS)]
        mahal = [r for r in rules if r.fields & DEEP_FIELDS]

        current = frame
        unknown_rows: dict[str, pd.DataFrame] = {}

        current = self._terapkan(murah, current, result, unknown_rows, include_unknown)

        if mahal and not current.empty:
            kandidat = set(current["ticker"])
            if len(kandidat) > max_deep:
                terpilih = current.nlargest(max_deep, "avg_value_20")
                result.deep_terpotong = len(kandidat) - len(terpilih)
                kandidat = set(terpilih["ticker"])
                current = terpilih
            result.deep_diambil = len(kandidat)
            rinci = self.snapshot(progress, only=kandidat, deep_tickers=kandidat)
            if not rinci.empty:
                current = rinci
            current = self._terapkan(mahal, current, result, unknown_rows, include_unknown)

        if unknown_rows:
            result.unknown = pd.concat(unknown_rows.values()).drop_duplicates(subset="ticker")
        result.errors = dict(self.provider.errors)

        current = _sort(current, sort_by, bool(ascending))
        if limit:
            current = current.head(limit)
        result.matched = current
        return result


    def _terapkan(
        self,
        rules: list[Rule],
        frame: pd.DataFrame,
        result: ScreenResult,
        unknown_rows: dict[str, pd.DataFrame],
        include_unknown: bool,
    ) -> pd.DataFrame:
        """Jalankan sederet aturan dan catat corongnya."""
        for rule in rules:
            if frame.empty:
                break
            verdicts = frame.apply(lambda r, rule=rule: rule.evaluate(r.to_dict()), axis=1)
            passed = verdicts.map(lambda v: v is True)
            undecided = verdicts.map(lambda v: v is None)
            if include_unknown:
                passed = passed | undecided
            elif undecided.any():
                unknown_rows[rule.expression] = frame[undecided]
            result.funnel.append({
                "filter": rule.expression,
                "lolos": int(passed.sum()),
                "gugur": int((~passed).sum()),
                "data_kosong": int(undecided.sum()),
            })
            frame = frame[passed]
        return frame


def _sort(frame: pd.DataFrame, sort_by: str | None, ascending: bool) -> pd.DataFrame:
    if frame.empty or not sort_by or sort_by not in frame.columns:
        return frame
    return frame.sort_values(sort_by, ascending=ascending, na_position="last")


def rank_score(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Skor gabungan 0-100 dari beberapa metrik.

    Bobot positif berarti "makin besar makin baik", negatif sebaliknya.
    Tiap metrik diubah ke peringkat persentil dulu supaya satuannya setara.
    """
    total = 0.0
    score = pd.Series(0.0, index=frame.index)
    for column, weight in weights.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().sum() < 2:
            continue
        pct = values.rank(pct=True, na_option="keep")
        if weight < 0:
            pct = 1 - pct
        score = score.add(pct.fillna(0.5) * abs(weight), fill_value=0)
        total += abs(weight)
    return (score / total * 100).round(1) if total else score
