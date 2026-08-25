from core import *
import asyncio
import logging

# ---- Reports ----
@api.get("/reports/booking-widgets")
async def booking_widgets(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    """Widget statistik booking untuk Dashboard."""
    # (2026-08-09) today_start/month_start WAJIB dari WITA, bukan UTC mentah - sama fix
    # dgn report_summary (2026-08-07) - dini hari WITA (00:00-07:59) msh tanggal UTC
    # KEMARIN. Filter "source": "online" jg diganti ONLINE_BOOKING_SOURCES (sama fix dgn
    # report_summary/report_daily/report_rooms/report_service_revenue - literal "online"
    # sebelumnya tidak mencakup "ota"/"whatsapp"/"whatsapp_auto").
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_start_iso, today_end_iso = wita_date_range_to_utc(today_wita.isoformat(), today_wita.isoformat())
    month_start_iso, _ = wita_date_range_to_utc(today_wita.replace(day=1).isoformat(), today_wita.replace(day=1).isoformat())
    # Booking hari ini = jam_mulai dalam rentang hari ini
    today_bk = await db.bookings.count_documents(scoped({
        "jam_mulai": {"$gte": today_start_iso, "$lte": today_end_iso},
        "status": {"$in": ["aktif", "booking_pending", "booking_paid", "checked_in"]},
    }, property_id))
    pending_count = await db.bookings.count_documents(scoped({"status": "booking_pending"}, property_id))
    paid_count = await db.bookings.count_documents(scoped({"status": "booking_paid"}, property_id))
    # Pendapatan online = sum total dari booking_paid bulan ini
    online_paid = await db.bookings.find(scoped({
        "source": {"$in": ONLINE_BOOKING_SOURCES}, "payment_status": "paid",
        "paid_at": {"$gte": month_start_iso},
    }, property_id), {"_id": 0, "total": 1, "amount_due": 1}).to_list(1000)
    pendapatan_online = sum(int(b.get("amount_due") or b.get("total", 0)) for b in online_paid)
    # Total semua transaksi payment gateway settlement (lifetime, gabungan riwayat Tripay +
    # Midtrans lama — field ini TIDAK filter `gateway`, sengaja mencakup histori keduanya).
    # gross_amount disimpan sebagai string "61800.00". "capture" = status khusus Midtrans lama
    # (kartu kredit), tidak pernah dihasilkan Tripay lagi tapi tetap relevan utk histori.
    payment_total = await db.payment_log.aggregate([
        {"$match": scoped({"transaction_status": {"$in": ["settlement", "capture"]}}, property_id)},
        {"$group": {"_id": None, "sum": {"$sum": {"$toDouble": "$gross_amount"}}, "count": {"$sum": 1}}},
    ]).to_list(1)
    payment_sum = int(payment_total[0]["sum"]) if payment_total else 0
    payment_count = payment_total[0]["count"] if payment_total else 0
    # Walk-in vs Online (bulan ini)
    online_bulan = await db.bookings.count_documents(scoped({
        "source": {"$in": ONLINE_BOOKING_SOURCES}, "created_at": {"$gte": month_start_iso},
    }, property_id))
    # Walk-in = check-ins langsung dari dashboard (tanpa booking online) bulan ini
    walk_bulan = await db.checkins.count_documents(scoped({
        "jam_checkin": {"$gte": month_start_iso},
    }, property_id))
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
async def cancellation_revenue(from_date: str, to_date: str, user: dict = Depends(get_current_user),
                               property_id: str = Depends(get_active_property)):
    """Pendapatan dari cancel fee (10% × total) + no-show retention (amount_due booking_paid yang jadi no_show).
    from_date/to_date: YYYY-MM-DD (inclusive).
    Returns: { cancel_fees_total, no_show_total, grand_total, by_day:[...], items:[...] }
    """
    try:
        start, end = wita_date_range_to_utc(from_date, to_date)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    cancels = await db.bookings.find(scoped({
        "status": "cancelled", "cancel_fee": {"$gt": 0},
        "cancelled_at": {"$gte": start, "$lte": end},
    }, property_id), {"_id": 0}).to_list(2000)
    no_shows = await db.bookings.find(scoped({
        "status": "no_show",
        "no_show_at": {"$gte": start, "$lte": end},
    }, property_id), {"_id": 0}).to_list(2000)
    cancel_total = sum(int(b.get("cancel_fee") or 0) for b in cancels)
    noshow_total = sum(int(b.get("amount_due") or 0) for b in no_shows)
    # group per hari (2026-08-09, tanggal WITA - bukan slice UTC mentah, lihat tanggal_wita())
    by_day: Dict[str, Dict[str, int]] = {}
    for b in cancels:
        if not b.get("cancelled_at"): continue
        day = tanggal_wita(b["cancelled_at"])
        by_day.setdefault(day, {"cancel_fee": 0, "no_show": 0})
        by_day[day]["cancel_fee"] += int(b.get("cancel_fee") or 0)
    for b in no_shows:
        if not b.get("no_show_at"): continue
        day = tanggal_wita(b["no_show_at"])
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
                                  user: dict = Depends(get_current_user),
                                  property_id: str = Depends(get_active_property)):
    """Aggregate service fee income:
    - checkin_service_fee: service_fee 3% dari checkins selesai (walk-in)
    - booking_service_fee: service_fee 3% dari bookings publik (payment_status=paid, source=online)
    - manual_services: layanan tambahan manual (nominal fleksibel dari staff)
    """
    start, end = wita_date_range_to_utc(from_date, to_date)

    # 1) service_fee 3% dari checkins (walk-in)
    ci = await db.checkins.find(
        scoped({"jam_checkout": {"$gte": start, "$lte": end}, "status": "selesai"}, property_id),
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

    # 2) service_fee 3% dari bookings SEMUA saluran (Menginap) yang sudah lunas
    # (2026-08-09, sama fix dgn report_summary/report_daily/report_rooms - filter
    # sebelumnya literal "online" saja, tidak mencakup "ota"/"whatsapp"/"whatsapp_auto").
    # TIDAK filter "source" + TAMBAH "status" != cancelled (2026-08-25, revisi lebih
    # dalam - lihat catatan lengkap di core.py & _hitung_pendapatan_harian).
    # checkin_id exists=False jg disertakan - booking day_use yang sudah check-in
    # service fee-nya SUDAH terhitung via checkin_items di atas, jangan dobel di sini.
    bk = await db.bookings.find(
        scoped({
            "jam_mulai": {"$gte": start, "$lte": end},
            "payment_status": "paid",
            "status": {"$ne": "cancelled"},
            "checkin_id": {"$exists": False},
        }, property_id),
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
            "source": b.get("source") or "online",
            "petugas": b.get("created_by") or "public",
        })

    # 3) manual services
    svc = await db.services.find(
        scoped({"tanggal": {"$gte": start, "$lte": end}}, property_id),
        {"_id": 0}
    ).sort("tanggal", -1).to_list(5000)
    manual_total = sum(int(s.get("nominal") or 0) for s in svc)

    # by_day breakdown (2026-08-09) - tanggal WITA, bukan slice UTC mentah, lihat tanggal_wita()
    def bucket(iso): return tanggal_wita(iso) if iso else ""
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
async def report_summary(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    # WITA boundaries (2026-08-07, bug nyata - Dashboard/Laporan dilaporkan "tidak sinkron"
    # oleh Agus) - endpoint ini (dipakai Dashboard utama) TERLEWAT dari audit WITA-boundary
    # sebelumnya hari ini (commit d8f4c3a) karena tidak punya query param from_date/to_date
    # spt endpoint /reports/* lain, jadi tidak kena pola "start = from_date" yang diaudit -
    # tapi tetap punya bug yang SAMA PERSIS: "hari ini"/"bulan ini" dihitung dari tanggal UTC
    # mentah, bukan WITA. Dini hari WITA (00:00-07:59 WITA = masih tanggal KEMARIN di UTC)
    # bikin Dashboard "ketinggalan" transaksi yang sudah masuk hitungan "hari ini" di Laporan
    # (yang sudah benar pakai WITA). Sama helper (wita_date_range_to_utc) yang sudah dipakai
    # endpoint /reports/* lain, cukup diberi tanggal WITA hari ini sbg from_date=to_date.
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    today_start_iso, today_end_iso = wita_date_range_to_utc(today_wita.isoformat(), today_wita.isoformat())
    month_start_wita = today_wita.replace(day=1)
    month_start_iso, _ = wita_date_range_to_utc(month_start_wita.isoformat(), month_start_wita.isoformat())
    today_iso = today_start_iso
    month_start = month_start_iso
    today_date = today_wita
    today_start_dt = datetime.fromisoformat(today_start_iso)
    today_end_dt = today_start_dt + timedelta(days=1)

    # (2026-08-09, refactor - permintaan Agus "contek sistem penghitungan POS profesional
    # spt Majoo, data akurat") - pendapatan/pengeluaran SEKARANG dari SATU pemanggilan
    # _hitung_pendapatan_harian (mesin yang SAMA PERSIS dipakai /reports/daily) utk
    # rentang bulan-berjalan, bukan gather 9 query terpisah dgn formula sendiri lagi -
    # angka "hari ini" tinggal diambil sbg 1 baris dari situ, "bulan ini" dijumlah dari
    # semua baris - dijamin selalu identik dgn Ringkasan utk rentang tanggal yang sama.
    # 5 query di bawah tetap independen & paralel (asyncio.gather) - rooms/okupansi/
    # jumlah kedatangan TIDAK terkait pendapatan sama sekali, tetap query langsung.
    (
        rooms, today_bookings, ci_today, co_today, by_day_month,
    ) = await asyncio.gather(
        db.rooms.find(scoped({}, property_id), {"_id": 0}).to_list(500),
        db.bookings.find(scoped({
            "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
            "jam_mulai": {"$lt": today_end_dt.isoformat()},
            "jam_selesai": {"$gt": today_start_dt.isoformat()},
        }, property_id), {"_id": 0, "room_id": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(500),
        db.checkins.find(scoped({"jam_checkin": {"$gte": today_iso}}, property_id), {"_id": 0}).to_list(500),
        db.checkins.find(scoped({"jam_checkout": {"$gte": today_iso}, "status": "selesai"}, property_id), {"_id": 0}).to_list(500),
        _hitung_pendapatan_harian(month_start_wita.isoformat(), today_wita.isoformat(), property_id),
    )

    counts = {"kosong": 0, "day_use": 0, "menginap": 0, "perlu_dibersihkan": 0, "maintenance": 0, "dipesan_hari_ini": 0}
    # Kamar berstatus "kosong" tapi SUDAH ada booking (aktif/booking_pending/booking_paid) yang
    # menempati hari ini dihitung sebagai "dipesan_hari_ini", BUKAN "kosong" — sebelumnya kartu
    # "Kosong" di Dashboard murni baca `room.status` real-time, jadi tidak pernah berkurang
    # walau sudah ada booking OTA/walk-in untuk hari ini (room.status baru berubah setelah
    # tamu benar-benar di-check-in, lihat checkin_from_booking di routes/bookings.py). Rentang
    # tanggal sama seperti _occupies_date (routes/ketersediaan.py): [checkin_date, checkout_date)
    # exclusive checkout, kecuali day-use (checkin=checkout, tetap terhitung).
    rooms_dipesan_hari_ini = set()
    for b in today_bookings:
        # .date() di sini WAJIB dari waktu WITA, bukan UTC mentah (2026-08-07, sama fix
        # dgn today_date di atas) - `today_date` sekarang WITA, jadi sisi kanan perbandingan
        # ini harus konsisten WITA juga, bukan dibandingkan silang dgn tanggal UTC.
        b_start = parse_iso(b["jam_mulai"], "jam_mulai").astimezone(timezone(timedelta(hours=8))).date()
        b_end = parse_iso(b["jam_selesai"], "jam_selesai").astimezone(timezone(timedelta(hours=8))).date()
        occupies_today = today_date == b_start if b_start == b_end else b_start <= today_date < b_end
        if occupies_today:
            rooms_dipesan_hari_ini.add(b["room_id"])
    for r in rooms:
        status = r.get("status", "kosong")
        if status == "kosong" and r["id"] in rooms_dipesan_hari_ini:
            counts["dipesan_hari_ini"] += 1
        else:
            counts[status] = counts.get(status, 0) + 1
    # Pendapatan & pengeluaran (2026-08-09, lihat komentar di gather di atas) - "hari
    # ini" tinggal 1 baris dari by_day_month (default nol kalau belum ada transaksi sama
    # sekali hari ini), "bulan ini" dijumlah dari semua baris - SATU sumber angka yang
    # sama persis dgn /reports/daily (Ringkasan) & /reports/rooms utk rentang yang sama,
    # bukan dihitung ulang pakai formula sendiri (paid_at/jam_checkout) lagi seperti
    # sebelumnya - itulah akar masalah "Dashboard tidak sinkron dengan Ringkasan".
    _init_kosong = {"kamar": 0, "makanan": 0, "minuman": 0, "laundry": 0, "service": 0, "pengeluaran": 0}
    today_row = by_day_month.get(today_wita.isoformat(), _init_kosong)
    rev_kasir_today = today_row["makanan"] + today_row["minuman"] + today_row["laundry"]
    rev_per_kat = {"makanan": today_row["makanan"], "minuman": today_row["minuman"], "laundry": today_row["laundry"]}
    rev_svc_today = today_row["service"]
    total_exp_today = today_row["pengeluaran"]
    rev_month = sum(r["kamar"] + r["makanan"] + r["minuman"] + r["laundry"] + r["service"] for r in by_day_month.values())
    rev_svc_month = sum(r["service"] for r in by_day_month.values())
    total_exp_month = sum(r["pengeluaran"] for r in by_day_month.values())
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
        "pendapatan_hari_ini": today_row["kamar"] + rev_kasir_today + rev_svc_today,
        "pendapatan_kamar_hari_ini": today_row["kamar"],
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
async def report_kedatangan_harian(user: dict = Depends(get_current_user), property_id: str = Depends(get_active_property)):
    """Jumlah kedatangan tamu per hari, 30 hari terakhir (2026-07-21, permintaan user -
    grafik tren kedatangan di Dashboard utama). Sumber utama `db.bookings.jam_mulai`
    (tanggal check-in) - booking `cancelled` dikecualikan (tidak pernah benar-benar
    datang). Dihitung per booking (1 booking = 1 "kedatangan", konsisten dgn cara kamar
    dihitung terisi/tidaknya), bukan per kepala (jumlah_tamu) - lebih mudah dibaca staf
    sebagai tren reservasi.

    `db.checkins` TANPA `from_booking_id` (2026-08-02, bug nyata ditemukan Agus - grafik
    ini kelihatan sangat undercount, dilaporkan sbg "data tidak sinkron"/"harusnya
    nampilin kedatangan day use juga") DITAMBAHKAN ke hitungan, dikunci per `jam_checkin`.
    Asumsi lama dokumentasi ini ("db.checkins jarang terisi") sudah TIDAK BENAR lagi -
    audit 2026-08-02 menemukan 25 check-in walk-in day use murni cuma dalam 2 hari
    (1-2 Agustus), SEMUANYA hilang dari grafik ini krn walk-in Quick Book (staf pilih
    kamar kosong -> langsung isi tamu Day Use) TIDAK PERNAH membuat dokumen di
    `db.bookings` sama sekali, cuma di `db.checkins`. Checkins YANG PUNYA `from_booking_id`
    (asal dari booking WA AI/online yang staf check-in-kan) SENGAJA DILEWATI di sini -
    tamu itu sudah terhitung dari sisi `db.bookings`-nya, ikut dihitung lagi jadi dobel."""
    # (2026-08-09) "hari ini" WAJIB dari WITA, bukan UTC mentah - sama fix dgn
    # report_summary (2026-08-07) - dini hari WITA (00:00-07:59) masih tanggal UTC
    # KEMARIN, geser jendela 30 hari ini off-by-one kalau dibiarkan.
    end_date = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    start_date = end_date - timedelta(days=29)
    start_dt_iso, _ = wita_date_range_to_utc(start_date.isoformat(), start_date.isoformat())
    bookings = await db.bookings.find(scoped({
        "status": {"$ne": "cancelled"},
        "jam_mulai": {"$gte": start_dt_iso},
    }, property_id), {"_id": 0, "jam_mulai": 1, "tipe": 1}).to_list(5000)
    walkin_checkins = await db.checkins.find(scoped({
        "from_booking_id": None,
        "jam_checkin": {"$gte": start_dt_iso},
    }, property_id), {"_id": 0, "jam_checkin": 1, "tipe": 1}).to_list(5000)
    # Pisah Day Use vs Menginap (2026-08-03, permintaan Agus - grafik ini sebelumnya cuma
    # 1 angka gabungan per tanggal, staf tidak bisa lihat komposisi tipe kedatangan).
    per_tanggal: Dict[str, Dict[str, int]] = {}
    def _tambah(tgl: str, tipe: Optional[str]):
        row = per_tanggal.setdefault(tgl, {"day_use": 0, "menginap": 0})
        if tipe == "menginap":
            row["menginap"] += 1
        else:
            row["day_use"] += 1  # checkins walk-in TIDAK selalu punya field tipe eksplisit, default Day Use (mayoritas kasus nyata)
    for b in bookings:
        try:
            tgl = tanggal_wita(b["jam_mulai"])  # (2026-08-09) tanggal WITA, bukan .date() UTC mentah
        except Exception:
            continue
        _tambah(tgl, b.get("tipe"))
    for c in walkin_checkins:
        try:
            tgl = tanggal_wita(c["jam_checkin"])
        except Exception:
            continue
        _tambah(tgl, c.get("tipe"))
    out = []
    for i in range(30):
        d = (start_date + timedelta(days=i)).isoformat()
        row = per_tanggal.get(d, {"day_use": 0, "menginap": 0})
        out.append({
            "tanggal": d, "day_use": row["day_use"], "menginap": row["menginap"],
            "jumlah": row["day_use"] + row["menginap"],
        })
    return out


async def _hitung_pendapatan_harian(from_date: str, to_date: str, property_id: str) -> Dict[str, Dict[str, int]]:
    """Mesin pendapatan harian TUNGGAL (2026-08-09, permintaan Agus - "contek sistem
    penghitungan POS lain seperti Majoo... agar terlihat profesional dan data akurat").

    Sebelum ini, /reports/summary (Dashboard) menghitung pendapatan "hari ini"/"bulan
    ini" pakai formula SENDIRI (booking dibucket per `paid_at` - tanggal uang MASUK, dan
    walk-in dibucket per `jam_checkout` - tanggal PULANG), sementara /reports/daily
    (Ringkasan) & /reports/rooms sudah lebih dulu pakai formula berbeda (booking Menginap
    diakui per MALAM INAP/accrual dari tanggal KEDATANGAN, walk-in dibucket per
    `jam_checkin`) - DUA formula independen utk pertanyaan yang seharusnya sama ("berapa
    pendapatan periode ini"), makanya Dashboard & Ringkasan tidak pernah sinkron.

    Standar akuntansi hospitality yang benar (dipakai PMS profesional spt Cloudbeds/
    Mews/Majoo) - REVENUE RECOGNITION by SERVICE DATE (matching principle: pendapatan
    diakui saat jasanya benar-benar dikonsumsi/malam kamar terpakai), BUKAN tanggal uang
    diterima (`paid_at` - itu laporan ARUS KAS, konsep akuntansi berbeda, sengaja TIDAK
    dipakai di sini). Formula /reports/daily yang lebih dulu benar itulah yang jadi mesin
    tunggal ini - report_daily & report_summary SEKARANG memanggil fungsi yang SAMA
    PERSIS, bukan menghitung ulang sendiri-sendiri, supaya Dashboard & Ringkasan selalu
    menunjukkan angka yang identik untuk rentang tanggal yang sama (satu sumber
    kebenaran, prinsip #1 sistem pelaporan profesional).

    Kasir (POS) SENGAJA tetap dibucket per `timestamp` transaksi apa adanya (bukan
    accrual) - itu memang standar POS: barang/jasa kasir (makanan/minuman/laundry)
    dikonsumsi SAAT itu juga, tidak ada konsep "malam terpakai" spt kamar.

    checkin_id exists=False di query booking (2026-08-09) - booking yang SUDAH punya
    dokumen checkins sendiri (Day Use yang sudah check-in) TIDAK ikut dihitung di sini
    lagi, supaya tidak double-count dengan `ci` di bawah - lihat detail insiden nyata di
    commit yang menambahkan filter ini."""
    start, end = wita_date_range_to_utc(from_date, to_date)
    # Walk-in (checkins) dibucket per jam_checkin (tanggal KEDATANGAN), bukan
    # jam_checkout (2026-08-07, keputusan Agus - konsisten "tanggal 7" berarti tamu yg
    # DATANG tanggal 7, bukan yg pulang tanggal 7 - insiden nyata tamu Day Use lewat
    # tengah malam ikut ke laporan tanggal yang salah).
    ci = await db.checkins.find(scoped({"jam_checkin": {"$gte": start, "$lte": end}, "status": "selesai"}, property_id), {"_id": 0}).to_list(5000)
    # TIDAK filter "source" lagi (2026-08-25, revisi lebih dalam dari fix MENGINAP_REVENUE_
    # SOURCES sebelumnya hari ini - permintaan Agus "dalami akar masalahnya, agar semua
    # aman") - allowlist source ("ota"/"online"/"whatsapp"/dst) TERBUKTI 2x kebobolan
    # (whatsapp_auto 2026-08-09, whatsapp_request+walk_in 2026-08-25) tiap kali ada
    # channel/rename source BARU yang lupa didaftarkan - kelas bug yang SAMA akan terulang
    # lagi kalau suatu saat muncul channel baru (mis. Instagram DM, OTA lain). Query ini
    # SUDAH punya jaminan anti-double-count yang benar (checkin_id belum ada = belum
    # dikonversi ke checkins), jadi filter source itu sendiri TIDAK PERNAH benar2
    # diperlukan utk tujuan "hitung SEMUA pendapatan Menginap yang sah" - dihapus total,
    # bukan ditambal lagi.
    #
    # "status" != cancelled DITAMBAHKAN (bug KEDUA ditemukan sambil audit sama, arah
    # SEBALIKNYA - KELEBIHAN hitung): 7 booking (Rp1.003.000) berstatus "cancelled" TAPI
    # payment_status masih "paid" ditemukan nyata di DB - beberapa jalur cancel yang
    # BEDA (cancel_with_fee sudah benar reset ke refunded/forfeited, tapi auto-cancel OTA
    # di otomasi_email.py & beberapa koreksi manual/dedup RedDoorz TIDAK PERNAH menyentuh
    # payment_status sama sekali) - query lama disini TIDAK PERNAH cek `status`, jadi
    # booking yang sudah dibatalkan tapi kebetulan masih payment_status=paid dari sebelum
    # dibatalkan tetap ikut terhitung sbg pendapatan asli. Drpd kejar-kejaran memperbaiki
    # SETIAP jalur cancel (rapuh, gampang ada yg kelewat lagi) - filter di SISI BACA ini
    # (satu titik, dipakai semua laporan) yang ditutup, jaminan yang lebih kuat drpd
    # bergantung semua jalur tulis selalu ingat reset payment_status.
    bk = await db.bookings.find(scoped({
        "payment_status": "paid",
        "status": {"$ne": "cancelled"},
        "jam_mulai": {"$lte": end},
        "jam_selesai": {"$gte": start},
        "ota_harga_dikonfirmasi": {"$ne": False},
        "checkin_id": {"$exists": False},
    }, property_id), {"_id": 0, "total": 1, "jam_mulai": 1, "jam_selesai": 1}).to_list(5000)
    ks = await db.kasir.find(scoped({"timestamp": {"$gte": start, "$lte": end}}, property_id), {"_id": 0}).to_list(5000)
    ex = await db.expenses.find(scoped({"tanggal": {"$gte": start, "$lte": end}}, property_id), {"_id": 0}).to_list(5000)
    sv = await db.services.find(scoped({"tanggal": {"$gte": start, "$lte": end}}, property_id), {"_id": 0}).to_list(5000)
    by_day: Dict[str, Dict[str, int]] = {}
    bucket = tanggal_wita  # (2026-08-09) konversi ke tanggal KALENDER WITA, bukan slice UTC mentah - lihat docstring tanggal_wita() di core.py
    def _init(): return {"kamar": 0, "makanan": 0, "minuman": 0, "laundry": 0, "service": 0, "pengeluaran": 0}
    for c in ci:
        d = bucket(c["jam_checkin"])
        by_day.setdefault(d, _init())
        by_day[d]["kamar"] += c.get("total", 0)
    for b in bk:
        total = int(b.get("total") or 0)
        jm, js = b.get("jam_mulai"), b.get("jam_selesai")
        if not jm or not js:
            continue
        d0 = datetime.fromisoformat(tanggal_wita(jm)).date()
        d1 = datetime.fromisoformat(tanggal_wita(js)).date()
        nights = max(1, (d1 - d0).days)
        per_night = total / nights
        for i in range(nights):
            d = (d0 + timedelta(days=i)).isoformat()
            if d < from_date or d > to_date:
                continue
            by_day.setdefault(d, _init())
            by_day[d]["kamar"] += round(per_night)
    for k in ks:
        d = bucket(k["timestamp"])
        by_day.setdefault(d, _init())
        for it in k.get("items", []):
            by_day[d][it["kategori"]] += it["subtotal"]
    for s in sv:
        tgl_raw = s.get("tanggal")
        if not tgl_raw: continue
        d = bucket(tgl_raw)
        by_day.setdefault(d, _init())
        by_day[d]["service"] += int(s.get("nominal") or 0)
    for e in ex:
        tgl_raw = e.get("tanggal")
        if not tgl_raw: continue
        d = bucket(tgl_raw)
        by_day.setdefault(d, _init())
        by_day[d]["pengeluaran"] += e.get("nominal", 0)
    return by_day


@api.get("/reports/daily")
async def report_daily(from_date: str = Query(...), to_date: str = Query(...),
                       user: dict = Depends(get_current_user),
                       property_id: str = Depends(get_active_property)):
    """Return per-day revenue between dates (inclusive). Dates: YYYY-MM-DD. Formula
    lengkap (accrual malam-inap, dibucket per tanggal kedatangan) ada di
    _hitung_pendapatan_harian - SATU sumber kebenaran, dipakai juga oleh
    /reports/summary (Dashboard) supaya kedua laporan selalu sinkron."""
    by_day = await _hitung_pendapatan_harian(from_date, to_date, property_id)
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
                                  user: dict = Depends(get_current_user),
                                  property_id: str = Depends(get_active_property)):
    """Rekap uang masuk per metode bayar (Tunai/QRIS/Transfer) dari Kasir (POS) & Check-In
    (walk-in) — supaya owner bisa cocokkan uang cash fisik yang harus ada di laci vs sistem.
    SENGAJA tidak termasuk booking online/OTA (Tripay) karena uangnya masuk ke rekening/payment
    gateway, tidak pernah melewati laci fisik — lihat /reports/daily untuk total pendapatan
    kamar yang mencakup semua saluran."""
    start, end = wita_date_range_to_utc(from_date, to_date)
    totals = {"tunai": 0, "qris": 0, "transfer": 0}
    ks = await db.kasir.find(scoped({"timestamp": {"$gte": start, "$lte": end}}, property_id), {"_id": 0, "pembayaran": 1}).to_list(5000)
    ci = await db.checkins.find(
        scoped({"status": "selesai", "jam_checkout": {"$gte": start, "$lte": end}}, property_id),
        {"_id": 0, "pembayaran": 1},
    ).to_list(5000)
    for row in ks + ci:
        for p in row.get("pembayaran") or []:
            m = p.get("metode")
            if m in totals:
                totals[m] += int(p.get("jumlah") or 0)
    return {**totals, "total": sum(totals.values())}


@api.get("/reports/arus-kas")
async def report_arus_kas(from_date: str = Query(...), to_date: str = Query(...),
                          user: dict = Depends(get_current_user),
                          property_id: str = Depends(get_active_property)):
    """Laporan Arus Kas / Payment Report (2026-08-09, permintaan Agus - "contek sistem
    POS profesional spt Majoo, buat versi terbaik" setelah /reports/daily & /reports/
    summary disatukan ke akrual per tanggal KEDATANGAN/malam-inap).

    Sengaja TERPISAH dari /reports/daily - PMS profesional (Cloudbeds/Mews/Opera) selalu
    punya DUA laporan berbeda yang boleh menunjukkan angka BEDA tanpa itu jadi bug:
    - "Revenue Report" (di sini: /reports/daily) = pendapatan diakui per malam TERPAKAI
      (akrual, matching principle) - "berapa yang KAMI HASILKAN periode ini".
    - "Payment/Cash Flow Report" (endpoint INI) = uang yang BENAR-BENAR DITERIMA per
      tanggal transaksi bayar terjadi (cash basis) - "berapa UANG YANG MASUK periode
      ini". DP yang diterima bulan lalu utk booking yang menginap bulan ini MUNCUL DI
      SINI bulan lalu, bukan bulan ini - kebalikan dari /reports/daily.

    3 sumber uang masuk, masing2 dibucket per tanggal SUNGGUHAN transaksi bayar terjadi:
    1. `online` - pembayaran gateway (Tripay QRIS/VA, DP maupun pelunasan/collect-balance
       maupun verifikasi manual staf) dari `payment_log`, HANYA status settlement/capture
       (bukan pending/expired) - dibucket per `updated_at` (saat callback/staf BENAR-BENAR
       mengonfirmasi settlement), BUKAN `created_at` (itu cuma saat link/invoice dibuat -
       tamu bisa bayar berjam-jam/berhari-hari kemudian, beda tanggal kalau pakai created_at).
    2. `kamar_tunai_langsung` - bagian FISIK (cash/QR di lokasi, BUKAN online) dari
       `checkins.pembayaran`, dibucket per `jam_checkout` (saat transaksi kamar itu
       benar2 tutup/lunas). Utk checkin yang berasal dari booking (`from_booking_id`
       terisi), porsi `booking_paid` (DP online yang sudah lebih dulu dihitung di
       `online` di atas) DIKURANGI dari total pembayaran checkin ini - supaya TIDAK
       double-count DP yang sama muncul di 2 bucket. Sisanya (kalau ada) murni uang
       fisik BARU yang dikumpulkan staf saat check-in/checkout (tarif dasar walk-in,
       atau sisa/overtime yang dibayar cash).
    3. `kasir` - transaksi POS (makanan/minuman/laundry), dibucket per `timestamp`
       transaksi - tidak ada ambiguitas, konsumsi & bayar terjadi bersamaan.

    Booking Menginap yang BELUM check-in/checkout (msh `booking_paid`) - DP-nya TETAP
    muncul di sini (via payment_log) begitu settlement, walau kamarnya belum terpakai
    sama sekali - itu memang inti bedanya dari /reports/daily (akrual nunggu jasa
    terpakai, cash flow tidak nunggu apa-apa selain uang beneran diterima).

    4. Cash booking Menginap WALK-IN (2026-08-25, laporan Agus - "Arus Kas beda dgn
       Dashboard", ditemukan lewat audit lanjutan setelah fix pendapatan kamar hari ini)
       - booking Quick Book staf (source="walk_in") "bayar di depan semua" (2026-07-31)
       menyimpan `pembayaran` LANGSUNG di dokumen `bookings` sendiri (bukan lewat Tripay/
       payment_log SAMA SEKALI - itu jalur khusus gateway online). 3 sumber di atas TIDAK
       ADA yang pernah baca field ini: bukan `payment_log` (bukan gateway), bukan
       `checkins.pembayaran` (Menginap TIDAK PERNAH bikin dokumen checkins, beda dari
       day_use - lihat catatan checkin_from_booking di routes/bookings.py). Akibatnya
       Rp2.260.850 uang tunai asli (12 booking) sama sekali tidak pernah muncul di Arus
       Kas - PERSIS efek yang sama dgn bug pendapatan kamar yang baru diperbaiki hari
       ini, cuma di laporan yang beda. Dibucket per `created_at` (saat Quick Book
       disubmit - itu momen uang FISIK diterima staf, konsisten dgn semangat cash-basis
       laporan ini), bukan `paid_at` (kosong kalau baru DP/belum lunas penuh saat itu -
       created_at selalu ada & selalu = momen pembayaran itu tercatat). `checkin_id`
       belum ada (guard SAMA persis dgn fix pendapatan kamar) - kalau booking ini
       kemudian di-checkin sbg day_use (checkin_id terisi), pembayarannya sudah
       tercakup via `ci`/`kamar_tunai_langsung` di atas, jangan dobel di sini."""
    start, end = wita_date_range_to_utc(from_date, to_date)
    logs, ci, ks, bk_cash = await asyncio.gather(
        db.payment_log.find(scoped({
            "transaction_status": {"$in": ["settlement", "capture"]},
            "updated_at": {"$gte": start, "$lte": end},
        }, property_id), {"_id": 0, "gross_amount": 1, "updated_at": 1}).to_list(5000),
        db.checkins.find(scoped({
            "jam_checkout": {"$gte": start, "$lte": end}, "status": "selesai",
        }, property_id), {"_id": 0, "jam_checkout": 1, "pembayaran": 1, "from_booking_id": 1, "booking_paid": 1}).to_list(5000),
        db.kasir.find(scoped({"timestamp": {"$gte": start, "$lte": end}}, property_id), {"_id": 0, "timestamp": 1, "total": 1}).to_list(5000),
        db.bookings.find(scoped({
            "pembayaran": {"$exists": True, "$ne": []},
            "checkin_id": {"$exists": False},
            "status": {"$ne": "cancelled"},
            "created_at": {"$gte": start, "$lte": end},
        }, property_id), {"_id": 0, "created_at": 1, "pembayaran": 1}).to_list(5000),
    )
    by_day: Dict[str, Dict[str, int]] = {}
    bucket = tanggal_wita  # (2026-08-09) tanggal KALENDER WITA, bukan slice UTC mentah - lihat core.py
    def _init(): return {"online": 0, "kamar_tunai_langsung": 0, "kasir": 0}
    for log in logs:
        d = bucket(log["updated_at"])
        by_day.setdefault(d, _init())
        by_day[d]["online"] += int(float(log.get("gross_amount") or 0))
    for c in ci:
        d = bucket(c["jam_checkout"])
        by_day.setdefault(d, _init())
        total_bayar = sum(int(p.get("jumlah", 0)) for p in c.get("pembayaran") or [])
        online_portion = int(c.get("booking_paid") or 0) if c.get("from_booking_id") else 0
        by_day[d]["kamar_tunai_langsung"] += max(0, total_bayar - online_portion)
    for b in bk_cash:
        d = bucket(b["created_at"])
        by_day.setdefault(d, _init())
        by_day[d]["kamar_tunai_langsung"] += sum(int(p.get("jumlah", 0)) for p in b.get("pembayaran") or [])
    for k in ks:
        d = bucket(k["timestamp"])
        by_day.setdefault(d, _init())
        by_day[d]["kasir"] += k.get("total", 0)
    result = []
    for d in sorted(by_day.keys()):
        row = by_day[d]
        result.append({"tanggal": d, **row, "total_uang_masuk": row["online"] + row["kamar_tunai_langsung"] + row["kasir"]})
    return result

_PAYMENT_OPTION_JENIS = {"dp50": "DP", "full": "Lunas", "collect_balance": "Pelunasan", "manual": "Lunas (Manual)"}

async def _ambil_detail_pembayaran_booking(booking_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Rincian DP/pelunasan per booking (2026-08-02, permintaan Agus - Laporan Kamar
    perlu tunjukkan tamu DP berapa via cash/Tripay & pelunasannya ditagih di sistem
    pakai cash/QR atau lainnya), dari payment_log (sumber kebenaran tiap event bayar
    sungguhan - Tripay create-transaction/webhook, collect-balance staf, atau verifikasi
    manual) - HANYA entri yang benar settlement (transaction_status=="settlement"),
    bukan yang masih pending/belum terbayar."""
    if not booking_ids:
        return {}
    logs = await db.payment_log.find({
        "booking_id": {"$in": booking_ids}, "transaction_status": "settlement",
    }, {"_id": 0, "booking_id": 1, "payment_option": 1, "payment_type": 1, "gross_amount": 1, "created_at": 1}).sort("created_at", 1).to_list(2000)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for l in logs:
        bid = l.get("booking_id")
        if not bid:
            continue
        jenis = _PAYMENT_OPTION_JENIS.get(l.get("payment_option"), l.get("payment_option") or "Bayar")
        out.setdefault(bid, []).append({
            "jenis": jenis, "metode": l.get("payment_type") or "-",
            "jumlah": int(float(l.get("gross_amount") or 0)),
        })
    return out

def _detail_pembayaran_checkin(c: Dict[str, Any], booking_payment_option: Optional[str]) -> List[Dict[str, Any]]:
    """Utk walk-in Day Use (db.checkins) - field `pembayaran` sudah berisi rincian
    (seeded dari booking asal kalau ada + apapun yang dikumpulkan staf saat checkout,
    lihat fix bug dobel-tagih 2026-08-02 di checkin_from_booking). Entri PERTAMA =
    yang sudah dibayar sebelum/saat check-in (DP kalau booking asalnya dp50, else
    Lunas/Tunai) - entri SESUDAHNYA = dikumpulkan staf saat checkout (Pelunasan)."""
    pembayaran = c.get("pembayaran") or []
    out = []
    for i, p in enumerate(pembayaran):
        if i == 0:
            jenis = "DP" if booking_payment_option == "dp50" else "Lunas"
        else:
            jenis = "Pelunasan"
        out.append({"jenis": jenis, "metode": p.get("metode") or "-", "jumlah": int(p.get("jumlah") or 0)})
    return out

@api.get("/reports/rooms")
async def report_rooms(from_date: str = Query(...), to_date: str = Query(...),
                       user: dict = Depends(get_current_user),
                       property_id: str = Depends(get_active_property)):
    """Transaksi kamar walk-in (checkins) DIGABUNG booking online/OTA/WhatsApp yang sudah
    lunas (bookings, dibucket per paid_at) — sebelumnya cuma checkins, bikin RedDoorz/booking
    online tidak pernah terhitung di "Total Transaksi" & pendapatan kamar.

    (2026-08-09, KOREKSI - lihat komentar lengkap di report_summary) klaim lama "tidak ada
    duplikasi... dua alur guest-arrival independen" SALAH utk day_use: query `bk` di bawah
    exclude `checkin_id` yang sudah terisi supaya booking yang sudah check-in (revenue-nya
    sudah tercakup via `items`/checkins di atas) tidak ikut dihitung dobel di sini.

    `detail_pembayaran` per item (2026-08-02, permintaan Agus) - rincian DP/pelunasan
    & metode-nya (cash/Tripay/QR/dll), lihat _ambil_detail_pembayaran_booking &
    _detail_pembayaran_checkin.

    Basis TANGGAL KEDATANGAN (jam_checkin/jam_mulai), BUKAN checkout/paid_at (2026-08-07,
    permintaan Agus - bug nyata dilaporkan: tamu Gede Widana & Sangtu Satria check-in
    tanggal 6, check-out tanggal 7 (Day Use lewat tengah malam) - ikut ke laporan tanggal
    7 padahal Agus mengharapkan cuma tamu yg BENAR-BENAR datang tanggal itu ("harusnya
    cuma 3 transaksi"). Keputusan bisnis eksplisit dari Agus - laporan ini soal "siapa
    yang datang hari ini", bukan akuntansi accrual (beda dari report_daily yg tetap
    pakai malam-inap utk booking Menginap lintas hari, itu keputusan terpisah)."""
    start, end = wita_date_range_to_utc(from_date, to_date)
    items = await db.checkins.find(
        scoped({"jam_checkin": {"$gte": start, "$lte": end}, "status": "selesai"}, property_id),
        {"_id": 0}
    ).to_list(5000)
    # TIDAK filter "source" + TAMBAH "status" != cancelled (2026-08-25, sama fix dgn
    # _hitung_pendapatan_harian - lihat catatan lengkap di core.py & docstring atas).
    bk = await db.bookings.find(scoped({
        "payment_status": "paid",
        "status": {"$ne": "cancelled"},
        "jam_mulai": {"$gte": start, "$lte": end},
        "ota_harga_dikonfirmasi": {"$ne": False},
        "checkin_id": {"$exists": False},
    }, property_id), {"_id": 0}).to_list(5000)
    # Booking asal utk checkins yang berasal dari booking (perlu payment_option-nya
    # utk tahu entri pertama pembayaran itu DP atau Lunas) + payment_log utk semua
    # booking (baik yg langsung tampil sbg booking_items maupun yg jadi asal checkins).
    from_booking_ids = [c["from_booking_id"] for c in items if c.get("from_booking_id")]
    asal_bookings = {}
    if from_booking_ids:
        docs = await db.bookings.find({"id": {"$in": from_booking_ids}}, {"_id": 0, "id": 1, "payment_option": 1}).to_list(2000)
        asal_bookings = {d["id"]: d for d in docs}
    all_booking_ids = list({*(b["id"] for b in bk), *from_booking_ids})
    detail_map = await _ambil_detail_pembayaran_booking(all_booking_ids)
    for c in items:
        fbid = c.get("from_booking_id")
        payment_option = asal_bookings.get(fbid, {}).get("payment_option") if fbid else None
        c["detail_pembayaran"] = _detail_pembayaran_checkin(c, payment_option)
    booking_items = [{
        "id": b["id"], "trx_no": b.get("kode"),
        "nama_tamu": b.get("nama_tamu"), "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
        "jam_checkin": b.get("jam_mulai"), "jam_checkout": b.get("jam_selesai"),
        "jumlah_tamu": b.get("jumlah_tamu", 1),
        "tarif_dasar": b.get("subtotal", 0), "biaya_tambahan": 0, "total": b.get("total", 0),
        "petugas_checkout": b.get("created_by") or b.get("source"),
        "source": b.get("source"),
        "detail_pembayaran": detail_map.get(b["id"], []),
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
                              user: dict = Depends(get_current_user),
                              property_id: str = Depends(get_active_property)):
    start, end = wita_date_range_to_utc(from_date, to_date)
    trxs = await db.kasir.find(
        scoped({"timestamp": {"$gte": start, "$lte": end}}, property_id),
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
                            user: dict = Depends(get_current_user),
                            property_id: str = Depends(get_active_property)):
    start, end = wita_date_range_to_utc(from_date, to_date)
    trxs = await db.kasir.find(scoped({"timestamp": {"$gte": start, "$lte": end}}, property_id), {"_id": 0}).to_list(5000)
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
                              user: dict = Depends(get_current_user),
                              property_id: str = Depends(get_active_property)):
    """period: today | month | year"""
    # (2026-08-09) "today"/"month"/"year" WAJIB dari tanggal WITA, bukan UTC mentah -
    # sama fix dgn report_summary (2026-08-07) - dini hari WITA (00:00-07:59) masih
    # tanggal UTC KEMARIN, geser batas periode ini off-by-one kalau dibiarkan.
    today_wita = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    if period == "today":
        start, _ = wita_date_range_to_utc(today_wita.isoformat(), today_wita.isoformat())
    elif period == "year":
        start, _ = wita_date_range_to_utc(today_wita.replace(month=1, day=1).isoformat(), today_wita.replace(month=1, day=1).isoformat())
    else:
        start, _ = wita_date_range_to_utc(today_wita.replace(day=1).isoformat(), today_wita.replace(day=1).isoformat())
    trxs = await db.kasir.find(scoped({"timestamp": {"$gte": start}}, property_id), {"_id": 0}).to_list(10000)
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
                        user: dict = Depends(get_current_user),
                        property_id: str = Depends(get_active_property)):
    """Laporan aktivitas per petugas per hari. Sistem ini tidak punya konsep clock-in/out
    shift asli — laporan ini dirangkum dari jejak petugas yang sudah tercatat di tiap modul
    (kasir, check-in/out, pengeluaran, housekeeping), dikelompokkan per tanggal + nama
    petugas, supaya owner tetap bisa melihat kontribusi/aktivitas tiap staf per hari."""
    start, end = wita_date_range_to_utc(from_date, to_date)

    def bucket(iso: str) -> str:
        # (2026-08-09) tanggal WITA, bukan slice UTC mentah - lihat tanggal_wita() di core.py
        return tanggal_wita(iso) if iso else ""

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
        scoped({"timestamp": {"$gte": start, "$lte": end}}, property_id), {"_id": 0, "timestamp": 1, "petugas": 1, "total": 1}
    ).to_list(10000)
    for k in kasir_docs:
        r = row(bucket(k.get("timestamp")), k.get("petugas"))
        r["kasir_count"] += 1
        r["kasir_total"] += int(k.get("total") or 0)

    checkin_docs = await db.checkins.find(
        scoped({"jam_checkin": {"$gte": start, "$lte": end}}, property_id), {"_id": 0, "jam_checkin": 1, "petugas_checkin": 1}
    ).to_list(10000)
    for c in checkin_docs:
        r = row(bucket(c.get("jam_checkin")), c.get("petugas_checkin"))
        r["checkin_count"] += 1

    checkout_docs = await db.checkins.find(
        scoped({"jam_checkout": {"$gte": start, "$lte": end}}, property_id), {"_id": 0, "jam_checkout": 1, "petugas_checkout": 1, "total": 1}
    ).to_list(10000)
    for c in checkout_docs:
        if not c.get("jam_checkout"):
            continue
        r = row(bucket(c["jam_checkout"]), c.get("petugas_checkout"))
        r["checkout_count"] += 1
        r["checkout_total"] += int(c.get("total") or 0)

    expense_docs = await db.expenses.find(
        scoped({"tanggal": {"$gte": start, "$lte": end}}, property_id), {"_id": 0, "tanggal": 1, "user": 1, "nominal": 1}
    ).to_list(10000)
    for e in expense_docs:
        r = row(bucket(e.get("tanggal")), e.get("user"))
        r["expense_count"] += 1
        r["expense_total"] += int(e.get("nominal") or 0)

    hk_docs = await db.housekeeping_log.find(
        scoped({"jam_selesai": {"$gte": start, "$lte": end}, "status": "selesai"}, property_id), {"_id": 0, "jam_selesai": 1, "petugas": 1}
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
