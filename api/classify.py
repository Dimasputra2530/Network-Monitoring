"""
classify.py -- klasifikasi STATUS & TIPE anomali dari kolom fitur yang
sudah ada di tabel `anomaly_predictions` (dibuat oleh anomaly_detection/).

Isolation Forest (anomaly_detection/) tugasnya CUMA SATU: menandai baris
"tidak biasa" lewat anomaly_label -- fungsi di file ini HANYA dipanggil
untuk baris yang SUDAH ditandai 'Anomaly' oleh model itu. Heuristik di
bawah ini TIDAK menyentuh / tidak dipakai oleh model ML -- murni buat
kebutuhan tampilan dashboard, menjawab pertanyaan LANJUTAN: baris yang
sudah ditandai "tidak biasa" ini, seberapa yakin itu benar-benar pola
berbahaya?

STATUS (3 tingkat):
  - "Normal"           : tidak biasa dibanding SELURUH populasi host,
                          tapi MASIH SESUAI kebiasaan host ITU SENDIRI
                          (baca: kemungkinan besar bukan ancaman -- mis.
                          host yang memang rutin trafiknya tinggi). TETAP
                          ditampilkan/dipantau, BUKAN di-whitelist/
                          disembunyikan.
  - "Suspicious"        : ada penyimpangan cukup berarti dari kebiasaan
                          host ini sendiri, tapi belum cukup kuat/spesifik
                          buat dipastikan jenis pola serangannya.
  - "Confirmed Pattern" : indikator pola serangan spesifik (Port Scan /
                          Data Exfiltration) terpenuhi dengan kuat --
                          gabungan ambang batas ABSOLUT + deviasi dari
                          baseline host ITU SENDIRI (bukan cuma "jumlah
                          port/koneksi/tujuan tinggi").

TIPE -- label lebih spesifik buat ditampilkan (Port Scan, Data
Exfiltration, Unusual Traffic, dst).
"""
import config


def _deviation(row: dict, column: str) -> float:
    """Ambil kolom "<column>_deviation" dari row, default 0 kalau kolom
    belum ada (mis. data lama sebelum baseline.py ditambahkan) --
    supaya endpoint tetap jalan, bukan error, walau baseline belum
    pernah di-backfill ulang buat baris itu."""
    value = row.get(f"{column}_deviation")
    return float(value) if value is not None else 0.0


