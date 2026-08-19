# api/

API (FastAPI) yang menyajikan data dari MySQL `network_clean` — tabel
`hourly_features` & `raw_data` (diisi oleh `etl_app/`) dan
`anomaly_predictions` (diisi oleh `anomaly_detection/`) — buat dikonsumsi
`dashboard/`.

**Live**, bukan snapshot: tiap endpoint query MySQL saat itu juga, jadi
begitu `etl_app/run_etl.py` atau `anomaly_detection/predict.py` jalan dan
nambah data baru, tinggal refresh dashboard-nya (nggak perlu restart API
ataupun regenerate file apapun).

## Cara jalanin

Butuh MySQL `network_clean` yang sudah ada isinya (jalankan dulu
`etl_app/run_etl.py` / `backfill_mysql.py`, dan `anomaly_detection/predict.py`
/ `backfill.py` kalau mau data anomali juga muncul).

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Server ini sekaligus serve `dashboard/` di path `/` (lihat mount
`StaticFiles` di `main.py`) — jadi **satu command di atas sudah cukup**
buat jalanin API + dashboard bareng, tidak perlu server statis terpisah
lagi (mis. `python -m http.server`). Setelah jalan, buka:

- `http://localhost:8000/` — dashboard (di komputer yang sama)
- `http://<IP-LAN>:8000/` — dashboard (dari komputer lain di jaringan yang sama)
- `http://localhost:8000/api/...` — endpoint API (lihat daftar di bawah)

Cek jalan atau nggak:
```bash
curl http://localhost:8000/api/health
```
`{"status": "ok", "database": "connected"}` artinya sudah nyambung ke DB.
Kalau error, biasanya kredensial database yang salah — lihat bagian
**Konfigurasi** di bawah.

Dokumentasi endpoint otomatis (Swagger) ada di `http://localhost:8000/docs`.

## Konfigurasi

API ini **pakai `.env` yang sama dengan `etl_app/`** (baca
`etl_app/.env`, variabel `CLEAN_DB_*`) — jadi kalau `etl_app/` sudah
jalan dan `.env`-nya sudah bener, `api/` otomatis nyambung ke database
yang sama, nggak perlu setup ulang.

Kalau mau override khusus buat API (misalnya port server-nya, atau CORS),
bikin `api/.env`:

```env
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=*
```

`CORS_ORIGINS=*` (default) berguna kalau `dashboard/` dibuka terpisah
dari API (mis. lewat `file://`, atau server statis di port lain saat
development). Untuk pemakaian normal sekarang (dashboard di-serve
langsung oleh `api/` di port yang sama, lihat bagian **Cara jalanin**),
CORS sebenarnya tidak lagi jadi penghalang karena originnya sama — tapi
setting ini tetap dibiarkan `*` sebagai fallback yang aman. Ganti ke
domain spesifik (pisah koma kalau lebih dari satu) kalau sudah production.

## Endpoint

| Endpoint | Keterangan |
|---|---|
| `GET /` | serve `dashboard/index.html` (& `/app.js`, `/style.css`, asset lain) — lihat mount `StaticFiles` di `main.py` |
| `GET /api/info` | info service (nama, daftar endpoint, link docs) — dulu ada di `/`, dipindah ke sini karena `/` sekarang dipakai serve dashboard |
| `GET /api/health` | cek koneksi DB |
| `GET /api/meta` | rentang tanggal data, daftar IP unik, daftar bulan yang ada datanya |
| `GET /api/overview` | ringkasan hari terakhir (buat halaman Dashboard) |
| `GET /api/overview/traffic-trend` | agregat traffic per bulan & per tahun, seluruh histori (buat grafik Traffic Bulanan/Tahunan di Dashboard) |
| `GET /api/user-activity?limit=` | traffic per host + User/Guest (dari `data/`), buat kartu Guest/User Activity di Dashboard |
| `GET /api/traffic-analysis` | agregat seluruh periode (buat halaman Traffic Analysis) — `top_dst_ip` sudah dilengkapi GeoIP (Country/City/Organization/Hostname) & Application |
| `GET /api/anomaly` | daftar anomali + klasifikasi tipe/level (buat halaman Anomaly Detection & Alerts) — tiap item sudah dilengkapi User/Device dari `data/` |
| `GET /api/anomaly/detail?srcip=&tanggal=&jam=` | detail 1 baris anomali (User, Device, Destination pada jam itu) — buat modal klik-baris di Anomaly Detection |
| `GET /api/logs?page=&per_page=&search=&proto=&srcip=` | log koneksi mentah, paginasi & filter di sisi server — tiap baris sudah dilengkapi User/Guest dari `data/`; `search` juga cocok ke nama user |
| `GET /api/logs/ip-detail?srcip=` | detail 1 Source IP (User, Device, daftar Destination + Country + Application) — buat modal klik-IP di Real-time Logs |
| `GET /api/reports/monthly?ym=YYYY-MM` | laporan per hari dalam 1 bulan |
| `GET /api/reports/yearly?year=YYYY` | laporan per bulan dalam 1 tahun |

