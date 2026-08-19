import staging
import mysql_db
from feature_engineering import compute_hourly_features


def backfill():
    print("=== Backfill histori lama ke MySQL ===")

    mysql_db.init_schema()
    print("Skema MySQL siap.")

    # --- raw_data: baca SEMUA staging/detail_*.csv, truncate, insert ulang ---
    all_detail_df = staging.load_all_detail_csv()
    print(f"Ditemukan {len(all_detail_df)} baris detail di seluruh staging/detail_*.csv.")

    if all_detail_df.empty:
        print("Tidak ada data detail untuk di-backfill.")
    else:
        conn = mysql_db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE raw_data;")
            conn.commit()
            print("Tabel raw_data dikosongkan (TRUNCATE) sebelum diisi ulang.")
        finally:
            conn.close()

        n_raw = mysql_db.load_raw_data(all_detail_df)
        print(f"[raw_data] {n_raw} baris di-insert.")

    # --- hourly_features: hitung ulang dari seluruh histori detail, lalu upsert ---
    if all_detail_df.empty:
        print("Lewati hourly_features (tidak ada data detail).")
    else:
        features_df = compute_hourly_features(all_detail_df)
        n_fitur = mysql_db.load_hourly_features(features_df)
        print(f"[hourly_features] {n_fitur} baris di-upsert.")

    print("=== Backfill selesai ===")


if __name__ == "__main__":
    backfill()
