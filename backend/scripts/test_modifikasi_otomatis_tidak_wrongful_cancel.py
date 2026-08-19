"""Regresi proses_modifikasi_otomatis() - bug nyata Ayu Santika (2026-08-19, no. OTA
444267135972444). Email modifikasi RedDoorz dgn tanggal check-in/checkout DAN nama tamu
SAMA PERSIS dgn yang tersimpan di PMS sebelumnya di-anggap "pembatalan terselubung" dan
booking AKTIF tamu yang genuine checkin hari itu langsung dibatalkan otomatis - bug KEDUA
dari heuristik yang sama dalam 10 hari (setelah kasus "DarmaDarma Guest" 2026-08-09).

Fix (routes/otomasi_email.py, cabang tanggal+nama sama persis): tidak pernah auto-cancel
lagi dari sinyal ini - dialihkan ke tinjauan staf (_modifikasi_menunggu_review), pola yang
sudah dipakai utk skenario ambigu lain di fungsi yang sama.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB reports/laporan/checkin-checkout, lihat
CLAUDE.md) - otomasi_email.py TIDAK termasuk cakupan gerbang itu, skrip ini regresi
tambahan khusus. Sama pola AMAN dgn test_reddoorz_matching_property_scoping.py: jalan
in-process langsung ke DB produksi yang sama, data tes di bawah property_id/kode PALSU
berprefix jelas, dibersihkan total di akhir run (sukses maupun gagal). Tidak ada efek
samping nyata (tidak ada Telegram/WA/email).

Jalankan:
    cd backend && venv/bin/python -m scripts.test_modifikasi_otomatis_tidak_wrongful_cancel
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

TEST_PREFIX = "test-modifikasi-otomatis-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PREFIX}-{uuid.uuid4().hex[:8]}"


def _checkin_wita_naive(offset_hari: int = 3) -> tuple:
    """(check_in_naive_wita_str, check_out_naive_wita_str) - format persis output AI Email
    Parser (tanpa offset, standar 14:00/12:00 WITA)."""
    tgl = (datetime.now(timezone.utc) + timedelta(days=offset_hari)).date()
    tgl_out = tgl + timedelta(days=1)
    return f"{tgl.isoformat()}T14:00:00", f"{tgl_out.isoformat()}T12:00:00"


async def _buat_booking_ota_aktif(db, property_id: str, nama_tamu: str, no_reservasi: str,
                                   check_in_naive: str, check_out_naive: str) -> str:
    from routes.otomasi_email import _parse_ota_datetime
    bid = str(uuid.uuid4())
    jam_mulai = _parse_ota_datetime(check_in_naive, "check_in")
    jam_selesai = _parse_ota_datetime(check_out_naive, "check_out")
    await db.bookings.insert_one({
        "id": bid, "kode": f"BKO-TEST-{uuid.uuid4().hex[:8].upper()}",
        "property_id": property_id, "source": "ota", "ota_reservation_no": no_reservasi,
        "status": "aktif", "payment_status": "paid",
        "tipe": "menginap", "room_tipe": "Standard Tes", "room_id": "room-tes-tidak-ada", "room_nomor": "T1",
        "nama_tamu": nama_tamu, "jumlah_tamu": 2,
        "jam_mulai": jam_mulai.isoformat(), "jam_selesai": jam_selesai.isoformat(),
        "catatan": "", "created_at": datetime.now(timezone.utc).isoformat(), "created_by": "test",
    })
    return bid


async def _buat_email_log_test(db, no_reservasi: str) -> str:
    log_id = str(uuid.uuid4())
    await db.email_logs.insert_one({
        "id": log_id, "gmail_message_id": f"test-{uuid.uuid4().hex[:8]}",
        "subjek": "Booking telah dimodifikasi | test", "pengirim": "bookings-indonesia@reddoorz.com",
        "sumber": "RedDoorz", "status": "Diproses", "jenis": "modifikasi",
        "extracted_data": {"no_reservasi": no_reservasi},
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })
    return log_id


async def skenario_tanggal_dan_nama_sama_TIDAK_boleh_auto_cancel() -> tuple:
    """Inti fix - kasus nyata Ayu Santika: email modifikasi dgn tanggal+nama SAMA PERSIS
    HARUS dialihkan ke tinjauan staf, TIDAK PERNAH auto-cancel booking aktif."""
    nama = "tanggal_dan_nama_sama_persis_tidak_auto_cancel"
    from core import db
    from routes.otomasi_email import proses_modifikasi_otomatis

    property_id = _property_id_test()
    no_reservasi = f"TESRES-{uuid.uuid4().hex[:8]}"
    nama_tamu = "Tamu Tes Modifikasi Sama Persis"
    check_in, check_out = _checkin_wita_naive()
    bid, log_id = None, None
    try:
        bid = await _buat_booking_ota_aktif(db, property_id, nama_tamu, no_reservasi, check_in, check_out)
        log_id = await _buat_email_log_test(db, no_reservasi)

        await proses_modifikasi_otomatis(
            log_id,
            {"no_reservasi": no_reservasi, "nama_tamu": nama_tamu, "check_in": check_in, "check_out": check_out},
            "RedDoorz", "Booking telah dimodifikasi | test",
        )

        booking = await db.bookings.find_one({"id": bid})
        log = await db.email_logs.find_one({"id": log_id})

        if booking["status"] == "cancelled":
            return (nama, "FAIL - booking AKTIF ikut dibatalkan otomatis walau tamunya genuine (regresi bug Ayu Santika)")
        if booking["status"] != "aktif":
            return (nama, f"FAIL - status booking jadi '{booking['status']}', harus tetap 'aktif'")
        if booking.get("modifikasi_status") != "menunggu_review":
            return (nama, f"FAIL - modifikasi_status = '{booking.get('modifikasi_status')}', harus 'menunggu_review' (dialihkan ke staf)")
        if log["status"] != "Perlu_Review_Modifikasi":
            return (nama, f"FAIL - status email_log = '{log['status']}', harus 'Perlu_Review_Modifikasi'")
        return (nama, "PASS")
    finally:
        if bid:
            await db.bookings.delete_one({"id": bid})
        if log_id:
            await db.email_logs.delete_one({"id": log_id})


async def skenario_nama_beda_tetap_update_bukan_cancel() -> tuple:
    """Regresi lama (fix 2026-08-09, "DarmaDarma Guest") - pastikan BELUM rusak oleh fix
    baru: tanggal sama tapi nama BEDA -> update nama, bukan cancel, bukan juga
    menunggu_review (auto-resolve, sinyal nama berubah cukup jelas)."""
    nama = "nama_tamu_beda_tetap_update_bukan_cancel_bukan_review"
    from core import db
    from routes.otomasi_email import proses_modifikasi_otomatis

    property_id = _property_id_test()
    no_reservasi = f"TESRES-{uuid.uuid4().hex[:8]}"
    check_in, check_out = _checkin_wita_naive()
    bid, log_id = None, None
    try:
        bid = await _buat_booking_ota_aktif(db, property_id, "Nama Lama Guest", no_reservasi, check_in, check_out)
        log_id = await _buat_email_log_test(db, no_reservasi)

        await proses_modifikasi_otomatis(
            log_id,
            {"no_reservasi": no_reservasi, "nama_tamu": "Nama Baru Sungguhan", "check_in": check_in, "check_out": check_out},
            "RedDoorz", "Booking telah dimodifikasi | test",
        )

        booking = await db.bookings.find_one({"id": bid})
        if booking["status"] != "aktif":
            return (nama, f"FAIL - status jadi '{booking['status']}', harus tetap 'aktif'")
        if booking["nama_tamu"] != "Nama Baru Sungguhan":
            return (nama, f"FAIL - nama_tamu tidak ter-update, masih '{booking['nama_tamu']}'")
        if booking.get("modifikasi_status") == "menunggu_review":
            return (nama, "FAIL - kasus nama beda seharusnya auto-resolve (update_nama_tamu), bukan ikut menunggu_review")
        return (nama, "PASS")
    finally:
        if bid:
            await db.bookings.delete_one({"id": bid})
        if log_id:
            await db.email_logs.delete_one({"id": log_id})


async def skenario_tanggal_beda_tetap_reschedule_otomatis() -> tuple:
    """Regresi jalur normal - tanggal genuinely beda tetap reschedule otomatis (TIDAK
    kena cabang pembatalan-terselubung/menunggu_review sama sekali)."""
    nama = "tanggal_beda_tetap_reschedule_otomatis"
    from core import db
    from routes.otomasi_email import proses_modifikasi_otomatis

    property_id = _property_id_test()
    no_reservasi = f"TESRES-{uuid.uuid4().hex[:8]}"
    nama_tamu = "Tamu Tes Reschedule"
    check_in_lama, check_out_lama = _checkin_wita_naive(offset_hari=3)
    check_in_baru, check_out_baru = _checkin_wita_naive(offset_hari=10)
    bid, log_id = None, None
    try:
        bid = await _buat_booking_ota_aktif(db, property_id, nama_tamu, no_reservasi, check_in_lama, check_out_lama)
        log_id = await _buat_email_log_test(db, no_reservasi)

        await proses_modifikasi_otomatis(
            log_id,
            {"no_reservasi": no_reservasi, "nama_tamu": nama_tamu, "check_in": check_in_baru, "check_out": check_out_baru},
            "RedDoorz", "Booking telah dimodifikasi | test",
        )

        booking = await db.bookings.find_one({"id": bid})
        if booking["status"] != "aktif":
            return (nama, f"FAIL - status jadi '{booking['status']}', harus tetap 'aktif' setelah reschedule")
        if booking.get("modifikasi_status") != "direschedule":
            return (nama, f"FAIL - modifikasi_status = '{booking.get('modifikasi_status')}', harus 'direschedule'")
        if check_in_baru.split("T")[0] not in booking["jam_mulai"]:
            return (nama, f"FAIL - jam_mulai tidak ter-update ke tanggal baru: {booking['jam_mulai']}")
        return (nama, "PASS")
    finally:
        if bid:
            await db.bookings.delete_one({"id": bid})
        if log_id:
            await db.email_logs.delete_one({"id": log_id})


async def main():
    skenario_list = [
        skenario_tanggal_dan_nama_sama_TIDAK_boleh_auto_cancel,
        skenario_nama_beda_tetap_update_bukan_cancel,
        skenario_tanggal_beda_tetap_reschedule_otomatis,
    ]

    print("--- Skenario proses_modifikasi_otomatis (in-process, data test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    from core import db
    r1 = await db.get_collection("bookings").delete_many({"kode": {"$regex": "^BKO-TEST-"}})
    r2 = await db.get_collection("email_logs").delete_many({"gmail_message_id": {"$regex": "^test-"}})
    if r1.deleted_count or r2.deleted_count:
        print(f"cleanup cadangan: {r1.deleted_count} bookings + {r2.deleted_count} email_logs test tersisa dihapus")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
