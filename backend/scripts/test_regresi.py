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
# Unit test murni - _occupies_date (bug nyata 2026-08-15, kasus kamar 9 Pelangi
# tanggal 16 Aug: day-use Fani check-in PAGI 10:30 WITA tanggal 17 Aug membuat kalender
# tampilkan kamar 9 "tersedia" tanggal 16 padahal tidak bisa utk malam 16 - checkout
# menginap 12:00 WITA lebih siang dari day-use masuk. Day-use mulai sebelum 04:00 UTC
# = blokir malam sebelumnya juga, lihat docstring _occupies_date di ketersediaan.py)
# ---------------------------------------------------------------------------

def test_occupies_date_dayuse_pagi_blokir_malam_sebelumnya() -> tuple:
    from routes.ketersediaan import _occupies_date
    from datetime import datetime, timezone
    # Fani: day_use 17 Aug 02:30 UTC (10:30 WITA) -> 08:30 UTC
    start = datetime(2026, 8, 17, 2, 30, tzinfo=timezone.utc)
    end = datetime(2026, 8, 17, 8, 30, tzinfo=timezone.utc)
    # Tanggal 16 (malam sebelumnya) WAJIB terhitung terisi - kasus kamar 9
    t16 = _occupies_date(start, end, datetime(2026, 8, 16).date())
    # Tanggal 17 (hari check-in) tetap terisi
    t17 = _occupies_date(start, end, datetime(2026, 8, 17).date())
    # Tanggal 15 tidak terpengaruh
    t15 = _occupies_date(start, end, datetime(2026, 8, 15).date())
    ok = t16 is True and t17 is True and t15 is False
    return ("occupies_date_dayuse_pagi_blokir_malam_sebelumnya",
            "PASS" if ok else f"FAIL - t16={t16} (harus True), t17={t17} (harus True), t15={t15} (harus False)")


def test_occupies_date_dayuse_siang_tidak_blokir_malam_sebelumnya() -> tuple:
    from routes.ketersediaan import _occupies_date
    from datetime import datetime, timezone
    # Day use mulai 06:00 UTC (14:00 WITA) - SETELAH checkout menginap 12:00 WITA, aman
    start = datetime(2026, 8, 17, 6, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    t16 = _occupies_date(start, end, datetime(2026, 8, 16).date())
    t17 = _occupies_date(start, end, datetime(2026, 8, 17).date())
    ok = t16 is False and t17 is True
    return ("occupies_date_dayuse_siang_tidak_blokir_malam_sebelumnya",
            "PASS" if ok else f"FAIL - t16={t16} (harus False), t17={t17} (harus True)")


def test_occupies_date_menginap_hari_checkout_tidak_terisi() -> tuple:
    from routes.ketersediaan import _occupies_date
    from datetime import datetime, timezone
    # Menginap 15 Aug 06:00 UTC -> 16 Aug 04:00 UTC (checkout 12:00 WITA 16 Aug)
    start = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 16, 4, 0, tzinfo=timezone.utc)
    t15 = _occupies_date(start, end, datetime(2026, 8, 15).date())
    t16 = _occupies_date(start, end, datetime(2026, 8, 16).date())
    ok = t15 is True and t16 is False
    return ("occupies_date_menginap_hari_checkout_tidak_terisi",
            "PASS" if ok else f"FAIL - t15={t15} (harus True), t16={t16} (harus False)")


# ---------------------------------------------------------------------------
# Unit test murni - _booking_date_range (bug nyata 2026-08-15, kasus kamar 9 -
# konsisten dgn fix _occupies_date; public_availability / tool check_availability
# AI pakai fungsi ini, jadi harus sepaham dgn Kalender)
# ---------------------------------------------------------------------------

def test_booking_date_range_dayuse_pagi_blokir_malam_sebelumnya() -> tuple:
    from routes.public import _booking_date_range
    from datetime import datetime, timezone
    # Fani: day_use 17 Aug 02:30 UTC (10:30 WITA) -> 08:30 UTC, pagi.
    # TANPA jam_checkin (cek tanggal umum): blokir malam sebelumnya (16) juga.
    start = datetime(2026, 8, 17, 2, 30, tzinfo=timezone.utc)
    end = datetime(2026, 8, 17, 8, 30, tzinfo=timezone.utc)
    rs, re = _booking_date_range(start, end, jam_checkin_ada=False)
    ok = rs == datetime(2026, 8, 16).date() and re == datetime(2026, 8, 18).date()
    return ("booking_date_range_dayuse_pagi_blokir_malam_sebelumnya",
            "PASS" if ok else f"FAIL - range=({rs}, {re}), harusnya (2026-08-16, 2026-08-18)")


