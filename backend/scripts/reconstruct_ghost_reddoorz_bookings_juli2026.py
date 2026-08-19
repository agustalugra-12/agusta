"""Rekonstruksi satu kali (2026-08-19) - investigasi Claude Code diminta Agus.

Bug ditemukan: 95 email RedDoorz (13-31 Juli 2026) diklaim "berhasil buat reservasi"
(email_logs.status=Parsed_Success, aksi=reservasi_baru_dibuat) TAPI booking-nya TIDAK
PERNAH benar-benar ada di db.bookings - mekanisme/waktu hilangnya tidak ditemukan lewat
audit kode (tidak ada jalur hard-delete di codebase manapun). Detail investigasi lengkap
ada di percakapan sesi ini, tidak diulang di sini.

Scope skrip ini: docs/_ghost_bookings_juli_2026.csv (95 baris, sudah dedup by
reservation_id saat dibuat) DIKURANGI:
- "lugra lugra" (5 entri) - nama = surname Agus sendiri, pola test data jelas (5 email
  RedDoorz berturut-turut dalam <24 jam, semua "no. booking" beda tapi nama sama persis
  Agus), BUKAN tamu real - sengaja TIDAK direkonstruksi supaya tidak mencemari laporan
  keuangan dengan data test.
- "Ayu Santika" (444267135972444) - SUDAH ditangani terpisah
  (fix_ayu_santika_ota_wrongful_cancel.py), dikecualikan di sini biar tidak dobel.
- Baris dengan tipe_kamar kosong (data email tidak lengkap) - TIDAK bisa ditentukan
  kamar dgn yakin, dilewati & dilaporkan utk tinjauan manual drpd menebak.

Status booking hasil rekonstruksi:
- checkout_date < HARI_INI -> "checked_out" (stay sudah lewat, historis, revenue-only).
- checkout_date >= HARI_INI -> "aktif" (dicek dulu TIDAK ADA yang sedang berlangsung
  PERSIS hari ini - sudah diverifikasi terpisah sebelum skrip ini ditulis, lihat catatan
  di percakapan; kalau ADA yang genuinely tanggal depan/jauh [Des 2026/Jan-Mar 2027],
  tetap "aktif" apa adanya, TIDAK butuh penanganan kamar-khusus krn tidak bentrok
  okupansi HARI INI).

payment_status="paid" (keputusan bisnis 2026-07-13 yg sama dipakai buat_reservasi_otomatis
- tamu RedDoorz sudah bayar ke RedDoorz saat booking), dp_min=0, TIDAK ada service fee
(source="ota"). Room dipilih dari kandidat tipe yg benar, HINDARI bentrok jadwal dgn
booking manapun (status != cancelled) YANG SUDAH ADA maupun yang baru diinsert skrip ini
sendiri di run yang sama - kalau genuinely tidak ada kandidat kosong (semua kamar tipe
itu bentrok), tetap pilih kamar dgn bentrok PALING SEDIKIT & catat jelas di `catatan`
(rekonstruksi historis, akurasi kamar sekunder drpd akurasi revenue).

email_logs terkait di-update reservation_id/reservation_ids ke booking BARU (bukan ID
lama yg sudah terbukti hantu) supaya konsisten utk audit ke depan.

Jalankan SEKALI: venv/bin/python -m scripts.reconstruct_ghost_reddoorz_bookings_juli2026
"""
import asyncio
import csv
import uuid
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "pms"
PROPERTY_ID = "87ba6186-d849-48a4-a18c-bb8269fb56d2"
CSV_PATH = "/root/agusta/docs/_ghost_bookings_juli_2026.csv"
WITA = timezone(timedelta(hours=8))
HARI_INI = datetime(2026, 8, 19, tzinfo=timezone.utc)
EXCLUDE_NAMA = {"lugra lugra"}
EXCLUDE_NO_RESERVASI = {"444267135972444"}  # Ayu Santika, sudah ditangani terpisah


