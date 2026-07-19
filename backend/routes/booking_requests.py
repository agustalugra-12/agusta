"""Booking Request — Tahap 1 dari PRD "Modul Reservasi, Priority Booking & Payment Flow"
(diberi lampu hijau user 2026-07-17, lihat CLAUDE.md & memory project_reservasi_priority_booking_prd).

Entitas baru (`db.booking_requests`) — permintaan booking dikumpulkan AI WhatsApp
(routes/pesan_whatsapp.py, atau ai-chat-bot lewat routes/integrasi_ai_bot.py), baru
menjadi booking sungguhan (`db.bookings`) lewat `buat_booking_request()` — fungsi itu
sendiri tidak pernah membuat booking, cuma permintaan.

**Perubahan 2026-07-19 (dikonfirmasi user)**: Day Use dengan `payment_option` yang sudah
jelas dari tamu sekarang di-AUTO-APPROVE (`_coba_auto_approve_day_use`) - kamar dipilih
otomatis dari ketersediaan real-time, booking + transaksi Tripay dibuat langsung, link
bayar auto-terkirim, TANPA menunggu staf klik Terima di PMS. Menginap TETAP WAJIB direview
manual staf (butuh sinkron manual ke PMS RedDoorz, tidak bisa diotomatisasi sepenuhnya).
Kalau Day Use BENAR-BENAR penuh (tidak ada kamar kosong sama sekali di tanggal/tipe itu),
`_auto_reject_penuh` langsung menolak otomatis & mengabari tamu SAAT ITU JUGA (status
"rejected", `rejected_by="AI WhatsApp (otomatis)"`) - TIDAK dibiarkan nyangkut menunggu
staf sadar sendiri, karena staf pun tidak akan pernah bisa approve request yang memang
tidak ada kamarnya. Kalau auto-approve gagal/tidak berlaku karena alasan LAIN (>1 kamar,
payment_option belum disebutkan tamu), fallback ke alur lama: booking_request tetap
non-binding "waiting_approval", staf review manual (approve/reject di bawah).

Tahap 1 SENGAJA berhenti setelah tamu membayar (booking real dibuat & dibayar via Tripay
persis seperti alur publik yang sudah ada — reuse `create_reservation`/`tripay_create_transaction`,
tidak ada jalur pembayaran paralel baru). Bagian PRD yang BELUM dibangun di sini (Tahap 2,
menyusul terpisah): status "Action Required" untuk booking Menginap (input manual ke PMS
RedDoorz), penyaringan booking Menginap dari Calendar/Dashboard/Housekeeping/Laporan sampai
email konfirmasi RedDoorz diterima, dan mematikan/redirect tombol Book Now publik.
"""
from core import *
from reservation_service import create_reservation
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

STATUS_TERBUKA = ["waiting_approval"]

# Lock in-process per booking_request (2026-07-19, lanjutan audit anti-race-condition -
# lihat room_locks di reservation_service.py untuk pola & alasan yang sama: MongoDB
# standalone tanpa transaction, backend 1 proses). Mencegah 2 staf approve/reject
# permintaan yang SAMA nyaris bersamaan sama-sama lolos cek status "waiting_approval"
# sebelum salah satu sempat menulis - yang bisa menghasilkan 2 booking asli (+2 transaksi
# Tripay) dari 1 permintaan tamu. Ini BUKAN soal bentrok kamar (itu sudah aman lewat
# room_locks di create_reservation, kamar berbeda pun bisa dipilih tiap approval) - ini
# soal jangan sampai 1 permintaan tamu diproses/dipenuhi dua kali.
_request_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def _request_lock(rid: str):
    lock = _request_locks[rid]
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()

# Channel Tripay default untuk auto-approve Day Use (QRIS - paling universal di Indonesia,
# hampir semua e-wallet/mobile banking bisa scan). Kode Tripay sungguhan "QRIS2", BUKAN
# "QRIS" - dicek langsung ke GET /payments/tripay/channels sebelum dipakai di sini.
AUTO_APPROVE_PAYMENT_METHOD = "QRIS2"


def _kode_request() -> str:
    return f"REQ-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"


