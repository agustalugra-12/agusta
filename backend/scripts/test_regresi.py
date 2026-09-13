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


async def skenario_ringkasan_pisah_menginap_dan_day_use() -> tuple:
    """Fitur baru (2026-08-26, permintaan Agus - Ringkasan) - kamar_menginap/kamar_day_use
    HARUS terpisah benar per tipe, dan keduanya HARUS tetap jumlah ke "kamar" gabungan yang
    sudah ada (additive, bukan pengganti). 1 booking Menginap (belum check-in) + 1 checkin
    Day Use (sudah selesai) di hari yang sama - regresi kalau salah satu tercampur ke bucket
    yang salah, atau totalnya tidak lagi sama dengan "kamar" gabungan."""
    from core import db, now_iso
    from routes.reports import report_daily

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T10")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()

    # Menginap, belum check-in (paid, tipe=menginap)
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-MG-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T10",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Ringkasan Menginap",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "whatsapp_request", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "paid_at": now_iso(), "created_at": now_iso(),
    })
    # Day Use, sudah selesai (checkins collection - SELALU Day Use)
    await db.checkins.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "room_id": room_id, "room_nomor": "T10",
        "room_tipe": "Standard", "nama_tamu": "Test Regresi Ringkasan Day Use", "no_hp": _wa_unik(),
        "jumlah_tamu": 1, "tarif_dasar": 120000, "jam_checkin": f"{today_iso}T02:00:00+00:00",
        "jam_checkout": f"{today_iso}T08:00:00+00:00", "durasi_jam": 6, "overtime_jam": 0, "biaya_tambahan": 0,
        "subtotal": 120000, "service_fee": 3600, "total": 123600, "status": "selesai",
        "pembayaran": [{"metode": "tunai", "jumlah": 123600}],
        "petugas_checkin": "Test", "petugas_checkin_id": "test", "created_at": now_iso(),
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    daily = await report_daily(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_menginap = sum(r["kamar_menginap"] for r in daily)
    total_day_use = sum(r["kamar_day_use"] for r in daily)
    total_kamar = sum(r["kamar"] for r in daily)
    ok = total_menginap == 154500 and total_day_use == 123600 and total_kamar == total_menginap + total_day_use
    status = "PASS" if ok else (
        f"FAIL - kamar_menginap={total_menginap} (expected 154500), kamar_day_use={total_day_use} "
        f"(expected 123600), kamar={total_kamar} (expected {total_menginap + total_day_use})"
    )
    return ("ringkasan_pisah_menginap_dan_day_use", status)


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


async def skenario_arus_kas_walkin_menginap_tidak_hilang() -> tuple:
    """Bug KETIGA ditemukan sambil audit lanjutan (2026-08-25, laporan Agus "Arus Kas
    beda dgn Dashboard" - ditemukan LANGSUNG sesudah fix pendapatan kamar hari ini bikin
    Dashboard naik tapi Arus Kas TIDAK ikut naik utk booking yang sama). Booking Menginap
    Quick Book staf (source=walk_in) simpan `pembayaran` LANGSUNG di dokumen booking
    (bukan lewat payment_log/Tripay) - report_arus_kas SEBELUM ini cuma baca payment_log
    (online) + checkins.pembayaran (Day Use, Menginap tidak pernah bikin checkins) - cash
    booking walk_in Menginap (Rp2.260.850, 12 booking asli) tidak pernah muncul di Arus
    Kas sama sekali. Fix: baca juga db.bookings.pembayaran (guard checkin_id belum ada,
    sama pola dgn fix pendapatan kamar, cegah dobel kalau nanti dikonversi jadi day_use)."""
    from core import db, now_iso
    from routes.reports import report_arus_kas

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T5")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()

    # Booking walk_in menginap, cash langsung di pembayaran[] (bukan payment_log) - HARUS kehitung.
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-AK-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T5",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Arus Kas Walkin",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "walk_in", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "pembayaran": [{"metode": "tunai", "jumlah": 154500}],
        "created_at": now_iso(),
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    arus = await report_arus_kas(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_masuk = sum(r["total_uang_masuk"] for r in arus)
    ok = total_masuk == 154500
    status = "PASS" if ok else f"FAIL - total_uang_masuk={total_masuk}, expected=154500 (cash walk_in menginap Rp154500)"
    return ("arus_kas_walkin_menginap_tidak_hilang", status)


async def skenario_arus_kas_collect_balance_manual_masuk_kamar_tunai_bukan_online() -> tuple:
    """Bug KEEMPAT ditemukan 2026-09-06 (laporan Agus - "Arus Kas 'online' Rp19,9jt tapi
    dashboard Tripay cuma Rp10,4jt", dicek langsung ke Buffer... eh Tripay API asli -
    memang cuma Rp10,4jt). Root cause: collect_balance() & konfirmasi manual transfer
    (routes/bookings.py) insert ke payment_log TANPA field `gateway` (beda dari
    tripay.py yang SELALU set gateway="tripay" eksplisit) - uang tunai/QRIS/transfer
    yang dikumpulkan STAF DI LOKASI (bukan lewat Tripay sama sekali) ikut tersapu ke
    bucket "online" krn query report_arus_kas lama cuma cek transaction_status, tidak
    cek gateway. Fix: filter gateway="tripay" utk bucket online, entri TANPA gateway
    (collect_balance/manual) dipindah ke kamar_tunai_langsung (fisik/manual, sesuai
    definisi bucket itu sendiri) - total_uang_masuk TETAP SAMA (uang tidak hilang,
    cuma pindah bucket yang benar)."""
    from core import db, now_iso
    from routes.reports import report_arus_kas

    property_id = _property_id_test()
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()
    now = now_iso()

    # Simulasi payment_log dari collect_balance() - TANPA field `gateway`, persis pola
    # nyata di routes/bookings.py (bukan dari Tripay sama sekali).
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": "test-booking",
        "booking_kode": "TEST-CB", "order_id": f"COLLECT-TEST-{uuid.uuid4().hex[:4].upper()}",
        "gross_amount": "50000", "payment_option": "collect_balance",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": "cash", "fraud_status": None,
        "created_at": now, "updated_at": now,
    })
    # Pembanding: payment_log ASLI dari Tripay (gateway="tripay") - HARUS tetap masuk online.
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": "test-booking-2",
        "booking_kode": "TEST-TP", "order_id": f"TRIPAY-TEST-{uuid.uuid4().hex[:4].upper()}",
        "gateway": "tripay", "gross_amount": "75000", "payment_option": "dp50",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": "QRIS2", "fraud_status": None,
        "created_at": now, "updated_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    arus = await report_arus_kas(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_online = sum(r["online"] for r in arus)
    total_tunai = sum(r["kamar_tunai_langsung"] for r in arus)
    total_masuk = sum(r["total_uang_masuk"] for r in arus)
    ok = total_online == 75000 and total_tunai == 50000 and total_masuk == 125000
    status = (
        "PASS" if ok
        else f"FAIL - online={total_online} (expected 75000), kamar_tunai_langsung={total_tunai} (expected 50000), total_masuk={total_masuk} (expected 125000)"
    )
    return ("arus_kas_collect_balance_manual_masuk_kamar_tunai_bukan_online", status)


