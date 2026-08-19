"""
main.py -- FastAPI yang menyajikan data langsung dari MySQL `network_clean`
(tabel `raw_data`, `hourly_features` dari etl_app/, & `anomaly_predictions`
dari anomaly_detection/) buat dashboard/.

Jalankan:
    cd api
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Endpoint-endpoint di sini query MySQL SETIAP kali dipanggil (tidak ada
caching) -- jadi datanya selalu up-to-date sesuai isi database saat itu,
tanpa perlu re-generate/re-deploy apapun tiap kali etl_app/run_etl.py
atau anomaly_detection/predict.py jalan.
"""
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
import db
import dns_lookup
import geoip_lookup
import port_lookup
import user_mapping
from classify import classify_type, classify_severity

app = FastAPI(title="Network Monitoring API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONTH_NAMES_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def _require_data():
    """Cek tabel inti sudah ada & tidak kosong -- kalau belum, kasih
    pesan error yang jelas (bukan 500 generik) supaya gampang di-debug
    kalau ETL belum pernah dijalankan sama sekali."""
    if not db.table_exists("hourly_features"):
        raise HTTPException(
            status_code=503,
            detail="Tabel hourly_features belum ada. Jalankan etl_app/run_etl.py "
                   "(atau backfill_mysql.py) dulu supaya database network_clean terisi.",
        )


@app.get("/api/health")
def health():
    try:
        conn = db.mysql_db.get_connection()
        conn.close()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Tidak bisa konek ke MySQL: {e}")


@app.get("/api/meta")
def meta():
    """Info umum: rentang tanggal data, daftar IP unik, daftar bulan yang ada datanya."""
    _require_data()
    rng = db.query_one("SELECT MIN(tanggal) AS start, MAX(tanggal) AS end FROM hourly_features")
    months_df = db.query_df(
        "SELECT DISTINCT DATE_FORMAT(tanggal, '%Y-%m') AS ym FROM hourly_features ORDER BY ym"
    )
    ips_df = db.query_df("SELECT DISTINCT srcip FROM hourly_features ORDER BY srcip")
    return {
        "range_start": str(rng["start"]) if rng else None,
        "range_end": str(rng["end"]) if rng else None,
        "available_months": months_df["ym"].tolist(),
        "unique_ips": ips_df["srcip"].tolist(),
    }


# ================= OVERVIEW =================
@app.get("/api/overview")
def overview():
    _require_data()
    last_row = db.query_one("SELECT MAX(tanggal) AS last_date FROM hourly_features")
    last_date = str(last_row["last_date"])

    today = db.query_df(
        "SELECT * FROM hourly_features WHERE tanggal = %s", (last_date,)
    )
    total_traffic_bytes = int(today["total_data"].sum())
    total_koneksi = int(today["jumlah_koneksi"].sum())
    unique_ip = int(today["srcip"].nunique())

    anomali_today = 0
    if db.table_exists("anomaly_predictions"):
        a_today = db.query_df(
            "SELECT COUNT(*) AS n FROM anomaly_predictions WHERE tanggal = %s AND anomaly_label = 'Anomaly'",
            (last_date,),
        )
        anomali_today = int(a_today["n"].iloc[0])

    # trend 7 hari terakhir yang ADA datanya
    trend_df = db.query_df(
        """SELECT tanggal, SUM(total_data) AS total_data
           FROM hourly_features GROUP BY tanggal ORDER BY tanggal DESC LIMIT 7"""
    )
    trend_df = trend_df.sort_values("tanggal")
    trend7 = [
        {"date": r.tanggal, "traffic_mb": round(r.total_data / 1e6, 3)}
        for r in trend_df.itertuples()
    ]

    proto_row = db.query_one("SELECT SUM(tcp) AS tcp, SUM(udp) AS udp FROM hourly_features")
    tcp, udp = int(proto_row["tcp"] or 0), int(proto_row["udp"] or 0)
    proto_total = max(tcp + udp, 1)
    protocol_split = {
        "TCP": round(tcp / proto_total * 100, 1),
        "UDP": round(udp / proto_total * 100, 1),
    }

    top_src_df = db.query_df(
        """SELECT srcip, SUM(total_data) AS total_data FROM hourly_features
           GROUP BY srcip ORDER BY total_data DESC LIMIT 5"""
    )
    grand_total = db.query_one("SELECT SUM(total_data) AS s FROM hourly_features")["s"] or 1
    top_src_ip = [
        {"ip": r.srcip, "traffic_gb": round(r.total_data / 1e9, 4),
         "pct": round(r.total_data / grand_total * 100, 2)}
        for r in top_src_df.itertuples()
    ]

    top_port_ip = []
    if db.table_exists("raw_data"):
        top_port_df = db.query_df(
            """SELECT dstport, SUM(datasize) AS total_size FROM raw_data
               GROUP BY dstport ORDER BY total_size DESC LIMIT 5"""
        )
        total_raw = db.query_one("SELECT SUM(datasize) AS s FROM raw_data")["s"] or 1
        top_port_ip = [
            {"port": int(r.dstport), "name": config.PORT_NAMES.get(int(r.dstport), "Other"),
             "traffic_mb": round(r.total_size / 1e6, 3),
             "pct": round(r.total_size / total_raw * 100, 2)}
            for r in top_port_df.itertuples()
        ]

    return {
        "last_date": last_date,
        "total_traffic_bytes": total_traffic_bytes,
        "total_koneksi": total_koneksi,
        "unique_ip": unique_ip,
        "anomali": anomali_today,
        "trend7": trend7,
        "protocol_split": protocol_split,
        "top_src_ip": top_src_ip,
        "top_dest_port": top_port_ip,
    }


# ================= DASHBOARD: GUEST / USER ACTIVITY =================
@app.get("/api/user-activity")
def user_activity(limit: int = Query(10, ge=1, le=50)):
    """Traffic per host + User/Guest (dari mapping data/), buat kartu
    'Guest / User Activity' di halaman Dashboard. Kalau file mapping
    belum ada, tetap tampil (IP + traffic) dengan user 'Unknown User' --
    TIDAK butuh data sensitif buat endpoint ini tetap jalan."""
    _require_data()
    top_df = db.query_df(
        """SELECT srcip, SUM(total_data) AS total_data FROM hourly_features
           GROUP BY srcip ORDER BY total_data DESC LIMIT %s""",
        (limit,),
    )
    mapping = user_mapping.lookup_many(top_df["srcip"].tolist()) if len(top_df) else {}
    items = [
        {
            "user": mapping.get(r.srcip, {}).get("user", user_mapping.UNKNOWN_USER),
            "device": mapping.get(r.srcip, {}).get("device", user_mapping.UNKNOWN_DEVICE),
            "srcip": r.srcip,
            "traffic_bytes": int(r.total_data),
        }
        for r in top_df.itertuples()
    ]
    return {"items": items, "user_mapping_available": user_mapping.is_available()}


# ================= DASHBOARD: TRAFFIC BULANAN & TAHUNAN =================
@app.get("/api/overview/traffic-trend")
def overview_traffic_trend():
    """Agregat traffic per bulan & per tahun dari SELURUH histori
    hourly_features -- buat grafik 'Traffic Bulanan' & 'Traffic Tahunan'
    di halaman Dashboard (bukan tabel laporan panjang)."""
    _require_data()
    monthly_df = db.query_df(
        """SELECT DATE_FORMAT(tanggal, '%Y-%m') AS ym, SUM(total_data) AS total_data
           FROM hourly_features GROUP BY ym ORDER BY ym"""
    )
    yearly_df = db.query_df(
        """SELECT YEAR(tanggal) AS year, SUM(total_data) AS total_data
           FROM hourly_features GROUP BY year ORDER BY year"""
    )
    monthly = [{"ym": r.ym, "traffic_mb": round(r.total_data / 1e6, 3)} for r in monthly_df.itertuples()]
    yearly = [{"year": int(r.year), "traffic_mb": round(r.total_data / 1e6, 3)} for r in yearly_df.itertuples()]
    return {"monthly": monthly, "yearly": yearly}


# ================= TRAFFIC ANALYSIS =================
@app.get("/api/traffic-analysis")
def traffic_analysis():
    _require_data()
    rng = db.query_one("SELECT MIN(tanggal) AS start, MAX(tanggal) AS end FROM hourly_features")
    totals = db.query_one(
        """SELECT SUM(total_data) AS total_data, SUM(jumlah_koneksi) AS total_koneksi,
                  COUNT(DISTINCT srcip) AS unique_ip FROM hourly_features"""
    )
    avg_row = db.query_one(
        """SELECT AVG(hourly_total) AS avg_kb FROM (
             SELECT tanggal, jam, SUM(total_data) AS hourly_total
             FROM hourly_features GROUP BY tanggal, jam
           ) t"""
    )
    avg_per_hour_kb = round((avg_row["avg_kb"] or 0) / 1e3, 2)

    daily_df = db.query_df(
        "SELECT tanggal, SUM(total_data) AS total_data FROM hourly_features GROUP BY tanggal ORDER BY tanggal"
    )
    daily_trend = [
        {"date": r.tanggal[5:], "traffic_mb": round(r.total_data / 1e6, 3)}
        for r in daily_df.itertuples()
    ]

    hourly_df = db.query_df(
        """SELECT LEFT(jam, 2) AS jam_h, AVG(total_data) AS avg_data
           FROM hourly_features GROUP BY jam_h ORDER BY jam_h"""
    )
    hourly_map = {r.jam_h: r.avg_data for r in hourly_df.itertuples()}
    hourly_profile = [
        {"hour": f"{h:02d}", "avg_kb": round(hourly_map.get(f"{h:02d}", 0) / 1e3, 2)}
        for h in range(24)
    ]

    top_src_df = db.query_df(
        """SELECT srcip, SUM(total_data) AS total_data FROM hourly_features
           GROUP BY srcip ORDER BY total_data DESC LIMIT 10"""
    )
    grand_total = totals["total_data"] or 1
    top_src_ip = [
        {"ip": r.srcip, "traffic_gb": round(r.total_data / 1e9, 4),
         "pct": round(r.total_data / grand_total * 100, 2)}
        for r in top_src_df.itertuples()
    ]

    top_dst_ip, top_port, protocol = [], [], []
    if db.table_exists("raw_data"):
        raw_total = db.query_one("SELECT SUM(datasize) AS s FROM raw_data")["s"] or 1

        top_dst_df = db.query_df(
            """SELECT dstip_subnet, SUM(datasize) AS total_size FROM raw_data
               GROUP BY dstip_subnet ORDER BY total_size DESC LIMIT 10"""
        )
        top_dst_ip = []
        for r in top_dst_df.itertuples():
            # Port+proto paling sering dipakai ke tujuan ini -> dasar "Application"
            dominant = db.query_one(
                """SELECT dstport, proto FROM raw_data WHERE dstip_subnet = %s
                   GROUP BY dstport, proto ORDER BY COUNT(*) DESC LIMIT 1""",
                (r.dstip_subnet,),
            )
            geo = geoip_lookup.lookup(r.dstip_subnet)
            application = (
                port_lookup.application_name(dominant["dstport"], dominant["proto"])
                if dominant else "Unknown"
            )
            top_dst_ip.append({
                "ip": r.dstip_subnet,
                "traffic_mb": round(r.total_size / 1e6, 3),
                "pct": round(r.total_size / raw_total * 100, 2),
                "country": geo["country"], "city": geo["city"], "org": geo["org"],
                "hostname": dns_lookup.hostname_for(r.dstip_subnet),
                "application": application,
            })

        top_port_df = db.query_df(
            """SELECT dstport, SUM(datasize) AS total_size, COUNT(*) AS conn FROM raw_data
               GROUP BY dstport ORDER BY total_size DESC LIMIT 10"""
        )
        top_port = [
            {"port": int(r.dstport), "name": config.PORT_NAMES.get(int(r.dstport), "Other"),
             "traffic_mb": round(r.total_size / 1e6, 3), "conn": int(r.conn),
             "pct": round(r.total_size / raw_total * 100, 2)}
            for r in top_port_df.itertuples()
        ]

        proto_df = db.query_df(
            """SELECT proto, SUM(datasize) AS total_size, COUNT(*) AS conn FROM raw_data
               GROUP BY proto ORDER BY total_size DESC"""
        )
        protocol = [
            {"proto": r.proto, "conn": int(r.conn), "traffic_mb": round(r.total_size / 1e6, 3),
             "pct": round(r.total_size / raw_total * 100, 2)}
            for r in proto_df.itertuples()
        ]

    return {
        "range_start": str(rng["start"]), "range_end": str(rng["end"]),
        "total_traffic_mb": round((totals["total_data"] or 0) / 1e6, 2),
        "total_koneksi": int(totals["total_koneksi"] or 0),
        "unique_ip": int(totals["unique_ip"] or 0),
        "avg_per_hour_kb": avg_per_hour_kb,
        "daily_trend": daily_trend,
        "hourly_profile": hourly_profile,
        "top_src_ip": top_src_ip,
        "top_dst_ip": top_dst_ip,
        "top_port": top_port,
        "protocol": protocol,
        "geoip_available": geoip_lookup.is_available(),
    }


# ================= ANOMALY DETECTION =================
@app.get("/api/anomaly")
def anomaly():
    if not db.table_exists("anomaly_predictions"):
        return {"total": 0, "level_counts": {"Tinggi": 0, "Sedang": 0, "Rendah": 0}, "type_counts": {}, "items": []}

    df = db.query_df(
        """SELECT tanggal, jam, srcip, jumlah_koneksi, jumlah_tujuan_unik, jumlah_port_unik,
                  dns_ratio, web_ratio, app_ratio, other_ratio, destination_diversity, anomaly_score
           FROM anomaly_predictions WHERE anomaly_label = 'Anomaly' ORDER BY anomaly_score DESC"""
    )

    items, level_counts, type_counts = [], {"Tinggi": 0, "Sedang": 0, "Rendah": 0}, {}
    for row in df.to_dict(orient="records"):
        status, tipe, desc = classify_type(row)  # heuristik tampilan saja -- TIDAK menyentuh model Isolation Forest
        level = classify_severity(row["anomaly_score"])
        level_counts[level] += 1
        type_counts[tipe] = type_counts.get(tipe, 0) + 1
        mapping = user_mapping.lookup(row["srcip"])
        items.append({
            "tanggal": row["tanggal"], "jam": row["jam"], "srcip": row["srcip"],
            "user": mapping["user"], "device": mapping["device"],
            "status": status, "level": level, "tipe": tipe, "deskripsi": desc,
            "score": round(row["anomaly_score"], 4),
            "jumlah_koneksi": int(row["jumlah_koneksi"]),
            "jumlah_tujuan_unik": int(row["jumlah_tujuan_unik"]),
            "jumlah_port_unik": int(row["jumlah_port_unik"]),
            "destination_diversity": round(row["destination_diversity"], 4),
        })

    return {"total": len(items), "level_counts": level_counts, "type_counts": type_counts, "items": items,
            "user_mapping_available": user_mapping.is_available()}


# ================= ANOMALY DETECTION: DETAIL PER BARIS (klik) =================
@app.get("/api/anomaly/detail")
def anomaly_detail(
    srcip: str = Query(...),
    tanggal: str = Query(..., description="format YYYY-MM-DD"),
    jam: str = Query(..., description='format "HH:00"'),
):
    """Detail 1 baris anomali buat modal klik-baris di Anomaly Detection:
    User, Device (dari mapping data/), Traffic & Destination di jam itu
    (dari raw_data). TIDAK memanggil ulang / mengubah model ML -- cuma
    query data pendukung tampilan."""
    if not db.table_exists("anomaly_predictions"):
        raise HTTPException(status_code=503, detail="Tabel anomaly_predictions belum ada.")

    row_df = db.query_df(
        """SELECT tanggal, jam, srcip, jumlah_koneksi, jumlah_tujuan_unik, jumlah_port_unik,
                  dns_ratio, web_ratio, app_ratio, other_ratio, destination_diversity, anomaly_score
           FROM anomaly_predictions WHERE srcip = %s AND tanggal = %s AND jam = %s LIMIT 1""",
        (srcip, tanggal, jam),
    )
    if row_df.empty:
        raise HTTPException(status_code=404, detail="Data anomali untuk kombinasi srcip/tanggal/jam ini tidak ditemukan.")
    row = row_df.iloc[0].to_dict()
    status, tipe, desc = classify_type(row)
    level = classify_severity(row["anomaly_score"])

    mapping = user_mapping.lookup(srcip)

    destinations = []
    if db.table_exists("raw_data"):
        jam_start = jam if ":" in jam else f"{jam}:00"
        dest_df = db.query_df(
            """SELECT dstip_subnet, dstport, proto, COUNT(*) AS conn, SUM(datasize) AS total_size
               FROM raw_data
               WHERE srcip = %s AND received_at >= %s AND received_at < %s + INTERVAL 1 HOUR
               GROUP BY dstip_subnet, dstport, proto ORDER BY total_size DESC LIMIT 10""",
            (srcip, f"{tanggal} {jam_start}", f"{tanggal} {jam_start}"),
        )
        for r in dest_df.itertuples():
            geo = geoip_lookup.lookup(r.dstip_subnet)
            destinations.append({
                "dstip": r.dstip_subnet,
                "port": int(r.dstport),
                "proto": r.proto,
                "application": port_lookup.application_name(r.dstport, r.proto),
                "country": geo["country"],
                "conn": int(r.conn),
                "traffic_bytes": int(r.total_size),
            })

    return {
        "srcip": srcip, "tanggal": row["tanggal"], "jam": row["jam"],
        "user": mapping["user"], "device": mapping["device"],
        "status": status, "level": level, "tipe": tipe, "deskripsi": desc,
        "score": round(row["anomaly_score"], 4),
        "jumlah_koneksi": int(row["jumlah_koneksi"]),
        "jumlah_tujuan_unik": int(row["jumlah_tujuan_unik"]),
        "jumlah_port_unik": int(row["jumlah_port_unik"]),
        "destination_diversity": round(row["destination_diversity"], 4),
        "destinations": destinations,
        "user_mapping_available": user_mapping.is_available(),
    }


# ================= REAL-TIME LOGS =================
@app.get("/api/logs")
def logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    proto: Optional[str] = None,
    srcip: Optional[str] = None,
    date_start: Optional[str] = Query(None, description="format YYYY-MM-DD"),
    date_end: Optional[str] = Query(None, description="format YYYY-MM-DD"),
    sort: str = Query("desc", description="'desc' (terbaru dulu) atau 'asc' (terlama dulu)"),
):
    if not db.table_exists("raw_data"):
        return {"rows": [], "total": 0, "page": page, "per_page": per_page}

    where, params = [], []
    if proto:
        where.append("proto = %s")
        params.append(proto)
    if srcip:
        where.append("srcip = %s")
        params.append(srcip)
    if date_start:
        where.append("DATE(received_at) >= %s")
        params.append(date_start)
    if date_end:
        where.append("DATE(received_at) <= %s")
        params.append(date_end)
    if search:
        like = f"%{search}%"
        search_clauses = ["srcip LIKE %s", "dstip_subnet LIKE %s", "CAST(dstport AS CHAR) LIKE %s", "proto LIKE %s"]
        search_params = [like, like, like, like]
        # Pencarian berdasarkan nama Host: cari IP yang cocok di mapping
        # IP->Host (data/), lalu ikutkan sebagai OR srcip IN (...) --
        # kalau file mapping belum ada, search_ips_by_host() balik [] dan
        # pencarian tetap jalan normal berdasarkan IP/port/protocol saja.
        matched_ips = user_mapping.search_ips_by_host(search)
        if matched_ips:
            placeholders = ", ".join(["%s"] * len(matched_ips))
            search_clauses.append(f"srcip IN ({placeholders})")
            search_params += matched_ips
        where.append("(" + " OR ".join(search_clauses) + ")")
        params += search_params
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    order_dir = "ASC" if sort == "asc" else "DESC"

    total_row = db.query_one(f"SELECT COUNT(*) AS n FROM raw_data {where_clause}", params)
    total = int(total_row["n"]) if total_row else 0

    offset = (page - 1) * per_page
    rows_df = db.query_df(
        f"""SELECT received_at, srcip, dstip_subnet, dstport, proto, datasize
            FROM raw_data {where_clause}
            ORDER BY received_at {order_dir} LIMIT %s OFFSET %s""",
        params + [per_page, offset],
    )

    # --- Host (Source IP -> Host, dari mapping IP;Host di data/) ---
    host_map = user_mapping.lookup_hosts_many(rows_df["srcip"].unique().tolist()) if len(rows_df) else {}

    # --- GeoIP + reverse DNS + Application, di-batch per Destination IP
    # unik di halaman ini saja (bukan per baris) supaya tidak lookup
    # berulang buat IP yang sama. Reader GeoIP sendiri singleton/cache
    # di geoip_lookup.py (tidak dibuat ulang tiap request). Tiap lookup
    # dibungkus try/except sendiri-sendiri supaya 1 IP yang errornya
    # aneh tidak menggagalkan seluruh response /api/logs.
    unique_dstips = rows_df["dstip_subnet"].unique().tolist() if len(rows_df) else []
    geo_map, hostname_map = {}, {}
    for ip in unique_dstips:
        try:
            geo_map[ip] = geoip_lookup.lookup(ip)
        except Exception:
            geo_map[ip] = {"country": geoip_lookup.UNKNOWN, "city": geoip_lookup.UNKNOWN, "org": geoip_lookup.UNKNOWN}
        try:
            hostname_map[ip] = dns_lookup.hostname_for(ip)
        except Exception:
            hostname_map[ip] = dns_lookup.UNKNOWN

    def _application_for(port, proto):
        try:
            return port_lookup.application_name(port, proto)
        except Exception:
            return port_lookup.UNKNOWN

    rows = []
    for r in rows_df.itertuples():
        geo = geo_map.get(r.dstip_subnet, {"country": geoip_lookup.UNKNOWN, "city": geoip_lookup.UNKNOWN, "org": geoip_lookup.UNKNOWN})
        rows.append({
            "waktu": pd.Timestamp(r.received_at).strftime("%d/%m/%Y %H:%M:%S"),
            "srcip": r.srcip,
            "host": host_map.get(r.srcip, user_mapping.UNKNOWN_HOST),
            "dstip": r.dstip_subnet,
            "country": geo["country"],
            "city": geo["city"],
            "org": geo["org"],
            "hostname": hostname_map.get(r.dstip_subnet, dns_lookup.UNKNOWN),
            "port": int(r.dstport),
            "proto": r.proto,
            "application": _application_for(r.dstport, r.proto),
            "size": int(r.datasize),
        })
    return {"rows": rows, "total": total, "page": page, "per_page": per_page,
            "user_mapping_available": user_mapping.is_available(),
            "geoip_available": geoip_lookup.is_available()}


