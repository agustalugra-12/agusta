from core import *
from routes.push import send_push

# ---- Complaint & Maintenance ----
# Satu collection `issues` dipakai untuk 2 tipe (complaint/maintenance) — modelnya identik
# (kamar, deskripsi, status open->in_progress->resolved), cuma beda label/konteks di frontend.
# Klasifikasi otomatis dari AI WhatsApp (TV mati -> maintenance, handuk belum ada -> complaint)
# menyusul di fase AI booking recommendation — endpoint ini dulu untuk pencatatan manual staf.
ISSUE_TIPE = {"complaint", "maintenance"}
ISSUE_STATUS = {"open", "in_progress", "resolved"}
ISSUE_PRIORITAS = {"rendah", "normal", "tinggi"}

@api.post("/issues")
async def create_issue(body: IssueCreate, user: dict = Depends(get_current_user)):
    if body.tipe not in ISSUE_TIPE:
        raise HTTPException(400, "Tipe harus 'complaint' atau 'maintenance'")
    if not body.deskripsi or not body.deskripsi.strip():
        raise HTTPException(400, "Deskripsi wajib diisi")
    prioritas = body.prioritas or "normal"
    if prioritas not in ISSUE_PRIORITAS:
        raise HTTPException(400, f"Prioritas harus salah satu dari: {', '.join(sorted(ISSUE_PRIORITAS))}")
    room_nomor = (body.room_nomor or "").strip()
    if body.room_id:
        r = await db.rooms.find_one({"id": body.room_id})
        if not r:
            raise HTTPException(404, "Kamar tidak ditemukan")
        room_nomor = r["nomor"]
    doc = {
        "id": str(uuid.uuid4()),
        "tipe": body.tipe,
        "room_id": body.room_id,
        "room_nomor": room_nomor,
        "deskripsi": body.deskripsi.strip(),
        "status": "open",
        "catatan_penyelesaian": "",
        "nama_tamu": (body.nama_tamu or "").strip(),
        "prioritas": prioritas,
        "teknisi": (body.teknisi or "").strip(),
        "estimasi_selesai": body.estimasi_selesai,
        "created_by": user["nama"],
        "created_by_id": user["id"],
        "created_at": now_iso(),
        "resolved_by": None,
        "resolved_at": None,
    }
    await db.issues.insert_one(doc)
    label = "Komplain" if body.tipe == "complaint" else "Maintenance"
    await log_activity(user, "create_issue", f"{label} kamar {room_nomor or '-'}: {doc['deskripsi']}", entity=room_nomor)
    await send_push(f"{label} Baru", f"Kamar {room_nomor or '-'}: {doc['deskripsi']}", url="/komplain")
    doc.pop("_id", None)
    return doc

@api.get("/issues")
async def list_issues(tipe: Optional[str] = None, status: Optional[str] = None,
                      user: dict = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if tipe: q["tipe"] = tipe
    if status: q["status"] = status
    items = await db.issues.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return items

@api.put("/issues/{issue_id}/status")
async def update_issue_status(issue_id: str, body: IssueStatusUpdate, user: dict = Depends(get_current_user)):
    if body.status not in ISSUE_STATUS:
        raise HTTPException(400, f"Status harus salah satu dari: {', '.join(sorted(ISSUE_STATUS))}")
    it = await db.issues.find_one({"id": issue_id})
    if not it:
        raise HTTPException(404, "Data tidak ditemukan")
    updates: Dict[str, Any] = {"status": body.status, "catatan_penyelesaian": body.catatan_penyelesaian or it.get("catatan_penyelesaian", "")}
    if body.teknisi is not None:
        updates["teknisi"] = body.teknisi.strip()
    if body.estimasi_selesai is not None:
        updates["estimasi_selesai"] = body.estimasi_selesai
    if body.prioritas is not None:
        if body.prioritas not in ISSUE_PRIORITAS:
            raise HTTPException(400, f"Prioritas harus salah satu dari: {', '.join(sorted(ISSUE_PRIORITAS))}")
        updates["prioritas"] = body.prioritas
    if body.status == "resolved":
        updates["resolved_by"] = user["nama"]
        updates["resolved_at"] = now_iso()
    else:
        updates["resolved_by"] = None
        updates["resolved_at"] = None
    await db.issues.update_one({"id": issue_id}, {"$set": updates})
    await log_activity(user, "update_issue_status", f"{it['tipe']} kamar {it.get('room_nomor') or '-'} -> {body.status}", entity=it.get("room_nomor"))
    return {"ok": True}

@api.delete("/issues/{issue_id}")
async def delete_issue(issue_id: str, user: dict = Depends(require_owner)):
    it = await db.issues.find_one({"id": issue_id})
    if not it:
        raise HTTPException(404, "Data tidak ditemukan")
    await db.issues.delete_one({"id": issue_id})
    await log_activity(user, "delete_issue", f"Hapus {it['tipe']} kamar {it.get('room_nomor') or '-'}", entity=it.get("room_nomor"))
    return {"ok": True}
