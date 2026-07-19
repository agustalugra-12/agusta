from core import *
from reservation_service import check_room_available, create_reservation, room_locks
from email_service import generate_voucher_pdf, send_voucher_email
from routes.push import send_push
from scheduling_engine import slot_dayuse_aman
import httpx
import io
from fastapi.responses import StreamingResponse

def _booking_date_range(start: datetime, end: datetime):
    """Rentang TANGGAL [start_date, end_date_exclusive) yang benar-benar ditempati booking —
    end_date_exclusive (hari check-out) TIDAK dihitung menempati, tamu sudah checkout sebelum
    hari itu dianggap kosong lagi, KECUALI booking day-use yang checkin/checkout di hari yang
    sama (tetap menempati hari itu). Sama seperti `_occupies_date` di routes/ketersediaan.py —
    lihat bug 2026-07-12 di sana untuk detail kenapa overlap timestamp mentah salah di sini juga.
    """
    start_date, end_date = start.date(), end.date()
    if start_date == end_date:
        end_date = start_date + timedelta(days=1)
    return start_date, end_date


@api.get("/public/rooms-catalog")
async def public_rooms_catalog():
    """Katalog kamar untuk halaman publik. Mengelompokkan berdasarkan tipe.
    Tidak mengekspos field internal seperti info / status detail.
    """
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    rooms.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    # Foto & deskripsi per tipe kamar — statis (bukan dari DB) karena semua kamar
    # dalam 1 tipe memakai foto yang sama. File-nya ada di frontend/public/assets/.
    META = {
        "Standard": {
            "image": "/assets/std-5.webp",
            "size": "3 × 3 m",
            "capacity": "2 Dewasa + 1 Anak",
            "description": "Kamar hangat dan efisien untuk berdua, dengan teras pribadi dan kamar mandi bersih.",
        },
        "Cottage": {
            "image": "/assets/cot-2.webp",
            "size": "5 × 3,5 m",
            "capacity": "2 Dewasa + 1 Anak",
            "description": "Fasilitas identik dengan Standard Room, namun jauh lebih lapang — cocok untuk keluarga kecil atau honeymoon.",
        },
    }
    grouped: Dict[str, Any] = {}
    for r in rooms:
        t = r["tipe"]
        if t not in grouped:
            m = META.get(t, {})
            grouped[t] = {
                "tipe": t,
                "tarif": r["tarif"],  # harga Day Use (flat per 6 jam)
                "tarif_menginap": r["tarif_menginap"],  # harga Menginap per malam, tanpa sarapan
                "image": m.get("image", ""),
                "size": m.get("size", ""),
                "capacity": m.get("capacity", ""),
                "description": m.get("description", ""),
                "fasilitas": [
                    "AC", "Wi-Fi gratis", "TV LED", "Kamar mandi dalam",
                    "Air panas", "Handuk & toiletries",
                ] + (["Cottage Style", "Area Outdoor"] if t == "Cottage" else []),
                "rooms": [],
            }
        grouped[t]["rooms"].append({"id": r["id"], "nomor": r["nomor"]})
    return list(grouped.values())

@api.get("/public/availability")
async def public_availability(tanggal: str, tipe: Optional[str] = None, checkout: Optional[str] = None):
    """List kamar tersedia pada tanggal tertentu (halaman publik).
    Untuk tanggal MASA DEPAN, status realtime kamar (day_use/menginap/perlu_dibersihkan) TIDAK relevan
    karena akan kembali kosong sebelum tanggal tersebut. Hanya `maintenance` (long-term) yang di-exclude.
    Filter utama: tidak ada booking_pending/booking_paid/aktif yang overlap dengan tanggal target.

    `checkout` (opsional, YYYY-MM-DD) dipakai untuk booking menginap: kalau diisi,
    window overlap yang dicek adalah seluruh rentang [tanggal, checkout), bukan cuma
    1 hari — supaya kamar yang sudah dibooking di salah satu malam dalam rentang itu
    tidak muncul sebagai tersedia.
    """
    try:
        d = datetime.fromisoformat(tanggal)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    d_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    if checkout:
        try:
            d_end = datetime.fromisoformat(checkout).replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception:
            raise HTTPException(400, "Format tanggal checkout harus YYYY-MM-DD")
        if d_end <= d_start:
            raise HTTPException(400, "Tanggal checkout harus setelah tanggal check-in")
    else:
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
    # Filter rooms yang punya booking overlap di tanggal tsb — [d_start, d_end) di sini
    # sudah berupa rentang TANGGAL (bukan cuma pre-filter kasar), jadi hari check-out booking
    # lain TIDAK dihitung menempati (lihat _booking_date_range).
    q_range_start, q_range_end = d_start.date(), d_end.date()
    out = []
    for r in rooms:
        kandidat = await db.bookings.find({
            "room_id": r["id"],
            "status": {"$in": ["aktif", "booking_paid", "booking_pending"]},
            "jam_mulai": {"$lt": d_end.isoformat()},
            "jam_selesai": {"$gt": d_start.isoformat()},
        }, {"_id": 0, "jam_mulai": 1, "jam_selesai": 1}).to_list(50)
        bk = None
        for c in kandidat:
            b_start, b_end = _booking_date_range(parse_iso(c["jam_mulai"], "jam_mulai"), parse_iso(c["jam_selesai"], "jam_selesai"))
            if b_start < q_range_end and q_range_start < b_end:
                bk = c
                break
        if not bk:
            out.append({"id": r["id"], "nomor": r["nomor"], "tipe": r["tipe"], "tarif": r["tarif"], "tarif_menginap": r["tarif_menginap"]})
    out.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    return {"tanggal": tanggal, "tipe": tipe, "rooms": out}

