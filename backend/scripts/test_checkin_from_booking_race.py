"""Regresi TOCTOU/atomicity untuk `checkin_from_booking` (2026-08-14, temuan #2 audit
arsitektur/risiko - MEDIUM). Bug class yang SAMA PERSIS sudah pernah jadi insiden nyata
di jalur walk-in `/checkins` (2026-08-05, lihat komentar `checkins.py:82` - dashboard
tampil "3 kamar overtime" tapi isinya kamar SAMA x3, root cause: klaim kamar TIDAK
atomic, cek status "kosong" [read] terpisah dari tulis status baru [write], 2 request
nyaris bersamaan sama-sama lolos cek sebelum salah satu sempat menulis). Fix atomic-nya
(`find_one_and_update` dgn status="kosong" di FILTER yang sama dgn update) sudah dipasang
di `checkins.py` sejak insiden itu, tapi TIDAK IKUT dipasang di `checkin_from_booking`
(`routes/bookings.py`) - jalur LAIN yang sama-sama menandai kamar terisi (dipakai OTA/
Quick-Book/booking online). Celah TOCTOU yang sama berpotensi masih ada di sana sebelum
fix ini.

Skenario di bawah menembak race SUNGGUHAN (bukan cuma sekuensial) - 2 panggilan
`checkin_from_booking` ke booking YANG SAMA di-fire BARENGAN lewat `asyncio.gather` (motor
async driver benar-benar mengirim 2 operasi ke MongoDB nyaris bersamaan, bukan simulasi).
Sebelum fix: race ini bisa membuat SISI-EFEK DOBEL (dokumen `checkins` day_use dobel,
`total_transaksi` tamu ke-`$inc` dua kali utk menginap - uang tercatat dobel). Setelah
fix: HARUS persis 1 dari 2 panggilan sukses (`ok: True`), yang lain HARUS gagal dgn
HTTPException 400 (kamar sudah diklaim), dan sisi-efeknya (dokumen checkins / kenaikan
total_transaksi) HARUS terjadi tepat SEKALI, tidak dua kali.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB reports/laporan/checkin-checkout,
lihat CLAUDE.md - skrip INI sendiri TERMASUK cakupan checkin-checkout, jadi WAJIB
dijalankan sebelum push perubahan ini, TAPI skrip ini sendiri bukan bagian test_regresi.py
- dijalankan terpisah). Sama pola AMAN dgn skrip regresi lain malam ini: in-process
langsung ke DB produksi yang sama, semua data tes di bawah property_id PALSU (prefix di
bawah) dan dibersihkan total di akhir run, sukses maupun gagal.

Jalankan:
    cd backend && venv/bin/python -m scripts.test_checkin_from_booking_race
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-checkin-race-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _user_test() -> dict:
    return {"id": str(uuid.uuid4()), "nama": "Staf Tes Regresi", "role": "staff"}


async def _setup_room_dan_booking(db, property_id: str, tipe: str) -> tuple:
    room_id = str(uuid.uuid4())
    await db.rooms.insert_one({
        "id": room_id, "property_id": property_id,
        "nomor": "TES-1", "tipe": "Standard Tes",
        "tarif": 150000, "tarif_menginap": 300000,
        "status": "kosong", "info": {},
    })
    jam_mulai = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    bid = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": bid, "property_id": property_id,
        "kode": f"BKO-TEST-{uuid.uuid4().hex[:8].upper()}",
        "room_id": room_id, "room_nomor": "TES-1", "room_tipe": "Standard Tes",
        "tipe": tipe, "status": "aktif",
        "nama_tamu": "Tamu Tes Race Checkin", "no_hp": "62800" + uuid.uuid4().hex[:8],
        "no_identitas": "", "kendaraan": "", "jumlah_tamu": 1,
        "jam_mulai": jam_mulai,
        "subtotal": 150000, "service_fee": 0, "total": 150000,
        "amount_due": 150000, "payment_status": "paid", "payment_type": "online",
        "source": "test",
    })
    return room_id, bid


async def _cleanup(db, property_id: str, room_id: str, bid: str):
    await db.bookings.delete_many({"id": bid})
    await db.rooms.delete_many({"id": room_id})
    await db.checkins.delete_many({"from_booking_id": bid})
    await db.guests.delete_many({"property_id": property_id})


async def skenario_race_2_checkin_bersamaan_cuma_1_menang() -> tuple:
    """Inti fix: 2 checkin_from_booking() ke booking SAMA, di-fire BARENGAN. Cuma 1 boleh
    sukses, yang lain HARUS ditolak (bukan dua-duanya sukses / dua-duanya bikin sisi-efek)."""
    nama = "race_2_checkin_bersamaan_ke_booking_sama_cuma_1_menang_klaim_kamar"
    from core import db
    from routes.bookings import checkin_from_booking
    from core import CheckinFromBookingBody

    property_id = _property_id_test()
    room_id, bid = await _setup_room_dan_booking(db, property_id, "day_use")
    user = _user_test()
    body = CheckinFromBookingBody()

    try:
        hasil = await asyncio.gather(
            checkin_from_booking(bid, body, user, property_id),
            checkin_from_booking(bid, body, user, property_id),
            return_exceptions=True,
        )

        sukses = [h for h in hasil if isinstance(h, dict) and h.get("ok")]
        gagal = [h for h in hasil if not (isinstance(h, dict) and h.get("ok"))]

        if len(sukses) != 1:
            return (nama, f"FAIL - {len(sukses)} panggilan sukses (harus persis 1): {hasil!r}")
        if len(gagal) != 1:
            return (nama, f"FAIL - {len(gagal)} panggilan gagal (harus persis 1)")
        exc = gagal[0]
        from fastapi import HTTPException
        if not isinstance(exc, HTTPException) or exc.status_code != 400:
            return (nama, f"FAIL - panggilan kalah harus HTTPException 400 (kamar sudah diklaim), dapat: {exc!r}")

        # Sisi-efek HARUS tepat 1x, bukan dobel - inti dari kenapa race ini berbahaya
        # (day_use: dokumen checkins dobel; kalau tipe menginap, total_transaksi ke-$inc 2x).
        jumlah_checkin_doc = await db.checkins.count_documents({"from_booking_id": bid})
        if jumlah_checkin_doc != 1:
            return (nama, f"FAIL - dokumen checkins utk booking ini = {jumlah_checkin_doc}, harus 1 (race bikin dobel side-effect)")

        room_akhir = await db.rooms.find_one({"id": room_id})
        if room_akhir.get("status") != "day_use":
            return (nama, f"FAIL - status kamar akhir = {room_akhir.get('status')!r}, harus 'day_use' (bukan nyangkut di '_checkin_pending')")

        booking_akhir = await db.bookings.find_one({"id": bid})
        if booking_akhir.get("status") != "checked_in":
            return (nama, f"FAIL - status booking akhir = {booking_akhir.get('status')!r}, harus 'checked_in'")

        return (nama, "PASS")
    finally:
        await _cleanup(db, property_id, room_id, bid)


async def skenario_retry_setelah_sukses_ditolak_bukan_dobel_checkin() -> tuple:
    """Guard sekunder (sekuensial, bukan konkuren) - setelah 1 checkin sukses, panggilan
    checkin_from_booking BERIKUTNYA ke booking yang SAMA (mis. staf klik tombol lagi
    setelah sukses, atau retry network) harus ditolak 400 "tidak bisa di-check-in" krn
    booking sudah bukan booking_paid/aktif lagi - guard status booking lama TETAP jalan,
    fix atomic ini menambah lapis proteksi kamar, bukan menggantikan guard status booking."""
    nama = "retry_setelah_sukses_ditolak_krn_booking_sudah_checked_in"
    from core import db
    from routes.bookings import checkin_from_booking
    from core import CheckinFromBookingBody
    from fastapi import HTTPException

    property_id = _property_id_test()
    room_id, bid = await _setup_room_dan_booking(db, property_id, "menginap")
    user = _user_test()
    body = CheckinFromBookingBody()

    try:
        hasil_1 = await checkin_from_booking(bid, body, user, property_id)
        if not hasil_1.get("ok"):
            return (nama, f"FAIL - panggilan pertama harus sukses: {hasil_1!r}")

        try:
            await checkin_from_booking(bid, body, user, property_id)
            return (nama, "FAIL - panggilan kedua (retry) harus ditolak HTTPException, malah sukses (double check-in)")
        except HTTPException as e:
            if e.status_code != 400:
                return (nama, f"FAIL - status code panggilan kedua = {e.status_code}, harus 400")

        guest = await db.guests.find_one({"property_id": property_id, "no_hp": {"$exists": True}})
        if guest and guest.get("total_transaksi", 0) != 150000:
            return (nama, f"FAIL - total_transaksi tamu = {guest.get('total_transaksi')}, harus 150000 (bukan 2x dari retry)")

        return (nama, "PASS")
    finally:
        await _cleanup(db, property_id, room_id, bid)


async def main():
    skenario_list = [
        skenario_race_2_checkin_bersamaan_cuma_1_menang,
        skenario_retry_setelah_sukses_ditolak_bukan_dobel_checkin,
    ]

    print("--- Skenario race-condition checkin_from_booking (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup cadangan (skenario sudah cleanup masing-masing, ini jaring pengaman kalau ada
    # exception sebelum sempat cleanup).
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    r1 = await db.get_collection("bookings").delete_many({"property_id": prop_pattern})
    r2 = await db.get_collection("rooms").delete_many({"property_id": prop_pattern})
    r3 = await db.get_collection("checkins").delete_many({"property_id": prop_pattern})
    r4 = await db.get_collection("guests").delete_many({"property_id": prop_pattern})
    sisa = r1.deleted_count + r2.deleted_count + r3.deleted_count + r4.deleted_count
    if sisa:
        print(f"cleanup cadangan: {sisa} dokumen test tersisa dihapus")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
