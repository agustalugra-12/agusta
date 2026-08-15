"""Gerbang Regresi PMS (2026-08-10, permintaan Agus setelah audit pendapatan/tanggal WITA
hari ini menemukan & memperbaiki beberapa bug nyata di /reports/* TANPA ada tes otomatis
yang menjaganya - sama pola dgn Modul 19 "AI Self-Healing" yang sudah ada di ai-chat-bot
[lihat CLAUDE.md repo itu], sekarang dibawa ke PMS.

BEDA dari `tests/` (pytest, butuh SERVER TEST TERPISAH + DB terpisah, lihat conftest.py
- infra itu tidak pernah benar-benar disiapkan di server produksi ini) - skrip ini jalan
LANGSUNG in-process terhadap DB PRODUKSI yang sama (sama pola dgn
ai-chat-bot/scripts/test_hallucination_guards.py), tapi AMAN: semua data tes dibuat di
bawah property_id PALSU (prefix `TEST_PROPERTY_PREFIX`, bukan Pelangi/Harmoni asli) yang
TIDAK PERNAH muncul di property switcher UI manapun - staf/owner tidak akan pernah
melihatnya di Dashboard/Reports asli, walau sempat ada di DB selama tes berjalan. TIAP
skenario pakai property_id UNIK sendiri (bukan 1 konstanta dipakai bersama) - supaya
skenario satu tidak pernah bocor/tercampur ke hitungan skenario lain yang jalan di
percakapan yang sama. Dibersihkan total di akhir `main()` (hapus semua dokumen
ber-property_id berprefix ini), sukses maupun gagal.

Jalankan sebelum push perubahan yang menyentuh /reports/*, /laporan-analitik/*,
checkin/checkout, atau helper tanggal WITA (core.py tanggal_wita/wita_date_range_to_utc):
    cd backend && venv/bin/python -m scripts.test_regresi
Exit code 1 kalau ada FAIL - jangan push/deploy sebelum diperbaiki.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-regresi-pms-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _wa_unik() -> str:
    return "62800" + uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Unit test murni - tanggal_wita (bug nyata 2026-08-09/10, "baris tanggal 31 Juli
# nongol tidak diminta" - lihat commit fix di core.py)
# ---------------------------------------------------------------------------

def test_tanggal_wita_dini_hari_geser_ke_hari_berikutnya() -> tuple:
    from core import tanggal_wita
    # 2026-08-01T19:00:00 UTC = 2026-08-02T03:00:00 WITA (dini hari) - HARUS tanggal 2,
    # bukan iso[:10] mentah yang akan bilang tanggal 1.
    hasil = tanggal_wita("2026-08-01T19:00:00+00:00")
    return ("tanggal_wita_dini_hari_geser_ke_hari_berikutnya", "PASS" if hasil == "2026-08-02" else f"FAIL - hasil: {hasil!r}")


def test_tanggal_wita_siang_tidak_geser() -> tuple:
    # 2026-08-01T10:00:00 UTC = 2026-08-01T18:00:00 WITA (masih sore hari yg sama)
    from core import tanggal_wita
    hasil = tanggal_wita("2026-08-01T10:00:00+00:00")
    return ("tanggal_wita_siang_tidak_geser", "PASS" if hasil == "2026-08-01" else f"FAIL - hasil: {hasil!r}")


def test_tanggal_wita_naive_diasumsikan_sudah_wita() -> tuple:
    from core import tanggal_wita
    hasil = tanggal_wita("2026-08-01")
    return ("tanggal_wita_naive_diasumsikan_sudah_wita", "PASS" if hasil == "2026-08-01" else f"FAIL - hasil: {hasil!r}")


# ---------------------------------------------------------------------------
# Skenario LIVE (in-process, property_id palsu terisolasi - lihat docstring atas)
# ---------------------------------------------------------------------------

async def _bikin_kamar_test(db, property_id: str, nomor: str) -> str:
    room_id = str(uuid.uuid4())
    await db.rooms.insert_one({
        "id": room_id, "property_id": property_id, "nomor": nomor, "tipe": "Standard",
        "tarif": 100000, "tarif_menginap": 150000, "status": "kosong", "info": {},
    })
    return room_id


async def skenario_dashboard_ringkasan_sinkron() -> tuple:
    """Bug asli (2026-08-09): Dashboard (report_summary) & Ringkasan (report_daily)
    pakai formula pendapatan BEDA (paid_at vs akrual malam-inap) - angkanya tidak
    pernah sama. Sekarang keduanya WAJIB memanggil _hitung_pendapatan_harian yang
    sama. Regresi kalau kedua angka berbeda utk rentang tanggal yang sama."""
    from core import db, now_iso
    from routes.reports import report_summary, report_daily

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T1")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    checkin_id = str(uuid.uuid4())
    await db.checkins.insert_one({
        "id": checkin_id, "property_id": property_id, "room_id": room_id, "room_nomor": "T1",
        "room_tipe": "Standard", "nama_tamu": "Test Regresi Sinkron", "no_hp": _wa_unik(),
        "jumlah_tamu": 1, "tarif_dasar": 100000,
        "jam_checkin": now_iso(), "jam_checkout": now_iso(),
        "durasi_jam": 6, "overtime_jam": 0, "biaya_tambahan": 0,
        "subtotal": 100000, "service_fee": 3000, "total": 103000,
        "status": "selesai", "pembayaran": [{"metode": "tunai", "jumlah": 103000}],
        "petugas_checkin": "Test", "petugas_checkin_id": "test", "created_at": now_iso(),
    })
    owner = {"id": "test", "nama": "Test Regresi"}
    summary = await report_summary(user=owner, property_id=property_id)
    daily = await report_daily(from_date=today_wita.isoformat(), to_date=today_wita.isoformat(), user=owner, property_id=property_id)
    total_daily = sum(r["pendapatan"] for r in daily)
    ok = summary["pendapatan_hari_ini"] == total_daily == 103000
    status = "PASS" if ok else f"FAIL - dashboard={summary['pendapatan_hari_ini']}, ringkasan={total_daily}, expected=103000"
    return ("dashboard_ringkasan_sinkron", status)


async def skenario_whatsapp_auto_tidak_hilang_dan_tidak_dobel() -> tuple:
    """Bug asli (2026-08-09): filter source booking online literal ["ota","online",
    "whatsapp"] tidak mencakup "whatsapp_auto" (booking auto-approve AI) - Rp350.200
    booking asli hilang dari laporan. Fix KEDUA yang ditemukan SAAT verifikasi fix
    pertama: booking whatsapp_auto yang SUDAH py checkin_id (day_use yg sudah check-in)
    harus DIKECUALIKAN dari hitungan booking supaya tidak dobel dgn checkins.

    Skenario ini bikin 2 booking whatsapp_auto: (A) menginap, belum checkin_id -> WAJIB
    kehitung dari booking. (B) day_use, SUDAH py checkin_id + checkins doc kembar ->
    WAJIB kehitung PERSIS SEKALI (dari checkins, bukan dari booking lagi)."""
    from core import db, now_iso
    from routes.reports import report_daily

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T2")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()

    # Booking A: menginap, whatsapp_auto, belum check-in (tidak py checkin_id)
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-WA-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T2",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi WA Auto Menginap",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "whatsapp_auto", "payment_status": "paid",
        "subtotal": 200000, "service_fee": 6000, "total": 206000, "amount_due": 206000,
        "paid_at": now_iso(), "created_at": now_iso(),
    })

    # Booking B: day_use, whatsapp_auto, SUDAH checkin_id (linked ke checkins kembar)
    checkin_id_b = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-WB-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T2",
        "room_tipe": "Standard", "tipe": "day_use", "nama_tamu": "Test Regresi WA Auto DayUse",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{today_iso}T12:00:00+00:00",
        "status": "checked_out", "source": "whatsapp_auto", "payment_status": "paid",
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "amount_due": 103000,
        "paid_at": now_iso(), "created_at": now_iso(), "checkin_id": checkin_id_b,
    })
    await db.checkins.insert_one({
        "id": checkin_id_b, "property_id": property_id, "room_id": room_id, "room_nomor": "T2",
        "room_tipe": "Standard", "nama_tamu": "Test Regresi WA Auto DayUse", "no_hp": _wa_unik(),
        "jumlah_tamu": 1, "tarif_dasar": 100000, "jam_checkin": f"{today_iso}T06:00:00+00:00",
        "jam_checkout": f"{today_iso}T12:00:00+00:00", "durasi_jam": 6, "overtime_jam": 0, "biaya_tambahan": 0,
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "status": "selesai",
        "pembayaran": [{"metode": "QRIS", "jumlah": 103000}], "petugas_checkin": "Test", "petugas_checkin_id": "test",
        "created_at": now_iso(), "from_booking_id": None,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    daily = await report_daily(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_kamar = sum(r["kamar"] for r in daily)
    # Booking A (206000, 1 malam - jatuh 1x krn checkin=hari ini) + Booking B via checkins (103000, SEKALI) = 309000.
    # Kalau bug lama balik (whatsapp_auto hilang): 103000 saja. Kalau double-count balik: 412000.
    ok = total_kamar == 309000
    status = "PASS" if ok else f"FAIL - total_kamar={total_kamar}, expected=309000 (206000 menginap whatsapp_auto + 103000 day_use via checkins, SEKALI)"
    return ("whatsapp_auto_tidak_hilang_dan_tidak_dobel", status)


async def skenario_checkout_sync_amount_due() -> tuple:
    """Bug asli (2026-08-09, tamu Harmoni 'I Kadek Adi'): sisa pembayaran cash yang
    dikumpulkan SAAT CHECKOUT tidak pernah disinkronkan balik ke bookings.amount_due -
    booking itu selamanya terlihat "baru DP" di Reservasi walau sudah lunas beneran.
    Regresi kalau amount_due booking TIDAK naik jadi full total setelah checkout()."""
    from core import db, now_iso, CheckinFromBookingBody, CheckoutIn
    from routes.bookings import checkin_from_booking
    from routes.checkins import checkout as do_checkout

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T3")
    owner = {"id": "test", "nama": "Test Regresi"}
    today_iso = datetime.now(timezone.utc).isoformat()

    booking_id = str(uuid.uuid4())
    total = 103000
    dp = 51500
    await db.bookings.insert_one({
        "id": booking_id, "kode": f"TEST-{uuid.uuid4().hex[:8].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T3",
        "room_tipe": "Standard", "tipe": "day_use", "nama_tamu": "Test Regresi Checkout Sync",
        "no_hp": _wa_unik(), "jam_mulai": today_iso, "jam_selesai": today_iso,
        "status": "booking_paid", "source": "whatsapp_auto", "payment_status": "paid",
        "subtotal": 100000, "service_fee": 3000, "total": total, "amount_due": dp,
        "payment_type": "QRIS", "paid_at": today_iso, "created_at": today_iso,
    })

    ci_result = await checkin_from_booking(booking_id, CheckinFromBookingBody(), user=owner, property_id=property_id)
    checkin_id = ci_result["checkin_id"]
    sisa = total - dp
    await do_checkout(checkin_id, CheckoutIn(pembayaran=[{"metode": "tunai", "jumlah": sisa}]), user=owner, property_id=property_id)

    updated = await db.bookings.find_one({"id": booking_id})
    ok = updated.get("amount_due") == total
    status = "PASS" if ok else f"FAIL - amount_due={updated.get('amount_due')}, expected={total} (DP {dp} + sisa cash {sisa} saat checkout)"
    return ("checkout_sync_amount_due", status)


async def skenario_checkout_payment_protection() -> tuple:
    """Fitur baru (2026-08-12, PRD "Owner Control Center" §16, permintaan Agus "blokir
    keras + tombol override owner") - checkout booking yang MASIH ada sisa tagihan
    (setelah dihitung pembayaran yang diinput saat checkout) HARUS ditolak (402) & bikin
    incident "checkout_blocked", KECUALI owner sudah override.

    subtotal SENGAJA dibuat jauh LEBIH KECIL dari total (selisihnya merepresentasikan
    biaya tambahan yang di-set langsung ke booking.total, di luar tarif_dasar/service_fee
    yang dipakai calc_tagihan checkin) - supaya cek checkin-level yang SUDAH ADA (baris
    "Pembayaran extend/overtime kurang", pakai tarif_dasar checkin yang notabene JAUH
    lebih kecil dari total booking sungguhan) langsung LOLOS dari DP saja, dan skenario
    ini betul-betul menguji cek proteksi BARU (booking-level), bukan cuma re-test cek
    lama yang sudah dites skenario checkout_sync_amount_due. Kalau subtotal~=total
    seperti draft pertama fitur ini, cek lama SELALU nembak duluan & cek baru ini tidak
    pernah benar-benar dieksekusi oleh test.

    Regresi kalau (a) checkout yang JELAS belum menutup total booking tetap LOLOS tanpa
    diblokir, ATAU (b) checkout yang SEBENARNYA melunasi total booking malah ke-blokir
    terus-menerus (false positive/deadlock - ini PERSIS bug capping calc["total"] yang
    ditemukan & diperbaiki saat menulis skenario ini sendiri, lihat komentar lengkap di
    routes/checkins.py checkout())."""
    from core import db, now_iso, CheckinFromBookingBody, CheckoutIn
    from routes.bookings import checkin_from_booking
    from routes.checkins import checkout as do_checkout

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T4")
    owner = {"id": "test", "nama": "Test Regresi"}
    today_iso = datetime.now(timezone.utc).isoformat()

    booking_id = str(uuid.uuid4())
    subtotal = 45000  # tarif_dasar checkin - SENGAJA jauh < total (lihat docstring)
    total = 200000    # total booking sungguhan (subtotal + biaya tambahan di luar tarif)
    dp = 50000        # DP > tarif checkin sendiri -> cek checkin-level LOLOS dari DP saja
    await db.bookings.insert_one({
        "id": booking_id, "kode": f"TEST-{uuid.uuid4().hex[:8].upper()}", "property_id": property_id,
        "room_id": room_id, "room_nomor": "T4", "room_tipe": "Standard", "tipe": "day_use",
        "nama_tamu": "Test Regresi Proteksi Checkout", "no_hp": _wa_unik(),
        "jam_mulai": today_iso, "jam_selesai": today_iso, "status": "booking_paid",
        "source": "whatsapp_auto", "payment_status": "paid", "subtotal": subtotal, "service_fee": 1350,
        "total": total, "amount_due": dp, "payment_type": "QRIS", "paid_at": today_iso, "created_at": today_iso,
    })
    ci_result = await checkin_from_booking(booking_id, CheckinFromBookingBody(), user=owner, property_id=property_id)
    checkin_id = ci_result["checkin_id"]

    # (a) Checkout TANPA bayar tambahan sama sekali - cek checkin-level lama LOLOS
    # (DP 50rb > tarif checkin ~46rb), tapi HARUS tetap DITOLAK 402 oleh cek proteksi
    # booking-level yang baru + bikin incident checkout_blocked.
    ditolak_402 = False
    try:
        await do_checkout(checkin_id, CheckoutIn(pembayaran=[]), user=owner, property_id=property_id)
    except Exception as e:
        ditolak_402 = getattr(e, "status_code", None) == 402
    if not ditolak_402:
        return ("checkout_payment_protection", "FAIL - checkout yg TIDAK menutup total booking LOLOS (harusnya ditolak 402 oleh cek booking-level baru)")
    incident = await db.incidents.find_one({"dedup_key": f"checkout_blocked:{checkin_id}", "status": "open"})
    if not incident:
        return ("checkout_payment_protection", "FAIL - checkout ditolak tapi TIDAK ADA incident checkout_blocked dibuat")

    # (b) Checkout dgn bayar CUKUP utk melunasi total booking sungguhnya (bukan cuma
    # tarif checkin) - harus LOLOS, BUKAN macet permanen (ini persis bug capping
    # calc["total"] yg ditemukan: sebelum fix, proyeksi amount_due tidak pernah bisa
    # lebih dari ~46rb walau dibayar penuh, jadi checkout MUSTAHIL lolos). checkin_id
    # yang SAMA dipakai ulang (checkout (a) gagal -> checkin TETAP status "aktif").
    sisa = total - dp
    lolos = False
    try:
        await do_checkout(checkin_id, CheckoutIn(pembayaran=[{"metode": "tunai", "jumlah": sisa}]), user=owner, property_id=property_id)
        lolos = True
    except Exception as e:
        lolos = False
        gagal_detail = str(getattr(e, "detail", e))
    if not lolos:
        return ("checkout_payment_protection", f"FAIL - checkout dgn pembayaran yg MELUNASI total booking tetap ditolak (false positive/deadlock): {gagal_detail}")
    updated_booking = await db.bookings.find_one({"id": booking_id})
    if updated_booking.get("status") != "checked_out":
        return ("checkout_payment_protection", f"FAIL - booking status={updated_booking.get('status')}, expected checked_out")

    # Cleanup incident test (booking/room/checkins ikut dibersihkan main() via property_id prefix)
    await db.incidents.delete_many({"meta.checkin_id": checkin_id})
    return ("checkout_payment_protection", "PASS")


async def skenario_checkin_dari_booking_day_use_bisa_ditumpuk_menginap() -> tuple:
    """Bug nyata 2026-08-15 (kasus RedDoorz I Komang Budiana kamar 17 & Indah Inda kamar
    6 - keduanya TOLAK auto-booking & harus di-override manual owner "tumpuk day use ->
    menginap"): `check_room_available()` (reservation_service.py) memperlakukan checkin
    yang DITURUNKAN dari booking Day Use (`from_booking_id` ada) sebagai walk-in murni &
    mengestimasi selesainya `jam_checkin + 6 jam`, padahal booking asalnya sudah punya
    `jam_selesai` PASTI (mis. Day Use Oka: booking selesai 17:00 WITA tapi estimasi
    checkin 11:37 WITA + 6 jam = 17:37 WITA - salah 37 menit). Akibatnya kamar Day Use
    yang sudah selesai terjadwal tetap diblokir 37+ menit lebih lama utk booking Menginap
    OTA yang baru masuk.

    Skenario: bikin booking Day Use yg sudah di-check-in (checkin dari booking, punya
    from_booking_id & booking jam_selesai presisi) di kamar test. Lalu cek kamar utk
    booking Menginap OTA baru: (A) jam mulai STANDAR OTA (14:00 WITA = 06:00 UTC) - kalau
    day use berakhir sebelum itu, harus TERSEDIA; (B) kalau day use berakhir lebih siang,
    jam mulai DIGESER ke jam_selesai + buffer 30 menit harus TERSEDIA (bukan ditolak).
    Regresi kalau salah satu TIDAK tersedia padahal jendela yang dicek sudah bebas dari
    day use."""
    from core import db, now_iso
    from reservation_service import check_room_available

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T7")
    bk_du_id = str(uuid.uuid4())
    ck_id = str(uuid.uuid4())
    # Booking Day Use: selesai 08:00 UTC (16:00 WITA) - presisi, jadwal PASTI
    await db.bookings.insert_one({
        "id": bk_du_id, "kode": f"TEST-DU-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T7",
        "room_tipe": "Standard", "tipe": "day_use", "nama_tamu": "Test Regresi DayUse Dari Booking",
        "no_hp": _wa_unik(), "jam_mulai": "2026-08-20T02:00:00+00:00", "jam_selesai": "2026-08-20T08:00:00+00:00",
        "status": "checked_in", "source": "whatsapp_auto", "payment_status": "paid",
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "amount_due": 103000,
        "paid_at": now_iso(), "created_at": now_iso(),
    })
    # Checkin dari booking tsb (from_booking_id ada) - SEBELUM fix, estimasi +6 jam dari
    # jam_checkin 04:00 UTC = 10:00 UTC, padahal booking selesai 08:00 UTC.
    await db.checkins.insert_one({
        "id": ck_id, "property_id": property_id, "room_id": room_id, "room_nomor": "T7",
        "room_tipe": "Standard", "nama_tamu": "Test Regresi DayUse Dari Booking", "no_hp": _wa_unik(),
        "jumlah_tamu": 1, "tarif_dasar": 100000, "jam_checkin": "2026-08-20T04:00:00+00:00",
        "jam_checkout": None, "durasi_jam": 6, "overtime_jam": 0, "biaya_tambahan": 0,
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "status": "aktif",
        "from_booking_id": bk_du_id, "from_booking_kode": "TEST-DU-001",
        "pembayaran": [{"metode": "tunai", "jumlah": 103000}],
        "petugas_checkin": "Test", "petugas_checkin_id": "test", "created_at": now_iso(),
    })

    # Booking Menginap OTA baru, check-in 14:00 WITA (06:00 UTC), checkout 12:00 WITA besok
    mulai = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)   # 14:00 WITA
    selesai = datetime(2026, 8, 21, 4, 0, tzinfo=timezone.utc)  # 12:00 WITA besok

    # Kasus B: day use selesai 08:00 UTC, mulai digeser ke 08:00 + 30 menit = 08:30 UTC
    # -> harus TERSEDIA (SEBELUM fix: estimasi checkin +6 jam = 10:00 UTC, jadi 08:30
    # ditolak walau day use sudah selesai).
    mulai_digeser = datetime(2026, 8, 20, 8, 30, tzinfo=timezone.utc)
    try:
        await check_room_available(room_id, mulai_digeser, selesai, property_id)
        ok_b = True
        err_b = None
    except Exception as e:
        ok_b = False
        err_b = str(e)

    status = "PASS" if ok_b else f"FAIL - kamar Day Use dari booking diblokir berlebihan saat mulai digeser ke {mulai_digeser.isoformat()} (harusnya tersedia, day use sudah selesai): {err_b}"
    return ("checkin_dari_booking_day_use_bisa_ditumpuk_menginap", status)


async def main():
    unit_tests = [
        test_tanggal_wita_dini_hari_geser_ke_hari_berikutnya,
        test_tanggal_wita_siang_tidak_geser,
        test_tanggal_wita_naive_diasumsikan_sudah_wita,
    ]
    skenario_list = [
        skenario_dashboard_ringkasan_sinkron,
        skenario_whatsapp_auto_tidak_hilang_dan_tidak_dobel,
        skenario_checkout_sync_amount_due,
        skenario_checkout_payment_protection,
        skenario_checkin_dari_booking_day_use_bisa_ditumpuk_menginap,
    ]

    print("--- Unit test (murni, tanpa DB) ---")
    hasil_unit = []
    for t in unit_tests:
        nama, status = t()
        hasil_unit.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    print("\n--- Skenario LIVE (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup TOTAL - hapus semua dokumen ber-property_id berprefix test ini (tiap
    # skenario punya property_id UNIK sendiri, lihat _property_id_test()), sukses
    # maupun gagal.
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    for coll in ["rooms", "bookings", "checkins", "guests", "issues", "housekeeping_log", "incidents"]:
        r = await db.get_collection(coll).delete_many({"property_id": prop_pattern})
        if r.deleted_count:
            print(f"cleanup: {r.deleted_count} dokumen {coll} test dihapus")

    semua = hasil_unit + hasil_skenario
    gagal = [h for h in semua if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(semua) - len(gagal)}/{len(semua)} PASS ===")
    if gagal:
        print("ADA REGRESI - jangan deploy sebelum ini diperbaiki:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
