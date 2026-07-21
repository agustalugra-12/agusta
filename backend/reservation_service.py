"""Reservation service — logika terpusat seputar booking kamar.

Tahap 1: cek ketersediaan kamar (anti-overbooking). Logika ini sebelumnya
terduplikasi di routes/bookings.py (create_booking, update_booking) dan
routes/public.py (public_create_booking).

Tahap 2: pembuatan reservasi (create_reservation). Logika ini sebelumnya
ada di routes/public.py (public_create_booking) — dipusatkan supaya sumber
booking lain (mis. OTA) bisa memakai alur yang sama.

**Locking anti-race-condition (ditambahkan 2026-07-19, audit atas permintaan user)**:
`check_room_available` sendiri HANYA membaca (find_one) — celah antara pengecekan itu
dan tulis (insert/update) berikutnya di tiap caller adalah celah TOCTOU (time-of-check-
time-of-use) klasik: 2 request yang nyaris bersamaan (mis. AI Day Use auto-approve vs
staf Quick Book, atau 2 tamu rebutan kamar terakhir) bisa SAMA-SAMA lolos
check_room_available sebelum salah satu sempat menulis, menghasilkan double-booking
sungguhan. MongoDB di server ini jalan standalone (bukan replica set) jadi multi-document
transaction TIDAK tersedia, dan backend jalan 1 proses uvicorn saja (tanpa --workers) -
karena itu solusi paling sederhana & efektif adalah `asyncio.Lock` in-process per kamar
(`room_locks` di bawah), yang membungkus SETIAP celah check-lalu-tulis di seluruh
codebase (create_reservation di sini, plus routes/bookings.py, routes/public.py,
routes/otomasi_email.py - cari pemanggil check_room_available lain untuk daftar
lengkapnya). PENTING: ini HANYA melindungi selama backend tetap 1 proses/1 instance -
kalau suatu saat di-scale ke multi-worker/multi-instance di belakang load balancer, lock
in-process ini TIDAK CUKUP lagi, perlu locking di level DB (mis. upgrade MongoDB ke
replica set untuk transaction, atau skema lock berbasis dokumen atomic findOneAndUpdate)."""
from core import *
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

_room_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def room_locks(*room_ids: str):
    """Pegang lock in-process untuk 1+ kamar sekaligus (urutan diurutkan supaya tidak
    pernah deadlock walau 2 request memesan grup kamar yang sama dengan urutan berbeda).
    Bungkus SELURUH celah dari check_room_available sampai insert/update booking-nya
    dengan ini di setiap tempat yang benar-benar menulis ke db.bookings."""
    unik = sorted(set(room_ids))
    locks = [_room_locks[rid] for rid in unik]
    for lock in locks:
        await lock.acquire()
    try:
        yield
    finally:
        for lock in locks:
            lock.release()


async def check_room_available(room_id: str, mulai: datetime, selesai: datetime,
                                exclude_booking_id: Optional[str] = None) -> bool:
    """Raise HTTPException(400) jika kamar sudah dibooking pada rentang [mulai, selesai).
    Booking yang dianggap konflik: status aktif/booking_pending/booking_paid.
    exclude_booking_id dipakai saat reschedule (update_booking) agar booking itu
    sendiri tidak dianggap konflik dengan dirinya sendiri.
    """
    query: Dict[str, Any] = {
        "room_id": room_id,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": selesai.isoformat()},
        "jam_selesai": {"$gt": mulai.isoformat()},
    }
    if exclude_booking_id:
        query["id"] = {"$ne": exclude_booking_id}
    overlap = await db.bookings.find_one(query)
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")
    return True


