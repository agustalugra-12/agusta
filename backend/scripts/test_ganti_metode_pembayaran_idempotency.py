"""Regresi idempotency_key untuk _lakukan_ganti_metode_pembayaran (2026-08-14, HIGH -
temuan #1 audit lanjutan pola bug idempotency_key booking_request/2026-08-14).

Bug: endpoint AI-facing POST /integrasi-ai-bot/ganti-metode-pembayaran (dipanggil lewat
_pms_ganti_metode_pembayaran, ai-chat-bot) dibungkus _pms_http_retry yang me-retry pada
httpx.ReadTimeout (PMS lambat balas krn menunggu Tripay + kirim WA, BUKAN kegagalan
sungguhan) - PMS sisi endpoint 0 dedup, jadi retry identik = 2 transaksi Tripay LIVE +
2 link pembayaran BEDA terkirim WA ke tamu yang sama, membingungkan di tengah checkout
(real financial/guest-facing exposure).

Fix: idempotency_key (uuid4) dibuat SEKALI di ai-chat-bot (pms_connector.py, SEBELUM masuk
retry loop) dan dikirim identik di tiap percobaan. Beda dari booking_request/issues (yang
insert dokumen baru ke collection sendiri) - _lakukan_ganti_metode_pembayaran tidak insert
dokumen "hasil"-nya sendiri, jadi dedup pakai collection kecil terpisah
db.ganti_metode_pembayaran_idempotency yang menyimpan HASIL (bukan cuma existence flag) -
retry dgn key sama dikembalikan hasil yang SAMA PERSIS tanpa memanggil Tripay/kirim WA lagi.

Sama pola AMAN dgn test_booking_request_idempotency.py: jalan in-process langsung ke DB
produksi yang sama, tapi semua data tes (booking) di bawah property_id PALSU (prefix di
bawah, tidak pernah muncul di property switcher UI manapun) dan dibersihkan total di akhir
run, sukses maupun gagal. tripay_create_transaction (Tripay API SUNGGUHAN, transaksi
finansial nyata) & _kirim_dengan_alert (WhatsApp SUNGGUHAN) di-monkeypatch TOTAL - skrip
ini TIDAK PERNAH membuat transaksi Tripay nyata atau mengirim WA sungguhan.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB, scope reports/laporan/checkin-checkout)
- routes/payments.py TIDAK termasuk cakupan gerbang itu, jadi skrip ini BUKAN bagian dari
gerbang wajib push, cuma regresi tambahan utk bug idempotency spesifik ini.

Jalankan:
    cd backend && venv/bin/python -m scripts.test_ganti_metode_pembayaran_idempotency
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-idempotency-ganti-metode-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _wa_unik() -> str:
    return "62800" + uuid.uuid4().hex[:8]


async def _buat_booking_test(property_id: str) -> dict:
    """Booking Day Use minimal, status booking_pending & belum lunas - satu-satunya
    prasyarat _lakukan_ganti_metode_pembayaran (lihat guard status di fungsi itu)."""
    from core import db, now_iso
    doc = {
        "id": str(uuid.uuid4()), "kode": f"BKO-TEST-{uuid.uuid4().hex[:6].upper()}",
        "property_id": property_id, "no_hp": _wa_unik(), "nama_tamu": "Tamu Tes Idempotency",
        "tipe": "day_use", "status": "booking_pending", "payment_status": "pending",
        "room_id": str(uuid.uuid4()), "room_nomor": "T1", "room_tipe": "Standard",
        "total": 175000, "dp_min": 87500, "group_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.bookings.insert_one(doc)
    return doc


class _TripayWaCounter:
    """Pengganti tripay_create_transaction (Tripay API sungguhan) & _kirim_dengan_alert
    (WhatsApp sungguhan) - hitung panggilan, TIDAK PERNAH benar-benar hubungi Tripay/kirim
    WA nyata. Tiap panggilan tripay palsu menghasilkan order_id/checkout_url UNIK supaya
    skenario "key beda -> 2 transaksi terpisah" bisa dibuktikan (checkout_url beda)."""
    def __init__(self):
        self.tripay_calls = 0
        self.wa_calls = 0

    async def fake_tripay_create_transaction(self, body):
        self.tripay_calls += 1
        order_id = f"TEST-{uuid.uuid4().hex[:10].upper()}"
        return {
            "booking_id": body.booking_id, "order_id": order_id,
            "reference": f"REF-{order_id}", "checkout_url": f"https://tripay.test/{order_id}",
            "amount": 87500,
        }

    async def fake_kirim_dengan_alert(self, *args, **kwargs):
        self.wa_calls += 1
        return True


def _pasang_mock(counter: _TripayWaCounter):
    """Monkeypatch modul routes.tripay.tripay_create_transaction & routes.pesan_whatsapp.
    _kirim_dengan_alert - _lakukan_ganti_metode_pembayaran melakukan `from routes.X import
    Y` di DALAM fungsi tiap kali dipanggil (deferred import), jadi patch attribute modul
    di bawah ini otomatis kepakai tiap panggilan berikutnya tanpa perlu reload apa pun."""
    import routes.tripay as tripay_mod
    import routes.pesan_whatsapp as wa_mod
    asli = (tripay_mod.tripay_create_transaction, wa_mod._kirim_dengan_alert)
    tripay_mod.tripay_create_transaction = counter.fake_tripay_create_transaction
    wa_mod._kirim_dengan_alert = counter.fake_kirim_dengan_alert
    return tripay_mod, wa_mod, asli


def _lepas_mock(tripay_mod, wa_mod, asli):
    tripay_mod.tripay_create_transaction, wa_mod._kirim_dengan_alert = asli


async def skenario_normal_single_call_satu_transaksi() -> tuple:
    nama = "normal_single_call_satu_transaksi_tripay_dan_wa_sekali"
    from core import db
    from routes.payments import _lakukan_ganti_metode_pembayaran

    property_id = _property_id_test()
    b = await _buat_booking_test(property_id)
    counter = _TripayWaCounter()
    tripay_mod, wa_mod, asli = _pasang_mock(counter)
    try:
        key = str(uuid.uuid4())
        hasil = await _lakukan_ganti_metode_pembayaran(
            b["id"], "QRIS2", "dp50", "Tes Idempotency", property_id, idempotency_key=key,
        )
        jumlah_dedup = await db.ganti_metode_pembayaran_idempotency.count_documents({"idempotency_key": key})
        if counter.tripay_calls != 1:
            return (nama, f"FAIL - tripay_create_transaction terpanggil {counter.tripay_calls}x, harus 1x")
        if counter.wa_calls != 1:
            return (nama, f"FAIL - WA terkirim {counter.wa_calls}x, harus 1x")
        if jumlah_dedup != 1:
            return (nama, f"FAIL - dokumen dedup di DB = {jumlah_dedup}, harus 1")
        if not hasil.get("checkout_url"):
            return (nama, "FAIL - checkout_url kosong")
        return (nama, "PASS")
    finally:
        _lepas_mock(tripay_mod, wa_mod, asli)


async def skenario_retry_key_sama_tidak_dobel_transaksi() -> tuple:
    """Reproduksi PERSIS pola bug: 2 panggilan identik (idempotency_key SAMA, simulasi
    retry _pms_http_retry setelah httpx ReadTimeout) - HARUS cuma 1 transaksi Tripay & 1 WA
    (bukan 2 link BEDA terkirim ke tamu yang sama di tengah checkout)."""
    nama = "retry_key_sama_tidak_dobel_transaksi_tripay_dan_wa"
    from routes.payments import _lakukan_ganti_metode_pembayaran

    property_id = _property_id_test()
    b = await _buat_booking_test(property_id)
    counter = _TripayWaCounter()
    tripay_mod, wa_mod, asli = _pasang_mock(counter)
    try:
        key = str(uuid.uuid4())
        hasil_1 = await _lakukan_ganti_metode_pembayaran(b["id"], "QRIS2", "dp50", "Tes Idempotency", property_id, idempotency_key=key)
        hasil_2 = await _lakukan_ganti_metode_pembayaran(b["id"], "QRIS2", "dp50", "Tes Idempotency", property_id, idempotency_key=key)

        if counter.tripay_calls != 1:
            return (nama, f"FAIL - tripay_create_transaction terpanggil {counter.tripay_calls}x total, harus 1x (retry bikin transaksi dobel)")
        if counter.wa_calls != 1:
            return (nama, f"FAIL - WA terkirim {counter.wa_calls}x total, harus 1x (retry kirim link dobel ke tamu)")
        if hasil_1.get("checkout_url") != hasil_2.get("checkout_url"):
            return (nama, "FAIL - retry kembalikan checkout_url BEDA - tamu bisa terima 2 link berbeda")
        return (nama, "PASS")
    finally:
        _lepas_mock(tripay_mod, wa_mod, asli)


async def skenario_key_berbeda_tetap_2_transaksi() -> tuple:
    """Pastikan ini idempotency key SUNGGUHAN (per-request unik), BUKAN heuristik jendela
    waktu - 2 permintaan ganti metode BEDA (key beda, simulasi tamu benar2 minta ganti
    metode 2x berturutan) tetap harus jadi 2 transaksi Tripay terpisah, tidak boleh
    false-positive dianggap retry dari 1 permintaan yang sama."""
    nama = "key_berbeda_tetap_2_transaksi_tidak_false_positive"
    from routes.payments import _lakukan_ganti_metode_pembayaran

    property_id = _property_id_test()
    b = await _buat_booking_test(property_id)
    counter = _TripayWaCounter()
    tripay_mod, wa_mod, asli = _pasang_mock(counter)
    try:
        hasil_1 = await _lakukan_ganti_metode_pembayaran(
            b["id"], "QRIS2", "dp50", "Tes Idempotency", property_id, idempotency_key=str(uuid.uuid4()),
        )
        hasil_2 = await _lakukan_ganti_metode_pembayaran(
            b["id"], "BRIVA", "dp50", "Tes Idempotency", property_id, idempotency_key=str(uuid.uuid4()),
        )

        if counter.tripay_calls != 2:
            return (nama, f"FAIL - tripay_create_transaction terpanggil {counter.tripay_calls}x, harus 2x (2 request beda salah dianggap duplikat)")
        if counter.wa_calls != 2:
            return (nama, f"FAIL - WA terkirim {counter.wa_calls}x, harus 2x (2 request nyata beda)")
        if hasil_1.get("checkout_url") == hasil_2.get("checkout_url"):
            return (nama, "FAIL - 2 request beda key kembalikan checkout_url yang SAMA")
        return (nama, "PASS")
    finally:
        _lepas_mock(tripay_mod, wa_mod, asli)


async def main():
    skenario_list = [
        skenario_normal_single_call_satu_transaksi,
        skenario_retry_key_sama_tidak_dobel_transaksi,
        skenario_key_berbeda_tetap_2_transaksi,
    ]

    print("--- Skenario idempotency ganti_metode_pembayaran (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup TOTAL - hapus semua bookings ber-property_id berprefix tes ini, sukses maupun
    # gagal, PLUS dokumen ganti_metode_pembayaran_idempotency terkait (collection itu tidak
    # punya property_id sendiri - dicocokkan lewat booking_id SEBELUM booking-nya dihapus).
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    test_bookings = await db.get_collection("bookings").find({"property_id": prop_pattern}, {"_id": 0, "id": 1}).to_list(200)
    booking_ids = [b["id"] for b in test_bookings]
    if booking_ids:
        r_dedup = await db.get_collection("ganti_metode_pembayaran_idempotency").delete_many({"booking_id": {"$in": booking_ids}})
        if r_dedup.deleted_count:
            print(f"cleanup: {r_dedup.deleted_count} dokumen ganti_metode_pembayaran_idempotency test dihapus")
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
