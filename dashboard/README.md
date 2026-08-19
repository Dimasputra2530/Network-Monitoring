# dashboard/

Dashboard visualisasi buat `network_clean` (`hourly_features`, `raw_data`
dari `etl_app/`, dan `anomaly_predictions` dari `anomaly_detection/`).
**Live** — datanya di-`fetch()` dari `api/` setiap halaman dibuka/di-refresh,
bukan snapshot statis.

## Cara jalanin

Sekarang **cukup 1 server** — `api/` (FastAPI) sekaligus serve halaman
dashboard ini di port yang sama, jadi **tidak perlu lagi**
`python -m http.server` terpisah:

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Lalu buka:
- `http://localhost:8000/` (di komputer yang sama)
- `http://<IP-LAN-server>:8000/` (dari komputer lain di jaringan yang sama)

Kalau API-nya belum jalan / gagal konek, dashboard nampilin banner
merah di atas halaman yang jelasin masalahnya (bukan diam-diam kosong).

## Ganti alamat API

Defaultnya dashboard fetch ke **origin yang sama** dengan tempat dia
dibuka (relative URL) — jadi otomatis kerja baik lewat `localhost:8000`
maupun IP LAN manapun tanpa perlu diatur apa-apa. Ini cuma relevan kalau
API-nya sengaja dipisah ke host/port lain dari dashboard-nya; buka
dashboard-nya dengan parameter `?api=`:

```
index.html?api=http://192.168.1.10:8000
```

Sekali dibuka dengan parameter itu, pilihannya disimpan di browser
(`localStorage`) dan otomatis dipakai terus tanpa perlu nulis ulang
parameternya tiap buka halaman. Buat balik ke default (relative/same
origin), hapus override-nya: buka console browser lalu
`localStorage.removeItem('nm_api_base')`, atau buka
`index.html?api=` (kosongkan value-nya).

## Isi

6 halaman, dipilih lewat sidebar — semua datanya fetch dari `api/`
(lihat `api/README.md` untuk daftar endpoint lengkap):

| Halaman | Endpoint yang dipakai |
|---|---|
| **Dashboard** | `/api/overview`, `/api/overview/traffic-trend` (grafik Traffic Bulanan/Tahunan), `/api/user-activity` (kartu Guest/User Activity) |
| **Real-time Logs** | `/api/logs` — pencarian, filter, & paginasi dijalankan di server (query MySQL tiap ganti halaman/filter, bukan tarik semua log ke browser); klik Source IP buka modal detail lewat `/api/logs/ip-detail` |
| **Traffic Analysis** | `/api/traffic-analysis` — tab "Top Destination IP" menampilkan GeoIP (Country/City/Organization/Hostname) & Application |
| **Anomaly Detection** | `/api/anomaly`; klik baris buka modal detail lewat `/api/anomaly/detail` |
| **Reports** | `/api/reports/monthly`, `/api/reports/yearly` — tombol Download CSV generate file dari data yang lagi ditampilkan |
| **Alerts** | `/api/anomaly` (data yang sama dengan Anomaly Detection, ditampilkan sebagai feed) |

Kolom **User/Guest** (Real-time Logs, Anomaly Detection, Dashboard) dan
**GeoIP** (Traffic Analysis) bergantung pada file yang ditaruh manual di
`data/` (lihat `data/README.md` & `api/README.md`). Selama file itu
belum ada, kolom-kolom tersebut tetap tampil apa adanya sebagai
"Unknown User" / "Unknown" — bukan error.

## File

| File | Isi |
|---|---|
| `index.html` | Markup — sidebar, 6 halaman/section |
| `style.css` | Semua styling |
| `app.js` | Fetch ke `api/`, render tiap halaman, navigasi, filter/pencarian, paginasi, chart (Chart.js), download CSV |

Ketiga file itu harus tetap satu folder (dipanggil pakai path relatif).

## Kalau API belum ada / mau tetap pakai versi statis

Versi sebelumnya (data ter-embed langsung di `data.js`, jalan tanpa
backend sama sekali) masih valid sebagai pendekatan kalau kamu belum
sempat deploy `api/` — tinggal generate ulang `data.js` dari CSV/DB
secara manual dan tambahkan lagi `<script src="data.js">` sebelum
`app.js` di `index.html`, plus ganti pemanggilan `apiFetch()` di
`app.js` supaya baca dari `DATA` (variabel global) alih-alih fetch ke
jaringan. Untuk pemakaian normal sehari-hari, cara yang direkomendasikan
tetap lewat `api/` seperti dijelaskan di atas.
