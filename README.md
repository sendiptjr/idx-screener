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
- 13 preset strategi siap pakai (value, growth, dividen, momentum, breakout, …)
- Skor peringkat gabungan berbobot
- Backtest berbasis harga dengan penolakan otomatis terhadap look-ahead bias
- Antarmuka web Streamlit dengan grafik candlestick, volume, dan RSI
- Kiriman terjadwal ke Telegram atau WhatsApp
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

## Kesegaran data dan cache

Harga dan fundamental mengendap di SQLite (`.cache/cache.db`) supaya screening
berulang tidak menunggu jaringan. Umur simpannya bisa diatur:

| Variabel | Bawaan | Arti |
|---|---|---|
| `IDX_SCREENER_PRICE_TTL` | 6 | jam, sebelum harga diambil ulang |
| `IDX_SCREENER_FUNDAMENTAL_TTL` | 24 | jam, sebelum fundamental diambil ulang |

Bawaan 6 jam cocok untuk pemakaian lokal sesekali, tetapi **terlalu lama untuk
aplikasi web yang dibuka sepanjang jam bursa**: harga yang ditarik sebelum
bursa buka akan bertahan sampai siang, dan metrik "Data per" akan menunjukkan
tanggal kemarin padahal bursa sudah berjalan. Di Streamlit Cloud, setel
`IDX_SCREENER_PRICE_TTL=1` lewat Settings → Secrets.

Cache Streamlit sendiri mengikuti setelan yang sama (`CACHE_TTL` di
[app.py](app.py)), dibatasi paling lama 1 jam, supaya kedua lapis tidak saling
menambah. Tombol **"Muat ulang data"** di sidebar melewati keduanya.

Di baris perintah, `--refresh` melakukan hal yang sama:

```bash
idxscreen screen --preset lonjakan --refresh
```

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

### Penguat harian

`top-gainer` dan `top-gainer-likuid` menjawab pertanyaan berbeda dari preset
lain: bukan "apa yang layak dibeli", melainkan "apa yang bergerak hari ini".

```bash
idxscreen screen --preset top-gainer-likuid --refresh
```

Keduanya **tidak punya pengukuran di belakangnya** - sekadar pengurutan
menurut kenaikan harga. `top-gainer` tanpa saringan sama sekali;
`top-gainer-likuid` membatasi ke nilai transaksi di atas Rp 1 miliar sehari,
jauh lebih longgar daripada Rp 10 miliar milik preset `lonjakan`, sehingga
angka keunggulan backtest tidak berlaku.

Kolom `avg_value_20` dan `dist_ara` sengaja ditampilkan, karena dua angka itu
yang menerangkan daftarnya. Contoh nyata pada 22 September 2026:

| Kode | % Hari | Nilai/hari | Sisa ARA |
|---|---|---|---|
| FORU | +34,09% | Rp 18,05 M | 0,91% |
| NASI | +24,79% | Rp 3,50 M | 0,21% |
| SAPX | +24,50% | Rp 4,05 M | 0,50% |

Ketiganya praktis terkunci ARA - tidak bisa dibeli di harga itu. Dibandingkan
dengan daftar penguat di aplikasi broker pada waktu yang sama, sebelas dari
tiga belas nama teratas cocok, beberapa persis sampai ke rupiah; selisihnya
hanya beberapa tick pada emiten tipis karena dua potret diambil pada detik
yang berbeda.

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

## Kirim hasil screening ke ponsel

`idxscreen notify` menjalankan sebuah preset lalu mengirim hasilnya ke
**Telegram** atau **WhatsApp**. Bawaannya preset `lonjakan`, dan kanalnya
dipilih otomatis: Telegram bila `TELEGRAM_TOKEN` terpasang, selain itu
WhatsApp.

```bash
# lihat pesannya dulu, tanpa mengirim apa pun
idxscreen notify --dry-run --offline

# kirim beneran
idxscreen notify --preset lonjakan --top 15
```

