"""Penalaran dampak berita - tanpa memanggil Claude sungguhan."""

from __future__ import annotations

import json
import sys
import types

import pandas as pd
import pytest

from idx_screener import analisis
from idx_screener.analisis import (
    AnalisisError,
    Dampak,
    Tema,
    _ambil_json,
    analisis_berita,
    format_tema,
)
from idx_screener.news import Berita
from idx_screener.universe import Emiten


@pytest.fixture
def universe():
    return [
        Emiten("KLBF", "Kalbe Farma", "Kesehatan"),
        Emiten("MIKA", "Mitra Keluarga Karyasehat", "Kesehatan"),
        Emiten("SMGR", "Semen Indonesia", "Barang Baku"),
    ]


@pytest.fixture
def berita():
    return [Berita(judul="Gunung Krakatau Erupsi, Abu Vulkanik Selimuti Banten",
                   tautan="x", waktu=pd.Timestamp("2026-09-21 18:00", tz="Asia/Jakarta"),
                   sumber="uji")]


def pasang_klien(monkeypatch, teks: str):
    """Pasang modul 'anthropic' tiruan yang mengembalikan teks tertentu."""
    blok = types.SimpleNamespace(type="text", text=teks)
    pesan = types.SimpleNamespace(content=[blok])
    dikirim = {}

    class Messages:
        def create(self, **kwargs):
            dikirim.update(kwargs)
            return pesan

    class Anthropic:
        def __init__(self, **kwargs):
            self.messages = Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Anthropic))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "kunci-uji")
    return dikirim


JAWABAN = json.dumps({"tema": [{
    "peristiwa": "Erupsi Krakatau, abu vulkanik menyebar",
    "rantai": "Abu vulkanik memicu gangguan pernapasan sehingga permintaan obat dan layanan rumah sakit naik",
    "arah": "positif",
    "keyakinan": "sedang",
    "emiten": [{"ticker": "KLBF", "alasan": "Produsen obat pernapasan"},
               {"ticker": "MIKA", "alasan": "Jaringan rumah sakit di Banten"}],
}]})


# ---------------- pemanggilan ----------------


def test_tanpa_kunci_api_ditolak_sebelum_jaringan(monkeypatch, berita, universe):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(AnalisisError, match="ANTHROPIC_API_KEY"):
        analisis_berita(berita, universe)


def test_berita_kosong_tidak_memanggil_apa_pun(universe):
    assert analisis_berita([], universe) == []


def test_jawaban_diurai_jadi_tema(monkeypatch, berita, universe):
    pasang_klien(monkeypatch, JAWABAN)
    tema = analisis_berita(berita, universe)
    assert len(tema) == 1
    assert tema[0].arah == "positif" and tema[0].keyakinan == "sedang"
    assert [d.ticker for d in tema[0].emiten] == ["KLBF", "MIKA"]


def test_kode_emiten_karangan_dibuang(monkeypatch, berita, universe):
    """Claude bisa mengarang kode; yang tidak ada di daftar tidak boleh lolos."""
    jawaban = json.dumps({"tema": [{
        "peristiwa": "x", "rantai": "y", "arah": "positif", "keyakinan": "rendah",
        "emiten": [{"ticker": "KLBF", "alasan": "a"}, {"ticker": "ZZZZ", "alasan": "b"}],
    }]})
    pasang_klien(monkeypatch, jawaban)
    tema = analisis_berita(berita, universe)
    assert [d.ticker for d in tema[0].emiten] == ["KLBF"]


def test_tema_tanpa_emiten_sah_dibuang(monkeypatch, berita, universe):
    jawaban = json.dumps({"tema": [{
        "peristiwa": "x", "rantai": "y", "arah": "positif", "keyakinan": "rendah",
        "emiten": [{"ticker": "ZZZZ", "alasan": "b"}],
    }]})
    pasang_klien(monkeypatch, jawaban)
    assert analisis_berita(berita, universe) == []


def test_daftar_emiten_ikut_dikirim_dan_di_cache(monkeypatch, berita, universe):
    dikirim = pasang_klien(monkeypatch, JAWABAN)
    analisis_berita(berita, universe)
    sistem = dikirim["system"][0]
    assert "KLBF|Kalbe Farma|Kesehatan" in sistem["text"]
    assert sistem["cache_control"] == {"type": "ephemeral"}
    assert "Krakatau" in dikirim["messages"][0]["content"]


def test_model_bisa_diganti_lewat_env(monkeypatch, berita, universe):
    dikirim = pasang_klien(monkeypatch, JAWABAN)
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5")
    analisis_berita(berita, universe)
    assert dikirim["model"] == "claude-opus-5"


def test_model_bawaan_haiku(monkeypatch, berita, universe):
    dikirim = pasang_klien(monkeypatch, JAWABAN)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    analisis_berita(berita, universe)
    assert dikirim["model"] == "claude-haiku-4-5"


def test_galat_jaringan_dibungkus(monkeypatch, berita, universe):
    class Meledak:
        def create(self, **kwargs):
            raise RuntimeError("koneksi putus")

    class Anthropic:
        def __init__(self, **kwargs):
            self.messages = Meledak()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Anthropic))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "kunci-uji")
    with pytest.raises(AnalisisError, match="koneksi putus"):
        analisis_berita(berita, universe)


# ---------------- penguraian JSON ----------------


def test_pagar_kode_markdown_dilucuti():
    assert _ambil_json('```json\n{"tema": []}\n```') == {"tema": []}


def test_teks_pembuka_diabaikan():
    assert _ambil_json('Berikut hasilnya:\n{"tema": []}') == {"tema": []}


def test_jawaban_tanpa_json_ditolak():
    with pytest.raises(AnalisisError, match="tidak memuat JSON"):
        _ambil_json("maaf, saya tidak bisa menjawab")


# ---------------- perangkaian pesan ----------------


def test_pesan_kosong_menyebut_tidak_ada():
    assert "Tidak ada peristiwa" in format_tema([])


def test_pesan_memuat_rantai_sebab_dan_alasan():
    tema = [Tema("Erupsi Krakatau", "Abu memicu gangguan pernapasan", "positif", "sedang",
                 [Dampak("KLBF", "Produsen obat pernapasan")])]
    teks = format_tema(tema)
    assert "▲ Erupsi Krakatau" in teks
    assert "_(sedang)_" in teks
    assert "Abu memicu gangguan pernapasan" in teks
    assert "Produsen obat pernapasan" in teks


def test_arah_negatif_memakai_panah_bawah():
    tema = [Tema("Banjir", "Klaim naik", "negatif", "tinggi", [Dampak("KLBF", "x")])]
    assert "▼ Banjir" in format_tema(tema)


def test_pesan_menegaskan_hipotesis_bukan_rekomendasi():
    tema = [Tema("x", "y", "positif", "rendah", [Dampak("KLBF", "z")])]
    teks = format_tema(tema)
    assert "BUKAN" in teks and "hipotesis" in teks


def test_harga_dan_tanda_lolos_disertakan():
    snap = pd.DataFrame([{"ticker": "KLBF", "close": 1500.0, "change_pct": 2.5}]).set_index("ticker", drop=False)
    tema = [Tema("x", "y", "positif", "tinggi", [Dampak("KLBF", "z")])]
    teks = format_tema(tema, snapshot=snap, lolos_saringan={"KLBF": ["lonjakan"]})
    assert "Rp 1.500" in teks and "← lolos lonjakan" in teks
