"""Pencocokan berita ke emiten - tanpa menyentuh jaringan."""

from __future__ import annotations

import pandas as pd
import pytest

from idx_screener import news
from idx_screener.news import (
    Berita,
    BeritaError,
    Sebutan,
    ambil_berita,
    cocokkan,
    format_berita,
    jendela_semalam,
    penanda_nama,
    urai_rss,
)
from idx_screener.universe import Emiten

RSS = """<rss><channel>
<item><title>KPK Geledah Kantor Summarecon di Bogor</title>
<link>https://contoh/1</link><pubDate>Mon, 21 Sep 2026 17:38:00 +0700</pubDate>
<description><![CDATA[<p>Penyidik mendatangi kantor pusat.</p>]]></description></item>
<item><title>Saham BYAN Jadi Beban IHSG</title>
<link>https://contoh/2</link><pubDate>Mon, 21 Sep 2026 10:00:00 +0700</pubDate>
<description>Bayan Resources turun.</description></item>
<item><title>Tanpa tanggal</title><link>x</link></item>
</channel></rss>"""


@pytest.fixture
def universe():
    return [
        Emiten("SMRA", "Summarecon Agung", "Properti"),
        Emiten("BYAN", "Bayan Resources", "Energi"),
        Emiten("PGAS", "Perusahaan Gas Negara", "Energi"),
        Emiten("ABDA", "Asuransi Bina Dana Arta", "Keuangan"),
        Emiten("BBRI", "Bank Rakyat Indonesia", "Keuangan"),
        Emiten("MEDC", "Medco Energi Internasional", "Energi"),
    ]


def berita(judul, jam="21 Sep 2026 17:00:00 +0700", ringkasan=""):
    return Berita(judul=judul, tautan="x",
                  waktu=pd.Timestamp(f"2026-09-21 17:00", tz="Asia/Jakarta"),
                  sumber="uji", ringkasan=ringkasan)


# ---------------- jendela waktu ----------------


def test_jendela_senin_mundur_sampai_jumat_sore():
    """Tanpa ini, seluruh berita akhir pekan hilang dari kiriman Senin pagi."""
    mulai, selesai = jendela_semalam(pd.Timestamp("2026-09-21 08:30", tz="Asia/Jakarta"))
    assert (mulai.strftime("%a %d %H:%M"), selesai.strftime("%a %d %H:%M")) == (
        "Fri 18 15:00", "Mon 21 08:00")


def test_jendela_selasa_mundur_sehari():
    mulai, selesai = jendela_semalam(pd.Timestamp("2026-09-22 08:30", tz="Asia/Jakarta"))
    assert mulai.strftime("%a %d %H:%M") == "Mon 21 15:00"
    assert selesai.strftime("%a %d %H:%M") == "Tue 22 08:00"


def test_jendela_berakhir_sekarang_bila_dijalankan_subuh():
    _, selesai = jendela_semalam(pd.Timestamp("2026-09-22 05:00", tz="Asia/Jakarta"))
    assert selesai.strftime("%H:%M") == "05:00"


# ---------------- penguraian RSS ----------------


def test_rss_diurai_beserta_zona_waktunya():
    hasil = urai_rss(RSS, "uji")
    assert len(hasil) == 2                      # item tanpa pubDate dibuang
    assert hasil[0].judul == "KPK Geledah Kantor Summarecon di Bogor"
    assert hasil[0].waktu.strftime("%H:%M") == "17:38"
    assert "<p>" not in hasil[0].ringkasan      # tag HTML dibersihkan


# ---------------- penanda nama ----------------


class _Balasan:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


MULAI = pd.Timestamp("2026-09-21 15:00", tz="Asia/Jakarta")
SELESAI = pd.Timestamp("2026-09-22 08:00", tz="Asia/Jakarta")
DUA_SUMBER = (("A", "https://a"), ("B", "https://b"))


def test_status_tiap_sumber_dilaporkan(monkeypatch):
    balasan = {"https://a": _Balasan(200, RSS), "https://b": _Balasan(404)}
    monkeypatch.setattr(news.requests, "get", lambda url, **_: balasan[url])
    laporan = []
    hasil = ambil_berita(MULAI, SELESAI, sumber=DUA_SUMBER, laporan=laporan)
    assert [b.judul for b in hasil] == ["KPK Geledah Kantor Summarecon di Bogor"]
    assert laporan == ["A: 2 berita, 1 di jendela", "B: HTTP 404"]


def test_semua_sumber_gagal_bukan_daftar_kosong(monkeypatch):
    # Kosong karena diblokir harus bisa dibedakan dari malam yang sepi berita.
    monkeypatch.setattr(news.requests, "get", lambda url, **_: _Balasan(403))
    with pytest.raises(BeritaError, match="A: HTTP 403; B: HTTP 403"):
        ambil_berita(MULAI, SELESAI, sumber=DUA_SUMBER)


