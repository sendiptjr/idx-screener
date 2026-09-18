"""Kirim hasil screening ke WhatsApp (Meta Cloud API) atau Telegram.

Alur sehari-hari: cron memanggil `idxscreen notify --preset lonjakan`,
hasilnya dirangkai jadi pesan, lalu dikirim ke nomor tujuan.

Catatan penting soal Cloud API: pesan yang dimulai oleh bisnis (bukan balasan
dalam 24 jam setelah pengguna menyapa) HARUS berupa *template* yang sudah
disetujui Meta. Karena penjadwalan harian selalu di luar jendela 24 jam,
jalur normalnya adalah template. Teks bebas hanya dipakai saat menguji
sesaat setelah nomor tujuan membalas.

Nilai parameter template tidak boleh memuat baris baru, tab, atau lebih dari
empat spasi berturut-turut - karena itu daftar saham dirangkai jadi satu baris
dengan pemisah titik tengah.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass

import pandas as pd
import requests

from .report import fmt

API_HOST = "https://graph.facebook.com"
TELEGRAM_HOST = "https://api.telegram.org"

# Batas satu pesan Telegram.
TELEGRAM_LIMIT = 4096
DEFAULT_API_VERSION = "v25.0"

# Kode galat Meta yang berarti "jendela 24 jam tertutup, wajib pakai template".
REENGAGEMENT_ERRORS = {131047, 470}

# Template harian menyediakan delapan baris saham bernomor. Jumlahnya tetap:
# badan template ditulis sekali di Meta dan tidak bisa memanjang-memendek.
SLOT_SAHAM = 8

# Meta menolak parameter kosong tetapi menerima satu spasi - itulah yang
# dipakai untuk baris yang tidak terisi di hari sepi (diuji, bukan dugaan).
SLOT_KOSONG = " "

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


class NotifyError(RuntimeError):
    """Konfigurasi kurang lengkap atau Meta menolak pesannya."""


# --------------------------------------------------------------------------
# konfigurasi


@dataclass
class WhatsAppConfig:
    token: str
    phone_number_id: str
    to: str
    template: str = ""
    template_lang: str = "id"
    api_version: str = DEFAULT_API_VERSION

    @classmethod
    def from_env(cls, to: str | None = None) -> "WhatsAppConfig":
        nomor = to or os.environ.get("WA_TO", "")
        kurang = [
            nama for nama, nilai in (
                ("WA_TOKEN", os.environ.get("WA_TOKEN")),
                ("WA_PHONE_NUMBER_ID", os.environ.get("WA_PHONE_NUMBER_ID")),
                ("WA_TO (atau opsi --to)", nomor),
            ) if not nilai
        ]
        if kurang:
            raise NotifyError("Belum diset: " + ", ".join(kurang))
        return cls(
            token=os.environ["WA_TOKEN"],
            phone_number_id=os.environ["WA_PHONE_NUMBER_ID"],
            to=normalize_phone(nomor),
            template=os.environ.get("WA_TEMPLATE", ""),
            template_lang=os.environ.get("WA_TEMPLATE_LANG", "id"),
            api_version=os.environ.get("WA_API_VERSION", DEFAULT_API_VERSION),
        )


def normalize_phone(raw: str) -> str:
    """'081234567890' -> '6281234567890'; '+62 812-3456-7890' juga diterima."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise NotifyError("Nomor tujuan kosong.")
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    if len(digits) < 10:
        raise NotifyError(f"Nomor tujuan tidak masuk akal: {raw}")
    return digits


# --------------------------------------------------------------------------
# perangkaian pesan


def tanggal_id(iso: str) -> str:
    """'2026-09-17' -> 'Rabu, 17 Sep 2026'. Nilai tak terbaca dikembalikan apa adanya."""
    try:
        ts = pd.Timestamp(iso)
    except (ValueError, TypeError):
        return str(iso)
    return f"{HARI[ts.weekday()]}, {ts.day} {BULAN[ts.month - 1]} {ts.year}"


def konteks_data(tanggal: str, stale_days: int, *, sekarang: "pd.Timestamp | None" = None) -> str:
    """Terangkan data ini potret kapan.

    `stale_days` 0 berarti bar hari ini sudah ada, artinya bursa masih berjalan
    dan angkanya belum final - penting dibedakan karena kiriman pukul 15.00 WIB
    jatuh di tengah sesi II, sedangkan kiriman pagi memakai penutupan kemarin.
    """
    if stale_days <= 0:
        waktu = sekarang if sekarang is not None else pd.Timestamp.now(tz="Asia/Jakarta")
        return f"sesi berjalan {tanggal_id(tanggal)} pukul {waktu:%H.%M} WIB"
    return f"penutupan {tanggal_id(tanggal)}"