def test_booking_date_range_dayuse_pagi_dengan_jam_checkin_hanya_hari_itu() -> tuple:
    from routes.public import _booking_date_range
    from datetime import datetime, timezone
    # Fani day_use pagi 17 Aug, TAPI tamu sudah sebutkan jam_checkin spesifik (mis. 12:30) -
    # day-use pagi besok TIDAK diperluas ke hari sebelumnya di sini; filter presisi jam
    # (check_room_available) yang menentukan slot mana yang benar-benar bentrok.
    start = datetime(2026, 8, 17, 2, 30, tzinfo=timezone.utc)
    end = datetime(2026, 8, 17, 8, 30, tzinfo=timezone.utc)
    rs, re = _booking_date_range(start, end, jam_checkin_ada=True)
    ok = rs == datetime(2026, 8, 17).date() and re == datetime(2026, 8, 18).date()
    return ("booking_date_range_dayuse_pagi_dengan_jam_checkin_hanya_hari_itu",
            "PASS" if ok else f"FAIL - range=({rs}, {re}), harusnya (2026-08-17, 2026-08-18)")


def test_booking_date_range_dayuse_siang_hanya_hari_itu() -> tuple:
    from routes.public import _booking_date_range
    from datetime import datetime, timezone
    # Day use mulai 06:00 UTC (14:00 WITA) - SETELAH checkout menginap 12:00 WITA, aman
    start = datetime(2026, 8, 17, 6, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    rs, re = _booking_date_range(start, end, jam_checkin_ada=False)
    ok = rs == datetime(2026, 8, 17).date() and re == datetime(2026, 8, 18).date()
    return ("booking_date_range_dayuse_siang_hanya_hari_itu",
            "PASS" if ok else f"FAIL - range=({rs}, {re}), harusnya (2026-08-17, 2026-08-18)")


def test_booking_date_range_menginap() -> tuple:
    from routes.public import _booking_date_range
    from datetime import datetime, timezone
    # Menginap 15 -> 16 (checkout hari 16 tidak menempati)
    start = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 16, 4, 0, tzinfo=timezone.utc)
    rs, re = _booking_date_range(start, end)
    ok = rs == datetime(2026, 8, 15).date() and re == datetime(2026, 8, 16).date()
    return ("booking_date_range_menginap",
            "PASS" if ok else f"FAIL - range=({rs}, {re}), harusnya (2026-08-15, 2026-08-16)")


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


