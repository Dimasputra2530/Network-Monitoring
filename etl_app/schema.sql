-- ============================================================
-- Skema MySQL: 2 tabel -- raw_data (detail mentah hasil cleaning)
-- dan hourly_features (hasil feature engineering per jam/per host).
--
-- Jalankan manual sekali di awal (via mysql client / MySQL Workbench)
-- atau lewat mysql_db.init_schema() di modul mysql_db.py.
-- ============================================================

CREATE DATABASE IF NOT EXISTS network_clean
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE network_clean;

-- ------------------------------------------------------------
-- Tabel 1: raw_data
-- Data mentah per-baris koneksi, hasil clean.py (dstip sudah
-- disamarkan jadi subnet /24, srcip apa adanya).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_data (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    received_at     DATETIME(6)     NOT NULL,
    srcip           VARCHAR(45)     NOT NULL,
    dstip_subnet    VARCHAR(50)     NOT NULL,
    dstport         INT             NOT NULL,
    proto           VARCHAR(10)     NOT NULL,
    datasize        INT             NOT NULL,
    inserted_at     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_raw_srcip_received (srcip, received_at),
    INDEX idx_raw_received_at (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ------------------------------------------------------------
-- Tabel 2: hourly_features
-- Hasil feature_engineering.py: 1 baris = 1 host, 1 jam.
-- UNIQUE KEY (tanggal, jam, srcip) supaya aman di-upsert kalau
-- siklus ETL jalan ulang untuk jam yang sama (tidak dobel).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hourly_features (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    tanggal                 DATE            NOT NULL,
    jam                     VARCHAR(5)      NOT NULL,   -- format "HH:00"
    srcip                   VARCHAR(45)     NOT NULL,

    jumlah_koneksi          INT             NOT NULL,
    jumlah_tujuan_unik      INT             NOT NULL,
    jumlah_port_unik        INT             NOT NULL,
    tcp                     INT             NOT NULL,
    udp                     INT             NOT NULL,
    total_data              BIGINT          NOT NULL,
    average_datasize        DECIMAL(10, 2)  NOT NULL,

    dns                     INT             NOT NULL,
    web                     INT             NOT NULL,
    app                     INT             NOT NULL,
    other                   INT             NOT NULL,

    dns_ratio               DECIMAL(6, 4)   NOT NULL,
    web_ratio               DECIMAL(6, 4)   NOT NULL,
    app_ratio               DECIMAL(6, 4)   NOT NULL,
    other_ratio             DECIMAL(6, 4)   NOT NULL,
    destination_diversity   DECIMAL(6, 4)   NOT NULL,

    inserted_at             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                             ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_hourly_features_tanggal_jam_srcip (tanggal, jam, srcip),
    INDEX idx_hourly_features_srcip (srcip),
    INDEX idx_hourly_features_tanggal (tanggal)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