# Fraksi harga IDX: (batas atas harga, kelipatan tick).
FRAKSI_HARGA = ((200, 1), (500, 2), (2000, 5), (5000, 10), (float("inf"), 25))


def bulatkan_tick(harga: float) -> float:
    """Bulatkan ke bawah ke kelipatan tick yang sah di IDX.

    Ke bawah, bukan ke terdekat: angka ini dipakai sebagai batas atas, dan
    membulatkan ke atas akan menghasilkan harga yang justru ditolak bursa.
    """
    for batas, tick in FRAKSI_HARGA:
        if harga < batas:
            return math.floor(harga / tick) * tick
    return harga


def harga_ara(row: pd.Series) -> float | None:
    """Harga tertinggi yang boleh ditransaksikan hari ini (Rp).

    Batas ARA dihitung dari penutupan kemarin, bukan dari harga sekarang.
    """
    prev, batas = row.get("prev_close"), row.get("ara_limit")
    if prev is None or batas is None or pd.isna(prev) or pd.isna(batas):
        return None
    return bulatkan_tick(float(prev) * (1 + float(batas) / 100))


def _rupiah_bulat(harga: float) -> str:
    """Harga yang sudah dibulatkan ke tick tidak perlu desimal."""
    return f"{int(round(harga)):,}".replace(",", ".")


def baris_level(row: pd.Series) -> str:
    """Batas harga yang sifatnya fakta, bukan ancar-ancar.

    ARA adalah batas bursa; SMA20 adalah syarat preset ini sendiri, sehingga
    di bawahnya saham tersebut tidak akan lolos saringan lagi.
    """
    bagian = []
    ara = harga_ara(row)
    if ara:
        bagian.append(f"ARA hari ini Rp {_rupiah_bulat(ara)}")
    sma20 = row.get("sma20")
    if sma20 is not None and pd.notna(sma20):
        bagian.append(f"SMA20 Rp {_rupiah_bulat(bulatkan_tick(float(sma20)))}")
    return " · ".join(bagian)


def level_tp_sl(row: pd.Series) -> tuple[float | None, float | None]:
    """Acuan ambil untung dan batas rugi, dalam rupiah.

    SL memakai yang lebih tinggi antara SMA20 dan `close - 1,5 x ATR14`: SMA20
    adalah titik gugurnya premis untuk preset lonjakan, sedangkan kelipatan ATR
    menjaga agar saham yang harganya jauh di atas SMA20 tidak dibiarkan turun
    terlalu dalam. TP memakai `close + 2 x ATR14`.

    Angka-angka ini ancar-ancar volatilitas, bukan hasil pengukuran: backtest
    preset ini hanya menguji tahan 1-2 minggu lalu jual, tanpa TP/SL sama
    sekali.
    """
    close, atr, sma20 = row.get("close"), row.get("atr14"), row.get("sma20")
    if close is None or pd.isna(close):
        return None, None
    close = float(close)
    punya_atr = atr is not None and pd.notna(atr)

    tp = bulatkan_tick(close + 2 * float(atr)) if punya_atr else None

    kandidat = []
    if sma20 is not None and pd.notna(sma20) and float(sma20) < close:
        kandidat.append(float(sma20))
    if punya_atr:
        kandidat.append(close - 1.5 * float(atr))
    sl = bulatkan_tick(max(kandidat)) if kandidat else None
    return tp, sl


def baris_tp_sl(row: pd.Series) -> str:
    tp, sl = level_tp_sl(row)
    close = row.get("close")
    if close is None or pd.isna(close) or (tp is None and sl is None):
        return ""
    close = float(close)
    bagian = []
    if tp:
        bagian.append(f"TP Rp {_rupiah_bulat(tp)} ({_persen((tp / close - 1) * 100)})")
    if sl:
        bagian.append(f"SL Rp {_rupiah_bulat(sl)} ({_persen((sl / close - 1) * 100)})")
    return " · ".join(bagian)


def _persen(value) -> str:
    teks = fmt(value, "change_pct")
    return f"+{teks}" if isinstance(value, (int, float)) and value > 0 else teks


def baris_saham(row: pd.Series, *, gaya: str = "teks") -> str:
    """Satu saham jadi satu potong teks.

    gaya 'teks'    - pesan teks bebas, paling lengkap
    gaya 'slot'    - satu baris template; tanpa rasio volume agar tidak
                     membungkus di layar ponsel
    gaya 'ringkas' - sesingkat mungkin, untuk daftar sisa
    """
    kepala = f"{row.get('ticker', '?')} {_persen(row.get('change_pct'))}"
    if gaya == "ringkas":
        return kepala

    bagian = [kepala]
    if "close" in row.index and pd.notna(row.get("close")):
        bagian.append("Rp " + fmt(row["close"], "close"))
    if gaya == "slot" and "dist_ara" in row.index and pd.notna(row.get("dist_ara")):
        # Slot template tidak punya baris kedua, jadi ARA tetap disebut di sini.
        bagian.append(f"sisa ARA {fmt(row['dist_ara'], 'dist_ara')}")
    if gaya == "teks" and "volume_ratio" in row.index and pd.notna(row.get("volume_ratio")):
        bagian.append(f"vol {fmt(row['volume_ratio'])}x")
    return " · ".join(bagian)


