from core import *
import asyncio
import logging

# ---- Reports ----
@api.get("/reports/booking-widgets")
async def booking_widgets(user: dict = Depends(get_current_user)):
    """Widget statistik booking untuk Dashboard."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    # Booking hari ini = jam_mulai dalam rentang hari ini
    today_bk = await db.bookings.count_documents({
        "jam_mulai": {"$gte": today_start.isoformat(), "$lt": today_end.isoformat()},
        "status": {"$in": ["aktif", "booking_pending", "booking_paid", "checked_in"]},
    })
    pending_count = await db.bookings.count_documents({"status": "booking_pending"})
    paid_count = await db.bookings.count_documents({"status": "booking_paid"})
    # Pendapatan online = sum total dari booking_paid bulan ini
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    online_paid = await db.bookings.find({
        "source": "online", "payment_status": "paid",
        "paid_at": {"$gte": month_start.isoformat()},
    }, {"_id": 0, "total": 1, "amount_due": 1}).to_list(1000)
    pendapatan_online = sum(int(b.get("amount_due") or b.get("total", 0)) for b in online_paid)
    # Total semua transaksi payment gateway settlement (lifetime, gabungan riwayat Tripay +
    # Midtrans lama — field ini TIDAK filter `gateway`, sengaja mencakup histori keduanya).
    # gross_amount disimpan sebagai string "61800.00". "capture" = status khusus Midtrans lama
    # (kartu kredit), tidak pernah dihasilkan Tripay lagi tapi tetap relevan utk histori.
    payment_total = await db.payment_log.aggregate([
        {"$match": {"transaction_status": {"$in": ["settlement", "capture"]}}},
        {"$group": {"_id": None, "sum": {"$sum": {"$toDouble": "$gross_amount"}}, "count": {"$sum": 1}}},
    ]).to_list(1)
    payment_sum = int(payment_total[0]["sum"]) if payment_total else 0
    payment_count = payment_total[0]["count"] if payment_total else 0
    # Walk-in vs Online (bulan ini)
    online_bulan = await db.bookings.count_documents({
        "source": "online", "created_at": {"$gte": month_start.isoformat()},
    })
    # Walk-in = check-ins langsung dari dashboard (tanpa booking online) bulan ini
    walk_bulan = await db.checkins.count_documents({
        "jam_checkin": {"$gte": month_start.isoformat()},
    })
    return {
        "booking_hari_ini": today_bk,
        "booking_pending": pending_count,
        "booking_paid": paid_count,
        "pendapatan_online_bulan": pendapatan_online,
        "payment_total_count": payment_count,
        "payment_total_sum": payment_sum,
        "booking_online_bulan": online_bulan,
        "booking_walkin_bulan": walk_bulan,
    }


@api.get("/reports/cancellation-revenue")
async def cancellation_revenue(from_date: str, to_date: str, user: dict = Depends(get_current_user)):
    """Pendapatan dari cancel fee (10% × total) + no-show retention (amount_due booking_paid yang jadi no_show).
    from_date/to_date: YYYY-MM-DD (inclusive).
    Returns: { cancel_fees_total, no_show_total, grand_total, by_day:[...], items:[...] }
    """
    try:
        d_from = datetime.fromisoformat(from_date).replace(hour=0, minute=0, second=0, microsecond=0)
        d_to = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59, microsecond=999999)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    cancels = await db.bookings.find({
        "status": "cancelled", "cancel_fee": {"$gt": 0},
        "cancelled_at": {"$gte": d_from.isoformat(), "$lte": d_to.isoformat()},
    }, {"_id": 0}).to_list(2000)
    no_shows = await db.bookings.find({
        "status": "no_show",
        "no_show_at": {"$gte": d_from.isoformat(), "$lte": d_to.isoformat()},
    }, {"_id": 0}).to_list(2000)
    cancel_total = sum(int(b.get("cancel_fee") or 0) for b in cancels)
    noshow_total = sum(int(b.get("amount_due") or 0) for b in no_shows)
    # group per hari
    by_day: Dict[str, Dict[str, int]] = {}
    for b in cancels:
        day = (b.get("cancelled_at") or "")[:10]
        by_day.setdefault(day, {"cancel_fee": 0, "no_show": 0})
        by_day[day]["cancel_fee"] += int(b.get("cancel_fee") or 0)
    for b in no_shows:
        day = (b.get("no_show_at") or "")[:10]
        by_day.setdefault(day, {"cancel_fee": 0, "no_show": 0})
        by_day[day]["no_show"] += int(b.get("amount_due") or 0)
    chart = sorted([{"tanggal": k, **v, "total": v["cancel_fee"] + v["no_show"]} for k, v in by_day.items()], key=lambda x: x["tanggal"])
    items = []
    for b in cancels:
        items.append({"tipe": "cancel", "kode": b["kode"], "room_nomor": b.get("room_nomor"),
                      "nama_tamu": b.get("nama_tamu"), "tanggal": (b.get("cancelled_at") or "")[:19],
                      "nominal": int(b.get("cancel_fee") or 0),
                      "alasan": b.get("cancel_reason") or "",
                      "petugas": b.get("cancelled_by") or "",
                      "source": b.get("source") or "walk_in"})
    for b in no_shows:
        items.append({"tipe": "no_show", "kode": b["kode"], "room_nomor": b.get("room_nomor"),
                      "nama_tamu": b.get("nama_tamu"), "tanggal": (b.get("no_show_at") or "")[:19],
                      "nominal": int(b.get("amount_due") or 0),
                      "alasan": b.get("no_show_reason") or "",
                      "petugas": b.get("no_show_by") or "",
                      "source": b.get("source") or "walk_in"})
    items.sort(key=lambda x: x["tanggal"], reverse=True)
    return {
        "from_date": from_date, "to_date": to_date,
        "cancel_fees_total": cancel_total,
        "no_show_total": noshow_total,
        "grand_total": cancel_total + noshow_total,
        "cancel_count": len(cancels), "no_show_count": len(no_shows),
        "by_day": chart, "items": items,
    }



# ---- Reports: Service Fee 3% + Manual Services ----
@api.get("/reports/service-revenue")
async def report_service_revenue(from_date: str = Query(...), to_date: str = Query(...),
                                  user: dict = Depends(get_current_user)):
    """Aggregate service fee income:
    - checkin_service_fee: service_fee 3% dari checkins selesai (walk-in)
    - booking_service_fee: service_fee 3% dari bookings publik (payment_status=paid, source=online)
    - manual_services: layanan tambahan manual (nominal fleksibel dari staff)
    """
    start = from_date
    end = to_date + "T23:59:59"

    # 1) service_fee 3% dari checkins (walk-in)
    ci = await db.checkins.find(
        {"jam_checkout": {"$gte": start, "$lte": end}, "status": "selesai"},
        {"_id": 0}
    ).to_list(5000)
    checkin_items = []
    checkin_total = 0
    for c in ci:
        fee = int(c.get("service_fee") or 0)
        if fee <= 0: continue
        checkin_total += fee
        checkin_items.append({
            "id": c.get("id"),
            "kode": c.get("trx_no"),
            "tanggal": c.get("jam_checkout"),
            "nama_tamu": c.get("nama_tamu"),
            "room_nomor": c.get("room_nomor"),
            "subtotal": c.get("subtotal", 0),
            "service_fee": fee,
            "total": c.get("total", 0),
            "source": "walk_in",
            "petugas": c.get("petugas_checkout") or c.get("petugas_checkin"),
        })

    # 2) service_fee 3% dari bookings publik yang sudah dibayar
    bk = await db.bookings.find(
        {
            "jam_mulai": {"$gte": start, "$lte": end},
            "source": "online",
            "payment_status": "paid",
        },
        {"_id": 0}
    ).to_list(5000)
    booking_items = []
    booking_total = 0
    for b in bk:
        fee = int(b.get("service_fee") or 0)
        if fee <= 0: continue
        booking_total += fee
        booking_items.append({
            "id": b.get("id"),
            "kode": b.get("kode"),
            "tanggal": b.get("jam_mulai"),
            "nama_tamu": b.get("nama_tamu"),
            "room_nomor": b.get("room_nomor"),
            "subtotal": b.get("subtotal", 0),
            "service_fee": fee,
            "total": b.get("total", 0),
            "source": "online",
            "petugas": b.get("created_by") or "public",
        })

    # 3) manual services
    svc = await db.services.find(
        {"tanggal": {"$gte": start, "$lte": end}},
        {"_id": 0}
    ).sort("tanggal", -1).to_list(5000)
    manual_total = sum(int(s.get("nominal") or 0) for s in svc)

    # by_day breakdown
    def bucket(iso): return (iso or "")[:10]
    by_day: Dict[str, Dict[str, int]] = {}
    for it in checkin_items:
        d = bucket(it["tanggal"])
        by_day.setdefault(d, {"checkin_fee": 0, "booking_fee": 0, "manual": 0})
        by_day[d]["checkin_fee"] += it["service_fee"]
    for it in booking_items:
        d = bucket(it["tanggal"])
        by_day.setdefault(d, {"checkin_fee": 0, "booking_fee": 0, "manual": 0})
        by_day[d]["booking_fee"] += it["service_fee"]
    for s in svc:
        d = bucket(s.get("tanggal"))
        by_day.setdefault(d, {"checkin_fee": 0, "booking_fee": 0, "manual": 0})
        by_day[d]["manual"] += int(s.get("nominal") or 0)
    by_day_list = [{"tanggal": d, **by_day[d]} for d in sorted(by_day.keys())]

    grand_total_fee = checkin_total + booking_total
    grand_total_all = grand_total_fee + manual_total

    return {
        "from_date": from_date,
        "to_date": to_date,
        "service_fee_pct": SERVICE_FEE_PCT,
        "checkin_service_fee_total": checkin_total,
        "checkin_count": len(checkin_items),
        "booking_service_fee_total": booking_total,
        "booking_count": len(booking_items),
        "service_fee_grand_total": grand_total_fee,
        "manual_service_total": manual_total,
        "manual_service_count": len(svc),
        "grand_total": grand_total_all,
        "by_day": by_day_list,
        "checkin_items": checkin_items,
        "booking_items": booking_items,
        "manual_services": svc,
    }

@api.get("/reports/summary")
async def report_summary(user: dict = Depends(get_current_user)):
    today_iso = datetime.now(timezone.utc).date().isoformat()
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    # rooms
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    counts = {"kosong": 0, "day_use": 0, "menginap": 0, "perlu_dibersihkan": 0, "maintenance": 0, "dipesan_hari_ini": 0}
    # Kamar berstatus "kosong" tapi SUDAH ada booking (aktif/booking_pending/booking_paid) yang
    # menempati hari ini dihitung sebagai "dipesan_hari_ini", BUKAN "kosong" — sebelumnya kartu
    # "Kosong" di Dashboard murni baca `room.status` real-time, jadi tidak pernah berkurang
    # walau sudah ada booking OTA/walk-in untuk hari ini (room.status baru berubah setelah
    # tamu benar-benar di-check-in, lihat checkin_from_booking di routes/bookings.py). Rentang
    # tanggal sama seperti _occupies_date (routes/ketersediaan.py): [checkin_date, checkout_date)
    # exclusive checkout, kecuali day-use (checkin=checkout, tetap terhitung).
    today_date = datetime.now(timezone.utc).date()
    today_start_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_dt = today_start_dt + timedelta(days=1)
    today_bookings = await db.bookings.find({
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": today_end_dt.isoformat()},
        "jam_selesai": {"$gt": today_start_dt.isoformat()},
    }, {"_id": 0, "room_id": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(500)
    rooms_dipesan_hari_ini = set()
    for b in today_bookings:
        b_start = parse_iso(b["jam_mulai"], "jam_mulai").date()
        b_end = parse_iso(b["jam_selesai"], "jam_selesai").date()
        occupies_today = today_date == b_start if b_start == b_end else b_start <= today_date < b_end
        if occupies_today:
            rooms_dipesan_hari_ini.add(b["room_id"])
    for r in rooms:
        status = r.get("status", "kosong")
        if status == "kosong" and r["id"] in rooms_dipesan_hari_ini:
            counts["dipesan_hari_ini"] += 1
        else:
            counts[status] = counts.get(status, 0) + 1
    # checkins today
    ci_today = await db.checkins.find({"jam_checkin": {"$gte": today_iso}}, {"_id": 0}).to_list(500)
    co_today = await db.checkins.find({"jam_checkout": {"$gte": today_iso}, "status": "selesai"}, {"_id": 0}).to_list(500)
    rev_room_today = sum(c.get("total", 0) for c in co_today)
    # booking online/OTA/WhatsApp yang sudah lunas (dibucket per paid_at — tanggal uang benar-benar
    # masuk, sama seperti /reports/daily & /reports/rooms yang sudah lebih dulu diperbaiki 2026-07-13;
    # endpoint ini (dipakai Dashboard utama) sebelumnya kelewat, bikin "Pendapatan"/"Laba Bersih" di
    # Dashboard tidak sinkron dengan jumlah booking (yang sudah mencakup semua sumber sejak awal).
    # ota_harga_dikonfirmasi=False dikecualikan (2026-07-19) - booking OTA "Prepaid" yang
    # emailnya tidak mencantumkan nominal, sempat memakai ESTIMASI tarif publik PMS sebagai
    # placeholder (lihat buat_reservasi_otomatis, routes/otomasi_email.py) - jangan dihitung
    # sebagai pendapatan asli sampai staf konfirmasi nominal settlement sungguhan.
    bk_today = await db.bookings.find({
        "source": {"$in": ["ota", "online", "whatsapp"]}, "payment_status": "paid",
        "paid_at": {"$gte": today_iso}, "ota_harga_dikonfirmasi": {"$ne": False},
    }, {"_id": 0, "total": 1}).to_list(1000)
    rev_booking_today = sum(int(b.get("total") or 0) for b in bk_today)
    # kasir today / month
    kasir_today = await db.kasir.find({"timestamp": {"$gte": today_iso}}, {"_id": 0}).to_list(1000)
    rev_kasir_today = sum(k.get("total", 0) for k in kasir_today)
    rev_per_kat = {"makanan": 0, "minuman": 0, "laundry": 0}
    for k in kasir_today:
        for it in k.get("items", []):
            rev_per_kat[it["kategori"]] = rev_per_kat.get(it["kategori"], 0) + it["subtotal"]
    # month
    ci_month = await db.checkins.find({"jam_checkout": {"$gte": month_start}, "status": "selesai"}, {"_id": 0}).to_list(2000)
    kasir_month = await db.kasir.find({"timestamp": {"$gte": month_start}}, {"_id": 0}).to_list(2000)
    bk_month = await db.bookings.find({
        "source": {"$in": ["ota", "online", "whatsapp"]}, "payment_status": "paid",
        "paid_at": {"$gte": month_start}, "ota_harga_dikonfirmasi": {"$ne": False},
    }, {"_id": 0, "total": 1}).to_list(5000)
    rev_booking_month = sum(int(b.get("total") or 0) for b in bk_month)
    # services (manual)
    svc_today = await db.services.find({"tanggal": {"$gte": today_iso}}, {"_id": 0}).to_list(500)
    svc_month = await db.services.find({"tanggal": {"$gte": month_start}}, {"_id": 0}).to_list(2000)
    rev_svc_today = sum(s.get("nominal", 0) for s in svc_today)
    rev_svc_month = sum(s.get("nominal", 0) for s in svc_month)
    rev_month = sum(c.get("total", 0) for c in ci_month) + sum(k.get("total", 0) for k in kasir_month) + rev_svc_month + rev_booking_month
    # expenses
    exp_today = await db.expenses.find({"tanggal": {"$gte": today_iso}}, {"_id": 0}).to_list(500)
    exp_month = await db.expenses.find({"tanggal": {"$gte": month_start}}, {"_id": 0}).to_list(2000)
    total_exp_today = sum(e.get("nominal", 0) for e in exp_today)
    total_exp_month = sum(e.get("nominal", 0) for e in exp_month)
    # Okupansi harian (2026-07-21, permintaan user) - kamar yang TIDAK "kosong" (day_use,
    # menginap, dipesan_hari_ini, perlu_dibersihkan, maintenance) dianggap terisi/tidak
    # tersedia utk tamu walk-in hari ini - definisi operasional, bukan cuma "ada tamu
    # menginap semalam" (perlu_dibersihkan/maintenance juga bikin kamar tidak bisa dipakai).
    okupansi_persen = round((len(rooms) - counts["kosong"]) / len(rooms) * 100, 1) if rooms else 0
    return {
        "rooms": counts,
        "total_rooms": len(rooms),
        "okupansi_persen": okupansi_persen,
        "tamu_hari_ini": len(ci_today),
        "checkout_hari_ini": len(co_today),
        "pendapatan_hari_ini": rev_room_today + rev_booking_today + rev_kasir_today + rev_svc_today,
        "pendapatan_kamar_hari_ini": rev_room_today + rev_booking_today,
        "pendapatan_kasir_hari_ini": rev_kasir_today,
        "pendapatan_service_hari_ini": rev_svc_today,
        "pendapatan_service_bulan_ini": rev_svc_month,
        "pendapatan_per_kategori": rev_per_kat,
        "pendapatan_bulan_ini": rev_month,
        "pengeluaran_hari_ini": total_exp_today,
        "pengeluaran_bulan_ini": total_exp_month,
        "laba_bersih_bulan_ini": rev_month - total_exp_month,
    }


# GET /reports/ai-insight DIHAPUS 2026-07-22 - digantikan sepenuhnya oleh AI Grow
# (GET /ai-grow/daily-brief, routes/ai_grow.py), yang mencakup jauh lebih banyak (health
# score, korelasi, prediksi, opportunity/risk engine, rekomendasi), bukan cuma narasi
# okupansi+pengeluaran+kas.

@api.get("/reports/kedatangan-harian")
async def report_kedatangan_harian(user: dict = Depends(get_current_user)):
    """Jumlah kedatangan tamu per hari, 30 hari terakhir (2026-07-21, permintaan user -
    grafik tren kedatangan di Dashboard utama). Sumber `db.bookings.jam_mulai` (tanggal
    check-in), BUKAN `db.checkins` - collection itu jarang terisi (cuma jalur check-in
    manual staf tertentu yang menulis ke situ, sebagian besar booking online/OTA/AI tidak
    pernah membuat dokumen di sana), jadi tidak representatif untuk tren. Booking
    `cancelled` dikecualikan (tidak pernah benar-benar datang). Dihitung per booking
    (1 booking = 1 "kedatangan", konsisten dgn cara kamar dihitung terisi/tidaknya),
    bukan per kepala (jumlah_tamu) - lebih mudah dibaca staf sebagai tren reservasi."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=29)
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    bookings = await db.bookings.find({
        "status": {"$ne": "cancelled"},
        "jam_mulai": {"$gte": start_dt.isoformat()},
    }, {"_id": 0, "jam_mulai": 1}).to_list(5000)
    per_tanggal: Dict[str, int] = {}
    for b in bookings:
        try:
            tgl = parse_iso(b["jam_mulai"], "jam_mulai").date().isoformat()
        except Exception:
            continue
        per_tanggal[tgl] = per_tanggal.get(tgl, 0) + 1
    out = []
    for i in range(30):
        d = (start_date + timedelta(days=i)).isoformat()
        out.append({"tanggal": d, "jumlah": per_tanggal.get(d, 0)})
    return out


