"""Perangkaian dan pengiriman pesan WhatsApp - tanpa menyentuh jaringan."""

from __future__ import annotations

import pandas as pd
import pytest

from idx_screener import notify
from idx_screener.notify import (
    SLOT_KOSONG,
    SLOT_SAHAM,
    MetaError,
    NotifyError,
    WhatsAppConfig,
    baris_saham,
    format_template_params,
    konteks_data,
    format_text,
    markdown_ke_html,
    normalize_phone,
    sanitize_param,
    send,
    tanggal_id,
)


@pytest.fixture
def hasil() -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": "TEBE", "change_pct": 18.73, "close": 1965.0, "dist_ara": 6.27, "volume_ratio": 3.99},
        {"ticker": "SINI", "change_pct": 16.06, "close": 16800.0, "dist_ara": 3.94, "volume_ratio": 1.45},
        {"ticker": "SRSN", "change_pct": 14.85, "close": 116.0, "dist_ara": 20.15, "volume_ratio": 3.36},
    ])


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)
        self.content = b"x"

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def config() -> WhatsAppConfig:
    return WhatsAppConfig(
        token="rahasia", phone_number_id="123", to="6281234567890",
        template="idx_lonjakan_harian",
    )


# ---------------- nomor tujuan ----------------


@pytest.mark.parametrize("masukan", ["081234567890", "+62 812-3456-7890", "6281234567890", "81234567890"])
def test_nomor_dinormalkan_ke_format_internasional(masukan):
    assert normalize_phone(masukan) == "6281234567890"


@pytest.mark.parametrize("masukan", ["", "   ", "62812"])
def test_nomor_tidak_masuk_akal_ditolak(masukan):
    with pytest.raises(NotifyError):
        normalize_phone(masukan)


# ---------------- perangkaian pesan ----------------


def test_tanggal_dieja_dalam_bahasa_indonesia():
    assert tanggal_id("2026-09-17") == "Kamis, 17 Sep 2026"


def test_tanggal_tak_terbaca_dikembalikan_apa_adanya():
    assert tanggal_id("bukan-tanggal") == "bukan-tanggal"


def test_konteks_pagi_menyebut_penutupan():
    assert konteks_data("2026-09-17", 1) == "penutupan Kamis, 17 Sep 2026"
    assert konteks_data("2026-09-17", 3) == "penutupan Kamis, 17 Sep 2026"


def test_konteks_sore_menyebut_sesi_berjalan_beserta_jamnya():
    sekarang = pd.Timestamp("2026-09-18 15:02", tz="Asia/Jakarta")
    teks = konteks_data("2026-09-18", 0, sekarang=sekarang)
    assert teks == "sesi berjalan Jumat, 18 Sep 2026 pukul 15.02 WIB"


def test_konteks_ikut_ke_parameter_template(hasil):
    """Kiriman sore harus menandai dirinya sendiri sebagai data belum final."""
    params = format_template_params(hasil, tanggal="2026-09-18", stale_days=0, total_scanned=845)
    assert params[0].startswith("sesi berjalan Jumat, 18 Sep 2026 pukul")
    assert params[0].endswith("WIB")


def test_pesan_teks_memuat_judul_tanggal_dan_saham(hasil):
    teks = format_text(hasil, judul="Lonjakan", tanggal="2026-09-17", stale_days=1,
                       total_scanned=845, top=2)
    assert "*Lonjakan*" in teks
    assert "penutupan Kamis, 17 Sep 2026" in teks
    assert "3 dari 845 emiten lolos" in teks
    assert "1. TEBE" in teks and "2. SINI" in teks
    assert "SRSN" not in teks            # terpotong oleh top=2
    assert "dan 1 lainnya" in teks


def test_pesan_teks_saat_tidak_ada_yang_lolos():
    kosong = pd.DataFrame(columns=["ticker", "change_pct", "close"])
    teks = format_text(kosong, judul="Lonjakan", tanggal="2026-09-17", stale_days=1,
                       total_scanned=845)
    assert "Tidak ada emiten yang lolos" in teks