def format_text(
    frame: pd.DataFrame,
    *,
    judul: str,
    tanggal: str,
    stale_days: int,
    total_scanned: int,
    top: int = 10,
    catatan: str = "",
    sertakan_level: bool = True,
    sertakan_tpsl: bool = False,
) -> str:
    """Pesan teks bebas, berbaris banyak - hanya sah di dalam jendela 24 jam."""
    kepala = [
        f"*{judul}*",
        f"Data {konteks_data(tanggal, stale_days)}",
        f"{len(frame)} dari {total_scanned} emiten lolos",
        "",
    ]
    if frame.empty:
        kepala.append("_Tidak ada emiten yang lolos hari ini._")
    else:
        for nomor, (_, row) in enumerate(frame.head(top).iterrows(), start=1):
            kepala.append(f"{nomor}. {baris_saham(row, gaya='teks')}")
            if sertakan_level:
                level = baris_level(row)
                if level:
                    kepala.append(f"    {level}")
            if sertakan_tpsl:
                tpsl = baris_tp_sl(row)
                if tpsl:
                    kepala.append(f"    {tpsl}")
        if len(frame) > top:
            kepala.append(f"_...dan {len(frame) - top} lainnya._")
    if not frame.empty:
        keterangan = []
        if sertakan_level:
            keterangan.append("ARA batas bursa hari ini, SMA20 syarat saringan ini - "
                              "keduanya fakta.")
        if sertakan_tpsl:
            keterangan.append("TP/SL ancar-ancar volatilitas (2x dan 1,5x ATR14), bukan "
                              "hasil pengukuran: backtest hanya menguji beli di penutupan "
                              "lalu tahan 1-2 minggu, dan karena keunggulan datang dari "
                              "sedikit pemenang besar, TP ketat justru memotongnya.")
        if keterangan:
            kepala += ["", "_" + " ".join(keterangan) + "_"]
    if catatan:
        kepala += ["", f"_{catatan.strip()}_"]
    return "\n".join(kepala)


def sanitize_param(text: str) -> str:
    """Buang yang dilarang Meta pada nilai parameter template."""
    teks = str(text).replace("\t", " ")
    teks = re.sub(r"\s*\n+\s*", " · ", teks)
    teks = re.sub(r" {5,}", "    ", teks)
    return teks.strip() or "-"


def format_template_params(
    frame: pd.DataFrame,
    *,
    tanggal: str,
    stale_days: int,
    total_scanned: int,
    slots: int = SLOT_SAHAM,
) -> list[str]:
    """Parameter untuk template harian: 3 kepala + `slots` baris saham + 1 sisa.

    Urutannya harus persis sama dengan {{1}}..{{n}} pada badan template di
    WhatsApp Manager; lihat bagian "Kirim ke WhatsApp tiap pagi" di README.
    """
    params = [
        sanitize_param(konteks_data(tanggal, stale_days)),
        sanitize_param(str(len(frame))),
        sanitize_param(str(total_scanned)),
    ]

    tampil = frame.head(slots)
    for posisi in range(slots):
        if posisi < len(tampil):
            params.append(sanitize_param(baris_saham(tampil.iloc[posisi], gaya="slot")))
        else:
            params.append(SLOT_KOSONG)

    sisa = frame.iloc[slots:]
    if len(sisa):
        kode = ", ".join(str(t) for t in sisa["ticker"])
        params.append(sanitize_param(f"+{len(sisa)} lainnya: {kode}"))
    else:
        params.append(SLOT_KOSONG)
    return params


# --------------------------------------------------------------------------
# Telegram
#
# Jauh lebih sederhana daripada Cloud API: tidak ada template, tidak ada
# review, tidak ada jendela 24 jam. Pesan teks berbaris banyak dikirim apa
# adanya, jadi format yang sama dipakai tanpa dipotong-potong ke slot.


@dataclass
class TelegramConfig:
    token: str
    chat_id: str

    @classmethod
    def from_env(cls, chat_id: str | None = None) -> "TelegramConfig":
        tujuan = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        kurang = [
            nama for nama, nilai in (
                ("TELEGRAM_TOKEN", os.environ.get("TELEGRAM_TOKEN")),
                ("TELEGRAM_CHAT_ID (atau opsi --to)", tujuan),
            ) if not nilai
        ]
        if kurang:
            raise NotifyError("Belum diset: " + ", ".join(kurang))
        return cls(token=os.environ["TELEGRAM_TOKEN"], chat_id=str(tujuan))


