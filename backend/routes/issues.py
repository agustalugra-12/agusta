from core import *
from routes.push import send_push
from pymongo.errors import DuplicateKeyError

# ---- Complaint & Maintenance & Permintaan Layanan ----
# Satu collection `issues` dipakai untuk 3 tipe (complaint/maintenance/service_request) —
# modelnya identik (kamar, deskripsi, status open->in_progress->resolved), cuma beda
# label/konteks di frontend. service_request (extra bed/towel/cleaning/laundry/motor
# rental/airport pickup/dll dari AI WhatsApp/ai-chat-bot) sengaja REUSE mekanisme ini alih-alih
# collection/endpoint terpisah — secara sifat sama persis (staf perlu tindak lanjuti &
# selesaikan), cuma beda konteks dengan komplain/maintenance.
ISSUE_TIPE = {"complaint", "maintenance", "service_request"}
ISSUE_TIPE_LABEL = {"complaint": "Komplain", "maintenance": "Maintenance", "service_request": "Permintaan Layanan"}
ISSUE_STATUS = {"open", "in_progress", "resolved"}
ISSUE_PRIORITAS = {"rendah", "normal", "tinggi"}

async def buat_issue(tipe: str, deskripsi: str, user: dict, property_id: str, room_id: Optional[str] = None,
                     room_nomor: str = "", nama_tamu: str = "", prioritas: str = "normal",
                     teknisi: str = "", estimasi_selesai: Optional[str] = None, no_hp: str = "",
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Logika insert bersama — dipakai endpoint POST /issues (staf manual) DAN klasifikasi
    otomatis AI WhatsApp (routes/pesan_whatsapp.py) supaya audit log & push notif konsisten
    dari kedua jalur, tidak ada logika ganda yang bisa saling menyimpang.

    `idempotency_key` (2026-08-14, audit lanjutan pola bug idempotency_key
    booking_request/2026-08-14) - `ai_bot_buat_tiket` (routes/integrasi_ai_bot.py) reuse
    endpoint ini lewat `_pms_buat_tiket` (ai-chat-bot), yang dibungkus `_pms_http_retry`
    sama seperti `_pms_buat_booking_request` - retry pada `httpx.ReadTimeout` (PMS cuma
    LAMBAT balas krn sibuk kirim push notif, bukan gagal sungguhan) akan bikin tiket
    duplikat + push notif dobel tanpa guard ini. Optional/None supaya kompatibel mundur
    dgn pemanggil lama (endpoint staf manual POST /issues TIDAK PERNAH kirim field ini -
    tidak ada retry HTTP di jalur itu, jadi tetap selalu insert baru seperti sebelumnya)."""
    if idempotency_key:
        existing = await db.issues.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
        if existing:
            return existing
    if tipe not in ISSUE_TIPE:
        raise HTTPException(400, f"Tipe harus salah satu dari: {', '.join(sorted(ISSUE_TIPE))}")
    if not deskripsi or not deskripsi.strip():
        raise HTTPException(400, "Deskripsi wajib diisi")
    prioritas = prioritas or "normal"
    if prioritas not in ISSUE_PRIORITAS:
        raise HTTPException(400, f"Prioritas harus salah satu dari: {', '.join(sorted(ISSUE_PRIORITAS))}")
    if room_id:
        r = await db.rooms.find_one(scoped({"id": room_id}, property_id))
        if not r:
            raise HTTPException(404, "Kamar tidak ditemukan")
        room_nomor = r["nomor"]
    doc = {
        "id": str(uuid.uuid4()),
        "tipe": tipe,
        "room_id": room_id,
        "room_nomor": (room_nomor or "").strip(),
        "deskripsi": deskripsi.strip(),
        "status": "open",
        "catatan_penyelesaian": "",
        "nama_tamu": (nama_tamu or "").strip(),
        "no_hp": (no_hp or "").strip(),
        "prioritas": prioritas,
        "teknisi": (teknisi or "").strip(),
        "estimasi_selesai": estimasi_selesai,
        "created_by": user["nama"],
        "created_by_id": user["id"],
        "created_at": now_iso(),
        "resolved_by": None,
        "resolved_at": None,
        "property_id": property_id,
        "idempotency_key": idempotency_key,
    }
    try:
        await db.issues.insert_one(doc)
    except DuplicateKeyError:
        # Race sungguhan (2 request ber-idempotency_key sama lolos find_one di atas nyaris
        # bersamaan) - index unique sparse `issues.idempotency_key` (server.py startup) jadi
        # penjaga terakhir. Percobaan yang kalah balapan cukup ambil dokumen pemenang &
        # kembalikan itu, TANPA mengulang push notif.
        existing = await db.issues.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
        if existing:
            return existing
        raise
    label = ISSUE_TIPE_LABEL[tipe]
    push_url = {"complaint": "/komplain", "maintenance": "/maintenance", "service_request": "/service-requests"}[tipe]
    await log_activity(user, "create_issue", f"{label} kamar {doc['room_nomor'] or '-'}: {doc['deskripsi']}", entity=doc["room_nomor"])
    await send_push(f"{label} Baru", f"Kamar {doc['room_nomor'] or '-'}: {doc['deskripsi']}", url=push_url)
    doc.pop("_id", None)
    return doc


@api.post("/issues")
async def create_issue(body: IssueCreate, user: dict = Depends(get_current_user),
                       property_id: str = Depends(get_active_property)):
    return await buat_issue(
        body.tipe, body.deskripsi, user, property_id, room_id=body.room_id, room_nomor=body.room_nomor or "",
        nama_tamu=body.nama_tamu or "", prioritas=body.prioritas or "normal",
        teknisi=body.teknisi or "", estimasi_selesai=body.estimasi_selesai,
    )

@api.get("/issues")
async def list_issues(tipe: Optional[str] = None, status: Optional[str] = None,
                      user: dict = Depends(get_current_user),
                      property_id: str = Depends(get_active_property)):
    q: Dict[str, Any] = {}
    if tipe: q["tipe"] = tipe
    if status: q["status"] = status
    items = await db.issues.find(scoped(q, property_id), {"_id": 0}).sort("created_at", -1).to_list(1000)
    return items

@api.put("/issues/{issue_id}/status")
async def update_issue_status(issue_id: str, body: IssueStatusUpdate, user: dict = Depends(get_current_user),
                              property_id: str = Depends(get_active_property)):
    if body.status not in ISSUE_STATUS:
        raise HTTPException(400, f"Status harus salah satu dari: {', '.join(sorted(ISSUE_STATUS))}")
    it = await db.issues.find_one(scoped({"id": issue_id}, property_id))
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
async def delete_issue(issue_id: str, user: dict = Depends(require_owner),
                       property_id: str = Depends(get_active_property)):
    it = await db.issues.find_one(scoped({"id": issue_id}, property_id))
    if not it:
        raise HTTPException(404, "Data tidak ditemukan")
    await db.issues.delete_one({"id": issue_id})
    await log_activity(user, "delete_issue", f"Hapus {it['tipe']} kamar {it.get('room_nomor') or '-'}", entity=it.get("room_nomor"))
    return {"ok": True}
