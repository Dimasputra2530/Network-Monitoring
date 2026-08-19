# data/

Folder ini sengaja **kosong**. Di sinilah nanti file-file data sensitif
ditaruh secara manual di server (bukan lewat repo/git) supaya dashboard
bisa menampilkan informasi tambahan yang butuh data tersebut.

Selama file-file di bawah ini belum ada, seluruh aplikasi (API +
dashboard) tetap berjalan normal tanpa error — kolom yang terkait cukup
menampilkan "Unknown" / "Unknown User" apa adanya. Tidak ada bagian
kode yang mewajibkan folder ini terisi.

## 1. Mapping User/Guest (Real-time Logs, Anomaly Detection, Dashboard)

Taruh salah satu (dicek sesuai urutan ini):

```
data/user_mapping.csv
data/user_guest_mapping.csv
data/users.csv
```

Format CSV:

```csv
srcip,user,device
```

- Kolom `srcip` **wajib** ada (dipakai sebagai key lookup).
- Kolom `user` boleh kosong → otomatis ditandai `Guest`.
- Kolom `device` opsional → kosong jadi `Unknown Device`.
- Nama kolom tidak case-sensitive; beberapa alias umum otomatis dikenali
  (mis. `username`/`nama`/`pengguna` untuk kolom user, `ip`/`src_ip`
  untuk kolom srcip). Lihat `api/user_mapping.py` untuk daftar lengkap.
- File di-reload otomatis kalau isinya berubah (dicek dari waktu
  modifikasi file) — tidak perlu restart API setelah update.
- Kalau ada IP yang datang tapi tidak terdaftar di file ini →
  ditampilkan sebagai **"Unknown User"** (beda dari IP yang memang
  `user`-nya kosong di file, itu jadi "Guest").

Dipakai oleh: Real-time Logs (kolom User/Guest + detail klik IP),
Anomaly Detection (kolom Pengguna/IP + detail klik baris), Dashboard
(Guest / User Activity).

## 2. Database GeoIP MaxMind GeoLite2 (Traffic Analysis)

Daftar & unduh gratis dari MaxMind:
https://dev.maxmind.com/geoip/geolite2-free-geolocation-data

Taruh salah satu / kedua file `.mmdb` berikut:

```
data/GeoLite2-City.mmdb   -> dipakai untuk kolom Country & City
data/GeoLite2-ASN.mmdb    -> dipakai untuk kolom Organization/ASN
```

Library Python `geoip2` (sudah ada di `api/requirements.txt`) perlu
ter-install: `pip install geoip2`.

Dipakai oleh: Traffic Analysis → tab "Top Destination IP" (kolom
Country, City, Organization/ASN).

## Kenapa file-file ini tidak disertakan di repo

Data mapping User/Guest bersifat sensitif (menyangkut identitas
pengguna jaringan), dan database GeoLite2 punya lisensi sendiri dari
MaxMind yang mengharuskan diunduh langsung dari akun terdaftar
masing-masing, bukan didistribusikan ulang. Kode di `api/` (lihat
`user_mapping.py`, `geoip_lookup.py`, `dns_lookup.py`, `port_lookup.py`)
sudah disiapkan untuk membaca file-file ini begitu tersedia, tanpa
perlu perubahan kode lebih lanjut — cukup taruh filenya di folder ini.