def test_baris_teks_dan_slot_membawa_hal_berbeda(hasil):
    """Mode teks punya baris kedua untuk batas harga, slot template tidak.

    Karena itu ARA muncul sebagai persen di slot, sedangkan di mode teks ia
    pindah ke baris level sebagai harga rupiah, dan tempatnya dipakai volume.
    """
    row = hasil.iloc[0]
    teks = baris_saham(row, gaya="teks")
    slot = baris_saham(row, gaya="slot")
    assert teks == "TEBE +18,73% · Rp 1.965 · vol 3,99x"
    assert slot == "TEBE +18,73% · Rp 1.965 · sisa ARA 6,27%"


def test_baris_ringkas_hanya_kode_dan_persen(hasil):
    assert baris_saham(hasil.iloc[0], gaya="ringkas") == "TEBE +18,73%"


def test_sanitize_membuang_karakter_terlarang():
    assert "\n" not in sanitize_param("a\nb")
    assert "\t" not in sanitize_param("a\tb")
    assert " " * 5 not in sanitize_param("a" + " " * 9 + "b")
    assert sanitize_param("   ") == "-"


def test_parameter_template_berisi_kepala_slot_dan_sisa(hasil):
    params = format_template_params(hasil, tanggal="2026-09-17", stale_days=1, total_scanned=845)

    assert len(params) == 3 + SLOT_SAHAM + 1
    assert params[0] == "penutupan Kamis, 17 Sep 2026"
    assert params[1] == "3"          # jumlah yang lolos
    assert params[2] == "845"        # jumlah yang dipindai
    assert params[3].startswith("TEBE +18,73%")
    assert params[5].startswith("SRSN")
    assert params[-1] == SLOT_KOSONG  # tidak ada sisa di luar 8 slot


def test_slot_yang_tak_terpakai_diisi_satu_spasi(hasil):
    params = format_template_params(hasil, tanggal="2026-09-17", stale_days=1, total_scanned=845)
    # 3 saham mengisi slot pertama; lima sisanya harus spasi, bukan string kosong.
    assert params[6:11] == [SLOT_KOSONG] * 5
    assert all(p != "" for p in params)


def test_saham_di_luar_slot_dirangkum_di_parameter_terakhir():
    banyak = pd.DataFrame([
        {"ticker": f"AA{i:02d}", "change_pct": 20.0 - i, "close": 1000.0, "dist_ara": 5.0}
        for i in range(11)
    ])
    params = format_template_params(banyak, tanggal="2026-09-17", stale_days=1, total_scanned=845)
    assert params[-1] == "+3 lainnya: AA08, AA09, AA10"
    assert params[3].startswith("AA00")
    assert params[10].startswith("AA07")   # slot terakhir yang terisi


def test_parameter_template_tanpa_karakter_terlarang(hasil):
    params = format_template_params(hasil, tanggal="2026-09-17", stale_days=1, total_scanned=845)
    for p in params:
        assert "\n" not in p and "\t" not in p
        assert " " * 5 not in p


def test_hari_kosong_tetap_menghasilkan_parameter_sah():
    kosong = pd.DataFrame(columns=["ticker", "change_pct", "close", "dist_ara"])
    params = format_template_params(kosong, tanggal="2026-09-17", stale_days=1, total_scanned=845)
    assert len(params) == 3 + SLOT_SAHAM + 1
    assert params[1] == "0"
    assert params[3:] == [SLOT_KOSONG] * (SLOT_SAHAM + 1)


# ---------------- pengiriman ----------------


def test_kirim_template_membentuk_payload_meta(monkeypatch, config, hasil):
    dikirim = {}

    def fake_post(url, json, headers, timeout):
        dikirim.update(url=url, body=json, headers=headers)
        return FakeResponse({"messages": [{"id": "wamid.1"}]})

    monkeypatch.setattr(notify.requests, "post", fake_post)
    params = format_template_params(hasil, tanggal="2026-09-17", stale_days=1, total_scanned=845)
    jalur, response = send(config, text="abaikan", params=params, mode="template")

    assert jalur == "template"
    assert response["messages"][0]["id"] == "wamid.1"
    assert dikirim["url"].endswith("/123/messages")
    assert dikirim["headers"]["Authorization"] == "Bearer rahasia"
    body = dikirim["body"]
    assert body["to"] == "6281234567890"
    assert body["template"]["name"] == "idx_lonjakan_harian"
    assert [p["text"] for p in body["template"]["components"][0]["parameters"]] == params


