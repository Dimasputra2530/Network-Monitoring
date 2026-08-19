"""
generate_report.py -- Cetak & simpan laporan bulanan/tahunan dari tabel
`anomaly_predictions`.

Jalankan:
    python generate_report.py --month 2026-08     # laporan bulan Agustus 2026
    python generate_report.py --year 2026          # laporan tahun 2026

Butuh predict.py sudah pernah dijalankan minimal sekali dengan versi
terbaru (yang sudah nulis ke tabel anomaly_predictions), supaya ada data
buat dilaporkan.
"""
import argparse
import json

import config
import reports


def print_summary(summary: dict, label: str, trend_key: str, trend_col: str):
    print(f"=== Laporan {label}: {summary['periode']} ===")
    print(f"Total baris dipantau : {summary['total_baris']}")
    print(f"Total anomali        : {summary['total_anomali']}")
    print(f"Tingkat anomali      : {summary['tingkat_anomali']:.2%}")

    print("\nTop host anomali:")
    if summary["top_host_anomali"]:
        for srcip, count in summary["top_host_anomali"].items():
            print(f"  {srcip:<20} {count} kali")
    else:
        print("  (tidak ada anomali di periode ini)")

    print(f"\nTren per {trend_col}:")
    if summary[trend_key]:
        for row in summary[trend_key]:
            print(f"  {row[trend_col]:<12} total={row['total_baris']:<6} anomali={row['total_anomali']}")
    else:
        print("  (tidak ada data)")


def main():
    parser = argparse.ArgumentParser(description="Generate laporan bulanan/tahunan anomali.")
    parser.add_argument("--month", help="Format YYYY-MM, mis. 2026-08")
    parser.add_argument("--year", type=int, help="Format YYYY, mis. 2026")
    args = parser.parse_args()

    if not args.month and not args.year:
        parser.error("Isi salah satu: --month YYYY-MM atau --year YYYY")

    reports_dir = config.OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    if args.month:
        year, month = (int(x) for x in args.month.split("-"))
        summary = reports.get_monthly_report(year, month)
        print_summary(summary, "Bulanan", "tren_harian", "tanggal")
        out_path = reports_dir / f"laporan_bulanan_{args.month}.json"
    else:
        summary = reports.get_yearly_report(args.year)
        print_summary(summary, "Tahunan", "tren_bulanan", "bulan")
        out_path = reports_dir / f"laporan_tahunan_{args.year}.json"

    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nDetail lengkap (JSON) -> {out_path}")


if __name__ == "__main__":
    main()