Semua response JSON. Kalau tabel yang dibutuhkan belum ada / masih kosong
(mis. ETL belum pernah dijalankan), endpoint balikin `503` dengan pesan
yang jelas, bukan crash `500` biasa.

## Integrasi data sensitif (folder `data/`)

Beberapa fitur di atas (User/Guest, GeoIP) bergantung pada file yang
**sengaja tidak disertakan** di repo karena datanya sensitif (mapping
User/Guest) atau berlisensi pihak ketiga (database GeoLite2). Selama
file-file itu belum ditaruh di `data/`, semua endpoint di atas **tetap
jalan normal** — cukup balikin `"Unknown User"` / `"Unknown"` apa
adanya, tidak ada data dummy yang dikarang.

Detail format file yang diharapkan (nama file, format CSV, cara dapat
database GeoLite2, dll) ada di **`data/README.md`**. Modul yang
menangani masing-masing:

| Modul | Fungsi |
|---|---|
| `user_mapping.py` | Baca mapping User/Guest dari `data/user_mapping.csv` (auto-reload kalau file berubah) |
| `geoip_lookup.py` | Baca `data/GeoLite2-City.mmdb` & `data/GeoLite2-ASN.mmdb` (MaxMind GeoLite2) buat Country/City/Organization |
| `dns_lookup.py` | Reverse DNS (PTR) best-effort buat kolom Hostname, dengan hard timeout supaya tidak nge-hang kalau resolver DNS di jaringan server tidak reachable |
| `port_lookup.py` | Turunkan "Application" dari Port + Protocol, **reuse** `etl_app/port_service_map.py` (bukan duplikasi daftar port) |

## Klasifikasi tipe & level anomali

`anomaly_predictions` cuma punya `anomaly_label` (Normal/Anomaly) &
`anomaly_score` dari Isolation Forest — nggak ada kolom tipe. `classify.py`
nambahin klasifikasi tipe & level secara heuristik dari kolom fitur yang
sudah ada, murni buat kebutuhan tampilan (tidak mengubah/dipakai model
ML-nya):

- `jumlah_port_unik >= 30` → **Port Scan**
- `destination_diversity == 1.0` & `jumlah_koneksi <= 5` → **Unusual Traffic**
- `jumlah_koneksi >= 500` & `jumlah_port_unik < 15` & `destination_diversity < 0.15` → **Data Exfiltration**
- `other_ratio >= 0.4` & `app_ratio >= 0.15` & `jumlah_koneksi < 20` → **Suspicious App Traffic**
- selain itu → **Unusual Traffic** (fallback)

Level (Tinggi ≥0.05 / Sedang ≥0.015 / Rendah) dari `anomaly_score`. Ambang
batasnya ada di `config.py`, gampang di-tuning tanpa ubah logic endpoint.

## File

| File | Isi |
|---|---|
| `main.py` | Route FastAPI, semua endpoint di atas, + mount `StaticFiles` di `/` buat serve `dashboard/` |
| `db.py` | Koneksi & query helper — **reuse** `etl_app/mysql_db.py` (bukan duplikasi kode koneksi), plus auto-convert `Decimal` → `float` dari hasil query |
| `config.py` | Setting khusus API (host/port/CORS), baca `.env` yang sama dengan `etl_app/` |
| `classify.py` | Heuristik klasifikasi tipe & level anomali |
| `user_mapping.py` | Integrasi mapping User/Guest dari `data/` (lihat bagian "Integrasi data sensitif" di atas) |
| `geoip_lookup.py` | Integrasi MaxMind GeoLite2 dari `data/` |
| `dns_lookup.py` | Reverse DNS (Hostname) buat Traffic Analysis |
| `port_lookup.py` | Turunan "Application" dari Port + Protocol, reuse `etl_app/port_service_map.py` |
| `requirements.txt` | fastapi, uvicorn, pandas, PyMySQL, python-dotenv, geoip2 (opsional) |

## Performa & batasan yang perlu diketahui

- Tiap request agregasi (`/api/overview`, `/api/traffic-analysis`,
  `/api/reports/*`) query ulang dari awal, tanpa caching. Buat volume data
  yang dipakai testing (~390 ribu baris `raw_data`) responsnya masih
  cepat (sub-detik). Kalau volume datanya nanti jauh lebih besar (jutaan+
  baris `raw_data` dari deployment jangka panjang), pertimbangkan nambah
  caching (mis. `functools.lru_cache` dengan TTL pendek, atau Redis) di
  endpoint yang berat.
- `/api/logs` sudah paginasi & filter di level SQL (bukan tarik semua
  baris ke Python dulu), jadi aman dipakai meski tabel `raw_data`-nya
  besar.
- Tidak ada autentikasi di endpoint manapun — API ini didesain buat
  dipakai di jaringan internal/lokal bareng dashboard-nya. Kalau mau
  diekspos ke internet, tambahkan lapisan auth dulu.
