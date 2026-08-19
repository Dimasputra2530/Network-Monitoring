"""
Util bersama buat anomaly_detection -- terutama buat BACA hasil ETL
(tabel `hourly_features` di MySQL) TANPA menduplikasi kode koneksi database.

etl_app/ bukan package Python yang di-install (tidak ada __init__.py,
tiap file impor modul lain secara "flat", asumsi dijalankan dari dalam
folder etl_app/). anomaly_detection/ juga punya file bernama config.py
sendiri -- supaya DUA config.py ini (etl_app/config.py &
anomaly_detection/config.py) tidak saling tabrakan pas anomaly_detection
ikut mengimpor etl_app/mysql_db.py (yang di dalamnya ada baris
`from config import ...`), mysql_db.py di-load lewat importlib dengan
key sys.modules yang unik -- SATU tempat saja, dipakai train.py & predict.py.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd

ETL_APP_DIR = Path(__file__).resolve().parent.parent / "etl_app"


def _load_module_from_path(unique_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(unique_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


def _import_etl_mysql_db():
    """Import etl_app/mysql_db.py TANPA menduplikasi kodenya, dan TANPA
    bentrok sama anomaly_detection/config.py (dua-duanya sama-sama
    punya modul bernama 'config', gaya flat-import yang sudah dipakai
    di seluruh project ini)."""
    if "etl_app_mysql_db" in sys.modules:
        return sys.modules["etl_app_mysql_db"]

    if str(ETL_APP_DIR) not in sys.path:
        sys.path.insert(0, str(ETL_APP_DIR))

    # Simpan config milik anomaly_detection (kalau sudah ke-load), ganti
    # SEMENTARA sys.modules["config"] jadi punya etl_app/ -- supaya
    # `from config import CLEAN_DB_CONFIG` di DALAM mysql_db.py nyambung
    # ke config yang BENAR (etl_app/config.py), bukan config kita.
    own_config = sys.modules.pop("config", None)
    try:
        etl_config = _load_module_from_path("etl_app_config", ETL_APP_DIR / "config.py")
        sys.modules["config"] = etl_config
        mysql_db = _load_module_from_path("etl_app_mysql_db", ETL_APP_DIR / "mysql_db.py")
    finally:
        # Kembalikan config milik anomaly_detection, supaya file lain di
        # sini (train.py, feature_selector.py, dst) yang `import config`
        # tetap dapat config.py miliknya sendiri, bukan punya etl_app.
        if own_config is not None:
            sys.modules["config"] = own_config
        else:
            sys.modules.pop("config", None)

    return mysql_db


mysql_db = _import_etl_mysql_db()  # reuse dari etl_app, BUKAN duplikasi koneksi DB


def load_etl_output(min_tanggal: str | None = None) -> pd.DataFrame:
    """Baca hasil ETL (tabel `hourly_features`) langsung dari MySQL -- ini SUMBER
    DATA UTAMA buat training & prediksi, bukan baca ulang CSV.

    min_tanggal: filter opsional, mis. "2026-07-19" -- kalau diisi,
    cuma ambil baris tanggal >= itu (buat predict.py yang cuma perlu
    data terbaru, tidak perlu tarik seluruh histori tiap kali).

    Pakai cursor manual (bukan pandas.read_sql langsung ke koneksi
    pymysql) supaya tidak muncul UserWarning "DBAPI2 not tested" dari
    pandas -- pymysql memang bukan SQLAlchemy engine, tapi cara ini
    tetap benar & bersih tanpa nambah dependency SQLAlchemy."""
    conn = mysql_db.get_connection()
    try:
        query = "SELECT * FROM hourly_features"
        params = None
        if min_tanggal:
            query += " WHERE tanggal >= %s"
            params = (min_tanggal,)
        query += " ORDER BY tanggal, jam, srcip"
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
        df = pd.DataFrame(rows, columns=columns)
    finally:
        conn.close()

    # Kolom MySQL bertipe DECIMAL (dns_ratio, web_ratio, app_ratio, other_ratio,
    # destination_diversity, average_datasize) otomatis jadi Decimal Python lewat
    # pymysql -- Decimal selalu nampilin trailing zero penuh (mis. Decimal('1.0000')),
    decimal_columns = [
        c for c in ["dns_ratio", "web_ratio", "app_ratio", "other_ratio",
                     "destination_diversity", "average_datasize"]
        if c in df.columns
    ]
    if decimal_columns:
        df[decimal_columns] = df[decimal_columns].astype(float)

    return df


def latest_tanggal_in_output(df: pd.DataFrame) -> str | None:
    """Tanggal terbaru yang ada di suatu DataFrame hasil ETL (dipakai
    predict.py buat nge-print ringkasan, bukan logic inti)."""
    if df.empty:
        return None
    return str(df["tanggal"].max())