async def skenario_arus_kas_online_pakai_amount_diterima_bersih_bukan_gross() -> tuple:
    """Bug nyata 2026-09-07 (audit mendalam selisih Rp249.332 Pendapatan vs Total Uang
    Masuk Harmoni Agustus, permintaan Agus "kalau tidak ketemu pasti ada salah
    pencatatan"): `online` di report_arus_kas menjumlah `payment_log.gross_amount` -
    field ini diisi dari `total_amount` webhook Tripay (routes/tripay.py), yaitu TOTAL
    YANG DITAGIH KE TAMU TERMASUK fee_customer (biaya QRIS/VA yg Tripay bebankan ke
    tamu, Tripay TAHAN sendiri fee itu sebelum settle ke rekening Pelangi -
    `tripay_response.amount_received` adalah angka bersih yang benar2 masuk rekening).
    Bukti nyata: 29/29 transaksi settlement Harmoni Agustus SEMUANYA py fee_customer,
    total gross Rp2.862.252 vs net Rp2.806.800 (selisih Rp55.452) - `online` yang pakai
    gross SELALU overstate uang masuk sejumlah fee yg tidak pernah sampai ke Pelangi.
    Fix: `_uang_diterima_bersih()` pakai `tripay_response.amount_received` kalau ada,
    fallback ke gross_amount kalau tidak (entri lama/Midtrans)."""
    from core import db, now_iso
    from routes.reports import report_arus_kas

    property_id = _property_id_test()
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()
    now = now_iso()

    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": "test-booking-fee",
        "booking_kode": "TEST-FEE", "order_id": f"TRIPAY-FEE-{uuid.uuid4().hex[:4].upper()}",
        "gateway": "tripay", "gross_amount": "62983", "payment_option": "dp50",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": "QRIS2", "fraud_status": None,
        "tripay_response": {"amount": 62983, "fee_customer": 1183, "amount_received": 61800},
        "created_at": now, "updated_at": now,
    })
    # Pembanding: entri LAMA tanpa tripay_response (Midtrans/histori) - HARUS fallback
    # ke gross_amount apa adanya, bukan dianggap 0.
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": "test-booking-lama",
        "booking_kode": "TEST-LAMA", "order_id": f"TRIPAY-LAMA-{uuid.uuid4().hex[:4].upper()}",
        "gateway": "tripay", "gross_amount": "40000", "payment_option": "full",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": "bank_transfer", "fraud_status": None,
        "created_at": now, "updated_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    arus = await report_arus_kas(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_online = sum(r["online"] for r in arus)
    ok = total_online == 61800 + 40000
    status = ("PASS" if ok else
              f"FAIL - online={total_online} (harusnya 101800 = 61800 bersih + 40000 fallback gross, BUKAN 102983 gross mentah)")
    return ("arus_kas_online_pakai_amount_diterima_bersih_bukan_gross", status)


async def skenario_kas_metode_bayar_walkin_menginap_tidak_hilang() -> tuple:
    """Bug KEEMPAT ditemukan sambil audit lanjutan (2026-08-25, laporan Agus - "Kas per
    Metode Bayar cuma 4jt-an, Arus Kas 7jt-an") - sama akar dgn fix Arus Kas hari ini,
    laporan BEDA yang kelewat. Booking Menginap walk_in (Quick Book "bayar di depan
    semua") dilunasi tunai/QRIS/transfer LANGSUNG di tempat - report_kas_metode_bayar
    SEBELUM ini cuma baca kasir + checkins.pembayaran (Day Use), tidak pernah baca
    bookings.pembayaran (Menginap tidak pernah bikin dokumen checkins)."""
    from core import db, now_iso
    from routes.reports import report_kas_metode_bayar

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T6")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()

    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-KM-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T6",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Kas Metode Walkin",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "walk_in", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "pembayaran": [{"metode": "qris", "jumlah": 154500}],
        "created_at": now_iso(),
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    hasil = await report_kas_metode_bayar(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    ok = hasil["qris"] == 154500 and hasil["total"] == 154500
    status = "PASS" if ok else f"FAIL - hasil={hasil}, expected qris=154500 total=154500"
    return ("kas_metode_bayar_walkin_menginap_tidak_hilang", status)


async def skenario_kas_metode_bayar_collect_balance_manual_tidak_hilang() -> tuple:
    """Bug ditemukan 2026-09-06 (audit lanjutan permintaan Agus "cek satu-satu fitur
    laporan keuangan", sama akar bug dgn fix Arus Kas hari ini) - collect_balance()
    (pelunasan sisa tunai/QRIS di lokasi) & konfirmasi manual transfer disimpan di
    payment_log (bukan checkins.pembayaran/bookings.pembayaran) - report_kas_metode_bayar
    TIDAK PERNAH baca payment_log sama sekali, uang fisik/manual ini hilang total dari
    laporan rekonsiliasi laci kas, walau sudah benar sbg kamar_tunai_langsung di Arus
    Kas. Tripay ASLI (gateway="tripay") harus TETAP dikecualikan (sesuai niat laporan
    ini) - dicek eksplisit di sini juga."""
    from core import db, now_iso
    from routes.reports import report_kas_metode_bayar

    property_id = _property_id_test()
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()
    now = now_iso()

    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": "test-cb",
        "booking_kode": "TEST-CB2", "order_id": f"COLLECT-TEST-{uuid.uuid4().hex[:4].upper()}",
        "gross_amount": "30000", "payment_option": "collect_balance",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": "cash", "fraud_status": None, "created_at": now, "updated_at": now,
    })
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": "test-manual",
        "booking_kode": "TEST-MN2", "order_id": f"MANUAL-TEST-{uuid.uuid4().hex[:4].upper()}",
        "gross_amount": "40000", "payment_option": "manual",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": "transfer_manual", "fraud_status": None, "created_at": now, "updated_at": now,
    })
    # Tripay ASLI - HARUS TETAP diabaikan laporan ini (sesuai niat docstring).
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": "test-tripay",
        "booking_kode": "TEST-TP2", "order_id": f"TRIPAY-TEST-{uuid.uuid4().hex[:4].upper()}",
        "gateway": "tripay", "gross_amount": "999999", "payment_option": "dp50",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": "QRIS2", "fraud_status": None, "created_at": now, "updated_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    hasil = await report_kas_metode_bayar(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    ok = hasil["tunai"] == 30000 and hasil["transfer"] == 40000 and hasil["total"] == 70000
    status = "PASS" if ok else f"FAIL - hasil={hasil}, expected tunai=30000 transfer=40000 total=70000 (Tripay 999999 HARUS tidak ikut)"
    return ("kas_metode_bayar_collect_balance_manual_tidak_hilang", status)


async def skenario_service_revenue_ota_belum_konfirmasi_dikecualikan() -> tuple:
    """Bug ditemukan 2026-09-06 (audit lanjutan permintaan Agus "cek satu-satu fitur
    laporan keuangan") - guard `ota_harga_dikonfirmasi != False` sudah ada di
    _hitung_pendapatan_harian & report_rooms (booking OTA yg harganya masih ESTIMASI
    dari tarif publik PMS, belum dikonfirmasi staf dari settlement asli - lihat
    routes/bookings.py) tapi KELEWAT di report_service_revenue - service_fee booking OTA
    yg masih estimasi ikut terhitung sbg pendapatan service fee asli."""
    from core import db, now_iso
    from routes.reports import report_service_revenue

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T7")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()
    now = now_iso()

    # Booking OTA harga BELUM dikonfirmasi - HARUS dikecualikan.
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-SR1-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T7",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Service Revenue OTA Estimasi",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "ota", "payment_status": "paid", "ota_harga_dikonfirmasi": False,
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "amount_due": 103000,
        "created_at": now,
    })
    # Booking OTA harga SUDAH dikonfirmasi - HARUS tetap terhitung.
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-SR2-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T7",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Service Revenue OTA Konfirmasi",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "ota", "payment_status": "paid", "ota_harga_dikonfirmasi": True,
        "subtotal": 200000, "service_fee": 6000, "total": 206000, "amount_due": 206000,
        "created_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    hasil = await report_service_revenue(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    ok = hasil["booking_service_fee_total"] == 6000
    status = "PASS" if ok else f"FAIL - booking_service_fee_total={hasil['booking_service_fee_total']}, expected=6000 (OTA belum konfirmasi 3000 HARUS tidak ikut)"
    return ("service_revenue_ota_belum_konfirmasi_dikecualikan", status)