async def skenario_whatsapp_request_dan_walkin_menginap_tidak_hilang() -> tuple:
    """Bug asli (2026-08-25, laporan Agus - "hasil pendapatan berbeda", ditemukan lewat
    audit data asli): SAMA PERSIS insiden whatsapp_auto 2026-08-09, tapi 2 sumber baru
    yang lolos dari fix waktu itu.

    (A) source="whatsapp_request" (nilai ASLI dipakai approve_booking_request/
    otomasi_email, "whatsapp" polos di ONLINE_BOOKING_SOURCES ternyata tidak pernah jadi
    nilai apa pun) - 30 booking asli (Rp5.444.050 sejak 1 Agustus) hilang dari semua
    laporan.

    (B) source="walk_in" tipe menginap (booking Quick Book staf) - checkin_from_booking
    tidak pernah bikin dokumen checkins utk tipe menginap (beda dari day_use), dan
    ONLINE_BOOKING_SOURCES sengaja TIDAK memuat walk_in (perlu tetap exclude di widget
    online-vs-walkin) - 16 booking asli (Rp2.863.850 sejak 2 Agustus) hilang total, tidak
    ada query manapun yang pernah menghitungnya. Fix: MENGINAP_REVENUE_SOURCES terpisah
    (ONLINE_BOOKING_SOURCES + walk_in) dipakai KHUSUS di 3 titik total-pendapatan-
    menginap (bukan di widget perbandingan saluran)."""
    from core import db, now_iso
    from routes.reports import report_daily

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T3")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()

    # Booking A: menginap, whatsapp_request, belum check-in (tidak py checkin_id)
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-WR-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T3",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi WhatsApp Request Menginap",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "whatsapp_request", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "paid_at": now_iso(), "created_at": now_iso(),
    })

    # Booking B: menginap, walk_in (Quick Book staf), sudah checked_in - TIDAK PERNAH py
    # checkin_id/dokumen checkins (beda dari day_use), harus kehitung dari booking ini saja.
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-WI-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T3",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Walk-in Menginap",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "checked_in", "source": "walk_in", "payment_status": "paid",
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "amount_due": 103000,
        "paid_at": now_iso(), "created_at": now_iso(),
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    daily = await report_daily(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_kamar = sum(r["kamar"] for r in daily)
    # A (154500) + B (103000) = 257500. Kalau bug lama balik (salah satu/keduanya hilang
    # lagi): 0, 154500, atau 103000 saja.
    ok = total_kamar == 257500
    status = "PASS" if ok else f"FAIL - total_kamar={total_kamar}, expected=257500 (154500 whatsapp_request + 103000 walk_in menginap)"
    return ("whatsapp_request_dan_walkin_menginap_tidak_hilang", status)


async def skenario_booking_cancelled_masih_paid_tidak_dihitung() -> tuple:
    """Bug KEDUA ditemukan sambil audit fix whatsapp_request/walk_in di atas (2026-08-25,
    permintaan Agus "dalami akar masalahnya, agar semua aman") - arah SEBALIKNYA
    (KELEBIHAN hitung, bukan hilang). 7 booking asli (Rp1.003.000) ditemukan berstatus
    "cancelled" tapi payment_status masih "paid" - beberapa jalur cancel yang beda
    (auto-cancel OTA di otomasi_email.py, koreksi manual/dedup RedDoorz) tidak pernah
    reset payment_status (beda dari cancel_with_fee yang sudah benar set ke refunded/
    forfeited). Query _hitung_pendapatan_harian/report_rooms/report_service_revenue
    SEBELUM ini tidak pernah cek `status` sama sekali - booking cancelled yg kebetulan
    masih payment_status=paid ikut terhitung sbg pendapatan asli.

    Fix root-cause: filter source dihapus TOTAL dari 3 titik itu (allowlist rapuh,
    2x kebobolan - lihat skenario whatsapp_request di atas), diganti "status" != cancelled
    yang sekarang WAJIB ada. Skenario ini: 1 booking menginap "aktif" (harus kehitung) +
    1 booking menginap "cancelled" tapi payment_status="paid" (harus DIABAIKAN)."""
    from core import db, now_iso
    from routes.reports import report_daily

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T4")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()

    # Booking A: menginap, aktif, paid - HARUS kehitung.
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-CA-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T4",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Aktif Paid",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "online", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "paid_at": now_iso(), "created_at": now_iso(),
    })

    # Booking B: menginap, CANCELLED tapi payment_status masih "paid" (jalur cancel yang
    # lupa reset, mis. auto-cancel OTA) - HARUS DIABAIKAN, tidak boleh ikut kehitung.
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-CB-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T4",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Cancelled Masih Paid",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "cancelled", "source": "ota", "payment_status": "paid",
        "subtotal": 300000, "service_fee": 9000, "total": 309000, "amount_due": 309000,
        "paid_at": now_iso(), "created_at": now_iso(), "cancelled_at": now_iso(), "cancelled_by": "ai_email_parser",
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    daily = await report_daily(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_kamar = sum(r["kamar"] for r in daily)
    # A (154500) saja. Kalau bug lama balik (cancelled masih ikut kehitung): 154500+309000=463500.
    ok = total_kamar == 154500
    status = "PASS" if ok else f"FAIL - total_kamar={total_kamar}, expected=154500 (cancelled booking Rp309000 HARUS diabaikan)"
    return ("booking_cancelled_masih_paid_tidak_dihitung", status)


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


async def skenario_estimasi_siap_pada_tanggal_dayuse_pagi() -> tuple:
    """Bug nyata 2026-08-15 (permintaan Agus - kasus kamar 9 tanggal 16 Aug): tamu minta
    Day Use PAGI di tanggal masa depan yang kamarnya masih dipakai Menginap checkout 12:00
    WITA tanggal itu. `estimasi_kamar_siap` LAMA cuma hitung "hari ini" -> None utk tanggal
    masa depan -> AI jawab "penuh" tanpa tawaran jam 12:30. Fungsi baru
    `estimasi_kamar_siap_pada_tanggal` menghitung estimasi dari booking yang checkout-nya
    JATUH pada tanggal diminta (12:00 WITA + buffer 30 menit = siap ~12:30 WITA).

    Skenario: kamar test ada Menginap checked_in checkout besok 04:00 UTC (12:00 WITA).
    Panggil estimasi_kamar_siap_pada_tanggal utk tanggal checkout tsb - harus return
    04:30 UTC (12:30 WITA). Untuk tanggal LAIN (checkout bukan tanggal itu) - harus None."""
    from core import db, now_iso
    from scheduling_engine import estimasi_kamar_siap_pada_tanggal

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T8")
    # Booking Menginap: checkin kemarin, checkout BESOK 04:00 UTC (12:00 WITA), checked_in
    besok = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    lusa = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-ES-{uuid.uuid4().hex[:6].upper()}",
        "property_id": property_id, "room_id": room_id, "room_nomor": "T8",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Estimasi",
        "no_hp": _wa_unik(), "jam_mulai": f"{besok}T06:00:00+00:00", "jam_selesai": f"{lusa}T04:00:00+00:00",
        "status": "checked_in", "source": "whatsapp_auto", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "paid_at": now_iso(), "created_at": now_iso(),
    })

    # estimasi utk tanggal checkout (besok -> lusa checkout 04:00 UTC = 12:00 WITA lusa)
    # Estimasi dihitung utk tanggal checkout = lusa (jam_selesai lusa 04:00 UTC)
    siap = await estimasi_kamar_siap_pada_tanggal(room_id, property_id, lusa)
    ok_lusa = siap is not None and siap.strftime("%H:%M") == "04:30" and siap.date().isoformat() == lusa
    # Tanggal BUKAN checkout (besok, masih checkin) -> None (jangan janji kekosongan palsu)
    siap_besok = await estimasi_kamar_siap_pada_tanggal(room_id, property_id, besok)
    ok_besok = siap_besok is None

    ok = ok_lusa and ok_besok
    status = ("PASS" if ok else
              f"FAIL - estimasi lusa={siap} (harusnya {lusa}T04:30:00+00:00 / 12:30 WITA), "
              f"estimasi besok={siap_besok} (harusnya None - masih checkin, jangan janji kosong)")
    return ("estimasi_siap_pada_tanggal_dayuse_pagi", status)


