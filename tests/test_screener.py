import pytest

from idx_screener.metrics import FIELD_DOCS
from idx_screener.presets import load_presets
from idx_screener.rules import compile_rules, unknown_fields
from idx_screener.screener import Screener, rank_score


def test_snapshot_satu_baris_per_emiten(provider, universe):
    frame = Screener(provider=provider, universe=universe).snapshot()
    assert len(frame) == 3
    assert list(frame["ticker"]) == ["MURAH", "MAHAL", "SEPI"]


def test_filter_fundamental_menyaring(provider, universe):
    result = Screener(provider=provider, universe=universe).run(filters=["per < 20"])
    assert list(result.matched["ticker"]) == ["MURAH"]


def test_data_kosong_digugurkan_secara_default(provider, universe):
    result = Screener(provider=provider, universe=universe).run(filters=["per > 0"])
    assert "SEPI" not in list(result.matched["ticker"])   # SEPI tak punya PER
    assert result.unknown is not None and "SEPI" in list(result.unknown["ticker"])


def test_include_unknown_meloloskan_data_kosong(provider, universe):
    result = Screener(provider=provider, universe=universe).run(
        filters=["per > 0"], include_unknown=True
    )
    assert "SEPI" in list(result.matched["ticker"])


def test_corong_filter_terekam(provider, universe):
    result = Screener(provider=provider, universe=universe).run(
        filters=["avg_value_20 > 1e6", "per < 20"]
    )
    assert [step["filter"] for step in result.funnel] == ["avg_value_20 > 1e6", "per < 20"]
    assert result.funnel[0]["lolos"] == 2   # SEPI tidak likuid


def test_urutan_dan_limit(provider, universe):
    result = Screener(provider=provider, universe=universe).run(
        filters=["close > 0"], sort_by="per", ascending=True, limit=1
    )
    assert len(result.matched) == 1


def test_metrik_asing_ditolak(provider, universe):
    with pytest.raises(KeyError):
        Screener(provider=provider, universe=universe).run(filters=["ngaco > 1"])


def test_filter_mahal_ditunda_sampai_kandidat_mengerucut(provider, universe):
    """Filter DER (butuh Ticker.info) hanya ditarik untuk yang lolos saringan murah."""
    result = Screener(provider=provider, universe=universe).run(
        filters=["per < 20", "der < 1.0"]
    )
    assert list(result.matched["ticker"]) == ["MURAH"]
    assert provider.deep_diminta == {"MURAH"}      # MAHAL & SEPI tidak ditarik
    assert result.deep_diambil == 1


def test_tanpa_filter_mahal_tidak_ada_penarikan_rinci(provider, universe):
    Screener(provider=provider, universe=universe).run(filters=["per < 20"])
    assert provider.deep_diminta == set()


def test_batas_max_deep_memotong_kandidat(provider, universe):
    result = Screener(provider=provider, universe=universe).run(
        filters=["close > 0", "der < 99"], max_deep=1
    )
    assert result.deep_diambil == 1
    assert result.deep_terpotong == 2


def test_rank_score_dalam_rentang_0_100(provider, universe):
    frame = Screener(provider=provider, universe=universe).snapshot()
    skor = rank_score(frame, {"roe": 1, "per": -1})
    assert skor.between(0, 100).all()
    assert skor["MURAH"] > skor["MAHAL"]   # ROE tinggi, PER rendah


@pytest.mark.parametrize("name", sorted(load_presets()))
def test_semua_preset_valid(name):
    preset = load_presets()[name]
    rules = compile_rules(preset.filters)
    assert not unknown_fields(rules, set(FIELD_DOCS))
    if preset.sort_by:
        assert preset.sort_by in FIELD_DOCS
    for column in preset.columns:
        assert column in FIELD_DOCS
