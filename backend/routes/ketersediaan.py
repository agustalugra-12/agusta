from core import *

# Status booking yang dianggap menempati kamar (dipakai juga di routes/bookings.py availability check).
ACTIVE_BOOKING_STATUSES = ["aktif", "booking_paid", "booking_pending"]

# Tahap 2 Modul Reservasi (2026-07-17): booking Menginap dari Booking Request yang masih
# menunggu input/sinkron manual ke PMS RedDoorz TETAP memblokir slotnya (check_room_available
# tidak menyaring sync_status sama sekali — anti-overbooking tidak berubah), tapi TIDAK
# ditampilkan sebagai tamu terkonfirmasi di Kalender Ketersediaan sampai email RedDoorz
# cocok (lihat backend/routes/otomasi_email.py). Kamar jadi terlihat "tersedia" di kalender
# padahal sudah terpakai — staf yang coba booking ulang tetap akan ditolak check_room_available,
# jadi tidak berisiko double-booking, cuma tampilan sementara belum mencerminkan status penuh.
SYNC_STATUS_BELUM_CONFIRMED = ["waiting_reddoorz_input", "waiting_reddoorz_sync"]

# Ambang batas stok menipis: tipe kamar dianggap menipis jika sisa tersedia <= 20% dari total.
LOW_STOCK_THRESHOLD_PCT = 20


def _occupies_date(start: datetime, end: datetime, day) -> bool:
    """Tanggal kalender `day` dianggap terisi oleh booking [start, end) kalau ada di rentang
    [checkin_date, checkout_date) — hari CHECK-OUT TIDAK dihitung terisi (tamu sudah checkout
    sebelum hari itu dianggap kosong lagi untuk kalender ketersediaan), KECUALI booking day-use
    yang check-in/check-out di hari yang sama (harus tetap terhitung terisi hari itu).

    Bug ditemukan 2026-07-12: sebelumnya dipakai overlap TIMESTAMP mentah (b_end >= day_start),
    yang membuat hari check-out booking menginap selalu ikut terhitung terisi (mis. checkin
    tanggal 20/checkout tanggal 21 tampil terisi di tanggal 20 DAN 21, padahal cuma 1 malam
    yang seharusnya terisi di tanggal 20 saja).
    """
    start_date, end_date = start.date(), end.date()
    if start_date == end_date:
        return day == start_date
    return start_date <= day < end_date


async def _room_status_breakdown():
    """Ambil status kamar sekali, dipakai bareng oleh ringkasan/status-tipe/notifikasi/live
    supaya polling berkala tidak query db.rooms berkali-kali per request.
    'Tersedia' = kamar berstatus kosong; selain itu (day_use, menginap, perlu_dibersihkan,
    maintenance) dihitung sebagai terisi karena tidak siap dibooking langsung.
    """
    rooms = await db.rooms.find({}, {"_id": 0, "tipe": 1, "status": 1}).to_list(500)
    by_tipe: Dict[str, Dict[str, int]] = {}
    for r in rooms:
        tipe = r.get("tipe", "-")
        entry = by_tipe.setdefault(tipe, {"total": 0, "tersedia": 0})
        entry["total"] += 1
        if r.get("status") == "kosong":
            entry["tersedia"] += 1
    return rooms, by_tipe


def _ringkasan_from_rooms(rooms: list) -> dict:
    total = len(rooms)
    tersedia = sum(1 for r in rooms if r.get("status") == "kosong")
    terisi = total - tersedia
    okupansi_pct = round((terisi / total) * 100) if total else 0
    return {"total_kamar": total, "tersedia": tersedia, "terisi": terisi, "okupansi_pct": okupansi_pct}


def _status_tipe_from_breakdown(by_tipe: Dict[str, Dict[str, int]]) -> list:
    return [
        {"tipe": tipe, "total": v["total"], "tersedia": v["tersedia"], "terisi": v["total"] - v["tersedia"]}
        for tipe, v in sorted(by_tipe.items())
    ]


def _notifikasi_from_breakdown(by_tipe: Dict[str, Dict[str, int]]) -> list:
    notifications = []
    for tipe, v in sorted(by_tipe.items()):
        if v["total"] == 0:
            continue
        if v["tersedia"] == 0:
            notifications.append({"level": "error", "text": f"Kamar {tipe} habis — tidak ada kamar tersedia saat ini."})
        elif (v["tersedia"] / v["total"]) * 100 <= LOW_STOCK_THRESHOLD_PCT:
            notifications.append({"level": "warning", "text": f"Stok kamar {tipe} menipis — hanya {v['tersedia']} dari {v['total']} kamar tersedia."})
    return notifications


# ---- Dasbor Ketersediaan ----
@api.get("/ketersediaan/ringkasan-hari-ini")
async def ringkasan_hari_ini(user: dict = Depends(get_current_user)):
    """Ringkasan okupansi hari ini: total kamar tersedia, terisi, dan persentase okupansi."""
    rooms, _ = await _room_status_breakdown()
    return _ringkasan_from_rooms(rooms)


