from core import *
import re

# ---- Properti (Owner only) — 2026-07-24, fondasi multi-properti ----
# Setiap dokumen di sini merepresentasikan 1 properti fisik (homestay/cottage). `slug` dipakai
# di URL Booking Engine publik (book.pelangihomestay.com/<slug>, lihat routes/public.py) - harus
# unik & aman untuk URL. property_id dari sini yang di-scope ke rooms/bookings/checkins/guests/
# staff_kerja/staff_profil/issues/expenses/payroll/booking_requests/jadwal_kerja/products/kasir/
# rates lewat helper `scoped()` (core.py) di seluruh route lain.

def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "properti"

@api.get("/properties")
async def list_properties(user: dict = Depends(get_current_user)):
    """Owner lihat semua properti (buat property switcher). Resepsionis cuma lihat
    properti tempatnya sendiri ditugaskan (buat tampilkan nama properti di header)."""
    q = {} if user["role"] == "owner" else {"id": user.get("property_id")}
    return await db.properties.find(q, {"_id": 0}).sort("created_at", 1).to_list(100)

@api.post("/properties")
async def create_property(body: PropertyCreate, user: dict = Depends(require_owner)):
    slug = _slugify(body.slug or body.nama)
    if await db.properties.find_one({"slug": slug}):
        raise HTTPException(400, "Slug sudah dipakai properti lain")
    doc = {
        "id": str(uuid.uuid4()),
        "nama": body.nama.strip(),
        "slug": slug,
        "alamat": (body.alamat or "").strip(),
        "aktif": True,
        "butuh_sinkron_reddoorz": body.butuh_sinkron_reddoorz,
        "created_at": now_iso(),
    }
    await db.properties.insert_one(doc)
    await log_activity(user, "create_property", f"Buat properti {doc['nama']} ({slug})")
    return {k: v for k, v in doc.items() if k != "_id"}

@api.put("/properties/{property_id}")
async def update_property(property_id: str, body: PropertyUpdate, user: dict = Depends(require_owner)):
    p = await db.properties.find_one({"id": property_id})
    if not p:
        raise HTTPException(404, "Properti tidak ditemukan")
    updates: Dict[str, Any] = {}
    if body.nama is not None: updates["nama"] = body.nama.strip()
    if body.alamat is not None: updates["alamat"] = body.alamat.strip()
    if body.aktif is not None: updates["aktif"] = body.aktif
    if body.butuh_sinkron_reddoorz is not None: updates["butuh_sinkron_reddoorz"] = body.butuh_sinkron_reddoorz
    if body.slug is not None:
        slug = _slugify(body.slug)
        if slug != p["slug"] and await db.properties.find_one({"slug": slug}):
            raise HTTPException(400, "Slug sudah dipakai properti lain")
        updates["slug"] = slug
    if updates:
        await db.properties.update_one({"id": property_id}, {"$set": updates})
        await log_activity(user, "update_property", f"Update properti {p['nama']}")
    return {"ok": True}
