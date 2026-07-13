from core import *
from email_service import generate_voucher_pdf, send_voucher_email
import hmac

@api.get("/payments/tripay/config")
async def get_tripay_config(user: dict = Depends(get_current_user)):
    """Status konfigurasi Tripay untuk staf (halaman Pembayaran) — belum ada UI kredensial
    tersendiri (beda dari Konfigurasi Webhook WA) karena kredensial di-set lewat env var
    server, bukan lewat form, sesuai kredensial Merchant Tripay yang sensitif."""
    return {
        "configured": bool(TRIPAY_MERCHANT_CODE and TRIPAY_API_KEY and TRIPAY_PRIVATE_KEY),
        "is_production": TRIPAY_IS_PRODUCTION,
        "merchant_code": TRIPAY_MERCHANT_CODE or None,
        "callback_url": f"{os.environ.get('BACKEND_URL', 'https://api.pelangihomestay.com')}/api/payments/tripay/callback",
    }

@api.post("/payments/tripay/callback")
async def tripay_callback(request: Request):
    """Callback URL Tripay — daftarkan di Merchant Panel Tripay (Pengaturan → Kode
    Merchant → Callback URL). Tripay memanggil URL ini tiap ada perubahan status
    transaksi (PAID/EXPIRED/FAILED/REFUND/UNPAID).

    Signature (header X-Callback-Signature) = HMAC-SHA256(raw_body, TRIPAY_PRIVATE_KEY).
    Selama TRIPAY_PRIVATE_KEY belum di-set (masih tahap pendaftaran URL di sandbox),
    verifikasi signature dilewati dan payload TIDAK diproses ke booking — cuma dibalas
    sukses supaya proses pendaftaran/verifikasi URL di Tripay tidak gagal. Begitu
    kredensial asli di-set, verifikasi otomatis aktif dan payload baru diproses.
    """
    raw_body = await request.body()
    signature_header = request.headers.get("X-Callback-Signature", "")
    event = request.headers.get("X-Callback-Event", "")

    if not TRIPAY_PRIVATE_KEY:
        logging.getLogger("tripay").info("Callback Tripay diterima tapi TRIPAY_PRIVATE_KEY belum diset — payload diabaikan")
        return {"success": True}

    expected = hmac.new(TRIPAY_PRIVATE_KEY.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(403, "Signature Tripay tidak valid")

    if event and event != "payment_status":
        return {"success": True}

    payload = await request.json()
    merchant_ref = payload.get("merchant_ref")
    reference = payload.get("reference")
    status = payload.get("status")  # PAID | EXPIRED | FAILED | REFUND | UNPAID
    total_amount = payload.get("total_amount")
    payment_method = payload.get("payment_method")
    if not merchant_ref:
        raise HTTPException(400, "Payload Tripay tidak lengkap (merchant_ref kosong)")

    # update payment_log (idempotent by order_id, dipakai bersama Midtrans — field
    # `gateway` membedakan asalnya)
    log = await db.payment_log.find_one({"order_id": merchant_ref})
    log_fields = {
        "transaction_status": status, "gateway": "tripay", "reference": reference,
        "gross_amount": str(total_amount) if total_amount is not None else None,
        "payment_type": payment_method, "notification_payload": payload,
        "updated_at": now_iso(),
    }
    if log:
        await db.payment_log.update_one({"_id": log["_id"]}, {"$set": log_fields})
        booking_id = log.get("booking_id")
    else:
        new_log = {"id": str(uuid.uuid4()), "order_id": merchant_ref, "booking_id": None,
                   "booking_kode": None, "created_at": now_iso(), **log_fields}
        await db.payment_log.insert_one(new_log)
        booking_id = None

    if booking_id:
        b = await db.bookings.find_one({"id": booking_id})
        if b:
            new_status = b.get("status")
            new_payment = b.get("payment_status", "pending")
            now = now_iso()
            if status == "PAID":
                new_status, new_payment = "booking_paid", "paid"
            elif status == "UNPAID":
                new_payment = "pending"
            elif status in ("EXPIRED", "FAILED"):
                new_status = "cancelled"
                new_payment = "expired" if status == "EXPIRED" else "failed"
            elif status == "REFUND":
                new_payment = "refunded"
            was_paid = b.get("payment_status") == "paid"
            await db.bookings.update_one({"id": booking_id}, {"$set": {
                "status": new_status, "payment_status": new_payment,
                "paid_at": now if new_payment == "paid" else b.get("paid_at"),
                "payment_type": payment_method,
                "updated_at": now,
            }})
            await db.audit_log.insert_one({
                "id": str(uuid.uuid4()), "user_id": None, "username": "tripay-webhook",
                "action": f"payment_{(status or 'unknown').lower()}",
                "detail": f"Booking {b['kode']} - {status} ({payment_method or 'n/a'}) Rp{total_amount}",
                "entity": b.get("room_nomor", ""), "timestamp": now,
            })
            if new_payment == "paid" and not was_paid:
                try:
                    b_paid = {**b, "status": new_status, "payment_status": new_payment}
                    pdf_bytes = generate_voucher_pdf(b_paid)
                    await send_voucher_email(b_paid, pdf_bytes)
                except Exception as e:
                    logging.getLogger("tripay").warning(
                        f"Gagal kirim voucher otomatis (Tripay) booking {b['kode']}: {e}"
                    )
    return {"success": True}
