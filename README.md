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
- Kiriman WhatsApp terjadwal lewat Meta Cloud API
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

# kirim preset lonjakan ke WhatsApp (lihat bagian "Kirim ke WhatsApp tiap pagi")
idxscreen notify --preset lonjakan --dry-run

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

## Kirim ke WhatsApp tiap pagi

`idxscreen notify` menjalankan sebuah preset lalu mengirim hasilnya ke WhatsApp
lewat **Meta Cloud API**. Bawaannya preset `lonjakan`.

```bash
# lihat pesannya dulu, tanpa mengirim apa pun
idxscreen notify --dry-run --offline

# kirim beneran
idxscreen notify --preset lonjakan --top 10
```

| Opsi | Arti |
|---|---|
| `--preset` | preset yang dikirim (bawaan `lonjakan`) |
| `--to` | nomor tujuan; `081…`, `+62 …`, dan `62…` sama saja |
| `--top` | berapa saham teratas di pesan teks (bawaan 8); template selalu 8 baris |
| `--mode` | `auto` (bawaan) / `text` / `template` |
| `--dry-run` | cetak pesannya, jangan kirim |
| `--max-stale-days` | batalkan bila data bursa lebih tua dari ini (bawaan 5) |
| `--skip-empty` | diam saja bila tidak ada yang lolos |

### Kenapa harus lewat template

Cloud API hanya mengizinkan teks bebas di dalam **jendela 24 jam** setelah
nomor tujuan mengirim pesan ke nomor bisnis. Kiriman terjadwal jelas di luar
jendela itu, jadi jalurnya wajib **template yang sudah disetujui Meta**. Mode
`auto` memakai template bila namanya diset; mode `text` mencoba teks bebas dan
otomatis jatuh ke template kalau Meta menolak dengan kode 131047.

Nilai parameter template tidak boleh memuat baris baru - dicoba langsung ke
Cloud API dan ditolak dengan `132018: Param text cannot have new-line/tab
characters or more than 4 consecutive spaces`. Karena itu baris barunya harus
berada di badan template, satu placeholder per baris. Parameter berisi **satu
spasi** diterima, jadi baris yang tidak terpakai di hari sepi dibiarkan kosong.

### Template yang harus dibuat

Di WhatsApp Manager → Manage templates → Create template:

- **Name**: `idx_lonjakan_harian`
- **Category**: Utility (bukan Marketing - lebih murah dan lebih jarang ditolak)
- **Language**: Indonesian (`id`)
- **Placeholder**: pilih **positional** (`{{1}}`), bukan named (`{{tanggal}}`)

Badan template, salin persis:

```
*Lonjakan yang masih bisa dibeli*
Penutupan {{1}}
{{2}} dari {{3}} emiten lolos

1. {{4}}
2. {{5}}
3. {{6}}
4. {{7}}
5. {{8}}
6. {{9}}
7. {{10}}
8. {{11}}

{{12}}
Sumber: Yahoo Finance, harga penutupan.
```

Footer (kolom terpisah, teks tetap):

```
Bukan rekomendasi beli. Horizon 1-2 minggu.
```

Nomor urut sengaja ditulis sebagai teks tetap di template, bukan ikut di dalam
parameter: badan yang isinya hampir seluruhnya placeholder sering ditolak saat
review. Konsekuensinya, di hari yang cuma meloloskan dua saham, nomor 3-8 tetap
muncul tanpa isi.

Contoh nilai yang diminta Meta sebelum tombol Submit menyala:

| | |
|---|---|
| `{{1}}` | `Kamis, 17 Sep 2026` |
| `{{2}}` | `11` |
| `{{3}}` | `845` |
| `{{4}}` | `TEBE +18,73% · Rp 1.965 · sisa ARA 6,27%` |
| `{{5}}` … `{{11}}` | baris saham berikutnya, bentuk sama |
| `{{12}}` | `+3 lainnya: JARR, ICON, KETR` |

Jumlah baris saham dipatok 8 (`SLOT_SAHAM` di
[notify.py](idx_screener/notify.py)). Mengubahnya berarti mengubah badan
template di Meta juga - keduanya harus cocok.

### Kredensial

Empat variabel lingkungan; ambil dari Meta for Developers → aplikasi Anda →
WhatsApp → API Setup.

