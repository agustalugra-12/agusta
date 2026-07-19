from core import *
from routes.push import send_push

@api.post("/checkins")
async def create_checkin(body: CheckinCreate, user: dict = Depends(get_current_user)):
    """Check-in Day Use 1 kamar (alur lama, `room_id`) atau beberapa kamar sekaligus dalam
    1 grup (`room_ids`, mis. rombongan walk-in) — tarif_override berlaku sama untuk tiap
    kamar, 1 data tamu/guest record dipakai bersama, tapi tiap kamar tetap jadi dokumen
    checkin terpisah (harga/durasi/checkout dihitung independen per kamar). Response tetap
    1 dict datar (backward compatible) kalau cuma 1 kamar; jadi `{"group_id", "checkins": [...]}`
    kalau lebih dari 1.
    """
    room_ids = body.room_ids if body.room_ids else ([body.room_id] if body.room_id else [])
    room_ids = list(dict.fromkeys(room_ids))
    if not room_ids:
        raise HTTPException(400, "room_id atau room_ids wajib diisi")
    if body.tarif_override is not None and body.tarif_override <= 0:
        raise HTTPException(400, "Harga custom harus lebih dari 0")

    rooms = []
    for rid in room_ids:
        r = await db.rooms.find_one({"id": rid})
        if not r:
            raise HTTPException(404, f"Kamar tidak ditemukan (id {rid})")
        if r["status"] != "kosong":
            raise HTTPException(400, f"Kamar {r['nomor']} belum tersedia dan tidak dapat digunakan untuk check-in.")
        rooms.append(r)

    # Save / upsert guest — 1 data tamu dipakai bersama untuk semua kamar dalam grup ini.
    guest_id = await upsert_guest(body.nama_tamu, body.no_hp, body.no_identitas, body.kendaraan)
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

    group_id = str(uuid.uuid4()) if len(rooms) > 1 else None
    created = []
    for r in rooms:
        tarif_dasar = body.tarif_override if body.tarif_override else r["tarif"]
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
            "room_id": r["id"],
            "room_nomor": r["nomor"],
            "room_tipe": r["tipe"],
            "tarif_dasar": tarif_dasar,
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
        if group_id:
            doc["group_id"] = group_id
        await db.checkins.insert_one(doc)
        await db.rooms.update_one({"id": r["id"]}, {"$set": {"status": "day_use", "info": {"checkin_id": doc["id"], "nama_tamu": body.nama_tamu}}})
        await log_activity(user, "checkin", f"Check-in {body.nama_tamu} ke kamar {r['nomor']}", entity=r["nomor"])
        doc.pop("_id", None)
        created.append(doc)

    if len(created) == 1:
        return created[0]
    return {"group_id": group_id, "checkins": created}

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
    await send_push("Kamar Perlu Dibersihkan", f"Kamar {c['room_nomor']}", url="/housekeeping", role="resepsionis")
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
    items = await db.guests.find(query, {"_id": 0}).to_list(500)
    for it in items:
        it.update(diskon_member_untuk_total_kunjungan(it.get("total_kunjungan", 0)))
    # sort di Python (case-insensitive) - default Mongo sort per byte (huruf besar/kecil/angka
    # tercampur tidak sesuai urutan A-Z yang wajar dilihat orang), aman untuk skala tamu (<=500)
    items.sort(key=lambda g: (g.get("nama") or "").lower())
    return items

@api.get("/guests/{guest_id}/history")
async def guest_history(guest_id: str, user: dict = Depends(get_current_user)):
    items = await db.checkins.find({"guest_id": guest_id}, {"_id": 0}).sort("jam_checkin", -1).to_list(500)
    return items

