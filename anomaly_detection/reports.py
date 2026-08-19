"""
reports.py -- Laporan agregat (bulanan/tahunan) dari tabel `anomaly_predictions`.

Butuh predictions_db.py sudah pernah dipanggil minimal sekali (predict.py
sudah jalan, tabelnya sudah ada isinya) -- kalau tabelnya kosong/belum ada,
fungsi di sini balikin ringkasan kosong, bukan error.
"""
import pandas as pd

import utils


def _load_predictions(where_sql: str, params: tuple) -> pd.DataFrame:
    conn = utils.mysql_db.get_connection()
    try:
        query = (
            f"SELECT * FROM anomaly_predictions WHERE {where_sql} "
            f"ORDER BY tanggal, jam, srcip"
        )
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
        df = pd.DataFrame(rows, columns=columns)
    finally:
        conn.close()

    # Sama seperti utils.load_etl_output() -- kolom DECIMAL dari MySQL
    # otomatis jadi Decimal Python, cast ke float supaya aman diolah/ditulis.
    decimal_columns = [
        c for c in ["dns_ratio", "web_ratio", "app_ratio", "other_ratio",
                     "destination_diversity", "anomaly_score"]
        if c in df.columns
    ]
    if decimal_columns:
        df[decimal_columns] = df[decimal_columns].astype(float)

    return df


def _empty_summary(periode: str) -> dict:
    return {
        "periode": periode,
        "total_baris": 0,
        "total_anomali": 0,
        "tingkat_anomali": 0.0,
        "top_host_anomali": {},
    }


def _summarize(df: pd.DataFrame) -> dict:
    total = len(df)
    anomaly_rows = df[df["anomaly_label"] == "Anomaly"]
    n_anomaly = len(anomaly_rows)
    top_hosts = anomaly_rows["srcip"].value_counts().head(10).to_dict()
    return {
        "total_baris": total,
        "total_anomali": n_anomaly,
        "tingkat_anomali": round(n_anomaly / total, 4) if total else 0.0,
        "top_host_anomali": top_hosts,
    }


def get_monthly_report(year: int, month: int) -> dict:
    """Ringkasan + tren HARIAN untuk 1 bulan tertentu."""
    periode = f"{year}-{month:02d}"
    df = _load_predictions("YEAR(tanggal) = %s AND MONTH(tanggal) = %s", (year, month))

    if df.empty:
        summary = _empty_summary(periode)
        summary["tren_harian"] = []
        return summary

    summary = _summarize(df)
    summary["periode"] = periode

    daily = df.groupby(df["tanggal"].astype(str)).apply(
        lambda g: pd.Series({
            "total_baris": len(g),
            "total_anomali": int((g["anomaly_label"] == "Anomaly").sum()),
        })
    ).reset_index().rename(columns={"index": "tanggal"})
    summary["tren_harian"] = daily.to_dict(orient="records")

    return summary


def get_yearly_report(year: int) -> dict:
    """Ringkasan + tren BULANAN untuk 1 tahun tertentu."""
    periode = str(year)
    df = _load_predictions("YEAR(tanggal) = %s", (year,))

    if df.empty:
        summary = _empty_summary(periode)
        summary["tren_bulanan"] = []
        return summary

    summary = _summarize(df)
    summary["periode"] = periode

    df = df.copy()
    df["bulan"] = pd.to_datetime(df["tanggal"]).dt.month
    monthly = df.groupby("bulan").apply(
        lambda g: pd.Series({
            "total_baris": len(g),
            "total_anomali": int((g["anomaly_label"] == "Anomaly").sum()),
        })
    ).reset_index()
    summary["tren_bulanan"] = monthly.to_dict(orient="records")

    return summary
