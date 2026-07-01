from core import *


# ---- Services (Manual Layanan Tambahan) ----
@api.post("/services")
async def create_service(body: ServiceCreate, user: dict = Depends(get_current_user)):
    if body.nominal is None or body.nominal <= 0:
        raise HTTPException(400, "Nominal harus lebih dari 0")
    if not body.deskripsi or not body.deskripsi.strip():
        raise HTTPException(400, "Deskripsi layanan wajib diisi")
    kode = f"SVC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    doc = {
        "id": str(uuid.uuid4()),
        "kode": kode,
        "tanggal": body.tanggal or now_iso(),
        "kategori": body.kategori or "Layanan Tambahan",
        "deskripsi": body.deskripsi.strip(),
        "nominal": int(body.nominal),
        "tamu": (body.tamu or "").strip(),
        "no_hp": (body.no_hp or "").strip(),
        "room_nomor": (body.room_nomor or "").strip(),
        "metode_pembayaran": body.metode_pembayaran or "tunai",
        "user": user["nama"],
        "user_id": user["id"],
        "created_at": now_iso(),
    }
    await db.services.insert_one(doc)
    await log_activity(user, "service", f"Layanan {doc['kategori']} '{doc['deskripsi']}' Rp{doc['nominal']:,}".replace(",", "."), entity=kode)
    doc.pop("_id", None)
    return doc

@api.get("/services")
async def list_services(from_date: Optional[str] = None, to_date: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = from_date
        if to_date: rng["$lte"] = to_date + "T23:59:59"
        q["tanggal"] = rng
    items = await db.services.find(q, {"_id": 0}).sort("tanggal", -1).to_list(2000)
    return items

@api.delete("/services/{sid}")
async def delete_service(sid: str, user: dict = Depends(require_owner)):
    doc = await db.services.find_one({"id": sid})
    if not doc:
        raise HTTPException(404, "Layanan tidak ditemukan")
    await db.services.delete_one({"id": sid})
    await log_activity(user, "delete_service", f"Hapus layanan {doc.get('kode', sid)}", entity=doc.get("kode", sid))
    return {"ok": True}