@api.get("/public/scheduling/rekomendasi-dayuse")
async def public_rekomendasi_dayuse(room_id: str, jam_mulai: str):
    """Versi publik (tanpa login) dari /scheduling/rekomendasi-dayuse — dipakai halaman /book
    supaya tamu juga lihat peringatan kalau jam Day Use yang dipilih mepet booking Menginap
    yang sudah terkonfirmasi di kamar yang sama (Scheduling Engine, PRD Revisi #6). Murni
    informasi, TIDAK mengubah/membatasi apa yang bisa disubmit tamu."""
    mulai = parse_iso(jam_mulai, "jam_mulai")
    info = await slot_dayuse_aman(room_id, mulai)
    return {
        "jam_selesai_ideal": info["jam_selesai_ideal"].isoformat(),
        "jam_selesai_aman": info["jam_selesai_aman"].isoformat(),
        "dipersingkat": info["dipersingkat"],
        "alasan": info["alasan"],
    }

@api.post("/public/bookings")
async def public_create_booking(body: PublicBookingCreate):
    """Booking publik (tanpa login) — 1 kamar (`room_id`, alur lama) atau beberapa kamar
    sekaligus dalam 1 transaksi (`room_ids`, mis. rombongan) dengan tanggal/tipe/data tamu
    yang sama. Tiap kamar tetap dihitung harganya SENDIRI dari tarifnya masing-masing (bukan
    dibagi dari satu total gabungan — grup bisa campur Standard+Cottage), tapi berbagi
    `group_id` supaya bisa dibayar dalam SATU transaksi Tripay (lihat tripay.py) dan
    ditampilkan bersama di halaman sukses/voucher. Membuat booking dengan status
    'booking_pending'. Wajib bayar (DP 50% min) via Tripay. Day use: 6 jam dari jam
    check-in. Menginap: check-out fixed jam 12:00 WIB, harga per malam (termasuk extra bed).
    Response tetap 1 dict datar (backward compatible) kalau cuma 1 kamar; jadi
    `{"group_id", "bookings": [...]}` kalau lebih dari 1.
    """
    room_ids = body.room_ids if body.room_ids else ([body.room_id] if body.room_id else [])
    room_ids = list(dict.fromkeys(room_ids))
    if not room_ids:
        raise HTTPException(400, "room_id atau room_ids wajib diisi")
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "Tipe booking tidak valid")
    if body.tipe == "menginap":
        # Keputusan bisnis user 2026-07-17: booking Menginap publik instan DIMATIKAN — tamu
        # diarahkan chat WhatsApp dulu (alur Booking Request → approval → link Tripay, lihat
        # backend/routes/booking_requests.py). Day Use TETAP instan seperti biasa, tidak
        # berubah. Frontend (PublicBook.jsx) sudah tidak menawarkan opsi ini lagi ke tamu —
        # guard ini cuma jaga-jaga endpoint dipanggil langsung (mis. request lama ter-cache).
        raise HTTPException(400, "Booking Menginap sekarang lewat WhatsApp — silakan hubungi admin kami untuk reservasi menginap")
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

    nights = 1
    local_out = None
    if body.tipe == "menginap":
        if not body.tanggal_checkout:
            raise HTTPException(400, "Booking menginap wajib mengisi tanggal check-out")
        try:
            local_out = datetime.fromisoformat(f"{body.tanggal_checkout}T12:00:00+07:00")
        except Exception:
            raise HTTPException(400, "Format tanggal check-out tidak valid")
        end = local_out.astimezone(timezone.utc)
        if end <= start:
            raise HTTPException(400, "Tanggal check-out harus setelah tanggal check-in")
        nights = max(1, (local_out.date() - local_in.date()).days)
    else:
        end = start + timedelta(hours=6)  # day use 6 jam default

    # Cek semua kamar dulu SEBELUM membuat satupun dokumen — all-or-nothing untuk grup,
    # tamu sedang menunggu live di halaman checkout, tidak boleh ada kamar yang setengah
    # jalan ter-booking kalau salah satu ternyata bentrok (sama seperti Quick Book staf).
    rooms = []
    for rid in room_ids:
        r = await db.rooms.find_one({"id": rid})
        if not r:
            raise HTTPException(404, f"Kamar tidak ditemukan (id {rid})")
        await check_room_available(rid, start, end)
        rooms.append(r)

    extra_bed_qty = max(0, min(EXTRA_BED_MAX, int(body.extra_bed_qty or 0)))
    group_id = str(uuid.uuid4()) if len(rooms) > 1 else None
    created = []
    for r in rooms:
        harga_override = None
        if body.tipe == "menginap":
            tarif_per_malam = r["tarif_menginap"] + (BREAKFAST_PRICE if body.dengan_sarapan else 0)
            subtotal = tarif_per_malam * nights + extra_bed_qty * EXTRA_BED_PRICE * nights
            service_fee = round(subtotal * SERVICE_FEE_PCT)
            total = subtotal + service_fee
            harga_override = {"subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": round(total * 0.5)}
        data = {
            "room_id": r["id"],
            "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
            "email": email,
            "no_identitas": body.no_identitas, "kendaraan": body.kendaraan,
            "jumlah_tamu": body.jumlah_tamu, "extra_bed_qty": body.extra_bed_qty,
            "jam_mulai": start, "jam_selesai": end,
            "catatan": body.catatan,
            "created_by": body.nama_tamu,
            "tipe": body.tipe,
            "dengan_sarapan": body.dengan_sarapan,
        }
        booking = await create_reservation(data, source="online", harga_override=harga_override)
        if group_id:
            await db.bookings.update_one({"id": booking["id"]}, {"$set": {"group_id": group_id}})
            booking["group_id"] = group_id
        created.append(booking)

    if len(created) == 1:
        total_rp = f"Rp{int(created[0].get('total', 0)):,}".replace(",", ".")
        await send_push(
            "Booking Baru", f"{body.nama_tamu} — Kamar {created[0].get('room_nomor', '-')} ({total_rp})",
            url="/bookings",
        )
        return created[0]
    await send_push(
        "Booking Baru", f"{body.nama_tamu} — {len(created)} kamar sekaligus", url="/bookings",
    )
    return {"group_id": group_id, "bookings": created}

