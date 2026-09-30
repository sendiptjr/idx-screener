"""Antarmuka web screener IDX.

Jalankan: streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from idx_screener import indicators as ind
from idx_screener.config import PRICE_TTL_HOURS
from idx_screener.metrics import FIELD_DOCS, NUMERIC_FIELDS
from idx_screener.news import ambil_berita, cocokkan, jendela_semalam
from idx_screener.presets import load_presets
from idx_screener.report import fmt
from idx_screener.providers.yahoo import YahooProvider
from idx_screener.rules import RuleError
from idx_screener.screener import Screener, rank_score
from idx_screener.universe import load_universe

st.set_page_config(page_title="Screener Saham IDX", page_icon="📈", layout="wide")

PRESETS = load_presets()
UNIVERSE = load_universe()

# Cache Streamlit tidak boleh menahan lebih lama daripada cache harga di
# bawahnya, kalau tidak kedua lapis saling menambah dan harga bisa tertinggal
# berjam-jam. Atur keduanya sekaligus lewat IDX_SCREENER_PRICE_TTL.
CACHE_TTL = min(3600, int(PRICE_TTL_HOURS * 3600))


@st.cache_data(show_spinner=False, ttl=CACHE_TTL)
def get_snapshot(refresh: bool, offline: bool) -> tuple[pd.DataFrame, dict]:
    provider = YahooProvider(offline=offline, force_refresh=refresh)
    screener = Screener(provider=provider, universe=UNIVERSE)
    frame = screener.snapshot()
    return frame, dict(provider.errors)


@st.cache_data(show_spinner=False, ttl=CACHE_TTL)
def get_prices(ticker: str) -> pd.DataFrame:
    from idx_screener.universe import Emiten

    provider = YahooProvider()
    return provider.prices([Emiten(ticker=ticker)]).get(ticker, pd.DataFrame())


# Jendela berita bergeser tiap menit sebelum pukul 08.00, jadi yang dijadikan
# kunci cache adalah jam-jamnya, bukan stempel waktunya; TTL menahan agar
# berita baru tetap masuk.
@st.cache_data(show_spinner=False, ttl=1800)
def get_berita(jam_mulai: int, jam_selesai: int) -> tuple[pd.DataFrame, list[str], str]:
    """Emiten yang disebut berita semalam: (tabel sebutan, laporan sumber, rentang)."""
    mulai, selesai = jendela_semalam(jam_mulai=jam_mulai, jam_selesai=jam_selesai)
    laporan: list[str] = []
    berita = ambil_berita(mulai, selesai, laporan=laporan)
    sebutan = cocokkan(berita, UNIVERSE)
    tabel = pd.DataFrame([
        {
            "ticker": s.ticker,
            "name": s.nama,
            "jumlah_berita": len(s.berita),
            "judul": " · ".join(b.judul for b in s.berita[:3]),
            "tautan": s.berita[0].tautan if s.berita else "",
        }
        for s in sebutan
    ], columns=["ticker", "name", "jumlah_berita", "judul", "tautan"])
    rentang = f"{mulai:%d %b %H.%M} - {selesai:%d %b %H.%M} WIB · {len(berita)} berita"
    return tabel, laporan, rentang


def bubble_sizes(market_cap: pd.Series, low: int = 10, high: int = 44) -> pd.Series:
    """Ubah kapitalisasi pasar jadi diameter titik 10-44 piksel."""
    scaled = market_cap.astype(float).pow(0.25)
    if scaled.notna().sum() < 2 or scaled.max() == scaled.min():
        return pd.Series(low + (high - low) / 2, index=market_cap.index)
    normalized = (scaled - scaled.min()) / (scaled.max() - scaled.min())
    return (low + normalized.fillna(0) * (high - low)).clip(low, high)


def rupiah(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    for limit, suffix in ((1e12, " T"), (1e9, " M"), (1e6, " jt")):
        if abs(value) >= limit:
            return f"Rp {value / limit:,.2f}{suffix}".replace(",", "#").replace(".", ",").replace("#", ".")
    return f"Rp {value:,.0f}".replace(",", ".")


# ----------------------------- sidebar -----------------------------

st.sidebar.title("📈 Screener Saham IDX")
st.sidebar.caption(f"{len(UNIVERSE)} emiten · data Yahoo Finance")

TANPA_PRESET = "(tanpa preset)"
BY_TITLE = {p.title: p for p in PRESETS.values()}

preset_title = st.sidebar.selectbox("Strategi", [TANPA_PRESET] + sorted(BY_TITLE), key="preset")
preset = BY_TITLE.get(preset_title)

FILTER_BAWAAN = "avg_value_20 > 5e9\nper > 0 and per < 15"

# Widget ber-key mengabaikan argumen `value` setelah render pertama, jadi isinya
# ditulis ulang lewat session_state setiap kali preset berganti.
if st.session_state.get("_preset_aktif") != preset_title:
    st.session_state["_preset_aktif"] = preset_title
    st.session_state["filters"] = "\n".join(preset.filters) if preset else FILTER_BAWAAN
    st.session_state["sort_by"] = (
        preset.sort_by if preset and preset.sort_by in NUMERIC_FIELDS else "avg_value_20"
    )
    st.session_state["ascending"] = bool(preset.ascending) if preset else False
    st.session_state["limit"] = int(preset.limit or 30) if preset else 30

filter_text = st.sidebar.text_area(
    "Filter (satu ekspresi per baris)", height=180, key="filters",
    help="Contoh: close > sma200 · rsi14 between 40 and 60 · sector in ['Keuangan']",
)

sectors = sorted({e.sector for e in UNIVERSE if e.sector})
picked_sectors = st.sidebar.multiselect("Batasi sektor", sectors, key="sektor")

sort_by = st.sidebar.selectbox("Urutkan menurut", NUMERIC_FIELDS, key="sort_by")
ascending = st.sidebar.checkbox("Urut menaik", key="ascending")
limit = st.sidebar.slider("Jumlah baris", 5, 200, step=5, key="limit")
include_unknown = st.sidebar.checkbox("Loloskan emiten dengan data tidak lengkap", value=False)
max_deep = st.sidebar.slider(
    "Batas penarikan data rinci", 50, 600, 200, step=50, key="max_deep",
    help="Metrik seperti DER, margin, dan pertumbuhan butuh satu permintaan per emiten. "
         "Batas ini menahan berapa kandidat yang ditarik setelah saringan murah.",
)

st.sidebar.divider()
pakai_berita = st.sidebar.checkbox(
    "Hanya emiten yang disebut berita semalam", key="pakai_berita",
    help="Saringan di atas hanya diterapkan ke emiten yang muncul di berita pasar "
         "sejak sore hari bursa sebelumnya. Sebutan berita tidak punya pengukuran "
         "di belakangnya - perlakukan sebagai informasi, bukan sinyal.",
)
jam_a, jam_b = st.sidebar.columns(2)
jam_dari = jam_a.number_input(
    "Berita dari jam", 0, 23, 15, key="jam_dari", disabled=not pakai_berita,
    help="Jam WIB pada hari bursa sebelumnya.",
)
jam_sampai = jam_b.number_input(
    "sampai jam", 0, 23, 8, key="jam_sampai", disabled=not pakai_berita,
    help="Jam WIB hari ini.",
)
if pakai_berita and st.sidebar.button("Ambil ulang berita", width="stretch"):
    get_berita.clear()

col_a, col_b = st.sidebar.columns(2)
offline = col_a.checkbox("Offline", value=False, help="Hanya baca cache lokal.")
if col_b.button("Muat ulang data", width="stretch"):
    get_snapshot.clear()
    get_prices.clear()
    st.session_state["refresh"] = True

refresh = st.session_state.pop("refresh", False)

# ----------------------------- data -----------------------------

with st.spinner("Mengambil data harga dan fundamental..."):
    snapshot, errors = get_snapshot(refresh, offline)

if snapshot.empty:
    st.error("Tidak ada data. Jalankan `idxscreen update` lebih dulu atau matikan mode offline.")
    st.stop()

berita = None
if pakai_berita:
    try:
        with st.spinner("Mengambil berita semalam..."):
            berita, laporan_berita, rentang_berita = get_berita(int(jam_dari), int(jam_sampai))
    except Exception as exc:
        st.error(f"Gagal mengambil berita: {exc}")
        st.stop()
    # Saringan tetap dijalankan lewat Screener; yang dipersempit hanya
    # emiten yang diperiksanya.
    snapshot = snapshot[snapshot.index.isin(berita["ticker"])]
    if snapshot.empty:
        st.warning(f"Tidak ada emiten yang disebut berita ({rentang_berita}).")
        st.stop()

expressions = [line.strip() for line in filter_text.splitlines() if line.strip()]
if picked_sectors:
    expressions.append("sector in " + repr(picked_sectors))

# Provider di sini mengikuti tombol Offline: filter yang menyentuh metrik lapis
# rinci (DER, margin, pertumbuhan) perlu menarik Ticker.info untuk kandidat yang
# lolos saringan murah. Hasilnya mengendap di cache SQLite, jadi hanya lambat
# sekali per emiten per hari.
screener = Screener(provider=YahooProvider(offline=offline), universe=UNIVERSE)
try:
    with st.spinner("Menerapkan filter..."):
        result = screener.run(
            filters=expressions, sort_by=sort_by, ascending=ascending, limit=limit,
            include_unknown=include_unknown, snapshot=snapshot, max_deep=max_deep,
        )
except (RuleError, KeyError) as exc:
    st.error(f"Filter bermasalah: {exc}")
    st.stop()

matched = result.matched
if berita is not None and not matched.empty:
    per_ticker = berita.set_index("ticker")
    matched = matched.assign(
        jumlah_berita=matched["ticker"].map(per_ticker["jumlah_berita"]),
        judul=matched["ticker"].map(per_ticker["judul"]),
    )

# ----------------------------- header -----------------------------

st.title(preset.title if preset else "Screening khusus")
if preset:
    st.caption(preset.description)
    if preset.note:
        st.warning(preset.note)
if berita is not None:
    st.info(
        f"Dibatasi ke {len(berita)} emiten yang disebut berita semalam ({rentang_berita}). "
        "Sebutan berita tidak punya pengukuran di belakangnya dan pencocokannya bisa keliru "
        "(misalnya \"Matahari\" di berita astronomi) - periksa judulnya."
    )

m1, m2, m3, m4 = st.columns(4)
m1.metric("Emiten dipindai", result.total_scanned)
m2.metric("Lolos filter", len(matched))
m3.metric("Data per", snapshot["last_date"].max())
m4.metric(
    "Rata-rata return 1 bulan",
    f"{matched['ret_1m'].mean():.2f}%" if not matched.empty and matched["ret_1m"].notna().any() else "-",
)

if matched.empty:
    st.warning("Tidak ada emiten yang lolos. Longgarkan syarat, atau lihat corong filter di bawah.")
else:
    display_columns = [c for c in (preset.columns if preset else []) if c in matched.columns]
    if not display_columns:
        display_columns = ["ticker", "name", "sector", "close", "change_pct", "per", "pbv", "roe", "avg_value_20"]
    if sort_by not in display_columns:
        display_columns.append(sort_by)
    if berita is not None:
        display_columns += ["jumlah_berita", "judul"]

    st.dataframe(
        matched[display_columns],
        width="stretch",
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Kode"),
            "name": st.column_config.TextColumn("Nama", width="medium"),
            "close": st.column_config.NumberColumn("Harga", format="%.0f"),
            "change_pct": st.column_config.NumberColumn("% Hari", format="%.2f%%"),
            "market_cap": st.column_config.NumberColumn("Kap. Pasar", format="compact"),
            "avg_value_20": st.column_config.NumberColumn("Nilai/hari", format="compact"),
            "jumlah_berita": st.column_config.NumberColumn("Berita", format="%d"),
            "judul": st.column_config.TextColumn("Judul berita", width="large"),
        },
    )
    st.download_button(
        "Unduh CSV",
        matched[display_columns].to_csv(index=False).encode("utf-8"),
        file_name="screening-idx.csv",
        mime="text/csv",
    )

if result.deep_diambil:
    pesan = f"{result.deep_diambil} kandidat ditarik data rincinya (DER, margin, pertumbuhan)."
    if result.deep_terpotong:
        pesan += f" {result.deep_terpotong} lainnya dilewati karena batas {max_deep}."
    st.caption(pesan)

with st.expander("Corong filter - berapa emiten gugur di tiap syarat"):
    st.dataframe(
        pd.DataFrame([{"filter": "semua emiten", "lolos": result.total_scanned, "gugur": 0, "data_kosong": 0}] + result.funnel),
        width="stretch", hide_index=True,
    )
    if errors:
        st.caption(f"{len(errors)} emiten dilewati: " + ", ".join(list(errors)[:20]))

if berita is not None:
    with st.expander(f"Semua emiten yang disebut berita semalam ({len(berita)})"):
        lolos = set(matched["ticker"]) if not matched.empty else set()
        semua = berita.assign(lolos=berita["ticker"].isin(lolos))
        st.dataframe(
            semua[["ticker", "name", "lolos", "jumlah_berita", "judul", "tautan"]],
            width="stretch", hide_index=True,
            column_config={
                "ticker": st.column_config.TextColumn("Kode"),
                "name": st.column_config.TextColumn("Nama", width="medium"),
                "lolos": st.column_config.CheckboxColumn("Lolos filter"),
                "jumlah_berita": st.column_config.NumberColumn("Berita", format="%d"),
                "judul": st.column_config.TextColumn("Judul berita", width="large"),
                "tautan": st.column_config.LinkColumn("Tautan", display_text="buka"),
            },
        )
        st.caption("Sumber: " + " · ".join(laporan_berita))

# ----------------------------- peta sebaran -----------------------------

if not matched.empty:
    st.subheader("Sebaran valuasi")
    x_axis = st.selectbox("Sumbu X", NUMERIC_FIELDS, index=NUMERIC_FIELDS.index("per"))
    y_axis = st.selectbox("Sumbu Y", NUMERIC_FIELDS, index=NUMERIC_FIELDS.index("roe"))
    plot = matched.dropna(subset=[x_axis, y_axis])
    if plot.empty:
        st.info("Data tidak cukup untuk kedua metrik itu.")
    else:
        fig = go.Figure(
            go.Scatter(
                x=plot[x_axis], y=plot[y_axis], mode="markers+text",
                text=plot["ticker"], textposition="top center",
                marker=dict(
                    size=bubble_sizes(plot["market_cap"]),
                    color=plot["ret_3m"], colorscale="RdYlGn", showscale=True,
                    colorbar=dict(title="Return 3 bln (%)"),
                ),
                hovertemplate="<b>%{text}</b><br>" + f"{x_axis}: %{{x:.2f}}<br>{y_axis}: %{{y:.2f}}<extra></extra>",
            )
        )
        fig.update_layout(
            xaxis_title=FIELD_DOCS.get(x_axis, x_axis), yaxis_title=FIELD_DOCS.get(y_axis, y_axis),
            height=520, margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig, width="stretch")

# ----------------------------- detail emiten -----------------------------

st.subheader("Detail emiten")
choices = list(matched["ticker"]) if not matched.empty else list(snapshot["ticker"])
ticker = st.selectbox("Pilih kode", choices, key="detail_ticker")

if ticker:
    prices = get_prices(ticker)
    row = snapshot.loc[ticker]
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Harga", f"{row['close']:,.0f}".replace(",", "."), f"{row['change_pct']:.2f}%")
    d2.metric("PER", f"{row['per']:.2f}" if pd.notna(row["per"]) else "-")
    d3.metric("PBV", f"{row['pbv']:.2f}" if pd.notna(row["pbv"]) else "-")
    d4.metric("ROE", f"{row['roe']:.2f}%" if pd.notna(row["roe"]) else "-")
    d5.metric("Kap. pasar", rupiah(row["market_cap"]))

    if not prices.empty:
        view = prices.tail(250)
        close = view["Close"]
        fig = make_subplots(
            rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
            row_heights=[0.6, 0.2, 0.2],
            subplot_titles=(f"{ticker} - harga harian", "Volume", "RSI 14"),
        )
        fig.add_trace(
            go.Candlestick(
                x=view.index, open=view["Open"], high=view["High"], low=view["Low"], close=close,
                name="Harga", increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
            ), row=1, col=1,
        )
        for window, color in ((20, "#2563eb"), (50, "#f59e0b"), (200, "#7c3aed")):
            fig.add_trace(
                go.Scatter(x=view.index, y=ind.sma(prices["Close"], window).tail(250),
                           name=f"SMA{window}", line=dict(width=1.2, color=color)),
                row=1, col=1,
            )
        fig.add_trace(go.Bar(x=view.index, y=view["Volume"], name="Volume",
                             marker_color="#94a3b8"), row=2, col=1)
        fig.add_trace(go.Scatter(x=view.index, y=ind.rsi(prices["Close"]).tail(250),
                                 name="RSI14", line=dict(color="#0ea5e9")), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#dc2626", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#16a34a", row=3, col=1)
        fig.update_layout(height=720, showlegend=True, xaxis_rangeslider_visible=False,
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")

    with st.expander("Semua metrik"):
        # Nilai diformat jadi teks supaya satu kolom tidak bercampur angka dan kata.
        detail = pd.DataFrame(
            [{"metrik": k, "nilai": fmt(row[k], k), "arti": v}
             for k, v in FIELD_DOCS.items() if k in row.index]
        )
        st.dataframe(detail, width="stretch", hide_index=True)

st.caption(
    "Data disediakan Yahoo Finance dan bisa tertunda atau keliru. "
    "Alat ini untuk riset pribadi, bukan rekomendasi jual/beli."
)