```bash
export WA_TOKEN=EAAG...            # token permanen milik System User, bukan token 24 jam
export WA_PHONE_NUMBER_ID=1234567  # Phone number ID, bukan nomor teleponnya
export WA_TO=6281234567890         # nomor tujuan, wajib terdaftar dulu saat masih mode test
export WA_TEMPLATE=idx_lonjakan_harian
# opsional: WA_TEMPLATE_LANG (bawaan id), WA_API_VERSION (bawaan v25.0)
```

Selama aplikasi Meta masih berstatus *development*, nomor tujuan harus
didaftarkan dulu sebagai penerima uji di API Setup. Setelah aplikasi live,
siapa pun bisa dikirimi.

### Penjadwalan

[.github/workflows/wa-lonjakan.yml](.github/workflows/wa-lonjakan.yml)
menjalankannya dua kali tiap hari bursa:

| Cron (UTC) | WIB | Keadaan bursa | Isi pesan |
|---|---|---|---|
| `30 1 * * 1-5` | 08:30 | belum buka (sesi I mulai 09:00) | penutupan resmi hari bursa sebelumnya |
| `0 8 * * 1-5` | 15:00 | sesi II berjalan, tutup ~15.50 | harga berjalan, **belum final** |

WIB = UTC+7 dan tidak berganti tanggal pada jam-jam ini, jadi hari cron-nya
sama dengan hari WIB - `1-5` berarti Senin-Jumat.

Pesannya menandai sendiri potret kapan yang dikirim: `penutupan Kamis, 17 Sep
2026` untuk kiriman pagi, `sesi berjalan Jumat, 18 Sep 2026 pukul 15.02 WIB`
untuk kiriman sore. Pembedanya `stale_days`: bernilai 0 berarti bar hari ini
sudah ada, artinya bursa masih berjalan.

Simpan keempat nilai di atas sebagai **Repository secrets** (`WA_TOKEN`,
`WA_PHONE_NUMBER_ID`, `WA_TO`, `WA_TEMPLATE`), lalu uji sekali lewat tombol
*Run workflow* dengan `dry_run` menyala.

Cron GitHub tidak dijamin tepat waktu - meleset 5-15 menit itu biasa. Untuk
kiriman 15:00 keterlambatan lebih terasa karena bursa tutup sekitar 15.50.
Kalau jamnya harus pas, jalankan dari cron di VPS sendiri:

```cron
30 8 * * 1-5 cd /srv/idx-screener && .venv/bin/idxscreen notify --preset lonjakan --refresh
 0 15 * * 1-5 cd /srv/idx-screener && .venv/bin/idxscreen notify --preset lonjakan --refresh
```

`--refresh` di situ bukan hiasan. Cache harga berumur 6 jam
([config.py](idx_screener/config.py)), sedangkan jarak 08:30 ke 15:00 hanya
6,5 jam. Begitu jadwal pagi telat sedikit saja, cache masih dianggap segar dan
kiriman sore akan **mengulang data pagi tanpa memberi tanda apa pun**. Memaksa
ambil ulang menutup lubang itu.

### Yang perlu disadari soal jamnya

Kiriman 08:30 memakai penutupan resmi kemarin - berguna sebagai bahan
persiapan sebelum bursa buka, tapi bukan harga yang dipakai preset `lonjakan`
saat diukur: pengukurannya mengandaikan pembelian di harga penutupan pada hari
lonjakan itu sendiri.

Kiriman 15:00 lebih dekat ke asumsi itu - masih ada ~50 menit untuk bertindak
sebelum bursa tutup - dengan ongkos yang harus disadari: angkanya belum final.
Saham yang tampil +9% bisa ditutup +5%, atau justru terkunci ARA sehingga tidak
bisa dibeli di harga itu.

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
├── notify.py           perangkaian pesan & pengiriman WhatsApp (Meta Cloud API)
├── cache.py            cache SQLite untuk harga dan fundamental
├── universe.py         daftar emiten
└── providers/yahoo.py  pengambilan data (massal + rinci) & penyeragaman satuan
app.py                  antarmuka web Streamlit
tests/                  109 test, seluruhnya memakai data sintetis
```

Menambah sumber data lain cukup menyediakan kelas dengan dua metode,
`prices(emiten)` dan `fundamentals(emiten)`, seperti `FakeProvider` di
[tests/conftest.py](tests/conftest.py).

## Test

```bash
make test        # 109 test, < 1 detik, tanpa jaringan
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
