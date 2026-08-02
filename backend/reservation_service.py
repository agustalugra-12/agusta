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

WIB = timezone(timedelta(hours=7))


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
                                property_id: str, exclude_booking_id: Optional[str] = None) -> bool:
    """Raise HTTPException(400) jika kamar sudah dibooking pada rentang [mulai, selesai).
    Booking yang dianggap konflik: status aktif/booking_pending/booking_paid/checked_in.
    exclude_booking_id dipakai saat reschedule (update_booking) agar booking itu
    sendiri tidak dianggap konflik dengan dirinya sendiri.

    property_id (2026-07-24, multi-properti) WAJIB - room_id sendiri sudah unik global
    (uuid) jadi secara teknis query tanpa property_id tetap benar, tapi disertakan
    tetap sebagai lapis pertahanan konsisten dengan scoped() di collection lain.

    Bug nyata ditemukan 2026-07-28 (audit atas permintaan user - pastikan kamar Menginap
    TIDAK BISA ditumpuk Day Use, beda dari arah sebaliknya yang memang sengaja diizinkan):
    daftar status di sini TIDAK PERNAH menyertakan "checked_in" - begitu tamu Menginap
    BENAR-BENAR check-in (status booking berubah jadi "checked_in", lihat
    checkin_from_booking di routes/bookings.py), fungsi ini berhenti menganggap booking
    itu sebagai penghalang, jadi booking BARU yang overlap waktu (mis. Day Use di tengah
    masa inap tamu yang sudah check-in) bisa LOLOS dibuat - dites nyata & terbukti
    sebelum fix ini. scheduling_engine.py sudah punya daftar status yang BENAR
    (BOOKING_TERKONFIRMASI_STATUS, sudah termasuk "checked_in") tapi TIDAK bisa di-import
    langsung ke sini - scheduling_engine.py sendiri import check_room_available dari file
    ini, import balik akan circular. Ditambahkan langsung di sini sbg perbaikan tercepat
    & paling aman - kalau nanti direfactor, pindahkan konstanta status ini ke core.py
    supaya jadi satu sumber kebenaran yang sama utk kedua file."""
    query: Dict[str, Any] = scoped({
        "room_id": room_id,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid", "checked_in"]},
        "jam_mulai": {"$lt": selesai.isoformat()},
        "jam_selesai": {"$gt": mulai.isoformat()},
    }, property_id)
    if exclude_booking_id:
        query["id"] = {"$ne": exclude_booking_id}
    overlap = await db.bookings.find_one(query)
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")

    # Bug KRITIS ditemukan & diperbaiki 2026-08-02 (permintaan Agus - audit langsung: tamu
    # walk-in Day Use Harmoni checkin via routes/checkins.py create_checkin() TIDAK PERNAH
    # menulis ke db.bookings SAMA SEKALI (cuma db.checkins + set room.status="day_use") -
    # jadi query di atas (yang HANYA baca db.bookings) sama sekali TIDAK TAHU kamar itu
    # sedang fisik ditempati tamu walk-in. Reproduksi nyata: kamar dgn tamu walk-in aktif
    # sampai ~17:15 WIB tetap muncul "tersedia" utk booking baru jam 13:00 hari yg sama -
    # risiko double-booking sungguhan (2 tamu berbeda diarahkan ke kamar fisik yang sama).
    # Fix: cek juga db.checkins yang masih "aktif" (belum checkout, jam_checkout None) -
    # durasi belum pasti sampai checkout beneran terjadi, jadi pakai estimasi KONSERVATIF
    # (6 jam standar Day Use, SAMA persis dgn DAYUSE_DURASI_JAM di scheduling_engine.py -
    # TIDAK diimport langsung krn scheduling_engine.py sendiri import check_room_available
    # dari file ini, import balik jadi circular - sama alasan konstanta status di atas
    # sudah di-hardcode terpisah, ikuti pola yang sama) - lebih baik overestimate durasi
    # (kadang menolak booking yang sebenarnya sudah boleh) drpd underestimate (approve
    # booking yang ternyata masih bentrok tamu walk-in sungguhan).
    checkin_aktif = await db.checkins.find_one(scoped({
        "room_id": room_id, "status": "aktif",
    }, property_id))
    if checkin_aktif and checkin_aktif.get("jam_checkin"):
        ci_mulai = datetime.fromisoformat(checkin_aktif["jam_checkin"])
        ci_estimasi_selesai = ci_mulai + timedelta(hours=6)
        if ci_mulai < selesai and mulai < ci_estimasi_selesai:
            raise HTTPException(
                400,
                f"Kamar sedang dipakai tamu walk-in {checkin_aktif.get('nama_tamu', '-')} "
                f"(check-in {ci_mulai.astimezone(WIB).strftime('%H:%M')} WIB, perkiraan selesai "
                f"{ci_estimasi_selesai.astimezone(WIB).strftime('%H:%M')} WIB)"
            )
    return True


