from core import *
from reservation_service import check_room_available, create_reservation
from email_service import generate_voucher_pdf, send_voucher_email
import httpx
import io
from fastapi.responses import StreamingResponse

@api.get("/public/rooms-catalog")
async def public_rooms_catalog():
    """Katalog kamar untuk halaman publik. Mengelompokkan berdasarkan tipe.
    Tidak mengekspos field internal seperti info / status detail.
    """
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    rooms.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    grouped: Dict[str, Any] = {}
    for r in rooms:
        t = r["tipe"]
        if t not in grouped:
            grouped[t] = {
                "tipe": t,
                "tarif": r["tarif"],
                "fasilitas": [
                    "AC", "Wi-Fi gratis", "TV LED", "Kamar mandi dalam",
                    "Air panas", "Handuk & toiletries",
                ] + (["Cottage Style", "Area Outdoor"] if t == "Cottage" else []),
                "rooms": [],
            }
        grouped[t]["rooms"].append({"id": r["id"], "nomor": r["nomor"]})
    return list(grouped.values())

@api.get("/public/availability")
async def public_availability(tanggal: str, tipe: Optional[str] = None, checkout: Optional[str] = None):
    """List kamar tersedia pada tanggal tertentu (halaman publik).
    Untuk tanggal MASA DEPAN, status realtime kamar (day_use/menginap/perlu_dibersihkan) TIDAK relevan
    karena akan kembali kosong sebelum tanggal tersebut. Hanya `maintenance` (long-term) yang di-exclude.
    Filter utama: tidak ada booking_pending/booking_paid/aktif yang overlap dengan tanggal target.

    `checkout` (opsional, YYYY-MM-DD) dipakai untuk booking menginap: kalau diisi,
    window overlap yang dicek adalah seluruh rentang [tanggal, checkout), bukan cuma
    1 hari — supaya kamar yang sudah dibooking di salah satu malam dalam rentang itu
    tidak muncul sebagai tersedia.
    """
    try:
        d = datetime.fromisoformat(tanggal)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    d_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    if checkout:
        try:
            d_end = datetime.fromisoformat(checkout).replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception:
            raise HTTPException(400, "Format tanggal checkout harus YYYY-MM-DD")
        if d_end <= d_start:
            raise HTTPException(400, "Tanggal checkout harus setelah tanggal check-in")
    else:
        d_end = d_start + timedelta(days=1)
    # Untuk hari INI, kamar yang sedang dipakai (day_use/menginap/perlu_dibersihkan) tidak tersedia.
    # Untuk hari LAIN (masa depan), hanya 'maintenance' yang dikecualikan.
    today_local = datetime.now().strftime("%Y-%m-%d")
    is_today = tanggal == today_local
    q: Dict[str, Any] = {}
    if tipe:
        q["tipe"] = tipe
    if is_today:
        q["status"] = "kosong"
    else:
        q["status"] = {"$ne": "maintenance"}
    rooms = await db.rooms.find(q, {"_id": 0}).to_list(500)
    # Filter rooms yang punya booking overlap di tanggal tsb
    out = []
    for r in rooms:
        bk = await db.bookings.find_one({
            "room_id": r["id"],
            "status": {"$in": ["aktif", "booking_paid", "booking_pending"]},
            "jam_mulai": {"$lt": d_end.isoformat()},
            "jam_selesai": {"$gt": d_start.isoformat()},
        })
        if not bk:
            out.append({"id": r["id"], "nomor": r["nomor"], "tipe": r["tipe"], "tarif": r["tarif"]})
    out.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    return {"tanggal": tanggal, "tipe": tipe, "rooms": out}

