"""One-time migration (2026-07-24): backfill `property_id` onto every pre-existing document
across the core collections, and create the first `properties` doc representing the homestay
that's been running as the sole implicit property so far.

Safe to run more than once — every step only touches documents that don't already have a
`property_id` set, so re-running after a partial failure just picks up where it left off.

Usage: run manually from backend/ with the venv active:
    python3 -m scripts.migrate_multi_property
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core import db, now_iso  # noqa: E402

DEFAULT_PROPERTY_NAME = "Pelangi Homestay"
DEFAULT_PROPERTY_SLUG = "pelangi-homestay"

# Semua collection bisnis yang mulai di-scope per properti (lihat plan multi-properti,
# core.py: scoped()/get_active_property).
CORE_COLLECTIONS = [
    "rooms", "bookings", "checkins", "guests", "staff_kerja", "staff_profil",
    "jadwal_kerja", "jadwal_shifts", "issues", "expenses", "payroll",
    "booking_requests", "products", "kasir", "rates", "services", "kasbon",
]


async def main():
    existing = await db.properties.find_one({"slug": DEFAULT_PROPERTY_SLUG})
    if existing:
        default_id = existing["id"]
        print(f"Properti default sudah ada: {default_id}")
    else:
        default_id = str(uuid.uuid4())
        await db.properties.insert_one({
            "id": default_id, "nama": DEFAULT_PROPERTY_NAME, "slug": DEFAULT_PROPERTY_SLUG,
            "alamat": "", "aktif": True, "created_at": now_iso(),
        })
        print(f"Properti default dibuat: {default_id} ({DEFAULT_PROPERTY_NAME})")

    for name in CORE_COLLECTIONS:
        coll = db[name]
        result = await coll.update_many(
            {"property_id": {"$exists": False}},
            {"$set": {"property_id": default_id}},
        )
        remaining = await coll.count_documents({"property_id": {"$exists": False}})
        print(f"{name}: {result.modified_count} dokumen di-set property_id, sisa tanpa property_id: {remaining}")

    # Resepsionis existing user(s) dikunci ke properti default juga - owner tidak perlu
    # property_id (get_active_property menganggap None/absen role owner = akses semua).
    r = await db.users.update_many(
        {"role": "resepsionis", "property_id": {"$exists": False}},
        {"$set": {"property_id": default_id}},
    )
    print(f"users (resepsionis): {r.modified_count} akun di-set property_id")

    print("\nSelesai. Verifikasi manual: pastikan semua baris di atas 'sisa tanpa property_id: 0'.")


if __name__ == "__main__":
    asyncio.run(main())
