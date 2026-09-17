import pandas as pd

from idx_screener.metrics import FIELD_DOCS, build_row
from idx_screener.universe import Emiten
from tests.conftest import make_prices


def test_build_row_mengisi_semua_field():
    row = build_row(Emiten("TEST", "Uji", "Energi"), make_prices(), {"per": 10.0})
    assert row is not None
    assert set(FIELD_DOCS) - set(row) == set()
    assert row["ticker"] == "TEST"
    assert row["sector"] == "Energi"
    assert row["per"] == 10.0


def test_riwayat_terlalu_pendek_dikembalikan_none():
    assert build_row(Emiten("TEST"), make_prices(n=10)) is None


def test_return_dan_harga_konsisten():
    prices = make_prices(seed=4)
    row = build_row(Emiten("TEST"), prices)
    close = prices["Close"]
    assert row["close"] == close.iloc[-1]
    assert row["high_52w"] >= row["close"] >= 0
    assert row["ret_1m"] == (close.iloc[-1] / close.iloc[-22] - 1) * 100


def test_asof_memotong_data():
    prices = make_prices(seed=6)
    asof = prices.index[-30]
    row = build_row(Emiten("TEST"), prices, asof=asof)
    assert row["last_date"] == asof.strftime("%Y-%m-%d")
    assert row["close"] == prices["Close"].loc[asof]


def test_tanpa_fundamental_field_tetap_ada_dan_bernilai_none():
    row = build_row(Emiten("TEST"), make_prices())
    assert row["per"] is None and row["roe"] is None


def test_tidak_ada_nan_yang_lolos():
    row = build_row(Emiten("TEST"), make_prices())
    numeric = [v for v in row.values() if isinstance(v, float)]
    assert all(v == v for v in numeric)  # NaN != NaN