def _batas_jam_bebas_biaya(tipe: str) -> int:
    return 72 if tipe == "menginap" else 24  # H-3 menginap, H-1 day use


def _hitung_kebijakan_pembatalan(b: dict) -> dict:
    """Sama persis dengan calcCancelPolicy di PublicBook.jsx (frontend) — dipertahankan
    identik supaya biaya yang ditampilkan ke tamu = biaya yang benar-benar dipotong saat
    pembatalan mandiri sungguhan dieksekusi di endpoint ini."""
    batas_jam = _batas_jam_bebas_biaya(b.get("tipe", "day_use"))
    jam_checkin = parse_iso(b["jam_mulai"], "jam_mulai")
    jam_tersisa = (jam_checkin - datetime.now(timezone.utc)).total_seconds() / 3600
    dasar_biaya = int(b["total"]) if b.get("payment_status") == "paid" else int(b.get("dp_min") or 0)
    if jam_tersisa < 0:
        return {"label": "Hari check-in / lewat", "biaya": dasar_biaya, "gratis": False}
    if jam_tersisa < batas_jam:
        return {"label": f"Kurang dari {'H-3' if batas_jam == 72 else 'H-1'}", "biaya": round(dasar_biaya * 0.1), "gratis": False}
    return {"label": f"Lebih dari {'H-3' if batas_jam == 72 else 'H-1'}", "biaya": 0, "gratis": True}