async def skenario_laporan_pengeluaran_tanggal_penuh_timestamp() -> tuple:
    """Bug nyata 2026-08-18 (laporan Agus - "di tanggal 18 ada pengeluaran tapi tidak ada
    [di Laporan Pengeluaran], tapi di laporan Ringkasan ada"). Root cause: expenses.tanggal
    HAMPIR SELALU timestamp UTC PENUH (create_expense's `body.tanggal or now_iso()` - form
    web Pengeluaran.jsx TIDAK PUNYA input tanggal sama sekali, Telegram bot & payroll juga
    selalu now_iso()), TAPI list_expenses (routes/expenses.py) dulu bandingkan STRING
    MENTAH from_date/to_date ("YYYY-MM-DD" polos dari date picker) langsung ke field itu -
    "2026-08-18T05:24:55+00:00" <= "2026-08-18" itu FALSE scr leksikografis (string lebih
    panjang yg diawali string pembanding dianggap "lebih besar"), jadi SEMUA pengeluaran
    hari itu gagal lolos filter $lte, bukan cuma kasus tepi. Fix: pakai
    wita_date_range_to_utc (pola sama dgn reports.py/laporan_analitik.py).

    Regresi kalau expense dgn tanggal timestamp UTC penuh TIDAK muncul saat difilter
    from_date=to_date=tanggal WITA hari itu."""
    from core import db, now_iso
    from routes.expenses import list_expenses

    property_id = _property_id_test()
    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    tanggal_penuh = now_iso()  # persis pola create_expense: body.tanggal or now_iso()
    tanggal_wita_hari_ini = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")

    await db.expenses.insert_one({
        "id": str(uuid.uuid4()), "tanggal": tanggal_penuh, "kategori": "Belanja Operasional",
        "deskripsi": "Test Regresi Laporan Pengeluaran", "nominal": 25000, "foto_url": "",
        "user": "Test Regresi", "user_id": "test", "created_at": tanggal_penuh,
        "property_id": property_id,
    })

    hasil = await list_expenses(from_date=tanggal_wita_hari_ini, to_date=tanggal_wita_hari_ini,
                                 user=owner, property_id=property_id)
    ok = len(hasil) == 1 and hasil[0]["tanggal"] == tanggal_penuh
    status = ("PASS" if ok else
              f"FAIL - hasil filter from_date=to_date={tanggal_wita_hari_ini!r}: {len(hasil)} item "
              f"(harusnya 1, expense dgn tanggal={tanggal_penuh!r} harus lolos)")
    return ("laporan_pengeluaran_tanggal_penuh_timestamp", status)


