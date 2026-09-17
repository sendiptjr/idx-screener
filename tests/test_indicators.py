import numpy as np
import pandas as pd
import pytest

from idx_screener import indicators as ind
from tests.conftest import make_prices


def test_sma_sesuai_rata_rata_manual():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert ind.sma(s, 3).iloc[-1] == pytest.approx(4.0)
    assert pd.isna(ind.sma(s, 3).iloc[1])


def test_rsi_selalu_di_rentang_0_100():
    r = ind.rsi(make_prices(seed=7)["Close"]).dropna()
    assert not r.empty
    assert r.between(0, 100).all()


def test_rsi_100_saat_harga_hanya_naik():
    s = pd.Series(np.arange(1, 60), dtype=float)
    assert ind.rsi(s).iloc[-1] == pytest.approx(100.0)


def test_macd_histogram_adalah_selisih_garis():
    m = ind.macd(make_prices(seed=3)["Close"]).dropna()
    assert (m["hist"] - (m["macd"] - m["signal"])).abs().max() < 1e-9


def test_bollinger_pct_b_nol_di_batas_bawah():
    bb = ind.bollinger(make_prices(seed=5)["Close"]).dropna()
    assert bb["pct_b"].between(-0.5, 1.5).mean() > 0.95


def test_atr_tidak_negatif():
    df = make_prices(seed=11)
    a = ind.atr(df["High"], df["Low"], df["Close"]).dropna()
    assert (a > 0).all()
