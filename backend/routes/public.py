import asyncio
from core import *
from reservation_service import check_room_available, create_reservation, room_locks
from email_service import generate_voucher_pdf, send_voucher_email, get_property_branding
from routes.push import send_push
from scheduling_engine import slot_dayuse_aman, DAYUSE_DURASI_JAM, WIB
import httpx
import io
from fastapi.responses import StreamingResponse

async def _resolve_property(properti: Optional[str] = None) -> str:
    """Multi-properti Fase 5 (2026-07-25) - resolve property_id dari slug URL publik
    (`?properti=<slug>`, dikirim PublicBook.jsx dari path `/book/<slug>`). Slug kosong =
    fallback ke get_default_property_id() (properti pertama) - backward compatible untuk
    link lama/eksternal yang belum menyertakan slug, TIDAK PERNAH pecah link yang sudah
    beredar (mis. CTA lama web-pelangi sebelum di-update ke domain per-properti)."""
    if not properti:
        return await get_default_property_id()
    p = await db.properties.find_one({"slug": properti, "aktif": True})
    if not p:
        raise HTTPException(404, "Properti tidak ditemukan")
    return p["id"]


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


@api.get("/public/pricing-config")
async def public_pricing_config():
    """Konstanta harga tambahan (extra bed, sarapan, service fee) untuk ringkasan harga di
    halaman booking publik SEBELUM submit — dulu di-hardcode terpisah di PublicBook.jsx,
    gampang beda sendiri dari core.py kalau salah satu diubah tanpa yang lain. Sekarang satu
    sumber kebenaran; backend tetap menghitung ulang total resminya sendiri saat create
    booking (nilai di sini murni untuk tampilan awal, tidak pernah dipakai untuk hitung final)."""
    return {
        "service_fee_pct": SERVICE_FEE_PCT,
        "extra_bed_price": EXTRA_BED_PRICE,
        "extra_bed_max": EXTRA_BED_MAX,
        "breakfast_price": BREAKFAST_PRICE,
    }


@api.get("/public/rooms-catalog")
async def public_rooms_catalog(properti: Optional[str] = None):
    """Katalog kamar untuk halaman publik. Mengelompokkan berdasarkan tipe.
    Tidak mengekspos field internal seperti info / status detail.

    `properti` (Fase 5) - slug properti dari URL `/book/<slug>`, lihat _resolve_property."""
    property_id = await _resolve_property(properti)
    ada_sarapan = await property_ada_sarapan(property_id)
    # (2026-07-31) - kamar Harmoni TIDAK ada AC (beda dari Pelangi) - bug nyata ditemukan &
    # dilaporkan Agus: daftar fasilitas di bawah sebelumnya 1 daftar hardcode dipakai sama
    # rata semua properti, jadi Harmoni ikut diklaim "AC" padahal tidak ada.
    ada_ac = await property_ada_ac(property_id)
    rooms = await db.rooms.find(scoped({}, property_id), {"_id": 0}).to_list(500)
    rooms.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    ada_tipe_standard = any(r["tipe"] == "Standard" for r in rooms)
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
            # "identik dengan Standard Room" cuma masuk akal kalau properti ini memang PUNYA
            # tipe Standard (Pelangi) - Harmoni cuma punya Cottage, referensi ke Standard di
            # sana jadi membingungkan/salah konteks.
            "description": (
                "Fasilitas identik dengan Standard Room, namun jauh lebih lapang — cocok untuk keluarga kecil atau honeymoon."
                if ada_tipe_standard else
                "Cottage luas dan nyaman dengan area outdoor — cocok untuk keluarga kecil atau honeymoon."
            ),
        },
    }
    grouped: Dict[str, Any] = {}
    for r in rooms:
        t = r["tipe"]
        if t not in grouped:
            m = META.get(t, {})
            fasilitas = (["AC"] if ada_ac else []) + ["Wi-Fi gratis", "TV LED", "Kamar mandi dalam", "Air panas", "Handuk & toiletries"]
            grouped[t] = {
                "tipe": t,
                "tarif": r["tarif"],  # harga Day Use (flat per 6 jam)
                "tarif_menginap": r["tarif_menginap"],  # harga Menginap per malam, tanpa sarapan
                # (2026-07-31) - Harmoni tidak menyediakan sarapan sama sekali, beda dari
                # Pelangi - frontend pakai ini utk sembunyikan toggle "dengan sarapan".
                "ada_sarapan": ada_sarapan,
                "image": m.get("image", ""),
                "size": m.get("size", ""),
                "capacity": m.get("capacity", ""),
                "description": m.get("description", ""),
                "fasilitas": fasilitas + (["Cottage Style", "Area Outdoor"] if t == "Cottage" else []),
                "rooms": [],
            }
        grouped[t]["rooms"].append({"id": r["id"], "nomor": r["nomor"]})
    return list(grouped.values())

