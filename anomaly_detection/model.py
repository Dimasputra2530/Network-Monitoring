"""
Tanggung jawab file ini: SEMUA hal yang berhubungan langsung dengan
model Isolation Forest -- train, predict, decision function, simpan,
muat. train.py dan predict.py tidak pernah panggil sklearn langsung,
selalu lewat fungsi-fungsi di sini -- supaya kalau nanti ganti
algoritma (mis. dari Isolation Forest ke model lain), cukup ubah file
ini, train.py/predict.py tidak perlu diubah.
"""
import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

from config import ISOLATION_FOREST_PARAMS


def train_model(X: pd.DataFrame) -> IsolationForest:
    """Latih Isolation Forest baru dari data training (sudah di-scale)."""
    model = IsolationForest(**ISOLATION_FOREST_PARAMS)
    model.fit(X)
    return model


def predict_labels(model: IsolationForest, X: pd.DataFrame) -> pd.Series:
    """Label anomali per baris: 1 = ANOMALI, 0 = NORMAL.

    Catatan: sklearn IsolationForest.predict() aslinya balikin -1
    (anomali) / 1 (normal) -- di sini di-mapping ulang ke 1/0 supaya
    lebih intuitif dibaca di CSV hasil akhir (anomaly_label=1 artinya
    "iya, ini anomali", bukan angka -1 yang gampang ke-mispersepsi)."""
    raw = model.predict(X)  # -1 = anomali, 1 = normal
    return pd.Series((raw == -1).astype(int), index=X.index, name="anomaly_label")


def anomaly_scores(model: IsolationForest, X: pd.DataFrame) -> pd.Series:
    """Skor anomali per baris, MAKIN KECIL (makin negatif) = MAKIN
    ANOMALI. Ini kebalikan dari decision_function() bawaan sklearn
    (yang skornya makin BESAR = makin normal) -- dibalik tandanya (*-1)
    supaya lebih intuitif: 'anomaly_score tinggi = makin mencurigakan',
    konsisten sama nama kolomnya."""
    raw = model.decision_function(X)  # makin besar = makin normal (bawaan sklearn)
    return pd.Series(-raw, index=X.index, name="anomaly_score").round(6)


def save_model(model: IsolationForest, path) -> None:
    joblib.dump(model, path)


def load_model(path) -> IsolationForest:
    return joblib.load(path)
