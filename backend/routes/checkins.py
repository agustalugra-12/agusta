from core import *
from routes.push import send_push

@api.post("/checkins")
async def create_checkin(body: CheckinCreate, user: dict = Depends(get_current_user),
                         property_id: str = Depends(get_active_property)):
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
        r = await db.rooms.find_one(scoped({"id": rid}, property_id))
        if not r:
            raise HTTPException(404, f"Kamar tidak ditemukan (id {rid})")
        if r["status"] != "kosong":
            raise HTTPException(400, f"Kamar {r['nomor']} belum tersedia dan tidak dapat digunakan untuk check-in.")
        rooms.append(r)

    # Save / upsert guest — 1 data tamu dipakai bersama untuk semua kamar dalam grup ini.
    room_nomor_gabung = ", ".join(r["nomor"] for r in rooms)
    guest_id = await upsert_guest(body.nama_tamu, body.no_hp, body.no_identitas, body.kendaraan, property_id, room_nomor=room_nomor_gabung)
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
            "property_id": property_id,
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
    property_id: str = Depends(get_active_property),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = from_date
        if to_date: rng["$lte"] = to_date
        q["jam_checkin"] = rng
    items = await db.checkins.find(scoped(q, property_id), {"_id": 0}).sort("jam_checkin", -1).to_list(1000)
    return items

@api.get("/checkins/{checkin_id}")
async def get_checkin(checkin_id: str, user: dict = Depends(get_current_user),
                      property_id: str = Depends(get_active_property)):
    c = await db.checkins.find_one(scoped({"id": checkin_id}, property_id), {"_id": 0})
    if not c:
        raise HTTPException(404, "Check-in tidak ditemukan")
    if c["status"] == "aktif":
        now = datetime.now(timezone.utc)
        ci = datetime.fromisoformat(c["jam_checkin"])
        calc = calc_tagihan(c["tarif_dasar"], ci, now)
        c["preview"] = calc
    return c

@api.post("/checkins/{checkin_id}/checkout")
async def checkout(checkin_id: str, body: CheckoutIn, user: dict = Depends(get_current_user),
                   property_id: str = Depends(get_active_property)):
    c = await db.checkins.find_one(scoped({"id": checkin_id}, property_id))
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
    # Cash & Account Intelligence V1.5 (2026-07-22) - posting `total_bayar` (uang yang
    # BENAR-BENAR dikumpulkan staf saat checkout ini, bukan `calc["total"]`) ke rekening
    # operasional default, best-effort. Kalau booking ini sebelumnya sudah dibayar online
    # via Tripay, itu SUDAH terposting terpisah di webhook Tripay - `total_bayar` di sini
    # cuma yang dikumpulkan fisik di titik checkout, tidak dobel hitung.
    from routes.rekening import auto_posting
    await auto_posting("pemasukan", total_bayar, "Check-out Day Use", f"Kamar {c['room_nomor']} - {c['nama_tamu']}", property_id)
    res = {**c, **updates}
    res.pop("_id", None)
    return res

# ---- Guests ----
@api.get("/guests")
async def list_guests(q: Optional[str] = None, user: dict = Depends(get_current_user),
                      property_id: str = Depends(get_active_property)):
    query: Dict[str, Any] = {}
    if q:
        query = {"$or": [
            {"nama": {"$regex": q, "$options": "i"}},
            {"no_hp": {"$regex": q, "$options": "i"}},
            {"no_identitas": {"$regex": q, "$options": "i"}},
        ]}
    items = await db.guests.find(scoped(query, property_id), {"_id": 0}).to_list(500)
    for it in items:
        it.update(diskon_member_untuk_total_kunjungan(it.get("total_kunjungan", 0)))
    # sort di Python (case-insensitive) - default Mongo sort per byte (huruf besar/kecil/angka
    # tercampur tidak sesuai urutan A-Z yang wajar dilihat orang), aman untuk skala tamu (<=500)
    items.sort(key=lambda g: (g.get("nama") or "").lower())
    return items

@api.post("/guests")
async def create_guest(body: GuestCreate, user: dict = Depends(get_current_user),
                       property_id: str = Depends(get_active_property)):
    """Tambah data tamu manual (bukan dari booking/check-in) - mis. tamu lama yang mau
    dicatat riwayatnya, atau kontak yang perlu didata sebelum booking pertama."""
    if not body.no_hp and not body.no_identitas:
        raise HTTPException(400, "Isi minimal salah satu: No HP atau No KTP")
    existing = await cari_guest(property_id, body.no_hp, body.no_identitas)
    if existing:
        raise HTTPException(400, f"Tamu dengan No HP/KTP ini sudah ada: {existing['nama']}")
    doc = {
        "id": str(uuid.uuid4()), "nama": body.nama.strip(),
        "no_hp": body.no_hp.strip(), "no_identitas": body.no_identitas.strip(), "kendaraan": body.kendaraan.strip(),
        "total_kunjungan": 0, "total_transaksi": 0, "last_visit": None, "created_at": now_iso(),
        "property_id": property_id,
    }
    await db.guests.insert_one(doc)
    await log_activity(user, "create_guest", f"Tambah data tamu {doc['nama']}")
    doc.pop("_id", None)
    doc.update(diskon_member_untuk_total_kunjungan(0))
    return doc

