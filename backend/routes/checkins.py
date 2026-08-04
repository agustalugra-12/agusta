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

    # Tarif dasar (6 jam) WAJIB lunas saat check-in (2026-07-31, keputusan bisnis Agus:
    # "semua payment di lakukan di depan kecuali extend/overtime" - sebelumnya Day Use
    # TIDAK ada pembayaran sama sekali sampai checkout, tamu bisa pergi tanpa bayar).
    # service_fee dihitung dari tarif dasar SAJA di sini (bukan calc_tagihan, yg baru bisa
    # tahu overtime pas checkout) - selisihnya (kalau ada overtime) ditagih terpisah saat
    # checkout, lihat fungsi checkout di bawah.
    base_per_room = []
    for r in rooms:
        tarif_dasar = body.tarif_override if body.tarif_override else r["tarif"]
        base_subtotal = int(tarif_dasar)
        base_service_fee = round(base_subtotal * SERVICE_FEE_PCT)
        base_per_room.append({"tarif_dasar": tarif_dasar, "subtotal": base_subtotal, "service_fee": base_service_fee, "total": base_subtotal + base_service_fee})
    total_base_needed = sum(x["total"] for x in base_per_room)
    total_dibayar = sum(int(p.get("jumlah", 0)) for p in body.pembayaran)
    if total_dibayar < total_base_needed:
        raise HTTPException(400, f"Pembayaran kurang. Tarif dasar Day Use (6 jam{'/kamar' if len(rooms) > 1 else ''}) wajib dibayar lunas saat check-in: Rp{total_base_needed:,}".replace(",", "."))

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
    for i, r in enumerate(rooms):
        base = base_per_room[i]
        # Pembayaran dicatat apa adanya di kamar pertama kalau 1 kamar (kasus umum); utk
        # rombongan >1 kamar dalam 1 transaksi, alokasikan proporsional ke tarif dasar
        # tiap kamar supaya total per-kamar tetap masuk akal di laporan/riwayat, bukan
        # dobel-dicatat di semua kamar.
        if len(rooms) == 1:
            pembayaran_kamar = body.pembayaran
        else:
            share = base["total"] / total_base_needed if total_base_needed else 0
            pembayaran_kamar = [
                {**p, "jumlah": round(int(p.get("jumlah", 0)) * share)} for p in body.pembayaran
            ]
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
            "tarif_dasar": base["tarif_dasar"],
            "jam_checkin": jam_ci_iso,
            "jam_checkout": None,
            "durasi_jam": 0,
            "overtime_jam": 0,
            "biaya_tambahan": 0,
            # (2026-07-31) subtotal/service_fee/total SEKARANG diisi dari tarif dasar yang
            # sudah lunas dibayar di depan (bukan 0 lagi) - checkout nanti menghitung ULANG
            # dari calc_tagihan (termasuk overtime kalau ada) & menagih SELISIHnya saja.
            "subtotal": base["subtotal"], "service_fee": base["service_fee"], "total": base["total"],
            "status": "aktif",
            "catatan": body.catatan,
            "foto_identitas_url": body.foto_identitas_url or "",
            "pembayaran": pembayaran_kamar,
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
        # (2026-07-31) tarif dasar sudah lunas dibayar saat check-in - "sisa" di sini HANYA
        # extend/overtime yang belum dibayar, bukan tagihan penuh lagi.
        sudah_dibayar = sum(int(p.get("jumlah", 0)) for p in c.get("pembayaran", []))
        calc["sisa_dibayar"] = max(0, calc["total"] - sudah_dibayar)
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
    # (2026-07-31, keputusan bisnis Agus) - tarif dasar SUDAH lunas dibayar saat check-in
    # (lihat create_checkin), jadi di checkout cuma tagih SELISIHnya - biasanya = biaya
    # extend/overtime kalau ada, atau Rp0 kalau tamu pulang tepat waktu (tidak perlu bayar
    # apa-apa lagi). `sudah_dibayar` dari pembayaran yang tercatat saat check-in.
    sudah_dibayar = sum(int(p.get("jumlah", 0)) for p in c.get("pembayaran", []))
    sisa_ditagih = max(0, calc["total"] - sudah_dibayar)
    total_bayar_baru = sum(int(p.get("jumlah", 0)) for p in body.pembayaran)
    if total_bayar_baru < sisa_ditagih:
        raise HTTPException(400, f"Pembayaran extend/overtime kurang. Diperlukan Rp{sisa_ditagih:,}".replace(",", "."))
    pembayaran_final = list(c.get("pembayaran", [])) + list(body.pembayaran)
    updates = {
        "jam_checkout": now.isoformat(),
        "durasi_jam": calc["durasi_jam"],
        "overtime_jam": calc["overtime_jam"],
        "biaya_tambahan": calc["biaya_tambahan"],
        "subtotal": calc["subtotal"],
        "service_fee": calc["service_fee"],
        "total": calc["total"],
        "pembayaran": pembayaran_final,
        "status": "selesai",
        "petugas_checkout": user["nama"],
        "petugas_checkout_id": user["id"],
        "catatan_checkout": body.catatan,
    }
    await db.checkins.update_one({"id": checkin_id}, {"$set": updates})
    await db.rooms.update_one({"id": c["room_id"]}, {"$set": {"status": "perlu_dibersihkan", "info": {}}})
    # (2026-08-02, bug KRITIS nyata ditemukan - tamu Vina di kamar 5, RIAN RIAN tidak bisa
    # dipindah ke kamar 5 walau tamu sebelumnya sudah checkout & kamar sudah dibersihkan)
    # checkout ini TIDAK PERNAH menyentuh `db.bookings` sama sekali - booking asal (kalau
    # checkin ini dibuat dari booking via checkin_from_booking) tetap selamanya berstatus
    # "checked_in", yang termasuk status AKTIF/blocking di check_room_available &
    # move_room. Akibatnya kamar yang fisiknya sudah kosong & bersih tetap "terkunci" oleh
    # booking lama sampai jam_selesai terjadwalnya lewat. "checked_out" SENGAJA bukan bagian
    # dari BOOKING_AKTIF_STATUS/BOOKING_TERKONFIRMASI_STATUS/ACTIVE_BOOKING_STATUSES manapun
    # (semua daftar itu allow-list, bukan exclude-list) - jadi begitu status ini di-set,
    # booking otomatis berhenti dihitung "aktif"/"terkonfirmasi" di semua tempat itu tanpa
    # perlu ubah daftarnya. Laporan okupansi (laporan_analitik.py) tidak terdampak - untuk
    # Day Use dia sudah punya sumber independen dari db.checkins (jam_checkin/jam_checkout
    # asli), jadi tetap akurat lepas dari status booking ini.
    if c.get("from_booking_id"):
        await db.bookings.update_one({"id": c["from_booking_id"]}, {"$set": {
            "status": "checked_out", "checked_out_at": now.isoformat(), "checked_out_by": user["nama"],
        }})
    # housekeeping log
    await db.housekeeping_log.insert_one({
        "id": str(uuid.uuid4()),
        "property_id": property_id,
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
    await auto_posting("pemasukan", total_bayar_baru, "Check-out Day Use", f"Kamar {c['room_nomor']} - {c['nama_tamu']}", property_id)
    res = {**c, **updates}
    res.pop("_id", None)
    return res

# ---- Guests ----
@api.get("/guests/stats")
async def guests_stats(user: dict = Depends(get_current_user),
                       property_id: str = Depends(get_active_property)):
    """Dashboard Member (Member Intelligence Center, 2026-07-31) - KPI agregat di atas
    db.guests untuk halaman Data Tamu. HARUS didaftarkan sebelum "/guests" polos di
    bawah supaya tidak ketiban rute lain (meski di sini aman karena path-nya beda)."""
    guests = await db.guests.find(scoped({}, property_id), {"_id": 0}).to_list(5000)
    total_member = len(guests)
    repeat_guest = sum(1 for g in guests if (g.get("total_kunjungan") or 0) >= 2)
    revenue_member = sum(int(g.get("total_transaksi") or 0) for g in guests)
    reward_aktif = sum(1 for g in guests if diskon_member_untuk_total_kunjungan(g.get("total_kunjungan", 0)).get("diskon_persen", 0) > 0)
    batas_90_hari = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
    tidak_datang_90_hari = sum(1 for g in guests if g.get("last_visit") and g["last_visit"] < batas_90_hari)
    return {
        "total_member": total_member,
        "repeat_guest": repeat_guest,
        "revenue_member": revenue_member,
        "reward_aktif": reward_aktif,
        "tidak_datang_90_hari": tidak_datang_90_hari,
    }


@api.get("/guests")
async def list_guests(q: Optional[str] = None, user: dict = Depends(get_current_user),
                      property_id: str = Depends(get_active_property)):
    query: Dict[str, Any] = {}
    if q:
        # re.escape() (2026-07-27, audit keamanan) - cegah ReDoS dari pola regex jahat, cari
        # sbg teks harfiah.
        q_escaped = re.escape(q)
        query = {"$or": [
            {"nama": {"$regex": q_escaped, "$options": "i"}},
            {"no_hp": {"$regex": q_escaped, "$options": "i"}},
            {"no_identitas": {"$regex": q_escaped, "$options": "i"}},
        ]}
    items = await db.guests.find(scoped(query, property_id), {"_id": 0}).to_list(500)
    # Rata-rata total_transaksi SELURUH tamu di properti (bukan cuma hasil filter q) -
    # dipakai komponen monetary CRM Score, supaya skor tetap stabil terlepas dari
    # pencarian yang sedang aktif.
    semua_transaksi = await db.guests.find(scoped({}, property_id), {"total_transaksi": 1, "_id": 0}).to_list(5000)
    nilai_transaksi = [g.get("total_transaksi", 0) for g in semua_transaksi]
    avg_transaksi = sum(nilai_transaksi) / len(nilai_transaksi) if nilai_transaksi else 0
    for it in items:
        it.update(diskon_member_untuk_total_kunjungan(it.get("total_kunjungan", 0)))
        crm = hitung_crm_score(it.get("total_kunjungan", 0), it.get("last_visit"), it.get("total_transaksi", 0), avg_transaksi)
        it["crm_score"] = crm["skor"]
        it["crm_label"] = crm["label"]
        it["peluang_kembali"] = hitung_peluang_kembali(it.get("riwayat_kunjungan"))
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
        "tanggal_lahir": body.tanggal_lahir.strip(),
        "total_kunjungan": 0, "total_transaksi": 0, "last_visit": None, "created_at": now_iso(),
        "reward_wallet": [],
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


_HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


@api.get("/guests/{guest_id}/timeline")
async def guest_timeline(guest_id: str, user: dict = Depends(get_current_user),
                         property_id: str = Depends(get_active_property)):
    """Guest Timeline (Member Intelligence Center, 2026-07-31) - riwayat kronologis
    terpadu 1 tamu: booking dibuat -> dibayar -> check-in -> check-out -> kunjungan
    manual (migrasi kartu lama). `db.bookings` TIDAK punya field `guest_id` (cuma
    no_hp/no_identitas), jadi dicocokkan lewat phone_variants() (varian 62xxx/0xxx,
    lihat core.py) + no_identitas persis - sama seperti cara pembatalan/self-service
    tamu memverifikasi kepemilikan booking. `db.checkins` sudah punya `guest_id`
    langsung. Sekalian menghitung "Preferensi" - MURNI statistik deskriptif dari
    histori asli (tipe kamar favorit, hari biasa datang, rata-rata malam menginap),
    BUKAN prediksi - sengaja tidak membangun skor/prediksi "peluang kembali" dulu
    karena volume data tamu saat ini masih terlalu kecil untuk itu jujur/berguna."""
    g = await db.guests.find_one(scoped({"id": guest_id}, property_id), {"_id": 0})
    if not g:
        raise HTTPException(404, "Data tamu tidak ditemukan")

    or_clauses = []
    if g.get("no_hp"):
        or_clauses.append({"no_hp": {"$in": list(phone_variants(g["no_hp"]))}})
    if g.get("no_identitas"):
        or_clauses.append({"no_identitas": g["no_identitas"]})
    bookings = []
    if or_clauses:
        bookings = await db.bookings.find(scoped({"$or": or_clauses}, property_id), {"_id": 0}).to_list(500)
    checkins = await db.checkins.find(scoped({"guest_id": guest_id}, property_id), {"_id": 0}).to_list(500)

    events = []
    for b in bookings:
        label_kamar = f"kamar {b.get('room_nomor', '-')}"
        if b.get("created_at"):
            events.append({
                "waktu": b["created_at"], "jenis": "booking_dibuat",
                "label": f"Booking {b.get('tipe', '')} dibuat - {label_kamar}",
                "ref_id": b.get("id"),
            })
        if b.get("paid_at"):
            events.append({
                "waktu": b["paid_at"], "jenis": "pembayaran",
                "label": f"Pembayaran diterima - Rp{int(b.get('total', 0)):,}".replace(",", "."),
                "ref_id": b.get("id"),
            })
        # Check-in Menginap TIDAK pernah bikin dokumen db.checkins (itu cuma untuk Day
        # Use, lihat routes/bookings.py checkin_from_booking) - satu-satunya jejak
        # check-in Menginap yang ada cuma checked_in_at di booking ini sendiri, jadi
        # diambil dari sini, bukan dari koleksi checkins.
        if b.get("tipe") == "menginap" and b.get("checked_in_at"):
            events.append({
                "waktu": b["checked_in_at"], "jenis": "checkin",
                "label": f"Check-in {label_kamar} (menginap)",
                "ref_id": b.get("id"),
            })
    for c in checkins:
        label_kamar = f"kamar {c.get('room_nomor', '-')}"
        if c.get("jam_checkin"):
            events.append({
                "waktu": c["jam_checkin"], "jenis": "checkin",
                "label": f"Check-in {label_kamar} ({c.get('room_tipe', '')})",
                "ref_id": c.get("id"),
            })
        if c.get("jam_checkout"):
            events.append({
                "waktu": c["jam_checkout"], "jenis": "checkout",
                "label": f"Check-out {label_kamar} - Rp{int(c.get('total', 0)):,}".replace(",", "."),
                "ref_id": c.get("id"),
            })
    for k in (g.get("riwayat_kunjungan") or []):
        events.append({
            "waktu": k.get("tanggal"), "jenis": "kunjungan_manual",
            "label": f"Kunjungan tercatat (migrasi kartu lama) - kamar {k.get('room_nomor', '-')}",
            "ref_id": k.get("id"),
        })

    events = [e for e in events if e.get("waktu")]
    events.sort(key=lambda e: e["waktu"], reverse=True)

    tipe_counter: Dict[str, int] = {}
    hari_counter: Dict[str, int] = {}
    durasi_malam: List[int] = []
    for c in checkins:
        # db.checkins isinya SELALU Day Use (menginap tidak pernah insert ke sini) -
        # jadi cukup hitung tipe kamar & hari kedatangan, tanpa durasi menginap.
        tipe_kamar = c.get("room_tipe")
        if tipe_kamar:
            tipe_counter[tipe_kamar] = tipe_counter.get(tipe_kamar, 0) + 1
        dt_in = _parse_dt(c.get("jam_checkin"))
        if dt_in:
            hari = _HARI_ID[dt_in.weekday()]
            hari_counter[hari] = hari_counter.get(hari, 0) + 1
    for b in bookings:
        if b.get("tipe") != "menginap":
            continue
        tipe_kamar = b.get("room_tipe")
        if tipe_kamar:
            tipe_counter[tipe_kamar] = tipe_counter.get(tipe_kamar, 0) + 1
        dt_mulai = _parse_dt(b.get("jam_mulai"))
        if dt_mulai:
            hari = _HARI_ID[dt_mulai.weekday()]
            hari_counter[hari] = hari_counter.get(hari, 0) + 1
        dt_selesai = _parse_dt(b.get("jam_selesai"))
        if dt_mulai and dt_selesai and dt_selesai > dt_mulai:
            durasi_malam.append(max(1, round((dt_selesai - dt_mulai).total_seconds() / 86400)))

    preferensi = {
        "tipe_kamar_favorit": max(tipe_counter, key=tipe_counter.get) if tipe_counter else None,
        "hari_biasa_datang": max(hari_counter, key=hari_counter.get) if hari_counter else None,
        "rata_rata_malam_menginap": round(sum(durasi_malam) / len(durasi_malam), 1) if durasi_malam else None,
    }

    # Reward Wallet (Member Intelligence, 2026-07-31) - diskon member SAAT INI dihitung
    # ulang (bukan disimpan) dari total_kunjungan (siklus 10, lihat DISKON_MEMBER_TABLE) -
    # ditampilkan sebagai 1 reward "aktif" di sini kalau > 0%, DIGABUNG dengan voucher
    # yang benar-benar tersimpan di db (mis. voucher ulang tahun) di `reward_wallet`.
    member_diskon = diskon_member_untuk_total_kunjungan(g.get("total_kunjungan", 0))
    return {"events": events, "preferensi": preferensi, "member_diskon_aktif": member_diskon,
            "reward_wallet": g.get("reward_wallet", []),
            "peluang_kembali": hitung_peluang_kembali(g.get("riwayat_kunjungan"))}


def _recompute_last_visit(riwayat: list) -> Optional[str]:
    tanggal_list = [k["tanggal"] for k in riwayat if k.get("tanggal")]
    return max(tanggal_list) if tanggal_list else None


@api.post("/guests/{guest_id}/reward-wallet/voucher-ulang-tahun")
async def beri_voucher_ulang_tahun(guest_id: str, user: dict = Depends(get_current_user),
                                   property_id: str = Depends(get_active_property)):
    """Hadiah ulang tahun (keputusan bisnis Agus, 2026-07-31): "setiap yang ulang tahun
    mendapat vocer menginap gratis 1x dan 1 kamar" - voucher DISIMPAN di reward_wallet
    tamu (bukan otomatis dipotong dari harga), staf yang menerapkannya manual saat tamu
    booking/check-in (isi tarif_override=0 lalu tandai voucher ini "terpakai" di sini).
    Diberi lewat tombol staf di Dashboard (bukan otomatis) & dijaga 1x per tahun kalender
    supaya tidak dobel-klik."""
    g = await db.guests.find_one(scoped({"id": guest_id}, property_id))
    if not g:
        raise HTTPException(404, "Data tamu tidak ditemukan")
    tahun_ini = now_iso()[:4]
    wallet = list(g.get("reward_wallet") or [])
    sudah_ada = any(r.get("jenis") == "voucher_ulang_tahun" and r.get("tahun") == tahun_ini for r in wallet)
    if sudah_ada:
        raise HTTPException(400, f"Voucher ulang tahun {tahun_ini} untuk tamu ini sudah pernah diberikan")
    entry = {
        "id": str(uuid.uuid4()), "jenis": "voucher_ulang_tahun",
        "label": "Voucher Menginap Gratis (Ulang Tahun)",
        "deskripsi": "Gratis menginap 1x, 1 kamar standard",
        "tahun": tahun_ini, "status": "aktif",
        "diberikan_oleh": user["nama"], "created_at": now_iso(),
        "used_at": None, "catatan_pakai": "",
    }
    await db.guests.update_one({"id": guest_id}, {"$push": {"reward_wallet": entry}})
    await log_activity(user, "beri_voucher_ulang_tahun", f"Voucher ulang tahun {tahun_ini} untuk {g['nama']}")
    return entry


@api.post("/guests/{guest_id}/reward-wallet/{reward_id}/pakai")
async def pakai_reward_wallet(guest_id: str, reward_id: str, body: RewardPakaiIn,
                              user: dict = Depends(get_current_user),
                              property_id: str = Depends(get_active_property)):
    """Tandai 1 reward di wallet sebagai sudah dipakai (staf menerapkan diskon/gratisnya
    manual saat booking/check-in - lihat catatan di endpoint pemberian voucher di atas,
    fungsi ini murni pencatatan supaya reward tidak terlihat "masih bisa dipakai" lagi)."""
    g = await db.guests.find_one(scoped({"id": guest_id}, property_id))
    if not g:
        raise HTTPException(404, "Data tamu tidak ditemukan")
    wallet = list(g.get("reward_wallet") or [])
    target = next((r for r in wallet if r.get("id") == reward_id), None)
    if not target:
        raise HTTPException(404, "Reward tidak ditemukan")
    if target.get("status") == "terpakai":
        raise HTTPException(400, "Reward ini sudah ditandai terpakai sebelumnya")
    await db.guests.update_one(
        {"id": guest_id, "reward_wallet.id": reward_id},
        {"$set": {"reward_wallet.$.status": "terpakai", "reward_wallet.$.used_at": now_iso(),
                  "reward_wallet.$.catatan_pakai": body.catatan, "reward_wallet.$.dipakai_oleh": user["nama"]}}
    )
    await log_activity(user, "pakai_reward_wallet", f"Reward '{target.get('label')}' dipakai untuk {g['nama']}")
    return {"ok": True}


@api.get("/guests/ulang-tahun-hari-ini")
async def guests_ulang_tahun_hari_ini(user: dict = Depends(get_current_user),
                                      property_id: str = Depends(get_active_property)):
    """Notif Dashboard utama (Member Intelligence, 2026-07-31) - daftar tamu yang hari
    ini ulang tahun (cocok bulan+tanggal di `tanggal_lahir`). Dipakai utk tombol "Kirim
    Pesan" (WA manual via waLink, TIDAK ada broadcast otomatis - risiko WA banned per
    keputusan Agus) & "Kasih Voucher"."""
    hari_ini = now_iso()
    guests = await db.guests.find(scoped({"tanggal_lahir": {"$nin": ["", None]}}, property_id), {"_id": 0}).to_list(5000)
    hasil = [g for g in guests if is_ulang_tahun_hari_ini(g.get("tanggal_lahir"), hari_ini)]
    for g in hasil:
        tahun_ini = hari_ini[:4]
        g["sudah_dapat_voucher_tahun_ini"] = any(
            r.get("jenis") == "voucher_ulang_tahun" and r.get("tahun") == tahun_ini for r in (g.get("reward_wallet") or [])
        )
    return hasil


@api.get("/dashboard/tugas-harian")
async def tugas_harian(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    """AI Daily Assistant (Member Intelligence Center, 2026-07-31) - daftar tugas
    resepsionis hari ini. SENGAJA deterministik (query DB biasa), BUKAN teks yang
    di-generate GPT - lebih murah, tidak ada risiko halusinasi, dan datanya sendiri
    sudah cukup jelas tanpa perlu dibungkus prosa AI. "AI" di sini maksudnya asisten
    otomatis yang menyiapkan daftar, bukan pemanggilan model bahasa."""
    hari_ini = now_iso()[:10]
    batas_90_hari = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()

    kedatangan_menginap = await db.bookings.find(scoped({
        "tipe": "menginap", "status": {"$in": ["aktif", "booking_paid"]},
        "jam_mulai": {"$regex": f"^{hari_ini}"},
    }, property_id), {"_id": 0}).to_list(200)

    keberangkatan_menginap = await db.bookings.find(scoped({
        "tipe": "menginap", "status": "checked_in",
        "jam_selesai": {"$regex": f"^{hari_ini}"},
    }, property_id), {"_id": 0}).to_list(200)

    day_use_berlangsung = await db.checkins.find(scoped({"status": "aktif"}, property_id), {"_id": 0}).to_list(200)

    # Riwayat checkout SUDAH selesai hari ini (2026-08-04, permintaan Agus - kasus kamar
    # menginap checkout lalu dipakai Day Use di hari yang sama: begitu checkout
    # diproses, tamu itu hilang dari daftar "Keberangkatan"/"Day Use Berlangsung" di atas
    # (keduanya cuma daftar tugas YANG BELUM selesai) - Agus mau riwayat checkout tetap
    # kelihatan di dashboard, bukan menghilang begitu saja. Dicari dari status akhirnya
    # (checked_out/selesai) + timestamp checkout HARI INI, independen dari daftar di atas
    # jadi 1 tamu yang menginap lalu Day Use di kamar sama hari ini akan muncul 2x di
    # sini (checkout menginap-nya, lalu nanti checkout Day Use-nya) - itu memang benar,
    # dua transaksi checkout yang berbeda.
    keberangkatan_menginap_selesai = await db.bookings.find(scoped({
        "tipe": "menginap", "status": "checked_out",
        "checked_out_at": {"$regex": f"^{hari_ini}"},
    }, property_id), {"_id": 0}).sort("checked_out_at", -1).to_list(200)

    day_use_selesai = await db.checkins.find(scoped({
        "status": "selesai",
        "jam_checkout": {"$regex": f"^{hari_ini}"},
    }, property_id), {"_id": 0}).sort("jam_checkout", -1).to_list(200)

    tamu_semua = await db.guests.find(scoped({}, property_id), {"_id": 0}).to_list(5000)
    tamu_follow_up = [
        g for g in tamu_semua
        if (g.get("total_kunjungan") or 0) >= 2 and g.get("last_visit") and g["last_visit"] < batas_90_hari
    ]
    tamu_follow_up.sort(key=lambda g: g.get("last_visit") or "")
    for g in tamu_follow_up:
        g.update(diskon_member_untuk_total_kunjungan(g.get("total_kunjungan", 0)))
        g["peluang_kembali"] = hitung_peluang_kembali(g.get("riwayat_kunjungan"))

    ulang_tahun = [g for g in tamu_semua if is_ulang_tahun_hari_ini(g.get("tanggal_lahir"), hari_ini)]

    return {
        "kedatangan_menginap_hari_ini": kedatangan_menginap,
        "keberangkatan_menginap_hari_ini": keberangkatan_menginap,
        "day_use_sedang_berlangsung": day_use_berlangsung,
        "keberangkatan_menginap_selesai_hari_ini": keberangkatan_menginap_selesai,
        "day_use_selesai_hari_ini": day_use_selesai,
        "tamu_perlu_follow_up": tamu_follow_up[:20],
        "ulang_tahun_hari_ini": ulang_tahun,
    }


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

