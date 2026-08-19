"""
Training pipeline Isolation Forest.

Alurnya:
  1. Load hasil ETL (tabel `hourly_features` di MySQL) -- utils.py
  2. Hitung baseline perilaku per host/IP (median & MAD) -- baseline.py
  3. Pilih kolom fitur (fitur deviasi dari baseline) -- feature_selector.py
  4. Preprocess (missing value + scaling) -- preprocessing.py
  5. Latih Isolation Forest -- model.py
  6. Simpan model + scaler + baseline ke models/, ringkasan ke output/evaluation.json

PENTING soal "evaluasi": Isolation Forest itu UNSUPERVISED -- tidak ada
label anomali "asli" buat dibandingkan (tidak ada accuracy/precision/
recall beneran). evaluation.json isinya statistik DESKRIPTIF (distribusi
skor, jumlah baris yang kena label anomali, dsb) buat sanity-check
model, BUKAN metrik akurasi.

Jalankan:
    cd anomaly_detection
    python train.py
"""
import json
from datetime import datetime

import baseline
import config
import feature_selector
import model as model_module
import preprocessing
import utils


def main():
    print(f"[{datetime.now().isoformat()}] === Training Isolation Forest ===")

    print("[1/6] Load hasil ETL dari MySQL (tabel hourly_features)...")
    df = utils.load_etl_output()
    if df.empty:
        print("Tabel hourly_features kosong -- tidak ada data buat training. Jalankan ETL dulu.")
        return
    print(f"      {len(df)} baris dimuat (tanggal {df['tanggal'].min()} s.d. {df['tanggal'].max()}).")

    print("[2/6] Hitung baseline perilaku per host/IP (median & MAD)...")
    host_baseline = baseline.compute_host_baseline(df)
    df = baseline.apply_host_baseline(df, host_baseline)
    n_established = int((df["baseline_confidence"] == "established").sum())
    print(f"      {len(host_baseline['per_host'])} host punya baseline sendiri "
          f"({n_established}/{len(df)} baris histori cukup, sisanya pakai baseline global).")

    print("[3/6] Pilih kolom fitur (fitur deviasi dari baseline, bukan angka mentah)...")
    X_raw = feature_selector.select_features(df)
    print(f"      Fitur dipakai: {list(X_raw.columns)}")

    print("[4/6] Preprocessing (missing value + scaling)...")
    X_clean = preprocessing.handle_missing_values(X_raw)
    scaler, X_scaled = preprocessing.fit_scaler(X_clean)

    print("[5/6] Latih Isolation Forest...")
    model = model_module.train_model(X_scaled)

    print("[6/6] Simpan model + scaler + baseline...")
    model_module.save_model(model, config.MODEL_PATH)
    preprocessing.save_scaler(scaler, config.SCALER_PATH)
    baseline.save_baseline(host_baseline, config.BASELINE_PATH)
    print(f"      Model    -> {config.MODEL_PATH}")
    print(f"      Scaler   -> {config.SCALER_PATH}")
    print(f"      Baseline -> {config.BASELINE_PATH}")

    # --- Ringkasan training (bukan metrik akurasi, lihat docstring atas) ---
    scores = model_module.anomaly_scores(model, X_scaled)
    labels = model_module.predict_labels(model, X_scaled)
    evaluation = {
        "trained_at": datetime.now().isoformat(),
        "n_rows_trained": len(df),
        "tanggal_range": [str(df["tanggal"].min()), str(df["tanggal"].max())],
        "features_used": list(X_raw.columns),
        "isolation_forest_params": config.ISOLATION_FOREST_PARAMS,
        "anomaly_rate_on_training_data": round(float(labels.mean()), 4),
        "anomaly_score_stats": {
            "min": round(float(scores.min()), 6),
            "max": round(float(scores.max()), 6),
            "mean": round(float(scores.mean()), 6),
            "std": round(float(scores.std()), 6),
        },
    }
    with open(config.EVALUATION_PATH, "w") as f:
        json.dump(evaluation, f, indent=2)
    print(f"      Ringkasan training -> {config.EVALUATION_PATH}")

    print(f"[selesai] anomaly_rate di data training: {evaluation['anomaly_rate_on_training_data']:.2%}")


if __name__ == "__main__":
    main()
