import pandas as pd

from idx_screener.cache import Cache
from idx_screener.report import compact, export, fmt, render_table
from tests.conftest import make_prices


def test_cache_simpan_dan_baca(tmp_path):
    cache = Cache(tmp_path / "c.db")
    prices = make_prices(n=40)
    cache.put_prices("TEST", prices, period="2y")
    kembali = cache.get_prices("TEST")
    assert len(kembali) == 40
    assert kembali["Close"].iloc[-1] == pd.Series(prices["Close"]).iloc[-1]


def test_cache_menolak_periode_lebih_pendek(tmp_path):
    from idx_screener.providers.yahoo import YahooProvider

    cache = Cache(tmp_path / "c.db")
    cache.put_prices("TEST", make_prices(n=40), period="2y")
    assert YahooProvider(cache, period="5y")._price_is_stale("TEST") is True
    assert YahooProvider(cache, period="1y")._price_is_stale("TEST") is False


def test_cache_fundamental_roundtrip(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.put_fundamentals("TEST", {"per": 10.0})
    payload, umur, depth = cache.get_fundamentals("TEST")
    assert payload["per"] == 10.0 and umur < 1 and depth == "bulk"


def test_lapis_deep_melengkapi_bukan_menimpa(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.put_fundamentals("TEST", {"per": 10.0, "pbv": 2.0}, depth="bulk")
    cache.put_fundamentals("TEST", {"der": 0.5, "pbv": None}, depth="deep")
    payload, _, depth = cache.get_fundamentals("TEST")
    assert payload == {"per": 10.0, "pbv": 2.0, "der": 0.5}
    assert depth == "deep"


def test_bulk_tidak_menurunkan_kedalaman(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.put_fundamentals("TEST", {"der": 0.5}, depth="deep")
    cache.put_fundamentals("TEST", {"per": 9.0}, depth="bulk")
    assert cache.get_fundamentals("TEST")[2] == "deep"
    assert cache.tickers_by_depth("deep") == {"TEST"}


def test_format_angka():
    assert fmt(None) == "-"
    assert fmt(True) == "ya"
    assert fmt(12.3456, "roe") == "12,35%"
    assert fmt(1_250_000_000_000, "market_cap") == "1,25 T"
    assert fmt(6325, "close") == "6.325"
    assert fmt(3, "terpilih") == "3"


def test_compact_satuan_indonesia():
    assert compact(5.4e9) == "5,40 M"
    assert compact(-2.5e6) == "-2,50 jt"


def test_export_csv_dan_json(tmp_path):
    frame = pd.DataFrame([{"ticker": "AAA", "per": 5.0}, {"ticker": "BBB", "per": 9.0}])
    csv_path = export(frame, tmp_path / "hasil.csv")
    json_path = export(frame, tmp_path / "hasil.json")
    assert "AAA" in csv_path.read_text()
    assert "BBB" in json_path.read_text()


def test_render_table_tidak_error_untuk_kolom_kosong():
    frame = pd.DataFrame([{"ticker": "AAA", "per": None, "change_pct": -1.5}])
    table = render_table(frame, ["ticker", "per", "change_pct", "tidak_ada"])
    assert table.row_count == 1
