from core import *

@api.post("/bookings")
async def create_booking(body: BookingCreate, user: dict = Depends(get_current_user)):
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "Tipe booking tidak valid")
    r = await db.rooms.find_one({"id": body.room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    start = parse_iso(body.jam_mulai, "jam_mulai")
    if body.jam_selesai:
        end = parse_iso(body.jam_selesai, "jam_selesai")
    else:
        if body.tipe == "menginap":
            raise HTTPException(400, "Booking menginap wajib mengisi jam_selesai")
        end = start + timedelta(hours=6)
    if end <= start:
        raise HTTPException(400, "Jam selesai harus setelah jam mulai")
    overlap = await db.bookings.find_one({
        "room_id": body.room_id, "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": end.isoformat()},
        "jam_selesai": {"$gt": start.isoformat()},
    })
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")
    kode = f"BK-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    # Hitung estimasi tagihan (tarif kamar + 3% service fee). Untuk menginap, durasi jam dipakai sebagai kelipatan 6 jam.
    subtotal = int(r["tarif"])
    if body.tipe == "menginap":
        hours = max(6, int((end - start).total_seconds() / 3600))
        # menginap: tarif per hari (24 jam) — pakai ceil(hours/24) hari × tarif harian (tarif kamar × 4 untuk menginap)
        # Sederhanakan: tarif × ceil(hours/24)
        days = max(1, -(-hours // 24))
        subtotal = int(r["tarif"]) * days
    service_fee = round(subtotal * SERVICE_FEE_PCT)
    total = subtotal + service_fee
    doc = {
        "id": str(uuid.uuid4()), "kode": kode,
        "room_id": body.room_id, "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tipe": body.tipe, "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
        "no_identitas": body.no_identitas, "kendaraan": body.kendaraan, "jumlah_tamu": body.jumlah_tamu,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": body.catatan, "status": "aktif",
        "subtotal": subtotal, "service_fee": service_fee, "total": total,
        "source": "walk_in",
        "created_at": now_iso(), "created_by": user["nama"],
    }
    await db.bookings.insert_one(doc)
    await log_activity(user, "create_booking", f"Booking {body.tipe} kamar {r['nomor']} untuk {body.nama_tamu}", entity=r["nomor"])
    doc.pop("_id", None)
    return doc

@api.get("/bookings")
async def list_bookings(status: Optional[str] = None, tipe: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if status: q["status"] = status
    if tipe: q["tipe"] = tipe
    items = await db.bookings.find(q, {"_id": 0}).sort("jam_mulai", 1).to_list(1000)
    return items

@api.post("/bookings/{bid}/cancel-with-fee")
async def cancel_with_fee(bid: str, body: CancelWithFeeBody, user: dict = Depends(get_current_user)):
    """Cancel booking dengan biaya pembatalan 10% (online dan walk-in).
    - booking_paid: refund = paid - 10% fee. Fee diakui sebagai revenue.
    - booking_pending / aktif: no refund (belum ada uang masuk), 10% fee dicatat sebagai piutang/audit.
    Return: {refund_amount, fee, original_total, status}
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, f"Booking tidak dapat dibatalkan (status: {b.get('status')})")
    total = int(b.get("total") or 0)
    fee = round(total * 0.10) if total else 0
    paid = int(b.get("amount_due") or 0)
    refund = max(0, paid - fee) if b.get("status") == "booking_paid" else 0
    now = now_iso()
    update_fields = {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": user["nama"],
        "cancel_reason": body.alasan, "cancel_fee": fee, "refund_amount": refund,
    }
    if b.get("status") == "booking_paid":
        update_fields["payment_status"] = "refunded" if refund > 0 else "forfeited"
    await db.bookings.update_one({"id": bid}, {"$set": update_fields})
    detail = (
        f"Cancel booking {b['kode']}: total Rp{total:,}, fee Rp{fee:,}, "
        f"{'refund Rp' + format(refund, ',') if refund > 0 else 'tidak ada refund'}"
    ).replace(",", ".")
    await log_activity(user, "cancel_with_fee", detail, entity=b.get("room_nomor", ""))
    return {
        "ok": True, "refund_amount": refund, "fee": fee, "original_paid": paid,
        "original_total": total, "booking_kode": b["kode"], "previous_status": b.get("status"),
    }

@api.post("/bookings/{bid}/collect-balance")
async def collect_balance(bid: str, body: CollectBalanceBody, user: dict = Depends(get_current_user)):
    """Collect sisa pelunasan (untuk DP 50% yang belum lunas).
    Tambah amount_due dengan nominal yang diterima, catat di payment_log.
    """
    if body.nominal <= 0:
        raise HTTPException(400, "Nominal harus > 0")
    if body.metode not in ("cash", "qris"):
        raise HTTPException(400, "Metode harus cash atau qris")
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("booking_paid", "checked_in"):
        raise HTTPException(400, f"Hanya booking_paid/checked_in yang bisa di-collect (status: {b.get('status')})")
    total = int(b.get("total") or 0)
    paid_now = int(b.get("amount_due") or 0)
    sisa = max(0, total - paid_now)
    if sisa <= 0:
        raise HTTPException(400, "Booking sudah lunas, tidak ada sisa")
    if body.nominal > sisa:
        raise HTTPException(400, f"Nominal terlalu besar. Sisa: Rp{sisa:,}".replace(",", "."))
    new_paid = paid_now + body.nominal
    now = now_iso()
    await db.bookings.update_one({"id": bid}, {"$set": {
        "amount_due": new_paid, "updated_at": now,
    }})
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "booking_id": b["id"], "booking_kode": b["kode"],
        "order_id": f"COLLECT-{b['kode']}-{uuid.uuid4().hex[:4].upper()}",
        "gross_amount": str(body.nominal), "payment_option": "collect_balance",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": body.metode, "fraud_status": None,
        "created_at": now, "updated_at": now,
        "collected_by": user["nama"],
    })
    await log_activity(user, "collect_balance",
                       f"Collect sisa pelunasan booking {b['kode']}: Rp{body.nominal:,} via {body.metode} (total terbayar Rp{new_paid:,}/Rp{total:,})".replace(",", "."),
                       entity=b.get("room_nomor", ""))
    return {"ok": True, "amount_collected": body.nominal, "total_paid": new_paid, "remaining": max(0, total - new_paid), "booking_kode": b["kode"]}

@api.post("/bookings/{bid}/checkin")
async def checkin_from_booking(bid: str, user: dict = Depends(get_current_user)):
    """Check-in tamu dari booking (booking_paid → checked_in).
    Membuat record di db.checkins (status=aktif), update room → day_use, ubah booking status → checked_in.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") != "booking_paid":
        raise HTTPException(400, f"Hanya booking lunas yang bisa di-check-in (status: {b.get('status')})")
    r = await db.rooms.find_one({"id": b["room_id"]})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, f"Kamar {r['nomor']} sedang dipakai (status: {r['status']})")
    # Buat checkin doc
    trx_no = f"CI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    total = int(b.get("total") or 0)
    paid = int(b.get("amount_due") or 0)
    sisa = max(0, total - paid)
    now = now_iso()
    ci_doc = {
        "id": str(uuid.uuid4()),
        "trx_no": trx_no,
        "guest_id": None,
        "nama_tamu": b.get("nama_tamu", ""),
        "no_hp": b.get("no_hp", ""),
        "no_identitas": b.get("no_identitas", ""),
        "kendaraan": b.get("kendaraan", ""),
        "jumlah_tamu": b.get("jumlah_tamu", 1),
        "room_id": b["room_id"], "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tarif_dasar": int(r["tarif"]),
        "jam_checkin": now, "jam_checkout": None,
        "durasi_jam": 0, "overtime_jam": 0, "biaya_tambahan": 0, "total": 0,
        "status": "aktif",
        "catatan": f"Dari booking {b['kode']}. Sudah dibayar Rp{paid:,}/Rp{total:,}. Sisa Rp{sisa:,}".replace(",", "."),
        "foto_identitas_url": "",
        "pembayaran": [],
        "from_booking_id": b["id"], "from_booking_kode": b["kode"],
        "booking_paid": paid, "booking_remaining": sisa,
        "petugas_checkin": user["nama"], "petugas_checkin_id": user["id"],
        "created_at": now,
    }
    await db.checkins.insert_one(ci_doc)
    await db.rooms.update_one({"id": b["room_id"]}, {"$set": {
        "status": "day_use", "info": {"checkin_id": ci_doc["id"], "nama_tamu": b.get("nama_tamu", "")},
    }})
    await db.bookings.update_one({"id": bid}, {"$set": {
        "status": "checked_in", "checked_in_at": now, "checked_in_by": user["nama"],
        "checkin_id": ci_doc["id"],
    }})
    await log_activity(user, "checkin_from_booking",
                       f"Check-in tamu {b.get('nama_tamu','')} dari booking {b['kode']} ke kamar {r['nomor']} (sisa Rp{sisa:,})".replace(",", "."),
                       entity=r["nomor"])
    return {"ok": True, "checkin_id": ci_doc["id"], "trx_no": trx_no, "booking_kode": b["kode"], "remaining": sisa}


@api.post("/bookings/{bid}/mark-paid-manual")
async def mark_paid_manual(bid: str, body: ManualMarkPaidBody, user: dict = Depends(get_current_user)):
    """Staff verifikasi pembayaran manual (transfer rekening). Ubah booking_pending → booking_paid.
    Hanya untuk staff (auth required). Catat di audit + payment_log.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") != "booking_pending":
        raise HTTPException(400, f"Hanya booking_pending yang dapat dikonfirmasi manual (status: {b.get('status')})")
    nominal = body.nominal if body.nominal else int(b.get("total", 0))
    now = now_iso()
    await db.bookings.update_one({"id": bid}, {"$set": {
        "status": "booking_paid", "payment_status": "paid",
        "amount_due": nominal, "payment_type": body.metode,
        "paid_at": now, "manual_paid_by": user["nama"], "manual_paid_reason": body.alasan,
        "updated_at": now,
    }})
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "booking_id": b["id"], "booking_kode": b["kode"],
        "order_id": f"MANUAL-{b['kode']}", "transaction_token": None, "redirect_url": None,
        "gross_amount": str(nominal), "payment_option": "manual",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": body.metode, "fraud_status": None,
        "created_at": now, "updated_at": now,
        "manual_verified_by": user["nama"], "manual_verified_reason": body.alasan,
    })
    await log_activity(user, "manual_paid",
                       f"Konfirmasi manual booking {b['kode']} kamar {b.get('room_nomor','')}: Rp{nominal:,} via {body.metode}".replace(",", "."),
                       entity=b.get("room_nomor", ""))
    return {"ok": True, "booking_kode": b["kode"], "amount": nominal, "status": "booking_paid"}

@api.post("/bookings/{bid}/no-show")
async def mark_no_show(bid: str, body: NoShowBody, user: dict = Depends(get_current_user)):
    """Tandai booking sebagai NO-SHOW (tamu tidak datang).
    Hanya berlaku untuk booking_paid. DP/Full payment TIDAK direfund, tetap masuk pembukuan sebagai revenue.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") != "booking_paid":
        raise HTTPException(400, f"Hanya booking lunas yang dapat ditandai no-show (status: {b.get('status')})")
    paid = int(b.get("amount_due") or 0)
    now = now_iso()
    await db.bookings.update_one({"id": bid}, {"$set": {
        "status": "no_show", "payment_status": "kept",
        "no_show_at": now, "no_show_by": user["nama"], "no_show_reason": body.alasan,
    }})
    await log_activity(user, "no_show",
                       f"No-show booking {b['kode']} kamar {b.get('room_nomor','')}: Rp{paid:,} tetap masuk pembukuan".replace(",", "."),
                       entity=b.get("room_nomor", ""))
    return {"ok": True, "amount_retained": paid, "booking_kode": b["kode"]}


@api.get("/bookings/availability")
async def booking_availability(room_id: str, from_date: str, days: int = 14,
                               user: dict = Depends(get_current_user)):
    """Cek ketersediaan kamar per hari (zona lokal +07:00 / WIB)
    untuk menampilkan saran tanggal alternatif jika kamar penuh.
    Returns: { from_date, room_id, slots: [{date, available, reason}] }
    """
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    days = max(1, min(days, 60))
    try:
        base = datetime.fromisoformat(from_date)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(400, "from_date harus YYYY-MM-DD")
    # Ambil semua booking aktif untuk kamar ini dalam window from..from+days
    end_window = base + timedelta(days=days)
    bks = await db.bookings.find({
        "room_id": room_id,
        "status": {"$in": ["aktif", "booking_paid", "booking_pending"]},
        "jam_mulai": {"$lt": end_window.isoformat()},
        "jam_selesai": {"$gt": base.isoformat()},
    }, {"_id": 0}).to_list(500)
    slots = []
    for i in range(days):
        d = base + timedelta(days=i)
        d_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
        d_end = d_start + timedelta(days=1)
        conflict = None
        for b in bks:
            bs = datetime.fromisoformat(b["jam_mulai"])
            be = datetime.fromisoformat(b["jam_selesai"])
            if bs < d_end and be > d_start:
                conflict = b
                break
        slots.append({
            "date": d.strftime("%Y-%m-%d"),
            "available": conflict is None,
            "reason": f"Booking {conflict['kode']} ({conflict.get('tipe','')})" if conflict else "",
        })
    return {"room_id": room_id, "room_nomor": r["nomor"], "room_tipe": r["tipe"], "from_date": from_date, "days": days, "slots": slots}

@api.put("/bookings/{bid}")
async def update_booking(bid: str, body: BookingCreate, user: dict = Depends(get_current_user)):
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b["status"] not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, "Hanya booking aktif/pending/paid yang dapat di-reschedule")
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "Tipe booking tidak valid")
    r = await db.rooms.find_one({"id": body.room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    start = parse_iso(body.jam_mulai, "jam_mulai")
    if body.jam_selesai:
        end = parse_iso(body.jam_selesai, "jam_selesai")
    else:
        if body.tipe == "menginap":
            raise HTTPException(400, "Booking menginap wajib mengisi jam_selesai")
        end = start + timedelta(hours=6)
    if end <= start:
        raise HTTPException(400, "Jam selesai harus setelah jam mulai")
    overlap = await db.bookings.find_one({
        "id": {"$ne": bid},
        "room_id": body.room_id, "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": end.isoformat()},
        "jam_selesai": {"$gt": start.isoformat()},
    })
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")
    update_fields = {
        "room_id": body.room_id, "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tipe": body.tipe, "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
        "no_identitas": body.no_identitas, "kendaraan": body.kendaraan, "jumlah_tamu": body.jumlah_tamu,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": body.catatan, "updated_at": now_iso(), "updated_by": user["nama"],
    }
    await db.bookings.update_one({"id": bid}, {"$set": update_fields})
    await log_activity(user, "update_booking", f"Edit booking {b['kode']} kamar {r['nomor']} untuk {body.nama_tamu}", entity=r["nomor"])
    doc = await db.bookings.find_one({"id": bid}, {"_id": 0})
    return doc

@api.delete("/bookings/{bid}")
async def cancel_booking(bid: str, user: dict = Depends(get_current_user)):
    b = await db.bookings.find_one({"id": bid})
    if not b: raise HTTPException(404, "Booking tidak ditemukan")
    if b["status"] not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, "Booking sudah tidak dapat dibatalkan")
    await db.bookings.update_one({"id": bid}, {"$set": {"status": "cancelled", "cancelled_at": now_iso(), "cancelled_by": user["nama"]}})
    await log_activity(user, "cancel_booking", f"Batalkan booking {b['kode']} kamar {b['room_nomor']}")
    return {"ok": True}
