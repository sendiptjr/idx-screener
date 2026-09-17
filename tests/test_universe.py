from idx_screener.universe import load_universe, parse_tickers, save_universe


def test_daftar_bawaan_terbaca():
    emiten = load_universe()
    kode = {e.ticker for e in emiten}
    assert len(emiten) > 100
    assert {"BBCA", "TLKM", "ASII"} <= kode
    assert all(e.ticker == e.ticker.upper() for e in emiten)


def test_ticker_yahoo_diberi_akhiran_jk():
    assert load_universe()[0].yahoo.endswith(".JK")


def test_parse_tickers_membersihkan_input():
    hasil = parse_tickers("bbca, TLKM  asii.jk")
    assert [e.ticker for e in hasil] == ["BBCA", "TLKM", "ASII"]


def test_simpan_dan_baca_ulang(tmp_path):
    asli = load_universe()[:5]
    path = save_universe(asli, tmp_path / "u.csv")
    assert {e.ticker for e in load_universe(path)} == {e.ticker for e in asli}
