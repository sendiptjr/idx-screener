import pytest

from idx_screener.backtest import LookAheadError, backtest
from idx_screener.screener import Screener


def test_backtest_menolak_filter_fundamental(provider, universe):
    screener = Screener(provider=provider, universe=universe)
    with pytest.raises(LookAheadError):
        backtest(screener, ["per < 10"])


def test_backtest_izinkan_fundamental_bila_diminta(provider, universe):
    screener = Screener(provider=provider, universe=universe)
    hasil = backtest(screener, ["per < 100"], periods=2, allow_fundamentals=True)
    assert hasil.summary["periode"] >= 1


def test_backtest_harga_menghasilkan_ringkasan(provider, universe):
    screener = Screener(provider=provider, universe=universe)
    hasil = backtest(screener, ["close > sma50"], periods=4, hold_days=10, top_n=2)
    assert len(hasil.periods) == 4
    assert set(hasil.periods.columns) >= {"tanggal", "terpilih", "return_strategi", "return_pasar"}
    assert hasil.summary["hari_tahan"] == 10
    assert hasil.periods["terpilih"].max() <= 2


def test_backtest_tanggal_berurutan(provider, universe):
    hasil = backtest(Screener(provider=provider, universe=universe), ["close > 0"], periods=3)
    assert list(hasil.periods["tanggal"]) == sorted(hasil.periods["tanggal"])
