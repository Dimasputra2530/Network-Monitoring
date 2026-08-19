"""
port_lookup.py -- turunkan "Application" dari Port + Protocol buat
halaman Traffic Analysis (GeoIP section).

Reuse `etl_app/port_service_map.py` langsung (BUKAN duplikasi daftar
port) -- pola importlib yang sama dengan `db.py` (lihat komentar di
sana kenapa perlu importlib, bukan `import` biasa).
"""
import importlib.util
import sys
from pathlib import Path

ETL_APP_DIR = Path(__file__).resolve().parent.parent / "etl_app"

UNKNOWN = "Unknown"


def _load_module_from_path(unique_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(unique_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


def _import_port_service_map():
    if "etl_app_port_service_map" in sys.modules:
        return sys.modules["etl_app_port_service_map"]
    return _load_module_from_path(
        "etl_app_port_service_map", ETL_APP_DIR / "port_service_map.py"
    )


_port_map = _import_port_service_map()  # reuse dari etl_app, BUKAN duplikasi


def application_name(port, proto: str = "") -> str:
    """(port, proto) -> nama aplikasi/service, mis. (443, 'TCP') -> 'HTTPS'.
    Port yang tidak ada di PORT_SERVICE_MAP (etl_app/) -> 'Unknown',
    TIDAK dikarang-karang."""
    try:
        name, _category = _port_map.map_port(int(port))
    except (TypeError, ValueError):
        return UNKNOWN
    if name == "Unknown Service":
        return UNKNOWN
    return name
