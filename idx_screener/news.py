"""Cari emiten yang disebut berita semalam.

Alurnya: ambil RSS berita pasar, saring ke jendela waktu (bawaan 15.00 hari
bursa sebelumnya sampai 08.00 hari ini), lalu cocokkan judul dan ringkasannya
ke daftar emiten IDX.

Pencocokan ini TIDAK punya pengukuran di belakangnya. Preset di
`presets/*.yaml` diuji ke dua tahun data; "disebut berita" tidak. Karena itu
hasilnya disajikan sebagai informasi, dan yang diberi tekanan adalah
irisannya dengan saringan yang memang terukur.
"""

from __future__ import annotations

import email.utils
import re
from dataclasses import dataclass, field

import pandas as pd
import requests

from .universe import Emiten

# Hanya sumber yang benar-benar melayani permintaan otomatis. Kontan dan
# Bisnis.com membalas 403, jadi tidak disertakan.
SUMBER_RSS = (
    ("CNBC Indonesia", "https://www.cnbcindonesia.com/market/rss"),
    ("CNBC Investment", "https://www.cnbcindonesia.com/investment/rss"),
)

ZONA = "Asia/Jakarta"

# Nama pendek yang lazim dipakai media tetapi tidak ada di kolom nama resmi.
ALIAS = {
    "bri": "BBRI", "bca": "BBCA", "bni": "BBNI", "btn": "BBTN",
    "bank mandiri": "BMRI", "mandiri": "BMRI", "telkom": "TLKM",
    "antam": "ANTM", "indofood": "INDF", "unilever": "UNVR",
    "gojek": "GOTO", "gotoco": "GOTO", "tokopedia": "GOTO",
    "astra": "ASII", "adaro": "ADRO", "vale": "INCO", "bukalapak": "BUKA",
    "garuda": "GIAA", "pertamina geothermal": "PGEO", "pgn": "PGAS",
    "semen indonesia": "SMGR", "chandra asri": "TPIA", "barito": "BRPT",
    "amman": "AMMN", "merdeka": "MDKA", "timah": "TINS", "bukit asam": "PTBA",
}

# Kata yang terlalu umum untuk dijadikan penanda emiten sendirian. Tanpa
# daftar ini, "Perusahaan Gas Negara" akan tersangkut di tiap berita yang
# memuat kata "perusahaan", dan "Asuransi Bina Dana Arta" di tiap berita
# asuransi.
TERLALU_UMUM = {
    "bank", "indonesia", "energi", "sejahtera", "makmur", "jaya", "sentosa",
    "abadi", "mandiri", "utama", "nusantara", "internasional", "global",
    "prima", "karya", "sukses", "indo", "tbk", "persero",
    "mineral", "resource", "resources", "asuransi", "industri", "industries",
    "teknologi", "perusahaan", "sentral", "digital", "sumber", "sumberdaya",
    "kawasan", "pembangunan", "transportasi", "telekomunikasi", "properti",
    "investama", "sejahtra", "perdana", "propertindo", "agung", "mulia",
    "pratama", "lestari", "manufaktur", "perkasa", "sarana", "solusi",
    "nasional", "pacific", "pasifik", "raya", "central", "capital",
}


@dataclass
class Berita:
    judul: str
    tautan: str
    waktu: pd.Timestamp
    sumber: str
    ringkasan: str = ""

    @property
    def teks(self) -> str:
        return f"{self.judul} {self.ringkasan}"


@dataclass
class Sebutan:
    ticker: str
    nama: str
    berita: list[Berita] = field(default_factory=list)


# --------------------------------------------------------------------------
# jendela waktu


