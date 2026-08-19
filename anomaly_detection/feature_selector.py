"""
Tanggung jawab file ini CUMA SATU: menentukan kolom mana dari hasil ETL
yang dipakai sebagai fitur model, dan memilihnya dari DataFrame.
"""
import pandas as pd

from config import ALL_FEATURES, DROP_REDUNDANT_RATIO, REDUNDANT_RATIO_COLUMN


def get_feature_columns() -> list[str]:
    """Daftar kolom fitur yang dipakai model, sesudah mempertimbangkan
    DROP_REDUNDANT_RATIO dari config.py."""
    columns = list(ALL_FEATURES)
    if DROP_REDUNDANT_RATIO and REDUNDANT_RATIO_COLUMN in columns:
        columns.remove(REDUNDANT_RATIO_COLUMN)
    return columns


def select_features(df: pd.DataFrame) -> pd.DataFrame:
    """Ambil cuma kolom fitur dari hasil ETL, urutannya konsisten
    (penting -- scaler & model dilatih dengan urutan kolom tertentu,
    urutan yang beda di predict.py bisa bikin prediksi salah walau
    tidak error). Meledak lebih awal & jelas kalau ada kolom yang hilang
    dari hasil ETL, daripada silent-fail di tengah training/prediksi."""
    feature_columns = get_feature_columns()
    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"Kolom fitur berikut tidak ada di hasil ETL: {missing}. "
            f"Cek apakah feature_engineering.py di etl_app/ masih menghasilkan "
            f"kolom ini, atau apakah config.py di anomaly_detection/ perlu di-update."
        )
    return df[feature_columns].copy()
