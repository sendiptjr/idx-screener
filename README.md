# Screener Saham IDX

Penyaring saham Bursa Efek Indonesia berbasis data harga dan fundamental, lengkap
dengan CLI, antarmuka web, dan backtest sederhana. Data diambil dari Yahoo Finance
(kode emiten memakai akhiran `.JK`) lalu disimpan di cache SQLite lokal, sehingga
pemakaian berikutnya bisa berjalan tanpa jaringan.

```
idxscreen screen --preset value --funnel
```

## Isi

- 845 emiten - seluruh saham IDX yang dikenali Yahoo, diperbarui otomatis
- 78 metrik: valuasi, profitabilitas, likuiditas, indikator teknikal, return, volatilitas
- Bahasa filter sederhana: `per < 12 and roe > 15 and close > sma200`
- 11 preset strategi siap pakai (value, growth, dividen, momentum, breakout, …)
- Skor peringkat gabungan berbobot
- Backtest berbasis harga dengan penolakan otomatis terhadap look-ahead bias
- Antarmuka web Streamlit dengan grafik candlestick, volume, dan RSI
- Ekspor CSV / JSON / Excel / Markdown

## Pemasangan

```bash
git clone <repo> idx-screener && cd idx-screener
make setup          # membuat .venv lalu memasang dependensi
make update         # mengunduh data awal (~80 detik untuk 845 emiten)
```

Tanpa `make`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e . -r requirements.txt
.venv/bin/idxscreen update
```

## Pemakaian CLI

```bash
# strategi siap pakai
idxscreen screen --preset value
idxscreen screen --preset momentum --funnel      # tampilkan emiten yang gugur di tiap syarat

# filter sendiri, bisa ditumpuk
idxscreen screen -f "avg_value_20 > 1e10" -f "rsi14 < 35" -f "close > sma200" --sort rsi14 --asc

# preset + syarat tambahan
idxscreen screen --preset dividend -f "market_cap > 1e13" --limit 10

# beberapa emiten saja
idxscreen screen -t "BBCA,BBRI,BMRI,BBNI" -f "per > 0" --columns ticker,close,per,pbv,roe

# skor gabungan: ROE tinggi + PER rendah + momentum
idxscreen rank --weights "roe=1,per=-1,pbv=-0.5,ret_3m=0.5" --limit 20

# detail satu emiten
idxscreen show TLKM

# ekspor
idxscreen screen --preset growth --export out/growth.csv