@api.get("/ketersediaan/kalender-bulanan")
async def kalender_bulanan(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: dict = Depends(get_current_user),
):
    """Okupansi per hari untuk satu bulan (Kalender Ketersediaan). Dihitung dari booking
    aktif/pending/paid yang overlap tiap tanggal — bukan status kamar hari-ini (yang hanya
    relevan untuk hari ini).
    """
    total_rooms = await db.rooms.count_documents({})
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)

    bookings = await db.bookings.find({
        "status": {"$in": ACTIVE_BOOKING_STATUSES},
        "sync_status": {"$nin": SYNC_STATUS_BELUM_CONFIRMED},
        "jam_mulai": {"$lt": month_end.isoformat()},
        "jam_selesai": {"$gte": month_start.isoformat()},
    }, {"_id": 0, "room_id": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(2000)

    parsed = [(b["room_id"], parse_iso(b["jam_mulai"], "jam_mulai"), parse_iso(b["jam_selesai"], "jam_selesai")) for b in bookings if b.get("jam_selesai")]

    days = []
    n_days = (month_end - month_start).days
    for i in range(n_days):
        day_start = month_start + timedelta(days=i)
        occupied_rooms = {room_id for room_id, b_start, b_end in parsed if _occupies_date(b_start, b_end, day_start.date())}
        terisi = len(occupied_rooms)
        tersedia = max(0, total_rooms - terisi)
        okupansi_pct = round((terisi / total_rooms) * 100) if total_rooms else 0
        days.append({
            "tanggal": day_start.date().isoformat(),
            "terisi": terisi,
            "tersedia": tersedia,
            "okupansi_pct": okupansi_pct,
        })

    return {"year": year, "month": month, "days": days}


@api.get("/ketersediaan/hari")
async def ketersediaan_hari(
    tanggal: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """Ketersediaan satu tanggal tertentu, dipecah per tipe kamar — dipakai dialog detail hari
    di Kalender Ketersediaan. Logika overlap booking sama dengan kalender_bulanan, tapi
    dikelompokkan per tipe kamar bukan agregat total.
    """
    try:
        day_start = datetime.fromisoformat(tanggal).replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    day_end = day_start + timedelta(days=1)

    rooms = await db.rooms.find({}, {"_id": 0, "id": 1, "tipe": 1}).to_list(500)
    bookings = await db.bookings.find({
        "status": {"$in": ACTIVE_BOOKING_STATUSES},
        "sync_status": {"$nin": SYNC_STATUS_BELUM_CONFIRMED},
        "jam_mulai": {"$lt": day_end.isoformat()},
        "jam_selesai": {"$gte": day_start.isoformat()},
    }, {"_id": 0, "room_id": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(2000)
    occupied_room_ids = {
        b["room_id"] for b in bookings
        if b.get("jam_selesai") and _occupies_date(parse_iso(b["jam_mulai"], "jam_mulai"), parse_iso(b["jam_selesai"], "jam_selesai"), day_start.date())
    }

    by_tipe: Dict[str, Dict[str, int]] = {}
    for r in rooms:
        entry = by_tipe.setdefault(r.get("tipe", "-"), {"total": 0, "terisi": 0})
        entry["total"] += 1
        if r["id"] in occupied_room_ids:
            entry["terisi"] += 1

    rows = [
        {"tipe": tipe, "total": v["total"], "terisi": v["terisi"], "tersedia": v["total"] - v["terisi"]}
        for tipe, v in sorted(by_tipe.items())
    ]
    total = len(rooms)
    terisi = len(occupied_room_ids)
    return {
        "tanggal": tanggal,
        "total_kamar": total,
        "terisi": terisi,
        "tersedia": total - terisi,
        "okupansi_pct": round((terisi / total) * 100) if total else 0,
        "by_tipe": rows,
    }


@api.get("/ketersediaan/status-tipe-kamar")
async def status_tipe_kamar(user: dict = Depends(get_current_user)):
    """Ketersediaan hari ini, dipecah per tipe kamar (Standard/Cottage)."""
    _, by_tipe = await _room_status_breakdown()
    return _status_tipe_from_breakdown(by_tipe)


@api.get("/ketersediaan/notifikasi")
async def notifikasi_ketersediaan(user: dict = Depends(get_current_user)):
    """Deteksi kondisi yang perlu perhatian staff: stok kamar per tipe yang menipis/habis.
    Availability di aplikasi ini dibaca langsung dari satu sumber data (bukan disinkronkan
    dari sistem lain), sehingga tidak ada kelas notifikasi 'error sinkronisasi' — lihat
    keputusan pada task 'Buat mekanisme sinkronisasi data dari Pelangi PMS'.
    """
    _, by_tipe = await _room_status_breakdown()
    return _notifikasi_from_breakdown(by_tipe)


@api.get("/ketersediaan/live")
async def ketersediaan_live(user: dict = Depends(get_current_user)):
    """Endpoint gabungan (ringkasan + status tipe kamar + notifikasi) dalam satu response,
    dipakai frontend untuk auto-refresh berkala (polling) di Dasbor Ketersediaan — mengikuti
    pola polling sederhana yang sudah dipakai Dashboard.jsx (setInterval), bukan WebSocket,
    karena tidak ada infrastruktur WebSocket di backend ini.
    """
    rooms, by_tipe = await _room_status_breakdown()
    return {
        "ringkasan": _ringkasan_from_rooms(rooms),
        "status_tipe_kamar": _status_tipe_from_breakdown(by_tipe),
        "notifikasi": _notifikasi_from_breakdown(by_tipe),
        "updated_at": now_iso(),
    }
