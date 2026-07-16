from core import *
from email_service import generate_voucher_pdf, send_voucher_email

# Endpoint Midtrans (config/create-snap-token/notification/status) dihapus 2026-07-14 —
# gateway pembayaran tamu publik sepenuhnya pindah ke Tripay (lihat routes/tripay.py),
# Midtrans tidak dipakai lagi sama sekali (keputusan bisnis user). Data historis transaksi
# Midtrans TETAP ada di payment_log (dokumen lama tanpa field `gateway`, punya
# `transaction_token`/`redirect_url`/`midtrans_response`) — endpoint di bawah (list_payment_log
# dst) tetap membaca/menampilkannya, cuma jalur PEMBUATAN transaksi baru yang dihapus.

VALID_PAYMENT_STATUSES = {"settlement", "pending", "expire", "deny", "cancel", "refund"}

@api.put("/payments/log/{log_id}/status")
async def update_payment_status_manual(log_id: str, body: PaymentStatusUpdateBody,
                                        user: dict = Depends(require_owner)):
    """Ubah status transaksi payment_log secara manual — KHUSUS owner (keputusan bisnis:
    resepsionis hanya boleh lihat/export laporan keuangan, tidak mengubahnya).
    Beda dari webhook gateway (otomatis, signature-verified): ini aksi manual staf,
    jadi status booking terkait ikut disesuaikan dengan pemetaan yang sama dipakai webhook."""
    if body.status not in VALID_PAYMENT_STATUSES:
        raise HTTPException(400, f"Status harus salah satu dari: {', '.join(sorted(VALID_PAYMENT_STATUSES))}")
    log = await db.payment_log.find_one({"id": log_id})
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
                    pdf_bytes = generate_voucher_pdf(b_paid)
                    await send_voucher_email(b_paid, pdf_bytes)
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
                            user: dict = Depends(get_current_user)):
    """Daftar semua transaksi payment_log (Midtrans & Tripay, vocab transaction_status
    sudah dinormalisasi ke gaya Midtrans lowercase) untuk tabel utama halaman Pembayaran.
    nama_tamu di-join dari booking terkait karena payment_log sendiri tidak menyimpannya."""
    pipeline: List[Dict[str, Any]] = []
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

@api.get("/payments/log/by-booking/{booking_kode}")
async def get_payment_log_by_booking(booking_kode: str, user: dict = Depends(get_current_user)):
    """Riwayat semua percobaan pembayaran (payment_log) untuk satu reservasi — dipakai
    panel 'Riwayat Pembayaran' di halaman Pembayaran (mis. DP dulu baru pelunasan, atau
    sempat expired lalu dibuatkan tagihan baru)."""
    logs = await db.payment_log.find(
        {"booking_kode": booking_kode},
        {"_id": 0, "midtrans_response": 0, "notification_payload": 0},
    ).sort("created_at", 1).to_list(200)
    return logs

@api.get("/payments/bookings-status")
async def list_bookings_status_bayar(status_bayar: Optional[str] = None, search: Optional[str] = None,
                                      user: dict = Depends(get_current_user)):
    """Daftar reservasi dengan status bayar terderivasi (Belum Bayar/DP/Lunas) — dipakai
    fitur 'Status Bayar' halaman Pembayaran. `status_bayar` filter: belum_bayar|dp|lunas.
    """
    if status_bayar and status_bayar not in ("belum_bayar", "dp", "lunas"):
        raise HTTPException(400, "status_bayar harus belum_bayar, dp, atau lunas")
    q: Dict[str, Any] = {}
    if search:
        q["$or"] = [
            {"nama_tamu": {"$regex": search, "$options": "i"}},
            {"kode": {"$regex": search, "$options": "i"}},
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

@api.get("/public/bank-accounts")
async def public_bank_accounts():
    """Daftar rekening bank untuk transfer manual (tampil di halaman publik /book)."""
    accounts = [
        {"bank": "BRI", "nomor": os.environ.get("BANK_BRI_NUMBER", "464001008162533"),
         "atas_nama": os.environ.get("BANK_BRI_NAME", "Pelangi Homestay")},
    ]
    return {"accounts": accounts, "instruksi": "Transfer sesuai nominal yang tertera, kemudian klik tombol 'Saya Sudah Transfer' untuk verifikasi oleh resepsionis."}
