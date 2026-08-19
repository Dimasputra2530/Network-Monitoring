"""
backfill_predictions.py -- Script SEKALI-JALAN buat isi tabel
`anomaly_predictions` dari SELURUH histori `hourly_features` yang sudah
ada, pakai model yang SUDAH DILATIH (tidak training ulang).

Kenapa perlu ini: tabel `anomaly_predictions` baru dibuat (lihat
schema.sql/predictions_db.py) -- kalau cuma jalanin `predict.py` biasa,
dia memang tetap prediksi & upsert SEMUA baris di `hourly_features`
(default `min_tanggal=None` = semua data), jadi secara fungsi SAMA
PERSIS dengan script ini. Bedanya cuma di penamaan & tujuan: script ini
eksplisit buat "isi histori dari nol", mirip peran
`etl_app/backfill_mysql.py` buat tabel `raw_data`/`hourly_features`.

Aman dijalankan berkali-kali -- upsert (`UNIQUE KEY tanggal+jam+srcip`),
tidak akan dobel.

Jalankan:
    cd anomaly_detection
    python backfill_predictions.py
"""
from datetime import datetime

import baseline
import config
import feature_selector
import model as model_module
import predictions_db
import preprocessing
import utils


def main():
    print(f"[{datetime.now().isoformat()}] === Backfill anomaly_predictions ===")

    if not config.MODEL_PATH.exists() or not config.SCALER_PATH.exists() or not config.BASELINE_PATH.exists():
        print(f"Model/scaler/baseline belum ada di {config.MODEL_DIR}. Jalankan train.py dulu.")
        return

    print("[1/7] Load SELURUH histori dari MySQL (tabel hourly_features)...")
    df = utils.load_etl_output(min_tanggal=None)
    if df.empty:
        print("Tabel hourly_features kosong -- tidak ada yang bisa di-backfill.")
        return
    print(f"      {len(df)} baris dimuat (tanggal {df['tanggal'].min()} s.d. {df['tanggal'].max()}).")

    print("[2/7] Load model + scaler + baseline yang sudah dilatih...")
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

    print("[6/7] Predict anomaly_score & anomaly_label buat SEMUA baris histori...")
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
    result["anomaly_label"] = result["anomaly_label"].replace({0: "Normal", 1: "Anomaly"})

    print("[7/7] Upsert SEMUA baris ke tabel anomaly_predictions...")
    predictions_db.init_schema()
    n_saved = predictions_db.save_predictions(result)

    n_anomaly = (result["anomaly_label"] == "Anomaly").sum()
    print(f"[selesai] {n_saved} baris di-backfill ke anomaly_predictions, "
          f"{n_anomaly} di antaranya ditandai anomali ({n_anomaly / len(result):.2%}).")
    print("          Sekarang generate_report.py sudah bisa dipakai buat periode manapun "
          "yang ada di histori ini.")


if __name__ == "__main__":
    main()
