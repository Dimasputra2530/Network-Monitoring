"""
Konfigurasi module anomaly_detection.

Kenapa file ini ada:
Supaya semua hal yang "gampang berubah" (daftar fitur, hyperparameter
Isolation Forest, lokasi file model/output) terkumpul di SATU tempat.
train.py dan predict.py tidak boleh punya angka/nama kolom "hardcoded"
tersebar di banyak file -- kalau mau eksperimen ganti fitur atau
parameter model, cukup edit di sini.
"""
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
OUTPUT_DIR = BASE_DIR / "output"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = MODEL_DIR / "isolation_forest.joblib"
SCALER_PATH = MODEL_DIR / "scaler.joblib"
BASELINE_PATH = MODEL_DIR / "host_baseline.joblib"
ANOMALY_RESULTS_PATH = OUTPUT_DIR / "anomaly_results.csv"
EVALUATION_PATH = OUTPUT_DIR / "evaluation.json"

# ---------------------------------------------------------------------
# Baseline perilaku per host/IP
# ---------------------------------------------------------------------
# Kolom MENTAH (dari hourly_features) yang jadi dasar baseline per host --
# dipakai baseline.py buat menghitung "kebiasaan normal" tiap host
# (median & MAD per srcip dari data TRAINING), lalu dikonversi jadi
# fitur "<kolom>_deviation" -- seberapa jauh nilai jam ini dari
# kebiasaan host ITU SENDIRI, bukan dibanding seluruh populasi host.
# total_data disertakan supaya ada sinyal VOLUME (bukan cuma jumlah
# koneksi) -- penting buat bedain Data Exfiltration beneran dari host
# yang sekadar banyak koneksi kecil.
BASELINE_RAW_COLUMNS = [
    "jumlah_koneksi",
    "jumlah_tujuan_unik",
    "jumlah_port_unik",
    "total_data",
]

# Host butuh minimal segini banyak baris histori di data TRAINING supaya
# baseline-nya sendiri dianggap "cukup dipercaya" -- kalau kurang, pakai
# baseline GLOBAL (rata-rata seluruh host) sebagai fallback sementara,
# TAPI host itu tetap diikutkan/dipantau (lihat baseline.py & classify.py
# di api/), bukan otomatis di-whitelist atau diabaikan.
BASELINE_MIN_SAMPLES = 5

# ---------------------------------------------------------------------
# Fitur
# ---------------------------------------------------------------------
# PRIORITAS: fitur PERILAKU (proporsi/rasio & keragaman tujuan) --
# fokus model ke "bagaimana pola akses host", bukan besar-kecilnya
# volume trafik. Ini yang paling menentukan skor anomali.
PRIORITY_FEATURES = [
    "dns_ratio",
    "web_ratio",
    "app_ratio",
    "other_ratio",
    "destination_diversity",
]

# PENDUKUNG: fitur DEVIASI dari baseline PER HOST (median & MAD robust,
# lihat baseline.py) -- BUKAN angka mentah (jumlah_koneksi dkk) lagi.
# Alasannya: kalau model dikasih angka mentah, host yang MEMANG rutin
# volumenya besar (mis. gateway/proxy) akan TERUS kelihatan "outlier"
# dibanding host lain walau itu pola normal buat host tsb -- itu akar
# masalah kenapa trafik normal sering salah ditandai Port Scan/Data
# Exfiltration. Dengan fitur deviasi, model menilai "seberapa beda jam
# ini dari kebiasaan host itu sendiri", jadi host bertrafik tinggi tapi
# KONSISTEN tidak otomatis dianggap tidak biasa.
SUPPORT_FEATURES = [f"{col}_deviation" for col in BASELINE_RAW_COLUMNS]

ALL_FEATURES = PRIORITY_FEATURES + SUPPORT_FEATURES

DROP_REDUNDANT_RATIO = False
REDUNDANT_RATIO_COLUMN = "other_ratio"

# ---------------------------------------------------------------------
# Hyperparameter Isolation Forest
# ---------------------------------------------------------------------
# PENTING: Isolation Forest DI SINI cuma tugasnya SATU -- menandai baris
# "tidak biasa" (anomaly_label) lewat contamination di bawah. Ia TIDAK
# menentukan jenis serangan (Port Scan/Data Exfiltration/dst) -- itu
# heuristik terpisah di api/classify.py yang jalan SESUDAH & TIDAK
# mengubah model ini (lihat docstring classify.py).
ISOLATION_FOREST_PARAMS = {
    "n_estimators": 200,
    "contamination": 0.005,  # di training, 0.5% data dianggap anomali
    "max_samples": "auto",
    "random_state": 42,
    "n_jobs": -1,
}
