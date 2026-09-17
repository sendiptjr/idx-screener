"""Lokasi file dan nilai default yang dipakai seluruh package."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
PRESET_DIR = PACKAGE_DIR / "presets"

CACHE_DIR = Path(os.environ.get("IDX_SCREENER_CACHE", PROJECT_DIR / ".cache"))
CACHE_DB = CACHE_DIR / "cache.db"

UNIVERSE_CSV = DATA_DIR / "idx_universe.csv"

# Suffix ticker IDX di Yahoo Finance: BBCA -> BBCA.JK
YAHOO_SUFFIX = ".JK"

# Berapa lama data boleh dipakai ulang dari cache sebelum diambil ulang.
PRICE_TTL_HOURS = 6
FUNDAMENTAL_TTL_HOURS = 24

# Riwayat harga yang diambil; 2 tahun cukup untuk SMA200 + return 1 tahun.
HISTORY_PERIOD = "2y"

# Jumlah ticker per permintaan ke Yahoo agar tidak kena rate limit.
DOWNLOAD_CHUNK = 40

# Fundamental diambil satu permintaan per emiten, jadi paralelismenya dibatasi.
# Dengan 8 pekerja, Yahoo mulai menolak di sekitar emiten ke-600.
FUNDAMENTAL_WORKERS = 4

# Jeda sebelum percobaan ulang saat Yahoo mengirim "Too Many Requests".
RETRY_DELAYS = (3.0, 9.0, 20.0)
