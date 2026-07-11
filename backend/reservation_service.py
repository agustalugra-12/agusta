"""Reservation service — logika terpusat seputar booking kamar.

Tahap 1: cek ketersediaan kamar (anti-overbooking). Logika ini sebelumnya
terduplikasi di routes/bookings.py (create_booking, update_booking) dan
routes/public.py (public_create_booking).

Tahap 2: pembuatan reservasi (create_reservation). Logika ini sebelumnya
ada di routes/public.py (public_create_booking) — dipusatkan supaya sumber
booking lain (mis. OTA) bisa memakai alur yang sama.
"""
from core import *


async def check_room_available(room_id: str, mulai: datetime, selesai: datetime,
                                exclude_booking_id: Optional[str] = None) -> bool:
    """Raise HTTPException(400) jika kamar sudah dibooking pada rentang [mulai, selesai).
    Booking yang dianggap konflik: status aktif/booking_pending/booking_paid.
    exclude_booking_id dipakai saat reschedule (update_booking) agar booking itu
    sendiri tidak dianggap konflik dengan dirinya sendiri.
    """
    query: Dict[str, Any] = {
        "room_id": room_id,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": selesai.isoformat()},
        "jam_selesai": {"$gt": mulai.isoformat()},
    }
    if exclude_booking_id:
        query["id"] = {"$ne": exclude_booking_id}
    overlap = await db.bookings.find_one(query)
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")
    return True


async def create_reservation(data: Dict[str, Any], source: str = "public",
                              harga_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Buat reservasi/booking baru. Dipakai oleh public_create_booking (source="online");
    disiapkan agar sumber lain (mis. OTA) bisa memakai alur yang sama lewat harga_override.

    data wajib berisi: room_id, nama_tamu, no_hp, email, no_identitas, kendaraan,
    jumlah_tamu, jam_mulai (datetime UTC), jam_selesai (datetime UTC), catatan, created_by.
    data boleh berisi: tipe (default "day_use"), extra_bed_qty (default 0).

    harga_override, jika diisi, wajib berisi subtotal/service_fee/total/dp_min final
    (tidak dihitung ulang) — extra bed (kalau ada) harus sudah termasuk di subtotal.
    """
    r = await db.rooms.find_one({"id": data["room_id"]})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, "Kamar tidak tersedia")

    mulai = data["jam_mulai"]
    selesai = data["jam_selesai"]
    await check_room_available(data["room_id"], mulai, selesai)

    extra_bed_qty = max(0, min(EXTRA_BED_MAX, int(data.get("extra_bed_qty") or 0)))

    if harga_override is not None:
        subtotal = harga_override["subtotal"]
        service_fee = harga_override["service_fee"]
        total = harga_override["total"]
        dp_min = harga_override["dp_min"]
    else:
        subtotal = r["tarif"] + extra_bed_qty * EXTRA_BED_PRICE
        service_fee = round(subtotal * SERVICE_FEE_PCT)
        total = subtotal + service_fee
        dp_min = round(total * 0.5)

    kode = f"BKO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    doc = {
        "id": str(uuid.uuid4()), "kode": kode,
        "room_id": data["room_id"], "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tipe": data.get("tipe", "day_use"),
        "nama_tamu": data["nama_tamu"], "no_hp": data["no_hp"],
        "email": data["email"],
        "no_identitas": data["no_identitas"], "kendaraan": data["kendaraan"],
        "jumlah_tamu": data["jumlah_tamu"], "extra_bed_qty": extra_bed_qty,
        "jam_mulai": mulai.isoformat(), "jam_selesai": selesai.isoformat(),
        "catatan": data["catatan"],
        "status": "booking_pending",          # status booking utama (untuk public booking)
        "payment_status": "pending",          # pending | paid | expired | failed | refunded
        "subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": dp_min,
        "source": source,                      # online | walk_in
        "invoice_id": None, "payment_id": None,
        "created_at": now_iso(), "created_by": data["created_by"],
    }
    await db.bookings.insert_one(doc)
    await log_availability_change(r["id"], r["tipe"], -1, "booking_dibuat", booking_id=doc["id"])

    if source == "online":
        action, username = "public_create_booking", "public"
    else:
        action, username = f"create_booking_{source}", source
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": username,
        "action": action,
        "detail": f"Public booking {kode} kamar {r['nomor']} ({r['tipe']}) untuk {data['nama_tamu']}",
        "entity": r["nomor"], "timestamp": now_iso(),
    })
    doc.pop("_id", None)
    return doc
