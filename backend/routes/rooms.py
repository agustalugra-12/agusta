from core import *
from routes.push import send_push

UPLOAD_DIR_ROOMS = ROOT_DIR / "uploads" / "rooms"
UPLOAD_DIR_ROOMS.mkdir(parents=True, exist_ok=True)
_EXT_FOTO_DIIZINKAN = {"jpg", "jpeg", "png", "webp"}

# ---- Rooms ----
@api.get("/rooms")
async def list_rooms(user: dict = Depends(get_current_user)):
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    # Urut murni berdasarkan nomor kamar (1..18), tanpa dikelompokkan per tipe — nomor kamar tidak berurutan per tipe.
    rooms.sort(key=lambda r: int("".join(c for c in r.get("nomor", "0") if c.isdigit()) or 0))
    return rooms

@api.post("/rooms")
async def create_room(body: RoomCreate, user: dict = Depends(require_owner)):
    if await db.rooms.find_one({"nomor": body.nomor}):
        raise HTTPException(400, "Nomor kamar sudah ada")
    doc = {
        "id": str(uuid.uuid4()),
        "nomor": body.nomor,
        "tipe": body.tipe,
        "tarif": body.tarif,
        "tarif_menginap": body.tarif_menginap,
        "status": "kosong",
        "info": {},  # menginap info: nama_tamu, checkin_date, checkout_date, catatan
        "foto_urls": [],
        "foto_utama": "",
        "created_at": now_iso(),
    }
    await db.rooms.insert_one(doc)
    await log_activity(user, "create_room", f"Buat kamar {body.nomor}")
    doc.pop("_id", None)
    return doc

