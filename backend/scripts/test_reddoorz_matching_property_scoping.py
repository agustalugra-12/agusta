"""Regresi property_id scoping untuk `_cocokkan_booking_pending_reddoorz`
(2026-08-14, temuan #1 audit arsitektur/risiko - HIGH). Bug nyata (belum sempat jadi
insiden, ditemukan lewat audit code-review, bukan laporan tamu): fungsi ini query
`db.bookings.find(...)` TANPA `property_id` di filter sama sekali sejak awal dibuat -
beda dari 2 fungsi kembarannya di file yang sama (`_cocokkan_via_kode_pms`/`_masked`,
keduanya sudah benar pakai `scoped()`). Begitu properti kedua yang pakai RedDoorz sync
aktif, email konfirmasi properti A berpotensi salah tandai booking properti B sebagai
`sync_status="synced"` - kebocoran data lintas properti (matching fuzzy nama+tanggal,
BUKAN exact match, jadi risikonya nyata begitu ada >1 properti dgn nama tamu/tanggal
mirip).

Fix: `property_id` jadi parameter WAJIB, di-thread dari `buat_reservasi_otomatis`
(SETELAH property_id sudah diresolusi, tempat yang sama persis dgn 2 kembarannya), dan
filter query dibungkus `scoped()` - pola identik dgn 2 fungsi kembaran.

Skenario ini adalah bukti KONKRET fix-nya benar: 2 booking pending-RedDoorz dibuat dgn
nama tamu + tipe kamar + tanggal check-in SAMA PERSIS, tapi `property_id` BEDA - panggil
fungsi dgn SATU property_id spesifik, pastikan HANYA booking milik property_id itu yang
pernah muncul sbg kandidat, booking properti lain TIDAK PERNAH ikut kebawa walau semua
kriteria fuzzy-nya (nama/tanggal/tipe) cocok 100%.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB reports/laporan/checkin-checkout,
lihat CLAUDE.md) - otomasi_email.py TIDAK termasuk cakupan gerbang itu, skrip ini regresi
tambahan khusus bug scoping ini. Sama pola AMAN dgn test_regresi.py/
test_booking_request_idempotency.py: jalan in-process langsung ke DB produksi yang sama,
tapi semua data tes di bawah property_id PALSU (prefix di bawah, tidak pernah muncul di
property switcher UI manapun) dan dibersihkan total di akhir run, sukses maupun gagal.
Tidak ada efek samping nyata (tidak ada Telegram/WA/Tripay/email) di jalur yang diuji.

Jalankan:
    cd backend && venv/bin/python -m scripts.test_reddoorz_matching_property_scoping
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

TEST_PROPERTY_PREFIX = "test-reddoorz-scoping-jangan-dipakai-asli"


def _property_id_test() -> str:
    return f"{TEST_PROPERTY_PREFIX}-{uuid.uuid4().hex[:8]}"


def _checkin_iso() -> str:
    # +2 hari dari UTC sekarang - jauh cukup dari batas manapun, tidak flaky.
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


async def _buat_booking_pending_reddoorz(db, property_id: str, nama_tamu: str, room_tipe: str, jam_mulai_iso: str,
                                          sync_status: str = "waiting_reddoorz_sync", status: str = "aktif") -> str:
    bid = str(uuid.uuid4())
    await db.bookings.insert_one({
        "id": bid,
        "kode": f"BKO-TEST-{uuid.uuid4().hex[:8].upper()}",
        "property_id": property_id,
        "source": "whatsapp_request",
        "sync_status": sync_status,
        "status": status,
        "tipe": "menginap",
        "room_tipe": room_tipe,
        "nama_tamu": nama_tamu,
        "jam_mulai": jam_mulai_iso,
        "room_id": "room-tes-tidak-ada",
        "created_at": jam_mulai_iso,
    })
    return bid


async def skenario_tidak_bocor_lintas_properti() -> tuple:
    """Inti fix: 2 booking pending-RedDoorz, nama+tipe kamar+tanggal check-in SAMA
    PERSIS, property_id BEDA. Panggil fungsi dgn property_id milik booking A - HARUS
    HANYA kembalikan booking A, booking B (properti lain) TIDAK BOLEH pernah ikut jadi
    kandidat walau semua kriteria fuzzy cocok 100%."""
    nama = "tidak_bocor_lintas_properti_walau_nama_tanggal_tipe_sama_persis"
    from core import db
    from routes.otomasi_email import _cocokkan_booking_pending_reddoorz

    property_a = _property_id_test()
    property_b = _property_id_test()
    nama_tamu = "Tamu Tes Scoping RedDoorz"
    room_tipe = "Deluxe Tes"
    jam_mulai_iso = _checkin_iso()
    check_in_dt = datetime.fromisoformat(jam_mulai_iso)

    try:
        bid_a = await _buat_booking_pending_reddoorz(db, property_a, nama_tamu, room_tipe, jam_mulai_iso)
        bid_b = await _buat_booking_pending_reddoorz(db, property_b, nama_tamu, room_tipe, jam_mulai_iso)

        hasil = await _cocokkan_booking_pending_reddoorz(nama_tamu, room_tipe, check_in_dt, 1, property_a)
        hasil_ids = [b["id"] for b in hasil]

        if bid_b in hasil_ids:
            return (nama, f"FAIL - booking properti LAIN ({bid_b}, property_id={property_b}) ikut jadi kandidat saat query utk property_id={property_a} - KEBOCORAN DATA LINTAS PROPERTI")
        if bid_a not in hasil_ids:
            return (nama, f"FAIL - booking milik property_id yang diminta ({bid_a}) TIDAK ketemu - fix kelewat ketat/salah")
        if len(hasil_ids) != 1:
            return (nama, f"FAIL - jumlah kandidat = {len(hasil_ids)}, harus 1")
        return (nama, "PASS")
    finally:
        await db.bookings.delete_many({"id": {"$in": [bid_a, bid_b]}})


async def skenario_property_b_tetap_ketemu_sendiri() -> tuple:
    """Simetri: query dgn property_id B harus kembalikan booking B, bukan A - bukti fix
    bukan cuma "selalu return kosong" (false negative), tapi benar-benar scoped per
    properti yang diminta."""
    nama = "property_b_tetap_ketemu_booking_miliknya_sendiri"
    from core import db
    from routes.otomasi_email import _cocokkan_booking_pending_reddoorz

    property_a = _property_id_test()
    property_b = _property_id_test()
    nama_tamu = "Tamu Tes Scoping RedDoorz Dua"
    room_tipe = "Superior Tes"
    jam_mulai_iso = _checkin_iso()
    check_in_dt = datetime.fromisoformat(jam_mulai_iso)

    try:
        bid_a = await _buat_booking_pending_reddoorz(db, property_a, nama_tamu, room_tipe, jam_mulai_iso)
        bid_b = await _buat_booking_pending_reddoorz(db, property_b, nama_tamu, room_tipe, jam_mulai_iso)

        hasil = await _cocokkan_booking_pending_reddoorz(nama_tamu, room_tipe, check_in_dt, 1, property_b)
        hasil_ids = [b["id"] for b in hasil]

        if hasil_ids != [bid_b]:
            return (nama, f"FAIL - query property_id={property_b} kembalikan {hasil_ids}, harus [{bid_b}] saja")
        return (nama, "PASS")
    finally:
        await db.bookings.delete_many({"id": {"$in": [bid_a, bid_b]}})


async def main():
    skenario_list = [
        skenario_tidak_bocor_lintas_properti,
        skenario_property_b_tetap_ketemu_sendiri,
    ]

    print("--- Skenario property_id scoping _cocokkan_booking_pending_reddoorz (in-process, property_id test terisolasi) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    # Cleanup TOTAL cadangan (skenario sendiri sudah cleanup per-skenario di atas, ini
    # jaring pengaman kalau ada exception sebelum sempat cleanup) - hapus semua bookings
    # ber-property_id berprefix tes ini.
    from core import db
    prop_pattern = {"$regex": f"^{TEST_PROPERTY_PREFIX}"}
    r = await db.get_collection("bookings").delete_many({"property_id": prop_pattern})
    if r.deleted_count:
        print(f"cleanup cadangan: {r.deleted_count} dokumen bookings test tersisa dihapus")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
