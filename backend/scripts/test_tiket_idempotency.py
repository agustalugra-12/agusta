"""Regresi idempotency_key untuk buat_issue (2026-08-14, MEDIUM - temuan #2 audit lanjutan
pola bug idempotency_key booking_request/2026-08-14).

Bug: endpoint AI-facing POST /integrasi-ai-bot/tiket (dipanggil lewat _pms_buat_tiket,
ai-chat-bot) dibungkus _pms_http_retry yang me-retry pada httpx.ReadTimeout (PMS lambat
balas krn sedang kirim Web Push, BUKAN kegagalan sungguhan) - endpoint sisi PMS-nya
(ai_bot_buat_tiket -> buat_issue) sebelumnya plain insert_one tanpa dedup sama sekali,
jadi retry identik = 1 baris db.issues duplikat + 1 push notif dobel ke staf. Dampaknya
lebih ringan dari booking_request/ganti-metode-pembayaran (bukan data finansial/tamu),
tapi tetap membingungkan staf ("tiket mana yang harus ditindak?") - diperbaiki dgn pola
yang sama demi konsistensi.

Fix: idempotency_key (uuid4) dibuat SEKALI di ai-chat-bot (pms_connector.py, SEBELUM masuk
retry loop) dan dikirim identik di tiap percobaan. buat_issue cek db.issues (index unique
sparse "idempotency_key", server.py) SEBELUM insert - kalau key sudah pernah dipakai,
kembalikan dokumen tiket yang sudah ada & JANGAN ulangi push notif.

Sama pola AMAN dgn test_booking_request_idempotency.py: jalan in-process langsung ke DB
produksi yang sama, tapi semua data tes di bawah property_id PALSU (prefix di bawah, tidak
pernah muncul di property switcher UI manapun) dan dibersihkan total di akhir run, sukses
maupun gagal. send_push (Web Push SUNGGUHAN) di-monkeypatch total - skrip ini TIDAK PERNAH
mengirim push notif nyata.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB, scope reports/laporan/checkin-checkout)
- routes/issues.py TIDAK termasuk cakupan gerbang itu, jadi skrip ini BUKAN bagian dari
gerbang wajib push, cuma regresi tambahan utk bug idempotency spesifik ini.

Jalankan:
    cd backend && venv/bin/python -m scripts.test_tiket_idempotency
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-idempotency-tiket-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _wa_unik() -> str:
    return "62800" + uuid.uuid4().hex[:8]


def _user_ai_bot() -> dict:
    return {"id": "ai-chat-bot", "nama": "AI Chat Bot", "role": "owner"}


class _PushCounter:
    """Pengganti send_push (Web Push sungguhan) - hitung panggilan, TIDAK PERNAH benar-benar
    kirim push notif nyata."""
    def __init__(self):
        self.send_push_calls = 0

    async def fake_send_push(self, *args, **kwargs):
        self.send_push_calls += 1


def _pasang_mock(counter: _PushCounter):
    """Monkeypatch routes.push.send_push - buat_issue melakukan `from routes.push import
    send_push` di level MODUL routes/issues.py (bukan deferred di dalam fungsi), jadi patch
    langsung di objek yang sudah di-import ke namespace routes.issues (bukan routes.push)."""
    import routes.issues as issues_mod
    asli = issues_mod.send_push
    issues_mod.send_push = counter.fake_send_push
    return issues_mod, asli


def _lepas_mock(issues_mod, asli):
    issues_mod.send_push = asli


async def skenario_normal_single_call_satu_tiket() -> tuple:
    nama = "normal_single_call_satu_tiket_dan_push_sekali"
    from core import db
    from routes.issues import buat_issue

    property_id = _property_id_test()
    counter = _PushCounter()
    issues_mod, asli = _pasang_mock(counter)
    try:
        key = str(uuid.uuid4())
        hasil = await buat_issue(
            "complaint", "AC kamar tidak dingin", _user_ai_bot(), property_id,
            nama_tamu="Tamu Tes Idempotency", no_hp=_wa_unik(), idempotency_key=key,
        )
        jumlah_dokumen = await db.issues.count_documents({"property_id": property_id})
        if jumlah_dokumen != 1:
            return (nama, f"FAIL - dokumen issues di DB = {jumlah_dokumen}, harus 1")
        if hasil.get("status") != "open":
            return (nama, f"FAIL - status = {hasil.get('status')!r}, harus 'open'")
        if counter.send_push_calls != 1:
            return (nama, f"FAIL - send_push terpanggil {counter.send_push_calls}x, harus 1x")
        return (nama, "PASS")
    finally:
        _lepas_mock(issues_mod, asli)


async def skenario_retry_key_sama_tidak_dobel_tiket() -> tuple:
    """Reproduksi PERSIS pola bug: 2 panggilan identik (idempotency_key SAMA, simulasi
    retry _pms_http_retry setelah httpx ReadTimeout) - HARUS cuma 1 tiket & 1 push (bukan
    2 baris issues duplikat + 2 push notif ke staf)."""
    nama = "retry_key_sama_tidak_dobel_tiket_dan_push"
    from core import db
    from routes.issues import buat_issue

    property_id = _property_id_test()
    counter = _PushCounter()
    issues_mod, asli = _pasang_mock(counter)
    try:
        key = str(uuid.uuid4())
        no_hp = _wa_unik()
        hasil_1 = await buat_issue(
            "maintenance", "Keran wastafel bocor", _user_ai_bot(), property_id,
            nama_tamu="Tamu Tes Idempotency", no_hp=no_hp, idempotency_key=key,
        )
        hasil_2 = await buat_issue(
            "maintenance", "Keran wastafel bocor", _user_ai_bot(), property_id,
            nama_tamu="Tamu Tes Idempotency", no_hp=no_hp, idempotency_key=key,
        )

        jumlah_dokumen = await db.issues.count_documents({"property_id": property_id})
        if jumlah_dokumen != 1:
            return (nama, f"FAIL - dokumen issues di DB = {jumlah_dokumen}, harus 1 (retry bikin tiket duplikat)")
        if hasil_1.get("id") != hasil_2.get("id"):
            return (nama, f"FAIL - percobaan ke-2 kembalikan tiket BEDA (id {hasil_1.get('id')} vs {hasil_2.get('id')})")
        if counter.send_push_calls != 1:
            return (nama, f"FAIL - send_push terpanggil {counter.send_push_calls}x total, harus 1x (retry tidak boleh ulangi push)")
        return (nama, "PASS")
    finally:
        _lepas_mock(issues_mod, asli)


async def skenario_key_berbeda_tetap_2_tiket() -> tuple:
    """Pastikan ini idempotency key SUNGGUHAN (per-request unik), BUKAN heuristik jendela
    waktu - 2 tiket BEDA (key beda) yang kebetulan dibuat nyaris bersamaan (mis. 2 komplain
    berbeda dari tamu yang sama) tetap harus jadi 2 dokumen terpisah, tidak boleh
    false-positive dianggap duplikat."""
    nama = "key_berbeda_tetap_2_tiket_tidak_false_positive"
    from core import db
    from routes.issues import buat_issue

    property_id = _property_id_test()
    counter = _PushCounter()
    issues_mod, asli = _pasang_mock(counter)
    try:
        no_hp = _wa_unik()
        hasil_1 = await buat_issue(
            "complaint", "AC kamar tidak dingin", _user_ai_bot(), property_id,
            nama_tamu="Tamu Tes Idempotency", no_hp=no_hp, idempotency_key=str(uuid.uuid4()),
        )
        hasil_2 = await buat_issue(
            "complaint", "Air panas tidak jalan", _user_ai_bot(), property_id,
            nama_tamu="Tamu Tes Idempotency", no_hp=no_hp, idempotency_key=str(uuid.uuid4()),
        )

        jumlah_dokumen = await db.issues.count_documents({"property_id": property_id})
        if jumlah_dokumen != 2:
            return (nama, f"FAIL - dokumen issues di DB = {jumlah_dokumen}, harus 2 (2 tiket BEDA salah dianggap duplikat)")
        if hasil_1.get("id") == hasil_2.get("id"):
            return (nama, "FAIL - 2 tiket beda key kembalikan dokumen yang SAMA")
        if counter.send_push_calls != 2:
            return (nama, f"FAIL - send_push terpanggil {counter.send_push_calls}x, harus 2x (2 tiket nyata beda)")
        return (nama, "PASS")
    finally:
        _lepas_mock(issues_mod, asli)


async def main():
    skenario_list = [
        skenario_normal_single_call_satu_tiket,
        skenario_retry_key_sama_tidak_dobel_tiket,
        skenario_key_berbeda_tetap_2_tiket,
    ]

    print("--- Skenario idempotency tiket/issues (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup TOTAL - hapus semua issues ber-property_id berprefix tes ini, sukses maupun
    # gagal (idempotency_key ikut terhapus otomatis bersama dokumennya, tidak ada
    # collection dedup terpisah di fix ini - beda dari ganti_metode_pembayaran).
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    r = await db.get_collection("issues").delete_many({"property_id": prop_pattern})
    if r.deleted_count:
        print(f"cleanup: {r.deleted_count} dokumen issues test dihapus")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
