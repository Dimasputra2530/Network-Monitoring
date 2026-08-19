"""
Prediction pipeline Isolation Forest.
"""
import argparse
from datetime import datetime

import baseline
import config
import feature_selector
import model as model_module
import predictions_db
import preprocessing
import utils


def main(min_tanggal: str | None = None):
    print(f"[{datetime.now().isoformat()}] === Prediksi Anomali ===")

    if not config.MODEL_PATH.exists() or not config.SCALER_PATH.exists() or not config.BASELINE_PATH.exists():
        print(f"Model/scaler/baseline belum ada di {config.MODEL_DIR}. Jalankan train.py dulu.")
        return

    print("[1/7] Load hasil ETL dari MySQL (tabel hourly_features)...")
    df = utils.load_etl_output(min_tanggal=min_tanggal)
    if df.empty:
        print("Tidak ada baris untuk diprediksi.")
        return
    print(f"      {len(df)} baris dimuat (tanggal {df['tanggal'].min()} s.d. {df['tanggal'].max()}).")

    print("[2/7] Load model + scaler + baseline (SUDAH DILATIH, bukan fit ulang)...")
    model = model_module.load_model(config.MODEL_PATH)
    scaler = preprocessing.load_scaler(config.SCALER_PATH)
    host_baseline = baseline.load_baseline(config.BASELINE_PATH)

    print("[3/7] Terapkan baseline per host/IP (tambah kolom deviasi)...")
    df = baseline.apply_host_baseline(df, host_baseline)

    print("[4/7] Pilih kolom fitur (sama seperti waktu training)...")
    X_raw = feature_selector.select_features(df)

    print("[5/7] Preprocessing (missing value + scaling pakai scaler yang sudah ada)...")
    X_clean = preprocessing.handle_missing_values(X_raw)
    X_scaled = preprocessing.transform_with_scaler(scaler, X_clean)

    print("[6/7] Predict anomaly_score & anomaly_label (Isolation Forest cuma menandai "
          "TIDAK BIASA, bukan jenis serangan -- lihat api/classify.py buat tipe/status)...")
    scores = model_module.anomaly_scores(model, X_scaled)
    labels = model_module.predict_labels(model, X_scaled)

    result = df[[
        "tanggal", "jam", "srcip",
        "jumlah_koneksi", "jumlah_tujuan_unik", "jumlah_port_unik",
        "dns_ratio", "web_ratio", "app_ratio", "other_ratio",
        "destination_diversity",
        "total_data", "average_datasize",
        "jumlah_koneksi_deviation", "jumlah_tujuan_unik_deviation",
        "jumlah_port_unik_deviation", "total_data_deviation",
        "baseline_confidence",
    ]].copy()
    result["anomaly_score"] = scores.values
    result["anomaly_label"] = labels.values

    #ngubah label 0/1 jadi Normal/Anomaly biar gampang dibaca
    result["anomaly_label"] = result["anomaly_label"].replace({
    0: "Normal",
    1: "Anomaly"
    })

    result.to_csv(config.ANOMALY_RESULTS_PATH, index=False)

    print("[7/7] Simpan histori prediksi ke MySQL (tabel anomaly_predictions)...")
    predictions_db.init_schema()
    n_saved = predictions_db.save_predictions(result)
    print(f"      {n_saved} baris di-upsert -- dipakai buat laporan bulanan/tahunan (reports.py).")

    n_anomaly = (result["anomaly_label"] == "Anomaly").sum()
    print(f"[selesai] {len(result)} baris diprediksi, {n_anomaly} ditandai anomali "
          f"({n_anomaly / len(result):.2%}).")
    print(f"          CSV   -> {config.ANOMALY_RESULTS_PATH}")
    print(f"          MySQL -> tabel anomaly_predictions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prediksi anomali dari hasil ETL.")
    parser.add_argument("--tanggal", default=None,
                         help="Cuma prediksi baris tanggal >= ini (format YYYY-MM-DD). "
                              "Kosongkan buat prediksi SEMUA data di tabel hourly_features.")
    args = parser.parse_args()
    main(min_tanggal=args.tanggal)
