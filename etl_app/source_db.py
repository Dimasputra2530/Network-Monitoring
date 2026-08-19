"""
Koneksi ke server PRODUKSI (PostgreSQL) -- SELALU read-only
"""
import psycopg2
import psycopg2.extras
import pandas as pd

from config import SRC_DB_CONFIG, PULL_WINDOW_HOURS


def get_source_connection():
    conn = psycopg2.connect(**SRC_DB_CONFIG)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def fetch_new_rows(last_source_id: int) -> pd.DataFrame:
    conn = get_source_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, received_at, srcip, dstip, dstport, proto, datasize
            FROM syslog
            WHERE received_at >= NOW() - (%s * INTERVAL '1 hour')
              AND id > %s
            ORDER BY id ASC;
            """,
            (PULL_WINDOW_HOURS, last_source_id),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame(
            columns=["id", "received_at", "srcip", "dstip", "dstport", "proto", "datasize"]
        )
    return pd.DataFrame(rows)
