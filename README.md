# Network Monitoring

ETL yang menarik log koneksi jaringan dari PostgreSQL produksi (read-only),
membersihkannya, menghitung fitur per jam per host (Feature Engineering),
lalu menyimpan hasilnya ke **MySQL** (database bersih, 2 tabel) — dengan
CSV di `staging/` dan `data/` sebagai arsip/audit trail di tiap tahap.

Di atas hasil ETL itu, ada modul **`anomaly_detection/`** terpisah yang
mendeteksi anomali perilaku host pakai Isolation Forest (unsupervised).
**`api/`** menyajikan semua data itu (fitur, raw log, hasil anomali)
lewat REST API yang query MySQL langsung — lihat `api/README.md`.
**`dashboard/`** adalah dashboard visualisasi yang fetch data dari
`api/` itu secara live — lihat `dashboard/README.md`.

## Struktur project

```
network-monitoring/
├── etl_app/              -- ETL: Extract, Cleaning, Feature Engineering, load ke MySQL
├── anomaly_detection/     -- ML: Isolation Forest, terpisah total dari kode ETL
├── api/                   -- REST API (FastAPI) di atas MySQL, dipakai dashboard/, lihat api/README.md
├── dashboard/             -- dashboard visualisasi (index.html), fetch live dari api/, lihat dashboard/README.md
└── README.md
```

## Pipeline

```
PostgreSQL (produksi, read-only)
      │
      ▼
Extract          source_db.py     (tarik baris baru, PULL_WINDOW_HOURS jam terakhir)
      │
      ▼
Cleaning         clean.py         (dstip → subnet /24, dedup, dsb.)
      │
      ├──────────────────────────────────────────────┐
      ▼                                               │
staging/detail_<batch>.csv                            │
      │                                                │
      ▼                                                │
MySQL.raw_data   mysql_db.py::load_raw_data()          │
                                                        │
      ┌─────────────────────────────────────────────────┘
      ▼
Feature Engineering   feature_engineering.py
      │  (dihitung dari SELURUH histori staging/detail_*.csv, bukan cuma batch baru)
      ▼
staging/features_<tanggal>.csv   (1 file per tanggal)   staging.py::write_features_by_date()
      │
      ├────────────────────────────────┐
      ▼                                ▼
data/hourly_features.csv         MySQL.fitur
(snapshot gabungan semua           mysql_db.py::load_fitur()
 tanggal, ditimpa tiap siklus)           │
                                          ▼
                              ┌─────────────────────────┐
                              │   anomaly_detection/     │
                              │   train.py / predict.py  │
                              │   (baca MySQL.fitur)     │
                              └─────────────────────────┘
                                          │
                                          ▼
                    anomaly_detection/output/anomaly_results.csv
```

## etl_app/

| File | Fungsi |
|---|---|
| `config.py` | Baca `.env`, siapkan folder `staging/` & `data/`, konfigurasi koneksi PostgreSQL (`SRC_DB_CONFIG`) dan MySQL (`CLEAN_DB_CONFIG`) |
| `source_db.py` | Koneksi **read-only** ke PostgreSQL produksi, tarik baris baru berdasarkan watermark + jendela waktu (`PULL_WINDOW_HOURS`) |
| `clean.py` | Pembersihan: `dstip` disamarkan jadi subnet `/24` (mis. `8.8.8.8` → `8.8.8.0/24`), `srcip` dibiarkan apa adanya, `received_at` diperbaiki tipenya |
| `port_service_map.py` | Daftar port yang dikenal (SSH, FTP, SMTP, LDAP, SNMP, RDP, WireGuard, MySQL, PostgreSQL, Redis, MongoDB, dll), dipakai `feature_engineering.py` untuk kategori `app` |
| `feature_engineering.py` | Hitung fitur per jam per host — lihat bagian **Fitur** di bawah |
| `staging.py` | Tulis & validasi CSV ke `staging/`; `write_features_by_date()` memecah hasil feature engineering **per tanggal**; `load_all_detail_csv()` gabungkan seluruh histori `detail_*.csv` |
| `clean_db.py` | Watermark ETL lokal (`etl_state.json`, bukan di database) + `save_features_to_data()` (tulis snapshot gabungan ke `data/hourly_features.csv`) |
| `mysql_db.py` | Koneksi & loader ke MySQL (`raw_data` + `fitur`), pakai `pymysql`, insert di-**chunk** per 2000 baris supaya tidak kena error `max_allowed_packet` |
| `schema.sql` | DDL 2 tabel MySQL: `raw_data` dan `fitur` |
| `run_etl.py` | Orkestrasi satu siklus penuh (Extract → Clean → staging → MySQL.raw_data → Feature Engineering → staging per-tanggal → data/ + MySQL.fitur) + loop (interval biasa atau jam tetap harian) |
| `backfill_mysql.py` | Script sekali-jalan: baca **semua** `staging/detail_*.csv` yang sudah ada (histori lama), TRUNCATE `raw_data`, insert ulang semua, lalu hitung ulang & upsert semua fitur ke `MySQL.fitur` |