def markdown_ke_html(teks: str) -> str:
    """`*tebal*` dan `_miring_` -> HTML yang dimengerti Telegram.

    Dipakai mode HTML, bukan Markdown, karena tanda baca di dalam pesan
    (tanda kurung, minus, persen) membuat parser Markdown Telegram rewel
    sementara HTML hanya perlu meloloskan tiga karakter.
    """
    aman = teks.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    aman = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", aman)
    aman = re.sub(r"_([^_]+)_", r"<i>\1</i>", aman, flags=re.S)
    return aman


def _telegram(config: TelegramConfig, metode: str, payload: dict, timeout: float) -> dict:
    response = requests.post(
        f"{TELEGRAM_HOST}/bot{config.token}/{metode}", json=payload, timeout=timeout
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not body.get("ok"):
        raise NotifyError(
            f"Telegram menolak ({response.status_code}/{body.get('error_code')}): "
            + (body.get("description") or response.text[:200])
        )
    return body["result"]


def send_telegram(config: TelegramConfig, text: str, *, timeout: float = 30.0) -> dict:
    isi = markdown_ke_html(text)
    if len(isi) > TELEGRAM_LIMIT:
        isi = isi[: TELEGRAM_LIMIT - 20].rsplit("\n", 1)[0] + "\n..."
    return _telegram(config, "sendMessage", {
        "chat_id": config.chat_id,
        "text": isi,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout)


def telegram_chats(token: str, *, timeout: float = 30.0) -> list[dict]:
    """Daftar chat yang pernah menyapa bot ini - untuk menemukan chat id."""
    response = requests.get(f"{TELEGRAM_HOST}/bot{token}/getUpdates", timeout=timeout)
    body = response.json() if response.content else {}
    if not body.get("ok"):
        raise NotifyError(
            f"Telegram menolak: {body.get('description') or response.text[:200]}"
        )
    terlihat: dict[str, dict] = {}
    for update in body.get("result", []):
        pesan = update.get("message") or update.get("channel_post") or {}
        chat = pesan.get("chat") or {}
        if chat.get("id") is not None:
            nama = chat.get("title") or " ".join(
                bagian for bagian in (chat.get("first_name"), chat.get("last_name")) if bagian
            ) or chat.get("username") or "-"
            terlihat[str(chat["id"])] = {"chat_id": str(chat["id"]), "nama": nama,
                                         "jenis": chat.get("type", "-")}
    return list(terlihat.values())


# --------------------------------------------------------------------------
# pengiriman


def _post(config: WhatsAppConfig, payload: dict, timeout: float) -> dict:
    url = f"{API_HOST}/{config.api_version}/{config.phone_number_id}/messages"
    response = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {config.token}"},
        timeout=timeout,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or "error" in body:
        error = body.get("error", {})
        kode = error.get("code")
        pesan = error.get("message") or response.text[:300]
        detail = error.get("error_data", {}).get("details")
        raise MetaError(
            f"Meta menolak ({response.status_code}/{kode}): {pesan}"
            + (f" - {detail}" if detail else ""),
            code=kode,
        )
    return body


class MetaError(NotifyError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def send_text(config: WhatsAppConfig, text: str, *, timeout: float = 30.0) -> dict:
    return _post(config, {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": config.to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }, timeout)


def send_template(config: WhatsAppConfig, params: list[str], *, timeout: float = 30.0) -> dict:
    if not config.template:
        raise NotifyError("Nama template belum diset (WA_TEMPLATE atau --template).")
    return _post(config, {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": config.to,
        "type": "template",
        "template": {
            "name": config.template,
            "language": {"code": config.template_lang},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in params],
            }],
        },
    }, timeout)


def send(
    config: WhatsAppConfig,
    *,
    text: str,
    params: list[str],
    mode: str = "auto",
    timeout: float = 30.0,
) -> tuple[str, dict]:
    """Kirim pesan; kembalikan (jalur_yang_dipakai, respons Meta).

    mode 'auto'  - pakai template bila namanya diset, selain itu teks bebas
    mode 'text'  - paksa teks bebas, lalu jatuh ke template bila jendela tertutup
    mode 'template' - paksa template
    """
    if mode not in {"auto", "text", "template"}:
        raise NotifyError(f"Mode pengiriman tidak dikenal: {mode}")
    if mode == "auto":
        mode = "template" if config.template else "text"

    if mode == "template":
        return "template", send_template(config, params, timeout=timeout)

    try:
        return "text", send_text(config, text, timeout=timeout)
    except MetaError as exc:
        if exc.code in REENGAGEMENT_ERRORS and config.template:
            return "template", send_template(config, params, timeout=timeout)
        raise