@api.get("/public/availability")
async def public_availability(tanggal: str, tipe: Optional[str] = None, checkout: Optional[str] = None,
                              property_id_override: Optional[str] = None, properti: Optional[str] = None,
                              jam_checkin: Optional[str] = None):
    """List kamar tersedia pada tanggal tertentu (halaman publik).
    Untuk tanggal MASA DEPAN, status realtime kamar (day_use/menginap/perlu_dibersihkan) TIDAK relevan
    karena akan kembali kosong sebelum tanggal tersebut. Hanya `maintenance` (long-term) yang di-exclude.
    Filter utama: tidak ada booking_pending/booking_paid/aktif yang overlap dengan tanggal target.

    `checkout` (opsional, YYYY-MM-DD) dipakai untuk booking menginap: kalau diisi,
    window overlap yang dicek adalah seluruh rentang [tanggal, checkout), bukan cuma
    1 hari — supaya kamar yang sudah dibooking di salah satu malam dalam rentang itu
    tidak muncul sebagai tersedia.

    `jam_checkin` (opsional, "HH:MM" WIB, 2026-08-01 - bug nyata ditemukan lewat laporan
    user: tamu Vina tanya Day Use BESOK jam 10 pagi, AI jawab "tersedia banyak" padahal
    SEMUA kamar Standard hari itu baru checkout menginap jam 12 siang - filter tanggal-saja
    di atas TIDAK tahu soal jam, "hari checkout tidak dihitung menempati" cuma benar kalau
    checkin baru diminta SETELAH jam checkout riil, bukan utk Day Use pagi yang datang
    SEBELUM tamu lama keluar). HANYA relevan utk Day Use (kalau `checkout` diisi/multi-malam
    menginap, diabaikan - checkin menginap normalnya jam 14:00, sudah aman dari kasus ini).
    Kalau diisi, kamar yang lolos filter tanggal di atas DISARING ULANG pakai overlap presisi
    jam (check_room_available, hard validator yang sama dipakai saat submit sungguhan) thd
    slot Day Use [jam_checkin, jam_checkin + durasi standar] - supaya kamar yang secara
    TANGGAL "tersedia" tapi tamu sebelumnya belum checkout pas jam yang diminta, tidak ikut
    dihitung tersedia.

    `property_id_override` (Fase 4) - dipakai pemanggil INTERNAL yang sudah tahu properti
    yang benar dari konteksnya sendiri (mis. ai_bot_ketersediaan dari API key ai-chat-bot,
    atau _coba_auto_approve_day_use dari property_id booking_request). `properti` (Fase 5) -
    slug dari URL publik `/book/<slug>`, dipakai kalau override tidak diisi (override selalu
    menang - pemanggil internal tidak pernah salah properti walau kebetulan ada slug di query)."""
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
    property_id = property_id_override or await _resolve_property(properti)
    today_local = datetime.now().strftime("%Y-%m-%d")
    is_today = tanggal == today_local
    q: Dict[str, Any] = {}
    if tipe:
        q["tipe"] = tipe
    # Bug nyata ditemukan 2026-08-02 (pertanyaan Agus - tamu chat jam 8 pagi minta Day Use
    # jam 13:00 hari ini, tipe Standard: sistem salah bilang "0 kamar tersedia" padahal 8
    # kamar Standard checkout jam 12:00 siang hari itu juga, harusnya bisa dipakai jam 13:00):
    # gate "kosong" di bawah cuma cek status kamar SAAT QUERY DIJALANKAN (mis. jam 8 pagi,
    # kamar masih "menginap" krn checkout belum diproses staf) - kalau `jam_checkin` diisi
    # (tamu sudah sebutkan jam spesifik), JANGAN gunakan gate real-time ini sama sekali,
    # serahkan ke overlap presisi jam di bawah (check_room_available, sudah ada sejak fix
    # jam_checkin sebelumnya) yang benar-benar tahu kamar itu bebas atau tidak PADA JAM yang
    # diminta - bukan cuma status sesaat waktu query. Tanpa jam_checkin (belum tahu jam
    # spesifik), tetap pakai gate lama (konservatif, aman) supaya tidak menjanjikan kamar
    # yang belum tentu kosong di jam yang tamu belum sebutkan.
    if is_today and not jam_checkin:
        q["status"] = "kosong"
    else:
        q["status"] = {"$ne": "maintenance"}
    rooms = await db.rooms.find(scoped(q, property_id), {"_id": 0}).to_list(500)
    # Filter rooms yang punya booking overlap di tanggal tsb — [d_start, d_end) di sini
    # sudah berupa rentang TANGGAL (bukan cuma pre-filter kasar), jadi hari check-out booking
    # lain TIDAK dihitung menempati (lihat _booking_date_range).
    q_range_start, q_range_end = d_start.date(), d_end.date()
    out = []
    for r in rooms:
        kandidat = await db.bookings.find(scoped({
            "room_id": r["id"],
            # "checked_in" WAJIB disertakan (2026-08-01, bug nyata ditemukan Agus - tamu Opa
            # Isa yang sedang menginap sampai 10 Agustus muncul sbg "tersedia" di sini utk
            # tanggal2 di tengah masa inapnya, karena status booking-nya sudah "checked_in"
            # begitu tamu benar2 check-in, bukan "aktif" lagi). Bug ini WARISAN yang sama
            # persis dgn yang sudah pernah diperbaiki di check_room_available - fungsi ITU
            # sudah benar menyertakan "checked_in", tapi fungsi PREVIEW ini (dipakai halaman
            # /book publik & tool check_availability AI) ketinggalan - preview bisa bilang
            # "tersedia" utk kamar yang sebenarnya masih ditempati, walau submit sungguhan
            # tetap ditolak check_room_available (tidak double-booking asli, tapi tamu/AI
            # bisa terlanjur janji kamar yang ternyata tidak bisa dipakai).
            "status": {"$in": ["aktif", "booking_paid", "booking_pending", "checked_in"]},
            "jam_mulai": {"$lt": d_end.isoformat()},
            "jam_selesai": {"$gt": d_start.isoformat()},
        }, property_id), {"_id": 0, "jam_mulai": 1, "jam_selesai": 1}).to_list(50)
        bk = None
        for c in kandidat:
            b_start, b_end = _booking_date_range(parse_iso(c["jam_mulai"], "jam_mulai"), parse_iso(c["jam_selesai"], "jam_selesai"))
            if b_start < q_range_end and q_range_start < b_end:
                bk = c
                break
        if not bk:
            out.append({"id": r["id"], "nomor": r["nomor"], "tipe": r["tipe"], "tarif": r["tarif"], "tarif_menginap": r["tarif_menginap"]})

    # Filter presisi jam utk Day Use (2026-08-01, lihat catatan jam_checkin di docstring) -
    # HANYA jalan kalau jam_checkin diisi DAN ini bukan query menginap multi-malam (checkout
    # kosong). Pakai check_room_available yang SAMA persis dgn hard validator submit
    # sungguhan - kalau lolos di sini, dijamin juga lolos saat benar-benar submit (tidak ada
    # celah preview-vs-submit yang bisa menyimpang lagi).
    if jam_checkin and not checkout and out:
        try:
            jm_mulai_wib = datetime.combine(d.date(), datetime.strptime(jam_checkin, "%H:%M").time(), tzinfo=WIB)
        except ValueError:
            jm_mulai_wib = None
        if jm_mulai_wib:
            jm_mulai_utc = jm_mulai_wib.astimezone(timezone.utc)
            jm_selesai_utc = jm_mulai_utc + timedelta(hours=DAYUSE_DURASI_JAM)
            out_presisi = []
            for r in out:
                try:
                    await check_room_available(r["id"], jm_mulai_utc, jm_selesai_utc, property_id)
                    out_presisi.append(r)
                except HTTPException:
                    continue
            out = out_presisi

    out.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    return {"tanggal": tanggal, "tipe": tipe, "rooms": out}

