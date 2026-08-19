"""
baseline.py -- baseline PERILAKU NORMAL per host/IP (srcip).

Kenapa file ini ada:
Sebelumnya Isolation Forest dikasih makan angka MENTAH (jumlah_koneksi,
jumlah_tujuan_unik, jumlah_port_unik) yang di-scale GLOBAL (StandardScaler
lewat seluruh baris/host sekaligus). Akibatnya host yang MEMANG rutin
volumenya besar (mis. gateway/proxy/server) terus-menerus kelihatan
"outlier" dibanding host lain, padahal itu pola NORMAL buat host
tersebut -- inilah akar masalah kenapa trafik normal sering salah
ditandai Port Scan/Data Exfiltration.

Modul ini menghitung baseline PER HOST (median & MAD -- Median Absolute
Deviation, lebih tahan outlier dibanding mean/std) dari data TRAINING,
lalu dipakai buat mengubah angka mentah jadi "seberapa jauh nilai jam
ini dari KEBIASAAN host itu sendiri" (robust z-score, kolom
"<fitur>_deviation"). Isolation Forest dilatih pakai fitur deviasi ini
(lihat config.SUPPORT_FEATURES), bukan angka mentah lagi.

Dipakai SIMETRIS seperti scaler di preprocessing.py: dihitung SEKALI di
train.py (dari data training), disimpan ke file, lalu dipakai ULANG
(TIDAK dihitung ulang) di predict.py/backfill_predictions.py supaya
baseline konsisten antara training & prediksi -- persis pola
fit_scaler()/transform_with_scaler() yang sudah ada.

Host yang belum punya cukup histori (baru muncul / datanya sedikit)
TETAP diproses -- pakai baseline GLOBAL (rata-rata seluruh host) sebagai
fallback, bukan di-skip atau diberi angka aman begitu saja. Kolom
"baseline_confidence" menandai host mana yang baseline-nya masih lemah,
supaya lapisan klasifikasi di atasnya (api/classify.py) tahu untuk tetap
memantau host itu (bukan langsung percaya/curiga penuh) -- baca
docstring classify.py buat detailnya.
"""
import joblib
import numpy as np
import pandas as pd

from config import BASELINE_MIN_SAMPLES, BASELINE_RAW_COLUMNS

DEVIATION_SUFFIX = "_deviation"
# Skala MAD dikali 1.4826 supaya sebanding dengan std deviasi normal
# (konvensi umum "robust z-score").
_MAD_TO_STD = 1.4826

# LANTAI skala minimum -- PENTING: banyak host punya fitur count (mis.
# jumlah_port_unik) yang KEBETULAN konstan persis di histori training-nya
# (MAD=0, mis. host yang selalu buka tepat 3 port tiap jam). Tanpa lantai
# ini, scale-nya mendekati 0, jadi beda SATU satuan pun (3 -> 4) meledak
# jadi deviasi jutaan -- itu bikin StandardScaler ikut "meledak" (fit ke
# outlier degenerate ini), yang MALAH membuat deviasi asli yang benar2
# ekstrem (mis. port scan sungguhan) jadi kelihatan kecil setelah di-scale
# relatif ke outlier degenerate itu. Lantai berikut mencegahnya:
#   - _MIN_RELATIVE_SCALE : minimal 20% dari median host itu sendiri
#     (skala otomatis proporsional -- cocok baik buat fitur count kecil
#     maupun total_data yang satuannya bytes/jutaan)
#   - _MIN_ABSOLUTE_SCALE : lantai mutlak buat kolom count kecil yang
#     median-nya sendiri rendah (mis. median 1-3 port)
_MIN_RELATIVE_SCALE = 0.20
_MIN_ABSOLUTE_SCALE = 1.0


def _robust_scale(median_vals: np.ndarray, mad_vals: np.ndarray) -> np.ndarray:
    """Skala robust z-score DENGAN lantai minimum -- lihat penjelasan
    _MIN_RELATIVE_SCALE/_MIN_ABSOLUTE_SCALE di atas."""
    mad_scale = mad_vals * _MAD_TO_STD
    relative_floor = np.abs(median_vals) * _MIN_RELATIVE_SCALE
    return np.maximum.reduce([mad_scale, relative_floor, np.full_like(mad_scale, _MIN_ABSOLUTE_SCALE)])


