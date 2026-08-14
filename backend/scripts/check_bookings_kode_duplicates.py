"""Read-only check (2026-08-14, temuan audit #5): cek apakah db.bookings.kode punya
duplikat SEBELUM menambahkan unique index - retrofit unique index ke collection LIVE
bisa gagal keras kalau ada satu saja duplikat historis. `kode` dibuat dari timestamp-ke-
detik + 4 karakter hex acak (`reservation_service.py:210`) - proteksi tabrakan murni
probabilistik. Temuan ini LOW priority justru KARENA alasan ini - retrofit index ke data
live itu sendiri berisiko, bukan karena kemungkinan tabrakannya besar.

TIDAK MENGUBAH DATA APA PUN - murni aggregation ($group + $match count>1), read-only
total, aman dijalankan langsung terhadap DB produksi.

Jalankan:
    cd backend && venv/bin/python -m scripts.check_bookings_kode_duplicates

Exit 0 kalau nol duplikat ditemukan (aman lanjut tambah unique index). Exit 1 kalau ADA
duplikat - BERHENTI, jangan tambah unique index, laporkan sebagai temuan yang butuh
keputusan data-cleanup dari Agus, bukan langsung ditambal lewat kode.
"""
import asyncio
import sys

sys.path.insert(0, ".")


async def main():
    from core import db

    total_bookings = await db.bookings.count_documents({})
    print(f"Total dokumen db.bookings: {total_bookings}")

    pipeline = [
        {"$match": {"kode": {"$ne": None}}},
        {"$group": {
            "_id": "$kode",
            "count": {"$sum": 1},
            "ids": {"$push": "$id"},
            "property_ids": {"$push": "$property_id"},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    duplikat = await db.bookings.aggregate(pipeline).to_list(1000)

    if not duplikat:
        print("Nol duplikat kode ditemukan di db.bookings - AMAN tambah unique index.")
        return

    print(f"\nDITEMUKAN {len(duplikat)} nilai kode yang duplikat (BUKAN aman ditambah unique index):")
    for d in duplikat:
        print(f"  kode={d['_id']!r} count={d['count']} ids={d['ids']} property_ids={d['property_ids']}")
    print(
        "\nBERHENTI - jangan tambah unique index sebelum data duplikat ini dibersihkan "
        "atau Agus memutuskan cara penanganannya. Ini laporan temuan, bukan fix otomatis."
    )
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
