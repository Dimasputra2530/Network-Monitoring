import pandas as pd

from port_service_map import PORT_SERVICE_MAP
# Port-port DNS.
DNS_PORTS = {53, 5353, 853}

# Port-port layanan web umum.
WEB_PORTS = {80, 443, 8080, 8443, 8000, 8008, 8888}

APP_PORTS = set(PORT_SERVICE_MAP.keys()) - DNS_PORTS - WEB_PORTS

# Nama kolom hasil kategorisasi port, urutannya dipakai konsisten di
# CSV/DB. Hanya 4 kategori, semua huruf kecil.
PORT_GROUP_COLUMNS = ["dns", "web", "app", "other"]

# Kolom rasio (dns_ratio, web_ratio, app_ratio, other_ratio), satu per
# kategori port di atas, urutannya mengikuti PORT_GROUP_COLUMNS.
PORT_GROUP_RATIO_COLUMNS = [f"{col}_ratio" for col in PORT_GROUP_COLUMNS]


def classify_port(port) -> str:
    """Petakan satu nilai dstport ke salah satu dari 4 kategori:
    'dns', 'web', 'app', atau 'other'.

    'other' dipakai untuk: port kosong/NaN, port UNKNOWN yang tidak
    ada di mapping, dan port random/ephemeral yang tidak dikenal."""
    if pd.isna(port):
        return "other"
    try:
        p = int(port)
    except (ValueError, TypeError):
        return "other"

    if p in DNS_PORTS:
        return "dns"
    if p in WEB_PORTS:
        return "web"
    if p in APP_PORTS:
        return "app"
    return "other"


def compute_hourly_features(df_cleaned: pd.DataFrame) -> pd.DataFrame:
    base_columns = ["tanggal", "jam", "srcip", "jumlah_koneksi",
                     "jumlah_tujuan_unik", "jumlah_port_unik", "tcp", "udp",
                     "total_data", "average_datasize"]

    if df_cleaned.empty:
        return pd.DataFrame(
            columns=base_columns + PORT_GROUP_COLUMNS + PORT_GROUP_RATIO_COLUMNS
            + ["destination_diversity"]
        )

    df = df_cleaned.copy()
    df["tanggal"] = df["received_at"].dt.date
    df["jam"] = df["received_at"].dt.hour
    df["port_group"] = df["dstport"].apply(classify_port)

    grouped = df.groupby(["tanggal", "jam", "srcip"]).agg(
        jumlah_koneksi=("received_at", "count"),
        jumlah_tujuan_unik=("dstip_subnet", "nunique"),
        jumlah_port_unik=("dstport", "nunique"),
        tcp=("proto", lambda s: (s == "TCP").sum()),
        udp=("proto", lambda s: (s == "UDP").sum()),
        total_data=("datasize", "sum"),
    ).reset_index()

    # average_datasize = rata-rata ukuran data per koneksi (total_data /
    # jumlah_koneksi) -- fitur tambahan yang masih relevan sesuai arahan
    # mentor, aman dihitung karena jumlah_koneksi tidak pernah 0 di sini
    # (tiap baris grup pasti punya minimal 1 koneksi).
    grouped["average_datasize"] = (grouped["total_data"] / grouped["jumlah_koneksi"]).round(2)

    # Hitung jumlah koneksi per kategori port, dipivot jadi kolom terpisah
    # (satu kolom per kategori) supaya gampang langsung dipakai sebagai fitur ML.
    port_group_counts = (
        df.groupby(["tanggal", "jam", "srcip", "port_group"])
        .size()
        .unstack(fill_value=0)
    )
    # Pastikan semua kolom kategori selalu ada, walau di batch ini kategori
    # tsb tidak muncul sama sekali (kalau tidak, kolomnya akan hilang dan
    # bikin skema CSV antar-batch tidak konsisten).
    for col in PORT_GROUP_COLUMNS:
        if col not in port_group_counts.columns:
            port_group_counts[col] = 0
    port_group_counts = port_group_counts[PORT_GROUP_COLUMNS].reset_index()

    grouped = grouped.merge(port_group_counts, on=["tanggal", "jam", "srcip"], how="left")
    grouped[PORT_GROUP_COLUMNS] = grouped[PORT_GROUP_COLUMNS].fillna(0).astype(int)

    # Fitur rasio (dns_ratio, web_ratio, app_ratio, other_ratio) = jumlah
    # koneksi per kategori port / jumlah_koneksi. Tujuannya supaya analisis
    # fokus ke POLA PERILAKU host (proporsi tiap kategori) dibanding cuma
    # volume trafik mentah. Aman dibagi jumlah_koneksi karena tiap baris
    # grup pasti punya minimal 1 koneksi (sama seperti average_datasize).
    for col, ratio_col in zip(PORT_GROUP_COLUMNS, PORT_GROUP_RATIO_COLUMNS):
        grouped[ratio_col] = (grouped[col] / grouped["jumlah_koneksi"]).round(4)

    # destination_diversity = jumlah_tujuan_unik / jumlah_koneksi -- mengukur
    # tingkat keragaman tujuan akses per host per jam. Nilai mendekati 1
    # berarti hampir tiap koneksi mengarah ke tujuan yang berbeda (host
    # "menyebar", ciri umum scanning/anomali); mendekati 0 berarti koneksi
    # berulang-ulang ke tujuan yang itu-itu saja (perilaku normal umumnya).
    grouped["destination_diversity"] = (
        grouped["jumlah_tujuan_unik"] / grouped["jumlah_koneksi"]
    ).round(4)

    # Format kolom jam jadi "HH:00" (mis. 15 -> "15:00") untuk output akhir.
    # Pengelompokan di atas tetap pakai jam sebagai angka (0-23) supaya
    # urutan groupby benar; formatnya baru diubah di sini, paling akhir.
    grouped["jam"] = grouped["jam"].apply(lambda h: f"{int(h):02d}:00")

    return grouped