| Opsi | Arti |
|---|---|
| `--preset` | preset yang dikirim; beberapa dipisah koma, mis. `lonjakan,volume-spike` |
| `--channel` | `auto` (bawaan) / `telegram` / `whatsapp` |
| `--to` | tujuan; chat id Telegram, atau nomor WhatsApp (`081…`, `+62 …`, `62…`) |
| `--top` | berapa saham teratas di pesan (bawaan 8); template WhatsApp selalu 8 baris |
| `--mode` | WhatsApp saja: `auto` (bawaan) / `text` / `template` |
| `--dry-run` | cetak pesannya, jangan kirim |
| `--max-stale-days` | batalkan bila data bursa lebih tua dari ini (bawaan 5) |
| `--skip-empty` | diam saja bila tidak ada yang lolos |
| `--tp-sl` | sertakan acuan TP/SL berbasis ATR (bawaan mati) |
| `--news` | kirim juga emiten yang disebut berita semalam |
| `--news-ai` | nalar dampak berita umum lewat Claude (bawaan nyala) |
| `--refresh` | abaikan cache, ambil ulang dari Yahoo |

Telegram jauh lebih sederhana dan disarankan untuk pemakaian pribadi:

| | Telegram | WhatsApp Cloud API |
|---|---|---|
| Biaya | gratis | gratis pada volume kecil |
| Persetujuan pesan | tidak ada | template wajib direview Meta |
| Jendela 24 jam | tidak ada | ada; kiriman terjadwal wajib template |
| Bentuk pesan | teks penuh, berbaris banyak | 8 baris slot, panjang parameter terbatas |
| Pemasangan | ~5 menit | jam sampai hari |

### Telegram