def classify_type(row: dict) -> tuple[str, str, str]:
    """Return (status, tipe, deskripsi). status: salah satu dari
    'Normal', 'Suspicious', 'Confirmed Pattern' -- lihat docstring atas."""
    jk = row["jumlah_koneksi"]
    tu = row["jumlah_tujuan_unik"]
    pu = row["jumlah_port_unik"]
    dd = row["destination_diversity"]
    other_r = row.get("other_ratio", 0) or 0
    total_mb = float(row.get("total_data", 0) or 0) / 1e6

    dev_conn = _deviation(row, "jumlah_koneksi")
    dev_dest = _deviation(row, "jumlah_tujuan_unik")
    dev_port = _deviation(row, "jumlah_port_unik")
    dev_vol = _deviation(row, "total_data")
    max_dev = max(dev_conn, dev_dest, dev_port, dev_vol)

    conn_per_port = (jk / pu) if pu else float(jk)

    # --- Confirmed Pattern: Port Scan ------------------------------
    # Bukan cuma "banyak port" -- harus: port unik absolut cukup banyak,
    # jauh menyimpang dari kebiasaan host ini sendiri, DAN pola breadth
    # (tiap port disentuh sedikit kali), baru dianggap scanning beneran.
    if (pu >= config.ANOMALY_PORT_SCAN_MIN_PORTS
            and dev_port >= config.ANOMALY_DEVIATION_CONFIRMED
            and conn_per_port <= config.ANOMALY_PORT_SCAN_MAX_CONN_PER_PORT):
        return "Confirmed Pattern", "Port Scan", (
            f"{pu} port berbeda dihubungi ke {tu} tujuan dalam 1 jam, rata-rata cuma "
            f"{conn_per_port:.1f} koneksi/port -- jauh di atas kebiasaan normal host ini "
            f"sendiri (pola breadth khas scanning, bukan sekadar trafik ramai)"
        )

    # --- Confirmed Pattern: Data Exfiltration -----------------------
    # Bukan cuma "banyak koneksi" -- harus: volume outbound absolut
    # signifikan (MB), jauh menyimpang dari kebiasaan VOLUME host ini
    # sendiri, DAN terkonsentrasi ke sedikit tujuan (bukan tersebar).
    if (total_mb >= config.ANOMALY_EXFIL_MIN_MB
            and dev_vol >= config.ANOMALY_DEVIATION_CONFIRMED
            and dd <= config.ANOMALY_EXFIL_MAX_DIVERSITY):
        return "Confirmed Pattern", "Data Exfiltration", (
            f"Volume outbound {total_mb:.1f} MB dalam 1 jam, jauh di atas kebiasaan "
            f"volume host ini sendiri, terkonsentrasi ke cuma {tu} tujuan"
        )

    # --- Suspicious ---------------------------------------------------
    # Ada penyimpangan berarti dari baseline host ini sendiri (atau
    # proporsi trafik other/app tidak wajar), tapi belum memenuhi pola
    # spesifik di atas -- perlu dipantau lanjut, belum dipastikan jenisnya.
    if max_dev >= config.ANOMALY_DEVIATION_SUSPICIOUS or other_r >= 0.4:
        alasan = []
        if dev_conn >= config.ANOMALY_DEVIATION_SUSPICIOUS:
            alasan.append(f"jumlah koneksi ({jk})")
        if dev_dest >= config.ANOMALY_DEVIATION_SUSPICIOUS:
            alasan.append(f"jumlah tujuan unik ({tu})")
        if dev_port >= config.ANOMALY_DEVIATION_SUSPICIOUS:
            alasan.append(f"jumlah port unik ({pu})")
        if dev_vol >= config.ANOMALY_DEVIATION_SUSPICIOUS:
            alasan.append(f"volume trafik ({total_mb:.1f} MB)")
        if not alasan:
            alasan.append("proporsi trafik other/app")
        tipe = (
            "Suspicious App Traffic"
            if other_r >= 0.4 and dev_conn < config.ANOMALY_DEVIATION_SUSPICIOUS
            else "Unusual Traffic"
        )
        return "Suspicious", tipe, (
            f"Menyimpang dari kebiasaan host ini sendiri pada: {', '.join(alasan)} -- "
            f"belum cukup kuat buat dipastikan jenis polanya, perlu dipantau lanjut"
        )

    # --- Normal ---------------------------------------------------------
    # Isolation Forest menandai baris ini "tidak biasa" dibanding SELURUH
    # populasi host, tapi dibanding kebiasaan host ITU SENDIRI ternyata
    # masih wajar (mis. host yang memang rutin trafiknya tinggi). TETAP
    # ditampilkan/dipantau di sini (bukan disembunyikan/di-whitelist) --
    # cuma statusnya jujur: kemungkinan besar bukan ancaman.
    catatan_baseline = (
        "" if row.get("baseline_confidence") == "established"
        else " (host baru / histori masih sedikit, baseline belum kuat -- tetap dipantau)"
    )
    return "Normal", "Normal Traffic", (
        f"Volume trafik host ini tinggi dibanding host lain, tapi masih sesuai "
        f"kebiasaan host ini sendiri{catatan_baseline}"
    )


def classify_severity(score: float) -> str:
    if score >= config.ANOMALY_SEVERITY_TINGGI:
        return "Tinggi"
    if score >= config.ANOMALY_SEVERITY_SEDANG:
        return "Sedang"
    return "Rendah"