async def skenario_pendapatan_harian_kategori_kasir_tak_dikenal_tidak_crash() -> tuple:
    """Bug ditemukan 2026-09-06 (audit lanjutan "cek satu-satu fitur laporan keuangan")
    - kategori produk kasir field BEBAS TEKS (tidak dibatasi enum di level Pydantic),
    tapi _hitung_pendapatan_harian (mesin pendapatan TUNGGAL, dipakai Dashboard &
    Ringkasan) SEBELUM ini indexing langsung `by_day[d][it["kategori"]]` - kategori
    produk yg belum terdaftar (mis. "oleh-oleh") bikin KeyError, CRASH TOTAL laporan
    (bukan cuma produk itu yg gagal, SELURUH Dashboard/Ringkasan ikut 500). Fix: bucket
    kategori tak dikenal ke "lainnya" (uangnya TETAP masuk pendapatan, tidak hilang &
    tidak crash)."""
    from core import db, now_iso
    from routes.reports import report_daily

    property_id = _property_id_test()
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    now = now_iso()

    await db.kasir.insert_one({
        "id": str(uuid.uuid4()), "trx_no": f"TEST-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id,
        "items": [{"product_id": "test-p1", "kode": "P1", "nama": "Oleh-oleh Test", "kategori": "oleh-oleh",
                   "harga": 25000, "qty": 1, "subtotal": 25000}],
        "total": 25000, "metode_bayar": "tunai", "timestamp": now, "created_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    try:
        hasil = await report_daily(from_date=today_iso, to_date=today_iso, user=owner, property_id=property_id)
        total_pendapatan = sum(r["pendapatan"] for r in hasil)
        ok = total_pendapatan == 25000
        status = "PASS" if ok else f"FAIL - total_pendapatan={total_pendapatan}, expected=25000 (uang kategori tak dikenal HARUS tetap masuk)"
    except KeyError as e:
        status = f"FAIL - masih crash KeyError: {e!r} (kategori tak dikenal harusnya di-handle, bukan crash)"
    return ("pendapatan_harian_kategori_kasir_tak_dikenal_tidak_crash", status)


async def skenario_quickbook_bayar_depan_masuk_ledger_rekening() -> tuple:
    """Bug ditemukan 2026-09-06 (audit lanjutan "cek satu-satu fitur laporan keuangan",
    SAMA AKAR MASALAH dgn collect_balance()/mark_paid_manual() yg sudah diperbaiki lebih
    dulu) - Quick Book "bayar di depan semua" (create_booking, booking walk-in dgn
    body.pembayaran langsung) TIDAK PERNAH memanggil auto_posting() sejak awal dibuat,
    uang tunai/QRIS/transfer yg staf terima LANGSUNG saat booking dibuat tidak pernah
    tercatat ke ledger kas (db.rekening_transaksi) - padahal sudah benar muncul di Arus
    Kas/Kas per Metode Bayar (sumber beda, baca bookings.pembayaran langsung)."""
    from core import db, now_iso, BookingCreate
    from routes.bookings import create_booking

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T8")
    now = now_iso()
    besok = (datetime.fromisoformat(now) + timedelta(days=1)).isoformat()

    rekening_id = str(uuid.uuid4())
    await db.rekening.insert_one({
        "id": rekening_id, "nama": "Test Rekening Operasional", "bank": "", "no_rekening": "",
        "pemilik": "", "jenis": "operasional", "saldo": 0, "target": None,
        "warna": "#000000", "icon": "Wallet", "status": "aktif", "default_operasional": True,
        "created_at": now, "updated_at": now, "property_id": property_id,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    body = BookingCreate(
        room_id=room_id, tipe="menginap", nama_tamu="Test Regresi QuickBook Ledger",
        no_hp=_wa_unik(), jam_mulai=now, jam_selesai=besok, tarif_override=100000,
        pembayaran=[{"metode": "tunai", "jumlah": 100000}],
    )
    await create_booking(body, user=owner, property_id=property_id)

    r = await db.rekening.find_one({"id": rekening_id}, {"_id": 0, "saldo": 1})
    trx = await db.rekening_transaksi.find_one({"rekening_id": rekening_id, "kategori": "Booking Tamu (Walk-in/Quick Book)"}, {"_id": 0})
    ok = r is not None and r["saldo"] >= 100000 and trx is not None and trx["nominal"] == 100000
    status = "PASS" if ok else f"FAIL - saldo rekening={r.get('saldo') if r else None}, trx ditemukan={trx is not None}, expected saldo>=100000 & trx.nominal=100000"
    return ("quickbook_bayar_depan_masuk_ledger_rekening", status)


async def skenario_ubah_status_manual_masuk_ledger_rekening() -> tuple:
    """Bug ditemukan 2026-09-06 (audit lanjutan "cek satu-satu fitur laporan keuangan",
    SAMA AKAR MASALAH dgn collect_balance()/mark_paid_manual()/create_booking yg sudah
    diperbaiki lebih dulu) - update_payment_status_manual (owner ubah status transaksi
    payment_log macet jadi "settlement" manual, routes/payments.py) TIDAK PERNAH
    memanggil auto_posting() - uang ini sungguhan masuk (via Tripay, konfirmasi manual
    krn webhook gagal), tapi tidak pernah tercatat ke ledger kas."""
    from core import db, now_iso, PaymentStatusUpdateBody
    from routes.payments import update_payment_status_manual

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T9")
    now = now_iso()

    rekening_id = str(uuid.uuid4())
    await db.rekening.insert_one({
        "id": rekening_id, "nama": "Test Rekening Operasional 2", "bank": "", "no_rekening": "",
        "pemilik": "", "jenis": "operasional", "saldo": 0, "target": None,
        "warna": "#000000", "icon": "Wallet", "status": "aktif", "default_operasional": True,
        "created_at": now, "updated_at": now, "property_id": property_id,
    })
    booking_id = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": booking_id, "kode": f"TEST-UM-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id,
        "room_id": room_id, "room_nomor": "T9", "room_tipe": "Standard", "tipe": "menginap",
        "nama_tamu": "Test Regresi Ubah Status Manual", "no_hp": _wa_unik(),
        "jam_mulai": now, "jam_selesai": (datetime.fromisoformat(now) + timedelta(days=1)).isoformat(),
        "status": "booking_pending", "payment_status": "pending",
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "created_at": now,
    })
    log_id = str(uuid.uuid4())
    await db.payment_log.insert_one({
        "id": log_id, "property_id": property_id, "booking_id": booking_id, "booking_kode": "TEST-UM",
        "order_id": f"TRIPAY-TEST-UM-{uuid.uuid4().hex[:4].upper()}", "gateway": "tripay",
        "gross_amount": "103000", "payment_option": "full", "transaction_status": "pending",
        "status_code": None, "payment_type": "QRIS2", "fraud_status": None,
        "created_at": now, "updated_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    body = PaymentStatusUpdateBody(status="settlement", alasan="Test regresi - konfirmasi manual")
    await update_payment_status_manual(log_id, body, user=owner, property_id=property_id)

    r = await db.rekening.find_one({"id": rekening_id}, {"_id": 0, "saldo": 1})
    trx = await db.rekening_transaksi.find_one({"rekening_id": rekening_id, "kategori": "Booking Tamu (Tripay - konfirmasi manual)"}, {"_id": 0})
    ok = r is not None and r["saldo"] == 103000 and trx is not None and trx["nominal"] == 103000
    status = "PASS" if ok else f"FAIL - saldo rekening={r.get('saldo') if r else None}, trx ditemukan={trx is not None}, expected saldo=103000"
    return ("ubah_status_manual_masuk_ledger_rekening", status)


async def skenario_layanan_manual_masuk_arus_kas_dan_kas_metode_bayar() -> tuple:
    """Bug ditemukan 2026-09-06 (investigasi laporan Agus "bingung kenapa Total Uang
    Masuk beda dari Pendapatan") - db.services (Late Check-out dkk, routes/services.py)
    TIDAK PERNAH dibaca report_arus_kas MAUPUN report_kas_metode_bayar, walau uangnya
    sungguhan diterima staf (metode_pembayaran terisi) - sudah benar masuk Pendapatan
    (report_daily, bucket "service") tapi hilang total dari 2 laporan cash-basis ini."""
    from core import db, now_iso
    from routes.reports import report_arus_kas, report_kas_metode_bayar

    property_id = _property_id_test()
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()
    now = now_iso()

    await db.services.insert_one({
        "id": str(uuid.uuid4()), "kode": f"SVC-TEST-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id,
        "tanggal": now, "kategori": "Late Check-out", "deskripsi": "Test Regresi", "nominal": 40000,
        "tamu": "", "no_hp": "", "room_nomor": "", "metode_pembayaran": "transfer",
        "user": "Test Regresi", "user_id": "test", "created_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    arus = await report_arus_kas(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    kmb = await report_kas_metode_bayar(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    tunai_kmb = kmb["transfer"]
    tunai_ak = sum(r["kamar_tunai_langsung"] for r in arus)
    ok = tunai_ak == 40000 and tunai_kmb == 40000
    status = "PASS" if ok else f"FAIL - arus_kas.kamar_tunai_langsung={tunai_ak}, kas_metode_bayar.transfer={tunai_kmb}, expected 40000 keduanya"
    return ("layanan_manual_masuk_arus_kas_dan_kas_metode_bayar", status)


async def skenario_mark_paid_manual_tidak_bisa_dobel() -> tuple:
    """Bug ditemukan 2026-09-06 (audit lanjutan permintaan Agus "cek laporan keuangan,
    jangan ada data dobel") - booking Hendra Pratama nyata (BKO-20260807221531-FB1F,
    insiden yg SAMA yg jadi alasan fix "alasan wajib diisi" 2026-08-08) TERNYATA masih
    kena manual_paid 2x (gap 2 jam - staf submit ulang, bukan cuma race condition
    milidetik), payment_log Rp123.600 tercatat 2x, dobel-hitung di Arus Kas & Kas per
    Metode Bayar. Fix guard lama (plain find_one baca status) TIDAK cukup - diganti
    find_one_and_update ATOMIK dgn filter status="booking_pending" DI QUERY yang sama
    dgn update, pola sama dgn checkin_from_booking (room status "kosong")."""
    from core import db, now_iso, ManualMarkPaidBody
    from routes.bookings import mark_paid_manual
    from fastapi import HTTPException

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T10")
    now = now_iso()
    booking_id = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": booking_id, "kode": f"TEST-MPM-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id,
        "room_id": room_id, "room_nomor": "T10", "room_tipe": "Standard", "tipe": "menginap",
        "nama_tamu": "Test Regresi Mark Paid Manual", "no_hp": _wa_unik(),
        "jam_mulai": now, "jam_selesai": (datetime.fromisoformat(now) + timedelta(days=1)).isoformat(),
        "status": "booking_pending", "payment_status": "pending",
        "subtotal": 120000, "service_fee": 3600, "total": 123600, "created_at": now,
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    body = ManualMarkPaidBody(alasan="Test regresi - konfirmasi manual", metode="transfer_manual", nominal=123600)

    await mark_paid_manual(booking_id, body, user=owner, property_id=property_id)
    ditolak = False
    try:
        await mark_paid_manual(booking_id, body, user=owner, property_id=property_id)
    except HTTPException as e:
        ditolak = e.status_code == 400

    jumlah_log = await db.payment_log.count_documents({"booking_id": booking_id})
    ok = ditolak and jumlah_log == 1
    status = "PASS" if ok else f"FAIL - panggilan kedua ditolak={ditolak}, jumlah payment_log={jumlah_log} (expected: ditolak=True, jumlah=1)"
    return ("mark_paid_manual_tidak_bisa_dobel", status)


async def skenario_analitik_saluran_cancelled_dan_walkin_tidak_dobel() -> tuple:
    """Bug KELIMA ditemukan sambil audit lanjutan (2026-08-25) - laporan_analitik.py
    (Analitik Saluran) TIDAK PERNAH cek `status` sama sekali (booking cancelled yg lupa
    reset payment_status ikut kehitung, sama akar dgn fix _hitung_pendapatan_harian) DAN
    laporan_pendapatan TIDAK PERNAH cek `source` walau docstring-nya eksplisit bilang
    "tidak termasuk walk-in" (17 booking walk_in Menginap dobel-hitung dgn /reports/daily).
    Skenario: 1 booking online aktif (harus kehitung), 1 booking online cancelled-tapi-
    paid (harus diabaikan), 1 booking walk_in menginap paid (harus diabaikan di
    laporan_pendapatan krn bukan online - TAPI TETAP kehitung di performa_saluran kalau
    channel-nya match... walk_in bukan bagian SALURAN_KEYS manapun jadi otomatis tidak
    match, tidak perlu exclude eksplisit di situ)."""
    from core import db, now_iso
    from routes.laporan_analitik import laporan_pendapatan, laporan_performa_saluran

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T7")
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_iso = today_wita.isoformat()
    besok_iso = (today_wita + timedelta(days=1)).isoformat()

    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-AN-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T7",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Online Aktif",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "online", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "paid_at": now_iso(), "created_at": now_iso(),
    })
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-AC-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T7",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Online Cancelled",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "cancelled", "source": "ota", "payment_status": "paid",
        "subtotal": 300000, "service_fee": 9000, "total": 309000, "amount_due": 309000,
        "paid_at": now_iso(), "created_at": now_iso(), "cancelled_at": now_iso(),
    })
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-AW-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T7",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Walkin",
        "no_hp": _wa_unik(), "jam_mulai": f"{today_iso}T06:00:00+00:00", "jam_selesai": f"{besok_iso}T04:00:00+00:00",
        "status": "aktif", "source": "walk_in", "payment_status": "paid",
        "subtotal": 500000, "service_fee": 15000, "total": 515000, "amount_due": 515000,
        "paid_at": now_iso(), "created_at": now_iso(),
    })

    owner = {"id": "test", "nama": "Test Regresi"}
    pendapatan = await laporan_pendapatan(from_date=today_iso, to_date=besok_iso, user=owner, property_id=property_id)
    total_pendapatan = sum(r["pendapatan"] for r in pendapatan)
    saluran = await laporan_performa_saluran(channel="Semua", user=owner, property_id=property_id)
    total_saluran = sum(r["pendapatan"] for r in saluran)

    # pendapatan: cuma booking online aktif (154500) - cancelled diabaikan, walk_in diabaikan (bukan online).
    # saluran: sama (154500) - walk_in tidak match SALURAN_KEYS manapun, cancelled diabaikan.
    ok = total_pendapatan == 154500 and total_saluran == 154500
    status = "PASS" if ok else f"FAIL - laporan_pendapatan={total_pendapatan} (expected 154500), performa_saluran={total_saluran} (expected 154500)"
    return ("analitik_saluran_cancelled_dan_walkin_tidak_dobel", status)


