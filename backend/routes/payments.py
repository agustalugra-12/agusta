import asyncio
from core import *
from email_service import generate_voucher_pdf, send_voucher_email, kirim_voucher_wa, get_property_branding

# Endpoint Midtrans (config/create-snap-token/notification/status) dihapus 2026-07-14 —
# gateway pembayaran tamu publik sepenuhnya pindah ke Tripay (lihat routes/tripay.py),
# Midtrans tidak dipakai lagi sama sekali (keputusan bisnis user). Data historis transaksi
# Midtrans TETAP ada di payment_log (dokumen lama tanpa field `gateway`, punya
# `transaction_token`/`redirect_url`/`midtrans_response`) — endpoint di bawah (list_payment_log
# dst) tetap membaca/menampilkannya, cuma jalur PEMBUATAN transaksi baru yang dihapus.

VALID_PAYMENT_STATUSES = {"settlement", "pending", "expire", "deny", "cancel", "refund"}

@api.put("/payments/log/{log_id}/status")
async def update_payment_status_manual(log_id: str, body: PaymentStatusUpdateBody,
                                        user: dict = Depends(require_owner),
                                        property_id: str = Depends(get_active_property)):
    """Ubah status transaksi payment_log secara manual — KHUSUS owner (keputusan bisnis:
    resepsionis hanya boleh lihat/export laporan keuangan, tidak mengubahnya).
    Beda dari webhook gateway (otomatis, signature-verified): ini aksi manual staf,
    jadi status booking terkait ikut disesuaikan dengan pemetaan yang sama dipakai webhook."""
    if body.status not in VALID_PAYMENT_STATUSES:
        raise HTTPException(400, f"Status harus salah satu dari: {', '.join(sorted(VALID_PAYMENT_STATUSES))}")
    log = await db.payment_log.find_one(scoped({"id": log_id}, property_id))
    if not log:
        raise HTTPException(404, "Transaksi tidak ditemukan")
    if log.get("transaction_status") == body.status:
        return {"ok": True, "order_id": log.get("order_id"), "transaction_status": body.status, "unchanged": True}

    now = now_iso()
    await db.payment_log.update_one({"id": log_id}, {"$set": {
        "transaction_status": body.status, "updated_at": now,
        "manual_status_by": user["nama"], "manual_status_reason": body.alasan,
    }})

    booking_id = log.get("booking_id")
    if booking_id:
        b = await db.bookings.find_one({"id": booking_id})
        if b:
            new_status = b.get("status")
            new_payment = b.get("payment_status", "pending")
            if body.status == "settlement":
                new_status, new_payment = "booking_paid", "paid"
            elif body.status == "pending":
                new_payment = "pending"
            elif body.status in ("expire", "cancel", "deny"):
                new_status = "cancelled"
                new_payment = "expired" if body.status == "expire" else "failed"
            elif body.status == "refund":
                new_payment = "refunded"
            was_paid = b.get("payment_status") == "paid"
            await db.bookings.update_one({"id": booking_id}, {"$set": {
                "status": new_status, "payment_status": new_payment,
                "paid_at": now if new_payment == "paid" else b.get("paid_at"),
                "updated_at": now,
            }})
            if new_payment == "paid" and not was_paid:
                try:
                    b_paid = {**b, "status": new_status, "payment_status": new_payment}
                    branding = await get_property_branding(b_paid.get("property_id"))
                    pdf_bytes = await asyncio.to_thread(generate_voucher_pdf, b_paid, branding)
                    await send_voucher_email(b_paid, pdf_bytes)
                    await kirim_voucher_wa(b_paid, pdf_bytes)
                except Exception as e:
                    logging.getLogger("payments").warning(
                        f"Gagal kirim voucher otomatis (ubah status manual) booking {b['kode']}: {e}"
                    )
    await log_activity(user, "update_payment_status_manual",
                       f"Ubah status transaksi {log.get('order_id')} → {body.status}" +
                       (f" ({body.alasan})" if body.alasan else ""))
    return {"ok": True, "order_id": log.get("order_id"), "transaction_status": body.status}