def test_kata_umum_tidak_jadi_penanda_tunggal():
    """'Perusahaan' dan 'Asuransi' akan menyapu berita apa pun."""
    assert "perusahaan" not in penanda_nama("Perusahaan Gas Negara")[0]
    assert "asuransi" not in penanda_nama("Asuransi Bina Dana Arta")[0]


def test_kata_khas_jadi_penanda_tunggal():
    assert "summarecon" in penanda_nama("Summarecon Agung")[0]


def test_gabungan_kata_dipakai_untuk_penulisan_rapat():
    _, gabungan = penanda_nama("Medco Energi Internasional")
    assert "medcoenergi" in gabungan


# ---------------- pencocokan ----------------


def test_kode_emiten_dikenali(universe):
    hasil = cocokkan([berita("Saham BYAN Jadi Beban IHSG")], universe)
    assert [s.ticker for s in hasil] == ["BYAN"]


def test_nama_satu_kata_dikenali(universe):
    hasil = cocokkan([berita("KPK Geledah Kantor Summarecon di Bogor")], universe)
    assert [s.ticker for s in hasil] == ["SMRA"]


def test_penulisan_rapat_dikenali(universe):
    hasil = cocokkan([berita("MedcoEnergi Catat Kinerja Solid")], universe)
    assert [s.ticker for s in hasil] == ["MEDC"]


def test_alias_media_dikenali(universe):
    hasil = cocokkan([berita("BRI Perkuat Sinergi Ekosistem")], universe)
    assert [s.ticker for s in hasil] == ["BBRI"]


def test_kata_umum_tidak_memicu_kecocokan(universe):
    """Berita asuransi umum tidak boleh menyeret ABDA, dan sebaliknya."""
    hasil = cocokkan([berita("Bayar RS Bisa Pakai Asuransi Swasta")], universe)
    assert hasil == []


def test_resources_tidak_menyeret_emiten_berkata_resource(universe):
    hasil = cocokkan([berita("Harga Batu Bara Naik, Resources Global Menguat")], universe)
    assert "BYAN" not in [s.ticker for s in hasil]


def test_berita_yang_sama_tidak_dicatat_dua_kali(universe):
    satu = berita("Saham BYAN Naik", ringkasan="BYAN menguat")
    hasil = cocokkan([satu], universe)
    assert len(hasil[0].berita) == 1


def test_diurut_menurut_banyaknya_sebutan(universe):
    hasil = cocokkan([
        berita("Saham BYAN Jadi Beban"),
        berita("BYAN Kembali Turun"),
        berita("Kantor Summarecon Digeledah"),
    ], universe)
    assert [s.ticker for s in hasil] == ["BYAN", "SMRA"]


# ---------------- perangkaian pesan ----------------


def jendela():
    return (pd.Timestamp("2026-09-21 15:00", tz="Asia/Jakarta"),
            pd.Timestamp("2026-09-22 08:00", tz="Asia/Jakarta"))


def test_pesan_kosong_menyebut_tidak_ada():
    mulai, selesai = jendela()
    teks = format_berita([], mulai=mulai, selesai=selesai, jumlah_berita=18)
    assert "Tidak ada emiten yang disebut" in teks


def test_yang_lolos_saringan_ditaruh_di_depan():
    mulai, selesai = jendela()
    banyak = Sebutan("AAAA", "Alpha", [berita("a"), berita("b")])
    lolos = Sebutan("ZZZZ", "Zeta", [berita("c")])
    teks = format_berita([banyak, lolos], mulai=mulai, selesai=selesai,
                         jumlah_berita=3, lolos_saringan={"ZZZZ": ["lonjakan"]})
    assert teks.index("ZZZZ") < teks.index("AAAA")
    assert "← lolos lonjakan" in teks


def test_pesan_menegaskan_bukan_rekomendasi():
    mulai, selesai = jendela()
    teks = format_berita([Sebutan("SMRA", "Summarecon Agung", [berita("x")])],
                         mulai=mulai, selesai=selesai, jumlah_berita=1)
    assert "bukan rekomendasi" in teks


def test_harga_disertakan_bila_snapshot_ada():
    mulai, selesai = jendela()
    snap = pd.DataFrame([{"ticker": "SMRA", "close": 268.0, "change_pct": -3.6}]).set_index("ticker", drop=False)
    teks = format_berita([Sebutan("SMRA", "Summarecon Agung", [berita("x")])],
                         mulai=mulai, selesai=selesai, jumlah_berita=1, snapshot=snap)
    assert "Rp 268" in teks and "-3,60%" in teks
