"""Koreksi manual satu kali (2026-08-20) - investigasi Claude Code diminta Agus,
lanjutan kasus Ayu Santika/Bhargo Mulia (bug pembatalan-otomatis email modifikasi
RedDoorz tanggal-tidak-berubah).

Reservasi 77125102 ("IrsyadKamil Guest", checkin 13 Jan 2027) dibatalkan keliru
14 Agustus 2026 - beda dari kasus Bhargo Mulia (bukan rebooking cepat, jarak 2 minggu
dari booking asli, kemungkinan besar tamu genuine). Dikonfirmasi Agus "ya gitu aja"
(aktifkan, anggap tamu terpisah dari reservasi 6443681977/"Irsyad Kamil" checkin
14 Jan 2027 yang sudah direkonstruksi terpisah) - kedua reservasi tidak bentrok kamar/
tanggal (13->14 dan 14->15 Jan, berurutan, tidak tumpang tindih).

Jalankan SEKALI: venv/bin/python -m scripts.fix_irsyad_kamil_wrongful_cancel
"""
import asyncio
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

BOOKING_ID_OTA_RESERVASI = "77125102"


async def main():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["pms"]

    booking = await db.bookings.find_one({"ota_reservation_no": BOOKING_ID_OTA_RESERVASI})
    if not booking:
        print("Booking tidak ditemukan - stop.")
        return
    if booking["status"] != "cancelled":
        print(f"Status sekarang '{booking['status']}', bukan 'cancelled' - skrip sudah pernah jalan atau state berubah, stop.")
        return

    bentrok = await db.bookings.find_one({
        "room_id": booking["room_id"], "status": {"$ne": "cancelled"}, "id": {"$ne": booking["id"]},
        "jam_mulai": {"$lt": booking["jam_selesai"]},
        "jam_selesai": {"$gt": booking["jam_mulai"]},
    })
    if bentrok:
        print(f"Bentrok dgn booking {bentrok.get('kode')} - stop, tidak ada yang diubah.")
        return

    now = datetime.now(timezone.utc).isoformat()
    catatan_baru = (
        booking.get("catatan", "")
        + " [Dikoreksi 2026-08-20 oleh Claude Code (investigasi diminta Agus, dikonfirmasi "
          "\"ya gitu aja\"): dibatalkan keliru oleh bug pembatalan-otomatis email modifikasi "
          "RedDoorz (tanggal tidak berubah) - beda dari kasus Bhargo Mulia, ini bukan rebooking "
          "cepat, dianggap tamu genuine terpisah dari reservasi 6443681977.]"
    )
    result = await db.bookings.update_one(
        {"ota_reservation_no": BOOKING_ID_OTA_RESERVASI, "status": "cancelled"},
        {
            "$set": {"status": "aktif", "catatan": catatan_baru, "updated_at": now, "updated_by": "claude_code_investigation"},
            "$unset": {"cancelled_at": "", "cancelled_by": "", "cancel_reason": ""},
        },
    )
    print(f"update matched={result.matched_count} modified={result.modified_count}")

    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "claude_code_investigation",
        "action": "koreksi_manual_booking_ota",
        "detail": f"Reaktivasi {booking['kode']} (IrsyadKamil Guest, no. OTA {BOOKING_ID_OTA_RESERVASI}) - dibatalkan keliru oleh bug proses_modifikasi_otomatis.",
        "entity": booking.get("room_nomor", ""), "timestamp": now,
    })
    print("audit_log dicatat. Selesai.")


if __name__ == "__main__":
    asyncio.run(main())