@api.get("/payments/log")
async def list_payment_log(search: Optional[str] = None, status: Optional[str] = None,
                            user: dict = Depends(get_current_user),
                            property_id: str = Depends(get_active_property)):
    """Daftar semua transaksi payment_log (Midtrans & Tripay, vocab transaction_status
    sudah dinormalisasi ke gaya Midtrans lowercase) untuk tabel utama halaman Pembayaran.
    nama_tamu di-join dari booking terkait karena payment_log sendiri tidak menyimpannya."""
    pipeline: List[Dict[str, Any]] = [{"$match": scoped({}, property_id)}]
    if status:
        pipeline.append({"$match": {"transaction_status": status}})
    pipeline += [
        {"$sort": {"created_at": -1}},
        {"$limit": 500},
        {"$lookup": {"from": "bookings", "localField": "booking_kode",
                      "foreignField": "kode", "as": "_booking"}},
        {"$addFields": {"nama_tamu": {"$arrayElemAt": ["$_booking.nama_tamu", 0]}}},
        {"$project": {"_id": 0, "midtrans_response": 0, "notification_payload": 0,
                       "tripay_response": 0, "_booking": 0}},
    ]
    items = await db.payment_log.aggregate(pipeline).to_list(500)
    if search:
        q = search.lower()
        items = [i for i in items if q in (i.get("booking_kode") or "").lower()
                 or q in (i.get("nama_tamu") or "").lower()
                 or q in (i.get("order_id") or "").lower()]
    return items

@api.post("/bookings/{booking_id}/ganti-metode-pembayaran")
async def ganti_metode_pembayaran(booking_id: str, body: GantiMetodeBayarBody, user: dict = Depends(get_current_user),
                                   property_id: str = Depends(get_active_property)):
    """Ganti metode bayar (mis. VA BRI -> QRIS, atau VA bank A -> VA bank B) untuk booking
    yang LINK-nya masih aktif/belum kadaluarsa (2026-08-11, permintaan Agus - kejadian nyata
    tamu Nyoman Satria Wiguna: sudah dibuatkan link VA BRIVA, ternyata rekeningnya BCA jadi
    tidak bisa transfer ke VA itu, minta ganti QRIS. Sebelumnya harus ditangani manual lewat
    dialog "Buat Tagihan Baru" tanpa kirim link otomatis ke tamu - staf harus copy-paste
    sendiri ke WA). Beda dari resend-link (routes/booking_requests.py, KHUSUS link yang
    sudah kadaluarsa & booking lama otomatis cancelled) - ini untuk booking yang MASIH aktif,
    jadi booking & kamar TIDAK disentuh sama sekali, cuma dibuatkan transaksi Tripay BARU
    untuk booking yang SAMA (reuse tripay_create_transaction, endpoint yang sama dipakai
    dialog "Buat Tagihan Baru" & staf 'ganti DP jadi lunas' - webhook Tripay callback sudah
    ada guard supaya transaksi lama yang ditinggalkan expired belakangan TIDAK menimpa balik
    booking yang sudah lunas dibayar via transaksi baru, lihat tripay.py tripay_callback())."""
    from routes.booking_requests import TRIPAY_METODE_VALID
    if body.method not in TRIPAY_METODE_VALID:
        raise HTTPException(400, f"Metode harus salah satu dari: {', '.join(sorted(TRIPAY_METODE_VALID))}")
    if body.payment_option not in ("dp50", "full"):
        raise HTTPException(400, "payment_option harus 'dp50' atau 'full'")
    b = await db.bookings.find_one(scoped({"id": booking_id}, property_id))
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")

    from routes.tripay import tripay_create_transaction
    trx = await tripay_create_transaction(TripayCreateTransactionBody(
        booking_id=booking_id, payment_option=body.payment_option, method=body.method,
    ))

    # Sinkron ke booking_request terkait kalau ada (Booking Request dari AI WhatsApp) supaya
    # histori link-nya kelihatan rapi di halaman /booking-requests, sama pola dgn riwayat_link
    # di resend_payment_link.
    now = now_iso()
    req = await db.booking_requests.find_one(scoped({"booking_ids": booking_id}, property_id))
    if req:
        update_ops: Dict[str, Any] = {"$set": {
            "checkout_url": trx.get("checkout_url"), "metode_pembayaran_diminta": body.method, "updated_at": now,
        }}
        if req.get("checkout_url"):
            update_ops["$push"] = {"riwayat_link": {
                "booking_ids": req.get("booking_ids") or [], "checkout_url": req.get("checkout_url"),
                "total": req.get("total"), "diganti_at": now, "diganti_oleh": user["nama"],
            }}
        await db.booking_requests.update_one({"id": req["id"]}, update_ops)

    pesan = (
        f"Halo {b.get('nama_tamu','')}, berikut link pembayaran *baru* sesuai permintaan Anda:\n\n"
        f"{trx.get('checkout_url')}"
    )
    from routes.pesan_whatsapp import _kirim_dengan_alert
    wa_terkirim = await _kirim_dengan_alert(
        b.get("no_hp", ""), pesan, konteks=f"ganti_metode_pembayaran {booking_id}", property_id=property_id,
    )

    await log_activity(user, "ganti_metode_pembayaran",
                       f"Ganti metode bayar booking {b['kode']} ({b.get('nama_tamu','')}) -> {body.method}")
    return {**trx, "wa_terkirim": wa_terkirim}

