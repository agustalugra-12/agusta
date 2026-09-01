"""Koreksi pembukuan manual (2026-09-01), diminta Agus lewat chat.

Reservasi RedDoorz 444266137368086 (email masuk 2026-08-30 11:00 UTC) memesan 3 kamar
Standard untuk tamu HERI SETYONO, checkin 2026-08-30 14:00 - checkout 2026-08-31 12:00.
Auto-parser (`_coba_auto_approve_day_use`-setara utk menginap OTA di otomasi_email.py)
berhasil membuat 2 dari 3 booking (kamar 18 & 9, kode BKO-20260830180015-D26D/-0095,
masing-masing Rp175.000) - kamar ke-3 GAGAL karena SEMUA 8 kamar Standard (10-17) sudah
terisi tamu menginap lain di rentang tanggal itu (bukan bug Day Use salah blokir - dicek
langsung, seluruh 8 booking pemblokir bertipe "menginap" asli). Email ditandai
"Manual_Required" utk staf cari kamar lain/hubungi tamu, tapi sampai sekarang (5 hari
kemudian, tamu sudah checkout) tidak pernah ditindaklanjuti - Rp175.000 dari kamar ke-3
ini hilang dari pembukuan.

Karena periode menginapnya sudah LEWAT (tamu 2 kamar lain sudah checked_out di tanggal
yang sama), tidak ada kamar fisik yang perlu/bisa dialokasikan lagi - booking ini murni
koreksi pembukuan (revenue recognition), BUKAN reservasi kamar aktif. room_id/room_nomor
sengaja dikosongkan (bukan kamar sungguhan yang dipakai tamu - overbooking RedDoorz),
supaya tidak menciptakan kesan bentrok/ganda dengan kamar manapun.

Field disamakan dgn 2 booking sibling (BKO-20260830180015-D26D/-0095) supaya konsisten
& ikut kehitung benar di laporan pendapatan online (source="ota", payment_status="paid",
ota_harga_dikonfirmasi=True - laporan_pendapatan di routes/laporan_analitik.py filter
persis field-field ini, TIDAK mensyaratkan room_id).

Jalankan SEKALI: venv/bin/python -m scripts.fix_heri_setyono_kamar_ke3_reddoorz
"""
import asyncio
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

PROPERTY_ID = "87ba6186-d849-48a4-a18c-bb8269fb56d2"  # Pelangi Homestay
OTA_RESERVATION_NO = "444266137368086"
JAM_MULAI = "2026-08-30T06:00:00+00:00"   # sama dgn 2 sibling (WITA 14:00)
JAM_SELESAI = "2026-08-31T04:00:00+00:00"  # sama dgn 2 sibling (WITA 12:00)
TOTAL = 175000  # 525000 / 3 kamar, sama persis dgn 2 sibling


async def main():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["pms"]
    now = datetime.now(timezone.utc).isoformat()

    existing = await db.bookings.count_documents({"ota_reservation_no": OTA_RESERVATION_NO})
    if existing != 2:
        print(f"STOP: ditemukan {existing} booking dgn ota_reservation_no={OTA_RESERVATION_NO!r}, "
              f"diharapkan persis 2 (sibling yang sudah ada) - kemungkinan sudah ada perubahan, cek manual dulu.")
        return

    doc = {
        "id": str(uuid.uuid4()), "kode": f"BKO-REKONSILIASI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
        "room_id": None, "room_nomor": None, "room_tipe": "Standard",
        "tipe": "menginap", "nama_tamu": "HERI SETYONO", "no_hp": "081915605610",
        "email": "", "no_identitas": "", "kendaraan": "",
        "jumlah_tamu": 2, "extra_bed_qty": 0, "dengan_sarapan": False,
        "jam_mulai": JAM_MULAI, "jam_selesai": JAM_SELESAI,
        "catatan": (
            "[Rekonsiliasi pembukuan 2026-09-01, Claude Code atas permintaan Agus] Kamar "
            f"ke-3 dari reservasi RedDoorz {OTA_RESERVATION_NO} (3 kamar dipesan bersamaan, "
            "lihat sibling BKO-20260830180015-D26D & -0095) - GAGAL auto-booking karena "
            "seluruh 8 kamar Standard penuh tamu menginap lain di tanggal ini (bukan bug "
            "Day Use, dikonfirmasi via audit). Ditandai Manual_Required tapi tidak pernah "
            "ditindaklanjuti staf sampai tamu checkout - dibuat di sini murni utk pengakuan "
            "pendapatan (revenue recognition), TANPA kamar fisik (overbooking RedDoorz, "
            "periode menginap sudah lewat)."
        ),
        "status": "checked_out", "payment_status": "paid",
        "subtotal": TOTAL, "service_fee": 0, "total": TOTAL, "dp_min": round(TOTAL / 2),
        "diskon_member_persen": 0, "diskon_member_rp": 0, "kedatangan_ke": None,
        "source": "ota", "invoice_id": None, "payment_id": None,
        "created_at": now, "created_by": "claude_code (permintaan Agus)",
        "property_id": PROPERTY_ID,
        "amount_due": TOTAL, "ota_harga_dikonfirmasi": True,
        "ota_reservation_no": OTA_RESERVATION_NO,
        "paid_at": now,
    }
    await db.bookings.insert_one(doc)
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "claude_code (permintaan Agus)",
        "action": "rekonsiliasi_pembukuan_manual",
        "detail": (
            f"Booking rekonsiliasi Rp{TOTAL} dibuat utk HERI SETYONO, kamar ke-3 reservasi "
            f"RedDoorz {OTA_RESERVATION_NO} yang gagal auto-booking & tidak pernah "
            "ditindaklanjuti staf (tanpa kamar fisik, periode sudah lewat)."
        ),
        "entity": None, "timestamp": now,
    })
    print(f"Booking rekonsiliasi dibuat: kode={doc['kode']} total={TOTAL}")


if __name__ == "__main__":
    asyncio.run(main())