def test_mode_auto_memilih_template_bila_tersedia(monkeypatch, config):
    monkeypatch.setattr(notify.requests, "post",
                        lambda url, json, headers, timeout: FakeResponse({"messages": [{"id": "x"}]}))
    monkeypatch.setattr(notify, "send_text", lambda *a, **k: pytest.fail("teks tak boleh dipakai"))
    jalur, _ = send(config, text="t", params=["a", "b", "c"], mode="auto")
    assert jalur == "template"


def test_mode_auto_memakai_teks_bila_template_kosong(monkeypatch, config):
    config.template = ""
    monkeypatch.setattr(notify.requests, "post",
                        lambda url, json, headers, timeout: FakeResponse({"messages": [{"id": "x"}]}))
    jalur, _ = send(config, text="t", params=["a"], mode="auto")
    assert jalur == "text"


def test_jendela_24_jam_tertutup_jatuh_ke_template(monkeypatch, config):
    panggilan = []

    def fake_post(url, json, headers, timeout):
        panggilan.append(json["type"])
        if json["type"] == "text":
            return FakeResponse({"error": {"code": 131047, "message": "Re-engagement message"}}, 400)
        return FakeResponse({"messages": [{"id": "wamid.2"}]})

    monkeypatch.setattr(notify.requests, "post", fake_post)
    jalur, _ = send(config, text="t", params=["a", "b", "c"], mode="text")
    assert panggilan == ["text", "template"]
    assert jalur == "template"


def test_galat_lain_tidak_dijatuhkan_ke_template(monkeypatch, config):
    monkeypatch.setattr(notify.requests, "post", lambda url, json, headers, timeout:
                        FakeResponse({"error": {"code": 190, "message": "Token kedaluwarsa"}}, 401))
    with pytest.raises(MetaError) as exc:
        send(config, text="t", params=["a"], mode="text")
    assert exc.value.code == 190
    assert "Token kedaluwarsa" in str(exc.value)


def test_template_tanpa_nama_ditolak_sebelum_jaringan(config):
    config.template = ""
    with pytest.raises(NotifyError, match="template"):
        send(config, text="t", params=["a"], mode="template")


def test_mode_tidak_dikenal_ditolak(config):
    with pytest.raises(NotifyError, match="Mode"):
        send(config, text="t", params=["a"], mode="siaran")


def test_konfigurasi_dari_env_menyebut_yang_kurang(monkeypatch):
    for nama in ("WA_TOKEN", "WA_PHONE_NUMBER_ID", "WA_TO", "WA_TEMPLATE"):
        monkeypatch.delenv(nama, raising=False)
    with pytest.raises(NotifyError) as exc:
        WhatsAppConfig.from_env()
    assert "WA_TOKEN" in str(exc.value) and "WA_PHONE_NUMBER_ID" in str(exc.value)


def test_konfigurasi_dari_env_lengkap(monkeypatch):
    monkeypatch.setenv("WA_TOKEN", "t")
    monkeypatch.setenv("WA_PHONE_NUMBER_ID", "99")
    monkeypatch.setenv("WA_TEMPLATE", "idx_lonjakan_harian")
    monkeypatch.delenv("WA_TO", raising=False)
    config = WhatsAppConfig.from_env("081234567890")
    assert config.to == "6281234567890"
    assert config.template == "idx_lonjakan_harian"


# ---------------- Telegram ----------------


def test_markdown_diubah_ke_html():
    assert markdown_ke_html("*tebal*") == "<b>tebal</b>"
    assert markdown_ke_html("_miring_") == "<i>miring</i>"


def test_html_meloloskan_karakter_khusus():
    hasil = markdown_ke_html("a & b <c> d")
    assert hasil == "a &amp; b &lt;c&gt; d"


def test_tanda_baca_pesan_tidak_merusak_konversi(hasil):
    teks = format_text(hasil, judul="Lonjakan", tanggal="2026-09-17", stale_days=1,
                       total_scanned=845, catatan="Median 1-2 minggu negatif (-0,8%).")
    html = markdown_ke_html(teks)
    assert "<b>Lonjakan</b>" in html
    assert "(-0,8%)" in html          # tanda kurung dan minus lewat apa adanya
    assert "TEBE +18,73%" in html


