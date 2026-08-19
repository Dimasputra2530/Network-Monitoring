"""
Tanggung jawab file ini: ubah fitur MENTAH (hasil feature_selector.py)
jadi array numerik yang siap dilempar ke Isolation Forest.

Isinya CUMA transformasi data (missing value + scaling) -- tidak ada
logic milih kolom (itu punya feature_selector.py) dan tidak ada logic
training/predict (itu punya model.py). Satu file, satu tanggung jawab.
"""
import joblib
import pandas as pd
from sklearn.preprocessing import StandardScaler


def handle_missing_values(X: pd.DataFrame) -> pd.DataFrame:
    """Isi nilai kosong dengan 0 -- aman buat semua fitur yang dipakai
    (rasio/diversity kosong = tidak ada koneksi kategori itu = 0 secara
    makna; jumlah_koneksi dkk kosong = tidak ada aktivitas = 0). Baris
    NaN idealnya memang jarang terjadi karena feature_engineering.py
    sudah menjamin jumlah_koneksi tidak pernah 0 per baris, tapi tetap
    dijaga di sini sebagai lapisan aman kalau ada data longgar/rusak."""
    return X.fillna(0)


def fit_scaler(X: pd.DataFrame) -> tuple[StandardScaler, "pd.DataFrame"]:
    """Fit StandardScaler baru dari data training, return scaler-nya
    plus data yang sudah di-scale. DIPAKAI CUMA DI train.py -- predict.py
    harus pakai transform_with_scaler() (scaler yang SUDAH ADA), bukan
    fit ulang, supaya skala fitur konsisten antara training & prediksi."""
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    return scaler, pd.DataFrame(X_scaled, columns=X.columns, index=X.index)


def transform_with_scaler(scaler: StandardScaler, X: pd.DataFrame) -> pd.DataFrame:
    """Scale data BARU pakai scaler yang sudah dilatih sebelumnya
    (dipakai predict.py). Kolom X harus sama persis (nama & urutan)
    dengan yang dipakai waktu scaler di-fit -- ini dijamin karena
    keduanya lewat feature_selector.select_features() yang sama."""
    X_scaled = scaler.transform(X)
    return pd.DataFrame(X_scaled, columns=X.columns, index=X.index)


def save_scaler(scaler: StandardScaler, path) -> None:
    joblib.dump(scaler, path)


def load_scaler(path) -> StandardScaler:
    return joblib.load(path)