async def skenario_rekening_transaksi_tanggal_penuh_timestamp() -> tuple:
    """Bug nyata 2026-08-18 - SAMA AKAR MASALAH dgn Laporan Pengeluaran, ditemukan lewat
    audit lanjutan atas permintaan Agus ("cek juga laporan lainnya"). rekening_transaksi.
    tanggal SELALU timestamp UTC penuh (auto_posting), list_transaksi dulu bandingkan
    string mentah - 13 transaksi nyata tanggal 18 Agustus terkonfirmasi 0 lolos filter
    SEBELUM fix, 13 lolos SESUDAH fix (diverifikasi manual sblm nulis skenario ini)."""
    from core import db, now_iso
    from routes.rekening import list_transaksi

    property_id = _property_id_test()
    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    tanggal_penuh = now_iso()
    tanggal_wita_hari_ini = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")

    await db.rekening_transaksi.insert_one({
        "id": str(uuid.uuid4()), "rekening_id": str(uuid.uuid4()), "jenis": "pemasukan",
        "kategori": "Test Regresi", "deskripsi": "Test Regresi Rekening", "nominal": 50000,
        "tanggal": tanggal_penuh, "created_at": tanggal_penuh, "property_id": property_id,
    })

    hasil = await list_transaksi(rekening_id=None, jenis=None, from_date=tanggal_wita_hari_ini,
                                  to_date=tanggal_wita_hari_ini, user=owner, property_id=property_id)
    ok = len(hasil) == 1 and hasil[0]["tanggal"] == tanggal_penuh
    status = "PASS" if ok else f"FAIL - hasil filter: {len(hasil)} item (harusnya 1)"
    return ("rekening_transaksi_tanggal_penuh_timestamp", status)


async def skenario_checkins_list_jam_checkin_penuh_timestamp() -> tuple:
    """Bug nyata 2026-08-18 - SAMA AKAR MASALAH dgn Laporan Pengeluaran. checkins.
    jam_checkin SELALU timestamp UTC penuh, list_checkins dulu bandingkan string mentah -
    9 checkin nyata tanggal 18 Agustus terkonfirmasi 0 lolos filter SEBELUM fix, 9 lolos
    SESUDAH fix (diverifikasi manual sblm nulis skenario ini)."""
    from core import db, now_iso
    from routes.checkins import list_checkins

    property_id = _property_id_test()
    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    tanggal_penuh = now_iso()
    tanggal_wita_hari_ini = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")

    await db.checkins.insert_one({
        "id": str(uuid.uuid4()), "nama_tamu": "Test Regresi Checkins", "no_hp": _wa_unik(),
        "tipe": "day_use", "status": "aktif", "jam_checkin": tanggal_penuh,
        "jam_checkout": None, "pembayaran": [], "created_at": tanggal_penuh,
        "property_id": property_id,
    })

    hasil = await list_checkins(status=None, from_date=tanggal_wita_hari_ini,
                                 to_date=tanggal_wita_hari_ini, user=owner, property_id=property_id)
    ok = len(hasil) == 1 and hasil[0]["jam_checkin"] == tanggal_penuh
    status = "PASS" if ok else f"FAIL - hasil filter: {len(hasil)} item (harusnya 1)"
    return ("checkins_list_jam_checkin_penuh_timestamp", status)


async def skenario_kasir_list_timestamp_penuh_timestamp() -> tuple:
    """Bug nyata 2026-08-18 - SAMA AKAR MASALAH dgn Laporan Pengeluaran. kasir.timestamp
    SELALU timestamp UTC penuh, list_kasir dulu bandingkan string mentah - 2 transaksi
    kasir nyata tanggal 17 Agustus terkonfirmasi 0 lolos filter SEBELUM fix, 2 lolos
    SESUDAH fix (diverifikasi manual sblm nulis skenario ini)."""
    from core import db, now_iso
    from routes.kasir import list_kasir

    property_id = _property_id_test()
    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    tanggal_penuh = now_iso()
    tanggal_wita_hari_ini = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")

    await db.kasir.insert_one({
        "id": str(uuid.uuid4()), "trx_no": f"TEST-{uuid.uuid4().hex[:6].upper()}",
        "items": [], "total": 20000, "metode_bayar": "tunai",
        "timestamp": tanggal_penuh, "created_at": tanggal_penuh, "property_id": property_id,
    })

    hasil = await list_kasir(from_date=tanggal_wita_hari_ini, to_date=tanggal_wita_hari_ini,
                              user=owner, property_id=property_id)
    ok = len(hasil) == 1 and hasil[0]["timestamp"] == tanggal_penuh
    status = "PASS" if ok else f"FAIL - hasil filter: {len(hasil)} item (harusnya 1)"
    return ("kasir_list_timestamp_penuh_timestamp", status)