def test_pesan_telegram_dipotong_di_batas(monkeypatch):
    dikirim = {}

    def fake_post(url, json, timeout):
        dikirim.update(json=json)
        return FakeResponse({"ok": True, "result": {"message_id": 7, "chat": {"id": 42}}})

    monkeypatch.setattr(notify.requests, "post", fake_post)
    config = notify.TelegramConfig(token="t", chat_id="42")
    notify.send_telegram(config, "x" * 6000)
    assert len(dikirim["json"]["text"]) <= notify.TELEGRAM_LIMIT


def test_kirim_telegram_membentuk_payload(monkeypatch):
    dikirim = {}

    def fake_post(url, json, timeout):
        dikirim.update(url=url, json=json)
        return FakeResponse({"ok": True, "result": {"message_id": 7, "chat": {"id": 42}}})

    monkeypatch.setattr(notify.requests, "post", fake_post)
    hasil = notify.send_telegram(notify.TelegramConfig(token="rahasia", chat_id="42"), "*halo*")
    assert hasil["message_id"] == 7
    assert dikirim["url"].endswith("/botrahasia/sendMessage")
    assert dikirim["json"]["parse_mode"] == "HTML"
    assert dikirim["json"]["text"] == "<b>halo</b>"
    assert dikirim["json"]["chat_id"] == "42"


def test_telegram_menolak_dilaporkan_apa_adanya(monkeypatch):
    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout:
                        FakeResponse({"ok": False, "error_code": 400,
                                      "description": "chat not found"}, 400))
    with pytest.raises(NotifyError, match="chat not found"):
        notify.send_telegram(notify.TelegramConfig(token="t", chat_id="salah"), "halo")


