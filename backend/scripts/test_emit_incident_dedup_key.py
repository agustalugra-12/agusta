"""Regresi dedup_key ai_claim_mismatch (2026-08-14, MEDIUM-LOW - temuan #3 audit lanjutan
pola bug idempotency_key booking_request/2026-08-14).

Bug: `_pms_emit_incident` (ai-chat-bot, connectors/pms_connector.py) dibungkus
_pms_http_retry - retry pada httpx.ReadTimeout (PMS lambat balas, bukan gagal sungguhan)
sebelumnya bikin 2 incident IDENTIK di Action Center PMS tiap kali terjadi. BEDA dari 3
temuan lain malam ini - `create_incident` (routes/incidents.py, PMS) SUDAH PUNYA guard
dedup_key sejak 2026-08-12 (dipakai collection_required/tripay_settlement_not_posted dst),
tapi 2 titik panggil `_pms_emit_incident` di ai-chat-bot (server.py, guard
klaim_sukses_tanpa_bukti & ai_judge) TIDAK PERNAH mengisinya - proteksi yang sudah ada jadi
inert bukan krn PMS kurang, tapi krn ai-chat-bot tidak pernah kirim key-nya.

Fix (SISI ai-chat-bot, server.py) - dedup_key dibuat DETERMINISTIK per kejadian:
    f"ai_claim_mismatch:{source_guard}:{conv_id}:{len(conv['messages'])}"
BUKAN random/timestamp (itu akan menggagalkan dedup-nya sendiri) - len(conv["messages"])
stabil sepanjang retry loop 1 giliran chat (guest message sudah di-append di awal giliran,
AI message baru di-append SETELAH blok emit incident selesai), tapi beda antar giliran
berbeda (tiap giliran baru selalu nambah pesan).

Skrip ini TIDAK menguji ulang mekanisme dedup_key generik di create_incident (itu sudah
established & dipakai fitur lain sejak 2026-08-12) - fokusnya membuktikan WIRING fix ini
benar: dedup_key BERBENTUK PERSIS seperti yang sekarang dikirim ai-chat-bot (prefix
"ai_claim_mismatch:<source_guard>:<conv_id>:<n>") betul2 mencegah 2 incident dari 1
kejadian yang sama (retry), TAPI TETAP membuat 2 incident terpisah utk 2 kejadian NYATA
yang beda (giliran chat berbeda / source_guard berbeda) - supaya tidak over-dedup incident
yang harusnya tetap masing2 tampil ke owner.

Sama pola AMAN dgn test_booking_request_idempotency.py: jalan in-process langsung ke DB
produksi yang sama, property_id PALSU, dibersihkan total di akhir run. Push Telegram
urgent (_push_incident_urgent) di-monkeypatch total - skrip ini TIDAK PERNAH mengirim
pesan Telegram sungguhan.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB, scope reports/laporan/checkin-checkout)
- routes/incidents.py TIDAK termasuk cakupan gerbang itu, jadi skrip ini BUKAN bagian dari
gerbang wajib push, cuma regresi tambahan utk bug dedup_key spesifik ini.

Jalankan:
    cd backend && venv/bin/python -m scripts.test_emit_incident_dedup_key
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-idempotency-emit-incident-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _dedup_key(source_guard: str, conv_id: str, n_messages: int) -> str:
    """Reproduksi PERSIS format dedup_key yang sekarang dikirim server.py (ai-chat-bot) -
    lihat komentar di 2 titik panggil _pms_emit_incident, server.py."""
    return f"ai_claim_mismatch:{source_guard}:{conv_id}:{n_messages}"


class _TelegramPushCounter:
    """Pengganti _push_incident_urgent (Telegram sungguhan) - hitung panggilan, TIDAK
    PERNAH benar-benar kirim pesan Telegram nyata."""
    def __init__(self):
        self.push_calls = 0

    async def fake_push_incident_urgent(self, *args, **kwargs):
        self.push_calls += 1


def _pasang_mock(counter: _TelegramPushCounter):
    """create_incident (routes/incidents.py) `from routes.telegram_bot import
    _push_incident_urgent` di DALAM fungsi tiap kali severity=="urgent" (deferred import) -
    patch attribute modul routes.telegram_bot langsung."""
    import routes.telegram_bot as telegram_bot_mod
    asli = telegram_bot_mod._push_incident_urgent
    telegram_bot_mod._push_incident_urgent = counter.fake_push_incident_urgent
    return telegram_bot_mod, asli


def _lepas_mock(telegram_bot_mod, asli):
    telegram_bot_mod._push_incident_urgent = asli


async def skenario_normal_single_call_satu_incident() -> tuple:
    nama = "normal_single_call_satu_incident"
    from core import db
    from routes.incidents import create_incident

    property_id = _property_id_test()
    counter = _TelegramPushCounter()
    telegram_bot_mod, asli = _pasang_mock(counter)
    try:
        conv_id = str(uuid.uuid4())
        key = _dedup_key("klaim_sukses_tanpa_bukti", conv_id, 4)
        hasil = await create_incident(
            event_type="ai_claim_mismatch", severity="warning", title="Tes dedup_key",
            detail="skenario tes", source="ai-chat-bot", property_id=property_id, dedup_key=key,
        )
        jumlah = await db.incidents.count_documents({"property_id": property_id})
        if jumlah != 1:
            return (nama, f"FAIL - dokumen incidents di DB = {jumlah}, harus 1")
        if hasil is None or hasil.get("dedup_key") != key:
            return (nama, f"FAIL - hasil create_incident tidak sesuai: {hasil!r}")
        return (nama, "PASS")
    finally:
        _lepas_mock(telegram_bot_mod, asli)


async def skenario_retry_dedup_key_sama_tidak_dobel_incident() -> tuple:
    """Reproduksi PERSIS pola bug: 2 panggilan create_incident dgn dedup_key SAMA (simulasi
    retry _pms_http_retry setelah httpx ReadTimeout mengirim payload identik 2x) - HARUS
    cuma 1 incident & 1 push Telegram urgent (bukan 2 baris identik + 2 notifikasi urgent
    yang membanjiri owner utk 1 kejadian yang sama)."""
    nama = "retry_dedup_key_sama_tidak_dobel_incident_dan_push_urgent"
    from core import db
    from routes.incidents import create_incident

    property_id = _property_id_test()
    counter = _TelegramPushCounter()
    telegram_bot_mod, asli = _pasang_mock(counter)
    try:
        conv_id = str(uuid.uuid4())
        key = _dedup_key("klaim_sukses_tanpa_bukti", conv_id, 6)
        hasil_1 = await create_incident(
            event_type="ai_claim_mismatch", severity="urgent", title="Tes dedup_key percobaan 1",
            detail="percobaan asli", source="ai-chat-bot", property_id=property_id, dedup_key=key,
        )
        hasil_2 = await create_incident(
            event_type="ai_claim_mismatch", severity="urgent", title="Tes dedup_key percobaan 2 (retry)",
            detail="retry _pms_http_retry - payload identik", source="ai-chat-bot", property_id=property_id, dedup_key=key,
        )

        jumlah = await db.incidents.count_documents({"property_id": property_id})
        if jumlah != 1:
            return (nama, f"FAIL - dokumen incidents di DB = {jumlah}, harus 1 (retry bikin incident duplikat)")
        if hasil_1 is None:
            return (nama, "FAIL - percobaan pertama harus berhasil buat incident (hasil_1 None)")
        if hasil_2 is not None:
            return (nama, f"FAIL - percobaan ke-2 (retry, key sama) harus di-skip (return None), malah: {hasil_2!r}")
        if counter.push_calls != 1:
            return (nama, f"FAIL - push Telegram urgent terpanggil {counter.push_calls}x total, harus 1x (retry tidak boleh ulangi notifikasi urgent)")
        return (nama, "PASS")
    finally:
        _lepas_mock(telegram_bot_mod, asli)


async def skenario_key_berbeda_giliran_beda_tetap_2_incident() -> tuple:
    """Pastikan ini dedup key SUNGGUHAN per-giliran (bukan heuristik global per-conv) -
    2 kejadian ai_claim_mismatch NYATA dari conv yang SAMA tapi GILIRAN chat berbeda
    (len(conv["messages"]) beda, persis seperti fix di server.py) tetap harus jadi 2
    incident terpisah, tidak boleh false-positive dianggap retry dari kejadian yang sama."""
    nama = "key_berbeda_giliran_beda_tetap_2_incident_tidak_false_positive"
    from core import db
    from routes.incidents import create_incident

    property_id = _property_id_test()
    counter = _TelegramPushCounter()
    telegram_bot_mod, asli = _pasang_mock(counter)
    try:
        conv_id = str(uuid.uuid4())
        key_giliran_1 = _dedup_key("klaim_sukses_tanpa_bukti", conv_id, 4)
        key_giliran_2 = _dedup_key("klaim_sukses_tanpa_bukti", conv_id, 8)  # giliran chat berikutnya, conv sama
        hasil_1 = await create_incident(
            event_type="ai_claim_mismatch", severity="warning", title="Kejadian giliran 1",
            detail="giliran chat pertama", source="ai-chat-bot", property_id=property_id, dedup_key=key_giliran_1,
        )
        hasil_2 = await create_incident(
            event_type="ai_claim_mismatch", severity="warning", title="Kejadian giliran 2",
            detail="giliran chat KEDUA - kejadian ai_claim_mismatch nyata yang beda", source="ai-chat-bot",
            property_id=property_id, dedup_key=key_giliran_2,
        )

        jumlah = await db.incidents.count_documents({"property_id": property_id})
        if jumlah != 2:
            return (nama, f"FAIL - dokumen incidents di DB = {jumlah}, harus 2 (2 giliran nyata beda salah dianggap duplikat)")
        if hasil_1 is None or hasil_2 is None:
            return (nama, f"FAIL - kedua panggilan harus berhasil buat incident, dapat hasil_1={hasil_1!r} hasil_2={hasil_2!r}")
        if hasil_1.get("id") == hasil_2.get("id"):
            return (nama, "FAIL - 2 giliran beda key kembalikan incident yang SAMA")

        # Sekaligus buktikan source_guard beda (giliran SAMA) juga tidak saling dedup -
        # ai_judge & klaim_sukses_tanpa_bukti bisa sama2 terpicu di giliran yang sama.
        key_source_lain = _dedup_key("ai_judge", conv_id, 4)  # giliran sama dgn key_giliran_1, source beda
        hasil_3 = await create_incident(
            event_type="ai_claim_mismatch", severity="warning", title="Kejadian ai_judge giliran 1",
            detail="source_guard beda, giliran sama", source="ai-chat-bot",
            property_id=property_id, dedup_key=key_source_lain,
        )
        jumlah_akhir = await db.incidents.count_documents({"property_id": property_id})
        if jumlah_akhir != 3 or hasil_3 is None:
            return (nama, f"FAIL - source_guard beda (giliran sama) harus tetap incident terpisah, dokumen di DB = {jumlah_akhir}, hasil_3={hasil_3!r}")
        return (nama, "PASS")
    finally:
        _lepas_mock(telegram_bot_mod, asli)


async def main():
    skenario_list = [
        skenario_normal_single_call_satu_incident,
        skenario_retry_dedup_key_sama_tidak_dobel_incident,
        skenario_key_berbeda_giliran_beda_tetap_2_incident,
    ]

    print("--- Skenario dedup_key ai_claim_mismatch (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup TOTAL - hapus semua incidents ber-property_id berprefix tes ini, sukses maupun
    # gagal (correlation_groups tidak disentuh - dedup_key generik di sini tidak memicu
    # burst/entity correlation, semua skenario < BURST_THRESHOLD & tanpa meta.booking_id).
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    r = await db.get_collection("incidents").delete_many({"property_id": prop_pattern})
    if r.deleted_count:
        print(f"cleanup: {r.deleted_count} dokumen incidents test dihapus")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
