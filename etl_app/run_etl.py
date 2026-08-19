"""
ETL App menarik data dari server produksi (PostgreSQL, read-only),
bersihkan, lakukan Feature Engineering, lalu simpan hasilnya ke MySQL
(2 tabel: raw_data + hourly_features) -- selain tetap menulis CSV di staging/
dan data/ sebagai staging area / audit trail.

Pipeline: PostgreSQL -> Extract -> Cleaning -> staging (CSV, validasi)
-> MySQL.raw_data, lalu Feature Engineering -> staging (CSV, validasi)
-> MySQL.hourly_features + data/hourly_features.csv.
"""
from datetime import datetime, timedelta
import time

import clean_db
import mysql_db
import source_db
import staging
from clean import clean_dataframe
from config import ETL_INTERVAL_SECONDS, ETL_FIXED_TIME
from feature_engineering import compute_hourly_features
from staging import write_staging_csv, validate_staging_csv


#otomatis di jam 7.30 pengambilan data dari server produksi, kalau mau diubah bisa di config.py
def seconds_until_next(hh_mm: str) -> float:
    """Hitung berapa detik lagi sampai jam HH:MM berikutnya (hari ini kalau
    belum lewat, besok kalau sudah lewat) -- dipakai mode ETL_FIXED_TIME."""
    now = datetime.now()
    hh, mm = map(int, hh_mm.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_once():
    print(f"\n[{datetime.now().isoformat()}] === Mulai siklus ETL ===")

    last_source_id = clean_db.get_last_source_id()
    raw_df = source_db.fetch_new_rows(last_source_id)

    if raw_df.empty:
        print("Tidak ada baris baru dalam jendela waktu tarik. Siklus selesai.")
        return

    print(f"Menarik {len(raw_df)} baris baru dari produksi (id > {last_source_id}).")

    # --- Data Cleaning ---
    cleaned = clean_dataframe(raw_df)
    if cleaned.empty:
        print("Semua baris dibuang saat pembersihan (data tidak valid). Siklus selesai.")
        return

    new_watermark = int(cleaned["__source_id_watermark__"].max())
    cleaned_for_staging = cleaned.drop(columns=["__source_id_watermark__"])

    # --- Staging + validasi: DETAIL (baris mentah yang sudah bersih) ---
    detail_csv_path, detail_batch_id = write_staging_csv(cleaned_for_staging, kind="detail")
    print(f"[detail] Ditulis ke staging: {detail_csv_path}")

    ok, issues = validate_staging_csv(detail_csv_path, kind="detail")
    if not ok:
        print(f"[GAGAL VALIDASI] Batch detail {detail_batch_id} dilewati. Masalah: {issues}")
        return  # sengaja TIDAK update watermark, supaya batch ini dicoba ulang setelah diperbaiki

    print(f"[detail] {len(cleaned_for_staging)} baris detail siap (staging, lolos validasi).")

    # --- MySQL: insert baris detail ke tabel raw_data ---
    try:
        n_raw = mysql_db.load_raw_data(cleaned_for_staging)
        print(f"[detail] {n_raw} baris di-insert ke MySQL.raw_data.")
    except Exception as e:
        print(f"[ERROR] Gagal insert ke MySQL.raw_data: {e}")
        print("        (CSV staging tetap tersimpan, jadi tidak ada data yang hilang -- "
              "bisa di-retry manual dari staging/ setelah masalah MySQL diperbaiki.)")

    # --- Feature Engineering: baca SEMUA detail_*.csv di staging (histori
    # lama + batch baru ini), bukan cuma batch baru saja -- supaya
    # data/hourly_features.csv selalu jadi rekap LENGKAP dari seluruh data
    # yang pernah masuk ke staging. ---
    all_detail_df = staging.load_all_detail_csv()
    print(f"[features] Menghitung fitur dari {len(all_detail_df)} baris detail total (histori lama + baru).")
    features_df = compute_hourly_features(all_detail_df)

    # Pecah hasilnya PER TANGGAL, semua file masuk ke staging/
    # (staging/features_<tanggal>.csv) -- bukan 1 file gabungan lagi.
    written_paths = staging.write_features_by_date(features_df)

    all_valid = True
    for path in written_paths:
        ok_f, issues_f = validate_staging_csv(path, kind="features")
        if not ok_f:
            all_valid = False
            print(f"[GAGAL VALIDASI] {path}. Masalah: {issues_f}")

    if not all_valid:
        print("[features] Sebagian file per-tanggal gagal validasi -- data/ dan MySQL.hourly_features TIDAK di-update, perlu ditinjau manual.")
    else:
        print(f"[features] {len(written_paths)} file per-tanggal ditulis ke staging/, semua lolos validasi.")

        data_csv_path = clean_db.save_features_to_data(features_df)
        print(f"[features] Disalin ke data/ (hasil final): {data_csv_path}")

        # --- MySQL: upsert fitur jam ini ke tabel hourly_features ---
        try:
            n_fitur = mysql_db.load_hourly_features(features_df)
            print(f"[features] {n_fitur} baris di-upsert ke MySQL.hourly_features.")
        except Exception as e:
            print(f"[ERROR] Gagal upsert ke MySQL.hourly_features: {e}")
            print("        (CSV data/hourly_features.csv tetap ter-update, jadi tidak ada "
                  "data yang hilang -- bisa di-retry manual setelah masalah MySQL diperbaiki.)")

    # --- Simpan watermark ---
    clean_db.set_etl_state(new_watermark, len(cleaned_for_staging))
    print(f"Watermark diperbarui ke id sumber {new_watermark}. === Siklus selesai ===")


def main():
    print("Menyiapkan skema MySQL (CREATE DATABASE/TABLE IF NOT EXISTS)...")
    try:
        mysql_db.init_schema()
        print("Skema MySQL siap (database network_clean, tabel raw_data + hourly_features).")
    except Exception as e:
        print(f"[ERROR] Gagal menyiapkan skema MySQL: {e}")
        print("        Cek koneksi/kredensial CLEAN_DB_* di .env. ETL tetap lanjut "
              "jalan (CSV di staging/data tetap ditulis), tapi insert ke MySQL akan "
              "gagal terus sampai ini diperbaiki.")

    if ETL_FIXED_TIME:
        print(f"Mode JAM TETAP aktif: ETL akan jalan tiap hari jam {ETL_FIXED_TIME}.")
        print("Menjalankan catch-up run sekali dulu sekarang (supaya nggak nunggu sampai jadwal berikutnya)...")
        try:
            run_once()
        except Exception as e:
            print(f"[ERROR] Catch-up run gagal: {e}")
        while True:
            wait_seconds = seconds_until_next(ETL_FIXED_TIME)
            next_run = datetime.now() + timedelta(seconds=wait_seconds)
            print(f"Menunggu sampai {next_run.strftime('%Y-%m-%d %H:%M')} ({wait_seconds/3600:.1f} jam lagi)...")
            time.sleep(wait_seconds)
            try:
                run_once()
            except Exception as e:
                print(f"[ERROR] Siklus ETL gagal: {e}")
            # sengaja TIDAK time.sleep(interval) di sini -- iterasi berikutnya
            # otomatis hitung ulang "besok jam segini" lewat seconds_until_next()
    else:
        print(f"Mode INTERVAL aktif: ETL akan jalan tiap {ETL_INTERVAL_SECONDS} detik sejak sekarang.")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[ERROR] Siklus ETL gagal: {e}")
            time.sleep(ETL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