@api.get("/reports/daily")
async def report_daily(from_date: str = Query(...), to_date: str = Query(...),
                       user: dict = Depends(get_current_user)):
    """Return per-day revenue between dates (inclusive). Dates: YYYY-MM-DD.
    "kamar" mencakup walk-in (checkins, dibucket per jam_checkout) DAN booking
    online/OTA/WhatsApp yang sudah lunas (bookings, dibucket per paid_at — tanggal uang
    benar-benar masuk, konsisten dengan /laporan-analitik/pendapatan). Tidak ada duplikasi
    dengan checkins karena booking online/OTA/WA tidak pernah menghasilkan dokumen checkins
    terpisah di sistem ini (dua alur guest-arrival yang independen)."""
    start = from_date
    end = to_date + "T23:59:59"
    ci = await db.checkins.find({"jam_checkout": {"$gte": start, "$lte": end}, "status": "selesai"}, {"_id": 0}).to_list(5000)
    bk = await db.bookings.find({
        "source": {"$in": ["ota", "online", "whatsapp"]},
        "payment_status": "paid",
        "paid_at": {"$gte": start, "$lte": end},
        "ota_harga_dikonfirmasi": {"$ne": False},
    }, {"_id": 0, "total": 1, "paid_at": 1}).to_list(5000)
    ks = await db.kasir.find({"timestamp": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
    ex = await db.expenses.find({"tanggal": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
    sv = await db.services.find({"tanggal": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
    by_day: Dict[str, Dict[str, int]] = {}
    def bucket(iso):
        return iso[:10]
    def _init(): return {"kamar": 0, "makanan": 0, "minuman": 0, "laundry": 0, "service": 0, "pengeluaran": 0}
    for c in ci:
        d = bucket(c["jam_checkout"])
        by_day.setdefault(d, _init())
        by_day[d]["kamar"] += c.get("total", 0)
    for b in bk:
        d = bucket(b["paid_at"])
        by_day.setdefault(d, _init())
        by_day[d]["kamar"] += int(b.get("total") or 0)
    for k in ks:
        d = bucket(k["timestamp"])
        by_day.setdefault(d, _init())
        for it in k.get("items", []):
            by_day[d][it["kategori"]] += it["subtotal"]
    for s in sv:
        d = bucket(s.get("tanggal", ""))
        if not d: continue
        by_day.setdefault(d, _init())
        by_day[d]["service"] += int(s.get("nominal") or 0)
    for e in ex:
        d = bucket(e["tanggal"])
        by_day.setdefault(d, _init())
        by_day[d]["pengeluaran"] += e.get("nominal", 0)
    result = []
    for d in sorted(by_day.keys()):
        row = by_day[d]
        pendapatan = row["kamar"] + row["makanan"] + row["minuman"] + row["laundry"] + row["service"]
        result.append({
            "tanggal": d, **row,
            "pendapatan": pendapatan,
            "laba": pendapatan - row["pengeluaran"],
        })
    return result

@api.get("/reports/kas-metode-bayar")
async def report_kas_metode_bayar(from_date: str = Query(...), to_date: str = Query(...),
                                  user: dict = Depends(get_current_user)):
    """Rekap uang masuk per metode bayar (Tunai/QRIS/Transfer) dari Kasir (POS) & Check-In
    (walk-in) — supaya owner bisa cocokkan uang cash fisik yang harus ada di laci vs sistem.
    SENGAJA tidak termasuk booking online/OTA (Tripay) karena uangnya masuk ke rekening/payment
    gateway, tidak pernah melewati laci fisik — lihat /reports/daily untuk total pendapatan
    kamar yang mencakup semua saluran."""
    start = from_date
    end = to_date + "T23:59:59"
    totals = {"tunai": 0, "qris": 0, "transfer": 0}
    ks = await db.kasir.find({"timestamp": {"$gte": start, "$lte": end}}, {"_id": 0, "pembayaran": 1}).to_list(5000)
    ci = await db.checkins.find(
        {"status": "selesai", "jam_checkout": {"$gte": start, "$lte": end}},
        {"_id": 0, "pembayaran": 1},
    ).to_list(5000)
    for row in ks + ci:
        for p in row.get("pembayaran") or []:
            m = p.get("metode")
            if m in totals:
                totals[m] += int(p.get("jumlah") or 0)
    return {**totals, "total": sum(totals.values())}

@api.get("/reports/rooms")
async def report_rooms(from_date: str = Query(...), to_date: str = Query(...),
                       user: dict = Depends(get_current_user)):
    """Transaksi kamar walk-in (checkins) DIGABUNG booking online/OTA/WhatsApp yang sudah
    lunas (bookings, dibucket per paid_at) — sebelumnya cuma checkins, bikin RedDoorz/booking
    online tidak pernah terhitung di "Total Transaksi" & pendapatan kamar. Tidak ada duplikasi
    dengan checkins (dua alur guest-arrival independen, lihat report_daily)."""
    start = from_date
    end = to_date + "T23:59:59"
    items = await db.checkins.find(
        {"jam_checkout": {"$gte": start, "$lte": end}, "status": "selesai"},
        {"_id": 0}
    ).to_list(5000)
    bk = await db.bookings.find({
        "source": {"$in": ["ota", "online", "whatsapp"]},
        "payment_status": "paid",
        "paid_at": {"$gte": start, "$lte": end},
        "ota_harga_dikonfirmasi": {"$ne": False},
    }, {"_id": 0}).to_list(5000)
    booking_items = [{
        "id": b["id"], "trx_no": b.get("kode"),
        "nama_tamu": b.get("nama_tamu"), "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
        "jam_checkin": b.get("jam_mulai"), "jam_checkout": b.get("jam_selesai"),
        "jumlah_tamu": b.get("jumlah_tamu", 1),
        "tarif_dasar": b.get("subtotal", 0), "biaya_tambahan": 0, "total": b.get("total", 0),
        "petugas_checkout": b.get("created_by") or b.get("source"),
        "source": b.get("source"),
    } for b in bk]
    all_items = sorted(items + booking_items, key=lambda x: x.get("jam_checkout") or "", reverse=True)
    summary = {
        "tanggal_dari": from_date, "tanggal_sampai": to_date,
        "total_transaksi": len(all_items),
        "total_tamu": sum(int(c.get("jumlah_tamu", 1)) for c in all_items),
        "kamar_terpakai": len({c["room_nomor"] for c in all_items}),
        "pendapatan_standard": sum(c.get("total", 0) for c in all_items if c.get("room_tipe") == "Standard"),
        "pendapatan_cottage": sum(c.get("total", 0) for c in all_items if c.get("room_tipe") == "Cottage"),
        "total_overtime": sum(c.get("biaya_tambahan", 0) for c in all_items),
        "total_pendapatan": sum(c.get("total", 0) for c in all_items),
    }
    return {"summary": summary, "items": all_items}

@api.get("/reports/kasir-detail")
async def report_kasir_detail(from_date: str = Query(...), to_date: str = Query(...),
                              user: dict = Depends(get_current_user)):
    start = from_date
    end = to_date + "T23:59:59"
    trxs = await db.kasir.find(
        {"timestamp": {"$gte": start, "$lte": end}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(5000)
    per_kat = {"makanan": 0, "minuman": 0, "laundry": 0}
    for t in trxs:
        for it in t.get("items", []):
            per_kat[it["kategori"]] = per_kat.get(it["kategori"], 0) + it.get("subtotal", 0)
    summary = {
        "tanggal_dari": from_date, "tanggal_sampai": to_date,
        "total_transaksi": len(trxs),
        "total_makanan": per_kat["makanan"],
        "total_minuman": per_kat["minuman"],
        "total_laundry": per_kat["laundry"],
        "total_pendapatan": sum(t.get("total", 0) for t in trxs),
    }
    return {"summary": summary, "items": trxs}

@api.get("/reports/items-sold")
async def report_items_sold(from_date: str = Query(...), to_date: str = Query(...),
                            user: dict = Depends(get_current_user)):
    start = from_date
    end = to_date + "T23:59:59"
    trxs = await db.kasir.find({"timestamp": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
    agg: Dict[str, Dict[str, Any]] = {}
    for t in trxs:
        for it in t.get("items", []):
            key = it["product_id"]
            if key not in agg:
                agg[key] = {
                    "product_id": key, "kode": it["kode"], "nama": it["nama"],
                    "kategori": it["kategori"], "harga": it["harga"], "qty": 0, "pendapatan": 0,
                }
            agg[key]["qty"] += it["qty"]
            agg[key]["pendapatan"] += it["subtotal"]
    rows = sorted(agg.values(), key=lambda x: x["qty"], reverse=True)
    return rows

@api.get("/reports/top-products")
async def report_top_products(period: str = Query("month"), limit: int = Query(10),
                              user: dict = Depends(get_current_user)):
    """period: today | month | year"""
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.date().isoformat()
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    trxs = await db.kasir.find({"timestamp": {"$gte": start}}, {"_id": 0}).to_list(10000)
    agg: Dict[str, Dict[str, Any]] = {}
    for t in trxs:
        for it in t.get("items", []):
            key = it["product_id"]
            if key not in agg:
                agg[key] = {"kode": it["kode"], "nama": it["nama"], "kategori": it["kategori"], "qty": 0, "pendapatan": 0}
            agg[key]["qty"] += it["qty"]
            agg[key]["pendapatan"] += it["subtotal"]
    rows = sorted(agg.values(), key=lambda x: x["qty"], reverse=True)[:limit]
    return {"period": period, "rows": rows}

@api.get("/reports/shift")
async def report_shift(from_date: str = Query(...), to_date: str = Query(...),
                        user: dict = Depends(get_current_user)):
    """Laporan aktivitas per petugas per hari. Sistem ini tidak punya konsep clock-in/out
    shift asli — laporan ini dirangkum dari jejak petugas yang sudah tercatat di tiap modul
    (kasir, check-in/out, pengeluaran, housekeeping), dikelompokkan per tanggal + nama
    petugas, supaya owner tetap bisa melihat kontribusi/aktivitas tiap staf per hari."""
    start = from_date
    end = to_date + "T23:59:59"

    def bucket(iso: str) -> str:
        return (iso or "")[:10]

    def blank_row(tanggal: str, petugas: str) -> Dict[str, Any]:
        return {
            "tanggal": tanggal, "petugas": petugas,
            "kasir_count": 0, "kasir_total": 0,
            "checkin_count": 0,
            "checkout_count": 0, "checkout_total": 0,
            "expense_count": 0, "expense_total": 0,
            "housekeeping_count": 0,
        }

    rows: Dict[tuple, Dict[str, Any]] = {}
    def row(tanggal: str, petugas: str) -> Dict[str, Any]:
        key = (tanggal, petugas or "-")
        if key not in rows:
            rows[key] = blank_row(tanggal, petugas or "-")
        return rows[key]

    kasir_docs = await db.kasir.find(
        {"timestamp": {"$gte": start, "$lte": end}}, {"_id": 0, "timestamp": 1, "petugas": 1, "total": 1}
    ).to_list(10000)
    for k in kasir_docs:
        r = row(bucket(k.get("timestamp")), k.get("petugas"))
        r["kasir_count"] += 1
        r["kasir_total"] += int(k.get("total") or 0)

    checkin_docs = await db.checkins.find(
        {"jam_checkin": {"$gte": start, "$lte": end}}, {"_id": 0, "jam_checkin": 1, "petugas_checkin": 1}
    ).to_list(10000)
    for c in checkin_docs:
        r = row(bucket(c.get("jam_checkin")), c.get("petugas_checkin"))
        r["checkin_count"] += 1

    checkout_docs = await db.checkins.find(
        {"jam_checkout": {"$gte": start, "$lte": end}}, {"_id": 0, "jam_checkout": 1, "petugas_checkout": 1, "total": 1}
    ).to_list(10000)
    for c in checkout_docs:
        if not c.get("jam_checkout"):
            continue
        r = row(bucket(c["jam_checkout"]), c.get("petugas_checkout"))
        r["checkout_count"] += 1
        r["checkout_total"] += int(c.get("total") or 0)

    expense_docs = await db.expenses.find(
        {"tanggal": {"$gte": start, "$lte": end}}, {"_id": 0, "tanggal": 1, "user": 1, "nominal": 1}
    ).to_list(10000)
    for e in expense_docs:
        r = row(bucket(e.get("tanggal")), e.get("user"))
        r["expense_count"] += 1
        r["expense_total"] += int(e.get("nominal") or 0)

    hk_docs = await db.housekeeping_log.find(
        {"jam_selesai": {"$gte": start, "$lte": end}, "status": "selesai"}, {"_id": 0, "jam_selesai": 1, "petugas": 1}
    ).to_list(10000)
    for h in hk_docs:
        if not h.get("petugas"):
            continue
        r = row(bucket(h.get("jam_selesai")), h["petugas"])
        r["housekeeping_count"] += 1

    rows_list = sorted(rows.values(), key=lambda r: (r["tanggal"], r["petugas"]))

    agg_fields = ["kasir_count", "kasir_total", "checkin_count", "checkout_count", "checkout_total",
                  "expense_count", "expense_total", "housekeeping_count"]
    per_petugas: Dict[str, Dict[str, Any]] = {}
    for r in rows_list:
        p = per_petugas.setdefault(r["petugas"], {"petugas": r["petugas"], **{f: 0 for f in agg_fields}})
        for f in agg_fields:
            p[f] += r[f]

    return {
        "from_date": from_date,
        "to_date": to_date,
        "rows": rows_list,
        "per_petugas": sorted(per_petugas.values(), key=lambda p: p["kasir_total"] + p["checkout_total"], reverse=True),
    }