# lain-lain
idxscreen presets            # daftar strategi
idxscreen fields rsi         # cari nama metrik
idxscreen update             # segarkan cache
idxscreen update --deep 600  # tarik data rinci untuk lebih banyak emiten
idxscreen cache              # ukuran dan isi cache
idxscreen fetch-universe     # perbarui daftar emiten dari screener Yahoo
idxscreen sync-universe      # perbarui nama & sektor emiten satu per satu
```

Untuk hasil cepat, batasi ke daftar likuid kurasi (174 emiten):

```bash
idxscreen screen --universe data/idx_liquid.csv --preset value
```

Opsi yang berlaku di hampir semua perintah:

| Opsi | Arti |
|---|---|
| `--offline` | hanya baca cache, tidak menyentuh jaringan |
| `--refresh` | paksa ambil ulang dari Yahoo |
| `--universe berkas.csv` | pakai daftar emiten sendiri |
| `--tickers "BBCA,TLKM"` | batasi ke kode tertentu |
| `--include-unknown` | loloskan emiten yang sebagian metriknya kosong |

## Antarmuka web

```bash
make app        # atau: .venv/bin/streamlit run app.py
```

Sidebar berisi pemilih strategi, kotak filter, pembatas sektor, pengurutan, dan
tombol muat ulang data. Halaman utama menampilkan tabel hasil, corong filter,
peta sebaran dua metrik (mis. PER vs ROE), serta grafik candlestick + volume +
RSI untuk emiten yang dipilih.

## Dua lapis data

Memanggil `Ticker.info` Yahoo satu per satu untuk 845 emiten kena rate limit di
sekitar emiten ke-600 dan makan 5+ menit. Karena itu fundamental dibagi dua:

| Lapis | Isi | Biaya | Cakupan |
|---|---|---|---|
| **dasar** | PER, PBV, EPS, nilai buku, ROE, kapitalisasi, dividen, sektor | ~15 permintaan untuk seluruh bursa | semua 845 emiten |
| **rinci** | DER, ROA, margin, pertumbuhan, PEG, EV/EBITDA, beta, sub-industri | 1 permintaan per emiten | 300 teratas (`update --deep N`) |

Lapis dasar diambil dari screener Yahoo yang mengembalikan 250 emiten sekaligus;
ROE-nya diturunkan dari EPS dibagi nilai buku per saham (perhitungan resmi
memakai rata-rata ekuitas, jadi angkanya pendekatan — untuk BBCA 21,4% vs 21,8%).
Begitu lapis rinci tersedia, nilai resminya menimpa yang turunan; keduanya bisa
berbeda jauh kalau EPS yang dipakai Yahoo sudah kedaluwarsa (OLIV: +5,1% turunan
vs −21,8% resmi).

Saat screening memakai metrik lapis rinci, mesin menundanya: filter murah
dijalankan dulu, lalu data rinci hanya ditarik untuk kandidat yang tersisa.
Preset `value` misalnya mengerucutkan 845 → 42 emiten dengan PER/PBV/ROE, baru
menarik DER untuk 42 itu. Batasnya diatur `--max-deep`.

## Bahasa filter

Satu baris = satu syarat, dan semuanya harus terpenuhi (AND).

```
per > 0 and per < 12                 perbandingan dan operator logika
close > sma200                       metrik dibandingkan dengan metrik lain
rsi14 between 40 and 60              rentang
sector in ["Keuangan", "Energi"]     keanggotaan (tidak peduli huruf besar/kecil)
"bank" in lower(industry)            pencocokan potongan teks
not (der > 1.5)                      negasi
avg_value_20 > 5e9                   notasi ilmiah
abs(dist_52w_high) < 3               fungsi: abs, min, max, round, len, lower
```

Ekspresi diperiksa lewat AST dengan daftar putih, bukan `eval`, jadi filter dari
file preset maupun input web tidak bisa menjalankan kode lain.

**Penanganan data kosong.** Kalau sebuah metrik tidak tersedia (Yahoo tidak
mengirim PER untuk emiten rugi, misalnya), syarat itu bernilai *tidak diketahui*
dan emitennya dibuang — kecuali dijalankan dengan `--include-unknown`. Logikanya
tetap hemat: `per > 100 and pbv < 2` langsung `False` bila PER 8 walau PBV kosong.

Daftar lengkap nama metrik: `idxscreen fields`.

## Preset

| Nama | Isi singkat |
|---|---|
| `value` | PER < 12, PBV < 1,8, ROE > 10%, DER < 1,5 |
| `growth` | pertumbuhan pendapatan > 10% dan laba > 15% |
| `dividend` | yield > 4% dengan payout masih di bawah 85% |
| `momentum` | di atas SMA20/50/200, return 3 bulan > 10% |
| `breakout` | kurang dari 5% di bawah puncak 52 minggu + volume di atas rata-rata |
| `pullback` | tren panjang naik tapi RSI < 40 dan menempel batas bawah Bollinger |
| `golden-cross` | SMA50 memotong ke atas SMA200 dalam 10 hari terakhir |
| `volume-spike` | volume > 3x rata-rata dengan harga menguat |
| `bb-squeeze` | Bollinger paling sempit dalam 6 bulan |
| `blue-chip` | kapitalisasi > Rp 50 T dan sangat likuid |
| `lonjakan` | melonjak >7% hari ini dan belum terkunci ARA (horizon 1-2 minggu) |
| `lonjakan-tenang` | sama, tapi kenaikannya tanpa lonjakan volume - varian terkuat |
| `syariah-proxy` | perkiraan saringan syariah — **bukan** DES resmi OJK |

Preset adalah berkas YAML di [idx_screener/presets/](idx_screener/presets/).
Menambah strategi cukup menyalin satu berkas:

```yaml
name: bank-murah
title: Bank dengan valuasi rendah
description: Bank likuid dengan PBV di bawah rata-rata sektornya.
filters:
  - sector in ["Keuangan"]
  - pbv > 0 and pbv < 1.2
  - roe > 12
  - avg_value_20 > 5e9
