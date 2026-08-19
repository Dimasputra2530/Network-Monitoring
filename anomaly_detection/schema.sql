-- ------------------------------------------------------------
-- Schema khusus anomaly_detection/ -- TERPISAH dari etl_app/schema.sql,
-- konsisten sama prinsip pemisahan modul yang sudah dipakai di project ini.
-- Ditulis ke database yang SAMA (`network_clean`) lewat koneksi yang sama
-- (reuse etl_app/mysql_db.py via utils.py), cuma tabelnya beda tanggung jawab.
-- ------------------------------------------------------------

-- Tabel: anomaly_predictions
-- Histori hasil predict.py -- SEBELUMNYA cuma ditulis ke anomaly_results.csv
-- (yang ditimpa total tiap kali predict.py dijalankan). Tabel ini upsert
-- (UNIQUE KEY tanggal+jam+srcip), sama seperti hourly_features -- jadi
-- hasil prediksi TERAKUMULASI dari waktu ke waktu, bisa dipakai buat
-- laporan bulanan/tahunan (reports.py), bukan cuma snapshot terakhir.
CREATE TABLE IF NOT EXISTS anomaly_predictions (
    tanggal DATE NOT NULL,
    jam VARCHAR(5) NOT NULL,
    srcip VARCHAR(45) NOT NULL,

    jumlah_koneksi INT NOT NULL,
    jumlah_tujuan_unik INT NOT NULL,
    jumlah_port_unik INT NOT NULL,

    dns_ratio DECIMAL(6,4) NOT NULL,
    web_ratio DECIMAL(6,4) NOT NULL,
    app_ratio DECIMAL(6,4) NOT NULL,
    other_ratio DECIMAL(6,4) NOT NULL,
    destination_diversity DECIMAL(6,4) NOT NULL,

    -- Volume outbound MENTAH (bytes) + rata-rata ukuran paket/koneksi --
    -- dipakai buat menilai Data Exfiltration dari VOLUME beneran, bukan
    -- cuma dari jumlah koneksi (lihat api/classify.py).
    total_data BIGINT NOT NULL DEFAULT 0,
    average_datasize DECIMAL(10,2) NOT NULL DEFAULT 0,

    -- Deviasi robust (median/MAD) dari BASELINE HOST ITU SENDIRI --
    -- "seberapa jauh nilai jam ini dari kebiasaan normal host ini",
    -- dihitung baseline.py, dipakai baik sebagai fitur Isolation Forest
    -- maupun buat klasifikasi tipe/status di api/classify.py.
    jumlah_koneksi_deviation DECIMAL(12,4) NOT NULL DEFAULT 0,
    jumlah_tujuan_unik_deviation DECIMAL(12,4) NOT NULL DEFAULT 0,
    jumlah_port_unik_deviation DECIMAL(12,4) NOT NULL DEFAULT 0,
    total_data_deviation DECIMAL(12,4) NOT NULL DEFAULT 0,

    -- "established" = host ini punya histori CUKUP buat baseline-nya
    -- dipercaya, "new_host" = histori masih sedikit, pakai baseline
    -- global sementara -- host baru TETAP dipantau, bukan diabaikan.
    baseline_confidence VARCHAR(20) NOT NULL DEFAULT 'new_host',

    anomaly_score DECIMAL(10,6) NOT NULL,
    anomaly_label VARCHAR(10) NOT NULL,  -- "Normal" / "Anomaly"

    predicted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_anomaly_predictions_tanggal_jam_srcip (tanggal, jam, srcip),
    INDEX idx_anomaly_predictions_tanggal (tanggal),
    INDEX idx_anomaly_predictions_label (anomaly_label)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