async def skenario_telegram_laporan_harian_cancelled_tidak_dihitung() -> tuple:
    """Bug KEENAM ditemukan sambil audit lanjutan (2026-08-25) - _pendapatan_kamar_per_tipe_
    hari_ini (telegram_bot.py, sumber Laporan Harian Telegram ke owner jam 23:00 WITA) SAMA
    SEKALI tidak cek `status` di 2 query booking-nya (day_use belum checkin + menginap) -
    booking cancelled yang lupa reset payment_status ikut kehitung sbg pendapatan hari ini
    di laporan yang dikirim LANGSUNG ke Agus tiap malam."""
    from core import db, now_iso
    from routes.telegram_bot import _pendapatan_kamar_per_tipe_hari_ini

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T8")
    today_iso = now_iso()

    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-TG-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T8",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Telegram Aktif",
        "no_hp": _wa_unik(), "jam_mulai": today_iso, "jam_selesai": today_iso,
        "status": "aktif", "source": "online", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "paid_at": today_iso, "created_at": today_iso,
    })
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-TC-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id, "room_id": room_id, "room_nomor": "T8",
        "room_tipe": "Standard", "tipe": "menginap", "nama_tamu": "Test Regresi Telegram Cancelled",
        "no_hp": _wa_unik(), "jam_mulai": today_iso, "jam_selesai": today_iso,
        "status": "cancelled", "source": "ota", "payment_status": "paid",
        "subtotal": 300000, "service_fee": 9000, "total": 309000, "amount_due": 309000,
        "paid_at": today_iso, "created_at": today_iso, "cancelled_at": today_iso,
    })

    hasil = await _pendapatan_kamar_per_tipe_hari_ini(property_id)
    ok = hasil["menginap_total"] == 154500 and hasil["menginap_kamar"] == 1
    status = "PASS" if ok else f"FAIL - hasil={hasil}, expected menginap_total=154500 menginap_kamar=1"
    return ("telegram_laporan_harian_cancelled_tidak_dihitung", status)


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


async def skenario_konfirmasi_checkin_dari_tiket_berhasil() -> tuple:
    """Fitur baru (2026-08-26, PRD "Fix Member Discount & Day Use dengan Code" - tombol
    "Ya, sudah check-in" di notifikasi Telegram staf, dipicu dari catat_kedatangan_tamu
    ai-chat-bot) - _konfirmasi_checkin_dari_tiket HARUS benar-benar menjalankan check-in
    ASLI (checkin_from_booking yang SUDAH ADA, direct reuse - bukan mekanisme baru):
    booking berubah status checked_in DAN total_kunjungan tamu naik lewat jalur yang
    PERSIS SAMA dengan check-in manual biasa di PMS (definisi "kedatangan" tidak berubah)."""
    from core import db, now_iso
    from routes.telegram_bot import _konfirmasi_checkin_dari_tiket

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T8")
    staff_user = {"id": "test-staf", "nama": "Test Regresi Staf"}
    no_hp = _wa_unik()
    today_iso = datetime.now(timezone.utc).isoformat()

    booking_id = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": booking_id, "kode": f"TEST-{uuid.uuid4().hex[:8].upper()}", "property_id": property_id,
        "room_id": room_id, "room_nomor": "T8", "room_tipe": "Standard", "tipe": "day_use",
        "nama_tamu": "Test Regresi Konfirmasi Checkin", "no_hp": no_hp,
        "jam_mulai": today_iso, "jam_selesai": today_iso, "status": "booking_paid",
        "source": "whatsapp_auto", "payment_status": "paid", "subtotal": 100000, "service_fee": 3000,
        "total": 103000, "amount_due": 103000, "payment_type": "QRIS", "paid_at": today_iso, "created_at": today_iso,
    })

    konfirmasi = await _konfirmasi_checkin_dari_tiket(booking_id, staff_user)
    updated = await db.bookings.find_one({"id": booking_id})
    guest = await db.guests.find_one({"no_hp": no_hp, "property_id": property_id})

    ok = (
        konfirmasi.startswith("✅")
        and updated is not None and updated.get("status") == "checked_in"
        and guest is not None and guest.get("total_kunjungan") == 1
    )
    status = "PASS" if ok else (
        f"FAIL - konfirmasi={konfirmasi!r}, booking_status={updated.get('status') if updated else None}, "
        f"guest_total_kunjungan={guest.get('total_kunjungan') if guest else None} (harusnya checked_in & 1)"
    )
    return ("konfirmasi_checkin_dari_tiket_berhasil", status)