@api.put("/rooms/{room_id}")
async def update_room(room_id: str, body: RoomUpdate, user: dict = Depends(require_owner)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "foto_utama" in updates and updates["foto_utama"] not in (r.get("foto_urls") or []):
        raise HTTPException(400, "Foto utama harus salah satu foto yang sudah diupload untuk kamar ini")
    if updates:
        await db.rooms.update_one({"id": room_id}, {"$set": updates})
    await log_activity(user, "update_room", f"Update kamar {r['nomor']}")
    return {"ok": True}

@api.post("/rooms/{room_id}/foto")
async def upload_room_foto(room_id: str, file: UploadFile = File(...), user: dict = Depends(require_owner)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    ext = (file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "")
    if ext not in _EXT_FOTO_DIIZINKAN:
        raise HTTPException(400, "Format foto harus JPG, PNG, atau WEBP")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Ukuran foto maksimal 5MB")
    fname = f"{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR_ROOMS / fname).write_bytes(content)
    url = f"/uploads/rooms/{fname}"
    foto_urls = (r.get("foto_urls") or []) + [url]
    updates = {"foto_urls": foto_urls}
    if not r.get("foto_utama"):
        updates["foto_utama"] = url
    await db.rooms.update_one({"id": room_id}, {"$set": updates})
    await log_activity(user, "upload_room_foto", f"Upload foto kamar {r['nomor']}")
    return {"foto_urls": foto_urls, "foto_utama": updates.get("foto_utama", r.get("foto_utama", ""))}

@api.delete("/rooms/{room_id}/foto")
async def delete_room_foto(room_id: str, url: str, user: dict = Depends(require_owner)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    foto_urls = [u for u in (r.get("foto_urls") or []) if u != url]
    updates = {"foto_urls": foto_urls}
    if r.get("foto_utama") == url:
        updates["foto_utama"] = foto_urls[0] if foto_urls else ""
    await db.rooms.update_one({"id": room_id}, {"$set": updates})
    fpath = UPLOAD_DIR_ROOMS / url.rsplit("/", 1)[-1]
    if fpath.exists() and fpath.is_relative_to(UPLOAD_DIR_ROOMS):
        fpath.unlink()
    await log_activity(user, "delete_room_foto", f"Hapus foto kamar {r['nomor']}")
    return {"foto_urls": foto_urls, "foto_utama": updates.get("foto_utama", r.get("foto_utama", ""))}

@api.delete("/rooms/{room_id}")
async def delete_room(room_id: str, user: dict = Depends(require_owner)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, "Kamar tidak dapat dihapus karena sedang aktif")
    await db.rooms.delete_one({"id": room_id})
    await log_activity(user, "delete_room", f"Hapus kamar {r['nomor']}")
    return {"ok": True}

@api.put("/rooms/{room_id}/status")
async def change_room_status(room_id: str, body: RoomStatusUpdate, user: dict = Depends(get_current_user)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    valid = {"kosong", "day_use", "menginap", "perlu_dibersihkan", "maintenance"}
    if body.status not in valid:
        raise HTTPException(400, "Status tidak valid")
    if body.status == "day_use":
        raise HTTPException(400, "Status day_use diubah otomatis lewat check-in")
    old_status = r["status"]
    info = r.get("info", {}) or {}
    if body.status == "menginap":
        info = {
            "nama_tamu": body.nama_tamu,
            "catatan": body.catatan,
            "checkin_date": now_iso(),
        }
    elif body.status == "maintenance":
        info = {"catatan": body.catatan}
    else:
        info = {}
    await db.rooms.update_one({"id": room_id}, {"$set": {"status": body.status, "info": info}})
    await log_activity(user, "change_room_status",
                       f"Kamar {r['nomor']}: {old_status} -> {body.status}",
                       entity=r["nomor"])
    # housekeeping log
    if body.status == "perlu_dibersihkan":
        await db.housekeeping_log.insert_one({
            "id": str(uuid.uuid4()),
            "room_id": r["id"],
            "room_nomor": r["nomor"],
            "tanggal": now_iso(),
            "jam_mulai": None,
            "jam_selesai": None,
            "petugas": "",
            "catatan": body.catatan or "",
            "status": "pending",
        })
        await send_push("Kamar Perlu Dibersihkan", f"Kamar {r['nomor']}", url="/housekeeping", role="resepsionis")
    return {"ok": True}

@api.post("/rooms/{room_id}/housekeeping-mulai")
async def housekeeping_mulai(room_id: str, user: dict = Depends(get_current_user)):
    """Tandai kamar mulai dibersihkan (jam_mulai + status Cleaning) — idempotent, tidak
    menimpa jam_mulai yang sudah tercatat kalau tombol Mulai dipencet lebih dari sekali."""
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "perlu_dibersihkan":
        raise HTTPException(400, "Kamar tidak dalam status Perlu Dibersihkan")
    pending = await db.housekeeping_log.find_one({"room_id": room_id, "status": {"$in": ["pending", "cleaning"]}}, sort=[("tanggal", -1)])
    if pending and not pending.get("jam_mulai"):
        await db.housekeeping_log.update_one({"id": pending["id"]}, {"$set": {"jam_mulai": now_iso(), "status": "cleaning"}})
    return {"ok": True}

@api.post("/rooms/{room_id}/housekeeping-done")
async def housekeeping_done(room_id: str, body: HousekeepingDone, user: dict = Depends(get_current_user)):
    """Tandai kamar selesai dibersihkan — status jadi Clean (belum Inspected) & kamar kembali
    Kosong (siap dipakai lagi; Inspected sengaja tidak menahan ketersediaan kamar, cuma lapisan
    QC tambahan untuk supervisor/owner — lihat housekeeping_inspect)."""
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "perlu_dibersihkan":
        raise HTTPException(400, "Kamar tidak dalam status Perlu Dibersihkan")
    await db.rooms.update_one({"id": room_id}, {"$set": {"status": "kosong", "info": {}}})
    pending = await db.housekeeping_log.find_one({"room_id": room_id, "status": {"$in": ["pending", "cleaning"]}}, sort=[("tanggal", -1)])
    if pending:
        await db.housekeeping_log.update_one(
            {"id": pending["id"]},
            {"$set": {
                "jam_selesai": now_iso(),
                "petugas": body.petugas or user["nama"],
                "catatan": body.catatan or pending.get("catatan", ""),
                "status": "clean",
            }}
        )
    await log_activity(user, "housekeeping_done", f"Kamar {r['nomor']} selesai dibersihkan", entity=r["nomor"])
    return {"ok": True}

@api.post("/rooms/{room_id}/housekeeping-inspect")
async def housekeeping_inspect(room_id: str, user: dict = Depends(get_current_user)):
    """Verifikasi kualitas (QC) kamar yang sudah Clean — status jadi Inspected. Tidak
    mempengaruhi ketersediaan kamar (kamar sudah Kosong/bookable sejak status Clean),
    murni pencatatan siapa & kapan kamar diperiksa ulang."""
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    log = await db.housekeeping_log.find_one({"room_id": room_id, "status": "clean"}, sort=[("tanggal", -1)])
    if not log:
        raise HTTPException(400, "Tidak ada riwayat pembersihan berstatus Clean untuk kamar ini")
    await db.housekeeping_log.update_one(
        {"id": log["id"]},
        {"$set": {"status": "inspected", "inspected_by": user["nama"], "inspected_at": now_iso()}}
    )
    await log_activity(user, "housekeeping_inspect", f"Kamar {r['nomor']} diverifikasi (Inspected)", entity=r["nomor"])
    return {"ok": True}

@api.post("/rooms/{room_id}/move")
async def move_room(room_id: str, body: MoveRoomBody, user: dict = Depends(get_current_user)):
    """Pindahkan tamu/info dari kamar lama ke kamar baru.
    - day_use: update checkin aktif room_id + room_nomor + room_tipe (tarif_dasar tetap), pindah info.
    - menginap: pindah info dict ke kamar baru.
    - Kamar lama → perlu_dibersihkan (karena tamu pernah masuk). Kamar baru → status sama dengan kamar lama.
    """
    if body.new_room_id == room_id:
        raise HTTPException(400, "Kamar tujuan sama dengan kamar asal")
    old = await db.rooms.find_one({"id": room_id})
    if not old:
        raise HTTPException(404, "Kamar asal tidak ditemukan")
    if old["status"] not in ("day_use", "menginap"):
        raise HTTPException(400, "Hanya kamar Day Use atau Menginap yang bisa dipindahkan")
    new = await db.rooms.find_one({"id": body.new_room_id})
    if not new:
        raise HTTPException(404, "Kamar tujuan tidak ditemukan")
    if new["status"] != "kosong":
        raise HTTPException(400, f"Kamar tujuan tidak kosong (status: {new['status']})")
    new_status = old["status"]
    new_info = dict(old.get("info") or {})
    # update kamar baru
    await db.rooms.update_one({"id": new["id"]}, {"$set": {"status": new_status, "info": new_info}})
    # update kamar lama
    await db.rooms.update_one({"id": old["id"]}, {"$set": {"status": "perlu_dibersihkan", "info": {}}})
    # update active checkin jika day_use
    if old["status"] == "day_use":
        ci = await db.checkins.find_one({"room_id": old["id"], "status": "aktif"})
        if ci:
            await db.checkins.update_one(
                {"id": ci["id"]},
                {"$set": {
                    "room_id": new["id"], "room_nomor": new["nomor"], "room_tipe": new["tipe"],
                    "moved_from_room_id": old["id"], "moved_from_room_nomor": old["nomor"],
                    "moved_at": now_iso(), "moved_by": user["nama"],
                    "move_reason": body.alasan or "",
                }}
            )
    # housekeeping log untuk kamar lama
    await db.housekeeping_log.insert_one({
        "id": str(uuid.uuid4()), "room_id": old["id"], "room_nomor": old["nomor"],
        "tanggal": now_iso(), "jam_mulai": None, "jam_selesai": None,
        "petugas": "", "catatan": f"Pindah tamu ke kamar {new['nomor']}", "status": "pending",
    })
    await send_push("Kamar Perlu Dibersihkan", f"Kamar {old['nomor']}", url="/housekeeping", role="resepsionis")
    await log_activity(
        user, "move_room",
        f"Pindah tamu kamar {old['nomor']} → kamar {new['nomor']} ({body.alasan or 'tanpa alasan'})",
        entity=f"{old['nomor']}->{new['nomor']}"
    )
    return {"ok": True, "from": old["nomor"], "to": new["nomor"], "status": new_status}