# ================= REAL-TIME LOGS: DETAIL PER SOURCE IP =================
@app.get("/api/logs/ip-detail")
def logs_ip_detail(srcip: str = Query(...)):
    """Detail 1 Source IP buat modal klik-baris di Real-time Logs:
    Host (dari mapping IP->Host di data/), daftar Destination (+ Country,
    Application), berdasarkan histori koneksi terbaru IP itu di raw_data."""
    if not db.table_exists("raw_data"):
        raise HTTPException(status_code=503, detail="Tabel raw_data belum ada.")

    host = user_mapping.lookup_host(srcip)

    summary = db.query_one(
        """SELECT COUNT(*) AS n, MAX(received_at) AS last_seen, SUM(datasize) AS total_bytes
           FROM raw_data WHERE srcip = %s""",
        (srcip,),
    )
    total_koneksi = int(summary["n"]) if summary else 0
    last_seen = str(summary["last_seen"]) if summary and summary["last_seen"] is not None else None
    total_bytes = int(summary["total_bytes"]) if summary and summary["total_bytes"] is not None else 0

    dest_df = db.query_df(
        """SELECT dstip_subnet, dstport, proto, COUNT(*) AS conn, SUM(datasize) AS total_size
           FROM raw_data WHERE srcip = %s
           GROUP BY dstip_subnet, dstport, proto ORDER BY total_size DESC LIMIT 10""",
        (srcip,),
    )
    destinations = []
    for r in dest_df.itertuples():
        geo = geoip_lookup.lookup(r.dstip_subnet)
        destinations.append({
            "dstip": r.dstip_subnet,
            "port": int(r.dstport),
            "proto": r.proto,
            "application": port_lookup.application_name(r.dstport, r.proto),
            "country": geo["country"],
            "conn": int(r.conn),
            "traffic_bytes": int(r.total_size),
        })

    return {
        "srcip": srcip,
        "host": host,
        "total_koneksi": total_koneksi,
        "total_bytes": total_bytes,
        "last_seen": last_seen,
        "destinations": destinations,
        "user_mapping_available": user_mapping.is_available(),
    }