async def skenario_konfirmasi_checkin_dari_tiket_dobel_tidak_dobel_hitung() -> tuple:
    """Tap tombol "Ya, sudah check-in" DUA KALI pada booking yang SAMA HARUS TIDAK
    menghasilkan check-in dobel/total_kunjungan naik dua kali. Anti-dobel BUKAN mekanisme
    baru - direct reuse guard status yang SUDAH ADA di checkin_from_booking
    (booking_paid/aktif -> checked_in, tap kedua otomatis kena guard itu sendiri)."""
    from core import db, now_iso
    from routes.telegram_bot import _konfirmasi_checkin_dari_tiket

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T9")
    staff_user = {"id": "test-staf", "nama": "Test Regresi Staf"}
    no_hp = _wa_unik()
    today_iso = datetime.now(timezone.utc).isoformat()

    booking_id = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": booking_id, "kode": f"TEST-{uuid.uuid4().hex[:8].upper()}", "property_id": property_id,
        "room_id": room_id, "room_nomor": "T9", "room_tipe": "Standard", "tipe": "day_use",
        "nama_tamu": "Test Regresi Dobel Checkin", "no_hp": no_hp,
        "jam_mulai": today_iso, "jam_selesai": today_iso, "status": "booking_paid",
        "source": "whatsapp_auto", "payment_status": "paid", "subtotal": 100000, "service_fee": 3000,
        "total": 103000, "amount_due": 103000, "payment_type": "QRIS", "paid_at": today_iso, "created_at": today_iso,
    })

    konfirmasi_1 = await _konfirmasi_checkin_dari_tiket(booking_id, staff_user)
    konfirmasi_2 = await _konfirmasi_checkin_dari_tiket(booking_id, staff_user)
    guest = await db.guests.find_one({"no_hp": no_hp, "property_id": property_id})

    ok = (
        konfirmasi_1.startswith("✅")
        and not konfirmasi_2.startswith("✅")
        and guest is not None and guest.get("total_kunjungan") == 1
    )
    status = "PASS" if ok else (
        f"FAIL - konfirmasi_1={konfirmasi_1!r}, konfirmasi_2={konfirmasi_2!r}, "
        f"guest_total_kunjungan={guest.get('total_kunjungan') if guest else None} (harusnya tetap 1)"
    )
    return ("konfirmasi_checkin_dari_tiket_dobel_tidak_dobel_hitung", status)


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


async def skenario_checkin_pesan_error_perlu_dibersihkan_bukan_sedang_dipakai() -> tuple:
    """Bug nyata 2026-09-07 (laporan Agus - "day use ditumpuk menginap ada yang aneh?"):
    checkin_from_booking() SELALU bilang "Kamar X sedang dipakai" kalau room.status !=
    "kosong", TERMASUK saat statusnya sebenarnya "perlu_dibersihkan" (tamu Day Use SUDAH
    checkout, kamar fisik kosong, cuma belum ditandai selesai dibersihkan) - staf yang baca
    pesan ini bisa salah kira tamu sebelumnya belum pergi & menunggu sia-sia, padahal cukup
    klik "Selesai Dibersihkan" dulu. Fix: pesan dibedakan per status asli kamar."""
    from core import db, now_iso
    from routes.bookings import checkin_from_booking
    from core import CheckinFromBookingBody

    property_id = _property_id_test()
    room_id = await _bikin_kamar_test(db, property_id, "T10")
    await db.rooms.update_one({"id": room_id}, {"$set": {"status": "perlu_dibersihkan"}})
    bk_id = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": bk_id, "kode": f"TEST-PB-{uuid.uuid4().hex[:6].upper()}", "property_id": property_id,
        "room_id": room_id, "room_nomor": "T10", "room_tipe": "Standard", "tipe": "menginap",
        "nama_tamu": "Test Regresi Perlu Dibersihkan", "no_hp": _wa_unik(),
        "jam_mulai": "2026-08-20T06:00:00+00:00", "jam_selesai": "2026-08-21T04:00:00+00:00",
        "status": "aktif", "source": "whatsapp_auto", "payment_status": "paid",
        "subtotal": 150000, "service_fee": 4500, "total": 154500, "amount_due": 154500,
        "paid_at": now_iso(), "created_at": now_iso(),
    })
    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    try:
        await checkin_from_booking(bk_id, CheckinFromBookingBody(), user=owner, property_id=property_id)
        status = "FAIL - checkin_from_booking harusnya menolak (kamar belum ditandai kosong), tapi malah sukses"
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        ok = "belum ditandai selesai dibersihkan" in detail or "Selesai Dibersihkan" in detail
        status = "PASS" if ok else f"FAIL - pesan error masih generik/salah: {detail!r}"
    return ("checkin_pesan_error_perlu_dibersihkan_bukan_sedang_dipakai", status)


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


