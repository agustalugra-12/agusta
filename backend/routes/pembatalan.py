"""Pembatalan Booking via AI WhatsApp (dikonfirmasi user 2026-07-19).

Beda dengan pembatalan mandiri tamu di public.py (`public_batalkan_booking` — self-service,
eksekusi otomatis): AI TIDAK PERNAH mengeksekusi pembatalan sungguhan secara langsung (sama
seperti create_booking) — peran AI cuma "memberikan info ke PMS", PMS yang mencatat sebagai
permintaan (`cancel_request_status` di `db.bookings`), staf yang approve/reject manual.

Kebijakan refund SAMA dengan self-service (disatukan 2026-07-19, keputusan user "samakan
semua channel" - sebelumnya 2 aturan berbeda per channel membingungkan tamu) - lihat
`hitung_kebijakan_pembatalan` di core.py untuk aturan & alasan lengkapnya.

Refund sendiri (transfer uang) TETAP MANUAL oleh staf, sistem cuma menghitung nominal &
melacak status: requested (menunggu staf) -> pending (disetujui, tunggu refund dikirim
manual) -> refund_sent (staf klik "Sudah Dikirim", otomatis kirim WA konfirmasi ke tamu,
hilang dari daftar aktif/dashboard tapi riwayat tetap ada di db.bookings, bisa dilihat
lewat GET /cancellation-requests?status=riwayat)."""
from core import *

CANCEL_STATUS_AKTIF = ["requested", "pending"]


async def ajukan_pembatalan_ai(kode: str, no_hp: str, alasan: str = "") -> Dict[str, Any]:
    """Dipanggil dari routes/integrasi_ai_bot.py (tool cancel_booking di ai-chat-bot) —
    non-binding, TIDAK PERNAH langsung mengubah status booking, cuma menandai
    cancel_request_status supaya staf lihat & approve/reject manual di Dashboard.

    `kode` OPSIONAL (2026-07-21, perbaikan arsitektur - bukan cuma prompt) - insiden nyata
    BERULANG: AI (model lemah, gpt-4o-mini) sering gagal mengoordinasikan 2 tool call
    terpisah (lookup_booking dulu utk dapat kode, BARU cancel_booking pakai kode itu di
    giliran berikutnya) - kadang cuma manggil lookup_booking lalu NARASIKAN seolah sudah
    dibatalkan tanpa benar-benar memanggil cancel_booking. Sekarang kalau `kode` kosong,
    fungsi ini SENDIRI yang mencari booking aktif tamu dari no_hp - AI cukup 1x panggil
    tool ini langsung begitu tamu konfirmasi, tidak perlu lookup_booking dulu utk kasus
    umum (tamu cuma punya 1 booking aktif)."""
    digits = re.sub(r"\D", "", no_hp or "")
    if not digits:
        return {"ok": False, "error": "Nomor WhatsApp tidak valid"}

    if kode:
        b = await db.bookings.find_one({"kode": kode})
        if not b:
            return {"ok": False, "error": f"Booking dengan kode {kode} tidak ditemukan"}
        if digits not in phone_variants(b.get("no_hp")):
            return {"ok": False, "error": "Nomor WhatsApp tidak cocok dengan pemilik booking"}
    else:
        variasi = list(phone_variants(no_hp))
        kandidat = await db.bookings.find({
            "no_hp": {"$in": variasi},
            "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
            "cancel_request_status": {"$nin": CANCEL_STATUS_AKTIF},
        }).sort("created_at", -1).to_list(10)
        if not kandidat:
            return {"ok": False, "error": "Tidak ada booking aktif ditemukan untuk nomor ini yang bisa diajukan pembatalan"}
        if len(kandidat) > 1:
            daftar = [{"kode": k["kode"], "room_tipe": k.get("room_tipe"), "tanggal": (k.get("jam_mulai") or "")[:10]} for k in kandidat]
            return {"ok": False, "error": "Ada lebih dari 1 booking aktif - tamu harus sebutkan yang mana", "kandidat": daftar}
        b = kandidat[0]

    if b.get("status") not in ("aktif", "booking_pending", "booking_paid"):
        return {"ok": False, "error": f"Booking tidak bisa diajukan pembatalan (status: {b.get('status')})"}
    if b.get("cancel_request_status") in CANCEL_STATUS_AKTIF:
        return {"ok": False, "error": "Sudah ada permintaan pembatalan yang menunggu diproses staf untuk booking ini"}

    policy = hitung_kebijakan_pembatalan(b["jam_mulai"])
    paid = int(b.get("amount_due") or 0) if b.get("payment_status") == "paid" else 0
    fee = round(paid * policy["biaya_persen"] / 100)
    refund_estimate = paid - fee

    now = now_iso()
    await db.bookings.update_one({"id": b["id"]}, {"$set": {
        "cancel_request_status": "requested",
        "cancel_requested_at": now, "cancel_requested_reason": alasan or "",
        "cancel_requested_via": "ai_whatsapp",
        "cancel_policy_label": policy["label"], "cancel_fee_percent": policy["biaya_persen"],
        "cancel_fee": fee, "refund_amount": refund_estimate,
    }})

    from routes.push import send_push
    from routes.telegram_bot import kirim_alert_owner
    ringkas = f"{b['nama_tamu']} — {b['kode']} — {policy['label']}"
    await send_push("Permintaan Pembatalan Baru", ringkas, url="/pembatalan")
    await kirim_alert_owner(
        f"\U0001F6D1 Permintaan Pembatalan Baru ({b['kode']})\n\n"
        f"Nama: {b['nama_tamu']}\nHP: {b['no_hp']}\nKamar: {b.get('room_nomor', '-')}\n"
        f"Kebijakan: {policy['label']}\n"
        f"Estimasi refund: Rp{refund_estimate:,}".replace(",", ".")
    )

    return {
        "ok": True, "kode": b["kode"], "policy_label": policy["label"],
        "biaya_persen": policy["biaya_persen"], "refund_estimate": refund_estimate,
    }