# ================= REPORTS =================
@app.get("/api/reports/monthly")
def report_monthly(ym: str = Query(..., description="format YYYY-MM, mis. 2026-08")):
    _require_data()
    try:
        year, month = ym.split("-")
        int(year), int(month)
    except Exception:
        raise HTTPException(status_code=400, detail="Parameter 'ym' harus format YYYY-MM")

    feat_df = db.query_df(
        """SELECT tanggal, SUM(total_data) AS total_data, SUM(jumlah_koneksi) AS total_koneksi,
                  COUNT(DISTINCT srcip) AS ip_unik
           FROM hourly_features WHERE DATE_FORMAT(tanggal, '%%Y-%%m') = %s
           GROUP BY tanggal ORDER BY tanggal""",
        (ym,),
    )
    if feat_df.empty:
        return {"ym": ym, "rows": []}

    anomaly_df = pd.DataFrame(columns=["tanggal", "n"])
    if db.table_exists("anomaly_predictions"):
        anomaly_df = db.query_df(
            """SELECT tanggal, COUNT(*) AS n FROM anomaly_predictions
               WHERE DATE_FORMAT(tanggal, '%%Y-%%m') = %s AND anomaly_label = 'Anomaly'
               GROUP BY tanggal""",
            (ym,),
        )
    anomaly_map = dict(zip(anomaly_df.get("tanggal", []), anomaly_df.get("n", [])))

    top_port_map, top_proto_map = {}, {}
    if db.table_exists("raw_data"):
        raw_df = db.query_df(
            """SELECT DATE(received_at) AS d, dstport, proto FROM raw_data
               WHERE DATE_FORMAT(received_at, '%%Y-%%m') = %s""",
            (ym,),
        )
        if not raw_df.empty:
            raw_df["d"] = raw_df["d"].astype(str)
            for d, g in raw_df.groupby("d"):
                top_port = g["dstport"].value_counts().idxmax()
                top_port_map[d] = f"{int(top_port)} ({config.PORT_NAMES.get(int(top_port), 'Other')})"
                top_proto_map[d] = g["proto"].value_counts().idxmax()

    rows = [
        {
            "tanggal": r.tanggal,
            "total_traffic_mb": round(r.total_data / 1e6, 2),
            "total_koneksi": int(r.total_koneksi),
            "ip_unik": int(r.ip_unik),
            "top_port": top_port_map.get(r.tanggal, "-"),
            "top_protocol": top_proto_map.get(r.tanggal, "-"),
            "jumlah_anomali": int(anomaly_map.get(r.tanggal, 0)),
        }
        for r in feat_df.itertuples()
    ]
    return {"ym": ym, "rows": rows}


