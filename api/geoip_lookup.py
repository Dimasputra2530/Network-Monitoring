"""
geoip_lookup.py -- GeoIP lookup (Country, City, Organization/ASN) buat
Destination IP di halaman Traffic Analysis, pakai MaxMind GeoLite2.

PENTING: file database GeoLite2 (.mmdb) TIDAK disertakan di repo ini --
harus didaftar & diunduh sendiri (gratis) dari MaxMind:
https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
Modul ini HANYA menyiapkan integrasinya. Kalau file belum ada / library
`geoip2` belum terinstall / IP tidak ketemu di database (mis. IP privat/
lokal, atau subnet hasil masking clean.py) -> semua field balik
"Unknown", TIDAK ADA data lokasi palsu yang dibuat di sini.

Taruh file database di `data/` (root project, sejajar etl_app/, api/,
dashboard/):
    data/GeoLite2-City.mmdb   -> dipakai untuk Country & City
    data/GeoLite2-ASN.mmdb    -> dipakai untuk Organization / ASN

Install library (opsional, sudah ada di requirements.txt):
    pip install geoip2
"""
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CITY_DB_PATH = DATA_DIR / "GeoLite2-City.mmdb"
ASN_DB_PATH = DATA_DIR / "GeoLite2-ASN.mmdb"

UNKNOWN = "Unknown"

_lock = Lock()
_state = {"city_reader": None, "city_loaded": False, "asn_reader": None, "asn_loaded": False}


def _get_city_reader():
    with _lock:
        if _state["city_loaded"]:
            return _state["city_reader"]
        _state["city_loaded"] = True
        if not CITY_DB_PATH.exists():
            return None
        try:
            import geoip2.database
            _state["city_reader"] = geoip2.database.Reader(str(CITY_DB_PATH))
        except Exception:
            _state["city_reader"] = None
        return _state["city_reader"]


def _get_asn_reader():
    with _lock:
        if _state["asn_loaded"]:
            return _state["asn_reader"]
        _state["asn_loaded"] = True
        if not ASN_DB_PATH.exists():
            return None
        try:
            import geoip2.database
            _state["asn_reader"] = geoip2.database.Reader(str(ASN_DB_PATH))
        except Exception:
            _state["asn_reader"] = None
        return _state["asn_reader"]


def lookup(ip: str) -> dict:
    """Balikin {'country', 'city', 'org'} untuk 1 IP/subnet. `dstip_subnet`
    hasil clean.py berbentuk 'x.x.x.0/24' -- bagian '/24' dibuang dulu
    supaya tetap bisa di-lookup (representasi IP pertama di subnet itu,
    cukup akurat untuk keperluan tampilan Country/City/Org)."""
    result = {"country": UNKNOWN, "city": UNKNOWN, "org": UNKNOWN}
    if not ip:
        return result
    ip_only = ip.split("/")[0].strip()
    if not ip_only:
        return result

    city_reader = _get_city_reader()
    if city_reader is not None:
        try:
            resp = city_reader.city(ip_only)
            result["country"] = resp.country.name or UNKNOWN
            result["city"] = resp.city.name or UNKNOWN
        except Exception:
            pass

    asn_reader = _get_asn_reader()
    if asn_reader is not None:
        try:
            resp = asn_reader.asn(ip_only)
            org = resp.autonomous_system_organization
            asn_num = resp.autonomous_system_number
            if org and asn_num:
                result["org"] = f"{org} (AS{asn_num})"
            elif org:
                result["org"] = org
        except Exception:
            pass

    return result


def lookup_many(ips) -> dict:
    return {ip: lookup(ip) for ip in ips}


def is_available() -> bool:
    return CITY_DB_PATH.exists() or ASN_DB_PATH.exists()