async def _auto_reject_penuh(doc: Dict[str, Any]) -> None:
    """Day Use yang BENAR-BENAR tidak ada kamar kosong (bukan gagal krn payment_option belum
    jelas atau >1 kamar) - langsung tolak otomatis & kabari tamu jujur SAAT ITU JUGA
    (dikonfirmasi user 2026-07-19), JANGAN dibiarkan nyangkut "waiting_approval" menunggu
    staf sadar sendiri - staf pun tidak akan pernah bisa approve ini (create_reservation
    pasti gagal, memang tidak ada kamar). Konsisten dengan filosofi Day Use otomatis
    end-to-end: hasil negatif pun harus otomatis & cepat, bukan cuma hasil positif."""
    now = now_iso()
    await db.booking_requests.update_one({"id": doc["id"]}, {"$set": {
        "status": "rejected", "rejected_by": "AI WhatsApp (otomatis)",
        "rejected_reason": "Kamar penuh - tidak ada kamar kosong pada tanggal & tipe yang diminta",
        "updated_at": now,
    }})
    pesan = (
        f"Mohon maaf {doc['nama_tamu']}, kamar {doc.get('room_tipe') or ''} untuk Day Use "
        f"tanggal {doc['tanggal_checkin']} sedang penuh. Silakan coba tanggal lain atau tipe "
        f"kamar lain, kami siap bantu."
    )
    from routes.pesan_whatsapp import _kirim_via_provider
    await _kirim_via_provider(doc["no_hp"], pesan)


async def _coba_auto_approve_day_use(doc: Dict[str, Any]) -> None:
    """Auto-approve + auto-kirim link bayar untuk booking Day Use yang tamu sudah sebutkan
    preferensi DP/Lunas-nya sendiri (dikonfirmasi user 2026-07-19: Day Use tidak perlu lagi
    ditinjau staf, langsung diproses berdasarkan ketersediaan kamar real-time - BEDA dari
    Menginap yang TETAP wajib direview staf manual, lihat catatan Business Rules di
    CLAUDE.md soal RedDoorz). Update `doc` di db.bookings_requests LANGSUNG kalau berhasil
    ATAU kalau benar-benar penuh (auto-reject, lihat `_auto_reject_penuh`); kalau tidak
    berlaku sama sekali (bukan day_use, belum ada payment_option, >1 kamar), diam-diam TIDAK
    melakukan apa pun - booking_request tetap "waiting_approval" seperti biasa, staf yang
    proses manual seperti sebelumnya. Tidak pernah melempar exception ke caller (auto-approve
    SELALU best-effort, kegagalannya tidak boleh menggagalkan pembuatan booking_request itu
    sendiri)."""
    try:
        if doc["tipe"] != "day_use" or doc["payment_option_diminta"] not in ("dp50", "full"):
            return
        if doc["jumlah_kamar"] != 1:
            return  # grup >1 kamar tetap lewat review staf (auto-pilih banyak kamar sekaligus lebih berisiko)

        from routes.public import public_availability
        avail = await public_availability(doc["tanggal_checkin"], tipe=doc.get("room_tipe"))
        if not avail["rooms"]:
            await _auto_reject_penuh(doc)
            return

        room = avail["rooms"][0]
        jam = doc.get("jam_checkin") or "14:00"
        start = datetime.fromisoformat(f"{doc['tanggal_checkin']}T{jam}:00+07:00").astimezone(timezone.utc)
        end = start + timedelta(hours=6)

        booking = await create_reservation({
            "room_id": room["id"], "nama_tamu": doc["nama_tamu"], "no_hp": doc["no_hp"],
            "email": "", "no_identitas": "", "kendaraan": "",
            "jumlah_tamu": doc.get("jumlah_tamu", 1),
            "jam_mulai": start, "jam_selesai": end,
            "catatan": doc.get("catatan") or "", "created_by": "AI WhatsApp (otomatis)",
            "tipe": "day_use", "dengan_sarapan": False,
        }, source="whatsapp_auto")

        from routes.tripay import tripay_create_transaction
        trx = await tripay_create_transaction(TripayCreateTransactionBody(
            booking_id=booking["id"], payment_option=doc["payment_option_diminta"],
            method=AUTO_APPROVE_PAYMENT_METHOD,
        ))

        now = now_iso()
        await db.booking_requests.update_one({"id": doc["id"]}, {"$set": {
            "status": "waiting_payment", "booking_ids": [booking["id"]], "group_id": None,
            "approved_by": "AI WhatsApp (otomatis)", "approved_at": now, "updated_at": now,
            "checkout_url": trx.get("checkout_url"), "total": booking["total"],
        }})
        await log_availability_change(room["id"], room["tipe"], 0, "booking_auto_approve_ai", booking_id=booking["id"])

        pesan = (
            f"Halo {doc['nama_tamu']}, booking Day Use Anda *otomatis dikonfirmasi* berdasarkan "
            f"ketersediaan kamar saat ini!\n\n"
            f"Kamar: {room['nomor']} ({room['tipe']})\n"
            f"Total: Rp{int(booking['total']):,}".replace(",", ".") + "\n"
            f"Silakan selesaikan pembayaran melalui link berikut:\n{trx.get('checkout_url')}"
        )
        from routes.pesan_whatsapp import _kirim_via_provider
        await _kirim_via_provider(doc["no_hp"], pesan)
    except Exception as e:
        # Best-effort murni - kalau ADA yang gagal di tengah jalan (Tripay down, kamar
        # keburu terisi race condition, dst), booking_request tetap "waiting_approval",
        # staf tetap bisa proses manual seperti biasa. Tidak pernah bikin buat_booking_request
        # gagal gara-gara ini.
        logging.getLogger("booking_requests").warning(f"Auto-approve day_use {doc.get('kode')} gagal: {e}")


