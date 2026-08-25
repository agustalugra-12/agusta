from core import *
from routes.ketersediaan import _occupies_date

# ---- Laporan & Analitik (Fase 3) ----
# Beda dari /reports/* (P&L operasional Fase 1, sumber: checkins/kasir/expenses walk-in):
# fokus di sini pendapatan & performa booking multi-saluran (online/ota/whatsapp) dari
# collection `bookings`, plus tren okupansi gabungan (bookings + checkins walk-in).

SALURAN_KEYS = ["ota", "website", "whatsapp"]
# whatsapp_auto (booking auto-approve AI, day_use & menginap - lihat
# ONLINE_BOOKING_SOURCES di core.py) dipetakan ke saluran "whatsapp" yang sama dgn
# approval manual staf - sama-sama datang dari kanal WhatsApp, cuma beda siapa yang
# klik approve terakhir, bukan saluran akuisisi yang beda (2026-08-09, root cause sama
# dgn bug "Dashboard/Ringkasan/Laporan Kamar beda-beda" - booking whatsapp_auto
# sebelumnya tidak match key apa pun di sini, hilang total dari Analitik Saluran).
# whatsapp_request (2026-08-25, sama insiden dgn whatsapp_auto di atas - lihat
# ONLINE_BOOKING_SOURCES/core.py) - nilai source ASLI yang dipakai approve_booking_request/
# otomasi_email utk booking dari permintaan WhatsApp, "whatsapp" polos ternyata tidak
# pernah jadi nilai source apa pun (cek db.bookings.distinct("source")) - tanpa entri ini,
# 30 booking asli (Rp5.444.050 sejak 1 Agustus) hilang dari Analitik Saluran juga.
SOURCE_TO_SALURAN = {"online": "website", "ota": "ota", "whatsapp": "whatsapp", "whatsapp_auto": "whatsapp", "whatsapp_request": "whatsapp"}