async def skenario_services_list_tanggal_penuh_timestamp() -> tuple:
    """Bug nyata 2026-08-18 - SAMA AKAR MASALAH dgn Laporan Pengeluaran. services.tanggal
    SELALU timestamp UTC penuh. Fix SEBELUMNYA di endpoint ini (`to_date + "T23:59:59"`)
    cuma tambal to_date tanpa offset WITA eksplisit, from_date tetap raw - 2 layanan nyata
    tanggal 15 Juli terkonfirmasi 0 lolos filter SEBELUM fix penuh ini, 2 lolos SESUDAH
    (diverifikasi manual sblm nulis skenario ini)."""
    from core import db, now_iso
    from routes.services import list_services

    property_id = _property_id_test()
    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    tanggal_penuh = now_iso()
    tanggal_wita_hari_ini = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")

    await db.services.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-{uuid.uuid4().hex[:6].upper()}",
        "kategori": "Laundry", "deskripsi": "Test Regresi Services", "nominal": 15000,
        "tanggal": tanggal_penuh, "created_at": tanggal_penuh, "property_id": property_id,
    })

    hasil = await list_services(from_date=tanggal_wita_hari_ini, to_date=tanggal_wita_hari_ini,
                                 user=owner, property_id=property_id)
    ok = len(hasil) == 1 and hasil[0]["tanggal"] == tanggal_penuh
    status = "PASS" if ok else f"FAIL - hasil filter: {len(hasil)} item (harusnya 1)"
    return ("services_list_tanggal_penuh_timestamp", status)


async def main():
    unit_tests = [
        test_tanggal_wita_dini_hari_geser_ke_hari_berikutnya,
        test_tanggal_wita_siang_tidak_geser,
        test_tanggal_wita_naive_diasumsikan_sudah_wita,
        test_occupies_date_dayuse_pagi_blokir_malam_sebelumnya,
        test_occupies_date_dayuse_siang_tidak_blokir_malam_sebelumnya,
        test_occupies_date_menginap_hari_checkout_tidak_terisi,
        test_booking_date_range_dayuse_pagi_blokir_malam_sebelumnya,
        test_booking_date_range_dayuse_pagi_dengan_jam_checkin_hanya_hari_itu,
        test_booking_date_range_dayuse_siang_hanya_hari_itu,
        test_booking_date_range_menginap,
    ]
    skenario_list = [
        skenario_dashboard_ringkasan_sinkron,
        skenario_whatsapp_auto_tidak_hilang_dan_tidak_dobel,
        skenario_whatsapp_request_dan_walkin_menginap_tidak_hilang,
        skenario_booking_cancelled_masih_paid_tidak_dihitung,
        skenario_checkout_sync_amount_due,
        skenario_checkout_payment_protection,
        skenario_checkin_dari_booking_day_use_bisa_ditumpuk_menginap,
        skenario_estimasi_siap_pada_tanggal_dayuse_pagi,
        skenario_laporan_pengeluaran_tanggal_penuh_timestamp,
        skenario_rekening_transaksi_tanggal_penuh_timestamp,
        skenario_checkins_list_jam_checkin_penuh_timestamp,
        skenario_kasir_list_timestamp_penuh_timestamp,
        skenario_services_list_tanggal_penuh_timestamp,
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
    # expenses/rekening_transaksi/kasir/services ditambahkan 2026-08-18 (celah nyata
    # ditemukan - skenario tanggal-penuh-timestamp baru insert ke 4 koleksi ini tapi
    # cleanup lama tidak menghapusnya sama sekali, data test bocor permanen ke DB
    # produksi di bawah property_id palsu).
    for coll in ["rooms", "bookings", "checkins", "guests", "issues", "housekeeping_log", "incidents",
                 "expenses", "rekening_transaksi", "kasir", "services"]:
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