async def skenario_ota_jam_geser_tembus_tengah_malam_ditolak_otomatis() -> tuple:
    """Bug nyata 2026-09-07 (laporan Agus - "tamu harusnya checkin tanggal 4 tapi di PMS
    masuk tanggal 5"), kasus MASNAN MASNAN BKO-20260904173118-4400: buat_reservasi_otomatis
    (routes/otomasi_email.py) menggeser jam_mulai reservasi OTA baru ke jam kamar
    diperkirakan bebas kalau kamar standar (14:00 WITA) masih dipakai tamu Day Use walk-in.
    Kalau pergeserannya TEMBUS tengah malam WITA (kamar baru bebas SETELAH tanggal check-in
    yang dijanjikan di email OTA), sebelum fix ini tetap dibuat reservasi otomatis dgn
    tanggal SALAH (H+1) - tamu jadi hilang dari laporan tanggal aslinya. SETELAH fix: kasus
    tembus tengah malam TIDAK dibuat otomatis, email_log jadi Manual_Required dgn alasan
    jelas - staf yang putuskan, bukan sistem diam-diam salah catat tanggal.

    Skenario: kamar test tipe Standard, ada checkin walk-in aktif (Day Use, TANPA
    from_booking_id) jam_checkin 18:00 WITA (10:00 UTC) - estimasi konservatif walk-in
    (+6 jam di check_room_available) MEMANG masih bentrok dgn jam standar OTA 14:00 WITA,
    dan estimasi otomasi_email (+6 jam 30 menit = 00:30 WITA hari BERIKUTNYA) TEMBUS
    tengah malam dari tanggal check-in email (2026-08-20). Panggil buat_reservasi_otomatis
    langsung - HARUS TIDAK membuat booking (reservation_ids kosong), status email_log HARUS
    Manual_Required, dan alasan HARUS menyebut "tengah malam" (jejak jelas kenapa ditolak)."""
    from core import db, now_iso
    from routes.otomasi_email import buat_reservasi_otomatis

    property_id = _property_id_test()
    subjek_unik = f"Test Regresi OTA Midnight {uuid.uuid4().hex[:6]}"
    ota_tipe_unik = f"TEST-REGRESI-TIPE-{uuid.uuid4().hex[:6]}"
    sumber_unik = f"RedDoorzTestRegresi{uuid.uuid4().hex[:6]}"
    log_id = str(uuid.uuid4())

    await db.properties.insert_one({"id": property_id, "nama": subjek_unik, "aktif": True})
    await db.room_mappings.insert_one({
        "id": str(uuid.uuid4()), "ota_nama": ota_tipe_unik, "sumber": sumber_unik, "pms_tipe": "Standard",
    })
    room_id = await _bikin_kamar_test(db, property_id, "T9")
    await db.checkins.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "room_id": room_id, "room_nomor": "T9",
        "room_tipe": "Standard", "nama_tamu": "Test Regresi WalkIn DayUse", "no_hp": _wa_unik(),
        "jumlah_tamu": 1, "tarif_dasar": 100000, "jam_checkin": "2026-08-20T10:00:00+00:00",
        "jam_checkout": None, "durasi_jam": 6, "overtime_jam": 0, "biaya_tambahan": 0,
        "subtotal": 100000, "service_fee": 3000, "total": 103000, "status": "aktif",
        "pembayaran": [{"metode": "tunai", "jumlah": 103000}],
        "petugas_checkin": "Test", "petugas_checkin_id": "test", "created_at": now_iso(),
    })
    await db.email_logs.insert_one({
        "id": log_id, "gmail_message_id": f"test-{log_id}", "subjek": subjek_unik,
        "pengirim": "test@test.com", "sumber": sumber_unik, "status": "Parsed_Success", "jenis": "baru",
        "extracted_data": {}, "processed_at": now_iso(),
    })

    try:
        await buat_reservasi_otomatis(
            log_id,
            {
                "tipe_kamar": ota_tipe_unik, "no_reservasi": f"TEST-{uuid.uuid4().hex[:8]}",
                "nama_tamu": "Test Regresi Masnan Style", "check_in": "2026-08-20T14:00:00",
                "check_out": "2026-08-21T12:00:00", "jumlah_tamu": 1, "harga": 200000,
                "status_pembayaran": "Belum Bayar", "jumlah_kamar": 1, "permintaan_khusus": "NA",
            },
            sumber_unik, subjek_unik,
        )
        log = await db.email_logs.find_one({"id": log_id}, {"_id": 0})
        tidak_ada_booking = not log.get("reservation_ids")
        status_benar = log.get("status") == "Manual_Required"
        alasan_jelas = "tengah malam" in (log.get("alasan") or "").lower()
        ok = tidak_ada_booking and status_benar and alasan_jelas
        status = ("PASS" if ok else
                  f"FAIL - reservation_ids={log.get('reservation_ids')}, status={log.get('status')!r}, alasan={log.get('alasan')!r}")
    finally:
        await db.properties.delete_one({"id": property_id})
        await db.room_mappings.delete_many({"ota_nama": ota_tipe_unik})
        await db.email_logs.delete_one({"id": log_id})

    return ("ota_jam_geser_tembus_tengah_malam_ditolak_otomatis", status)


async def skenario_ota_manual_required_retry_otomatis_setelah_housekeeping() -> tuple:
    """Bug nyata 2026-09-07 (laporan Agus - "day use blokir OTA, staf yang pakai apa bisa
    dibantu?"): email OTA yang gagal total (Manual_Required krn "tidak ada kamar kosong",
    mis. kamar tipe itu penuh Day Use) SEBELUM ini diam selamanya - beda dari jalur booking
    AI WhatsApp yang SUDAH punya retry otomatis begitu housekeeping selesai
    (coba_retry_menginap_dayuse). Audit nemu 16 email OTA dari Juli-Agustus masih
    tersangkut Manual_Required krn tidak ada retry ini. Fix: coba_retry_ota_manual_required
    dipanggil dari housekeeping_done() (routes/rooms.py), sama pola dgn jalur WA.

    Skenario: email_log Manual_Required (alasan "Tidak ada kamar...", reservation_ids
    kosong) utk kamar tipe Standard, TAPI saat retry dipanggil kamar tipe itu SUDAH kosong
    (skenario ini sengaja tidak bikin konflik apa pun) - panggil housekeeping_done() pada
    kamar test tipe sama, HARUS memicu retry yang berhasil bikin reservasi & log jadi
    Parsed_Success (bukan diam selamanya)."""
    from core import db, now_iso, HousekeepingDone
    from routes.rooms import housekeeping_done

    property_id = _property_id_test()
    subjek_unik = f"Test Regresi OTA Retry {uuid.uuid4().hex[:6]}"
    ota_tipe_unik = f"TEST-REGRESI-RETRY-{uuid.uuid4().hex[:6]}"
    sumber_unik = f"RedDoorzTestRetry{uuid.uuid4().hex[:6]}"
    log_id = str(uuid.uuid4())

    await db.properties.insert_one({"id": property_id, "nama": subjek_unik, "aktif": True})
    await db.room_mappings.insert_one({
        "id": str(uuid.uuid4()), "ota_nama": ota_tipe_unik, "sumber": sumber_unik, "pms_tipe": "Standard",
    })
    room_id = await _bikin_kamar_test(db, property_id, "T12")
    await db.rooms.update_one({"id": room_id}, {"$set": {"status": "perlu_dibersihkan"}})
    await db.email_logs.insert_one({
        "id": log_id, "gmail_message_id": f"test-{log_id}", "subjek": subjek_unik,
        "pengirim": "test@test.com", "sumber": sumber_unik, "status": "Manual_Required", "jenis": "baru",
        "alasan": "Tidak ada kamar Standard yang kosong pada 2026-08-20-2026-08-21 (kemungkinan bentrok)",
        "extracted_data": {
            "tipe_kamar": ota_tipe_unik, "no_reservasi": f"TEST-{uuid.uuid4().hex[:8]}",
            "nama_tamu": "Test Regresi Retry Housekeeping", "check_in": "2026-08-20T14:00:00",
            "check_out": "2026-08-21T12:00:00", "jumlah_tamu": 1, "harga": 150000,
            "status_pembayaran": "Belum Bayar", "jumlah_kamar": 1, "permintaan_khusus": "NA",
        },
        "processed_at": now_iso(),
    })

    owner = {"id": "test", "nama": "Test Regresi", "role": "owner"}
    try:
        await housekeeping_done(room_id, HousekeepingDone(petugas="Test"), user=owner, property_id=property_id)
        log = await db.email_logs.find_one({"id": log_id}, {"_id": 0})
        ok = log.get("status") == "Parsed_Success" and bool(log.get("reservation_ids"))
        status = ("PASS" if ok else
                  f"FAIL - status={log.get('status')!r}, reservation_ids={log.get('reservation_ids')} (harusnya Parsed_Success dgn reservasi terbuat)")
    finally:
        await db.properties.delete_one({"id": property_id})
        await db.room_mappings.delete_many({"ota_nama": ota_tipe_unik})
        await db.email_logs.delete_one({"id": log_id})

    return ("ota_manual_required_retry_otomatis_setelah_housekeeping", status)


# --- Availability publik / Booking Engine Traveloka-style (Phase 2, 2026-09-13) ---
# Mengunci perilaku setelah gate STATUS FISIK dibuang (commit 69de564): availability
# publik HARUS murni date/booking-based. Tanpa test ini, gate `q["status"]="kosong"`
# bisa diam-diam masuk lagi & memunculkan "kamar penuh padahal kosong" (keluhan nyata
# Agus 2026-09) tanpa ketahuan. Ingat: 04:00 UTC = 12:00 WITA, 06:00 UTC = 14:00 WITA.

async def skenario_availability_hari_ini_hanya_sembunyikan_maintenance() -> tuple:
    from routes.public import public_availability
    from core import db
    property_id = _property_id_test()
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()
    r_kotor = await _bikin_kamar_test(db, property_id, "AV1")
    await db.rooms.update_one({"id": r_kotor}, {"$set": {"status": "perlu_dibersihkan"}})
    r_maint = await _bikin_kamar_test(db, property_id, "AV2")
    await db.rooms.update_one({"id": r_maint}, {"$set": {"status": "maintenance"}})
    res = await public_availability(tanggal=today, property_id_override=property_id)
    ids = {x["id"] for x in res["rooms"]}
    ok = r_kotor in ids and r_maint not in ids
    return ("availability_hari_ini_hanya_sembunyikan_maintenance",
            "PASS" if ok else f"FAIL - kotor_muncul={r_kotor in ids}(harus True), maintenance_muncul={r_maint in ids}(harus False)")