async def create_reservation(data: Dict[str, Any], property_id: str, source: str = "public",
                              harga_override: Optional[Dict[str, Any]] = None,
                              diskon_ai_persen: int = 0) -> Dict[str, Any]:
    """Buat reservasi/booking baru. Dipakai oleh public_create_booking (source="online");
    disiapkan agar sumber lain (mis. OTA) bisa memakai alur yang sama lewat harga_override.

    data wajib berisi: room_id, nama_tamu, no_hp, email, no_identitas, kendaraan,
    jumlah_tamu, jam_mulai (datetime UTC), jam_selesai (datetime UTC), catatan, created_by.
    data boleh berisi: tipe (default "day_use"), extra_bed_qty (default 0), dengan_sarapan (default False, hanya relevan untuk tipe menginap).

    harga_override, jika diisi, wajib berisi subtotal/service_fee/total/dp_min final
    (tidak dihitung ulang) — extra bed (kalau ada) harus sudah termasuk di subtotal.

    property_id (2026-07-24) WAJIB - room_id di-scope ke properti ini supaya tidak bisa
    booking kamar milik properti lain lewat room_id yang ditebak/bocor, dan booking yang
    dibuat otomatis ikut property_id yang sama (scoped() di insert doc di bawah).
    """
    r = await db.rooms.find_one(scoped({"id": data["room_id"]}, property_id))
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")

    mulai = data["jam_mulai"]
    selesai = data["jam_selesai"]

    if r["status"] == "maintenance":
        raise HTTPException(400, "Kamar sedang maintenance, tidak bisa dibooking")
    # Kamar yang sedang terisi (day_use/menginap/perlu_dibersihkan) SAAT INI cuma menghalangi
    # booking yang checkin-nya SEKARANG/SUDAH LEWAT — booking utk jam NANTI (baik hari ini
    # atau tanggal lain) tetap boleh, cukup divalidasi lewat check_room_available (overlap
    # jam presisi sungguhan) di bawah. Konsisten dengan logika public_availability (is_today)
    # di routes/public.py. Bug ditemukan 2026-07-17: booking publik utk tanggal mendatang
    # salah ditolak "Kamar tidak tersedia" hanya karena kamar itu kebetulan sedang dipakai
    # tamu lain SAAT INI, walau sudah kosong lagi jauh sebelum tanggal check-in yang diminta.
    #
    # Ralat 2026-08-02 (kasus lapangan Agus - tamu chat jam 8 pagi setuju booking Day Use
    # jam 2 siang setelah AI kasih rekomendasi jam; atau tamu walk-in jam 9 pagi minta
    # Menginap begitu staf infokan kamar ready jam 2 siang lewat Quick Book): guard lama
    # bandingkan TANGGAL KALENDER (bukan jam presisi) pakai `datetime.now(timezone.utc)` -
    # PADAHAL server jalan di zona WIB (server.timezone = Asia/Jakarta) sementara "hari ini"
    # semestinya dihitung dari WIB (konsisten dgn is_today di public.py yg pakai
    # datetime.now() lokal server, otomatis WIB). Akibat gabungan 2 masalah ini: (1) guard
    # cuma cek TANGGAL (bukan jam), jadi booking jam 2 siang nanti tetap ditolak kalau kamar
    # masih terisi jam 8 pagi SEKARANG, padahal jam 2 siang jelas beda dari "sekarang" -
    # (2) window "grey zone" 00:00-07:00 WIB (UTC belum ganti tanggal walau WIB sudah)
    # bikin perilakunya tidak konsisten. Sekarang guard ini HANYA berlaku kalau checkin
    # BENAR-BENAR sekarang/sudah lewat (mulai <= now, dibandingkan di WIB) - booking utk jam
    # mendatang (nanti hari ini ATAU tanggal lain) sepenuhnya diserahkan ke check_room_available
    # (validasi jam presisi, tahu persis kapan tamu SEKARANG ini akan checkout).
    now_wib = datetime.now(timezone.utc).astimezone(WIB)
    if mulai.astimezone(WIB) <= now_wib and r["status"] != "kosong":
        raise HTTPException(400, "Kamar tidak tersedia")

    extra_bed_qty = max(0, min(EXTRA_BED_MAX, int(data.get("extra_bed_qty") or 0)))
    # Aturan okupansi (2026-07-21): 1 kamar standar 2 dewasa + 1 anak, extra bed (jadi 3
    # dewasa + 1 anak) HANYA berlaku utk tipe Cottage. Sebelumnya validasi ini cuma ada di
    # public_create_booking (routes/public.py) - dipindah/diduplikasi ke sini supaya
    # SEMUA pemanggil create_reservation (termasuk yang mungkin ditambah nanti) otomatis
    # ikut aturan yang sama, bukan tergantung tiap caller ingat cek sendiri-sendiri.
    if extra_bed_qty > 0 and r.get("tipe") != "Cottage":
        raise HTTPException(400, "Extra bed hanya tersedia untuk tipe kamar Cottage, tidak bisa dipesan untuk Standard")

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
        diskon_info = await hitung_diskon_member(property_id, data.get("no_hp", ""), data.get("no_identitas", ""))
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
        "property_id": property_id,
    }
    # Celah check_room_available -> insert_one dibungkus lock in-process per kamar supaya
    # 2 request nyaris bersamaan tidak bisa sama-sama lolos cek lalu sama-sama menulis
    # (race condition anti-double-booking, lihat catatan di kepala file).
    async with room_locks(data["room_id"]):
        await check_room_available(data["room_id"], mulai, selesai, property_id)
        await db.bookings.insert_one(doc)
    await log_availability_change(r["id"], r["tipe"], -1, "booking_dibuat", property_id, booking_id=doc["id"])
    await upsert_guest(data["nama_tamu"], data["no_hp"], data["no_identitas"], data["kendaraan"],
                        property_id, count_kunjungan=False)

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
