"""
predictions_db.py -- Simpan histori hasil prediksi anomali ke MySQL (tabel
`anomaly_predictions`), TERPISAH dari `anomaly_results.csv`.

Kenapa perlu ini: predict.py sebelumnya cuma nulis anomaly_results.csv,
yang DITIMPA TOTAL tiap kali dijalankan -- jadi tidak ada histori hasil
prediksi yang bisa dipakai buat laporan bulanan/tahunan (cuma snapshot
terakhir). Tabel ini upsert (UNIQUE KEY tanggal+jam+srcip), sama seperti
`hourly_features` di etl_app -- aman dijalankan berkali-kali, hasilnya
terakumulasi jadi arsip histori yang bisa di-query per bulan/tahun lewat
reports.py.

Reuse koneksi dari utils.mysql_db (etl_app/mysql_db.py) -- TIDAK
duplikasi kode koneksi database.
"""
from pathlib import Path

import pandas as pd

import utils

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

PREDICTION_COLUMNS = [
    "tanggal", "jam", "srcip",
    "jumlah_koneksi", "jumlah_tujuan_unik", "jumlah_port_unik",
    "dns_ratio", "web_ratio", "app_ratio", "other_ratio", "destination_diversity",
    "total_data", "average_datasize",
    "jumlah_koneksi_deviation", "jumlah_tujuan_unik_deviation",
    "jumlah_port_unik_deviation", "total_data_deviation",
    "baseline_confidence",
    "anomaly_score", "anomaly_label",
]

# Kolom yang ditambahkan belakangan (baseline per host + volume) --
# dipakai _ensure_new_columns() buat ALTER TABLE kalau tabel
# anomaly_predictions SUDAH ADA dari versi sebelumnya (CREATE TABLE IF
# NOT EXISTS di init_schema() tidak akan menambah kolom ke tabel yang
# sudah ada, jadi perlu migrasi ringan ini supaya deployment lama tetap
# aman di-upgrade tanpa hapus data histori yang sudah terkumpul).
_NEW_COLUMNS_DDL = {
    "total_data": "BIGINT NOT NULL DEFAULT 0",
    "average_datasize": "DECIMAL(10,2) NOT NULL DEFAULT 0",
    "jumlah_koneksi_deviation": "DECIMAL(12,4) NOT NULL DEFAULT 0",
    "jumlah_tujuan_unik_deviation": "DECIMAL(12,4) NOT NULL DEFAULT 0",
    "jumlah_port_unik_deviation": "DECIMAL(12,4) NOT NULL DEFAULT 0",
    "total_data_deviation": "DECIMAL(12,4) NOT NULL DEFAULT 0",
    "baseline_confidence": "VARCHAR(20) NOT NULL DEFAULT 'new_host'",
}


def _ensure_new_columns(conn) -> None:
    """Tambah kolom baru ke tabel anomaly_predictions kalau belum ada
    (aman dipanggil berkali-kali, cuma nge-ALTER kolom yang benar-benar
    hilang). TIDAK menyentuh/menghapus data baris yang sudah ada."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'anomaly_predictions'"""
        )
        existing = {row[0] for row in cur.fetchall()}
        if not existing:
            return  # tabel belum ada -- CREATE TABLE di init_schema() yang urus
        for column, ddl in _NEW_COLUMNS_DDL.items():
            if column not in existing:
                cur.execute(f"ALTER TABLE anomaly_predictions ADD COLUMN {column} {ddl}")
    conn.commit()


def init_schema() -> None:
    """Jalankan schema.sql (CREATE TABLE IF NOT EXISTS anomaly_predictions),
    lalu pastikan kolom-kolom baru (baseline/volume) ada juga kalau
    tabelnya sudah dibuat dari versi sebelumnya. Aman dipanggil
    berkali-kali -- tidak akan menghapus data yang sudah ada."""
    conn = utils.mysql_db.get_connection()
    try:
        statements = [
            s.strip() for s in SCHEMA_PATH.read_text().split(";") if s.strip()
        ]
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        _ensure_new_columns(conn)
    finally:
        conn.close()


def save_predictions(df: pd.DataFrame) -> int:
    """Upsert baris hasil prediksi ke tabel anomaly_predictions, key-nya
    (tanggal, jam, srcip) -- kalau predict.py dijalankan ulang buat
    tanggal yang sama, baris lama di-UPDATE (bukan dobel/duplikat).
    Return jumlah baris yang diproses (insert atau update)."""
    if df.empty:
        return 0

    rows = list(df[PREDICTION_COLUMNS].itertuples(index=False, name=None))

    update_cols = [c for c in PREDICTION_COLUMNS if c not in ("tanggal", "jam", "srcip")]
    update_clause = ", ".join(f"{c} = VALUES({c})" for c in update_cols)
    sql = f"""
        INSERT INTO anomaly_predictions ({", ".join(PREDICTION_COLUMNS)})
        VALUES ({", ".join(["%s"] * len(PREDICTION_COLUMNS))})
        ON DUPLICATE KEY UPDATE {update_clause}
    """

    conn = utils.mysql_db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()

    return len(rows)
