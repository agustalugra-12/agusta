from core import *

# Status booking yang dianggap menempati kamar (dipakai juga di routes/bookings.py availability check).
# "checked_in" WAJIB disertakan (2026-08-01, bug nyata ditemukan Agus - tamu Opa Isa yang
# sedang menginap sampai 10 Agustus "hilang" dari Kalender Ketersediaan untuk tanggal-tanggal
# di tengah masa inapnya): begitu tamu Menginap benar-benar check-in, status booking berubah
# dari "aktif" jadi "checked_in" (lihat checkin_from_booking di routes/bookings.py) - list ini
# sebelumnya TIDAK PERNAH menyertakan "checked_in", jadi begitu tamu check-in (hampir selalu
# terjadi di hari pertama), okupansi kalender langsung menganggap kamarnya KOSONG untuk SISA
# masa inapnya sampai hari checkout - live test tanggal 3/4/6/9/10 Agustus semuanya salah
# tampil 0% okupansi padahal banyak tamu asli masih menginap. check_room_available
# (reservation_service.py) & scheduling_engine.BOOKING_TERKONFIRMASI_STATUS sudah lama benar
# menyertakan "checked_in" - list di sini yang ketinggalan, sekarang disamakan.
ACTIVE_BOOKING_STATUSES = ["aktif", "booking_paid", "booking_pending", "checked_in"]

