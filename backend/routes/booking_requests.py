"""Booking Request — Tahap 1 dari PRD "Modul Reservasi, Priority Booking & Payment Flow"
(diberi lampu hijau user 2026-07-17, lihat CLAUDE.md & memory project_reservasi_priority_booking_prd).

Entitas baru (`db.booking_requests`) — permintaan booking NON-BINDING yang dikumpulkan AI
WhatsApp (routes/pesan_whatsapp.py), ditinjau manual staf (approve/reject di sini), baru
menjadi booking sungguhan (`db.bookings`) setelah disetujui. AI WhatsApp TIDAK PERNAH punya
akses membuat dokumen di sini secara langsung selain lewat `buat_booking_request()` — dan
fungsi itu sendiri tidak pernah membuat booking, cuma permintaan.

Tahap 1 SENGAJA berhenti setelah tamu membayar (booking real dibuat & dibayar via Tripay
persis seperti alur publik yang sudah ada — reuse `create_reservation`/`tripay_create_transaction`,
tidak ada jalur pembayaran paralel baru). Bagian PRD yang BELUM dibangun di sini (Tahap 2,
menyusul terpisah): status "Action Required" untuk booking Menginap (input manual ke PMS
RedDoorz), penyaringan booking Menginap dari Calendar/Dashboard/Housekeeping/Laporan sampai
email konfirmasi RedDoorz diterima, dan mematikan/redirect tombol Book Now publik.
"""
from core import *
from reservation_service import create_reservation

STATUS_TERBUKA = ["waiting_approval"]


def _kode_request() -> str:
    return f"REQ-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"


async def buat_booking_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Dipanggil dari alur pengumpulan data AI WhatsApp (pesan_whatsapp.py) setelah field
    wajib lengkap & tamu konfirmasi — sengaja BUKAN endpoint HTTP publik (tidak menambah
    permukaan serangan baru untuk membuat data). `data` wajib berisi: nama_tamu, no_hp,
    tipe (day_use|menginap), room_tipe, tanggal_checkin; boleh berisi jumlah_kamar,
    jumlah_tamu, jam_checkin (day_use), tanggal_checkout (menginap), catatan,
    payment_option (dp50|full — preferensi tamu KALAU disebutkan sendiri di chat, lihat
    BOOKING_FLOW_SYSTEM_PROMPT; None kalau belum disebut — staf yang putuskan saat approve)."""
    payment_option = data.get("payment_option")
    doc = {
        "id": str(uuid.uuid4()), "kode": _kode_request(),
        "nama_tamu": data["nama_tamu"], "no_hp": data["no_hp"],
        "tipe": data["tipe"], "room_tipe": data.get("room_tipe"),
        "jumlah_kamar": int(data.get("jumlah_kamar") or 1),
        "jumlah_tamu": int(data.get("jumlah_tamu") or 1),
        "tanggal_checkin": data["tanggal_checkin"], "jam_checkin": data.get("jam_checkin"),
        "tanggal_checkout": data.get("tanggal_checkout"), "catatan": data.get("catatan") or "",
        "payment_option_diminta": payment_option if payment_option in ("dp50", "full") else None,
        "status": "waiting_approval", "source": "whatsapp",
        "booking_ids": [], "group_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.booking_requests.insert_one(doc)

    from routes.push import send_push
    from routes.telegram_bot import kirim_alert_owner
    ringkas = (
        f"{doc['nama_tamu']} — {doc['tipe']} {doc['room_tipe'] or ''} x{doc['jumlah_kamar']}, "
        f"{doc['tanggal_checkin']}"
    )
    await send_push("Permintaan Booking Baru", ringkas, url="/booking-requests")
    await kirim_alert_owner(
        f"📩 Permintaan Booking Baru ({doc['kode']})\n\n"
        f"Nama: {doc['nama_tamu']}\nHP: {doc['no_hp']}\n"
        f"Tipe: {doc['tipe']} — {doc['room_tipe'] or '(belum tentu)'} x{doc['jumlah_kamar']}, "
        f"{doc['jumlah_tamu']} tamu\n"
        f"Check-in: {doc['tanggal_checkin']}" + (f" {doc['jam_checkin']}" if doc.get("jam_checkin") else "") +
        (f"\nCheck-out: {doc['tanggal_checkout']}" if doc.get("tanggal_checkout") else "") +
        (f"\nTamu minta: {'DP 50%' if doc['payment_option_diminta'] == 'dp50' else 'Bayar Penuh'}" if doc.get("payment_option_diminta") else "") +
        "\n\nTinjau di PMS → Booking Request."
    )
    doc.pop("_id", None)
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

    created_bookings = []
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

    return await db.booking_requests.find_one({"id": rid}, {"_id": 0})


@api.post("/booking-requests/{rid}/reject")
async def reject_booking_request(rid: str, body: BookingRequestReject, user: dict = Depends(get_current_user)):
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