async def buat_booking_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Dipanggil dari alur pengumpulan data AI WhatsApp (pesan_whatsapp.py) setelah field
    wajib lengkap & tamu konfirmasi — sengaja BUKAN endpoint HTTP publik (tidak menambah
    permukaan serangan baru untuk membuat data). `data` wajib berisi: nama_tamu, no_hp,
    tipe (day_use|menginap), room_tipe, tanggal_checkin; boleh berisi jumlah_kamar,
    jumlah_tamu, jam_checkin (day_use), tanggal_checkout (menginap), catatan,
    payment_option (dp50|full — preferensi tamu KALAU disebutkan sendiri di chat, lihat
    BOOKING_FLOW_SYSTEM_PROMPT; None kalau belum disebut — staf yang putuskan saat approve)."""
    payment_option = data.get("payment_option")

    # Guard tanggal masa lalu (2026-07-19, audit reliabilitas AI booking flow) - AI WhatsApp
    # sekarang selalu diberi tanggal hari ini di prompt-nya (lihat build_dynamic_prompt di
    # ai-chat-bot), tapi tetap divalidasi keras di sini sebagai lapis pertahanan kedua kalau
    # model salah ekstrak tanggal (mis. tamu bilang "kemarin" bercanda, atau typo tahun) -
    # jangan sampai booking_request nyangkut untuk tanggal yang sudah lewat, staf pasti bingung.
    try:
        tanggal_checkin_date = datetime.fromisoformat(data["tanggal_checkin"]).date()
    except (ValueError, TypeError):
        raise HTTPException(400, "Format tanggal_checkin tidak valid (harus YYYY-MM-DD)")
    if tanggal_checkin_date < datetime.now().date():
        raise HTTPException(400, "Tanggal check-in tidak boleh di masa lalu - tanya ulang tanggal yang benar ke tamu")

    # Preview diskon member (Program Loyalitas Kedatangan, dikonfirmasi user 2026-07-19) -
    # cuma INFORMASIONAL di tahap permintaan (supaya AI/staf tahu & tamu diberi tahu di
    # muka), dihitung ULANG & jadi final saat staf approve (lewat create_reservation) -
    # kalau ada jeda waktu & total_kunjungan berubah, angka final yang berlaku.
    diskon_info = await hitung_diskon_member(data["no_hp"])

    doc = {
        "id": str(uuid.uuid4()), "kode": _kode_request(),
        "nama_tamu": data["nama_tamu"], "no_hp": data["no_hp"],
        "tipe": data["tipe"], "room_tipe": data.get("room_tipe"),
        "jumlah_kamar": int(data.get("jumlah_kamar") or 1),
        "jumlah_tamu": int(data.get("jumlah_tamu") or 1),
        "tanggal_checkin": data["tanggal_checkin"], "jam_checkin": data.get("jam_checkin"),
        "tanggal_checkout": data.get("tanggal_checkout"), "catatan": data.get("catatan") or "",
        "payment_option_diminta": payment_option if payment_option in ("dp50", "full") else None,
        "preview_kedatangan_ke": diskon_info["kedatangan_ke"], "preview_diskon_persen": diskon_info["diskon_persen"],
        "status": "waiting_approval", "source": "whatsapp",
        "booking_ids": [], "group_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.booking_requests.insert_one(doc)

    from routes.push import send_push
    from routes.telegram_bot import kirim_alert_owner

    # Day Use dengan payment_option jelas: coba auto-approve + auto-kirim link bayar
    # langsung (dikonfirmasi user 2026-07-19), TIDAK perlu menunggu staf klik Terima di
    # PMS - beda dari Menginap yang tetap wajib direview manual. Best-effort, diam-diam
    # tidak melakukan apa pun kalau gagal/tidak berlaku (lihat docstring fungsinya).
    await _coba_auto_approve_day_use(doc)
    doc = await db.booking_requests.find_one({"id": doc["id"]}, {"_id": 0}) or doc

    ringkas = (
        f"{doc['nama_tamu']} — {doc['tipe']} {doc['room_tipe'] or ''} x{doc['jumlah_kamar']}, "
        f"{doc['tanggal_checkin']}"
    )
    if doc["status"] == "waiting_payment":
        # Auto-approved - FYI ke owner, BUKAN alert "perlu ditinjau" (tidak ada aksi yang
        # perlu staf lakukan, link bayar sudah otomatis terkirim ke tamu).
        await kirim_alert_owner(
            f"✅ Booking Day Use OTOMATIS terkonfirmasi ({doc['kode']})\n\n"
            f"Nama: {doc['nama_tamu']}\nHP: {doc['no_hp']}\n"
            f"Tipe: {doc['tipe']} — {doc['room_tipe'] or '-'}, {doc['tanggal_checkin']}"
            + (f" {doc['jam_checkin']}" if doc.get("jam_checkin") else "") +
            f"\nTotal: Rp{int(doc.get('total') or 0):,}".replace(",", ".") +
            "\n\nLink pembayaran sudah otomatis terkirim ke tamu - tidak perlu tindakan."
        )
    elif doc["status"] == "rejected":
        # Auto-reject karena benar-benar penuh - FYI juga (bukan "perlu ditinjau", tamu
        # sudah otomatis dikabari penuh, tidak ada aksi staf yang perlu diambil).
        await kirim_alert_owner(
            f"❌ Booking Day Use OTOMATIS ditolak - kamar penuh ({doc['kode']})\n\n"
            f"Nama: {doc['nama_tamu']}\nHP: {doc['no_hp']}\n"
            f"Tipe: {doc['tipe']} — {doc['room_tipe'] or '-'}, {doc['tanggal_checkin']}"
            + (f" {doc['jam_checkin']}" if doc.get("jam_checkin") else "") +
            "\n\nTamu sudah otomatis dikabari kamar penuh - tidak perlu tindakan."
        )
    else:
        await send_push("Permintaan Booking Baru", ringkas, url="/booking-requests")
        await kirim_alert_owner(
            f"📩 Permintaan Booking Baru ({doc['kode']})\n\n"
            f"Nama: {doc['nama_tamu']}\nHP: {doc['no_hp']}\n"
            f"Tipe: {doc['tipe']} — {doc['room_tipe'] or '(belum tentu)'} x{doc['jumlah_kamar']}, "
            f"{doc['jumlah_tamu']} tamu\n"
            f"Check-in: {doc['tanggal_checkin']}" + (f" {doc['jam_checkin']}" if doc.get("jam_checkin") else "") +
            (f"\nCheck-out: {doc['tanggal_checkout']}" if doc.get("tanggal_checkout") else "") +
            (f"\nTamu minta: {'DP 50%' if doc['payment_option_diminta'] == 'dp50' else 'Bayar Penuh'}" if doc.get("payment_option_diminta") else "") +
            (f"\nKedatangan ke-{diskon_info['kedatangan_ke']}, diskon member {diskon_info['diskon_persen']}%" if diskon_info["diskon_persen"] else "") +
            "\n\nTinjau di PMS → Booking Request."
        )
    return doc


@api.get("/booking-requests")
async def list_booking_requests(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    """`status` mentah cuma tahu 3 nilai (waiting_approval/waiting_payment/rejected) —
    begitu di-approve, status TIDAK PERNAH otomatis lanjut lagi biar pun tamu sudah bayar
    (lihat approve_booking_request: satu-satunya penulis field ini). Supaya staf bisa lihat
    riwayat permintaan yang SUDAH benar-benar selesai (lunas), tiap item di sini diperkaya
    `status_efektif` (menambah nilai virtual "lunas") + `booking_ringkasan` (status booking
    sungguhan yang terkait) dengan mengecek payment_status booking yang sudah dibuat saat
    approve. `status=lunas` di query jadi filter virtual tambahan (bukan field asli)."""
    raw_status = status if status in ("waiting_approval", "waiting_payment", "rejected") else None
    q: Dict[str, Any] = {}
    if raw_status:
        q["status"] = raw_status
    elif status == "lunas":
        q["status"] = "waiting_payment"
    items = await db.booking_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)

    for it in items:
        it["status_efektif"] = it["status"]
        it["booking_ringkasan"] = None
        if it.get("booking_ids"):
            bks = await db.bookings.find({"id": {"$in": it["booking_ids"]}}, {"_id": 0}).to_list(20)
            if bks:
                it["booking_ringkasan"] = [{
                    "kode": b["kode"], "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
                    "status": b.get("status"), "payment_status": b.get("payment_status"),
                    "sync_status": b.get("sync_status"), "total": b.get("total"),
                    "payment_option": b.get("payment_option"),
                    **status_bayar_booking(b),  # status_bayar, jumlah_dibayar, sisa_tagihan
                } for b in bks]
                if it["status"] == "waiting_payment" and all(b.get("payment_status") == "paid" for b in bks):
                    it["status_efektif"] = "lunas"

    if status == "lunas":
        items = [it for it in items if it["status_efektif"] == "lunas"]
    elif status == "waiting_payment":
        items = [it for it in items if it["status_efektif"] == "waiting_payment"]
    return items


@api.get("/booking-requests/{rid}")
async def get_booking_request(rid: str, user: dict = Depends(get_current_user)):
    r = await db.booking_requests.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Permintaan booking tidak ditemukan")
    return r


@api.post("/booking-requests/{rid}/approve")
async def approve_booking_request(rid: str, body: BookingRequestApprove, user: dict = Depends(get_current_user)):
    """Setujui permintaan: staf sudah mengecek ketersediaan (termasuk RedDoorz, manual di
    luar sistem) & memilih kamar spesifik. Membuat booking SUNGGUHAN (status booking_pending,
    sama seperti alur publik) untuk tiap kamar via create_reservation (tetap lewat
    check_room_available — hard validator anti-overbooking yang sama, tidak dilewati), lalu
    langsung membuat transaksi Tripay & mengirim link bayar ke tamu lewat WhatsApp."""
    # Seluruh proses dibungkus _request_lock(rid) (2026-07-19, audit anti-race-condition
    # lanjutan) - termasuk pengecekan status "waiting_approval" itu sendiri, supaya kalau 2
    # staf klik Terima nyaris bersamaan, yang kedua benar-benar membaca status TERBARU
    # (bukan status basi dari sebelum yang pertama selesai) dan ditolak dengan bersih,
    # bukan sama-sama lolos dan membuat 2 booking asli dari 1 permintaan.
    async with _request_lock(rid):
        req = await db.booking_requests.find_one({"id": rid})
        if not req:
            raise HTTPException(404, "Permintaan booking tidak ditemukan")
        if req["status"] not in STATUS_TERBUKA:
            raise HTTPException(400, f"Hanya permintaan waiting_approval yang bisa disetujui (status: {req['status']})")
        if body.payment_option not in ("dp50", "full"):
            raise HTTPException(400, "payment_option harus 'dp50' atau 'full'")
        room_ids = list(dict.fromkeys(body.room_ids or []))
        if len(room_ids) != req.get("jumlah_kamar", 1):
            raise HTTPException(400, f"Pilih tepat {req.get('jumlah_kamar', 1)} kamar sesuai permintaan")

        tipe = req["tipe"]
        if tipe == "menginap":
            if not req.get("tanggal_checkout"):
                raise HTTPException(400, "Permintaan ini tidak punya tanggal_checkout — tidak bisa disetujui sebagai menginap")
            try:
                ci = datetime.fromisoformat(f"{req['tanggal_checkin']}T14:00:00+07:00")
                co = datetime.fromisoformat(f"{req['tanggal_checkout']}T12:00:00+07:00")
            except Exception:
                raise HTTPException(400, "Tanggal check-in/checkout pada permintaan tidak valid")
            if co <= ci:
                raise HTTPException(400, "Tanggal check-out harus setelah check-in")
            start, end = ci.astimezone(timezone.utc), co.astimezone(timezone.utc)
            nights = max(1, (co.date() - ci.date()).days)
        else:
            try:
                jam = req.get("jam_checkin") or "14:00"
                start = datetime.fromisoformat(f"{req['tanggal_checkin']}T{jam}:00+07:00").astimezone(timezone.utc)
            except Exception:
                raise HTTPException(400, "Tanggal/jam check-in pada permintaan tidak valid")
            end = start + timedelta(hours=6)
            nights = 1

        # Dari titik ini, kalau ADA yang gagal (mis. Tripay error) SETELAH booking asli
        # sempat dibuat, rollback booking yang sudah terlanjur dibuat & biarkan
        # booking_request tetap "waiting_approval" (2026-07-19, audit anti-race-condition
        # lanjutan) - supaya staf bisa klik Terima lagi dengan aman tanpa meninggalkan
        # booking "yatim" yang mengunci kamar tanpa pembayaran/transaksi, dan tanpa
        # menghasilkan booking DOBEL kalau retry dilakukan.
        created_bookings = []
        try:
            for room_id in room_ids:
                r = await db.rooms.find_one({"id": room_id})
                if not r:
                    raise HTTPException(404, f"Kamar tidak ditemukan (id {room_id})")
                harga_override = None
                if tipe == "menginap":
                    subtotal = int(r["tarif_menginap"]) * nights
                    service_fee = round(subtotal * SERVICE_FEE_PCT)
                    total = subtotal + service_fee
                    harga_override = {"subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": round(total * 0.5)}
                data = {
                    "room_id": room_id, "nama_tamu": req["nama_tamu"], "no_hp": req["no_hp"],
                    "email": "", "no_identitas": "", "kendaraan": "",
                    "jumlah_tamu": req.get("jumlah_tamu", 1),
                    "jam_mulai": start, "jam_selesai": end,
                    "catatan": req.get("catatan") or "", "created_by": user["nama"],
                    "tipe": tipe, "dengan_sarapan": False,
                }
                booking = await create_reservation(data, source="whatsapp_request", harga_override=harga_override)
                # Tahap 2 (PRD Modul Reservasi): booking Menginap dari Booking Request TIDAK langsung
                # dianggap "Confirmed" — admin harus input manual ke PMS RedDoorz dulu, baru dianggap
                # pasti setelah email konfirmasi RedDoorz cocok (lihat otomasi_email.py). Day Use tidak
                # pernah masuk RedDoorz (aturan lama, tidak berubah), jadi langsung "not_required".
                sync_status = "waiting_reddoorz_input" if tipe == "menginap" else "not_required"
                await db.bookings.update_one({"id": booking["id"]}, {"$set": {"sync_status": sync_status}})
                booking["sync_status"] = sync_status
                created_bookings.append(booking)

            group_id = None
            if len(created_bookings) > 1:
                group_id = str(uuid.uuid4())
                for b in created_bookings:
                    await db.bookings.update_one({"id": b["id"]}, {"$set": {"group_id": group_id}})

            total_group = sum(int(b["total"]) for b in created_bookings)

            from routes.tripay import tripay_create_transaction
            trx = await tripay_create_transaction(TripayCreateTransactionBody(
                booking_id=created_bookings[0]["id"], payment_option=body.payment_option, method=body.method,
            ))

            now = now_iso()
            await db.booking_requests.update_one({"id": rid}, {"$set": {
                "status": "waiting_payment", "booking_ids": [b["id"] for b in created_bookings], "group_id": group_id,
                "approved_by": user["nama"], "approved_at": now, "updated_at": now,
                "checkout_url": trx.get("checkout_url"), "total": total_group,
            }})
            await log_activity(user, "approve_booking_request", f"Setujui permintaan booking {req['kode']} ({req['nama_tamu']})")

            pesan = (
                f"Halo {req['nama_tamu']}, permintaan booking Anda kami *setujui*!\n\n"
                f"Total: Rp{total_group:,}".replace(",", ".") + "\n"
                f"Silakan selesaikan pembayaran melalui link berikut:\n{trx.get('checkout_url')}"
            )
            try:
                from routes.pesan_whatsapp import _kirim_via_provider
                await _kirim_via_provider(req["no_hp"], pesan)
            except Exception as e:
                logging.getLogger("booking_requests").warning(f"Gagal kirim link bayar ke {req['no_hp']}: {e}")
        except Exception:
            for b in created_bookings:
                await db.bookings.update_one({"id": b["id"]}, {"$set": {
                    "status": "cancelled", "cancelled_at": now_iso(),
                    "cancelled_by": "system_rollback_approve_gagal",
                }})
                await log_availability_change(
                    b["room_id"], b.get("room_tipe", ""), 1, "booking_dibatalkan_rollback_approve_gagal",
                    booking_id=b["id"],
                )
            raise

    return await db.booking_requests.find_one({"id": rid}, {"_id": 0})


@api.post("/booking-requests/{rid}/reject")
async def reject_booking_request(rid: str, body: BookingRequestReject, user: dict = Depends(get_current_user)):
    # Lock sama (_request_lock) dengan approve - satu rid tidak boleh di-approve & ditolak
    # bersamaan oleh 2 staf berbeda juga (2026-07-19, audit anti-race-condition lanjutan).
    async with _request_lock(rid):
        req = await db.booking_requests.find_one({"id": rid})
        if not req:
            raise HTTPException(404, "Permintaan booking tidak ditemukan")
        if req["status"] not in STATUS_TERBUKA:
            raise HTTPException(400, f"Hanya permintaan waiting_approval yang bisa ditolak (status: {req['status']})")
        now = now_iso()
        await db.booking_requests.update_one({"id": rid}, {"$set": {
            "status": "rejected", "rejected_by": user["nama"], "rejected_reason": body.alasan or "", "updated_at": now,
        }})
        await log_activity(user, "reject_booking_request", f"Tolak permintaan booking {req['kode']} ({req['nama_tamu']}): {body.alasan or '-'}")

        pesan = (
            f"Mohon maaf {req['nama_tamu']}, untuk permintaan booking tanggal {req['tanggal_checkin']} "
            f"kami belum bisa memenuhi" + (f": {body.alasan}." if body.alasan else " saat ini.") +
            " Silakan hubungi kami lagi untuk tanggal lain, kami siap bantu."
        )
        try:
            from routes.pesan_whatsapp import _kirim_via_provider
            await _kirim_via_provider(req["no_hp"], pesan)
        except Exception as e:
            logging.getLogger("booking_requests").warning(f"Gagal kirim pesan tolak ke {req['no_hp']}: {e}")

    return await db.booking_requests.find_one({"id": rid}, {"_id": 0})