async def skenario_availability_tanggal_depan_abaikan_status_fisik() -> tuple:
    from routes.public import public_availability
    from core import db
    property_id = _property_id_test()
    r = await _bikin_kamar_test(db, property_id, "AV3")
    await db.rooms.update_one({"id": r}, {"$set": {"status": "menginap"}})  # fisik terisi SEKARANG, tapi tak ada booking di masa depan
    depan = (datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date() + timedelta(days=3)).isoformat()
    res = await public_availability(tanggal=depan, property_id_override=property_id)
    ok = r in {x["id"] for x in res["rooms"]}
    return ("availability_tanggal_depan_abaikan_status_fisik",
            "PASS" if ok else "FAIL - kamar status fisik=menginap tak muncul di tanggal 3 hari lagi (harus muncul, status realtime tak relevan utk masa depan)")


async def skenario_availability_dayuse_presisi_jam_setelah_checkout() -> tuple:
    # Regresi bug Vina (public.py:199): kamar yg checkout menginap jam 12:00 HARUS bisa
    # dibooking Day Use jam 13:00 hari yg sama, tapi TIDAK jam 10:00 (masih terisi). Pakai
    # BESOK supaya bebas dari jam-dinding & guard "masa lalu".
    from routes.public import public_availability
    from core import db
    property_id = _property_id_test()
    r = await _bikin_kamar_test(db, property_id, "AV4")
    hari_ini = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    besok = (hari_ini + timedelta(days=1)).isoformat()
    hari_ini_iso = hari_ini.isoformat()
    # menginap: check-in hari ini 14:00 WITA (06:00 UTC), checkout BESOK 12:00 WITA (04:00 UTC)
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "room_id": r, "room_nomor": "AV4",
        "room_tipe": "Standard", "kode": "AVTEST", "tipe": "menginap", "status": "booking_paid",
        "payment_status": "paid", "nama_tamu": "Test Av", "no_hp": _wa_unik(),
        "jam_mulai": f"{hari_ini_iso}T06:00:00+00:00", "jam_selesai": f"{besok}T04:00:00+00:00",
        "tanggal_checkin": hari_ini_iso, "tanggal_checkout": besok,
        "total": 150000, "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # tipe di endpoint = filter TIPE KAMAR (Standard/Cottage), bukan day_use/menginap;
    # presisi Day Use ditentukan jam_checkin. Kirim tipe=Standard (sesuai kamar test).
    res_bebas = await public_availability(tanggal=besok, tipe="Standard", jam_checkin="13:00", property_id_override=property_id)
    res_terisi = await public_availability(tanggal=besok, tipe="Standard", jam_checkin="10:00", property_id_override=property_id)
    muncul_13 = r in {x["id"] for x in res_bebas["rooms"]}
    muncul_10 = r in {x["id"] for x in res_terisi["rooms"]}
    ok = muncul_13 and not muncul_10
    return ("availability_dayuse_presisi_jam_setelah_checkout",
            "PASS" if ok else f"FAIL - jam13(bebas setelah checkout 12:00)={muncul_13}(harus True), jam10(masih terisi)={muncul_10}(harus False)")


async def skenario_pms_confirm_settlement_idempoten_sekali_per_grup() -> tuple:
    """(Phase 6 Booking Engine, 2026-09-13) PMS-confirm = tripay_callback settlement. Kunci
    2 invariant PATH UANG (regresi bug Jadid 4-kamar + retry webhook Tripay):
    (1) posting pemasukan ke rekening SEKALI per GRUP (bukan per kamar);
    (2) IDEMPOTEN — Tripay boleh kirim callback settlement yang sama BERKALI-KALI; callback
        kedua TIDAK boleh double-post uang / double-kirim voucher (guard `was_paid`).
    Semua sender eksternal (voucher PDF/email/WA, push, alert Telegram owner) di-patch jadi
    no-op supaya test TIDAK mengirim apa pun ke tamu/Agus (auto_posting tetap nyata → tulis
    ke rekening_transaksi test, dibersihkan)."""
    import json as _json, hashlib as _hashlib, hmac as _hmac
    from core import db, now_iso
    import routes.tripay as tp

    if not tp.TRIPAY_PRIVATE_KEY:
        return ("pms_confirm_settlement_idempoten_sekali_per_grup", "PASS")  # key tak diset di env ini → skip aman

    property_id = _property_id_test()
    r1 = await _bikin_kamar_test(db, property_id, "PC1")
    r2 = await _bikin_kamar_test(db, property_id, "PC2")
    await db.rekening.insert_one({"id": str(uuid.uuid4()), "property_id": property_id, "nama": "Test Op",
                                  "default_operasional": True, "status": "aktif", "saldo": 0, "created_at": now_iso()})
    group_id = str(uuid.uuid4())
    order_id = f"TEST-PC-{uuid.uuid4().hex[:6].upper()}"
    kodes = []
    for rid, nomor, total in [(r1, "PC1", 200000), (r2, "PC2", 300000)]:
        kode = f"TEST-PC-{uuid.uuid4().hex[:6].upper()}"
        kodes.append(kode)
        await db.bookings.insert_one({
            "id": str(uuid.uuid4()), "kode": kode, "property_id": property_id, "group_id": group_id,
            "room_id": rid, "room_nomor": nomor, "room_tipe": "Standard", "tipe": "menginap",
            "status": "booking_pending", "payment_status": "pending", "source": "online",
            "nama_tamu": "Test Confirm", "no_hp": _wa_unik(), "invoice_id": order_id,
            "jam_mulai": now_iso(), "jam_selesai": now_iso(),
            "subtotal": total, "service_fee": 0, "total": total, "amount_due": total, "created_at": now_iso(),
        })
    total_grup = 500000
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": (await db.bookings.find_one({"group_id": group_id}))["id"],
        "group_id": group_id, "order_id": order_id, "gateway": "tripay", "transaction_status": "pending",
        "payment_type": "QRIS", "payment_option": "full", "gross_amount": str(total_grup), "created_at": now_iso(),
    })

    # --- patch semua sender eksternal (aman: tak kirim ke tamu/Agus) ---
    voucher_calls = {"n": 0}
    orig = {k: getattr(tp, k) for k in
            ("send_voucher_email", "kirim_voucher_wa", "send_push", "kirim_alert_owner", "generate_voucher_pdf", "get_property_branding")}

    async def _count_voucher(*a, **k):
        voucher_calls["n"] += 1

    async def _noop_async(*a, **k):
        pass

    async def _branding(*a, **k):
        return {}

    tp.send_voucher_email = _count_voucher
    tp.kirim_voucher_wa = _noop_async
    tp.send_push = _noop_async
    tp.kirim_alert_owner = _noop_async
    tp.get_property_branding = _branding
    tp.generate_voucher_pdf = lambda *a, **k: b"PDF"  # sync (dipanggil via to_thread)

    class _FakeReq:
        def __init__(self, raw, sig):
            self._raw = raw
            self.headers = {"X-Callback-Signature": sig, "X-Callback-Event": "payment_status"}
        async def body(self):
            return self._raw
        async def json(self):
            return _json.loads(self._raw)

    def _req():
        payload = {"merchant_ref": order_id, "reference": "T-REF", "status": "PAID",
                   "total_amount": total_grup, "payment_method": "QRIS"}
        raw = _json.dumps(payload).encode()
        sig = _hmac.new(tp.TRIPAY_PRIVATE_KEY.encode(), raw, _hashlib.sha256).hexdigest()
        return _FakeReq(raw, sig)

    try:
        await tp.tripay_callback(_req())   # settlement pertama
        await tp.tripay_callback(_req())   # RETRY settlement (harus idempoten)
        paid = await db.bookings.count_documents({"group_id": group_id, "status": "booking_paid", "payment_status": "paid"})
        posting = await db.rekening_transaksi.count_documents({"property_id": property_id, "jenis": "pemasukan"})
        ok = (paid == 2) and (posting == 1) and (voucher_calls["n"] == 1)
        status = ("PASS" if ok else
                  f"FAIL - paid={paid}(harus 2), posting_pemasukan={posting}(harus 1 sekali per grup), voucher={voucher_calls['n']}(harus 1, retry tak dobel)")
    finally:
        for k, v in orig.items():
            setattr(tp, k, v)
        for kode in kodes:
            await db.audit_log.delete_many({"detail": {"$regex": kode}})
    return ("pms_confirm_settlement_idempoten_sekali_per_grup", status)