def jendela_semalam(
    sekarang: pd.Timestamp | None = None,
    *,
    jam_mulai: int = 15,
    jam_selesai: int = 8,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Dari jam_mulai hari bursa sebelumnya sampai jam_selesai hari ini.

    Hari bursa sebelumnya, bukan kemarin: dijalankan Senin pagi, jendelanya
    dimulai Jumat sore - kalau tidak, berita akhir pekan hilang seluruhnya.
    """
    now = sekarang if sekarang is not None else pd.Timestamp.now(tz=ZONA)
    selesai = now.normalize() + pd.Timedelta(hours=jam_selesai)
    if now < selesai:
        selesai = now
    mulai = (selesai.normalize() - pd.offsets.BDay(1)).tz_localize(None)
    mulai = pd.Timestamp(mulai, tz=now.tz) + pd.Timedelta(hours=jam_mulai)
    return mulai, selesai


# --------------------------------------------------------------------------
# pengambilan


def _isi_tag(tag: str, blok: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", blok, re.S)
    if not m:
        return ""
    teks = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", teks).strip()


def urai_rss(xml: str, sumber: str) -> list[Berita]:
    hasil = []
    for blok in re.findall(r"<item>(.*?)</item>", xml, re.S):
        judul = _isi_tag("title", blok)
        tanggal = _isi_tag("pubDate", blok)
        if not judul or not tanggal:
            continue
        try:
            waktu = pd.Timestamp(email.utils.parsedate_to_datetime(tanggal))
        except (TypeError, ValueError):
            continue
        if waktu.tz is None:
            waktu = waktu.tz_localize(ZONA)
        hasil.append(Berita(
            judul=judul,
            tautan=_isi_tag("link", blok),
            waktu=waktu.tz_convert(ZONA),
            sumber=sumber,
            ringkasan=_isi_tag("description", blok)[:400],
        ))
    return hasil


def ambil_berita(
    mulai: pd.Timestamp,
    selesai: pd.Timestamp,
    *,
    sumber=SUMBER_RSS,
    timeout: float = 20.0,
) -> list[Berita]:
    """Berita dari semua sumber yang jatuh di dalam jendela, terbaru dulu."""
    semua: list[Berita] = []
    for nama, url in sumber:
        try:
            response = requests.get(
                url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}
            )
            if response.status_code != 200:
                continue
            semua += urai_rss(response.text, nama)
        except requests.RequestException:
            continue      # satu sumber mati tidak boleh menggugurkan sisanya
    di_jendela = [b for b in semua if mulai <= b.waktu <= selesai]
    di_jendela.sort(key=lambda b: b.waktu, reverse=True)
    return di_jendela


# --------------------------------------------------------------------------
# pencocokan ke emiten


def _normal(teks: str) -> str:
    return re.sub(r"[^a-z0-9]", "", teks.lower())


def penanda_nama(nama: str) -> tuple[set[str], set[str]]:
    """Penanda khas sebuah nama perusahaan: (kata tunggal, gabungan kata).

    Dikembalikan dua jenis karena cara mencocokkannya berbeda. Kata tunggal
    dicocokkan utuh - "resource" tidak boleh tersangkut di "Bayan Resources".
    Gabungan kata dicocokkan sebagai potongan, supaya "Medco Energi" tetap
    kena pada penulisan media "MedcoEnergi".
    """
    kata = [k for k in re.split(r"\s+", nama.strip()) if k]
    if not kata:
        return set(), set()

    tunggal: set[str] = set()
    gabungan: set[str] = set()

    pertama = _normal(kata[0])
    # Makin pendek sebuah kata, makin besar peluangnya itu kata umum yang
    # kebetulan mengawali nama perusahaan - karena itu batasnya 8 huruf.
    if len(pertama) >= 8 and pertama not in TERLALU_UMUM:
        tunggal.add(pertama)
    elif len(kata) == 1 and len(pertama) >= 5 and pertama not in TERLALU_UMUM:
        tunggal.add(pertama)

    if len(kata) >= 2:
        dua = _normal("".join(kata[:2]))
        if len(dua) >= 9:
            gabungan.add(dua)
    if len(kata) >= 3:
        tiga = _normal("".join(kata[:3]))
        if len(tiga) >= 12:
            gabungan.add(tiga)
    return tunggal, gabungan


def _kata_utuh(teks: str) -> set[str]:
    """Kata-kata berita, dinormalkan - untuk penanda satu kata."""
    return {_normal(k) for k in re.findall(r"[A-Za-z]+", teks)}


def cocokkan(berita: list[Berita], universe: list[Emiten]) -> list[Sebutan]:
    """Petakan berita ke emiten lewat kode ticker, nama, dan alias."""
    per_ticker = {e.ticker: e for e in universe}
    tunggal: dict[str, str] = {}
    gabungan: dict[str, str] = {}
    for e in universe:
        satu, gabung = penanda_nama(e.name or "")
        for t in satu:
            tunggal.setdefault(t, e.ticker)
        for g in gabung:
            gabungan.setdefault(g, e.ticker)

    hasil: dict[str, Sebutan] = {}

    def catat(ticker: str, item: Berita) -> None:
        emiten = per_ticker.get(ticker)
        if emiten is None:
            return
        sebutan = hasil.setdefault(ticker, Sebutan(ticker, emiten.name or ticker))
        if item not in sebutan.berita:
            sebutan.berita.append(item)

    for item in berita:
        teks = item.teks
        rata = _normal(teks)
        kata_berita = _kata_utuh(teks)

        # 1. Kode emiten ditulis apa adanya - paling meyakinkan.
        for kode in set(re.findall(r"\b[A-Z]{4}\b", teks)):
            if kode in per_ticker:
                catat(kode, item)

        # 2. Nama perusahaan.
        for tanda, ticker in tunggal.items():
            if tanda in kata_berita:
                catat(ticker, item)
        for tanda, ticker in gabungan.items():
            if tanda in rata:
                catat(ticker, item)

        # 3. Nama pendek yang lazim di media.
        for alias, ticker in ALIAS.items():
            potongan = _normal(alias)
            kena = potongan in rata if " " in alias else potongan in kata_berita
            if kena:
                catat(ticker, item)

    return sorted(hasil.values(), key=lambda s: (-len(s.berita), s.ticker))


# --------------------------------------------------------------------------
# perangkaian pesan


def format_berita(
    sebutan: list[Sebutan],
    *,
    mulai: pd.Timestamp,
    selesai: pd.Timestamp,
    jumlah_berita: int,
    snapshot: pd.DataFrame | None = None,
    lolos_saringan: dict[str, list[str]] | None = None,
    top: int = 12,
) -> str:
    """Pesan daftar emiten yang disebut berita, beserta irisannya ke saringan."""
    from .report import fmt

    lolos_saringan = lolos_saringan or {}
    kepala = [
        "*Saham yang disebut berita semalam*",
        f"{mulai:%d %b %H.%M} - {selesai:%d %b %H.%M} WIB · {jumlah_berita} berita",
        f"{len(sebutan)} emiten disebut",
        "",
    ]
    if not sebutan:
        kepala.append("_Tidak ada emiten yang disebut berita di jendela ini._")
        return "\n".join(kepala)

    # Yang juga lolos saringan terukur ditaruh di depan - itu bagian yang
    # punya bukti, sisanya sekadar informasi.
    berurut = sorted(
        sebutan,
        key=lambda s: (-len(lolos_saringan.get(s.ticker, [])), -len(s.berita), s.ticker),
    )
    for nomor, s in enumerate(berurut[:top], start=1):
        tanda = ""
        if s.ticker in lolos_saringan:
            tanda = "  ← lolos " + ", ".join(lolos_saringan[s.ticker])
        kepala.append(f"{nomor}. {s.ticker} · {s.nama}{tanda}")

        if snapshot is not None and s.ticker in snapshot.index:
            baris = snapshot.loc[s.ticker]
            harga = fmt(baris.get("close"), "close")
            ubah = fmt(baris.get("change_pct"), "change_pct")
            kepala.append(f"    Rp {harga} · {ubah}")

        for b in s.berita[:2]:
            kepala.append(f"    • {b.judul}")

    if len(berurut) > top:
        kepala.append(f"_...dan {len(berurut) - top} emiten lain._")

    kepala += ["", "_Ini daftar sebutan berita, bukan rekomendasi. Tidak ada "
                   "pengukuran di belakangnya - berbeda dengan preset yang diuji "
                   "ke dua tahun data. Tanda 'lolos' menunjukkan emiten itu juga "
                   "memenuhi saringan yang memang terukur; sisanya hanya informasi._"]
    return "\n".join(kepala)
