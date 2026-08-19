"""
evaluate_synthetic.py -- Uji Isolation Forest pakai data ANOMALI BUATAN (synthetic
anomaly injection), bukan data ETL asli.

Kenapa perlu ini: Isolation Forest itu unsupervised, jadi TIDAK ADA cara resmi buat
menghitung accuracy/precision/recall dari data asli (tidak ada label anomali yang
sudah dikonfirmasi manusia). Script ini membuat pola-pola trafik yang SUDAH KITA
TAHU seharusnya anomali (port scanning, DDoS, DNS tunneling, C2 beaconing), lalu
cek apakah model berhasil menandainya -- hasilnya jadi semacam "recall terhadap
anomali sintetis", bukti konkret buat sidang bahwa model memang bisa menangkap
pola-pola yang secara umum dikenal berbahaya.

CATATAN PENTING berhasil deteksi anomali sintetis
TIDAK BERARTI model 100% akurat di dunia nyata -- pola-pola ini dibuat manual
berdasarkan pemahaman umum soal serangan jaringan, bukan dari insiden yang
benar-benar terjadi & terverifikasi. Anggap ini "sanity check" tambahan yang
melengkapi (bukan menggantikan) validasi manual bareng tim IT.

Butuh model & scaler yang sudah dilatih (train.py) -- script ini TIDAK training
ulang, TIDAK butuh koneksi database (baris sintetis dibuat langsung di Python).

Jalankan:
    cd anomaly_detection
    python evaluate_synthetic.py
"""
import numpy as np
import pandas as pd

import baseline
import config
import feature_selector
import model as model_module
import preprocessing


def generate_synthetic_anomalies(n_per_type: int = 10, random_state: int = 42) -> pd.DataFrame:
    """Bikin beberapa pola trafik yang SUDAH DIKETAHUI mencurigakan (bukan hasil
    ETL asli). Tiap pola dibuat beberapa variasi (n_per_type) dengan sedikit noise
    acak (+-30%) supaya hasilnya lebih bisa dipercaya -- bukan cuma kebetulan 1
    baris yang pas ke-detect, tapi rata-rata dari beberapa variasi pola yang sama.

    Baris sintetis ini TIDAK datang dari host manapun di baseline (srcip diisi
    placeholder unik supaya baseline.apply_host_baseline() otomatis pakai
    baseline GLOBAL sebagai fallback -- konsisten dengan cara host baru/belum
    dikenal diperlakukan di predict.py, BUKAN perlakuan khusus).
    """
    rng = np.random.default_rng(random_state)
    rows = []

    def add_variants(attack_type, base_koneksi, base_tujuan, base_port, ratios, base_total_data):
        dns_r, web_r, app_r, other_r = ratios
        for i in range(n_per_type):
            koneksi = max(1, int(round(base_koneksi * rng.uniform(0.7, 1.3))))
            tujuan = max(1, min(koneksi, int(round(base_tujuan * rng.uniform(0.7, 1.3)))))
            port = max(1, min(koneksi, int(round(base_port * rng.uniform(0.7, 1.3)))))
            total_data = max(1, int(round(base_total_data * rng.uniform(0.7, 1.3))))
            rows.append({
                "attack_type": attack_type,
                "srcip": f"synthetic-{attack_type}-{i}",  # placeholder unik, bukan host asli
                "jumlah_koneksi": koneksi,
                "jumlah_tujuan_unik": tujuan,
                "jumlah_port_unik": port,
                "total_data": total_data,
                "dns_ratio": dns_r,
                "web_ratio": web_r,
                "app_ratio": app_r,
                "other_ratio": other_r,
                "destination_diversity": round(tujuan / koneksi, 4),
            })

    # Horizontal port scan -- 1 port yang sama, disebar ke ratusan host berbeda
    add_variants("Horizontal port scan", 1000, 980, 1, (0.0, 0.0, 0.0, 1.0), base_total_data=60_000)
    # Vertical port scan -- 1 host yang sama, ratusan port dicoba satu-satu
    add_variants("Vertical port scan", 1000, 1, 950, (0.0, 0.0, 0.0, 1.0), base_total_data=60_000)
    # DDoS outbound flood -- ribuan koneksi ke 1 target, 1 port (mis. HTTP flood)
    add_variants("DDoS outbound flood", 8000, 1, 1, (0.0, 1.0, 0.0, 0.0), base_total_data=400_000)
    # DNS tunneling -- ribuan query DNS ke 1 resolver (data di-encode di nama domain)
    add_variants("DNS tunneling", 2000, 1, 1, (1.0, 0.0, 0.0, 0.0), base_total_data=150_000)
    # Low-volume C2 beaconing -- callback kecil & rutin ke 1 server command-and-control
    add_variants("Low-volume C2 beaconing", 12, 1, 1, (0.0, 0.0, 1.0, 0.0), base_total_data=5_000)
    # Data exfiltration -- volume BESAR ke sedikit tujuan, koneksi tidak perlu banyak
    add_variants("Data exfiltration (volume tinggi)", 40, 2, 3, (0.0, 0.1, 0.9, 0.0), base_total_data=800_000_000)

    return pd.DataFrame(rows)


