from core import *
from email_service import generate_voucher_pdf, send_voucher_email
import hmac
import httpx

# Tripay pakai vocab status sendiri (uppercase); payment_log.transaction_status
# dinormalisasi ke gaya Midtrans (lowercase) supaya satu field bisa dipakai lintas
# gateway — lihat tripay_callback().
TRIPAY_STATUS_MAP = {
    "PAID": "settlement", "UNPAID": "pending", "EXPIRED": "expire",
    "FAILED": "deny", "REFUND": "refund",
}

@api.get("/payments/tripay/channels")
async def tripay_channels():
    """Daftar metode pembayaran aktif dari Tripay (VA/e-wallet/QRIS/retail dst) — dipakai
    halaman booking publik sebagai pengganti pilihan metode di popup Snap Midtrans (Tripay
    tidak punya widget serupa, tamu pilih metode dulu baru transaksi dibuat khusus metode itu).
    No-auth (dipakai PublicBook.jsx sebelum tamu login)."""
    if not TRIPAY_API_KEY:
        raise HTTPException(503, "Tripay belum dikonfigurasi")
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            r = await http.get(
                f"{TRIPAY_BASE_URL}/merchant/payment-channel",
                headers={"Authorization": f"Bearer {TRIPAY_API_KEY}"},
            )
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Gagal menghubungi Tripay: {e}")
    resp = r.json()
    if r.status_code != 200 or not resp.get("success", True):
        raise HTTPException(502, f"Tripay error: {resp.get('message', r.text)}")
    return [c for c in resp.get("data", []) if c.get("active")]

@api.post("/payments/tripay/create-transaction")
async def tripay_create_transaction(body: TripayCreateTransactionBody):
    """Buat transaksi closed-payment Tripay untuk booking publik. No-auth (tamu publik).
    Pengganti /payments/midtrans/create-snap-token — beda dari Snap, Tripay butuh `method`
    (channel spesifik) di-set duluan, hasilnya `checkout_url` (halaman instruksi bayar
    ter-hosted Tripay) untuk di-redirect, bukan token untuk popup JS.
    """
    if not (TRIPAY_MERCHANT_CODE and TRIPAY_API_KEY and TRIPAY_PRIVATE_KEY):
        raise HTTPException(503, "Tripay belum dikonfigurasi")
    b = await db.bookings.find_one({"id": body.booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("booking_pending",):
        raise HTTPException(400, f"Booking tidak dapat dibayar (status: {b.get('status')})")
    total = int(b.get("total", 0))
    if body.payment_option == "dp50":
        amount = int(b.get("dp_min") or round(total * 0.5))
    elif body.payment_option == "full":
        amount = total
    else:
        raise HTTPException(400, "payment_option harus 'dp50' atau 'full'")

    merchant_ref = f"{b['kode']}-{datetime.now().strftime('%H%M%S')}{uuid.uuid4().hex[:3].upper()}"
    signature = hmac.new(
        TRIPAY_PRIVATE_KEY.encode(),
        f"{TRIPAY_MERCHANT_CODE}{merchant_ref}{amount}".encode(),
        hashlib.sha256,
    ).hexdigest()
    payload = {
        "method": body.method,
        "merchant_ref": merchant_ref,
        "amount": amount,
        "customer_name": b.get("nama_tamu") or "Tamu",
        "customer_email": b.get("email") or "tamu@pelangihomestay.com",
        "customer_phone": b.get("no_hp") or "",
        "order_items": [{
            "sku": b["room_id"], "name": f"Kamar {b['room_nomor']} ({b['room_tipe']}) - {b['kode']}",
            "price": amount, "quantity": 1,
        }],
        "return_url": f"{os.environ.get('FRONTEND_URL', '')}/book/sukses/{b['id']}",
        "expired_time": int(datetime.now(timezone.utc).timestamp()) + 24 * 3600,
        "signature": signature,
    }
    async with httpx.AsyncClient(timeout=15) as http:
        try:
            r = await http.post(
                f"{TRIPAY_BASE_URL}/transaction/create", json=payload,
                headers={"Authorization": f"Bearer {TRIPAY_API_KEY}"},
            )
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Gagal menghubungi Tripay: {e}")
    resp = r.json()
    if r.status_code != 200 or not resp.get("success"):
        raise HTTPException(502, f"Tripay error: {resp.get('message', r.text)}")
    trx = resp["data"]

    await db.bookings.update_one({"id": b["id"]}, {"$set": {
        "invoice_id": merchant_ref, "payment_option": body.payment_option,
        "amount_due": amount, "amount_paid_min": amount,
        "updated_at": now_iso(),
    }})
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "booking_id": b["id"], "booking_kode": b["kode"],
        "order_id": merchant_ref, "gateway": "tripay",
        "reference": trx.get("reference"), "checkout_url": trx.get("checkout_url"),
        "gross_amount": str(amount), "payment_option": body.payment_option,
        "transaction_status": "pending", "status_code": None,
        "payment_type": body.method, "fraud_status": None,
        "created_at": now_iso(), "updated_at": now_iso(),
        "tripay_response": trx,
    })
    return {
        "booking_id": b["id"], "order_id": merchant_ref,
        "reference": trx.get("reference"), "checkout_url": trx.get("checkout_url"),
        "qr_url": trx.get("qr_url"), "pay_code": trx.get("pay_code"),
        "amount": amount, "expired_time": trx.get("expired_time"),
        "instructions": trx.get("instructions"),
    }

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
    status_raw = payload.get("status")  # PAID | EXPIRED | FAILED | REFUND | UNPAID
    # payment_log.transaction_status dipakai bersama Midtrans, jadi dinormalisasi ke
    # vocab Midtrans (lowercase) di sini — biar tabel Pembayaran & VALID_PAYMENT_STATUSES
    # cuma perlu paham satu vocab, bukan dua asal gateway berbeda.
    status = TRIPAY_STATUS_MAP.get(status_raw, (status_raw or "").lower())
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
        # payment_log seharusnya sudah ada dari create-transaction — kalau tidak ketemu,
        # tebak booking dari pola order_id supaya booking tetap ter-update & voucher tetap
        # terkirim, bukan diam-diam jadi entri yatim (lihat guess_booking_kode_from_order_id).
        kode_guess = guess_booking_kode_from_order_id(merchant_ref)
        b_guess = await db.bookings.find_one({"kode": kode_guess}) if kode_guess else None
        booking_id = b_guess["id"] if b_guess else None
        if not b_guess:
            logging.getLogger("tripay").warning(
                "Callback Tripay untuk order_id %s tidak ketemu payment_log maupun booking tebakan (%s)",
                merchant_ref, kode_guess,
            )
        new_log = {"id": str(uuid.uuid4()), "order_id": merchant_ref, "booking_id": booking_id,
                   "booking_kode": b_guess["kode"] if b_guess else None,
                   "created_at": now_iso(), **log_fields}
        await db.payment_log.insert_one(new_log)

    if booking_id:
        b = await db.bookings.find_one({"id": booking_id})
        if b:
            new_status = b.get("status")
            new_payment = b.get("payment_status", "pending")
            now = now_iso()
            if status == "settlement":
                new_status, new_payment = "booking_paid", "paid"
            elif status == "pending":
                new_payment = "pending"
            elif status in ("expire", "deny"):
                new_status = "cancelled"
                new_payment = "expired" if status == "expire" else "failed"
            elif status == "refund":
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
