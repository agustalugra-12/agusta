"""Koreksi manual satu kali (2026-08-19) - investigasi Claude Code (uji coba pertama
shared engineering workflow, diminta Agus).

Bug: proses_modifikasi_otomatis() di routes/otomasi_email.py membatalkan booking
BKO-20260801051546-41FA (Ayu Santika, no. OTA 444267135972444) hari ini krn heuristik
"pembatalan terselubung" (tanggal+nama sama persis di email modifikasi RedDoorz) salah
deteksi - tamunya genuine checkin hari ini, bukan pembatalan. Root cause lengkap &
riwayat investigasi ada di percakapan sesi ini, bukan diulang di sini.

Selagi bug ini aktif, kamar 10 (kamar asli booking ini) sempat kelihatan kosong dan
diisi tamu RedDoorz LAIN yang genuine (Made Lisyantari, no. OTA 444266136901953,
BKO-20260819193756-17AE) - jadi booking ini TIDAK BISA dikembalikan ke kamar 10,
dipindah ke kamar 13 (dicek kosong utk 19-20 Agustus sebelum skrip ini ditulis).

Verifikasi data: dicek langsung ke Gmail (bukan cuma email_logs yang sudah diproses
aplikasi) - HANYA ada 2 email asli utk reservasi ini (booking baru 30 Juli, modifikasi
hari ini), tidak ada email terpisah 31 Juli - input manual Agus 31 Juli sudah cocok
persis dgn data email 30 Juli (tipe kamar, tanggal, jumlah tamu).

Jalankan SEKALI: venv/bin/python -m scripts.fix_ayu_santika_ota_wrongful_cancel
"""
import asyncio
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "pms"
BOOKING_ID = "a933b24a-47d4-431d-9862-45609227bcd2"
PROPERTY_ID = "87ba6186-d849-48a4-a18c-bb8269fb56d2"
KAMAR_BARU_NOMOR = "13"


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    booking = await db.bookings.find_one({"id": BOOKING_ID})
    if not booking:
        print("Booking tidak ditemukan, skrip sudah pernah jalan atau ID salah - stop.")
        return
    if booking["status"] != "cancelled":
        print(f"Status booking sekarang '{booking['status']}', bukan 'cancelled' - skrip sudah pernah jalan atau state berubah, stop (tidak ada yang diubah).")
        return

    kamar_baru = await db.rooms.find_one({"property_id": PROPERTY_ID, "tipe": "Standard", "nomor": KAMAR_BARU_NOMOR})
    if not kamar_baru:
        print(f"Kamar {KAMAR_BARU_NOMOR} tidak ditemukan - stop.")
        return

    bentrok = await db.bookings.find_one({
        "room_id": kamar_baru["id"], "property_id": PROPERTY_ID,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": "2026-08-20T04:00:00+00:00"},
        "jam_selesai": {"$gt": "2026-08-19T06:00:00+00:00"},
    })
    if bentrok:
        print(f"Kamar {KAMAR_BARU_NOMOR} sudah bentrok dgn booking {bentrok.get('kode')} - stop, tidak ada yang diubah.")
        return

    now = datetime.now(timezone.utc).isoformat()
    catatan_baru = (
        booking.get("catatan", "")
        + " [Dikoreksi 2026-08-19 oleh Claude Code (investigasi diminta Agus): dibatalkan "
          "keliru oleh bug pembatalan-otomatis email modifikasi RedDoorz (tanggal tidak "
          "berubah). Dipindah kamar 10->13 krn kamar 10 sudah terisi tamu RedDoorz lain "
          "(Made Lisyantari, BKO-20260819193756-17AE) selagi bug ini aktif.]"
    )
    result = await db.bookings.update_one(
        {"id": BOOKING_ID, "status": "cancelled"},
        {
            "$set": {
                "status": "aktif",
                "room_id": kamar_baru["id"], "room_nomor": KAMAR_BARU_NOMOR,
                "catatan": catatan_baru,
                "updated_at": now, "updated_by": "claude_code_investigation",
            },
            "$unset": {"cancelled_at": "", "cancelled_by": "", "cancel_reason": ""},
        },
    )
    print(f"update matched={result.matched_count} modified={result.modified_count}")

    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "claude_code_investigation",
        "action": "koreksi_manual_booking_ota",
        "detail": (
            f"Reaktivasi {booking['kode']} (Ayu Santika, no. OTA 444267135972444) - "
            f"dibatalkan keliru oleh bug proses_modifikasi_otomatis (pembatalan terselubung "
            f"salah deteksi, lihat routes/otomasi_email.py:945). Dipindah kamar 10->{KAMAR_BARU_NOMOR} "
            f"krn kamar 10 sudah terisi tamu RedDoorz lain (Made Lisyantari) saat kamar 10 "
            f"sempat kosong akibat bug ini."
        ),
        "entity": KAMAR_BARU_NOMOR, "timestamp": now,
    })
    print("audit_log dicatat. Selesai - Ayu Santika aktif di kamar", KAMAR_BARU_NOMOR)


if __name__ == "__main__":
    asyncio.run(main())
