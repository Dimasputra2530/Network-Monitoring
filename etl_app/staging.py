"""
Dipakai untuk DUA jenis batch:
  - "detail"  : baris koneksi mentah yang sudah dibersihkan (conn_logs)
  - "features": hasil feature engineering per jam per IP (hourly_features)
"""
from datetime import datetime

import pandas as pd

from config import STAGING_DIR

REQUIRED_COLUMNS = {
    "detail": ["received_at", "srcip", "dstip_subnet", "dstport", "proto", "datasize"],
    "features": ["tanggal", "jam", "srcip", "jumlah_koneksi",
                 "jumlah_tujuan_unik", "jumlah_port_unik", "tcp", "udp", "total_data"],
}


def write_staging_csv(df: pd.DataFrame, kind: str = "detail"):
    batch_id = datetime.now().strftime(f"{kind}_%Y%m%d_%H%M%S")
    path = STAGING_DIR / f"{batch_id}.csv"
    df.to_csv(path, index=False)
    return str(path), batch_id


def write_features_by_date(features_df: pd.DataFrame) -> list[str]:
    """Pecah hasil feature engineering jadi SATU FILE CSV PER TANGGAL di
    staging/ (bukan 1 file gabungan semua tanggal). Nama file:
    staging/features_<tanggal>.csv, mis. staging/features_2026-07-19.csv.

    File per tanggal DITIMPA tiap kali fungsi ini dipanggil (idempotent) --
    supaya kalau ada data baru masuk untuk tanggal yang sama, file tanggal
    itu otomatis ter-update jadi versi terbaru/lengkap, bukan numpuk jadi
    banyak file untuk tanggal yang sama."""
    if features_df.empty:
        return []

    written_paths = []
    for tanggal, group_df in features_df.groupby("tanggal"):
        path = STAGING_DIR / f"features_{tanggal}.csv"
        group_df.to_csv(path, index=False)
        written_paths.append(str(path))

    return written_paths


def load_all_detail_csv() -> pd.DataFrame:
    """Baca dan gabungkan SEMUA file staging/detail_*.csv yang ada (batch
    lama maupun baru), bukan cuma batch hasil siklus ETL saat ini.

    Dipakai supaya Feature Engineering menghitung dari SELURUH histori data
    yang sudah pernah masuk ke staging, bukan cuma batch terbaru saja."""
    detail_files = sorted(STAGING_DIR.glob("detail_*.csv"))
    if not detail_files:
        return pd.DataFrame(columns=REQUIRED_COLUMNS["detail"])

    frames = []
    for f in detail_files:
        try:
            df = pd.read_csv(f)
            # Parse received_at PER FILE (bukan setelah digabung) -- supaya
            # aman kalau ada perbedaan representasi timezone antar batch
            # (mis. offset yang beda), yang kalau digabung dulu sebagai teks
            # bisa bikin pandas gagal parse sebagian baris jadi NaT.
            df["received_at"] = pd.to_datetime(df["received_at"], errors="coerce")
            frames.append(df)
        except Exception as e:
            print(f"[staging] Lewati {f.name}, gagal dibaca: {e}")

    if not frames:
        return pd.DataFrame(columns=REQUIRED_COLUMNS["detail"])

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined = combined.dropna(subset=["received_at"])
    dropped = before - len(combined)
    if dropped:
        print(f"[staging] {dropped} baris histori dibuang karena received_at tidak valid setelah parsing")
    return combined


def validate_staging_csv(path: str, kind: str = "detail"):
    issues = []
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return False, [f"Gagal membaca CSV: {e}"]

    if df.empty:
        return True, []  # batch kosong bukan error, cuma tidak ada apa-apa untuk dimuat

    required = REQUIRED_COLUMNS[kind]
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        issues.append(f"Kolom hilang: {missing_cols}")
        return False, issues

    if kind == "detail":
        if df["received_at"].isna().any():
            issues.append("Ada baris dengan received_at kosong")
        if df["dstip_subnet"].isna().any() or (df["dstip_subnet"] == "").any():
            issues.append("Ada baris dengan dstip_subnet kosong")
        if (df["datasize"] < 0).any():
            issues.append("Ada nilai datasize negatif")
        invalid_subnet_ratio = (df["dstip_subnet"] == "invalid/24").mean()
        if invalid_subnet_ratio > 0.5:
            issues.append(f"Lebih dari separuh baris ({invalid_subnet_ratio:.0%}) punya dstip tidak valid")

    elif kind == "features":
        if df["srcip"].isna().any() or (df["srcip"] == "").any():
            issues.append("Ada baris dengan srcip kosong")
        if (df["jumlah_koneksi"] < 0).any() or (df["total_data"] < 0).any():
            issues.append("Ada nilai jumlah_koneksi/total_data negatif")
        # Kolom jam sekarang berformat "HH:00" (mis. "15:00"), bukan angka polos.
        jam_str = df["jam"].astype(str)
        jam_valid = jam_str.str.match(r"^([01]\d|2[0-3]):00$")
        if not jam_valid.all():
            issues.append("Ada nilai jam yang formatnya bukan 'HH:00' atau di luar rentang 00:00-23:00")

    return (len(issues) == 0), issues