async def create_reservation(data: Dict[str, Any], source: str = "public",
                              harga_override: Optional[Dict[str, Any]] = None,
                              diskon_ai_persen: int = 0) -> Dict[str, Any]:
    """Buat reservasi/booking baru. Dipakai oleh public_create_booking (source="online");
    disiapkan agar sumber lain (mis. OTA) bisa memakai alur yang sama lewat harga_override.

    data wajib berisi: room_id, nama_tamu, no_hp, email, no_identitas, kendaraan,
    jumlah_tamu, jam_mulai (datetime UTC), jam_selesai (datetime UTC), catatan, created_by.
    data boleh berisi: tipe (default "day_use"), extra_bed_qty (default 0), dengan_sarapan (default False, hanya relevan untuk tipe menginap).

    harga_override, jika diisi, wajib berisi subtotal/service_fee/total/dp_min final
    (tidak dihitung ulang) — extra bed (kalau ada) harus sudah termasuk di subtotal.
    """
    r = await db.rooms.find_one({"id": data["room_id"]})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")

    mulai = data["jam_mulai"]
    selesai = data["jam_selesai"]

    if r["status"] == "maintenance":
        raise HTTPException(400, "Kamar sedang maintenance, tidak bisa dibooking")
    # Kamar yang sedang terisi (day_use/menginap/perlu_dibersihkan) SAAT INI cuma menghalangi
    # booking yang mulai HARI INI JUGA — booking untuk tanggal mendatang tetap boleh, cukup
    # divalidasi lewat check_room_available (overlap tanggal sungguhan) di bawah. Konsisten
    # dengan logika public_availability (is_today) di routes/public.py. Bug ditemukan
    # 2026-07-17: booking publik utk tanggal mendatang salah ditolak "Kamar tidak tersedia"
    # hanya karena kamar itu kebetulan sedang dipakai tamu lain SAAT INI, walau sudah kosong
    # lagi jauh sebelum tanggal check-in yang diminta.
    if mulai.astimezone(timezone.utc).date() <= datetime.now(timezone.utc).date() and r["status"] != "kosong":
        raise HTTPException(400, "Kamar tidak tersedia")

    extra_bed_qty = max(0, min(EXTRA_BED_MAX, int(data.get("extra_bed_qty") or 0)))

    if harga_override is not None:
        subtotal = harga_override["subtotal"]
        service_fee = harga_override["service_fee"]
    else:
        subtotal = r["tarif"] + extra_bed_qty * EXTRA_BED_PRICE
        service_fee = round(subtotal * SERVICE_FEE_PCT)

    # Program Loyalitas Kedatangan (diskon member, dikonfirmasi user 2026-07-19) - berlaku
    # semua channel booking langsung ke Pelangi (publik/walk-in lewat sini, WhatsApp AI lewat
    # booking_requests) KECUALI source="ota" (RedDoorz - subtotal itu apa adanya dari OTA,
    # bukan tarif Pelangi sendiri, mendiskonnya akan merusak rekonsiliasi settlement).
    # Selalu dihitung ULANG di sini (bukan dipercaya dari harga_override) - satu sumber
    # kebenaran, konsisten di semua channel yang lewat create_reservation.
    diskon_persen, diskon_rp, kedatangan_ke = 0, 0, None
    if source != "ota":
        diskon_info = await hitung_diskon_member(data.get("no_hp", ""), data.get("no_identitas", ""))
        kedatangan_ke = diskon_info["kedatangan_ke"]
        # Diskon diskresi AI (permintaan tamu, hitung_diskon_ai_diskresi) digabung dengan
        # diskon member - AMBIL YANG TERBESAR, TIDAK dijumlah (kebijakan bisnis 2026-07-21,
        # sama seperti diskon diskresi sendiri tidak dijumlah antar kriteria malam/kamar).
        diskon_persen = max(diskon_info["diskon_persen"], min(DISKON_AI_MAX_PERSEN, max(0, int(diskon_ai_persen or 0))))
        hasil_diskon = terapkan_diskon_member(subtotal, diskon_persen)
        subtotal = hasil_diskon["subtotal"]
        diskon_rp = hasil_diskon["diskon_rp"]

    total = subtotal + service_fee
    dp_min = round(total * 0.5)

    kode = f"BKO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    doc = {
        "id": str(uuid.uuid4()), "kode": kode,
        "room_id": data["room_id"], "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tipe": data.get("tipe", "day_use"),
        "nama_tamu": data["nama_tamu"], "no_hp": data["no_hp"],
        "email": data["email"],
        "no_identitas": data["no_identitas"], "kendaraan": data["kendaraan"],
        "jumlah_tamu": data["jumlah_tamu"], "extra_bed_qty": extra_bed_qty,
        "dengan_sarapan": bool(data.get("dengan_sarapan")) if data.get("tipe") == "menginap" else False,
        "jam_mulai": mulai.isoformat(), "jam_selesai": selesai.isoformat(),
        "catatan": data["catatan"],
        "status": "booking_pending",          # status booking utama (untuk public booking)
        "payment_status": "pending",          # pending | paid | expired | failed | refunded
        "subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": dp_min,
        "diskon_member_persen": diskon_persen, "diskon_member_rp": diskon_rp, "kedatangan_ke": kedatangan_ke,
        "source": source,                      # online | walk_in
        "invoice_id": None, "payment_id": None,
        "created_at": now_iso(), "created_by": data["created_by"],
    }
    # Celah check_room_available -> insert_one dibungkus lock in-process per kamar supaya
    # 2 request nyaris bersamaan tidak bisa sama-sama lolos cek lalu sama-sama menulis
    # (race condition anti-double-booking, lihat catatan di kepala file).
    async with room_locks(data["room_id"]):
        await check_room_available(data["room_id"], mulai, selesai)
        await db.bookings.insert_one(doc)
    await log_availability_change(r["id"], r["tipe"], -1, "booking_dibuat", booking_id=doc["id"])
    await upsert_guest(data["nama_tamu"], data["no_hp"], data["no_identitas"], data["kendaraan"], count_kunjungan=False)

    if source == "online":
        action, username = "public_create_booking", "public"
    else:
        action, username = f"create_booking_{source}", source
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": username,
        "action": action,
        "detail": f"Public booking {kode} kamar {r['nomor']} ({r['tipe']}) untuk {data['nama_tamu']}",
        "entity": r["nomor"], "timestamp": now_iso(),
    })
    doc.pop("_id", None)
    return doc