def main():
    print("=== Evaluasi Synthetic Anomaly Injection ===")

    if not config.MODEL_PATH.exists() or not config.SCALER_PATH.exists() or not config.BASELINE_PATH.exists():
        print(f"Model/scaler/baseline belum ada di {config.MODEL_DIR}. Jalankan train.py dulu.")
        return

    print("[1/4] Load model + scaler + baseline...")
    model = model_module.load_model(config.MODEL_PATH)
    scaler = preprocessing.load_scaler(config.SCALER_PATH)
    host_baseline = baseline.load_baseline(config.BASELINE_PATH)

    print("[2/4] Bikin data anomali sintetis...")
    synthetic = generate_synthetic_anomalies(n_per_type=10)
    print(f"      {len(synthetic)} baris sintetis dibuat, "
          f"{synthetic['attack_type'].nunique()} jenis pola serangan.")

    print("[3/4] Terapkan baseline (fallback global, host sintetis belum dikenal) "
          "+ preprocessing + prediksi (pakai model & scaler yang SUDAH ADA, bukan fit baru)...")
    synthetic = baseline.apply_host_baseline(synthetic, host_baseline)
    X_raw = feature_selector.select_features(synthetic)
    X_clean = preprocessing.handle_missing_values(X_raw)
    X_scaled = preprocessing.transform_with_scaler(scaler, X_clean)

    scores = model_module.anomaly_scores(model, X_scaled)
    labels = model_module.predict_labels(model, X_scaled)

    result = synthetic.copy()
    result["anomaly_score"] = scores.values
    result["anomaly_label"] = labels.map({0: "Normal", 1: "Anomaly"}).values

    print("[4/4] Simpan hasil...")
    out_path = config.OUTPUT_DIR / "synthetic_anomaly_evaluation.csv"
    result.to_csv(out_path, index=False)

    print()
    print("=== Detection rate per jenis pola ===")
    summary = (
        result.groupby("attack_type")["anomaly_label"]
        .apply(lambda s: (s == "Anomaly").mean())
        .sort_values(ascending=False)
    )
    for attack_type, rate in summary.items():
        print(f"  {attack_type:<28} {rate:.0%} terdeteksi")

    overall_rate = (result["anomaly_label"] == "Anomaly").mean()
    n_detected = int((result["anomaly_label"] == "Anomaly").sum())
    print()
    print(f"[selesai] Detection rate keseluruhan: {overall_rate:.1%} "
          f"({n_detected}/{len(result)} baris sintetis).")
    print(f"          Hasil detail -> {out_path}")


if __name__ == "__main__":
    main()