@api.post("/public/bookings/{bid}/batalkan")
async def public_batalkan_booking(bid: str, body: CancelWithFeeBody = CancelWithFeeBody()):
    """Pembatalan mandiri SUNGGUHAN oleh tamu (bukan cuma 'ajukan permintaan') — otomatis
    penuh tanpa approval staf, sesuai keputusan bisnis yang dikonfirmasi user 2026-07-11.
    Refund uang (kalau ada) tetap harus ditransfer manual oleh staf — sistem cuma
    menghitung & mencatat nominalnya (refund_amount), tidak memproses transfer sungguhan.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, f"Booking tidak dapat dibatalkan (status: {b.get('status')})")

    policy = _hitung_kebijakan_pembatalan(b)
    biaya = policy["biaya"]
    paid = int(b.get("amount_due") or 0)
    is_paid = b.get("payment_status") == "paid"
    refund = max(0, paid - biaya) if is_paid else 0

    now = now_iso()
    update_fields = {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": "guest_self_service",
        "cancel_reason": body.alasan or "Dibatalkan mandiri oleh tamu",
        "cancel_fee": biaya, "refund_amount": refund,
    }
    if is_paid:
        update_fields["payment_status"] = "refunded" if refund > 0 else "forfeited"
    await db.bookings.update_one({"id": bid}, {"$set": update_fields})
    await log_availability_change(b["room_id"], b.get("room_tipe", ""), 1, "booking_dibatalkan_mandiri", booking_id=b["id"])
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "guest_self_service",
        "action": "cancel_self_service",
        "detail": f"Tamu batalkan mandiri {b['kode']}: biaya Rp{biaya:,}, {'refund Rp' + format(refund, ',') if refund > 0 else 'tidak ada refund'}".replace(",", "."),
        "entity": b.get("room_nomor", ""), "timestamp": now,
    })

    # Notifikasi konfirmasi ke tamu via WhatsApp (best-effort — pakai webhook yang sama
    # dengan bot WhatsApp, kalau staf sudah konfigurasi; kalau belum, cukup dilewati saja).
    try:
        from routes.pesan_whatsapp import _kirim_via_provider
        pesan = (
            f"Booking {b['kode']} sudah dibatalkan. "
            + (f"Biaya pembatalan Rp{biaya:,}.".replace(",", ".") if biaya else "Tidak ada biaya pembatalan.")
            + (f" Refund Rp{refund:,} akan diproses staf kami.".replace(",", ".") if refund > 0 else "")
        )
        await _kirim_via_provider(b["no_hp"], pesan)
    except Exception:
        pass

    return {
        "ok": True, "booking_kode": b["kode"], "cancel_fee": biaya, "refund_amount": refund,
        "policy_label": policy["label"], "gratis": policy["gratis"],
    }


@api.post("/public/bookings/{bid}/retry-bayar")
async def public_retry_bayar(bid: str):
    """Buka lagi booking yang dibatalkan OTOMATIS karena pembayaran expired/gagal, supaya
    tamu bisa coba bayar lagi tanpa isi ulang seluruh form booking dari awal (permintaan
    user 2026-07-14, sebelumnya sengaja ditunda — dinilai aman karena dampaknya cuma UX).

    HANYA berlaku untuk booking yang dibatalkan otomatis oleh webhook payment gateway
    (Tripay/Midtrans) — dibedakan dari pembatalan mandiri tamu (`cancelled_by=
    "guest_self_service"`), pembatalan staf, atau auto-cancel modifikasi OTA
    (`cancelled_by="ai_email_parser"`) lewat absennya field `cancelled_by`: webhook
    payment gateway (`routes/payments.py`, `routes/tripay.py`) tidak pernah mengisi field
    itu saat set status ke cancelled. Kamar di-cek ulang ketersediaannya (anti-overbooking)
    sebelum dibuka lagi — kalau sudah keburu dipesan tamu lain sejak dibatalkan, ditolak
    dengan pesan jelas, bukan double-booking.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") != "cancelled" or b.get("payment_status") not in ("expired", "failed") or b.get("cancelled_by"):
        raise HTTPException(400, "Booking ini tidak bisa dibuka lagi untuk coba bayar (bukan dibatalkan otomatis karena gagal bayar)")

    mulai = parse_iso(b["jam_mulai"], "jam_mulai")
    selesai = parse_iso(b["jam_selesai"], "jam_selesai")
    now = now_iso()
    # Celah check-lalu-tulis dibungkus lock (2026-07-19, audit anti-race-condition) - lihat
    # catatan di reservation_service.py.
    async with room_locks(b["room_id"]):
        await check_room_available(b["room_id"], mulai, selesai)
        await db.bookings.update_one({"id": bid}, {
            "$set": {"status": "booking_pending", "payment_status": "pending", "updated_at": now},
            "$unset": {"cancelled_at": "", "cancel_reason": "", "cancel_fee": "", "refund_amount": ""},
        })
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "guest_self_service",
        "action": "retry_bayar",
        "detail": f"Tamu coba bayar lagi booking {b['kode']} yang sempat dibatalkan otomatis (expired/gagal bayar)",
        "entity": b.get("room_nomor", ""), "timestamp": now,
    })
    updated = await db.bookings.find_one({"id": bid}, {"_id": 0})
    safe = {k: updated.get(k) for k in [
        "id", "kode", "room_nomor", "room_tipe", "tipe", "nama_tamu", "no_hp", "email",
        "jumlah_tamu", "extra_bed_qty", "dengan_sarapan", "jam_mulai", "jam_selesai", "status", "payment_status",
        "subtotal", "service_fee", "total", "dp_min", "invoice_id",
    ]}
    safe.update(status_bayar_booking(updated))
    return safe


