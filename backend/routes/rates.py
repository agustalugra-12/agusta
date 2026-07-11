from core import *

# ---- Manajemen Harga / Rates (Fase 3, halaman Kalender Harga) ----
# Tarif dasar per tipe kamar tetap di `rooms.tarif` (satu sumber kebenaran).
# `rates` cuma menyimpan override per tanggal — tanggal tanpa override memakai tarif dasar.


async def _tarif_dasar_per_tipe() -> Dict[str, int]:
    rooms = await db.rooms.find({}, {"_id": 0, "tipe": 1, "tarif": 1}).to_list(200)
    out: Dict[str, int] = {}
    for r in rooms:
        out.setdefault(r["tipe"], r["tarif"])
    return out


@api.get("/rates/kalender")
async def get_kalender_harga(room_type: str = Query(...), from_date: str = Query(...),
                              to_date: str = Query(...), user: dict = Depends(get_current_user)):
    """Harga per tanggal untuk satu tipe kamar dalam rentang [from_date, to_date]:
    override dari `rates` kalau ada, jatuh balik ke tarif dasar `rooms.tarif`."""
    dasar = await _tarif_dasar_per_tipe()
    if room_type not in dasar:
        raise HTTPException(404, "Tipe kamar tidak ditemukan")
    tarif_dasar = dasar[room_type]

    overrides = await db.rates.find({
        "room_type": room_type,
        "tanggal": {"$gte": from_date, "$lte": to_date},
    }, {"_id": 0, "tanggal": 1, "harga": 1}).to_list(400)
    by_date = {o["tanggal"]: o["harga"] for o in overrides}

    d_from = datetime.fromisoformat(from_date).date()
    d_to = datetime.fromisoformat(to_date).date()
    days = []
    d = d_from
    while d <= d_to:
        iso = d.isoformat()
        days.append({"tanggal": iso, "harga": by_date.get(iso, tarif_dasar), "override": iso in by_date})
        d += timedelta(days=1)
    return {"room_type": room_type, "tarif_dasar": tarif_dasar, "days": days}


@api.get("/rates/tipe-kamar")
async def get_tipe_kamar_rates(user: dict = Depends(get_current_user)):
    """Daftar tipe kamar + tarif dasar, dipakai untuk tab selector di halaman Kalender Harga."""
    dasar = await _tarif_dasar_per_tipe()
    return [{"tipe": k, "tarif_dasar": v} for k, v in dasar.items()]


@api.post("/rates/update-massal")
async def update_harga_massal(body: RateBulkUpdateBody, user: dict = Depends(get_current_user)):
    """Update Harga Massal: terapkan `harga` ke setiap tanggal di [dari, sampai] untuk satu
    tipe kamar (atau semua tipe kalau room_type == 'Semua'). Upsert per (room_type, tanggal)."""
    if body.harga <= 0:
        raise HTTPException(400, "Harga harus lebih dari 0")
    d_from = datetime.fromisoformat(body.dari).date()
    d_to = datetime.fromisoformat(body.sampai).date()
    if d_from > d_to:
        raise HTTPException(400, "Rentang tanggal tidak valid")

    dasar = await _tarif_dasar_per_tipe()
    tipe_list = list(dasar.keys()) if body.room_type == "Semua" else [body.room_type]
    for t in tipe_list:
        if t not in dasar:
            raise HTTPException(404, f"Tipe kamar '{t}' tidak ditemukan")

    now = now_iso()
    jumlah_hari = (d_to - d_from).days + 1
    d = d_from
    while d <= d_to:
        iso = d.isoformat()
        for t in tipe_list:
            await db.rates.update_one(
                {"room_type": t, "tanggal": iso},
                {"$set": {"harga": body.harga, "updated_at": now, "updated_by": user["nama"]},
                 "$setOnInsert": {"id": str(uuid.uuid4()), "room_type": t, "tanggal": iso}},
                upsert=True,
            )
        d += timedelta(days=1)
    detail = f"Update harga {', '.join(tipe_list)} {body.dari}..{body.sampai} → {body.harga}"
    await log_activity(user, "update_harga_massal", detail)
    # Sinkronisasi harga ke saluran (bot WhatsApp) — pola sama dengan sinkronisasi ketersediaan
    # (lihat push_sync_event di core.py, dipakai juga oleh log_availability_change).
    await push_sync_event("harga", detail)
    return {"ok": True, "tipe": tipe_list, "jumlah_hari": jumlah_hari, "harga": body.harga}
