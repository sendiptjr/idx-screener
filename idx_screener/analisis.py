"""Terjemahkan berita umum jadi emiten yang mungkin terdampak, lewat Claude.

Berbeda dengan `news.py` yang hanya mencocokkan nama, modul ini menalar:
"Krakatau meletus, abu vulkanik menyebar" -> gangguan pernapasan -> farmasi dan
rumah sakit. Penalaran semacam itu tidak mungkin didaftarkan lebih dulu di
tabel kata kunci, sebab justru peristiwa yang tak terduga yang paling bernilai.

Perlu ditegaskan: hasilnya HIPOTESIS, bukan sinyal. Tidak ada pengukuran di
belakangnya - tidak seperti preset di `presets/*.yaml` yang diuji ke dua tahun
data. Kaitan berita ke harga sering sudah habis diperdagangkan dalam hitungan
menit, atau tidak pernah terwujud sama sekali.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .news import Berita
from .universe import Emiten

# Haiku dipilih karena pemanggilannya sekali sehari atas ~50 judul; ongkosnya
# sekitar seperseratus sen. Untuk penalaran dampak lapis kedua yang lebih
# tajam, setel ANTHROPIC_MODEL=claude-opus-5 - lebih mahal, lebih baik.
MODEL_BAWAAN = "claude-haiku-4-5"
MAX_BERITA = 60


class AnalisisError(RuntimeError):
    """Kunci API tidak ada, atau Claude tidak bisa dihubungi."""


@dataclass
class Dampak:
    ticker: str
    alasan: str


@dataclass
class Tema:
    peristiwa: str
    rantai: str                       # rantai sebabnya, dalam satu kalimat
    arah: str                         # "positif" | "negatif"
    keyakinan: str                    # "tinggi" | "sedang" | "rendah"
    emiten: list[Dampak] = field(default_factory=list)


SISTEM = """Anda analis pasar saham Indonesia. Dari judul-judul berita semalam,
temukan peristiwa yang berpotensi menggerakkan emiten tertentu di Bursa Efek
Indonesia, termasuk lewat dampak tidak langsung.

Contoh penalaran tidak langsung yang diharapkan: gunung meletus dan abu
vulkanik menyebar -> gangguan pernapasan meningkat -> emiten farmasi dan rumah
sakit; banjir besar -> kerusakan infrastruktur -> emiten konstruksi dan semen,
tetapi merugikan asuransi umum.

Aturan yang wajib dipatuhi:
- Hanya gunakan kode emiten dari daftar yang diberikan. Jangan mengarang kode.
- Lewati berita yang tidak punya kaitan masuk akal ke emiten mana pun. Lebih
  baik mengembalikan daftar kosong daripada mengada-ada.
- Berita makro umum (IHSG naik/turun, rupiah, suku bunga) hanya disertakan bila
  dampaknya jelas mengarah ke kelompok emiten tertentu, bukan ke pasar secara
  keseluruhan.
- Nilai keyakinan dengan jujur. "tinggi" hanya untuk kaitan langsung dan
  jelas; gunakan "rendah" bila rantai sebabnya panjang atau spekulatif.
- Paling banyak 5 tema, dan paling banyak 4 emiten per tema.

