import json
from pathlib import Path

from config import BASE_DIR, DATA_DIR

ETL_STATE_PATH = BASE_DIR / "etl_state.json"


# ---------------------------------------------------------------------
# Watermark (ETL state) -- disimpan lokal (JSON), menggantikan tabel
# etl_state di MySQL yang sudah tidak dipakai lagi.
# ---------------------------------------------------------------------

def get_last_source_id() -> int:
    """Baca watermark terakhir dari etl_state.json. Kalau file belum ada
    (run pertama kali) atau isinya rusak, dianggap 0 (mulai dari awal)."""
    if not ETL_STATE_PATH.exists():
        return 0
    try:
        data = json.loads(ETL_STATE_PATH.read_text())
        return int(data.get("last_source_id", 0))
    except Exception:
        return 0


def set_etl_state(last_source_id: int, batch_rows: int) -> None:
    """Simpan watermark terbaru ke etl_state.json setelah satu siklus ETL
    berhasil, supaya siklus berikutnya tidak menarik ulang baris yang
    sama dari PostgreSQL."""
    from datetime import datetime

    ETL_STATE_PATH.write_text(
        json.dumps(
            {
                "last_source_id": last_source_id,
                "last_batch_rows": batch_rows,
                "last_run_at": datetime.now().isoformat(),
            },
            indent=2,
        )
    )


# ---------------------------------------------------------------------
# Simpan hasil FINAL Feature Engineering ke folder data/
# ---------------------------------------------------------------------

def save_features_to_data(features_df, filename: str = "hourly_features.csv") -> str:
    """Tulis DataFrame hasil feature engineering (SEMUA tanggal) ke
    data/hourly_features.csv, nama file TETAP (ditimpa tiap siklus) --
    ini snapshot gabungan buat tahap berikutnya / MySQL. Beda dari
    staging/features_<tanggal>.csv yang sudah dipecah per tanggal."""
    dest_path = Path(DATA_DIR) / filename
    features_df.to_csv(dest_path, index=False)
    return str(dest_path)