@api.get("/public/scheduling/rekomendasi-dayuse")
async def public_rekomendasi_dayuse(room_id: str, jam_mulai: str, properti: Optional[str] = None):
    """Versi publik (tanpa login) dari /scheduling/rekomendasi-dayuse — dipakai halaman /book
    supaya tamu juga lihat peringatan kalau jam Day Use yang dipilih mepet booking Menginap
    yang sudah terkonfirmasi di kamar yang sama (Scheduling Engine, PRD Revisi #6). Murni
    informasi, TIDAK mengubah/membatasi apa yang bisa disubmit tamu."""
    mulai = parse_iso(jam_mulai, "jam_mulai")
    property_id = await _resolve_property(properti)
    info = await slot_dayuse_aman(room_id, mulai, property_id)
    return {
        "jam_selesai_ideal": info["jam_selesai_ideal"].isoformat(),
        "jam_selesai_aman": info["jam_selesai_aman"].isoformat(),
        "dipersingkat": info["dipersingkat"],
        "alasan": info["alasan"],
    }

@api.post("/public/bookings")
async def public_create_booking(body: PublicBookingCreate, properti: Optional[str] = None):
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
    property_id = await _resolve_property(properti)
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
        r = await db.rooms.find_one(scoped({"id": rid}, property_id))
        if not r:
            raise HTTPException(404, f"Kamar tidak ditemukan (id {rid})")
        await check_room_available(rid, start, end, property_id)
        rooms.append(r)

    extra_bed_qty = max(0, min(EXTRA_BED_MAX, int(body.extra_bed_qty or 0)))
    # Aturan okupansi (2026-07-21, permintaan user): 1 kamar standar 2 dewasa + 1 anak,
    # extra bed (jadi 3 dewasa + 1 anak) HANYA berlaku utk tipe Cottage - Standard sama
    # sekali tidak bisa pakai extra bed. Sebelumnya extra_bed_qty diterapkan rata ke semua
    # kamar tanpa peduli tipe-nya (bug laten - kebetulan belum pernah kejadian tamu booking
    # campur Standard+Cottage sekaligus minta extra bed).
    if extra_bed_qty > 0 and any(r.get("tipe") != "Cottage" for r in rooms):
        raise HTTPException(400, "Extra bed hanya tersedia untuk tipe kamar Cottage, tidak bisa dipesan untuk Standard")
    # Harmoni tidak menyediakan sarapan sama sekali (2026-07-31, permintaan user - beda dari
    # Pelangi) - paksa False di sini (satu tempat, sebelum harga & data booking dibentuk)
    # supaya TIDAK MUNGKIN kepungut biaya sarapan utk properti yang tidak menyediakannya,
    # apa pun yang tamu kirim di body (typo/manipulasi payload).
    dengan_sarapan_efektif = body.dengan_sarapan and await property_ada_sarapan(property_id)
    group_id = str(uuid.uuid4()) if len(rooms) > 1 else None
    created = []
    try:
        for r in rooms:
            harga_override = None
            if body.tipe == "menginap":
                tarif_per_malam = r["tarif_menginap"] + (BREAKFAST_PRICE if dengan_sarapan_efektif else 0)
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
                "dengan_sarapan": dengan_sarapan_efektif,
            }
            booking = await create_reservation(data, property_id, source="online", harga_override=harga_override)
            if group_id:
                await db.bookings.update_one({"id": booking["id"]}, {"$set": {"group_id": group_id}})
                booking["group_id"] = group_id
            created.append(booking)
    except Exception:
        # Rollback all-or-nothing (2026-07-19, audit anti-race-condition lanjutan): pre-check
        # di atas (baris ~200) tidak atomik dengan create_reservation di sini (yang punya lock
        # per-kamar sendiri) - kalau kamar ke-2+ dalam grup ternyata direbut request lain di
        # celah waktu antara pre-check dan create_reservation, kamar ke-1 yang sudah TERLANJUR
        # dibuat perlu dibatalkan lagi supaya tidak ada booking grup yang nyangkut separuh jalan
        # (tamu sedang menunggu live di halaman checkout, harus dapat error yang bersih & kamar
        # yang gagal betul-betul lepas lagi, bukan "kepesan tapi tidak lengkap").
        for b in created:
            await db.bookings.update_one({"id": b["id"]}, {"$set": {
                "status": "cancelled", "cancelled_at": now_iso(),
                "cancelled_by": "system_rollback_group_booking_gagal",
            }})
            await log_availability_change(
                b["room_id"], b.get("room_tipe", ""), 1, "booking_dibatalkan_rollback_group_gagal",
                b.get("property_id"), booking_id=b["id"],
            )
        raise

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