## Cara pakai

```bash
cd etl_app
pip install -r requirements.txt
```

Isi `.env` (lihat contoh variabel di bawah), lalu:

```bash
# Sekali saja, kalau sudah ada data lama di staging/ yang belum masuk MySQL:
python backfill_mysql.py

# Jalan terus-menerus (loop sesuai ETL_INTERVAL_SECONDS / ETL_FIXED_TIME di .env):
python run_etl.py
```

Variabel `.env` yang dipakai:
```
SRC_DB_HOST=...        SRC_DB_PORT=5432        SRC_DB_NAME=...
SRC_DB_USER=...        SRC_DB_PASSWORD=...

CLEAN_DB_HOST=127.0.0.1   CLEAN_DB_PORT=3306   CLEAN_DB_NAME=network_clean
CLEAN_DB_USER=root        CLEAN_DB_PASSWORD=

PULL_WINDOW_HOURS=24
ETL_INTERVAL_SECONDS=86400
ETL_FIXED_TIME=07:30      # kosongkan kalau mau pakai interval biasa
STAGING_DIR=./staging
DATA_DIR=./data
```

## Grouping Port

Port dikelompokkan jadi **4 kategori saja** (tidak per-nama-service):

| Kategori | Contoh port |
|---|---|
| `dns`   | 53, 5353, 853 |
| `web`   | 80, 443, 8080, 8443, 8000, 8008, 8888 |
| `app`   | semua port dikenal selain DNS & WEB (SSH, FTP, SMTP, POP3, IMAP, LDAP, SNMP, NTP, DHCP, RDP, SMB, WireGuard, IPsec, MySQL, PostgreSQL, Redis, MongoDB, dll — lihat `port_service_map.py`) |
| `other` | port unknown / tidak ada di mapping / random / ephemeral |

## Fitur (per jam, per host)

| Kolom | Keterangan |
|---|---|
| `tanggal`, `jam` | tanggal + jam (format `"HH:00"`, mis. `"15:00"`) |
| `srcip` | IP host internal |
| `jumlah_koneksi` | total koneksi dalam jam itu |
| `jumlah_tujuan_unik` | jumlah IP tujuan (subnet /24) berbeda |
| `jumlah_port_unik` | jumlah port tujuan berbeda |
| `tcp`, `udp` | jumlah koneksi per protokol |
| `total_data`, `average_datasize` | total & rata-rata ukuran data per koneksi |
| `dns`, `web`, `app`, `other` | jumlah koneksi per kategori port |
| `dns_ratio`, `web_ratio`, `app_ratio`, `other_ratio` | proporsi tiap kategori port (`kategori / jumlah_koneksi`), totalnya ~1 karena saling eksklusif |
| `destination_diversity` | `jumlah_tujuan_unik / jumlah_koneksi` — mendekati 1 = tiap koneksi ke tujuan beda-beda (host "menyebar", ciri umum scanning); mendekati 0 = koneksi berulang ke tujuan itu-itu saja (perilaku normal umumnya) |

## MySQL (`network_clean`) — 2 tabel

- **`raw_data`** — data mentah per-baris koneksi hasil cleaning (`received_at, srcip, dstip_subnet, dstport, proto, datasize`). Insert `APPEND` biasa (bukan upsert).
- **`fitur`** — hasil feature engineering per jam per host (semua kolom di atas). `UNIQUE KEY (tanggal, jam, srcip)` + `ON DUPLICATE KEY UPDATE` → aman di-load ulang berkali-kali, tidak akan dobel.

## Output ETL

- `etl_app/staging/detail_<batch>.csv` — hasil cleaning, 1 file per siklus ETL (arsip).
- `etl_app/staging/features_<tanggal>.csv` — hasil feature engineering, **1 file per tanggal** (bukan gabungan semua tanggal).
- `etl_app/data/hourly_features.csv` — snapshot gabungan SEMUA tanggal, ditimpa tiap siklus.
- MySQL `network_clean.raw_data` + `network_clean.fitur` — **sumber data utama** untuk `anomaly_detection/`.

---

# anomaly_detection/

Module terpisah, khusus Machine Learning — **tidak ada kode ETL di
sini**. Baca hasil ETL langsung dari MySQL (tabel `fitur`), tidak baca
ulang CSV.

## Kenapa dipisah dari etl_app/