def parse_ota_datetime(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=WITA)
    return d.astimezone(timezone.utc)


async def cari_kamar_bebas(db, kandidat_rooms, start, end, sudah_dipakai_batch):
    """Return (room, bentrok_count) - room dgn 0 bentrok kalau ada, kalau tidak ada
    room dgn bentrok PALING SEDIKIT (tidak pernah return None - selalu ada kandidat)."""
    hasil = []
    for r in kandidat_rooms:
        bentrok_db = await db.bookings.count_documents({
            "room_id": r["id"], "property_id": PROPERTY_ID,
            "status": {"$ne": "cancelled"},
            "jam_mulai": {"$lt": end.isoformat()},
            "jam_selesai": {"$gt": start.isoformat()},
        })
        bentrok_batch = sum(
            1 for b in sudah_dipakai_batch.get(r["id"], [])
            if b[0] < end and b[1] > start
        )
        hasil.append((r, bentrok_db + bentrok_batch))
    hasil.sort(key=lambda x: x[1])
    return hasil[0]


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    mappings = {m["ota_nama"]: m["pms_tipe"] for m in await db.room_mappings.find({"sumber": "RedDoorz"}).to_list(20)}
    rooms_by_tipe: dict[str, list] = {}
    for r in await db.rooms.find({"property_id": PROPERTY_ID}).to_list(50):
        rooms_by_tipe.setdefault(r["tipe"], []).append(r)

    rows = list(csv.DictReader(open(CSV_PATH)))
    sudah_dipakai_batch: dict[str, list] = {}
    hasil = {"dibuat": [], "dilewati_kamar_kosong": [], "dilewati_lain": []}

    for row in rows:
        nama = (row.get("nama") or "").strip()
        no_reservasi = (row.get("no_reservasi") or "").strip()
        tipe_kamar = (row.get("tipe_kamar") or "").strip()
        check_in_raw = (row.get("check_in") or "").strip()
        check_out_raw = (row.get("check_out") or "").strip()

        if nama.lower() in {n.lower() for n in EXCLUDE_NAMA}:
            continue
        if no_reservasi in EXCLUDE_NO_RESERVASI:
            continue
        if not tipe_kamar:
            hasil["dilewati_kamar_kosong"].append((nama, no_reservasi))
            continue
        if not check_in_raw or not check_out_raw:
            hasil["dilewati_lain"].append((nama, no_reservasi, "tanggal kosong"))
            continue

        pms_tipe = mappings.get(tipe_kamar)
        if not pms_tipe or pms_tipe not in rooms_by_tipe:
            hasil["dilewati_lain"].append((nama, no_reservasi, f"tipe_kamar '{tipe_kamar}' tidak ter-mapping"))
            continue

        try:
            start = parse_ota_datetime(check_in_raw)
            end = parse_ota_datetime(check_out_raw)
        except Exception as e:
            hasil["dilewati_lain"].append((nama, no_reservasi, f"parse tanggal gagal: {e}"))
            continue
        if end <= start:
            hasil["dilewati_lain"].append((nama, no_reservasi, "checkout <= checkin"))
            continue

        # Dedup dalam batch ini sendiri (CSV punya beberapa baris duplikat persis sama
        # no_reservasi, sisa dari artefak array reservation_ids saat CSV dibuat).
        sudah_ada = await db.bookings.find_one({"ota_reservation_no": no_reservasi, "property_id": PROPERTY_ID})
        if sudah_ada:
            continue

        room, bentrok = await cari_kamar_bebas(db, rooms_by_tipe[pms_tipe], start, end, sudah_dipakai_batch)
        sudah_dipakai_batch.setdefault(room["id"], []).append((start, end))

        harga_raw = row.get("harga") or "0"
        try:
            harga = int(float(harga_raw))
        except ValueError:
            harga = 0
        jumlah_kamar = 1
        try:
            jumlah_kamar = max(1, min(int(float(row.get("jumlah_kamar") or 1)), 20))
        except ValueError:
            pass
        subtotal_semua = harga if harga > 0 else room["tarif_menginap"] * jumlah_kamar
        subtotal_per_kamar = round(subtotal_semua / jumlah_kamar)

        status = "checked_out" if end.date() < HARI_INI.date() else "aktif"
        now = datetime.now(timezone.utc).isoformat()
        processed_at = row.get("processed_at") or now
        bentrok_note = f" [PERINGATAN: kamar {room['nomor']} bentrok jadwal dgn {bentrok} booking lain - dipilih krn paling sedikit bentrok, akurasi kamar TIDAK terjamin]" if bentrok > 0 else ""

        doc = {
            "id": str(uuid.uuid4()),
            "kode": f"BKO-REKONSTRUKSI-{uuid.uuid4().hex[:8].upper()}",
            "room_id": room["id"], "room_nomor": room["nomor"], "room_tipe": room["tipe"],
            "tipe": "menginap",
            "nama_tamu": nama, "no_hp": "", "email": "", "no_identitas": "", "kendaraan": "",
            "jumlah_tamu": 2, "extra_bed_qty": 0, "dengan_sarapan": False,
            "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
            "catatan": (
                f"REKONSTRUKSI 2026-08-19 oleh Claude Code (investigasi diminta Agus) - email RedDoorz "
                f"\"{tipe_kamar}\" no. {no_reservasi} diproses {processed_at} diklaim sukses buat reservasi "
                f"tapi booking aslinya tidak pernah ada di database (bug parser, root cause tidak ditemukan). "
                f"Data direkonstruksi dari log email asli (Gmail), BUKAN dari booking asli yang hilang."
                f"{bentrok_note}"
            ),
            "status": status, "payment_status": "paid",
            "subtotal": subtotal_per_kamar, "service_fee": 0, "total": subtotal_per_kamar,
            "dp_min": 0, "diskon_member_persen": 0, "diskon_member_rp": 0, "kedatangan_ke": None,
            "source": "ota", "invoice_id": None, "payment_id": None,
            "created_at": now, "created_by": "claude_code_reconstruction",
            "property_id": PROPERTY_ID, "ota_reservation_no": no_reservasi,
            "ota_harga_dikonfirmasi": harga > 0, "amount_due": subtotal_per_kamar,
            "paid_at": processed_at,
        }
        await db.bookings.insert_one(doc)
        await db.audit_log.insert_one({
            "id": str(uuid.uuid4()), "user_id": None, "username": "claude_code_reconstruction",
            "action": "rekonstruksi_booking_ota_hilang",
            "detail": f"Rekonstruksi {doc['kode']} ({nama}, no. OTA {no_reservasi}) - booking asli hilang dari DB, direkonstruksi dari log email RedDoorz.",
            "entity": room["nomor"], "timestamp": now,
        })
        await db.email_logs.update_many(
            {"extracted_data.no_reservasi": no_reservasi},
            {"$set": {"reservation_id": doc["id"], "reservation_ids": [doc["id"]]}},
        )
        hasil["dibuat"].append((nama, no_reservasi, doc["kode"], room["nomor"], status, bentrok))

    print(f"=== Dibuat: {len(hasil['dibuat'])} booking ===")
    for x in hasil["dibuat"]:
        print(" ", x)
    print(f"\n=== Dilewati (tipe_kamar kosong, {len(hasil['dilewati_kamar_kosong'])}) ===")
    for x in hasil["dilewati_kamar_kosong"]:
        print(" ", x)
    print(f"\n=== Dilewati (alasan lain, {len(hasil['dilewati_lain'])}) ===")
    for x in hasil["dilewati_lain"]:
        print(" ", x)


if __name__ == "__main__":
    asyncio.run(main())