def compute_host_baseline(df: pd.DataFrame) -> dict:
    """Hitung baseline (median & MAD) PER HOST + fallback GLOBAL, dari
    data TRAINING saja. Hasilnya disimpan lewat save_baseline() dan
    dipakai ULANG di predict.py -- TIDAK dihitung ulang tiap prediksi."""
    columns = [c for c in BASELINE_RAW_COLUMNS if c in df.columns]

    per_host: dict[str, dict[str, dict]] = {}
    if "srcip" in df.columns:
        for srcip, g in df.groupby("srcip"):
            stats = {}
            for col in columns:
                vals = g[col].astype(float)
                median = float(vals.median())
                mad = float((vals - median).abs().median()) 
                stats[col] = {"median": median, "mad": mad, "n": int(len(vals))}
            per_host[str(srcip)] = stats

    global_stats = {}
    for col in columns:
        # PENTING: fallback global TIDAK dihitung dari SEMUA baris
        # di-pool jadi satu (df[col] mentah) -- itu mencampur variasi
        # ANTAR-host (host A rutin 2000 koneksi, host B rutin 20) dengan
        # variasi DALAM satu host, jadi sebaran "normal"-nya jadi SANGAT
        # LEBAR. Akibatnya host baru/belum dikenal yang jelas-jelas
        # ekstrem (mis. pola scanning/eksfiltrasi beneran) jadi tidak
        # kelihatan aneh sama sekali dibanding sebaran super lebar itu --
        # sensitivitas anjlok, bukan cuma buat sintetis, tapi buat host
        # BARU asli juga.
        #
        # Fallback yang benar: "kalau host ini seperti host TIPIKAL,
        # seberapa jauh nilainya dari situ" -- median DARI median tiap
        # host (bukan median semua baris), MAD DARI MAD tiap host (bukan
        # MAD semua baris). ID representasi variasi DALAM-host yang khas,
        # bukan variasi ANTAR-host.
        host_medians = [
            stats[col]["median"] for stats in per_host.values() if col in stats
        ]
        host_mads = [
            stats[col]["mad"] for stats in per_host.values() if col in stats
        ]
        if host_medians:
            median = float(np.median(host_medians))
            mad = float(np.median(host_mads)) if host_mads else 0.0
        else:
            # Belum ada host sama sekali (mis. training pertama kali,
            # data masih sangat sedikit) -- fallback terakhir: statistik
            # dari seluruh baris mentah, lebih baik daripada tidak ada
            # baseline sama sekali.
            vals = df[col].astype(float)
            median = float(vals.median())
            mad = float((vals - median).abs().median())
        global_stats[col] = {"median": median, "mad": mad, "n": len(host_medians)}

    return {
        "columns": columns,
        "per_host": per_host,
        "global": global_stats,
        "min_samples": BASELINE_MIN_SAMPLES,
    }


def apply_host_baseline(df: pd.DataFrame, baseline: dict) -> pd.DataFrame:
    """Tambah kolom "<fitur>_deviation" (robust z-score relatif ke
    baseline HOST itu sendiri, fallback ke baseline global kalau host
    belum punya cukup histori) + kolom "baseline_confidence"
    ("established" / "new_host"). TIDAK mengubah atau menghapus kolom
    data asli manapun -- cuma menambah kolom turunan baru."""
    df = df.copy()
    columns = baseline.get("columns", BASELINE_RAW_COLUMNS)
    per_host = baseline.get("per_host", {})
    global_stats = baseline.get("global", {})
    min_samples = baseline.get("min_samples", BASELINE_MIN_SAMPLES)
    n_rows = len(df)

    # Tabel kecil statistik per-host, di-merge (bukan loop manual per
    # baris) -- gaya vektor pandas yang konsisten dengan modul lain
    # (feature_selector.py, preprocessing.py).
    host_rows = []
    for srcip, stats in per_host.items():
        row = {"srcip": srcip}
        for col in columns:
            col_stats = stats.get(col)
            if col_stats:
                row[f"{col}__median"] = col_stats["median"]
                row[f"{col}__mad"] = col_stats["mad"]
                row[f"{col}__n"] = col_stats["n"]
        host_rows.append(row)
    host_df = pd.DataFrame(host_rows) if host_rows else pd.DataFrame(columns=["srcip"])

    if "srcip" in df.columns:
        merged = df[["srcip"]].merge(host_df, on="srcip", how="left")
    else:
        merged = pd.DataFrame(index=df.index)

    enough_history = np.zeros(n_rows, dtype=bool)

    for col in columns:
        if col not in df.columns:
            continue
        g_stats = global_stats.get(col, {"median": 0.0, "mad": 0.0})
        n_col, median_col, mad_col = f"{col}__n", f"{col}__median", f"{col}__mad"

        if n_col in merged.columns:
            n_vals = merged[n_col].fillna(0).to_numpy()
            has_host = n_vals >= min_samples
            median_vals = np.where(
                has_host, merged[median_col].fillna(g_stats["median"]).to_numpy(), g_stats["median"]
            )
            mad_vals = np.where(
                has_host, merged[mad_col].fillna(g_stats["mad"]).to_numpy(), g_stats["mad"]
            )
        else:
            has_host = np.zeros(n_rows, dtype=bool)
            median_vals = np.full(n_rows, g_stats["median"])
            mad_vals = np.full(n_rows, g_stats["mad"])

        enough_history = enough_history | has_host

        scale = _robust_scale(median_vals, mad_vals)
        df[f"{col}{DEVIATION_SUFFIX}"] = (df[col].astype(float).to_numpy() - median_vals) / scale

    df["baseline_confidence"] = np.where(enough_history, "established", "new_host")
    return df


def save_baseline(baseline: dict, path) -> None:
    joblib.dump(baseline, path)


def load_baseline(path) -> dict:
    return joblib.load(path)
