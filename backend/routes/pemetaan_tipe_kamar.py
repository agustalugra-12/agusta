from core import *

# ---- Pemetaan Tipe Kamar OTA <-> PMS ----
# Catatan arsitektur: Pelangi PMS di sistem ini ADALAH aplikasi ini sendiri (bukan PMS
# eksternal terpisah), jadi tidak ada tabel `pms_room_types` tersendiri yang perlu
# disinkronkan/basi — tipe kamar diambil langsung & selalu real-time dari collection
# `rooms` yang sudah ada (dipakai juga oleh /api/rooms dan /api/public/rooms-catalog).

@api.get("/pms-room-types")
async def list_pms_room_types(user: dict = Depends(get_current_user)):
    rooms = await db.rooms.find({}, {"_id": 0, "tipe": 1, "tarif": 1}).to_list(500)
    grouped: Dict[str, Any] = {}
    for r in rooms:
        t = r["tipe"]
        if t not in grouped:
            grouped[t] = {"tipe": t, "tarif": r["tarif"], "jumlah_kamar": 0}
        grouped[t]["jumlah_kamar"] += 1
    return list(grouped.values())

@api.post("/pms-room-types/sync")
async def sync_pms_room_types(user: dict = Depends(require_owner)):
    """"Impor dari PMS" — di arsitektur ini PMS = aplikasi ini sendiri, jadi "sinkronisasi"
    berarti membaca ulang `rooms` (selalu live). Dipertahankan sebagai endpoint eksplisit
    supaya tombol "Impor dari PMS" di UI punya aksi nyata + tercatat di audit log.
    """
    tipe_list = await list_pms_room_types(user)
    await log_activity(user, "sync_pms_room_types", f"Impor {len(tipe_list)} tipe kamar dari PMS")
    return {"tipe": [t["tipe"] for t in tipe_list], "waktu": now_iso()}

@api.get("/mappings")
async def list_mappings(user: dict = Depends(get_current_user)):
    items = await db.room_mappings.find({}, {"_id": 0}).to_list(500)
    items.sort(key=lambda m: (m["sumber"], m["ota_nama"]))
    return items

async def _cek_duplikat(sumber: str, ota_nama: str, exclude_id: Optional[str] = None):
    q: Dict[str, Any] = {"sumber": sumber, "ota_nama": ota_nama}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    dup = await db.room_mappings.find_one(q)
    if dup:
        raise HTTPException(400, f'Pemetaan "{ota_nama}" dari {sumber} sudah ada')

@api.post("/mappings")
async def create_mapping(body: RoomMappingCreate, user: dict = Depends(require_owner)):
    await _cek_duplikat(body.sumber, body.ota_nama)
    doc = {
        "id": str(uuid.uuid4()),
        "ota_nama": body.ota_nama,
        "pms_tipe": body.pms_tipe,
        "sumber": body.sumber,
        "created_by": user["id"],
        "created_at": now_iso(),
    }
    await db.room_mappings.insert_one(doc)
    await log_activity(user, "create_mapping", f'Petakan "{body.ota_nama}" ({body.sumber}) -> {body.pms_tipe}')
    doc.pop("_id", None)
    return doc

@api.put("/mappings/{mapping_id}")
async def update_mapping(mapping_id: str, body: RoomMappingUpdate, user: dict = Depends(require_owner)):
    m = await db.room_mappings.find_one({"id": mapping_id})
    if not m:
        raise HTTPException(404, "Pemetaan tidak ditemukan")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await _cek_duplikat(updates.get("sumber", m["sumber"]), updates.get("ota_nama", m["ota_nama"]), exclude_id=mapping_id)
        await db.room_mappings.update_one({"id": mapping_id}, {"$set": updates})
    await log_activity(user, "update_mapping", f'Update pemetaan "{m["ota_nama"]}"')
    return {"ok": True}

@api.delete("/mappings/{mapping_id}")
async def delete_mapping(mapping_id: str, user: dict = Depends(require_owner)):
    m = await db.room_mappings.find_one({"id": mapping_id})
    if not m:
        raise HTTPException(404, "Pemetaan tidak ditemukan")
    await db.room_mappings.delete_one({"id": mapping_id})
    await log_activity(user, "delete_mapping", f'Hapus pemetaan "{m["ota_nama"]}" ({m["sumber"]})')
    return {"ok": True}

@api.get("/unmapped-ota-rooms")
async def list_unmapped_ota_rooms(user: dict = Depends(get_current_user)):
    """Nama tipe kamar OTA yang terdeteksi AI Email Parser (extracted_data.tipe_kamar di
    `email_logs`) tapi belum ada pemetaannya. Selalu kosong sampai email parsing sungguhan
    (task terpisah, butuh API key AI) aktif dan mulai mengisi `email_logs`.
    """
    mapped: set = set()
    async for m in db.room_mappings.find({}, {"_id": 0, "ota_nama": 1, "sumber": 1}):
        mapped.add((m["ota_nama"], m["sumber"]))
    logs = await db.email_logs.find(
        {"extracted_data.tipe_kamar": {"$exists": True}},
        {"_id": 0, "extracted_data.tipe_kamar": 1, "sumber": 1},
    ).to_list(1000)
    counts: Dict[Any, int] = {}
    for l in logs:
        tipe = (l.get("extracted_data") or {}).get("tipe_kamar")
        sumber = l.get("sumber")
        if not tipe or not sumber or (tipe, sumber) in mapped:
            continue
        key = (tipe, sumber)
        counts[key] = counts.get(key, 0) + 1
    return [
        {"id": f"{sumber}:{tipe}", "ota_nama": tipe, "sumber": sumber, "jumlah_kemunculan": n}
        for (tipe, sumber), n in counts.items()
    ]
