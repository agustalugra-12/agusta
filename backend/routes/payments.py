from core import *
from email_service import generate_voucher_pdf, send_voucher_email

@api.get("/payments/midtrans/config")
async def get_midtrans_config():
    """Endpoint public untuk ambil client key (dipakai Snap.js di frontend)."""
    return {
        "client_key": MIDTRANS_CLIENT_KEY,
        "is_production": MIDTRANS_IS_PRODUCTION,
        "snap_url": (
            "https://app.midtrans.com/snap/snap.js" if MIDTRANS_IS_PRODUCTION
            else "https://app.sandbox.midtrans.com/snap/snap.js"
        ),
    }

@api.post("/payments/midtrans/create-snap-token")
async def create_snap_token(body: CreateSnapTokenBody):
    """Buat Snap transaction token untuk booking publik. No-auth (tamu publik).
    payment_option: dp50 = bayar 50%, full = bayar penuh.
    """
    b = await db.bookings.find_one({"id": body.booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("booking_pending",):
        raise HTTPException(400, f"Booking tidak dapat dibayar (status: {b.get('status')})")
    total = int(b.get("total", 0))
    if body.payment_option == "dp50":
        gross_amount = int(b.get("dp_min") or round(total * 0.5))
    elif body.payment_option == "full":
        gross_amount = total
    else:
        raise HTTPException(400, "payment_option harus 'dp50' atau 'full'")
    # order_id unik per attempt
    order_id = f"{b['kode']}-{datetime.now().strftime('%H%M%S')}{uuid.uuid4().hex[:3].upper()}"
    parameter = {
        "transaction_details": {"order_id": order_id, "gross_amount": gross_amount},
        "enabled_payments": ["qris", "bank_transfer", "echannel", "permata_va",
                              "bca_va", "bni_va", "bri_va", "cimb_va", "mandiri_va"],
        "customer_details": {
            "first_name": b.get("nama_tamu", ""),
            "phone": b.get("no_hp", ""),
            "email": b.get("email", ""),
        },
        "item_details": [{
            "id": b["room_id"], "name": f"Kamar {b['room_nomor']} ({b['room_tipe']})",
            "price": gross_amount, "quantity": 1,
        }],
        "callbacks": {"finish": f"{os.environ.get('FRONTEND_URL', '')}/book/sukses/{b['id']}"},
    }
    try:
        trx = snap_client.create_transaction(parameter)
    except Exception as e:
        raise HTTPException(502, f"Midtrans error: {e}")
    # simpan ke booking + payment_log
    await db.bookings.update_one({"id": b["id"]}, {"$set": {
        "invoice_id": order_id, "payment_option": body.payment_option,
        "amount_due": gross_amount, "amount_paid_min": gross_amount,
        "updated_at": now_iso(),
    }})
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "booking_id": b["id"], "booking_kode": b["kode"],
        "order_id": order_id, "transaction_token": trx.get("token"),
        "redirect_url": trx.get("redirect_url"),
        "gross_amount": str(gross_amount), "payment_option": body.payment_option,
        "transaction_status": "initiated", "status_code": None,
        "payment_type": None, "fraud_status": None,
        "created_at": now_iso(), "updated_at": now_iso(),
        "midtrans_response": trx,
    })
    return {
        "booking_id": b["id"], "order_id": order_id,
        "transaction_token": trx.get("token"), "redirect_url": trx.get("redirect_url"),
        "client_key": MIDTRANS_CLIENT_KEY, "gross_amount": gross_amount,
        "is_production": MIDTRANS_IS_PRODUCTION,
    }

def _verify_midtrans_signature(order_id: str, status_code: str, gross_amount: str, signature_key: str) -> bool:
    raw = f"{order_id}{status_code}{gross_amount}{MIDTRANS_SERVER_KEY}".encode("utf-8")
    return hashlib.sha512(raw).hexdigest() == signature_key