@app.get("/api/reports/yearly")
def report_yearly(year: int = Query(..., description="mis. 2026")):
    _require_data()
    feat_df = db.query_df(
        """SELECT DATE_FORMAT(tanggal, '%%m') AS mo, SUM(total_data) AS total_data,
                  SUM(jumlah_koneksi) AS total_koneksi, COUNT(DISTINCT srcip) AS ip_unik,
                  COUNT(DISTINCT tanggal) AS n_days
           FROM hourly_features WHERE YEAR(tanggal) = %s GROUP BY mo""",
        (year,),
    )
    feat_map = {r.mo: r for r in feat_df.itertuples()}

    anomaly_map = {}
    if db.table_exists("anomaly_predictions"):
        anomaly_df = db.query_df(
            """SELECT DATE_FORMAT(tanggal, '%%m') AS mo, COUNT(*) AS n
               FROM anomaly_predictions WHERE YEAR(tanggal) = %s AND anomaly_label = 'Anomaly'
               GROUP BY mo""",
            (year,),
        )
        anomaly_map = dict(zip(anomaly_df["mo"], anomaly_df["n"]))

    rows = []
    for i in range(1, 13):
        mo = f"{i:02d}"
        r = feat_map.get(mo)
        if r is None:
            rows.append({
                "bulan": MONTH_NAMES_ID[i - 1], "total_traffic_mb": None, "total_koneksi": None,
                "ip_unik": None, "avg_per_hari_mb": None, "jumlah_anomali": None,
            })
        else:
            total_mb = r.total_data / 1e6
            rows.append({
                "bulan": MONTH_NAMES_ID[i - 1],
                "total_traffic_mb": round(total_mb, 2),
                "total_koneksi": int(r.total_koneksi),
                "ip_unik": int(r.ip_unik),
                "avg_per_hari_mb": round(total_mb / max(r.n_days, 1), 2),
                "jumlah_anomali": int(anomaly_map.get(mo, 0)),
            })
    return {"year": year, "rows": rows}


@app.get("/api/info")
def api_info():
    """Info service (dulu ada di '/' -- dipindah ke sini karena '/' sekarang
    dipakai buat serve dashboard/index.html, lihat mount StaticFiles di bawah)."""
    return {
        "service": "Network Monitoring API",
        "endpoints": [
            "/api/health", "/api/meta", "/api/overview", "/api/overview/traffic-trend",
            "/api/traffic-analysis", "/api/anomaly", "/api/anomaly/detail",
            "/api/logs", "/api/logs/ip-detail", "/api/user-activity",
            "/api/reports/monthly?ym=YYYY-MM", "/api/reports/yearly?year=YYYY",
        ],
        "docs": "/docs",
    }


# ================= SERVE DASHBOARD (SATU PORT DENGAN API) =================
# Mount ini SENGAJA ditaruh PALING BAWAH (setelah semua route /api/... di
# atas didaftarkan) supaya route /api/... tetap diprioritaskan Starlette
# sebelum jatuh ke static files. StaticFiles(html=True) otomatis serve
# dashboard/index.html untuk "/" dan untuk path lain yang tidak match file
# (mis. refresh di path SPA), serta serve app.js/style.css/asset lain apa
# adanya lewat path relatif (mis. GET /app.js, GET /style.css).
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")