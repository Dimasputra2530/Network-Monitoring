"""
Konfigurasi api/ -- terpisah dari etl_app/config.py & anomaly_detection/config.py
(pola yang sama dipakai di seluruh project ini: tiap modul punya config.py sendiri).
Baca dari .env yang SAMA di root project (python-dotenv cari .env ke atas
otomatis kalau dipanggil dari subfolder manapun -- tapi supaya eksplisit,
kita load .env milik etl_app/ juga di sini).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ETL_ENV_PATH = BASE_DIR.parent / "etl_app" / ".env"

load_dotenv(ETL_ENV_PATH)  # pakai .env yang sama dengan etl_app/ (kredensial MySQL sama)
load_dotenv()  # fallback: .env lokal di api/ (kalau ada override)

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# "*" supaya dashboard/ (dibuka via file:// atau server statis di port
# manapun) bisa fetch ke API ini tanpa error CORS. Ganti ke domain
# spesifik kalau sudah production.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# Ambang klasifikasi tipe & status anomali -- dipusatkan di sini supaya
# gampang di-tuning tanpa ubah logic endpoint. Klasifikasi ini heuristik
# TAMPILAN saja, jalan SESUDAH & TERPISAH dari Isolation Forest (lihat
# docstring classify.py) -- baris yang masuk sini SUDAH ditandai "tidak
# biasa" oleh model, ambang di bawah cuma menentukan SEBERAPA YAKIN itu
# pola berbahaya tertentu, bukan cuma variasi normal host itu sendiri.
#
# DEVIATION_* -- ambang robust z-score (median/MAD, lihat
# anomaly_detection/baseline.py) relatif ke KEBIASAAN HOST ITU SENDIRI:
#   >= DEVIATION_SUSPICIOUS : cukup menyimpang buat diperhatikan
#   >= DEVIATION_CONFIRMED  : menyimpang jauh dari kebiasaan host ini
ANOMALY_DEVIATION_SUSPICIOUS = 3.0
ANOMALY_DEVIATION_CONFIRMED = 6.0

# Port Scan baru dianggap "Confirmed Pattern" kalau SEMUA benar:
# (1) jumlah port unik absolut cukup banyak, (2) itu jauh di atas
# kebiasaan host ini sendiri (deviasi), DAN (3) pola "breadth" -- tiap
# port cuma disentuh sedikit kali (rata2 koneksi/port rendah), ciri khas
# scanning dibanding host yang memang ramai di port itu-itu saja.
ANOMALY_PORT_SCAN_MIN_PORTS = 20
ANOMALY_PORT_SCAN_MAX_CONN_PER_PORT = 3

# Data Exfiltration baru dianggap "Confirmed Pattern" kalau SEMUA benar:
# (1) volume outbound absolut cukup besar (MB), (2) itu jauh di atas
# kebiasaan VOLUME host ini sendiri (deviasi total_data, bukan cuma
# jumlah koneksi), DAN (3) terkonsentrasi ke sedikit tujuan.
ANOMALY_EXFIL_MIN_MB = 50
ANOMALY_EXFIL_MAX_DIVERSITY = 0.2

ANOMALY_SEVERITY_TINGGI = 0.05
ANOMALY_SEVERITY_SEDANG = 0.015

# Nama layanan port terkenal, buat label di tabel top port
PORT_NAMES = {
    443: "HTTPS", 80: "HTTP", 53: "DNS", 22: "SSH", 21: "FTP",
    3478: "STUN", 123: "NTP", 8443: "HTTPS-Alt", 853: "DNS-over-TLS",
    4500: "IPsec NAT-T", 993: "IMAPS", 51820: "WireGuard",
}