@api.put("/guests/{guest_id}")
async def update_guest(guest_id: str, body: GuestUpdate, user: dict = Depends(get_current_user),
                       property_id: str = Depends(get_active_property)):
    g = await db.guests.find_one(scoped({"id": guest_id}, property_id))
    if not g:
        raise HTTPException(404, "Data tamu tidak ditemukan")
    updates = {k: v.strip() if isinstance(v, str) else v for k, v in body.model_dump().items() if v is not None}
    no_hp = updates.get("no_hp", g.get("no_hp"))
    no_identitas = updates.get("no_identitas", g.get("no_identitas"))
    if no_hp or no_identitas:
        other = await cari_guest(property_id, no_hp, no_identitas)
        if other and other["id"] != guest_id:
            raise HTTPException(400, f"No HP/KTP ini sudah dipakai tamu lain: {other['nama']}")
    if updates:
        await db.guests.update_one({"id": guest_id}, {"$set": updates})
    await log_activity(user, "update_guest", f"Update data tamu {updates.get('nama', g.get('nama'))}")
    fresh = await db.guests.find_one({"id": guest_id}, {"_id": 0})
    fresh.update(diskon_member_untuk_total_kunjungan(fresh.get("total_kunjungan", 0)))
    return fresh

@api.get("/guests/{guest_id}/history")
async def guest_history(guest_id: str, user: dict = Depends(get_current_user),
                        property_id: str = Depends(get_active_property)):
    items = await db.checkins.find(scoped({"guest_id": guest_id}, property_id), {"_id": 0}).sort("jam_checkin", -1).to_list(500)
    return items


def _recompute_last_visit(riwayat: list) -> Optional[str]:
    tanggal_list = [k["tanggal"] for k in riwayat if k.get("tanggal")]
    return max(tanggal_list) if tanggal_list else None


@api.post("/guests/{guest_id}/kunjungan-manual")
async def tambah_kunjungan_manual(guest_id: str, body: KunjunganManualIn, user: dict = Depends(require_owner),
                                  property_id: str = Depends(get_active_property)):
    """Migrasi riwayat kartu member kertas lama (2026-07-24, permintaan user - supaya tamu
    lama yang sudah punya riwayat di kartu kertas tidak dirugikan/dianggap "kedatangan ke-1"
    lagi begitu pindah ke sistem digital). Owner-only (data ini memengaruhi diskon member
    sungguhan, sama sensitifnya dengan Payroll). Entri ditandai `source: "manual"` supaya
    beda dari riwayat check-in sungguhan (`source: "checkin"`) - cuma entri manual yang
    boleh dihapus lagi kalau salah input."""
    g = await db.guests.find_one(scoped({"id": guest_id}, property_id))
    if not g:
        raise HTTPException(404, "Data tamu tidak ditemukan")
    try:
        datetime.fromisoformat(body.tanggal)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    entry = {
        "id": str(uuid.uuid4()), "tanggal": body.tanggal, "room_nomor": body.room_nomor,
        "catatan": body.catatan, "source": "manual",
        "dicatat_oleh": user["nama"], "dicatat_at": now_iso(),
    }
    riwayat = list(g.get("riwayat_kunjungan") or [])
    riwayat.append(entry)
    await db.guests.update_one({"id": guest_id}, {
        "$push": {"riwayat_kunjungan": entry},
        "$inc": {"total_kunjungan": 1},
        "$set": {"last_visit": _recompute_last_visit(riwayat)},
    })
    await log_activity(user, "kunjungan_manual", f"Tambah kunjungan manual {g['nama']} - {body.tanggal} (migrasi kartu member lama)")
    fresh = await db.guests.find_one({"id": guest_id}, {"_id": 0})
    fresh.update(diskon_member_untuk_total_kunjungan(fresh.get("total_kunjungan", 0)))
    return fresh


@api.delete("/guests/{guest_id}/kunjungan-manual/{entry_id}")
async def hapus_kunjungan_manual(guest_id: str, entry_id: str, user: dict = Depends(require_owner),
                                 property_id: str = Depends(get_active_property)):
    """Cuma entri `source: "manual"` yang bisa dihapus - riwayat dari check-in sungguhan
    tidak boleh dihapus lewat sini (kalau memang salah, itu masalah data check-in aslinya,
    bukan sekadar hapus jejak kunjungan)."""
    g = await db.guests.find_one(scoped({"id": guest_id}, property_id))
    if not g:
        raise HTTPException(404, "Data tamu tidak ditemukan")
    riwayat = list(g.get("riwayat_kunjungan") or [])
    target = next((k for k in riwayat if k.get("id") == entry_id), None)
    if not target:
        raise HTTPException(404, "Entri kunjungan tidak ditemukan")
    if target.get("source") != "manual":
        raise HTTPException(400, "Cuma entri kunjungan manual yang bisa dihapus")
    riwayat = [k for k in riwayat if k.get("id") != entry_id]
    await db.guests.update_one({"id": guest_id}, {
        "$set": {"riwayat_kunjungan": riwayat, "last_visit": _recompute_last_visit(riwayat)},
        "$inc": {"total_kunjungan": -1},
    })
    await log_activity(user, "hapus_kunjungan_manual", f"Hapus kunjungan manual {g['nama']} - {target['tanggal']}")
    fresh = await db.guests.find_one({"id": guest_id}, {"_id": 0})
    fresh.update(diskon_member_untuk_total_kunjungan(fresh.get("total_kunjungan", 0)))
    return fresh