@api.get("/payments/log/by-booking/{booking_kode}")
async def get_payment_log_by_booking(booking_kode: str, user: dict = Depends(get_current_user),
                                      property_id: str = Depends(get_active_property)):
    """Riwayat semua percobaan pembayaran (payment_log) untuk satu reservasi — dipakai
    panel 'Riwayat Pembayaran' di halaman Pembayaran (mis. DP dulu baru pelunasan, atau
    sempat expired lalu dibuatkan tagihan baru)."""
    logs = await db.payment_log.find(
        scoped({"booking_kode": booking_kode}, property_id),
        {"_id": 0, "midtrans_response": 0, "notification_payload": 0},
    ).sort("created_at", 1).to_list(200)
    return logs

@api.get("/payments/bookings-status")
async def list_bookings_status_bayar(status_bayar: Optional[str] = None, search: Optional[str] = None,
                                      user: dict = Depends(get_current_user),
                                      property_id: str = Depends(get_active_property)):
    """Daftar reservasi dengan status bayar terderivasi (Belum Bayar/DP/Lunas/Direfund) —
    dipakai fitur 'Status Bayar' halaman Pembayaran. `status_bayar` filter:
    belum_bayar|dp|lunas|direfund.
    """
    if status_bayar and status_bayar not in ("belum_bayar", "dp", "lunas", "direfund"):
        raise HTTPException(400, "status_bayar harus belum_bayar, dp, lunas, atau direfund")
    q: Dict[str, Any] = scoped({}, property_id)
    if search:
        # re.escape() (2026-07-27, audit keamanan) - cegah ReDoS dari pola regex jahat, cari
        # sbg teks harfiah.
        search_escaped = re.escape(search)
        q["$or"] = [
            {"nama_tamu": {"$regex": search_escaped, "$options": "i"}},
            {"kode": {"$regex": search_escaped, "$options": "i"}},
        ]
    fields = {"_id": 0, "id": 1, "kode": 1, "nama_tamu": 1, "room_nomor": 1, "room_tipe": 1,
              "tipe": 1, "status": 1, "payment_status": 1, "payment_option": 1, "total": 1,
              "amount_due": 1, "dp_min": 1, "created_at": 1, "paid_at": 1}
    items = await db.bookings.find(q, fields).sort("created_at", -1).to_list(1000)
    for b in items:
        b.update(status_bayar_booking(b))
    if status_bayar:
        items = [b for b in items if b["status_bayar"] == status_bayar]
    return items
