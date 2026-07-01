from core import *

@api.post("/checkins")
async def create_checkin(body: CheckinCreate, user: dict = Depends(get_current_user)):
    r = await db.rooms.find_one({"id": body.room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, "Kamar belum tersedia dan tidak dapat digunakan untuk check-in.")
    # Save / upsert guest
    guest = None
    if body.no_identitas:
        guest = await db.guests.find_one({"no_identitas": body.no_identitas})
    if not guest and body.no_hp:
        guest = await db.guests.find_one({"no_hp": body.no_hp})
    if guest:
        await db.guests.update_one({"id": guest["id"]}, {
            "$set": {
                "nama": body.nama_tamu,
                "no_hp": body.no_hp,
                "kendaraan": body.kendaraan,
                "last_visit": now_iso(),
            },
            "$inc": {"total_kunjungan": 1},
        })
        guest_id = guest["id"]
    else:
        guest_id = str(uuid.uuid4())
        await db.guests.insert_one({
            "id": guest_id,
            "nama": body.nama_tamu,
            "no_hp": body.no_hp,
            "no_identitas": body.no_identitas,
            "kendaraan": body.kendaraan,
            "total_kunjungan": 1,
            "last_visit": now_iso(),
            "created_at": now_iso(),
        })
    # parse jam_checkin
    jam_ci_iso = now_iso()
    if body.jam_checkin:
        try:
            d = datetime.fromisoformat(body.jam_checkin.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            jam_ci_iso = d.astimezone(timezone.utc).isoformat()
        except Exception:
            raise HTTPException(400, "Format jam check-in tidak valid")
    # number generator
    trx_no = f"CI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    doc = {
        "id": str(uuid.uuid4()),
        "trx_no": trx_no,
        "guest_id": guest_id,
        "nama_tamu": body.nama_tamu,
        "no_hp": body.no_hp,
        "no_identitas": body.no_identitas,
        "kendaraan": body.kendaraan,
        "jumlah_tamu": body.jumlah_tamu,
        "room_id": body.room_id,
        "room_nomor": r["nomor"],
        "room_tipe": r["tipe"],
        "tarif_dasar": r["tarif"],
        "jam_checkin": jam_ci_iso,
        "jam_checkout": None,
        "durasi_jam": 0,
        "overtime_jam": 0,
        "biaya_tambahan": 0,
        "total": 0,
        "status": "aktif",
        "catatan": body.catatan,
        "foto_identitas_url": body.foto_identitas_url or "",
        "pembayaran": [],
        "petugas_checkin": user["nama"],
        "petugas_checkin_id": user["id"],
        "created_at": now_iso(),
    }
    await db.checkins.insert_one(doc)
    await db.rooms.update_one({"id": body.room_id}, {"$set": {"status": "day_use", "info": {"checkin_id": doc["id"], "nama_tamu": body.nama_tamu}}})
    await log_activity(user, "checkin", f"Check-in {body.nama_tamu} ke kamar {r['nomor']}", entity=r["nomor"])
    doc.pop("_id", None)
    return doc

@api.get("/checkins")
async def list_checkins(
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = from_date
        if to_date: rng["$lte"] = to_date
        q["jam_checkin"] = rng
    items = await db.checkins.find(q, {"_id": 0}).sort("jam_checkin", -1).to_list(1000)
    return items

@api.get("/checkins/{checkin_id}")
async def get_checkin(checkin_id: str, user: dict = Depends(get_current_user)):
    c = await db.checkins.find_one({"id": checkin_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Check-in tidak ditemukan")
    if c["status"] == "aktif":
        now = datetime.now(timezone.utc)
        ci = datetime.fromisoformat(c["jam_checkin"])
        calc = calc_tagihan(c["tarif_dasar"], ci, now)
        c["preview"] = calc
    return c

@api.post("/checkins/{checkin_id}/checkout")
async def checkout(checkin_id: str, body: CheckoutIn, user: dict = Depends(get_current_user)):
    c = await db.checkins.find_one({"id": checkin_id})
    if not c:
        raise HTTPException(404, "Check-in tidak ditemukan")
    if c["status"] != "aktif":
        raise HTTPException(400, "Check-in sudah selesai")
    now = datetime.now(timezone.utc)
    if body.jam_checkout:
        try:
            d = datetime.fromisoformat(body.jam_checkout.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            now = d.astimezone(timezone.utc)
        except Exception:
            raise HTTPException(400, "Format jam check-out tidak valid")
    ci = datetime.fromisoformat(c["jam_checkin"])
    if now < ci:
        raise HTTPException(400, "Jam check-out tidak boleh sebelum jam check-in")
    calc = calc_tagihan(c["tarif_dasar"], ci, now, body.overtime_manual)
    total_bayar = sum(int(p.get("jumlah", 0)) for p in body.pembayaran)
    if total_bayar < calc["total"]:
        raise HTTPException(400, f"Total pembayaran kurang. Diperlukan Rp{calc['total']:,}".replace(",", "."))
    updates = {
        "jam_checkout": now.isoformat(),
        "durasi_jam": calc["durasi_jam"],
        "overtime_jam": calc["overtime_jam"],
        "biaya_tambahan": calc["biaya_tambahan"],
        "subtotal": calc["subtotal"],
        "service_fee": calc["service_fee"],
        "total": calc["total"],
        "pembayaran": body.pembayaran,
        "status": "selesai",
        "petugas_checkout": user["nama"],
        "petugas_checkout_id": user["id"],
        "catatan_checkout": body.catatan,
    }
    await db.checkins.update_one({"id": checkin_id}, {"$set": updates})
    await db.rooms.update_one({"id": c["room_id"]}, {"$set": {"status": "perlu_dibersihkan", "info": {}}})
    # housekeeping log
    await db.housekeeping_log.insert_one({
        "id": str(uuid.uuid4()),
        "room_id": c["room_id"],
        "room_nomor": c["room_nomor"],
        "tanggal": now.isoformat(),
        "jam_checkout": now.isoformat(),
        "jam_mulai": None,
        "jam_selesai": None,
        "petugas": "",
        "catatan": "",
        "status": "pending",
    })
    if c.get("guest_id"):
        await db.guests.update_one({"id": c["guest_id"]}, {"$inc": {"total_transaksi": calc["total"]}})
    await log_activity(user, "checkout", f"Check-out {c['nama_tamu']} kamar {c['room_nomor']}, total Rp{calc['total']:,}".replace(",", "."), entity=c["room_nomor"])
    res = {**c, **updates}
    res.pop("_id", None)
    return res

# ---- Guests ----
@api.get("/guests")
async def list_guests(q: Optional[str] = None, user: dict = Depends(get_current_user)):
    query: Dict[str, Any] = {}
    if q:
        query = {"$or": [
            {"nama": {"$regex": q, "$options": "i"}},
            {"no_hp": {"$regex": q, "$options": "i"}},
            {"no_identitas": {"$regex": q, "$options": "i"}},
        ]}
    items = await db.guests.find(query, {"_id": 0}).sort("last_visit", -1).to_list(500)
    return items

@api.get("/guests/{guest_id}/history")
async def guest_history(guest_id: str, user: dict = Depends(get_current_user)):
    items = await db.checkins.find({"guest_id": guest_id}, {"_id": 0}).sort("jam_checkin", -1).to_list(500)
    return items

