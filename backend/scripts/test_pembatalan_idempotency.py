"""Regresi idempotency_key untuk ajukan_pembatalan_ai (2026-08-14, MEDIUM - audit lanjutan
pola bug idempotency_key booking_request/2026-08-14, temuan §Lampiran D #6 dokumen
Engineering Safety - satu-satunya endpoint tulis PMS via _pms_http_retry yang belum dapat
idempotency_key di sweep malam itu).

Bug: endpoint AI-facing POST /integrasi-ai-bot/cancel-request (dipanggil lewat
_pms_ajukan_pembatalan, ai-chat-bot) dibungkus _pms_http_retry yang me-retry pada
httpx.ReadTimeout (PMS lambat balas krn kirim push+alert Telegram, BUKAN kegagalan
sungguhan) - PMS sisi endpoint sebelumnya 0 dedup, jadi retry identik bisa kirim 2
push/alert Telegram nyaris identik utk 1 permintaan pembatalan yang sama. Blast radius
lebih kecil dari booking_request/ganti-metode-pembayaran (non-binding, staf tetap review
manual, dan guard `cancel_request_status in CANCEL_STATUS_AKTIF` sudah cegah dobel-state)
tapi ditutup jg utk konsistensi pola.

Fix: idempotency_key (uuid4) dibuat SEKALI di ai-chat-bot (pms_connector.py, SEBELUM masuk
retry loop) dan dikirim identik di tiap percobaan. Sama pola dgn
_lakukan_ganti_metode_pembayaran (routes/payments.py) - ajukan_pembatalan_ai tidak insert
dokumen "hasil"-nya sendiri (fungsi ini UPDATE db.bookings yang sudah ada, bukan insert
dokumen baru), jadi dedup pakai collection kecil terpisah db.pembatalan_idempotency yang
menyimpan HASIL - retry dgn key sama dikembalikan hasil yang SAMA PERSIS tanpa mengulang
push/alert Telegram.

Sama pola AMAN dgn test_ganti_metode_pembayaran_idempotency.py: jalan in-process langsung
ke DB produksi yang sama, tapi semua data tes (booking) di bawah property_id PALSU (prefix
di bawah, tidak pernah muncul di property switcher UI manapun) dan dibersihkan total di
akhir run, sukses maupun gagal. send_push & kirim_alert_owner (Web Push/Telegram
SUNGGUHAN) di-monkeypatch TOTAL - skrip ini TIDAK PERNAH mengirim notifikasi nyata.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB, scope reports/laporan/checkin-checkout)
- routes/pembatalan.py TIDAK termasuk cakupan gerbang itu, jadi skrip ini BUKAN bagian dari
gerbang wajib push, cuma regresi tambahan utk bug idempotency spesifik ini (dijalankan jg
lewat scripts/test_regresi.py sekali sbg sanity check per instruksi audit malam ini).

Jalankan:
    cd backend && venv/bin/python -m scripts.test_pembatalan_idempotency
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-idempotency-pembatalan-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _wa_unik() -> str:
    return "62800" + uuid.uuid4().hex[:8]


async def _buat_booking_test(property_id: str) -> dict:
    """Booking aktif, check-in 10 hari lagi (>=72 jam - refund 100%, jam_tersisa tidak
    ambigu antar percobaan) & sudah lunas, satu-satunya prasyarat ajukan_pembatalan_ai
    (lihat guard status di fungsi itu)."""
    from core import db, now_iso
    checkin = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "kode": f"BKO-TEST-{uuid.uuid4().hex[:6].upper()}",
        "property_id": property_id, "no_hp": _wa_unik(), "nama_tamu": "Tamu Tes Idempotency",
        "tipe": "day_use", "status": "booking_paid", "payment_status": "paid",
        "amount_due": 175000, "jam_mulai": checkin,
        "room_id": str(uuid.uuid4()), "room_nomor": "T1", "room_tipe": "Standard",
        "cancel_request_status": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.bookings.insert_one(doc)
    return doc


class _PushTelegramCounter:
    """Pengganti send_push & kirim_alert_owner (Web Push/Telegram SUNGGUHAN) - hitung
    panggilan, TIDAK PERNAH benar-benar kirim notifikasi nyata."""
    def __init__(self):
        self.push_calls = 0
        self.telegram_calls = 0

    async def fake_send_push(self, *args, **kwargs):
        self.push_calls += 1
        return True

    async def fake_kirim_alert_owner(self, *args, **kwargs):
        self.telegram_calls += 1
        return True


def _pasang_mock(counter: _PushTelegramCounter):
    """Monkeypatch routes.push.send_push & routes.telegram_bot.kirim_alert_owner -
    ajukan_pembatalan_ai melakukan `from routes.X import Y` di DALAM fungsi tiap kali
    dipanggil (deferred import), jadi patch attribute modul di bawah ini otomatis kepakai
    tiap panggilan berikutnya tanpa perlu reload apa pun."""
    import routes.push as push_mod
    import routes.telegram_bot as telegram_mod
    asli = (push_mod.send_push, telegram_mod.kirim_alert_owner)
    push_mod.send_push = counter.fake_send_push
    telegram_mod.kirim_alert_owner = counter.fake_kirim_alert_owner
    return push_mod, telegram_mod, asli


def _lepas_mock(push_mod, telegram_mod, asli):
    push_mod.send_push, telegram_mod.kirim_alert_owner = asli


async def skenario_normal_single_call_satu_notifikasi() -> tuple:
    nama = "normal_single_call_satu_notifikasi_push_dan_telegram"
    from core import db
    from routes.pembatalan import ajukan_pembatalan_ai

    property_id = _property_id_test()
    b = await _buat_booking_test(property_id)
    counter = _PushTelegramCounter()
    push_mod, telegram_mod, asli = _pasang_mock(counter)
    try:
        key = str(uuid.uuid4())
        hasil = await ajukan_pembatalan_ai(b["kode"], b["no_hp"], property_id, "tes idempotency", idempotency_key=key)
        jumlah_dedup = await db.pembatalan_idempotency.count_documents({"idempotency_key": key})
        if counter.push_calls != 1:
            return (nama, f"FAIL - send_push terpanggil {counter.push_calls}x, harus 1x")
        if counter.telegram_calls != 1:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.telegram_calls}x, harus 1x")
        if jumlah_dedup != 1:
            return (nama, f"FAIL - dokumen dedup di DB = {jumlah_dedup}, harus 1")
        if not hasil.get("ok"):
            return (nama, f"FAIL - hasil ok=False: {hasil}")
        return (nama, "PASS")
    finally:
        _lepas_mock(push_mod, telegram_mod, asli)


async def skenario_retry_key_sama_tidak_dobel_notifikasi() -> tuple:
    """Reproduksi PERSIS pola bug: 2 panggilan identik (idempotency_key SAMA, simulasi
    retry _pms_http_retry setelah httpx ReadTimeout) - HARUS cuma 1 push & 1 alert
    Telegram (bukan 2 notifikasi hampir identik utk 1 permintaan pembatalan yang sama)."""
    nama = "retry_key_sama_tidak_dobel_notifikasi_push_dan_telegram"
    from routes.pembatalan import ajukan_pembatalan_ai

    property_id = _property_id_test()
    b = await _buat_booking_test(property_id)
    counter = _PushTelegramCounter()
    push_mod, telegram_mod, asli = _pasang_mock(counter)
    try:
        key = str(uuid.uuid4())
        hasil_1 = await ajukan_pembatalan_ai(b["kode"], b["no_hp"], property_id, "tes idempotency", idempotency_key=key)
        hasil_2 = await ajukan_pembatalan_ai(b["kode"], b["no_hp"], property_id, "tes idempotency", idempotency_key=key)

        if counter.push_calls != 1:
            return (nama, f"FAIL - send_push terpanggil {counter.push_calls}x total, harus 1x (retry bikin notifikasi dobel)")
        if counter.telegram_calls != 1:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.telegram_calls}x total, harus 1x (retry alert dobel)")
        if hasil_1 != hasil_2:
            return (nama, f"FAIL - retry kembalikan hasil BEDA: {hasil_1} vs {hasil_2}")
        return (nama, "PASS")
    finally:
        _lepas_mock(push_mod, telegram_mod, asli)


async def skenario_key_berbeda_booking_beda_tetap_2_notifikasi() -> tuple:
    """Pastikan ini idempotency key SUNGGUHAN (per-request unik), BUKAN heuristik jendela
    waktu - 2 permintaan pembatalan BEDA (booking beda, key beda, simulasi 2 tamu request
    pembatalan pada waktu yang berdekatan) tetap harus jadi 2 notifikasi terpisah, tidak
    boleh false-positive dianggap retry dari 1 permintaan yang sama."""
    nama = "key_berbeda_booking_beda_tetap_2_notifikasi_tidak_false_positive"
    from routes.pembatalan import ajukan_pembatalan_ai

    property_id = _property_id_test()
    b1 = await _buat_booking_test(property_id)
    b2 = await _buat_booking_test(property_id)
    counter = _PushTelegramCounter()
    push_mod, telegram_mod, asli = _pasang_mock(counter)
    try:
        hasil_1 = await ajukan_pembatalan_ai(b1["kode"], b1["no_hp"], property_id, "tes 1", idempotency_key=str(uuid.uuid4()))
        hasil_2 = await ajukan_pembatalan_ai(b2["kode"], b2["no_hp"], property_id, "tes 2", idempotency_key=str(uuid.uuid4()))

        if counter.push_calls != 2:
            return (nama, f"FAIL - send_push terpanggil {counter.push_calls}x, harus 2x (2 request beda salah dianggap duplikat)")
        if counter.telegram_calls != 2:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.telegram_calls}x, harus 2x (2 request nyata beda)")
        if hasil_1.get("kode") == hasil_2.get("kode"):
            return (nama, "FAIL - 2 request booking berbeda kembalikan kode booking yang SAMA")
        return (nama, "PASS")
    finally:
        _lepas_mock(push_mod, telegram_mod, asli)


async def main():
    skenario_list = [
        skenario_normal_single_call_satu_notifikasi,
        skenario_retry_key_sama_tidak_dobel_notifikasi,
        skenario_key_berbeda_booking_beda_tetap_2_notifikasi,
    ]

    print("--- Skenario idempotency ajukan_pembatalan_ai (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup TOTAL - hapus semua bookings ber-property_id berprefix tes ini, sukses maupun
    # gagal, PLUS dokumen pembatalan_idempotency terkait (collection itu tidak punya
    # property_id sendiri - dicocokkan lewat booking_id SEBELUM booking-nya dihapus).
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    test_bookings = await db.get_collection("bookings").find({"property_id": prop_pattern}, {"_id": 0, "id": 1}).to_list(200)
    booking_ids = [b["id"] for b in test_bookings]
    if booking_ids:
        r_dedup = await db.get_collection("pembatalan_idempotency").delete_many({"booking_id": {"$in": booking_ids}})
        if r_dedup.deleted_count:
            print(f"cleanup: {r_dedup.deleted_count} dokumen pembatalan_idempotency test dihapus")
    r_bookings = await db.get_collection("bookings").delete_many({"property_id": prop_pattern})
    if r_bookings.deleted_count:
        print(f"cleanup: {r_bookings.deleted_count} dokumen bookings test dihapus")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
