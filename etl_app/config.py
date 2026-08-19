"""
Konfigurasi ETL App -- dibaca dari file .env.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# --- Sumber: PostgreSQL produksi (read-only) ---
SRC_DB_CONFIG = {
    "host": os.getenv("SRC_DB_HOST"),
    "port": os.getenv("SRC_DB_PORT", "5432"),
    "dbname": os.getenv("SRC_DB_NAME"),
    "user": os.getenv("SRC_DB_USER"),
    "password": os.getenv("SRC_DB_PASSWORD"),
}

# --- Tujuan: MySQL (database bersih, 2 tabel: raw_data + fitur) ---
CLEAN_DB_CONFIG = {
    "host": os.getenv("CLEAN_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CLEAN_DB_PORT", "3306")),
    "database": os.getenv("CLEAN_DB_NAME", "network_clean"),
    "user": os.getenv("CLEAN_DB_USER", "root"),
    "password": os.getenv("CLEAN_DB_PASSWORD", ""),
}

# --- Perilaku ETL ---
ETL_INTERVAL_SECONDS = int(os.getenv("ETL_INTERVAL_SECONDS", "86400"))  # 24 jam sekali
PULL_WINDOW_HOURS = int(os.getenv("PULL_WINDOW_HOURS", "24"))           # tarik 24 jam terakhir saja

# bukan interval relatif dari kapan script di-start. Kalau diisi, nilai ini
# yang dipakai dan ETL_INTERVAL_SECONDS diabaikan. Kosongkan untuk pakai
# interval biasa (ETL_INTERVAL_SECONDS).
ETL_FIXED_TIME = os.getenv("ETL_FIXED_TIME", "").strip()

# Folder hasil sementara (intermediate): CSV detail hasil cleaning +
# CSV hasil feature engineering, masing-masing per-batch (bertanda waktu).
STAGING_DIR = BASE_DIR / os.getenv("STAGING_DIR", "./staging")
STAGING_DIR.mkdir(parents=True, exist_ok=True)

# Folder hasil FINAL: salinan CSV feature engineering terakhir (nama file
# tetap/stabil, ditimpa tiap siklus) -- ini yang jadi sumber data untuk
# tahap berikutnya (dibaca dari file, bukan dari database).
DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "./data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