@api.get("/cancellation-requests")
async def list_cancellation_requests(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    """status kosong/None -> aktif (requested+pending, dipakai Dashboard/daftar utama).
    status='riwayat' -> semua yang pernah punya permintaan pembatalan (termasuk refund_sent)."""
    q = {"cancel_request_status": {"$ne": None}} if status == "riwayat" else {"cancel_request_status": {"$in": CANCEL_STATUS_AKTIF}}
    items = await db.bookings.find(q, {"_id": 0}).sort("cancel_requested_at", -1).to_list(200)
    return items


@api.post("/cancellation-requests/{booking_id}/approve")
async def approve_cancellation_request(booking_id: str, user: dict = Depends(get_current_user)):
    """Setujui: eksekusi pembatalan sungguhan (booking.status -> cancelled), kebijakan
    dihitung ULANG di saat approval (bukan dipakai angka saat request) supaya staf ambil
    keputusan dari sisa waktu paling akurat — sama pola dengan pembatalan mandiri
    (public.py). Status jadi 'pending' (menunggu staf transfer refund manual)."""
    b = await db.bookings.find_one({"id": booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("cancel_request_status") != "requested":
        raise HTTPException(400, f"Hanya permintaan berstatus 'requested' yang bisa disetujui (status saat ini: {b.get('cancel_request_status')})")

    policy = hitung_kebijakan_pembatalan(b["jam_mulai"])
    paid = int(b.get("amount_due") or 0) if b.get("payment_status") == "paid" else 0
    fee = round(paid * policy["biaya_persen"] / 100)
    refund = paid - fee

    now = now_iso()
    update_fields = {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": user["nama"],
        "cancel_reason": b.get("cancel_requested_reason") or "Dibatalkan via AI WhatsApp",
        "cancel_request_status": "pending",
        "cancel_policy_label": policy["label"], "cancel_fee_percent": policy["biaya_persen"],
        "cancel_fee": fee, "refund_amount": refund,
        "cancel_approved_at": now, "cancel_approved_by": user["nama"],
    }
    if b.get("payment_status") == "paid":
        update_fields["payment_status"] = "refunded" if refund > 0 else "forfeited"
    await db.bookings.update_one({"id": booking_id}, {"$set": update_fields})
    await log_availability_change(b["room_id"], b.get("room_tipe", ""), 1, "booking_dibatalkan_ai", booking_id=b["id"])
    await log_activity(
        user, "approve_cancellation_request",
        f"Setujui pembatalan {b['kode']} ({b['nama_tamu']}) — refund Rp{refund:,}".replace(",", "."),
        entity=b.get("room_nomor", ""),
    )

    # Notifikasi WA begitu staf APPROVE (2026-07-21, keputusan user: konfirmasi "sudah
    # dibatalkan" ke tamu HANYA boleh terjadi di titik ini, bukan pas AI baru mengajukan -
    # sebelumnya TIDAK ADA notifikasi sama sekali di titik approve, cuma ada saat reject &
    # refund-sent - AI jadi cenderung menyampaikan sendiri "berhasil dibatalkan" ke tamu
    # padahal baru pengajuan, kadang bahkan mengarang tanpa tool benar2 dipanggil).
    pesan = (
        f"Halo {b['nama_tamu']}, pembatalan booking {b['kode']} sudah kami *setujui dan proses*. "
        f"{policy['label']}. Refund yang akan Anda terima: Rp{refund:,}".replace(",", ".") + ". "
        "Dana refund akan ditransfer manual oleh staf kami, mohon ditunggu."
    )
    try:
        from routes.pesan_whatsapp import _kirim_via_provider
        await _kirim_via_provider(b["no_hp"], pesan)
    except Exception as e:
        logging.getLogger("pembatalan").warning(f"Gagal kirim notif approve ke {b['no_hp']}: {e}")

    return await db.bookings.find_one({"id": booking_id}, {"_id": 0})


@api.post("/cancellation-requests/{booking_id}/reject")
async def reject_cancellation_request(booking_id: str, body: CancelWithFeeBody = CancelWithFeeBody(), user: dict = Depends(get_current_user)):
    b = await db.bookings.find_one({"id": booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("cancel_request_status") != "requested":
        raise HTTPException(400, f"Hanya permintaan berstatus 'requested' yang bisa ditolak (status saat ini: {b.get('cancel_request_status')})")

    await db.bookings.update_one({"id": booking_id}, {"$set": {
        "cancel_request_status": None, "cancel_rejected_at": now_iso(), "cancel_rejected_by": user["nama"],
        "cancel_rejected_reason": body.alasan or "",
    }})
    await log_activity(user, "reject_cancellation_request", f"Tolak pembatalan {b['kode']} ({b['nama_tamu']})", entity=b.get("room_nomor", ""))

    pesan = f"Halo {b['nama_tamu']}, permintaan pembatalan booking {b['kode']} belum bisa kami proses. Silakan hubungi kami untuk info lebih lanjut."
    try:
        from routes.pesan_whatsapp import _kirim_via_provider
        await _kirim_via_provider(b["no_hp"], pesan)
    except Exception as e:
        logging.getLogger("pembatalan").warning(f"Gagal kirim notif tolak ke {b['no_hp']}: {e}")
    return {"ok": True}


@api.post("/cancellation-requests/{booking_id}/refund-sent")
async def mark_refund_sent(booking_id: str, user: dict = Depends(get_current_user)):
    """Tombol "Sudah Dikirim" — refund uangnya tetap ditransfer manual staf DI LUAR sistem
    (belum ada integrasi payout otomatis), tombol ini cuma menandai selesai + otomatis
    kirim WA konfirmasi ke tamu. Begitu ditandai, item ini otomatis tidak lagi muncul di
    daftar aktif/Dashboard (lihat CANCEL_STATUS_AKTIF), tapi tetap ada di riwayat."""
    b = await db.bookings.find_one({"id": booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("cancel_request_status") != "pending":
        raise HTTPException(400, f"Hanya yang berstatus 'pending' (sudah disetujui) yang bisa ditandai refund terkirim (status saat ini: {b.get('cancel_request_status')})")

    now = now_iso()
    await db.bookings.update_one({"id": booking_id}, {"$set": {
        "cancel_request_status": "refund_sent", "refund_sent_at": now, "refund_sent_by": user["nama"],
    }})
    refund_amount = int(b.get("refund_amount") or 0)
    await log_activity(
        user, "refund_sent",
        f"Tandai refund terkirim {b['kode']} ({b['nama_tamu']}) — Rp{refund_amount:,}".replace(",", "."),
        entity=b.get("room_nomor", ""),
    )

    if refund_amount > 0:
        pesan = (
            f"Halo {b['nama_tamu']}, refund pembatalan booking {b['kode']} sebesar "
            f"Rp{refund_amount:,}".replace(",", ".") + " sudah berhasil kami kirimkan. Terima kasih."
        )
    else:
        pesan = f"Halo {b['nama_tamu']}, booking {b['kode']} sudah kami batalkan sesuai permintaan. Terima kasih."
    try:
        from routes.pesan_whatsapp import _kirim_via_provider
        await _kirim_via_provider(b["no_hp"], pesan)
    except Exception as e:
        logging.getLogger("pembatalan").warning(f"Gagal kirim konfirmasi refund ke {b['no_hp']}: {e}")
    return {"ok": True}