def test_konfigurasi_telegram_menyebut_yang_kurang(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(NotifyError) as exc:
        notify.TelegramConfig.from_env()
    assert "TELEGRAM_TOKEN" in str(exc.value) and "TELEGRAM_CHAT_ID" in str(exc.value)


def test_chat_id_dikumpulkan_tanpa_duplikat(monkeypatch):
    updates = {"ok": True, "result": [
        {"message": {"chat": {"id": 42, "type": "private", "first_name": "Sendi"}}},
        {"message": {"chat": {"id": 42, "type": "private", "first_name": "Sendi"}}},
        {"channel_post": {"chat": {"id": -100, "type": "channel", "title": "Saham"}}},
    ]}
    monkeypatch.setattr(notify.requests, "get",
                        lambda url, timeout: FakeResponse(updates))
    chats = notify.telegram_chats("t")
    assert [c["chat_id"] for c in chats] == ["42", "-100"]
    assert chats[0]["nama"] == "Sendi" and chats[1]["nama"] == "Saham"


# ---------------- batas harga ----------------


@pytest.mark.parametrize("harga,harapan", [
    (156.6, 156),      # < 200  -> tick 1
    (199.9, 199),
    (483.0, 482),      # 200-500 -> tick 2
    (643.75, 640),     # 500-2000 -> tick 5
    (2001.0, 2000),    # 2000-5000 -> tick 10
    (5124.0, 5100),    # >= 5000 -> tick 25
])
def test_harga_dibulatkan_ke_fraksi_idx(harga, harapan):
    assert notify.bulatkan_tick(harga) == harapan


def test_pembulatan_selalu_ke_bawah():
    """Batas atas yang dibulatkan ke atas justru akan ditolak bursa."""
    assert notify.bulatkan_tick(644.9) == 640
    assert notify.bulatkan_tick(199.99) == 199


def test_harga_ara_dihitung_dari_penutupan_kemarin():
    row = pd.Series({"prev_close": 515.0, "ara_limit": 25.0, "close": 585.0})
    assert notify.harga_ara(row) == 640          # 515 * 1,25 = 643,75 -> tick 5


def test_harga_ara_kosong_bila_datanya_tidak_ada():
    assert notify.harga_ara(pd.Series({"close": 100.0})) is None
    assert notify.harga_ara(pd.Series({"prev_close": None, "ara_limit": 25.0})) is None


def test_baris_level_memuat_ara_dan_sma20():
    row = pd.Series({"prev_close": 515.0, "ara_limit": 25.0, "sma20": 583.0})
    assert notify.baris_level(row) == "ARA hari ini Rp 640 · SMA20 Rp 580"


def test_baris_level_tanpa_desimal_untuk_harga_kecil():
    row = pd.Series({"prev_close": 116.0, "ara_limit": 35.0, "sma20": 95.45})
    assert notify.baris_level(row) == "ARA hari ini Rp 156 · SMA20 Rp 95"


def test_level_masuk_ke_pesan_teks():
    frame = pd.DataFrame([{
        "ticker": "FPNI", "change_pct": 13.59, "close": 585.0,
        "prev_close": 515.0, "ara_limit": 25.0, "sma20": 583.0, "volume_ratio": 2.67,
    }])
    teks = format_text(frame, judul="Lonjakan", tanggal="2026-09-18", stale_days=0,
                       total_scanned=845)
    assert "ARA hari ini Rp 640" in teks
    assert "keduanya fakta" in teks


def test_level_bisa_dimatikan():
    frame = pd.DataFrame([{
        "ticker": "FPNI", "change_pct": 13.59, "close": 585.0,
        "prev_close": 515.0, "ara_limit": 25.0, "sma20": 583.0,
    }])
    teks = format_text(frame, judul="Lonjakan", tanggal="2026-09-18", stale_days=0,
                       total_scanned=845, sertakan_level=False)
    assert "ARA hari ini" not in teks


def test_slot_template_tetap_memakai_persen_bukan_harga():
    """Slot tidak punya baris kedua, jadi sisa ARA tetap disebut di sana."""
    row = pd.Series({"ticker": "FPNI", "change_pct": 13.59, "close": 585.0, "dist_ara": 11.41})
    assert "sisa ARA 11,41%" in baris_saham(row, gaya="slot")
    assert "sisa ARA" not in baris_saham(row, gaya="teks")


def test_tp_sl_hanya_muncul_bila_diminta():
    frame = pd.DataFrame([{
        "ticker": "FPNI", "change_pct": 16.5, "close": 600.0,
        "prev_close": 515.0, "ara_limit": 25.0, "sma20": 580.0, "atr14": 51.0,
    }])
    tanpa = format_text(frame, judul="L", tanggal="2026-09-18", stale_days=0, total_scanned=845)
    dengan = format_text(frame, judul="L", tanggal="2026-09-18", stale_days=0,
                         total_scanned=845, sertakan_tpsl=True)
    assert "TP Rp" not in tanpa
    assert "TP Rp 700 (+16,67%) · SL Rp 580 (-3,33%)" in dengan
    assert "ancar-ancar" in dengan


def test_sl_memakai_sma20_bila_lebih_dekat_ke_harga():
    """SMA20 di atas batas ATR -> dipakai, sebab di sana premisnya gugur."""
    row = pd.Series({"close": 600.0, "atr14": 51.0, "sma20": 580.0})
    tp, sl = notify.level_tp_sl(row)          # 600 - 1,5*51 = 523,5 < 580
    assert (tp, sl) == (700, 580)


def test_sl_memakai_atr_bila_sma20_jauh_di_bawah():
    """Fraksi ditentukan oleh harga level itu sendiri, bukan harga sahamnya.

    SL 1.915 jatuh di bawah Rp 2.000, jadi ticknya Rp 5 - bukan Rp 10 seperti
    harga sahamnya yang Rp 2.050.
    """
    row = pd.Series({"close": 2050.0, "atr14": 90.0, "sma20": 1595.0})
    tp, sl = notify.level_tp_sl(row)          # 2050 - 135 = 1915 > 1595
    assert (tp, sl) == (2230, 1915)


def test_sma20_di_atas_harga_tidak_dipakai_sebagai_sl():
    """Stop di atas harga beli tidak masuk akal."""
    row = pd.Series({"close": 100.0, "atr14": 8.0, "sma20": 120.0})
    _, sl = notify.level_tp_sl(row)
    assert sl == 88


def test_tanpa_atr_hanya_sl_dari_sma20():
    row = pd.Series({"close": 600.0, "sma20": 580.0})
    tp, sl = notify.level_tp_sl(row)
    assert tp is None and sl == 580