@api.post("/payments/midtrans/notification")
async def midtrans_notification(request: Request):
    """Webhook Midtrans. URL ini harus di-set di Dashboard Midtrans
    (Settings → Configuration → Payment Notification URL).
    """
    payload = await request.json()
    order_id = payload.get("order_id")
    status_code = payload.get("status_code")
    gross_amount = payload.get("gross_amount")
    signature_key = payload.get("signature_key", "")
    transaction_status = payload.get("transaction_status")
    payment_type = payload.get("payment_type")
    fraud_status = payload.get("fraud_status")
    if not all([order_id, status_code, gross_amount, signature_key]):
        raise HTTPException(400, "Payload Midtrans tidak lengkap")
    if not _verify_midtrans_signature(order_id, status_code, gross_amount, signature_key):
        raise HTTPException(403, "Signature Midtrans tidak valid")
    # update payment_log (idempotent by order_id)
    log = await db.payment_log.find_one({"order_id": order_id})
    log_fields = {
        "transaction_status": transaction_status, "status_code": status_code,
        "gross_amount": gross_amount, "payment_type": payment_type,
        "fraud_status": fraud_status, "notification_payload": payload,
        "updated_at": now_iso(),
    }
    if log:
        await db.payment_log.update_one({"_id": log["_id"]}, {"$set": log_fields})
        booking_id = log.get("booking_id")
    else:
        # fallback insert (jarang terjadi)
        new_log = {"id": str(uuid.uuid4()), "order_id": order_id,
                   "created_at": now_iso(), **log_fields}
        await db.payment_log.insert_one(new_log)
        booking_id = None
    # update booking
    if booking_id:
        b = await db.bookings.find_one({"id": booking_id})
        if b:
            new_status = b.get("status")
            new_payment = b.get("payment_status", "pending")
            now = now_iso()
            if transaction_status in ("settlement", "capture"):
                if transaction_status == "capture" and fraud_status == "challenge":
                    new_payment = "challenge"
                else:
                    new_status = "booking_paid"
                    new_payment = "paid"
            elif transaction_status == "pending":
                new_payment = "pending"
            elif transaction_status in ("expire", "cancel", "deny"):
                new_status = "cancelled"
                new_payment = "expired" if transaction_status == "expire" else "failed"
            elif transaction_status == "refund":
                new_payment = "refunded"
            await db.bookings.update_one({"id": booking_id}, {"$set": {
                "status": new_status, "payment_status": new_payment,
                "paid_at": now if new_payment == "paid" else b.get("paid_at"),
                "payment_type": payment_type,
                "updated_at": now,
            }})
            # log activity
            await db.audit_log.insert_one({
                "id": str(uuid.uuid4()), "user_id": None, "username": "midtrans-webhook",
                "action": f"payment_{transaction_status}",
                "detail": f"Booking {b['kode']} - {transaction_status} ({payment_type or 'n/a'}) Rp{gross_amount}",
                "entity": b.get("room_nomor", ""), "timestamp": now,
            })
            # kirim voucher otomatis begitu pembayaran sukses (sekali saja, bukan tiap retry webhook)
            if new_payment == "paid" and b.get("payment_status") != "paid":
                try:
                    b_paid = {**b, "status": new_status, "payment_status": new_payment}
                    pdf_bytes = generate_voucher_pdf(b_paid)
                    await send_voucher_email(b_paid, pdf_bytes)
                except Exception as e:
                    logging.getLogger("payments").warning(
                        f"Gagal kirim voucher otomatis booking {b['kode']}: {e}"
                    )
    return {"ok": True}

@api.get("/payments/midtrans/status/{order_id}")
async def get_payment_status(order_id: str):
    """Polling status pembayaran untuk frontend (setelah Snap close)."""
    log = await db.payment_log.find_one({"order_id": order_id}, {"_id": 0, "midtrans_response": 0, "notification_payload": 0})
    if not log:
        raise HTTPException(404, "Payment log tidak ditemukan")
    return log

@api.get("/public/bank-accounts")
async def public_bank_accounts():
    """Daftar rekening bank untuk transfer manual (tampil di halaman publik /book)."""
    accounts = [
        {"bank": "BRI", "nomor": os.environ.get("BANK_BRI_NUMBER", "464001008162533"),
         "atas_nama": os.environ.get("BANK_BRI_NAME", "Pelangi Homestay")},
    ]
    return {"accounts": accounts, "instruksi": "Transfer sesuai nominal yang tertera, kemudian klik tombol 'Saya Sudah Transfer' untuk verifikasi oleh resepsionis."}