# DIHAPUS 2026-08-07 (permintaan langsung Agus - kasus nyata tamu Riyan Sumardika, kamar 13
# tanggal 8 Agustus terlihat "kosong/tersedia" di Kalender Ketersediaan padahal sudah lunas &
# terkunci utk dia, staf bingung menyangka belum ada booking sama sekali). Sebelumnya (Tahap
# 2 Modul Reservasi, 2026-07-17) ada filter `sync_status NOT IN [waiting_reddoorz_input,
# waiting_reddoorz_sync]` di query okupansi bulanan & harian di bawah, supaya booking yang
# masih menunggu sinkron manual RedDoorz TIDAK dianggap "Confirmed" di kalender walau tetap
# memblokir slotnya di check_room_available (anti-overbooking TIDAK terpengaruh keputusan
# ini, dulu maupun sekarang). Ternyata di praktik efeknya JUSTRU MEMBINGUNGKAN (kamar
# kelihatan kosong padahal sebenarnya sudah tidak bisa dibooking siapa pun) - Agus lebih
# pilih kalender selalu cerminkan kenyataan sistem (terisi = terisi, apa pun sync_status-nya).
# Filter dihapus dari kedua query di bawah, bukan cuma dikosongkan - constant ini sudah
# tidak dipakai di tempat lain sama sekali (dicek eksplisit sebelum dihapus).

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

    (2026-08-15, bug nyata ditemukan lewat audit - kasus kamar 9 Pelangi tanggal 16 Agustus:
    Kalender Ketersediaan menampilkan kamar 9 "tersedia" utk tanggal 16 padahal sebenarnya
    TIDAK bisa utk malam 16. Penyebabnya day-use Fani yang check-in PAGI (10:30 WITA) tanggal
    17 Agustus: `_occupies_date` lama cuma menghitung day-use terisi di tanggal check-in-nya
    (`day == start_date`), jadi tanggal 16 dianggap kosong. Padahal checkout standar Menginap
    adalah 12:00 WITA, lebih SIANG dari day-use masuk 10:30 WITA - tamu malam 16 checkout
    17/08 12:00 WITA BENTROK 1.5 jam dgn day-use Fani. Day-use yang mulai sebelum 12:00 WITA
    (04:00 UTC) = memblokir malam sebelumnya juga; day-use mulai jam 12:00 WITA ke atas aman
    (checkout menginap selesai dulu). Diperbaiki: utk day-use (start_date == end_date) yang
    mulai sebelum 04:00 UTC, selain `day == start_date` juga `day == start_date - 1` dihitung
    terisi. `_occupies_date` murni tanggal (input `start`/`end` sudah aware UTC dari
    parse_iso), perbandingan jam dipakai jam UTC murni utk menghindari ambiguitas offset."""
    start_date, end_date = start.date(), end.date()
    if start_date == end_date:
        # Day use satu hari: terisi di tanggal check-in-nya. Kalau mulai SEBELUM 04:00 UTC
        # (12:00 WITA - checkout standar Menginap), berarti pagi harinya menabrak malam
        # SEBELUMNYA juga (checkout menginap 12:00 WITA lebih siang dari day-use masuk) -
        # blokir tanggal sebelumnya juga supaya kalender tidak menampilkan kamar "tersedia"
        # utk malam yang sebenarnya tidak bisa (kasus nyata kamar 9, 2026-08-15).
        blokir_sebelumnya = start.hour < 4
        if blokir_sebelumnya:
            return day in (start_date, start_date - timedelta(days=1))
        return day == start_date
    return start_date <= day < end_date


async def _room_status_breakdown(property_id: str):
    """Ambil status kamar sekali, dipakai bareng oleh ringkasan/status-tipe/notifikasi/live
    supaya polling berkala tidak query db.rooms berkali-kali per request.
    'Tersedia' = kamar berstatus kosong; selain itu (day_use, menginap, perlu_dibersihkan,
    maintenance) dihitung sebagai terisi karena tidak siap dibooking langsung.
    """
    rooms = await db.rooms.find(scoped({}, property_id), {"_id": 0, "tipe": 1, "status": 1}).to_list(500)
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
async def ringkasan_hari_ini(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    """Ringkasan okupansi hari ini: total kamar tersedia, terisi, dan persentase okupansi."""
    rooms, _ = await _room_status_breakdown(property_id)
    return _ringkasan_from_rooms(rooms)


@api.get("/ketersediaan/kalender-bulanan")
async def kalender_bulanan(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: dict = Depends(get_current_user),
    property_id: str = Depends(get_active_property),
):
    """Okupansi per hari untuk satu bulan (Kalender Ketersediaan). Dihitung dari booking
    aktif/pending/paid yang overlap tiap tanggal — bukan status kamar hari-ini (yang hanya
    relevan untuk hari ini).
    """
    total_rooms = await db.rooms.count_documents(scoped({}, property_id))
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)

    # (2026-08-15, bug nyata kasus kamar 9 - lihat ketersediaan_hari): day-use yang check-in
    # PAGI tanggal 1 bulan berikutnya (mulai sebelum 04:00 UTC / 12:00 WITA) memblokir malam
    # TERAKHIR bulan ini. Query `jam_mulai < month_end` tidak menangkapnya - perlebar batas
    # atas sampai pagi hari berikutnya supaya _occupies_date bisa menilai (dia yang putuskan
    # apakah benar meng-occupy, bukan overlap mentah).
    month_end_query = month_end + timedelta(hours=4)

    bookings = await db.bookings.find(scoped({
        "status": {"$in": ACTIVE_BOOKING_STATUSES},
        "jam_mulai": {"$lt": month_end_query.isoformat()},
        "jam_selesai": {"$gte": month_start.isoformat()},
    }, property_id), {"_id": 0, "room_id": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(2000)

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
    property_id: str = Depends(get_active_property),
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

    # (2026-08-15, bug nyata kasus kamar 9): day-use yang check-in PAGI hari BERIKUTNYA
    # (mulai sebelum 04:00 UTC / 12:00 WITA, lihat _occupies_date) memblokir malam
    # SEBELUMNYA - tapi filter `jam_mulai < day_end` TIDAK menangkapnya (Fani mulai 17/08
    # 02:30 UTC, day_end utk tanggal 16 = 17/08 00:00 UTC, 02:30 < 00:00 = False). Perluas
    # batas atas `jam_mulai` sampai pagi hari berikutnya (12:00 WITA = 04:00 UTC, batas
    # checkout standar Menginap yang relevan utk day-use pagi) supaya booking dini-hari
    # hari berikutnya ikut dipertimbangkan; _occupies_date yang memutuskan apakah
    # benar-benar meng-occupy tanggal ini (bukan sekadar overlap mentah).
    query_start = day_start - timedelta(days=1)
    jam_mulai_batas = day_end + timedelta(hours=4)

    rooms = await db.rooms.find(scoped({}, property_id), {"_id": 0, "id": 1, "tipe": 1}).to_list(500)
    bookings = await db.bookings.find(scoped({
        "status": {"$in": ACTIVE_BOOKING_STATUSES},
        "jam_mulai": {"$lt": jam_mulai_batas.isoformat()},
        "jam_selesai": {"$gte": query_start.isoformat()},
    }, property_id), {"_id": 0, "room_id": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(2000)
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
async def status_tipe_kamar(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    """Ketersediaan hari ini, dipecah per tipe kamar (Standard/Cottage)."""
    _, by_tipe = await _room_status_breakdown(property_id)
    return _status_tipe_from_breakdown(by_tipe)


@api.get("/ketersediaan/notifikasi")
async def notifikasi_ketersediaan(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    """Deteksi kondisi yang perlu perhatian staff: stok kamar per tipe yang menipis/habis.
    Availability di aplikasi ini dibaca langsung dari satu sumber data (bukan disinkronkan
    dari sistem lain), sehingga tidak ada kelas notifikasi 'error sinkronisasi' — lihat
    keputusan pada task 'Buat mekanisme sinkronisasi data dari Pelangi PMS'.
    """
    _, by_tipe = await _room_status_breakdown(property_id)
    return _notifikasi_from_breakdown(by_tipe)


@api.get("/ketersediaan/live")
async def ketersediaan_live(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    """Endpoint gabungan (ringkasan + status tipe kamar + notifikasi) dalam satu response,
    dipakai frontend untuk auto-refresh berkala (polling) di Dasbor Ketersediaan — mengikuti
    pola polling sederhana yang sudah dipakai Dashboard.jsx (setInterval), bukan WebSocket,
    karena tidak ada infrastruktur WebSocket di backend ini.
    """
    rooms, by_tipe = await _room_status_breakdown(property_id)
    return {
        "ringkasan": _ringkasan_from_rooms(rooms),
        "status_tipe_kamar": _status_tipe_from_breakdown(by_tipe),
        "notifikasi": _notifikasi_from_breakdown(by_tipe),
        "updated_at": now_iso(),
    }