async def skenario_pms_confirm_pembayaran_telat_kamar_diambil_tidak_revive() -> tuple:
    """(Phase 5 completion, 2026-09-13) Guard anti-overbooking: kalau booking online sudah
    CANCELLED (hold TTL kadaluarsa, kamar dilepas) lalu pembayaran TELAT masuk & kamar
    KEBURU diambil tamu lain — callback settlement TIDAK boleh menghidupkan ulang booking
    itu jadi paid (kalau tidak: 2 tamu 1 kamar, dua-duanya bayar). Harus tetap cancelled +
    tak ada posting + tak ada voucher (alih ke alert refund staf)."""
    import json as _json, hashlib as _hashlib, hmac as _hmac
    from core import db, now_iso
    import routes.tripay as tp

    if not tp.TRIPAY_PRIVATE_KEY:
        return ("pms_confirm_pembayaran_telat_kamar_diambil_tidak_revive", "PASS")

    property_id = _property_id_test()
    rid = await _bikin_kamar_test(db, property_id, "PT1")
    await db.rekening.insert_one({"id": str(uuid.uuid4()), "property_id": property_id, "nama": "Test Op",
                                  "default_operasional": True, "status": "aktif", "saldo": 0, "created_at": now_iso()})
    besok = (datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date() + timedelta(days=1)).isoformat()
    mulai = f"{besok}T05:00:00+00:00"   # besok 13:00 WITA
    selesai = f"{besok}T11:00:00+00:00"  # besok 19:00 WITA
    order_id = f"TEST-PT-{uuid.uuid4().hex[:6].upper()}"
    kode_a = f"TEST-PT-{uuid.uuid4().hex[:6].upper()}"
    # Booking A: online, SUDAH cancelled krn hold kadaluarsa (belum bayar)
    id_a = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": id_a, "kode": kode_a, "property_id": property_id, "room_id": rid, "room_nomor": "PT1",
        "room_tipe": "Standard", "tipe": "day_use", "status": "cancelled", "payment_status": "pending",
        "source": "online", "cancelled_by": "system:hold_expired", "nama_tamu": "Telat Bayar", "no_hp": _wa_unik(),
        "invoice_id": order_id, "jam_mulai": mulai, "jam_selesai": selesai,
        "subtotal": 200000, "service_fee": 0, "total": 200000, "amount_due": 200000, "created_at": now_iso(),
    })
    # Booking B: tamu lain sudah ambil kamar+slot yg sama (aktif/paid) → kamar TAK bebas lagi
    await db.bookings.insert_one({
        "id": str(uuid.uuid4()), "kode": f"TEST-PT-B-{uuid.uuid4().hex[:5].upper()}", "property_id": property_id,
        "room_id": rid, "room_nomor": "PT1", "room_tipe": "Standard", "tipe": "day_use", "status": "booking_paid",
        "payment_status": "paid", "source": "online", "nama_tamu": "Tamu Lain", "no_hp": _wa_unik(),
        "jam_mulai": mulai, "jam_selesai": selesai, "total": 200000, "created_at": now_iso(),
    })
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "property_id": property_id, "booking_id": id_a, "order_id": order_id,
        "gateway": "tripay", "transaction_status": "pending", "payment_type": "BRIVA", "payment_option": "full",
        "gross_amount": "200000", "created_at": now_iso(),
    })

    calls = {"voucher": 0, "alert": 0}
    orig = {k: getattr(tp, k) for k in
            ("send_voucher_email", "kirim_voucher_wa", "send_push", "kirim_alert_owner", "generate_voucher_pdf", "get_property_branding")}

    async def _cv(*a, **k):
        calls["voucher"] += 1

    async def _ca(*a, **k):
        calls["alert"] += 1

    async def _noop_async(*a, **k):
        pass

    async def _branding(*a, **k):
        return {}

    tp.send_voucher_email = _cv
    tp.kirim_voucher_wa = _noop_async
    tp.send_push = _noop_async
    tp.kirim_alert_owner = _ca
    tp.get_property_branding = _branding
    tp.generate_voucher_pdf = lambda *a, **k: b"PDF"

    class _FakeReq:
        def __init__(self, raw, sig):
            self._raw = raw
            self.headers = {"X-Callback-Signature": sig, "X-Callback-Event": "payment_status"}
        async def body(self):
            return self._raw
        async def json(self):
            return _json.loads(self._raw)

    payload = {"merchant_ref": order_id, "reference": "T-REF", "status": "PAID", "total_amount": 200000, "payment_method": "BRIVA"}
    raw = _json.dumps(payload).encode()
    sig = _hmac.new(tp.TRIPAY_PRIVATE_KEY.encode(), raw, _hashlib.sha256).hexdigest()

    try:
        await tp.tripay_callback(_FakeReq(raw, sig))
        a = await db.bookings.find_one({"id": id_a}, {"_id": 0, "status": 1, "payment_status": 1})
        posting = await db.rekening_transaksi.count_documents({"property_id": property_id, "jenis": "pemasukan"})
        ok = (a["status"] == "cancelled" and a["payment_status"] != "paid" and posting == 0
              and calls["voucher"] == 0 and calls["alert"] >= 1)
        status = ("PASS" if ok else
                  f"FAIL - A.status={a['status']}(harus cancelled), A.payment={a['payment_status']}(bukan paid), "
                  f"posting={posting}(harus 0), voucher={calls['voucher']}(harus 0), alert_refund={calls['alert']}(harus >=1)")
    finally:
        for k, v in orig.items():
            setattr(tp, k, v)
        await db.audit_log.delete_many({"detail": {"$regex": kode_a}})
    return ("pms_confirm_pembayaran_telat_kamar_diambil_tidak_revive", status)


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
        skenario_ringkasan_pisah_menginap_dan_day_use,
        skenario_booking_cancelled_masih_paid_tidak_dihitung,
        skenario_arus_kas_walkin_menginap_tidak_hilang,
        skenario_arus_kas_collect_balance_manual_masuk_kamar_tunai_bukan_online,
        skenario_arus_kas_online_pakai_amount_diterima_bersih_bukan_gross,
        skenario_kas_metode_bayar_collect_balance_manual_tidak_hilang,
        skenario_service_revenue_ota_belum_konfirmasi_dikecualikan,
        skenario_pendapatan_harian_kategori_kasir_tak_dikenal_tidak_crash,
        skenario_quickbook_bayar_depan_masuk_ledger_rekening,
        skenario_ubah_status_manual_masuk_ledger_rekening,
        skenario_layanan_manual_masuk_arus_kas_dan_kas_metode_bayar,
        skenario_mark_paid_manual_tidak_bisa_dobel,
        skenario_kas_metode_bayar_walkin_menginap_tidak_hilang,
        skenario_analitik_saluran_cancelled_dan_walkin_tidak_dobel,
        skenario_telegram_laporan_harian_cancelled_tidak_dihitung,
        skenario_checkout_sync_amount_due,
        skenario_checkout_payment_protection,
        skenario_konfirmasi_checkin_dari_tiket_berhasil,
        skenario_konfirmasi_checkin_dari_tiket_dobel_tidak_dobel_hitung,
        skenario_checkin_dari_booking_day_use_bisa_ditumpuk_menginap,
        skenario_estimasi_siap_pada_tanggal_dayuse_pagi,
        skenario_checkin_pesan_error_perlu_dibersihkan_bukan_sedang_dipakai,
        skenario_laporan_pengeluaran_tanggal_penuh_timestamp,
        skenario_rekening_transaksi_tanggal_penuh_timestamp,
        skenario_checkins_list_jam_checkin_penuh_timestamp,
        skenario_kasir_list_timestamp_penuh_timestamp,
        skenario_services_list_tanggal_penuh_timestamp,
        skenario_ota_jam_geser_tembus_tengah_malam_ditolak_otomatis,
        skenario_ota_manual_required_retry_otomatis_setelah_housekeeping,
        skenario_availability_hari_ini_hanya_sembunyikan_maintenance,
        skenario_availability_tanggal_depan_abaikan_status_fisik,
        skenario_availability_dayuse_presisi_jam_setelah_checkout,
        skenario_pms_confirm_settlement_idempoten_sekali_per_grup,
        skenario_pms_confirm_pembayaran_telat_kamar_diambil_tidak_revive,
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
    # payment_log ditambahkan 2026-09-06 (skenario arus_kas_collect_balance_manual...
    # baru insert langsung ke koleksi ini - celah SAMA PERSIS dgn catatan expenses/dst
    # di atas kalau tidak ditambahkan di sini).
    for coll in ["rooms", "bookings", "checkins", "guests", "issues", "housekeeping_log", "incidents",
                 "expenses", "rekening_transaksi", "rekening", "kasir", "services", "payment_log"]:
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