- ETL sudah berjalan benar dan tidak boleh diubah logic-nya. Memisah
  total mencegah perubahan di modul ML tidak sengaja merusak ETL.
- Siklus hidupnya beda: ETL jalan terus-menerus (loop harian), training
  model idealnya dijalankan berkala terpisah (mis. mingguan) sementara
  prediksi bisa jalan lebih sering.
- Dependency beda: `anomaly_detection/requirements.txt` sendiri
  (`scikit-learn`, `joblib`) supaya `etl_app/` tidak perlu ikut install
  library ML yang tidak dipakainya.

## File & tanggung jawabnya

| File | Tanggung jawab |
|---|---|
| `config.py` | Konfigurasi terpusat: lokasi model/output, daftar fitur (`PRIORITY_FEATURES` + `SUPPORT_FEATURES`), hyperparameter Isolation Forest. Satu-satunya tempat yang perlu diubah kalau mau eksperimen fitur/parameter lain |
| `utils.py` | `load_etl_output()` — baca tabel `fitur` dari MySQL, reuse `etl_app/mysql_db.py` (lihat catatan **Reuse Kode ETL** di bawah), TIDAK duplikasi kode koneksi DB |
| `feature_selector.py` | Pilih & validasi kolom fitur dari hasil ETL. Meledak dengan pesan jelas kalau ada kolom fitur yang hilang, daripada silent-fail |
| `preprocessing.py` | Missing value handling (`fillna(0)`) + scaling (`StandardScaler`) + simpan/muat scaler |
| `model.py` | Bungkus `IsolationForest` — train, predict label (0/1), anomaly score, save/load model. `train.py`/`predict.py` tidak pernah panggil sklearn langsung, selalu lewat sini |
| `train.py` | Orkestrasi training: load data → pilih fitur → preprocess (fit scaler) → latih model → simpan model+scaler → simpan ringkasan ke `evaluation.json` |
| `predict.py` | Orkestrasi prediksi: load data terbaru → load model+scaler (yang sudah ada, tidak fit ulang) → pilih fitur → scale → prediksi → simpan `anomaly_results.csv` **+ upsert ke tabel `anomaly_predictions`** (lihat `predictions_db.py`) |
| `schema.sql` | DDL tabel `anomaly_predictions` -- **terpisah** dari `etl_app/schema.sql`, tapi nulis ke database yang sama (`network_clean`) lewat koneksi yang sama |
| `predictions_db.py` | `init_schema()` + `save_predictions()` -- simpan histori hasil prediksi ke MySQL (upsert, `UNIQUE KEY tanggal+jam+srcip`), supaya tidak cuma snapshot terakhir kayak `anomaly_results.csv` |
| `backfill_predictions.py` | Script sekali-jalan: prediksi & upsert SELURUH histori `hourly_features` ke `anomaly_predictions` (dipakai sekali di awal, supaya laporan bulanan/tahunan langsung ada datanya, bukan cuma dari `predict.py` berikutnya) |
| `reports.py` | `get_monthly_report()` / `get_yearly_report()` -- query & agregasi tabel `anomaly_predictions` per bulan/tahun (total baris, total anomali, tingkat anomali, top host, tren) |
| `generate_report.py` | CLI buat cetak & simpan laporan: `python generate_report.py --month 2026-08` atau `--year 2026` |
| `evaluate_synthetic.py` | Synthetic anomaly injection -- bikin pola trafik yang SUDAH DIKETAHUI mencurigakan (port scan, DDoS, DNS tunneling, dll), cek berapa persen berhasil ke-flag model. Tidak butuh DB, tidak training ulang |
| `models/` | `isolation_forest.joblib` + `scaler.joblib`, dibuat otomatis oleh `train.py` |
| `output/` | `anomaly_results.csv` (snapshot terakhir dari `predict.py`) + `evaluation.json` (dari `train.py`) + `reports/laporan_*.json` (dari `generate_report.py`) + `synthetic_anomaly_evaluation.csv` (dari `evaluate_synthetic.py`), semua dibuat otomatis |

## Fitur yang dipakai model

**Prioritas** (fokus ke pola PERILAKU, bukan volume trafik):
`dns_ratio`, `web_ratio`, `app_ratio`, `other_ratio`, `destination_diversity`

**Pendukung** (skala/volume, bantu model membedakan host dengan sedikit
data yang rasionya kurang bisa dipercaya):
`jumlah_koneksi`, `jumlah_tujuan_unik`, `jumlah_port_unik`

