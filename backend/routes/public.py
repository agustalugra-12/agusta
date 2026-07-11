from core import *
from reservation_service import check_room_available, create_reservation

@api.get("/public/rooms-catalog")
async def public_rooms_catalog():
    """Katalog kamar untuk halaman publik. Mengelompokkan berdasarkan tipe.
    Tidak mengekspos field internal seperti info / status detail.
    """
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    rooms.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    grouped: Dict[str, Any] = {}
    for r in rooms:
        t = r["tipe"]
        if t not in grouped:
            grouped[t] = {
                "tipe": t,
                "tarif": r["tarif"],
                "fasilitas": [
                    "AC", "Wi-Fi gratis", "TV LED", "Kamar mandi dalam",
                    "Air panas", "Handuk & toiletries",
                ] + (["Cottage Style", "Area Outdoor"] if t == "Cottage" else []),
                "rooms": [],
            }
        grouped[t]["rooms"].append({"id": r["id"], "nomor": r["nomor"]})
    return list(grouped.values())

@api.get("/public/availability")
async def public_availability(tanggal: str, tipe: Optional[str] = None):
    """List kamar tersedia pada tanggal tertentu (halaman publik).
    Untuk tanggal MASA DEPAN, status realtime kamar (day_use/menginap/perlu_dibersihkan) TIDAK relevan
    karena akan kembali kosong sebelum tanggal tersebut. Hanya `maintenance` (long-term) yang di-exclude.
    Filter utama: tidak ada booking_pending/booking_paid/aktif yang overlap dengan tanggal target.
    """
    try:
        d = datetime.fromisoformat(tanggal)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    d_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    d_end = d_start + timedelta(days=1)
    # Untuk hari INI, kamar yang sedang dipakai (day_use/menginap/perlu_dibersihkan) tidak tersedia.
    # Untuk hari LAIN (masa depan), hanya 'maintenance' yang dikecualikan.
    today_local = datetime.now().strftime("%Y-%m-%d")
    is_today = tanggal == today_local
    q: Dict[str, Any] = {}
    if tipe:
        q["tipe"] = tipe
    if is_today:
        q["status"] = "kosong"
    else:
        q["status"] = {"$ne": "maintenance"}
    rooms = await db.rooms.find(q, {"_id": 0}).to_list(500)
    # Filter rooms yang punya booking overlap di tanggal tsb
    out = []
    for r in rooms:
        bk = await db.bookings.find_one({
            "room_id": r["id"],
            "status": {"$in": ["aktif", "booking_paid", "booking_pending"]},
            "jam_mulai": {"$lt": d_end.isoformat()},
            "jam_selesai": {"$gt": d_start.isoformat()},
        })
        if not bk:
            out.append({"id": r["id"], "nomor": r["nomor"], "tipe": r["tipe"], "tarif": r["tarif"]})
    out.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    return {"tanggal": tanggal, "tipe": tipe, "rooms": out}

@api.post("/public/bookings")
async def public_create_booking(body: PublicBookingCreate):
    """Booking publik (tanpa login). Membuat booking dengan status 'booking_pending'.
    Tarif = tarif kamar + 3% service fee. Wajib bayar (DP 50% min) via Xendit (Fase C).
    Sementara Xendit belum ada, booking tetap berstatus pending sampai resepsionis approve.
    """
    # Validasi email wajib (untuk kirim bukti pembayaran)
    email = (body.email or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Email wajib diisi dengan format yang valid (untuk menerima bukti pembayaran)")
    # Parse tanggal + jam check-in (WIB +07:00)
    try:
        local_in = datetime.fromisoformat(f"{body.tanggal}T{body.jam_checkin}:00+07:00")
    except Exception:
        raise HTTPException(400, "Format tanggal/jam tidak valid")
    start = local_in.astimezone(timezone.utc)
    end = start + timedelta(hours=6)  # day use 6 jam default
    data = {
        "room_id": body.room_id,
        "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
        "email": email,
        "no_identitas": body.no_identitas, "kendaraan": body.kendaraan,
        "jumlah_tamu": body.jumlah_tamu, "extra_bed_qty": body.extra_bed_qty,
        "jam_mulai": start, "jam_selesai": end,
        "catatan": body.catatan,
        "created_by": body.nama_tamu,
    }
    return await create_reservation(data, source="online")

@api.get("/public/bookings/{bid}")
async def public_get_booking(bid: str):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    # batasi field yang dikembalikan ke publik
    safe = {k: b.get(k) for k in [
        "id", "kode", "room_nomor", "room_tipe", "tipe", "nama_tamu", "no_hp", "email",
        "jumlah_tamu", "extra_bed_qty", "jam_mulai", "jam_selesai", "status", "payment_status",
        "subtotal", "service_fee", "total", "dp_min", "invoice_id",
    ]}
    return safe