sort: { by: pbv, ascending: true }
limit: 20
columns: [ticker, name, close, pbv, per, roe, dividend_yield]
```

### Catatan soal preset lonjakan

Kedua preset itu disusun dari pengukuran, bukan naluri. Pada 2 tahun data
(845 emiten, Okt 2024 - Sep 2026), saham likuid yang melonjak >7% tanpa terkunci
ARA, dibandingkan pasar pada horizon 2 minggu:

| Varian | n | Return 2 minggu | Unggul di |
|---|---|---|---|
| pasar (pembanding) | 60.119 | +0,71% | - |
| dasar | 3.428 | +3,29% | 8 dari 8 kuartal |
| + volume di bawah rata-rata | 1.861 | **+4,25%** | 8 dari 8 kuartal |
| + volume di atas 2x rata-rata | 1.567 | +2,14% | 4 dari 8 kuartal |

Menyaring volume tinggi - naluri yang paling umum - justru memangkas keunggulan
sampai setara lempar koin. Pada horizon 1 hari, seluruh varian merugi setelah
ongkos; yang menguntungkan besok hanyalah saham yang terkunci ARA sore ini, dan
saham itu tidak bisa dibeli.

## Backtest

```bash
idxscreen backtest --preset momentum --periods 12 --hold 21
```

Tiap periode rebalancing, strategi dijalankan ulang dengan data yang tersedia
sampai tanggal itu, lalu return selama masa tahan dibandingkan dengan rata-rata
seluruh emiten yang dipindai.

Yang perlu disadari sebelum mempercayai angkanya:

- **Filter fundamental ditolak secara default.** Yahoo hanya menyediakan nilai
  fundamental terkini, bukan nilai pada tanggal rebalancing, sehingga memakainya
  berarti memasukkan informasi masa depan. `--allow-fundamentals` tersedia bila
  biasnya memang disadari.
- Biaya transaksi, slippage, dan dividen tidak dihitung.
- Emiten yang sudah delisting tidak ada dalam daftar, jadi hasilnya condong
  optimistis (survivorship bias).
- Pembanding "pasar" adalah rata-rata sama-rata emiten dalam daftar, bukan IHSG
  yang berbobot kapitalisasi.

## Daftar emiten

| Berkas | Isi | Kapan dipakai |
|---|---|---|
| [data/idx_universe.csv](data/idx_universe.csv) | 845 emiten, seluruh IDX | bawaan |
| [data/idx_liquid.csv](data/idx_liquid.csv) | 174 emiten likuid, sektor kurasi manual | saat ingin cepat |

IDX memblokir akses otomatis ke daftar emiten resminya lewat Cloudflare, jadi
daftarnya disusun dari screener Yahoo:

```bash
idxscreen fetch-universe
```

Perintah itu menggabungkan, bukan menimpa: screener Yahoo kadang tidak memuat
emiten yang masih aktif (ADHI, WIKA, FASW, HITS, INAF, SMCB pernah absen), jadi
entri lama dipertahankan kecuali dijalankan dengan `--prune`.

Daftar sendiri juga bisa dipakai — format CSV `ticker,name,sector`, dua kolom
terakhir opsional:

```bash
idxscreen screen --universe daftar-saya.csv --preset value
```

## Struktur kode

```
idx_screener/
├── cli.py              perintah baris perintah (typer)
├── screener.py         mesin: data -> metrik -> filter -> urut
├── metrics.py          satu baris metrik per emiten + kamus penjelasannya
├── indicators.py       SMA, EMA, RSI, MACD, ATR, Bollinger, Stochastic, MFI
├── rules.py            evaluator ekspresi filter berbasis AST
├── presets.py          pemuat strategi YAML
├── backtest.py         uji historis + penjaga look-ahead bias
├── report.py           tabel terminal, format angka Indonesia, ekspor
├── cache.py            cache SQLite untuk harga dan fundamental
├── universe.py         daftar emiten
└── providers/yahoo.py  pengambilan data (massal + rinci) & penyeragaman satuan
app.py                  antarmuka web Streamlit
tests/                  76 test, seluruhnya memakai data sintetis
```

Menambah sumber data lain cukup menyediakan kelas dengan dua metode,
`prices(emiten)` dan `fundamentals(emiten)`, seperti `FakeProvider` di
[tests/conftest.py](tests/conftest.py).

## Test

```bash
make test        # 76 test, < 1 detik, tanpa jaringan
```

## Batasan data

- Sumbernya Yahoo Finance: harga bisa tertunda dan angka fundamental kadang
  keliru atau kosong, terutama untuk emiten kecil. Pakai `idxscreen show KODE`
  untuk memeriksa satu per satu sebelum mengambil keputusan.
- Harga tidak disesuaikan dengan aksi korporasi, sehingga return di sekitar
  stock split atau dividen besar bisa menyesatkan.
- Tidak ada data asing/domestik (foreign flow), frekuensi transaksi, order book,
  maupun laporan keuangan per kuartal.
- Cakupan 845 emiten berasal dari screener Yahoo; IDX sendiri mencatat lebih
  banyak emiten, dan yang paling kecil atau baru IPO bisa belum terdaftar di
  sana. Tambahkan manual ke CSV bila perlu.
- Metrik lapis rinci (DER, margin, pertumbuhan) hanya tersedia untuk emiten yang
  sudah ditarik data rincinya. Emiten tanpa data itu akan gugur dari filter yang
  memakainya — pakai `--include-unknown` atau naikkan `update --deep N`.
- `dividend_yield` mengikuti angka indikatif Yahoo; `dividend_yield_ttm` dihitung
  sendiri dari nominal dividen 12 bulan terakhir dibagi harga.

## Catatan

Alat ini untuk riset pribadi, bukan rekomendasi jual atau beli. Screening hanya
mempersempit daftar yang layak dibaca lebih lanjut — laporan keuangan, aksi
korporasi, dan keterbukaan informasi tetap perlu dibaca sendiri.