@api.post("/public/bookings")
async def public_create_booking(body: PublicBookingCreate):
    """Booking publik (tanpa login). Membuat booking dengan status 'booking_pending'.
    Tarif = tarif kamar (x malam untuk menginap) + 3% service fee. Wajib bayar (DP 50%
    min) via Midtrans Snap. Day use: 6 jam dari jam check-in (default lama, tidak berubah).
    Menginap: check-out fixed jam 12:00 WIB, harga dihitung per malam (termasuk extra bed).
    """
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "Tipe booking tidak valid")
    # Validasi email wajib (untuk kirim bukti pembayaran)
    email = (body.email or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Email wajib diisi dengan format yang valid (untuk menerima bukti pembayaran)")
    # Parse tanggal + jam check-in (WIB +07:00)
    try:
        local_in = datetime.fromisoformat(f"{body.tanggal}T{body.jam_checkin}:00+07:00")
    except Exception:
        raise HTTPException(400, "Format tanggal/jam tidak valid")
    start = local_in.astimezone(timezone.utc)

    harga_override = None
    if body.tipe == "menginap":
        if not body.tanggal_checkout:
            raise HTTPException(400, "Booking menginap wajib mengisi tanggal check-out")
        try:
            local_out = datetime.fromisoformat(f"{body.tanggal_checkout}T12:00:00+07:00")
        except Exception:
            raise HTTPException(400, "Format tanggal check-out tidak valid")
        end = local_out.astimezone(timezone.utc)
        if end <= start:
            raise HTTPException(400, "Tanggal check-out harus setelah tanggal check-in")
        nights = max(1, (local_out.date() - local_in.date()).days)
        r = await db.rooms.find_one({"id": body.room_id})
        if not r:
            raise HTTPException(404, "Kamar tidak ditemukan")
        extra_bed_qty = max(0, min(EXTRA_BED_MAX, int(body.extra_bed_qty or 0)))
        subtotal = r["tarif"] * nights + extra_bed_qty * EXTRA_BED_PRICE * nights
        service_fee = round(subtotal * SERVICE_FEE_PCT)
        total = subtotal + service_fee
        harga_override = {"subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": round(total * 0.5)}
    else:
        end = start + timedelta(hours=6)  # day use 6 jam default

    data = {
        "room_id": body.room_id,
        "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
        "email": email,
        "no_identitas": body.no_identitas, "kendaraan": body.kendaraan,
        "jumlah_tamu": body.jumlah_tamu, "extra_bed_qty": body.extra_bed_qty,
        "jam_mulai": start, "jam_selesai": end,
        "catatan": body.catatan,
        "created_by": body.nama_tamu,
        "tipe": body.tipe,
    }
    return await create_reservation(data, source="online", harga_override=harga_override)

def _batas_jam_bebas_biaya(tipe: str) -> int:
    return 72 if tipe == "menginap" else 24  # H-3 menginap, H-1 day use


def _hitung_kebijakan_pembatalan(b: dict) -> dict:
    """Sama persis dengan calcCancelPolicy di PublicBook.jsx (frontend) — dipertahankan
    identik supaya biaya yang ditampilkan ke tamu = biaya yang benar-benar dipotong saat
    pembatalan mandiri sungguhan dieksekusi di endpoint ini."""
    batas_jam = _batas_jam_bebas_biaya(b.get("tipe", "day_use"))
    jam_checkin = parse_iso(b["jam_mulai"], "jam_mulai")
    jam_tersisa = (jam_checkin - datetime.now(timezone.utc)).total_seconds() / 3600
    dasar_biaya = int(b["total"]) if b.get("payment_status") == "paid" else int(b.get("dp_min") or 0)
    if jam_tersisa < 0:
        return {"label": "Hari check-in / lewat", "biaya": dasar_biaya, "gratis": False}
    if jam_tersisa < batas_jam:
        return {"label": f"Kurang dari {'H-3' if batas_jam == 72 else 'H-1'}", "biaya": round(dasar_biaya * 0.1), "gratis": False}
    return {"label": f"Lebih dari {'H-3' if batas_jam == 72 else 'H-1'}", "biaya": 0, "gratis": True}


@api.post("/public/bookings/{bid}/batalkan")
async def public_batalkan_booking(bid: str, body: CancelWithFeeBody = CancelWithFeeBody()):
    """Pembatalan mandiri SUNGGUHAN oleh tamu (bukan cuma 'ajukan permintaan') — otomatis
    penuh tanpa approval staf, sesuai keputusan bisnis yang dikonfirmasi user 2026-07-11.
    Refund uang (kalau ada) tetap harus ditransfer manual oleh staf — sistem cuma
    menghitung & mencatat nominalnya (refund_amount), tidak memproses transfer sungguhan.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, f"Booking tidak dapat dibatalkan (status: {b.get('status')})")

    policy = _hitung_kebijakan_pembatalan(b)
    biaya = policy["biaya"]
    paid = int(b.get("amount_due") or 0)
    is_paid = b.get("payment_status") == "paid"
    refund = max(0, paid - biaya) if is_paid else 0

    now = now_iso()
    update_fields = {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": "guest_self_service",
        "cancel_reason": body.alasan or "Dibatalkan mandiri oleh tamu",
        "cancel_fee": biaya, "refund_amount": refund,
    }
    if is_paid:
        update_fields["payment_status"] = "refunded" if refund > 0 else "forfeited"
    await db.bookings.update_one({"id": bid}, {"$set": update_fields})
    await log_availability_change(b["room_id"], b.get("room_tipe", ""), 1, "booking_dibatalkan_mandiri", booking_id=b["id"])
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "guest_self_service",
        "action": "cancel_self_service",
        "detail": f"Tamu batalkan mandiri {b['kode']}: biaya Rp{biaya:,}, {'refund Rp' + format(refund, ',') if refund > 0 else 'tidak ada refund'}".replace(",", "."),
        "entity": b.get("room_nomor", ""), "timestamp": now,
    })

    # Notifikasi konfirmasi ke tamu via WhatsApp (best-effort — pakai webhook yang sama
    # dengan bot WhatsApp, kalau staf sudah konfigurasi; kalau belum, cukup dilewati saja).
    try:
        from routes.pesan_whatsapp import _kirim_via_provider
        pesan = (
            f"Booking {b['kode']} sudah dibatalkan. "
            + (f"Biaya pembatalan Rp{biaya:,}.".replace(",", ".") if biaya else "Tidak ada biaya pembatalan.")
            + (f" Refund Rp{refund:,} akan diproses staf kami.".replace(",", ".") if refund > 0 else "")
        )
        await _kirim_via_provider(b["no_hp"], pesan)
    except Exception:
        pass

    return {
        "ok": True, "booking_kode": b["kode"], "cancel_fee": biaya, "refund_amount": refund,
        "policy_label": policy["label"], "gratis": policy["gratis"],
    }


@api.get("/public/bookings/{bid}")
async def public_get_booking(bid: str):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    # batasi field yang dikembalikan ke publik
    safe = {k: b.get(k) for k in [
        "id", "kode", "room_nomor", "room_tipe", "tipe", "nama_tamu", "no_hp", "email",
        "jumlah_tamu", "extra_bed_qty", "jam_mulai", "jam_selesai", "status", "payment_status",
        "subtotal", "service_fee", "total", "dp_min", "invoice_id",
    ]}
    return safe


@api.get("/pengiriman-voucher/logs")
async def list_email_send_log(user: dict = Depends(get_current_user)):
    """Log pengiriman voucher ke tamu (staf). Terisi begitu ada pengiriman lewat
    Brevo (otomatis setelah pembayaran sukses, atau kirim ulang manual)."""
    return await db.email_send_log.find({}, {"_id": 0}).sort("waktu", -1).to_list(200)


@api.post("/pengiriman-voucher/kirim-ulang/{bid}")
async def resend_voucher_email(bid: str, user: dict = Depends(get_current_user)):
    """Kirim ulang voucher ke email tamu secara manual (dipicu staf dari halaman
    Log Pengiriman, misalnya karena pengiriman otomatis sebelumnya gagal)."""
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    pdf_bytes = generate_voucher_pdf(b)
    log_entry = await send_voucher_email(b, pdf_bytes)
    if log_entry["status"] != "Terkirim":
        raise HTTPException(502, log_entry["error"] or "Gagal mengirim voucher")
    return log_entry


@api.get("/public/bookings/{bid}/voucher.pdf")
async def public_download_voucher_pdf(bid: str):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    pdf_bytes = generate_voucher_pdf(b)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="voucher-{b["kode"]}.pdf"'},
    )
