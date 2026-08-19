"""
dns_lookup.py -- reverse DNS (PTR) lookup buat kolom "Hostname" di
Traffic Analysis (GeoIP section). Best-effort saja: banyak IP tujuan
(apalagi subnet /24 hasil masking clean.py) memang tidak punya PTR
record, atau reverse-lookup-nya lambat/timeout -- kalau gagal balik
"Unknown", TIDAK ADA hostname palsu yang dikarang.

Ada cache in-memory (per proses) + HARD timeout per lookup (dijalankan
di worker thread terpisah, ditinggal kalau lewat batas waktu) supaya
endpoint Traffic Analysis tidak ikut nge-hang kalau resolver DNS di
jaringan server lambat/tidak reachable sama sekali -- `socket.gethostbyaddr`
memanggil resolver sistem yang TIDAK selalu menghormati
`socket.setdefaulttimeout()`, jadi timeout itu sendirian tidak cukup buat
menjamin lookup ini tidak menggantung.
"""
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Lock

UNKNOWN = "Unknown"
LOOKUP_TIMEOUT_SECONDS = 0.6

_cache_lock = Lock()
_cache = {}
# max_workers kecil; kalau sebuah lookup timeout, thread-nya dibiarkan
# selesai sendiri di background tanpa memblokir request yang menunggunya.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dns-lookup")


def _resolve(ip_only: str) -> str:
    try:
        host, _aliases, _addrs = socket.gethostbyaddr(ip_only)
        return host or UNKNOWN
    except Exception:
        return UNKNOWN


def hostname_for(ip: str) -> str:
    """Balikin PTR hostname untuk 1 IP/subnet, atau 'Unknown' kalau tidak
    ketemu / timeout / resolver tidak reachable. `dstip_subnet` hasil
    clean.py ('x.x.x.0/24') di-strip dulu bagian '/24'-nya."""
    if not ip:
        return UNKNOWN
    ip_only = ip.split("/")[0].strip()
    if not ip_only:
        return UNKNOWN

    with _cache_lock:
        if ip_only in _cache:
            return _cache[ip_only]

    future = _executor.submit(_resolve, ip_only)
    try:
        result = future.result(timeout=LOOKUP_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        result = UNKNOWN
        # sengaja tidak dibatalkan paksa -- gethostbyaddr() yang sudah
        # berjalan di thread tidak bisa diinterupsi dari luar, jadi
        # dibiarkan selesai sendiri di background tanpa memblokir request ini
    except Exception:
        result = UNKNOWN

    with _cache_lock:
        _cache[ip_only] = result
    return result
