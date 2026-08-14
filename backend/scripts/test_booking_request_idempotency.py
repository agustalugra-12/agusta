"""Regresi idempotency_key untuk buat_booking_request (2026-08-14, bug nyata: tamu Bagus
Wira kirim 1 pesan WhatsApp "1 malam" tapi menghasilkan 2 db.booking_requests terpisah
15.8 detik - ai-chat-bot punya retry (_pms_http_retry) untuk error jaringan transient,
tapi httpx ReadTimeout (PMS lambat balas krn sibuk kirim alert Telegram/WA, BUKAN
kegagalan sungguhan) ikut ter-retry, dan endpoint PMS-nya (ai_bot_buat_booking_request ->
buat_booking_request) 0 deduplikasi - tiap POST bikin dokumen baru tanpa syarat.

Fix: idempotency_key dibuat SEKALI di ai-chat-bot (pms_connector.py, SEBELUM masuk retry
loop) dan dikirim identik di tiap percobaan - PMS cek dulu apakah key itu sudah pernah
dipakai (db.booking_requests, index unique sparse "idempotency_key", server.py) sebelum
insert; kalau sudah ada, kembalikan dokumen yang sudah ada & JANGAN ulangi alert
Telegram/WA (skenario 2 di bawah). Skenario 3 memastikan ini idempotency key SUNGGUHAN,
bukan heuristik jendela waktu - 2 request BEDA yang kebetulan berdekatan tetap 2 dokumen.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB utk reports/laporan/checkin-checkout,
lihat CLAUDE.md) - booking_requests.py TIDAK termasuk cakupan gerbang itu, jadi skrip ini
BUKAN bagian dari gerbang wajib push, cuma regresi tambahan utk bug idempotency spesifik
ini. Sama pola AMAN dgn test_regresi.py: jalan in-process langsung ke DB produksi yang
sama, tapi semua data tes di bawah property_id PALSU (prefix di bawah, tidak pernah
muncul di property switcher UI manapun) dan dibersihkan total di akhir run, sukses
maupun gagal. Efek samping nyata (Telegram/Web Push) di-monkeypatch total - skrip ini
TIDAK PERNAH mengirim pesan sungguhan.

Jalankan:
    cd backend && venv/bin/python -m scripts.test_booking_request_idempotency
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-idempotency-booking-request-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _wa_unik() -> str:
    return "62800" + uuid.uuid4().hex[:8]


def _tanggal_checkin_aman() -> str:
    # +2 hari dari UTC sekarang - jauh cukup dari batas "tidak boleh masa lalu" (WITA)
    # supaya tidak flaky di sekitar pergantian hari.
    return (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()


def _data_dasar(property_id: str, idempotency_key) -> dict:
    return {
        "nama_tamu": "Tamu Tes Idempotency",
        "no_hp": _wa_unik(),
        "tipe": "day_use",
        "tanggal_checkin": _tanggal_checkin_aman(),
        "jam_checkin": "12:00",  # >= 11:00 WITA (guard minimum Day Use)
        # room_tipe SENGAJA kosong - _hitung_preview_harga return None dgn aman kalau
        # room_tipe tidak ditemukan, tidak perlu bikin db.rooms utk tes ini.
        # payment_option SENGAJA tidak diisi - _coba_auto_approve_day_use no-op kalau
        # payment_option_diminta bukan dp50/full, status tetap "waiting_approval" & TIDAK
        # menyentuh create_reservation/Tripay/kamar sama sekali (murni jalur review staf).
        "idempotency_key": idempotency_key,
    }


class _AlertCounter:
    """Pengganti kirim_alert_owner & send_push - hitung panggilan, TIDAK PERNAH kirim
    apa pun sungguhan (Telegram/Web Push nyata)."""
    def __init__(self):
        self.kirim_alert_owner_calls = 0
        self.send_push_calls = 0

    async def kirim_alert_owner(self, *args, **kwargs):
        self.kirim_alert_owner_calls += 1

    async def send_push(self, *args, **kwargs):
        self.send_push_calls += 1


def _pasang_mock_alert():
    """Monkeypatch modul routes.telegram_bot.kirim_alert_owner & routes.push.send_push -
    buat_booking_request melakukan `from routes.X import Y` di DALAM fungsi tiap kali
    dipanggil (deferred import), jadi patch attribute modul di bawah ini otomatis
    kepakai tiap panggilan berikutnya tanpa perlu reload apa pun."""
    import routes.telegram_bot as telegram_bot_mod
    import routes.push as push_mod
    counter = _AlertCounter()
    asli = (telegram_bot_mod.kirim_alert_owner, push_mod.send_push)
    telegram_bot_mod.kirim_alert_owner = counter.kirim_alert_owner
    push_mod.send_push = counter.send_push
    return counter, telegram_bot_mod, push_mod, asli


def _lepas_mock_alert(telegram_bot_mod, push_mod, asli):
    telegram_bot_mod.kirim_alert_owner, push_mod.send_push = asli


async def skenario_normal_single_call_satu_dokumen() -> tuple:
    nama = "normal_single_call_satu_dokumen_dan_alert_sekali"
    from core import db
    from routes.booking_requests import buat_booking_request

    property_id = _property_id_test()
    counter, telegram_bot_mod, push_mod, asli = _pasang_mock_alert()
    try:
        data = _data_dasar(property_id, str(uuid.uuid4()))
        hasil = await buat_booking_request(data, property_id)
        jumlah_dokumen = await db.booking_requests.count_documents({"property_id": property_id})
        if jumlah_dokumen != 1:
            return (nama, f"FAIL - dokumen di DB = {jumlah_dokumen}, harus 1")
        if hasil.get("status") != "waiting_approval":
            return (nama, f"FAIL - status = {hasil.get('status')!r}, harus 'waiting_approval'")
        if counter.kirim_alert_owner_calls != 1:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.kirim_alert_owner_calls}x, harus 1x")
        if counter.send_push_calls != 1:
            return (nama, f"FAIL - send_push terpanggil {counter.send_push_calls}x, harus 1x")
        return (nama, "PASS")
    finally:
        _lepas_mock_alert(telegram_bot_mod, push_mod, asli)


async def skenario_retry_idempotency_key_sama_tidak_dobel() -> tuple:
    """Reproduksi PERSIS skenario bug Bagus Wira: 2 POST identik (idempotency_key SAMA,
    simulasi retry _pms_http_retry ai-chat-bot setelah httpx ReadTimeout) - HARUS cuma 1
    dokumen & alert Telegram/WA HANYA sekali (bukan dobel)."""
    nama = "retry_idempotency_key_sama_tidak_dobel_dokumen_dan_alert"
    from core import db
    from routes.booking_requests import buat_booking_request

    property_id = _property_id_test()
    counter, telegram_bot_mod, push_mod, asli = _pasang_mock_alert()
    try:
        key = str(uuid.uuid4())
        data = _data_dasar(property_id, key)
        hasil_1 = await buat_booking_request(data, property_id)
        hasil_2 = await buat_booking_request(dict(data), property_id)  # payload identik, key SAMA - simulasi retry

        jumlah_dokumen = await db.booking_requests.count_documents({"property_id": property_id})
        if jumlah_dokumen != 1:
            return (nama, f"FAIL - dokumen di DB = {jumlah_dokumen}, harus 1 (retry bikin duplikat)")
        if hasil_1.get("id") != hasil_2.get("id"):
            return (nama, f"FAIL - percobaan ke-2 kembalikan dokumen BEDA (id {hasil_1.get('id')} vs {hasil_2.get('id')})")
        if counter.kirim_alert_owner_calls != 1:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.kirim_alert_owner_calls}x total, harus 1x (retry tidak boleh ulangi alert)")
        if counter.send_push_calls != 1:
            return (nama, f"FAIL - send_push terpanggil {counter.send_push_calls}x total, harus 1x")
        return (nama, "PASS")
    finally:
        _lepas_mock_alert(telegram_bot_mod, push_mod, asli)


async def skenario_key_berbeda_tetap_2_dokumen() -> tuple:
    """Pastikan ini idempotency key SUNGGUHAN (per-request unik), BUKAN heuristik jendela
    waktu - 2 permintaan BEDA (key beda) yang kebetulan dibuat nyaris bersamaan tetap
    harus jadi 2 dokumen terpisah, tidak boleh false-positive dianggap duplikat."""
    nama = "key_berbeda_tetap_2_dokumen_tidak_false_positive"
    from core import db
    from routes.booking_requests import buat_booking_request

    property_id = _property_id_test()
    counter, telegram_bot_mod, push_mod, asli = _pasang_mock_alert()
    try:
        hasil_1 = await buat_booking_request(_data_dasar(property_id, str(uuid.uuid4())), property_id)
        hasil_2 = await buat_booking_request(_data_dasar(property_id, str(uuid.uuid4())), property_id)

        jumlah_dokumen = await db.booking_requests.count_documents({"property_id": property_id})
        if jumlah_dokumen != 2:
            return (nama, f"FAIL - dokumen di DB = {jumlah_dokumen}, harus 2 (2 request BEDA salah dianggap duplikat)")
        if hasil_1.get("id") == hasil_2.get("id"):
            return (nama, "FAIL - 2 request beda key kembalikan dokumen yang SAMA")
        if counter.kirim_alert_owner_calls != 2:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.kirim_alert_owner_calls}x, harus 2x (2 request nyata beda)")
        return (nama, "PASS")
    finally:
        _lepas_mock_alert(telegram_bot_mod, push_mod, asli)


async def main():
    skenario_list = [
        skenario_normal_single_call_satu_dokumen,
        skenario_retry_idempotency_key_sama_tidak_dobel,
        skenario_key_berbeda_tetap_2_dokumen,
    ]

    print("--- Skenario idempotency booking_request (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup TOTAL - hapus semua booking_requests ber-property_id berprefix tes ini,
    # sukses maupun gagal (tidak ada db.rooms/bookings yang tersentuh skenario di atas).
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    r = await db.get_collection("booking_requests").delete_many({"property_id": prop_pattern})
    if r.deleted_count:
        print(f"cleanup: {r.deleted_count} dokumen booking_requests test dihapus")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