@api.post("/public/bookings/{bid}/batalkan")
async def public_batalkan_booking(bid: str, body: CancelWithFeeBody = CancelWithFeeBody(), _rl: None = Depends(rate_limiter(10, 60))):
    """DIMATIKAN sejak 2026-07-31 (keputusan bisnis Agus: "pembatalan hanya lewat WA, tidak
    ada jalur lain") - endpoint ini DULU (2026-07-11) melakukan pembatalan mandiri
    SUNGGUHAN otomatis tanpa approval staf, sekarang SELALU menolak & mengarahkan tamu ke
    WhatsApp (jalur `ajukan_pembatalan_ai`/`pembatalan.py` yang tetap butuh approval staf
    manual). Endpoint TIDAK dihapus total (biar link lama yang mungkin masih tersimpan
    staf/tamu tidak 404 membingungkan) - sengaja jadi guard eksplisit, bukan cuma dicabut
    diam-diam dari frontend, supaya panggilan API langsung pun tetap tidak bisa membatalkan
    otomatis lagi."""
    raise HTTPException(
        400,
        "Pembatalan booking sekarang hanya bisa lewat WhatsApp - silakan chat admin kami "
        "untuk mengajukan pembatalan, tim kami akan proses secepatnya.",
    )


@api.post("/public/bookings/{bid}/retry-bayar")
async def public_retry_bayar(bid: str, body: RetryBayarBody = RetryBayarBody(), _rl: None = Depends(rate_limiter(10, 60))):
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
    verifikasi_pemilik_booking(b.get("no_hp"), body.no_hp_konfirmasi)
    if b.get("status") != "cancelled" or b.get("payment_status") not in ("expired", "failed") or b.get("cancelled_by"):
        raise HTTPException(400, "Booking ini tidak bisa dibuka lagi untuk coba bayar (bukan dibatalkan otomatis karena gagal bayar)")

    mulai = parse_iso(b["jam_mulai"], "jam_mulai")
    selesai = parse_iso(b["jam_selesai"], "jam_selesai")
    now = now_iso()
    # Celah check-lalu-tulis dibungkus lock (2026-07-19, audit anti-race-condition) - lihat
    # catatan di reservation_service.py. property_id diambil dari booking-nya sendiri
    # (Fase 5, 2026-07-25) - lebih akurat daripada stopgap, booking ini sudah pasti tercatat
    # dengan properti yang benar sejak dibuat, tidak perlu slug dari query lagi di sini.
    property_id = b.get("property_id") or await get_default_property_id()
    async with room_locks(b["room_id"]):
        await check_room_available(b["room_id"], mulai, selesai, property_id)
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
async def public_get_booking(bid: str, _rl: None = Depends(rate_limiter(30, 60))):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    # batasi field yang dikembalikan ke publik
    safe = {k: b.get(k) for k in _PUBLIC_BOOKING_FIELDS}
    # status_bayar (belum_bayar/dp/lunas) + sisa_tagihan — bedakan DP dari lunas untuk
    # halaman /book/sukses & voucher, karena payment_status mentah cuma tahu "paid" (gateway
    # settlement) tanpa peduli itu DP atau bayar penuh.
    safe.update(status_bayar_booking(b))
    # property_slug (2026-07-31) - halaman sukses/pembatalan publik (PublicBook.jsx) perlu
    # tahu properti booking ini utk arahkan tamu ke nomor WA yang BENAR (Pelangi vs Harmoni),
    # bukan hardcode 1 nomor Pelangi utk semua properti seperti sebelumnya.
    prop = await db.properties.find_one({"id": b.get("property_id")}, {"_id": 0, "slug": 1})
    safe["property_slug"] = (prop or {}).get("slug")
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
    # generate_voucher_pdf pakai ReportLab (sync/CPU-bound) - to_thread supaya tidak
    # blokir event loop tunggal (2026-07-28, audit performa) selama proses render PDF.
    branding = await get_property_branding(b.get("property_id"))
    pdf_bytes = await asyncio.to_thread(generate_voucher_pdf, b, branding)
    log_entry = await send_voucher_email(b, pdf_bytes)
    if log_entry["status"] != "Terkirim":
        raise HTTPException(502, log_entry["error"] or "Gagal mengirim voucher")
    return log_entry


@api.get("/public/bookings/{bid}/voucher.pdf")
async def public_download_voucher_pdf(bid: str, _rl: None = Depends(rate_limiter(30, 60))):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    # generate_voucher_pdf pakai ReportLab (sync/CPU-bound) - to_thread supaya tidak
    # blokir event loop tunggal (2026-07-28, audit performa) selama proses render PDF.
    branding = await get_property_branding(b.get("property_id"))
    pdf_bytes = await asyncio.to_thread(generate_voucher_pdf, b, branding)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="voucher-{b["kode"]}.pdf"'},
    )