_PUBLIC_BOOKING_FIELDS = [
    "id", "kode", "room_nomor", "room_tipe", "tipe", "nama_tamu", "no_hp", "email",
    "jumlah_tamu", "extra_bed_qty", "dengan_sarapan", "jam_mulai", "jam_selesai", "status", "payment_status",
    "subtotal", "service_fee", "total", "dp_min", "invoice_id",
]


@api.get("/public/bookings/{bid}")
async def public_get_booking(bid: str):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    # batasi field yang dikembalikan ke publik
    safe = {k: b.get(k) for k in _PUBLIC_BOOKING_FIELDS}
    # status_bayar (belum_bayar/dp/lunas) + sisa_tagihan — bedakan DP dari lunas untuk
    # halaman /book/sukses & voucher, karena payment_status mentah cuma tahu "paid" (gateway
    # settlement) tanpa peduli itu DP atau bayar penuh.
    safe.update(status_bayar_booking(b))
    # Kalau booking ini bagian dari GRUP (>1 kamar dibayar dalam 1 checkout), sertakan kamar
    # lain dalam grup yang sama supaya halaman sukses bisa menampilkan semuanya sekaligus,
    # bukan cuma kamar yang kebetulan ada di URL.
    if b.get("group_id"):
        siblings = await db.bookings.find(
            {"group_id": b["group_id"], "id": {"$ne": bid}}, {"_id": 0}
        ).to_list(20)
        safe["group_id"] = b["group_id"]
        safe["group_bookings"] = [
            {**{k: s.get(k) for k in _PUBLIC_BOOKING_FIELDS}, **status_bayar_booking(s)}
            for s in siblings
        ]
    return safe


@api.get("/pengiriman-voucher/logs")
async def list_email_send_log(user: dict = Depends(get_current_user)):
    """Log pengiriman voucher ke tamu (staf). Terisi begitu ada pengiriman lewat
    Brevo (otomatis setelah pembayaran sukses, atau kirim ulang manual)."""
    return await db.email_send_log.find({}, {"_id": 0}).sort("waktu", -1).to_list(200)


@api.post("/pengiriman-voucher/kirim-ulang/{bid}")
async def resend_voucher_email(bid: str, user: dict = Depends(get_current_user)):
    """Kirim ulang voucher ke email tamu secara manual (dipicu staf dari halaman
    Log Pengiriman, misalnya karena pengiriman otomatis sebelumnya gagal)."""
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    pdf_bytes = generate_voucher_pdf(b)
    log_entry = await send_voucher_email(b, pdf_bytes)
    if log_entry["status"] != "Terkirim":
        raise HTTPException(502, log_entry["error"] or "Gagal mengirim voucher")
    return log_entry


@api.get("/public/bookings/{bid}/voucher.pdf")
async def public_download_voucher_pdf(bid: str):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    pdf_bytes = generate_voucher_pdf(b)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="voucher-{b["kode"]}.pdf"'},
    )
