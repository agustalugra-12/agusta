from core import *

# ---- Laporan & Analitik (Fase 3) ----
# Beda dari /reports/* (P&L operasional Fase 1, sumber: checkins/kasir/expenses walk-in):
# fokus di sini pendapatan & performa booking multi-saluran (online/ota/whatsapp) dari
# collection `bookings`, plus tren okupansi gabungan (bookings + checkins walk-in).

SALURAN_KEYS = ["ota", "website", "whatsapp"]
SOURCE_TO_SALURAN = {"online": "website", "ota": "ota", "whatsapp": "whatsapp"}


@api.get("/laporan-analitik/pendapatan")
async def laporan_pendapatan(from_date: str = Query(...), to_date: str = Query(...),
                              user: dict = Depends(get_current_user)):
    """Pendapatan harian dari booking multi-saluran yang sudah dibayar (payment_status=paid),
    dikelompokkan per tanggal paid_at. Tidak termasuk pendapatan walk-in (sudah ada di /reports/daily)."""
    start = from_date
    end = to_date + "T23:59:59"
    bks = await db.bookings.find({
        "payment_status": "paid",
        "paid_at": {"$gte": start, "$lte": end},
        "ota_harga_dikonfirmasi": {"$ne": False},
    }, {"_id": 0, "total": 1, "paid_at": 1}).to_list(5000)
    by_day: Dict[str, int] = {}
    for b in bks:
        d = (b.get("paid_at") or "")[:10]
        by_day[d] = by_day.get(d, 0) + int(b.get("total") or 0)
    return [{"tanggal": d, "pendapatan": by_day[d]} for d in sorted(by_day.keys())]


@api.get("/laporan-analitik/performa-saluran")
async def laporan_performa_saluran(channel: str = Query("Semua"),
                                    user: dict = Depends(get_current_user)):
    """Jumlah booking & pendapatan (paid) per saluran (ota/website/whatsapp), lifetime.
    channel: 'Semua' atau salah satu key saluran untuk filter satu saja."""
    keys = SALURAN_KEYS if channel == "Semua" else [channel]
    sources = [src for src, key in SOURCE_TO_SALURAN.items() if key in keys]
    bks = await db.bookings.find({
        "source": {"$in": sources},
        "payment_status": "paid",
        "ota_harga_dikonfirmasi": {"$ne": False},
    }, {"_id": 0, "source": 1, "total": 1}).to_list(10000)
    agg = {k: {"booking": 0, "pendapatan": 0} for k in keys}
    for b in bks:
        k = SOURCE_TO_SALURAN.get(b.get("source"))
        if k in agg:
            agg[k]["booking"] += 1
            agg[k]["pendapatan"] += int(b.get("total") or 0)
    return [{"key": k, **agg[k]} for k in keys]


@api.get("/laporan-analitik/tren-okupansi")
async def laporan_tren_okupansi(from_date: str = Query(...), to_date: str = Query(...),
                                 user: dict = Depends(get_current_user)):
    """Okupansi harian (%) = jumlah kamar unik terisi hari itu / total kamar.
    Gabungan booking multi-saluran (bookings, status aktif/booking_paid) + walk-in (checkins)."""
    total_rooms = await db.rooms.count_documents({})
    d_from = datetime.fromisoformat(from_date).replace(hour=0, minute=0, second=0, microsecond=0)
    d_to = datetime.fromisoformat(to_date).replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = d_from.isoformat()
    range_end = (d_to + timedelta(days=1)).isoformat()

    bks = await db.bookings.find({
        "status": {"$in": ["aktif", "booking_paid"]},
        "jam_mulai": {"$lt": range_end}, "jam_selesai": {"$gt": range_start},
    }, {"_id": 0, "room_nomor": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(5000)
    cis = await db.checkins.find({
        "jam_checkin": {"$lt": range_end},
        "$or": [{"jam_checkout": {"$gt": range_start}}, {"status": "aktif"}],
    }, {"_id": 0, "room_nomor": 1, "jam_checkin": 1, "jam_checkout": 1}).to_list(5000)

    stays = [(b["room_nomor"], b["jam_mulai"], b.get("jam_selesai") or range_end) for b in bks]
    stays += [(c["room_nomor"], c["jam_checkin"], c.get("jam_checkout") or range_end) for c in cis]

    result = []
    n_days = (d_to - d_from).days + 1
    for i in range(max(1, n_days)):
        day = d_from + timedelta(days=i)
        day_start = day.isoformat()
        day_end = (day + timedelta(days=1)).isoformat()
        occupied = {room for room, mulai, selesai in stays if mulai < day_end and selesai > day_start}
        pct = round(len(occupied) / total_rooms * 100) if total_rooms else 0
        result.append({"tanggal": day.date().isoformat(), "okupansi": min(100, pct)})
    return result