Jawab HANYA dengan JSON, tanpa teks pembuka atau penutup, dalam bentuk:
{"tema": [{"peristiwa": "...", "rantai": "...", "arah": "positif|negatif",
"keyakinan": "tinggi|sedang|rendah",
"emiten": [{"ticker": "KLBF", "alasan": "..."}]}]}"""


def _daftar_emiten(universe: list[Emiten]) -> str:
    return "\n".join(
        f"{e.ticker}|{e.name or '-'}|{e.sector or '-'}" for e in universe
    )


def _ambil_json(teks: str) -> dict:
    """Ambil objek JSON dari jawaban, tahan terhadap pagar kode."""
    teks = teks.strip()
    teks = re.sub(r"^```(?:json)?|```$", "", teks, flags=re.M).strip()
    awal, akhir = teks.find("{"), teks.rfind("}")
    if awal == -1 or akhir == -1:
        raise AnalisisError("Jawaban Claude tidak memuat JSON.")
    return json.loads(teks[awal:akhir + 1])


def analisis_berita(
    berita: list[Berita],
    universe: list[Emiten],
    *,
    model: str | None = None,
    max_berita: int = MAX_BERITA,
    timeout: float = 120.0,
) -> list[Tema]:
    """Kembalikan tema dampak beserta emiten yang mungkin terkena."""
    if not berita:
        return []
    try:
        import anthropic
    except ImportError as exc:                              # pragma: no cover
        raise AnalisisError("Paket 'anthropic' belum terpasang.") from exc
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise AnalisisError("ANTHROPIC_API_KEY belum diset.")

    sah = {e.ticker for e in universe}
    judul = "\n".join(
        f"- [{b.waktu:%d/%m %H:%M}] {b.judul}" for b in berita[:max_berita]
    )
    client = anthropic.Anthropic(timeout=timeout)
    try:
        response = client.messages.create(
            model=model or os.environ.get("ANTHROPIC_MODEL", MODEL_BAWAAN),
            max_tokens=4000,
            system=[{
                "type": "text",
                "text": SISTEM + "\n\nDaftar emiten (kode|nama|sektor):\n"
                        + _daftar_emiten(universe),
                # Daftar emiten sama tiap hari; taruh di depan agar bisa di-cache.
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": f"Judul berita semalam:\n{judul}"}],
        )
    except Exception as exc:
        raise AnalisisError(f"Gagal menghubungi Claude: {exc}") from exc

    teks = "".join(b.text for b in response.content if b.type == "text")
    data = _ambil_json(teks)

    hasil: list[Tema] = []
    for item in data.get("tema", [])[:5]:
        dampak = [
            Dampak(ticker=str(d.get("ticker", "")).upper(), alasan=str(d.get("alasan", "")))
            for d in item.get("emiten", [])[:4]
            # Kode karangan dibuang, bukan ditampilkan apa adanya.
            if str(d.get("ticker", "")).upper() in sah
        ]
        if not dampak:
            continue
        hasil.append(Tema(
            peristiwa=str(item.get("peristiwa", "")).strip(),
            rantai=str(item.get("rantai", "")).strip(),
            arah=str(item.get("arah", "")).strip().lower() or "positif",
            keyakinan=str(item.get("keyakinan", "")).strip().lower() or "rendah",
            emiten=dampak,
        ))
    return hasil


def format_tema(tema: list[Tema], *, snapshot=None, lolos_saringan=None) -> str:
    """Rangkai tema jadi pesan."""
    from .report import fmt

    lolos_saringan = lolos_saringan or {}
    panah = {"positif": "▲", "negatif": "▼"}
    kepala = ["*Dampak berita semalam*", ""]
    if not tema:
        kepala.append("_Tidak ada peristiwa yang berkaitan jelas dengan emiten._")
        return "\n".join(kepala)

    for nomor, t in enumerate(tema, start=1):
        kepala.append(f"{nomor}. {panah.get(t.arah, '•')} {t.peristiwa}  _({t.keyakinan})_")
        if t.rantai:
            kepala.append(f"    {t.rantai}")
        for d in t.emiten:
            baris = f"    • {d.ticker}"
            if snapshot is not None and d.ticker in snapshot.index:
                r = snapshot.loc[d.ticker]
                baris += f" Rp {fmt(r.get('close'), 'close')} · {fmt(r.get('change_pct'), 'change_pct')}"
            if d.ticker in lolos_saringan:
                baris += " ← lolos " + ", ".join(lolos_saringan[d.ticker])
            kepala.append(baris)
            if d.alasan:
                kepala.append(f"      {d.alasan}")
        kepala.append("")

    kepala.append("_Ini hipotesis hasil penalaran Claude atas judul berita, BUKAN "
                  "rekomendasi dan tidak punya pengukuran apa pun di belakangnya - "
                  "berbeda dengan preset yang diuji ke dua tahun data. Kaitan berita "
                  "ke harga kerap sudah habis diperdagangkan sebelum Anda membaca ini._")
    return "\n".join(kepala)
