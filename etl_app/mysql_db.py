"""
Loader ke MySQL (database bersih `network_clean`) -- 2 tabel:

  1) raw_data  -- data detail mentah per-baris koneksi, hasil clean.py
  2) hourly_features -- hasil feature_engineering.py (per jam, per host)
"""
from pathlib import Path

import pandas as pd
import pymysql

from config import CLEAN_DB_CONFIG, BASE_DIR

SCHEMA_PATH = BASE_DIR / "schema.sql"

# executemany() PyMySQL menggabungkan SEMUA baris jadi SATU query besar
# (INSERT ... VALUES (...),(...),...). Kalau baris nya banyak (mis. pas
# backfill histori lama, bisa ratusan ribu baris), query itu bisa lebih
# besar dari max_allowed_packet di server MySQL -> error "Got a packet
# bigger than 'max_allowed_packet' bytes". Makanya di-kirim per-CHUNK
# kecil, bukan sekaligus semua baris dalam 1 query.
CHUNK_SIZE = 2000


def _executemany_chunked(cur, sql: str, rows: list) -> None:
    for i in range(0, len(rows), CHUNK_SIZE):
        cur.executemany(sql, rows[i:i + CHUNK_SIZE])


def get_connection():
    """Buka koneksi baru ke MySQL pakai CLEAN_DB_CONFIG dari .env."""
    return pymysql.connect(
        host=CLEAN_DB_CONFIG["host"],
        port=CLEAN_DB_CONFIG["port"],
        user=CLEAN_DB_CONFIG["user"],
        password=CLEAN_DB_CONFIG["password"],
        database=CLEAN_DB_CONFIG["database"],
        charset="utf8mb4",
        autocommit=False,
    )


def init_schema() -> None:
    """Jalankan schema.sql (CREATE DATABASE/TABLE IF NOT EXISTS) supaya
    kedua tabel pasti ada sebelum insert pertama kali. Aman dipanggil
    berkali-kali -- statement-nya semua idempotent (IF NOT EXISTS)."""
    sql_text = Path(SCHEMA_PATH).read_text(encoding="utf-8")
    # CREATE DATABASE butuh koneksi TANPA database dulu (network_clean
    # mungkin belum ada), baru abis itu USE network_clean.
    conn = pymysql.connect(
        host=CLEAN_DB_CONFIG["host"],
        port=CLEAN_DB_CONFIG["port"],
        user=CLEAN_DB_CONFIG["user"],
        password=CLEAN_DB_CONFIG["password"],
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            for statement in sql_text.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Tabel 1: raw_data
# ---------------------------------------------------------------------

RAW_DATA_COLUMNS = ["received_at", "srcip", "dstip_subnet", "dstport", "proto", "datasize"]


def load_raw_data(df: pd.DataFrame) -> int:
    """Insert (append) baris detail hasil cleaning ke tabel raw_data.
    Return jumlah baris yang berhasil di-insert. Kalau df kosong,
    tidak melakukan apa-apa dan return 0."""
    if df.empty:
        return 0

    df = df.copy()
    # received_at datang dengan offset timezone (mis. "...+07:00"), tapi
    # kolom MySQL DATETIME tidak menerima offset -- konversi ke UTC lalu
    # buang info timezone-nya (disimpan sebagai UTC naive).
    df["received_at"] = pd.to_datetime(df["received_at"], utc=True).dt.tz_localize(None)

    rows = list(
        df[RAW_DATA_COLUMNS]
        .itertuples(index=False, name=None)
    )

    sql = f"""
        INSERT INTO raw_data ({", ".join(RAW_DATA_COLUMNS)})
        VALUES ({", ".join(["%s"] * len(RAW_DATA_COLUMNS))})
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _executemany_chunked(cur, sql, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return len(rows)


# ---------------------------------------------------------------------
# Tabel 2: hourly_features
# ---------------------------------------------------------------------

HOURLY_FEATURES_COLUMNS = [
    "tanggal", "jam", "srcip",
    "jumlah_koneksi", "jumlah_tujuan_unik", "jumlah_port_unik", "tcp", "udp",
    "total_data", "average_datasize",
    "dns", "web", "app", "other",
    "dns_ratio", "web_ratio", "app_ratio", "other_ratio",
    "destination_diversity",
]

# Kolom yang di-UPDATE kalau (tanggal, jam, srcip) sudah ada (upsert) --
# semua kolom KECUALI key komposit-nya sendiri.
_UPDATE_COLUMNS = [c for c in HOURLY_FEATURES_COLUMNS if c not in ("tanggal", "jam", "srcip")]


def load_hourly_features(df: pd.DataFrame) -> int:
    """Upsert baris hasil feature engineering ke tabel hourly_features,
    key-nya (tanggal, jam, srcip). Return jumlah baris yang diproses
    (insert atau update). Kalau df kosong, tidak melakukan apa-apa dan
    return 0."""
    if df.empty:
        return 0

    rows = list(
        df[HOURLY_FEATURES_COLUMNS]
        .itertuples(index=False, name=None)
    )

    update_clause = ", ".join(f"{col} = VALUES({col})" for col in _UPDATE_COLUMNS)
    sql = f"""
        INSERT INTO hourly_features ({", ".join(HOURLY_FEATURES_COLUMNS)})
        VALUES ({", ".join(["%s"] * len(HOURLY_FEATURES_COLUMNS))})
        ON DUPLICATE KEY UPDATE {update_clause}
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _executemany_chunked(cur, sql, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return len(rows)