**Soal redundansi**: `dns_ratio + web_ratio + app_ratio + other_ratio`
selalu ~1 (saling eksklusif), jadi salah satu kolom bisa dihitung dari
3 lainnya. Untuk model **linear** ini masalah (redundan), tapi Isolation
Forest itu **tree-based** (bukan linear) — jadi tidak terganggu oleh
korelasi/redundansi antar fitur ini, dan ke-4 rasio tetap dipertahankan
karena kombinasinya (mis. `app_ratio` tinggi + `other_ratio` juga
tinggi) bisa jadi pola berbeda. Kalau nanti mau dicoba tanpa
`other_ratio`, tinggal set `DROP_REDUNDANT_RATIO = True` di
`anomaly_detection/config.py` — tidak perlu ubah file lain.

## Reuse kode ETL (bukan duplikasi)

`utils.py` meng-import `etl_app/mysql_db.py` langsung (bukan copy-paste
logic koneksi/query). Karena `etl_app/` dan `anomaly_detection/`
sama-sama bukan Python package resmi (tiap file saling impor "flat",
bukan lewat package/`__init__.py`) dan sama-sama punya file bernama
`config.py`, ada penanganan khusus di `utils.py` (pakai `importlib`)
supaya `config.py` milik `etl_app/` dan `config.py` milik
`anomaly_detection/` tidak saling menimpa satu sama lain saat
di-import bersamaan.

## Cara pakai

```bash
cd anomaly_detection
pip install -r requirements.txt

python train.py                       # latih model dari SELURUH histori MySQL.hourly_features
python predict.py                     # prediksi SEMUA baris di MySQL.hourly_features
python predict.py --tanggal 2026-08-01   # cuma prediksi tanggal >= itu

python backfill_predictions.py        # SEKALI-JALAN: isi anomaly_predictions dari histori lama
python generate_report.py --month 2026-08   # laporan bulanan
python generate_report.py --year 2026       # laporan tahunan

python evaluate_synthetic.py          # cek model pakai anomali buatan (tidak butuh DB)
```

`train.py` cukup dijalankan ulang secara berkala (mis. mingguan) untuk
melatih ulang model dengan data terbaru. `predict.py` bisa dijalankan
lebih sering (mis. tiap `run_etl.py` selesai) dan TIDAK melatih ulang
model — cuma pakai model yang sudah ada di `models/`.

## Output prediksi (`output/anomaly_results.csv`)

| Kolom | Keterangan |
|---|---|
| `tanggal`, `jam`, `srcip` | identitas baris (sama seperti MySQL.fitur) |
| `jumlah_koneksi`, `jumlah_tujuan_unik`, `jumlah_port_unik` | fitur pendukung (volume) |
| `dns_ratio`, `web_ratio`, `app_ratio`, `other_ratio`, `destination_diversity` | fitur prioritas (perilaku) |
| `anomaly_score` | skor kontinu, **makin tinggi = makin mencurigakan** (sudah dibalik dari konvensi asli sklearn supaya intuitif) |
| `anomaly_label` | `1` = anomali, `0` = normal |

## Soal "evaluasi" model

Isolation Forest itu **unsupervised** — tidak ada label anomali asli
buat dibandingkan, jadi tidak ada accuracy/precision/recall yang
sebenarnya. `evaluation.json` isinya statistik **deskriptif** (jumlah
baris dilatih, rentang tanggal, fitur yang dipakai, parameter model,
tingkat anomali di data training, distribusi skor) — buat sanity-check
model habis dilatih, bukan metrik akurasi.

---

# api/ & dashboard/

`api/` (FastAPI) dan `dashboard/` (HTML/CSS/JS statis) sama-sama modul
terpisah lagi, di atas `etl_app/` dan `anomaly_detection/` — pola yang
sama: tidak duplikasi kode koneksi DB (`api/db.py` reuse
`etl_app/mysql_db.py` lewat `importlib`, sama seperti
`anomaly_detection/utils.py`), dependency sendiri-sendiri
(`api/requirements.txt`), dan `config.py` sendiri-sendiri.

`api/` query MySQL (`hourly_features`, `raw_data`, `anomaly_predictions`)
langsung tiap request — jadi begitu `run_etl.py` atau `predict.py`
menambah data baru, `dashboard/` yang fetch ke `api/` otomatis lihat
data terbaru tanpa perlu redeploy apapun.

**Satu server, satu port**: `api/main.py` sekaligus serve file statis
`dashboard/` (lewat `StaticFiles` di path `/`), jadi cukup jalankan
`uvicorn main:app --host 0.0.0.0 --port 8000` dari folder `api/` —
tidak perlu server terpisah buat dashboard-nya. Endpoint API tetap
semuanya di bawah `/api/...`.

Detail lengkap (cara jalanin, daftar endpoint, cara ganti alamat API di
dashboard, dll) ada di masing-masing:

- **`api/README.md`**
- **`dashboard/README.md`**
