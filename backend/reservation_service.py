"""Reservation service — logika terpusat seputar booking kamar.

Tahap 1: cek ketersediaan kamar (anti-overbooking). Logika ini sebelumnya
terduplikasi di routes/bookings.py (create_booking, update_booking) dan
routes/public.py (public_create_booking).
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
