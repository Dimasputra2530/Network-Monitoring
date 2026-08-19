"""
user_mapping.py -- baca mapping IP -> Host dari folder `data/` di ROOT
project (sejajar dengan etl_app/, anomaly_detection/, api/, dashboard/)
-- BUKAN `etl_app/data/` (folder itu isinya snapshot hasil ETL, beda
keperluan).

Format file mapping yang didukung HANYA 2 kolom:
    IP;Host
    192.168.1.10;PC-DIMAS
    192.168.1.11;PC-HRD
    192.168.1.12;LAPTOP-ADMIN

TIDAK ADA kolom User/Username/Guest -- data itu memang tidak tersedia,
jadi modul ini TIDAK mencari atau mengandalkan kolom tsb sama sekali.
Kalau Source IP tidak ada di mapping, hasil lookup adalah "Unknown".

Taruh file mapping di salah satu nama berikut di `data/` (dicek sesuai
urutan ini):
    data/user_mapping.csv
    data/user_guest_mapping.csv
    data/users.csv

Delimiter di-deteksi otomatis per file (sebagian besar export Excel di
Indonesia pakai ";", tapi ini tetap jaga-jaga kalau ada yang pakai ",").
Nama kolom tidak case-sensitive dan boleh diapit whitespace -- lihat
_COLUMN_ALIASES untuk alias yang dikenali.

File di-reload otomatis kalau berubah (cek mtime), jadi begitu file
di-update di server, tidak perlu restart API.
"""
import csv
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAPPING_FILENAME_CANDIDATES = ["user_mapping.csv"]

# Hanya 2 konsep kolom yang didukung: IP (key lookup) dan Host (nama
# perangkat yang ditampilkan). TIDAK ADA alias untuk User/Username/Guest.
_COLUMN_ALIASES = {
    "ip": {"ip", "srcip", "src_ip", "source_ip", "sourceip"},
    "host": {"host", "hostname", "device", "device_name", "nama_host", "nama_perangkat"},
}

UNKNOWN_HOST = "Unknown"
# Alias lama dipertahankan (dipakai oleh endpoint lain seperti
# /api/user-activity dan /api/anomaly/detail yang belum diminta untuk
# diubah) supaya tidak ada logic lain yang jadi rusak oleh perubahan ini.
UNKNOWN_USER = "Unknown"
UNKNOWN_DEVICE = "Unknown"

_cache_lock = Lock()
_cache = {"path": None, "mtime": None, "data": {}}


def _find_mapping_file():
    """Cari file mapping di data/. Balik None kalau folder/file belum ada."""
    if not DATA_DIR.exists():
        return None
    for name in MAPPING_FILENAME_CANDIDATES:
        p = DATA_DIR / name
        if p.exists():
            return p
    return None


def _detect_delimiter(sample: str) -> str:
    """Deteksi delimiter dari baris header. File mapping user pada
    umumnya export Excel Indonesia -> pakai ';'. Kalau jumlah ';' di
    baris pertama lebih banyak/sama dari ',', pakai ';'; selain itu ','.
    Ini mencegah salah baca seperti header "IP;Host" yang kalau dipaksa
    pakai delimiter default (',') akan dianggap SATU kolom bernama
    "IP;Host" sehingga kolom IP/Host tidak pernah ketemu."""
    first_line = sample.splitlines()[0] if sample else ""
    if first_line.count(";") >= first_line.count(","):
        return ";"
    return ","


def _normalize_ip(value) -> str:
    """Bersihkan whitespace & pastikan hasil selalu string, supaya
    perbedaan tipe data (mis. IP kebaca sebagai angka/float oleh Excel)
    tidak membuat mapping gagal cocok."""
    return str(value if value is not None else "").strip()


def _resolve_columns(fieldnames):
    resolved = {}
    lowered = {(f or "").strip().lower(): f for f in (fieldnames or [])}
    for key, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                resolved[key] = lowered[alias]
                break
    return resolved


def _load_mapping():
    """Baca & cache isi file mapping (IP -> Host). Cache di-invalidate
    otomatis kalau mtime file berubah. Balik dict kosong (bukan
    exception) kalau file belum ada / format tidak sesuai -- caller
    selalu dapat jawaban aman ("Unknown")."""
    path = _find_mapping_file()
    if path is None:
        with _cache_lock:
            _cache.update({"path": None, "mtime": None, "data": {}})
        return {}

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}

    with _cache_lock:
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["data"]

    data = {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            raw = f.read()
        delimiter = _detect_delimiter(raw)
        reader = csv.DictReader(raw.splitlines(), delimiter=delimiter)
        cols = _resolve_columns(reader.fieldnames)
        if "ip" not in cols:
            data = {}
        else:
            for row in reader:
                ip = _normalize_ip(row.get(cols["ip"]))
                if not ip:
                    continue
                host = str(row.get(cols.get("host", ""), "") or "").strip()
                data[ip] = host if host else UNKNOWN_HOST
    except (OSError, csv.Error):
        data = {}

    with _cache_lock:
        _cache.update({"path": path, "mtime": mtime, "data": data})
    return data


def lookup_host(srcip: str) -> str:
    """Balikin nama Host untuk satu Source IP. "Unknown" kalau IP tidak
    ada di mapping (bukan error -- itu kondisi normal untuk IP baru)."""
    data = _load_mapping()
    return data.get(_normalize_ip(srcip), UNKNOWN_HOST)


def lookup_hosts_many(srcips) -> dict:
    """Versi batch dari lookup_host() -- satu kali baca file buat banyak
    IP sekaligus, dipakai di endpoint yang me-loop banyak baris
    (mis. /api/logs)."""
    data = _load_mapping()
    return {ip: data.get(_normalize_ip(ip), UNKNOWN_HOST) for ip in srcips}


def search_ips_by_host(keyword: str) -> list:
    """Balikin daftar srcip yang nama Host-nya mengandung `keyword`
    (case-insensitive) -- dipakai supaya pencarian di Real-time Logs
    bisa cari berdasarkan nama host juga, bukan cuma IP/port/protocol."""
    if not keyword:
        return []
    data = _load_mapping()
    kw = keyword.strip().lower()
    return [ip for ip, host in data.items() if kw in (host or "").lower()]


def is_available() -> bool:
    """True kalau file mapping IP->Host sudah ditaruh di data/."""
    return _find_mapping_file() is not None


# ---------------------------------------------------------------------
# Kompatibilitas untuk endpoint lain yang sudah berjalan (mis.
# /api/user-activity, /api/anomaly/*) dan belum diminta diubah --
# TIDAK ADA data User/Guest di file mapping baru, jadi "user" selalu
# "Unknown" apa adanya (bukan lagi label "Guest" tebakan), sedangkan
# "device" tetap terisi benar dari kolom Host karena secara konsep nama
# host = nama perangkat.
# ---------------------------------------------------------------------
def lookup(srcip: str) -> dict:
    host = lookup_host(srcip)
    return {"host": host, "device": host, "user": UNKNOWN_USER}


def lookup_many(srcips) -> dict:
    hosts = lookup_hosts_many(srcips)
    return {ip: {"host": host, "device": host, "user": UNKNOWN_USER} for ip, host in hosts.items()}


def search_ips_by_user(keyword: str) -> list:
    """Alias lama; sekarang cari berdasarkan Host (tidak ada lagi kolom
    User untuk dicari)."""
    return search_ips_by_host(keyword)
