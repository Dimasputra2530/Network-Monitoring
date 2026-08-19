"""
Transformasi pembersihan data sebelum masuk ke database bersih.
"""
import ipaddress
import pandas as pd


def anonymize_to_subnet(ip: str) -> str:
    """Samarkan IP jadi subnet /24 (3 oktet pertama, oktet terakhir dibuang).

    Contoh: 8.8.8.8 -> 8.8.8.0/24
    Kalau IP tidak valid (data kotor dari sumber), dikembalikan sebagai
    'invalid/24' supaya tetap kelihatan di data tapi tidak bikin ETL gagal.
    """
    try:
        octets = str(ip).strip().split(".")
        if len(octets) != 4:
            raise ValueError("bukan IPv4")
        # validasi tiap oktet
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
        return str(net)
    except Exception:
        return "invalid/24"


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()

    # --- received_at: perbaiki tipe & buang yang tidak valid ---
    out["received_at"] = pd.to_datetime(out["received_at"], errors="coerce")
    before = len(out)
    out = out.dropna(subset=["received_at"])
    dropped = before - len(out)
    if dropped:
        print(f"[clean] {dropped} baris dibuang karena received_at tidak valid")

    # --- dstip -> subnet /24 (anonimisasi) ---
    out["dstip_subnet"] = out["dstip"].apply(anonymize_to_subnet)

    # --- datasize: pastikan numerik, negatif/NaN jadi 0 ---
    out["datasize"] = pd.to_numeric(out["datasize"], errors="coerce").fillna(0).clip(lower=0).astype(int)

    # --- dstport: pastikan numerik (boleh kosong) ---
    out["dstport"] = pd.to_numeric(out["dstport"], errors="coerce")

    # id sumber disimpan sebentar sebagai kolom terpisah untuk watermark,
    # tapi TIDAK ikut ke kolom-kolom final yang di-staging/di-load.
    # Kolom `host` sengaja TIDAK disertakan sama sekali.
    watermark_col = out["id"]
    out = out[["received_at", "srcip", "dstip_subnet", "dstport", "proto", "datasize"]]
    out["__source_id_watermark__"] = watermark_col  # dipakai run_etl.py, dibuang sebelum staging

    return out
