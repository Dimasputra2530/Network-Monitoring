"""
db.py -- koneksi & query helper buat api/.

Sama seperti anomaly_detection/utils.py: TIDAK duplikasi kode koneksi
MySQL, reuse `etl_app/mysql_db.py` langsung lewat importlib. Ditulis
ulang (bukan `import` biasa) karena etl_app/, anomaly_detection/, dan
api/ semuanya flat-import (tidak ada __init__.py) dan sama-sama punya
file bernama `config.py` sendiri-sendiri -- jadi butuh penanganan
khusus supaya `from config import CLEAN_DB_CONFIG` di dalam
etl_app/mysql_db.py nyambung ke config.py milik etl_app/, bukan
tertimpa config.py milik api/.
"""
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

ETL_APP_DIR = Path(__file__).resolve().parent.parent / "etl_app"


def _load_module_from_path(unique_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(unique_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


def _import_etl_mysql_db():
    if "etl_app_mysql_db" in sys.modules:
        return sys.modules["etl_app_mysql_db"]

    if str(ETL_APP_DIR) not in sys.path:
        sys.path.insert(0, str(ETL_APP_DIR))

    own_config = sys.modules.pop("config", None)
    try:
        etl_config = _load_module_from_path("etl_app_config", ETL_APP_DIR / "config.py")
        sys.modules["config"] = etl_config
        mysql_db = _load_module_from_path("etl_app_mysql_db", ETL_APP_DIR / "mysql_db.py")
    finally:
        if own_config is not None:
            sys.modules["config"] = own_config
        else:
            sys.modules.pop("config", None)

    return mysql_db


mysql_db = _import_etl_mysql_db()  # reuse dari etl_app, BUKAN duplikasi koneksi DB


def query_df(sql: str, params: Optional[Sequence] = None) -> pd.DataFrame:
    """Jalankan query SELECT, return hasilnya sebagai pandas DataFrame.

    MySQL/pymysql bisa balikin kolom numerik (terutama hasil SUM/AVG atau
    kolom DECIMAL) sebagai `decimal.Decimal`, bukan float -- itu bikin
    operasi aritmatika biasa (mis. `/1e6`) meledak. Deteksi otomatis tiap
    kolom yang isinya Decimal (bukan cuma daftar nama tetap) lalu cast ke
    float, supaya semua endpoint aman dipakai untuk SUM/AVG apapun.
    """
    conn = mysql_db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
        df = pd.DataFrame(rows, columns=columns)
    finally:
        conn.close()

    for col in df.columns:
        if len(df) and isinstance(df[col].iloc[0], Decimal):
            df[col] = df[col].astype(float)
    for date_col in ("tanggal",):
        if date_col in df.columns and len(df):
            df[date_col] = df[date_col].astype(str)
    return df


def query_one(sql: str, params: Optional[Sequence] = None):
    """Jalankan query yang diharapkan hasilnya 1 baris, return dict (atau None)."""
    df = query_df(sql, params)
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def table_exists(table_name: str) -> bool:
    conn = mysql_db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES LIKE %s", (table_name,))
            return cur.fetchone() is not None
    finally:
        conn.close()