@api.get("/laporan-analitik/pendapatan")
async def laporan_pendapatan(from_date: str = Query(...), to_date: str = Query(...),
                              user: dict = Depends(get_current_user),
                              property_id: str = Depends(get_active_property)):
    """Pendapatan harian dari booking multi-saluran yang sudah dibayar (payment_status=paid),
    diakui per MALAM inap (accrual/matching principle) — booking yang nginap lintas bulan
    kebagi proporsional ke tiap bulan sesuai malam yang benar-benar terpakai, bukan numpuk
    semua di tanggal paid_at. Konsisten dengan /reports/daily. Tidak termasuk pendapatan
    walk-in (sudah ada di /reports/daily).

    2 bug ditemukan 2026-08-25 (audit lanjutan, "cek juga laporan lain" - sama insiden
    dgn fix pendapatan kamar/Arus Kas/Kas per Metode Bayar hari ini):
    1. Query TIDAK PERNAH cek `source` sama sekali - PADAHAL docstring di atas eksplisit
       bilang "tidak termasuk walk-in" - 17 booking walk_in Menginap (Rp3.327.350) nyata
       ikut kehitung di sini, DOBEL dgn /reports/daily yang sudah menghitungnya juga.
       Ditambahkan filter source=ONLINE_BOOKING_SOURCES supaya benar2 online-only sesuai
       niat docstring-nya.
    2. Query TIDAK PERNAH cek `status` - 7 booking cancelled (Rp1.003.000) yang lupa
       direset payment_status-nya (sama akar dgn fix _hitung_pendapatan_harian hari ini)
       ikut kehitung sbg pendapatan asli. Ditambahkan status != cancelled."""
    start, end = wita_date_range_to_utc(from_date, to_date)
    bks = await db.bookings.find(scoped({
        "source": {"$in": ONLINE_BOOKING_SOURCES},
        "payment_status": "paid",
        "status": {"$ne": "cancelled"},
        "jam_mulai": {"$lte": end},
        "jam_selesai": {"$gte": start},
        "ota_harga_dikonfirmasi": {"$ne": False},
    }, property_id), {"_id": 0, "total": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(5000)
    by_day: Dict[str, int] = {}
    for b in bks:
        total = int(b.get("total") or 0)
        jm, js = b.get("jam_mulai"), b.get("jam_selesai")
        if not jm or not js:
            continue
        d0 = datetime.fromisoformat(jm).date()
        d1 = datetime.fromisoformat(js).date()
        nights = max(1, (d1 - d0).days)
        per_night = total / nights
        for i in range(nights):
            d = (d0 + timedelta(days=i)).isoformat()
            if d < from_date or d > to_date:
                continue
            by_day[d] = by_day.get(d, 0) + round(per_night)
    return [{"tanggal": d, "pendapatan": by_day[d]} for d in sorted(by_day.keys())]


@api.get("/laporan-analitik/performa-saluran")
async def laporan_performa_saluran(channel: str = Query("Semua"),
                                    user: dict = Depends(get_current_user),
                                    property_id: str = Depends(get_active_property)):
    """Jumlah booking & pendapatan (paid) per saluran (ota/website/whatsapp), lifetime.
    channel: 'Semua' atau salah satu key saluran untuk filter satu saja.

    "status" != cancelled ditambahkan (2026-08-25, sama fix dgn laporan_pendapatan di atas)
    - 7 booking cancelled yang masih payment_status=paid sebelumnya ikut kehitung sbg
    performa saluran asli."""
    keys = SALURAN_KEYS if channel == "Semua" else [channel]
    sources = [src for src, key in SOURCE_TO_SALURAN.items() if key in keys]
    bks = await db.bookings.find(scoped({
        "source": {"$in": sources},
        "payment_status": "paid",
        "status": {"$ne": "cancelled"},
        "ota_harga_dikonfirmasi": {"$ne": False},
    }, property_id), {"_id": 0, "source": 1, "total": 1}).to_list(10000)
    agg = {k: {"booking": 0, "pendapatan": 0} for k in keys}
    for b in bks:
        k = SOURCE_TO_SALURAN.get(b.get("source"))
        if k in agg:
            agg[k]["booking"] += 1
            agg[k]["pendapatan"] += int(b.get("total") or 0)
    return [{"key": k, **agg[k]} for k in keys]


@api.get("/laporan-analitik/tren-okupansi")
async def laporan_tren_okupansi(from_date: str = Query(...), to_date: str = Query(...),
                                 user: dict = Depends(get_current_user),
                                 property_id: str = Depends(get_active_property)):
    """Okupansi harian (%) = jumlah kamar unik terisi hari itu / total kamar.
    Gabungan booking multi-saluran (bookings, status aktif/booking_paid) + walk-in (checkins).

    (2026-08-09, bug nyata - "iso[:10] mentah" audit lanjutan permintaan Agus) - batas
    query SEBELUMNYA dibandingkan LANGSUNG dari `from_date`/`to_date` yang diketik user
    tanpa konversi WITA sama sekali (beda dari endpoint /reports/* lain yang sudah pakai
    `wita_date_range_to_utc`) - dini hari WITA (00:00-07:59) bisa ke-exclude/ke-include
    keliru. `mulai`/`selesai` yang dibandingkan ke `_occupies_date` juga dikonversi ke
    WITA dulu sebelum `.date()` (di dalam _occupies_date sendiri) - drpd `.date()` pada
    datetime UTC mentah yang bisa jatuh ke tanggal kalender yang salah."""
    total_rooms = await db.rooms.count_documents(scoped({}, property_id))
    d_from = datetime.fromisoformat(from_date)
    d_to = datetime.fromisoformat(to_date)
    next_day_after_to = (d_to.date() + timedelta(days=1)).isoformat()
    range_start, _ = wita_date_range_to_utc(from_date, from_date)
    range_end, _ = wita_date_range_to_utc(next_day_after_to, next_day_after_to)
    WITA = timezone(timedelta(hours=8))

    bks = await db.bookings.find(scoped({
        # "booking_pending"/"checked_in" WAJIB disertakan (2026-08-02, bug nyata - sama pola
        # dgn Kalender Ketersediaan/Daftar Reservasi: tamu yang sudah check-in tidak lagi
        # "aktif", jadi tanpa ini tren okupansi UNDERCOUNT begitu tamu benar-benar check-in).
        "status": {"$in": ["aktif", "booking_paid", "booking_pending", "checked_in"]},
        "jam_mulai": {"$lt": range_end}, "jam_selesai": {"$gt": range_start},
    }, property_id), {"_id": 0, "room_nomor": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(5000)
    cis = await db.checkins.find(scoped({
        "jam_checkin": {"$lt": range_end},
        "$or": [{"jam_checkout": {"$gt": range_start}}, {"status": "aktif"}],
    }, property_id), {"_id": 0, "room_nomor": 1, "jam_checkin": 1, "jam_checkout": 1}).to_list(5000)

    stays = [(b["room_nomor"], b["jam_mulai"], b.get("jam_selesai") or range_end) for b in bks]
    stays += [(c["room_nomor"], c["jam_checkin"], c.get("jam_checkout") or range_end) for c in cis]

    result = []
    n_days = (d_to.date() - d_from.date()).days + 1
    for i in range(max(1, n_days)):
        day = d_from.date() + timedelta(days=i)
        # Bug nyata ditemukan 2026-08-02 (sama pola dgn Kalender Ketersediaan/Daftar
        # Reservasi/saran tanggal alternatif - overlap TIMESTAMP mentah membuat hari CHECKOUT
        # ikut dihitung terisi, inflate okupansi). Pakai _occupies_date yang sama - juga benar
        # utk day-use (checkin/checkout hari yang sama tetap dihitung terisi hari itu).
        # mulai/selesai dikonversi ke WITA DULU (2026-08-09) sebelum .date() di dalam
        # _occupies_date - drpd .date() pada datetime UTC mentah yang jatuh ke tanggal
        # kalender yang salah utk transaksi dini hari WITA (00:00-07:59).
        occupied = {
            room for room, mulai, selesai in stays
            if _occupies_date(datetime.fromisoformat(mulai).astimezone(WITA), datetime.fromisoformat(selesai).astimezone(WITA), day)
        }
        pct = round(len(occupied) / total_rooms * 100) if total_rooms else 0
        result.append({"tanggal": day.isoformat(), "okupansi": min(100, pct)})
    return result