1. Chat ke [@BotFather](https://t.me/BotFather), kirim `/newbot`, ikuti
   petunjuknya. Anda mendapat token berbentuk `123456:ABC-DEF...`.
2. Kirim satu pesan apa saja ke bot baru itu dari akun yang akan menerima.
3. Cari chat id-nya:

```bash
export TELEGRAM_TOKEN=123456:ABC-DEF...
idxscreen telegram-id
```

4. Pasang hasilnya dan kirim:

```bash
export TELEGRAM_CHAT_ID=123456789
idxscreen notify --preset lonjakan --top 15
```

Pesannya dikirim sebagai HTML (`*tebal*` dan `_miring_` diubah otomatis),
dipotong bila melewati batas 4096 huruf Telegram.

### Batas harga di dalam pesan

Tiap saham disertai satu baris batas harga:

```
1. FPNI +13,59% · Rp 585 · vol 2,67x
    ARA hari ini Rp 640 · SMA20 Rp 580
```

Keduanya fakta, bukan ancar-ancar:

- **ARA** - harga tertinggi yang boleh ditransaksikan hari ini. Di atasnya
  order ditolak bursa. Dihitung dari penutupan kemarin dikali batas auto
  reject atas, lalu dibulatkan **ke bawah** ke fraksi harga IDX; membulatkan
  ke atas justru menghasilkan harga yang ditolak.
- **SMA20** - syarat preset ini sendiri (`close > sma20`). Di bawah angka itu
  saham tersebut tidak akan lolos saringan lagi.

Yang diukur backtest hanyalah pembelian di **harga penutupan**. Kedua angka di
atas menerangkan batas, bukan menyarankan titik masuk - rentang masuk apa pun
di luar penutupan belum pernah diuji.

### TP/SL - dan kenapa bawaannya mati

`--tp-sl` menambah satu baris lagi per saham:

```
1. FPNI +16,50% · Rp 600 · vol 3,09x
    ARA hari ini Rp 640 · SMA20 Rp 580
    TP Rp 700 (+16,67%) · SL Rp 580 (-3,33%)
```

- **TP** = `close + 2 x ATR14`
- **SL** = yang lebih tinggi antara SMA20 dan `close - 1,5 x ATR14`. SMA20
  dipakai karena di sanalah premis preset `lonjakan` gugur; kelipatan ATR
  menjaga saham yang harganya jauh di atas SMA20 agar tidak dibiarkan turun
  terlalu dalam. SMA20 yang berada di atas harga diabaikan - stop di atas
  harga beli tidak masuk akal.

Keduanya **ancar-ancar volatilitas, bukan hasil pengukuran.** Backtest preset
ini hanya menguji satu hal: beli di harga penutupan, tahan 1-2 minggu, jual.
Tanpa TP, tanpa SL.

Dan ada alasan kenapa itu bukan kelalaian. Catatan preset `lonjakan` berbunyi
median 1-2 minggunya **negatif**, sehingga seluruh keunggulan datang dari
sedikit pemenang besar. TP yang ketat memotong justru pemenang-pemenang itu,
dan yang tersisa hanyalah median yang negatif tadi. Karena itu bawaannya mati,
dan ketika dinyalakan pesannya menyebutkan sendiri keterbatasan ini.

Fraksi harga yang dipakai (`FRAKSI_HARGA` di [notify.py](idx_screener/notify.py)):

| Harga | Tick |
|---|---|
| < Rp 200 | Rp 1 |
| Rp 200 - < Rp 500 | Rp 2 |
| Rp 500 - < Rp 2.000 | Rp 5 |
| Rp 2.000 - < Rp 5.000 | Rp 10 |
| >= Rp 5.000 | Rp 25 |

### WhatsApp

Lewat **Meta Cloud API**. Lebih berliku - seluruh seluk-beluknya di bawah ini.

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

### Template yang dipakai

Namanya `idx_lonjakan`, kategori **Utility**, bahasa **Indonesian** (`id`),
placeholder **positional** (`{{1}}`, bukan `{{tanggal}}`). Badan template:

```
*Lonjakan yang masih bisa dibeli*
Data {{1}}
{{2}} dari {{3}} emiten lolos hari ini.

1. {{4}}
2. {{5}}
3. {{6}}
4. {{7}}
5. {{8}}
6. {{9}}
7. {{10}}
8. {{11}}
{{12}}

Daftar ini disaring dari saham likuid yang melonjak lebih dari tujuh persen
hari itu, belum terkunci ARA sehingga masih bisa dibeli, dan harganya masih
berada di atas rata-rata dua puluh hari. Diukur pada dua tahun data, kelompok
ini unggul sekitar satu sampai dua persen di atas pasar bila ditahan satu
sampai dua minggu, tetapi merugi bila dijual keesokan harinya. Keunggulannya
datang dari sedikit pemenang besar, jadi sebarkan ke banyak posisi, jangan
bertaruh pada satu atau dua saham saja.
```

Footer (kolom terpisah, teks tetap):

```
Bukan rekomendasi beli. Horizon 1-2 minggu.
```

Tiga keputusan bentuk di atas semuanya dipaksa oleh aturan Meta, bukan selera:

**Paragraf penjelasan itu wajib ada.** Versi pertama template ini - hanya
daftar saham tanpa paragraf - ditolak seketika dengan `2388293: Parameters
words ratio exceeds limit`, "too many variables for its length". Meta menuntut
teks tetap yang cukup banyak dibanding jumlah variabel. Versi sekarang: 600
huruf teks tetap untuk 12 variabel, sekitar 50 huruf per variabel, dan lolos.

**Nomor urut ditulis sebagai teks tetap**, bukan ikut di dalam parameter -
alasan yang sama. Konsekuensinya, di hari yang cuma meloloskan dua saham,
nomor 3-8 tetap muncul tanpa isi.

**`{{1}}` memuat konteks, bukan sekadar tanggal.** Badan template tidak bisa
berbeda antara jadwal pagi dan sore, jadi kata "penutupan" tidak boleh
ditulis tetap di situ - pukul 15:00 datanya bukan penutupan. Kode mengisi
`{{1}}` dengan `penutupan Kamis, 17 Sep 2026` atau `sesi berjalan Jumat,
18 Sep 2026 pukul 15.02 WIB`, tergantung `stale_days`.

Contoh nilai yang diminta Meta sebelum tombol Submit menyala:

| | |
|---|---|
| `{{1}}` | `penutupan Kamis, 17 Sep 2026` |
| `{{2}}` | `11` |
| `{{3}}` | `845` |
| `{{4}}` | `TEBE +18,73% · Rp 1.965 · sisa ARA 6,27%` |
| `{{5}}` … `{{11}}` | baris saham berikutnya, bentuk sama |
| `{{12}}` | `+3 lainnya: JARR, ICON, KETR` |

Jumlah baris saham dipatok 8 (`SLOT_SAHAM` di
[notify.py](idx_screener/notify.py)). Mengubahnya berarti mengubah badan
template di Meta juga - keduanya harus cocok.

**Template menempel pada WABA, bukan pada akun.** Kalau Anda punya lebih dari
satu WhatsApp Business Account - misalnya satu bawaan berisi nomor test Meta,
satu lagi berisi nomor produksi sendiri - template harus dibuat di WABA yang
memuat nomor pengirim yang dipakai. Dibuat di WABA yang salah, pengiriman
gagal dengan `132001` meski templatenya jelas-jelas APPROVED. Memeriksanya:

```bash
curl -s "https://graph.facebook.com/v25.0/<WABA_ID>/phone_numbers\
?fields=id,display_phone_number&access_token=$WA_TOKEN"
```

`WA_PHONE_NUMBER_ID` harus salah satu id yang muncul di daftar itu.

Satu jebakan kalau Anda perlu mengganti badan template kelak: **jangan hapus
lalu buat ulang dengan nama sama.** Meta memblokir pemakaian ulang nama yang
baru dihapus, dan pembuatan ulang akan ditolak berulang kali dengan
`2388023: Message template language is being deleted`. Template berstatus
APPROVED bisa disunting langsung; kalau masih PENDING, buat saja nama baru.

### Kredensial

Empat variabel lingkungan; ambil dari Meta for Developers → aplikasi Anda →
WhatsApp → API Setup.

```bash
export WA_TOKEN=EAAG...            # token permanen milik System User, bukan token 24 jam
export WA_PHONE_NUMBER_ID=1234567  # Phone number ID, bukan nomor teleponnya
export WA_TO=6281234567890         # nomor tujuan, wajib terdaftar dulu saat masih mode test
export WA_TEMPLATE=idx_lonjakan
# opsional: WA_TEMPLATE_LANG (bawaan id), WA_API_VERSION (bawaan v25.0)
```

Selama aplikasi Meta masih berstatus *development*, nomor tujuan harus
didaftarkan dulu sebagai penerima uji di API Setup. Setelah aplikasi live,
siapa pun bisa dikirimi.

## Emiten yang disebut berita

`--news` menambah satu pesan lagi: emiten yang namanya muncul di berita pasar
semalam.

```bash
idxscreen notify --news --dry-run
```

Jendelanya bawaan **15.00 hari bursa sebelumnya sampai 08.00 hari ini**, bisa
digeser dengan `--news-dari` dan `--news-sampai`. Hari bursa sebelumnya, bukan
kemarin: dijalankan Senin pagi jendelanya mundur sampai Jumat sore, supaya
berita akhir pekan tidak hilang.

Sumbernya RSS pasar CNBC Indonesia (feed investment-nya membalas 404 sejak
September 2026). Kontan dan Bisnis.com membalas 403 untuk permintaan otomatis,
jadi tidak dipakai. Status tiap sumber tercetak di log; bila semua sumber
gagal, `notify` keluar dengan kode 1 agar run-nya terlihat merah.

### Cara nama dicocokkan ke emiten

Tiga jalur, dari yang paling meyakinkan:

1. **Kode emiten** ditulis apa adanya di judul - `BYAN`, `CPIN`.
2. **Nama perusahaan**, dengan dua bentuk penanda. Kata tunggal harus cocok
   **utuh** dan panjangnya minimal 8 huruf; gabungan dua-tiga kata dicocokkan
   sebagai potongan supaya "Medco Energi" tetap kena pada penulisan media
   "MedcoEnergi".
3. **Nama pendek yang lazim di media** (`ALIAS` di
   [news.py](idx_screener/news.py)): BRI, BCA, Antam, Telkom, dan seterusnya.

Syarat "kata tunggal minimal 8 huruf dan tidak umum" itu bukan kehati-hatian
berlebihan. Tanpa itu, "Perusahaan Gas Negara" tersangkut di tiap berita yang
memuat kata *perusahaan*, "Asuransi Bina Dana Arta" di tiap berita asuransi,
dan "Bayan Resources" di tiap berita yang menyebut *resources*. Ketiganya
benar-benar terjadi pada percobaan pertama.

### Ini bukan rekomendasi

Preset di `presets/*.yaml` diuji ke dua tahun data. Pencocokan berita **tidak
diuji sama sekali** - tidak ada bukti bahwa saham yang disebut berita semalam
bergerak lebih baik. Karena itu pesannya menyebut dirinya daftar sebutan, dan
yang diberi tekanan justru irisannya: emiten bertanda `← lolos lonjakan`
adalah yang disebut berita **sekaligus** memenuhi saringan yang terukur.
Sisanya informasi, bukan sinyal.

Perlu juga disadari jendela semalam sering sepi. Pada uji pertama, 18 berita
dalam rentang 15.00-08.00 hanya menghasilkan satu emiten - sisanya berita
makro dan regulasi yang tidak menyebut perusahaan mana pun.

## Dampak berita, ditalar Claude

Pencocokan nama hanya menangkap berita yang menyebut emiten. Peristiwa seperti
gunung meletus, banjir besar, atau kebijakan mendadak tidak menyebut satu kode
pun, padahal dampaknya nyata. Untuk itu judul-judul berita dikirim ke Claude,
yang menyimpulkan rantai sebabnya dan emiten yang mungkin terkena.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
idxscreen notify --news --dry-run
```

Contoh bentuk hasilnya:

```
*Dampak berita semalam*

1. ▲ Erupsi Krakatau, abu vulkanik menyebar  _(sedang)_
    Abu memicu gangguan pernapasan sehingga permintaan obat dan layanan
    rumah sakit naik
    • KLBF Rp 1.500 · 2,50%
      Produsen obat pernapasan
    • MIKA Rp 2.900 · 0,70% ← lolos lonjakan
      Jaringan rumah sakit di Banten
```

Tanpa `ANTHROPIC_API_KEY`, bagian ini dilewati dengan pesan di log dan tiga
pesan lainnya tetap terkirim - bukan kegagalan.

### Model dan ongkos

Bawaannya `claude-haiku-4-5`: sekali sehari atas ~50 judul, ongkosnya sekitar
seperseratus sen per panggilan. Untuk penalaran dampak lapis kedua yang lebih
tajam, setel `ANTHROPIC_MODEL=claude-opus-5` - kira-kira sepuluh kali lebih
mahal dan tetap di bawah Rp 20.000 sebulan.

Daftar 845 emiten dikirim di bagian sistem dengan `cache_control`, jadi
posisinya stabil dan bisa dipakai ulang cache bila dipanggil berulang.

### Pengamannya

- **Kode karangan dibuang.** Claude kadang menyebut kode yang tidak ada;
  apa pun yang tidak ada di daftar emiten disaring sebelum masuk pesan.
- **Tema tanpa emiten sah ikut dibuang**, supaya tidak ada baris kosong.
- **Paling banyak 5 tema, 4 emiten per tema**, agar pesannya tetap terbaca.

### Ini hipotesis, bukan sinyal

Preset diuji ke dua tahun data. Penalaran ini **tidak diuji sama sekali** -
tidak ada bukti bahwa saham yang disebut bergerak sesuai dugaan. Rantai sebab
yang masuk akal di atas kertas sering sudah habis diperdagangkan dalam hitungan
menit, atau tidak pernah terwujud. Karena itu tiap tema membawa nilai keyakinan
yang diisi Claude sendiri, dan pesannya menutup dengan peringatan eksplisit.

Yang tetap bisa dipegang adalah irisannya: emiten bertanda `← lolos` muncul di
penalaran berita **sekaligus** memenuhi saringan yang memang terukur.

### Penjadwalan

[.github/workflows/lonjakan-harian.yml](.github/workflows/lonjakan-harian.yml)
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

Pasang secret sesuai kanal yang dipakai - `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID`,
atau `WA_TOKEN` + `WA_PHONE_NUMBER_ID` + `WA_TO` + `WA_TEMPLATE`. Cukup salah
satu set. Lalu uji sekali lewat tombol *Run workflow* dengan `dry_run` menyala.

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
├── notify.py           perangkaian pesan & pengiriman (Telegram, WhatsApp)
├── news.py             ambil berita RSS & cocokkan judulnya ke emiten
├── analisis.py         nalar dampak berita umum lewat Claude
├── cache.py            cache SQLite untuk harga dan fundamental
├── universe.py         daftar emiten
└── providers/yahoo.py  pengambilan data (massal + rinci) & penyeragaman satuan
app.py                  antarmuka web Streamlit
tests/                  172 test, seluruhnya memakai data sintetis
```

Menambah sumber data lain cukup menyediakan kelas dengan dua metode,
`prices(emiten)` dan `fundamentals(emiten)`, seperti `FakeProvider` di
[tests/conftest.py](tests/conftest.py).

## Test

```bash
make test        # 172 test, < 1 detik, tanpa jaringan
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
