from core import *
import secrets
from routes.public import public_availability
from routes.issues import buat_issue
from routes.booking_requests import buat_booking_request
from routes.pesan_whatsapp import _cari_kamar_dari_no_hp
from routes.pembatalan import ajukan_pembatalan_ai
from scheduling_engine import rekomendasi_slot_kosong

# ---- Integrasi AI Chat Bot Eksternal ----
# Untuk "ai-chat-bot" (repo terpisah milik user, dirancang reusable lintas sistem — BUKAN
# cuma untuk Pelangi PMS). Arahnya SELALU satu arah: ai-chat-bot yang memanggil endpoint di
# sini (baca data live + tulis balik hasil klasifikasi/booking request); PMS ini TIDAK
# pernah memanggil ai-chat-bot atau WAHA sama sekali — transport WhatsApp (WAHA dkk) jadi
# urusan ai-chat-bot sendiri, sama seperti pola AI Trigger BalesOtomatis di
# pesan_whatsapp.py tapi digeneralisasi supaya tidak terikat satu WA provider/vendor.
#
# Auth pakai API key sendiri (collection `ai_bot_integration_config`, header
# `Authorization: Bearer <api_key>`) — BUKAN JWT staf (`get_current_user`), karena
# pemanggilnya sistem lain, bukan user login.
#
# BATASAN KERAS (sama seperti alur booking AI WhatsApp bawaan, lihat CLAUDE.md): endpoint
# tulis di sini SENGAJA TIDAK PERNAH bisa membuat booking sungguhan langsung — cuma bisa
# memanggil `buat_booking_request` (non-binding, staf approve manual) & `buat_issue`
# (tiket komplain/maintenance), fungsi yang sama persis dipakai jalur AI WhatsApp internal,
# supaya tidak ada logika ganda yang bisa saling menyimpang.

DEFAULT_AI_BOT_CONFIG = {"aktif": False, "api_key": None, "updated_at": None}


async def verifikasi_ai_bot_key(request: Request) -> None:
    cfg = await db.ai_bot_integration_config.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("aktif") or not cfg.get("api_key"):
        raise HTTPException(404, "Not Found")
    auth = request.headers.get("Authorization", "")
    key = auth[7:] if auth.startswith("Bearer ") else ""
    if not key or not secrets.compare_digest(key, cfg["api_key"]):
        raise HTTPException(401, "API key tidak valid")


@api.get("/konfigurasi-integrasi-ai-bot")
async def get_ai_bot_config(user: dict = Depends(require_owner)):
    """`api_key` dibuat sekali otomatis kalau belum ada, supaya owner selalu punya key
    untuk ditempel ke konfigurasi ai-chat-bot sejak GET pertama (pola sama seperti
    `webhook_token` di konfigurasi_webhook.py)."""
    cfg = await db.ai_bot_integration_config.find_one({}, {"_id": 0})
    cfg = {**DEFAULT_AI_BOT_CONFIG, **(cfg or {})}
    if not cfg.get("api_key"):
        cfg["api_key"] = secrets.token_hex(24)
        await db.ai_bot_integration_config.update_one({}, {"$set": cfg}, upsert=True)
    return cfg


@api.put("/konfigurasi-integrasi-ai-bot")
async def update_ai_bot_config(body: Dict[str, Any], user: dict = Depends(require_owner)):
    updates = {"aktif": bool(body.get("aktif"))} if "aktif" in body else {}
    updates["updated_at"] = now_iso()
    await db.ai_bot_integration_config.update_one({}, {"$set": updates}, upsert=True)
    await log_activity(user, "update_ai_bot_config", "Update status integrasi AI Chat Bot eksternal")
    return await db.ai_bot_integration_config.find_one({}, {"_id": 0}) or DEFAULT_AI_BOT_CONFIG


@api.post("/konfigurasi-integrasi-ai-bot/regenerate-key")
async def regenerate_ai_bot_key(user: dict = Depends(require_owner)):
    new_key = secrets.token_hex(24)
    await db.ai_bot_integration_config.update_one(
        {}, {"$set": {"api_key": new_key, "updated_at": now_iso()}}, upsert=True
    )
    await log_activity(user, "regenerate_ai_bot_key", "Generate ulang API key integrasi AI Chat Bot")
    return await db.ai_bot_integration_config.find_one({}, {"_id": 0})


@api.get("/integrasi-ai-bot/ketersediaan")
async def ai_bot_ketersediaan(
    tanggal: Optional[str] = None, tipe: Optional[str] = None, _: None = Depends(verifikasi_ai_bot_key)
):
    """Ketersediaan & tarif kamar live per tanggal — logika sama dengan halaman publik
    `/book` (`public_availability`, termasuk fix hari checkout tidak dianggap booked),
    bukan hitungan ulang terpisah.

    **Perubahan 2026-07-19**: sebelumnya tipe yang 0 kamar kosong SAMA SEKALI TIDAK MUNCUL
    di hasil (AI tidak bisa membedakan "penuh" dari "tipe tidak ada") - sekarang SEMUA tipe
    kamar yang ada selalu muncul, termasuk yang `kamar_tersedia: 0`, supaya AI bisa jujur
    bilang "penuh" alih-alih menebak. Kalau penuhnya tanggal HARI INI khusus karena ada
    kamar Day Use yang akan checkout (bukan Menginap - lihat `estimasi_kamar_siap` di
    scheduling_engine.py), disertakan `estimasi_kosong_lagi` sebagai perkiraan jujur; kalau
    penuh karena Menginap atau tanggal bukan hari ini, field itu TIDAK ADA sama sekali -
    AI wajib bilang penuh apa adanya, tidak boleh menawarkan estimasi kosong."""
    tanggal = tanggal or datetime.now().strftime("%Y-%m-%d")
    hasil = await public_availability(tanggal=tanggal, tipe=tipe)

    q: Dict[str, Any] = {"tipe": tipe} if tipe else {}
    semua_kamar = await db.rooms.find(q, {"_id": 0, "tipe": 1, "tarif": 1, "tarif_menginap": 1}).to_list(500)
    per_tipe: Dict[str, Dict[str, Any]] = {}
    for r in semua_kamar:
        per_tipe.setdefault(r["tipe"], {"tarif_day_use": r["tarif"], "tarif_menginap": r["tarif_menginap"], "kamar_tersedia": 0})
    for r in hasil["rooms"]:
        if r["tipe"] in per_tipe:
            per_tipe[r["tipe"]]["kamar_tersedia"] += 1

    is_today = tanggal == datetime.now().strftime("%Y-%m-%d")
    out = []
    for t, v in per_tipe.items():
        item = {"tipe": t, **v}
        if v["kamar_tersedia"] == 0 and is_today:
            rekom = await rekomendasi_slot_kosong(t)
            if rekom:
                item["estimasi_kosong_lagi"] = rekom["siap_pakai"].isoformat()
                item["estimasi_kamar_nomor"] = rekom["room_nomor"]
        out.append(item)
    return {"tanggal": tanggal, "ketersediaan": out}


class AiBotTiketIn(BaseModel):
    tipe: str  # complaint | maintenance (divalidasi di buat_issue)
    deskripsi: str
    no_hp: str
    nama_tamu: str = ""
    room_nomor: Optional[str] = None  # kalau tamu sebutkan nomor kamarnya sendiri di chat (2026-07-20)


@api.post("/integrasi-ai-bot/tiket")
async def ai_bot_buat_tiket(body: AiBotTiketIn, _: None = Depends(verifikasi_ai_bot_key)):
    """Sama seperti `_klasifikasi_dan_buat_tiket` di pesan_whatsapp.py — tapi klasifikasinya
    sudah dilakukan ai-chat-bot sendiri, di sini cuma menulis tiketnya.

    room_nomor yang tamu sebutkan LANGSUNG di chat lebih diprioritaskan daripada pencarian
    otomatis by no_hp (2026-07-20, ditemukan lewat tes live: guest_service belum pernah
    dites sama sekali karena nomor WA Resepsionis belum pernah dihubungkan - begitu dites
    via Simulator, tiket maintenance/service_request selalu punya room_nomor KOSONG walau
    tamu jelas menyebut nomor kamarnya, karena pencarian by no_hp gagal kalau nomor WA tamu
    tidak persis cocok dengan yang tercatat di checkin/booking aktif)."""
    room_id, room_nomor = None, ""
    if body.room_nomor:
        raw = body.room_nomor.strip()
        r = await db.rooms.find_one({"nomor": raw})
        if not r:
            # AI kadang kirim teks bebas ("kamar 12"/"room 12") bukan cuma angka murni
            # seperti tersimpan di db.rooms.nomor ("12") - coba ekstrak angkanya.
            m = re.search(r"\d+", raw)
            if m:
                r = await db.rooms.find_one({"nomor": m.group(0)})
        if r:
            room_id, room_nomor = r["id"], r["nomor"]
    if not room_id:
        room_id, room_nomor = await _cari_kamar_dari_no_hp(body.no_hp)
    if not room_id and body.room_nomor:
        room_nomor = body.room_nomor.strip()  # tidak match db.rooms persis, tetap tampilkan apa adanya
    tiket = await buat_issue(
        body.tipe, body.deskripsi, {"id": "ai-chat-bot", "nama": "AI Chat Bot", "role": "owner"},
        room_id=room_id, room_nomor=room_nomor, nama_tamu=body.nama_tamu,
    )
    return {"ok": True, "tiket": tiket}


@api.get("/integrasi-ai-bot/rules")
async def ai_bot_rules(category: Optional[str] = None, _: None = Depends(verifikasi_ai_bot_key)):
    """Business Rules (DP/cancellation/checkin/checkout/promo/dll) — PMS jadi satu-satunya
    sumber kebenaran (lihat routes/business_rules.py), ai-chat-bot menarik ini untuk
    dijadikan konteks AI menjawab tamu, bukan menyimpan salinan kebijakan sendiri yang bisa
    basi. Hanya rule aktif yang diekspos, field internal (id/created_at/dll) disederhanakan."""
    q: Dict[str, Any] = {"is_active": True}
    if category:
        q["category"] = category
    rules = await db.business_rules.find(q, {"_id": 0}).to_list(500)
    return {
        "rules": [
            {"category": r["category"], "title": r["title"], "description": r["description"], "value": r.get("value")}
            for r in rules
        ],
    }


@api.get("/integrasi-ai-bot/booking-status")
async def ai_bot_booking_status(no_hp: str, _: None = Depends(verifikasi_ai_bot_key)):
    """Status booking request tamu (dicari dari no_hp, 5 permintaan terbaru) — reuse
    penuh logika pengayaan `status_efektif`/`booking_ringkasan` yang sama dipakai halaman
    staf /booking-requests (lihat list_booking_requests), supaya AI menjawab status yang
    sama persis dengan yang staf lihat, bukan hitungan terpisah yang bisa menyimpang."""
    digits = re.sub(r"\D", "", no_hp or "")
    if not digits:
        return {"no_hp": no_hp, "permintaan": []}
    variasi = {digits}
    if digits.startswith("62"):
        variasi.add("0" + digits[2:])
    elif digits.startswith("0"):
        variasi.add("62" + digits[1:])

    items = await db.booking_requests.find(
        {"no_hp": {"$in": list(variasi)}}, {"_id": 0}
    ).sort("created_at", -1).to_list(5)

    out = []
    for it in items:
        status_efektif = it["status"]
        booking_ringkasan = None
        if it.get("booking_ids"):
            bks = await db.bookings.find({"id": {"$in": it["booking_ids"]}}, {"_id": 0}).to_list(20)
            if bks:
                booking_ringkasan = [{
                    "kode": b["kode"], "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
                    "sync_status": b.get("sync_status"),
                    **status_bayar_booking(b),  # status_bayar, jumlah_dibayar, sisa_tagihan
                } for b in bks]
                if it["status"] == "waiting_payment" and all(b.get("payment_status") == "paid" for b in bks):
                    status_efektif = "lunas"
        out.append({
            "kode": it["kode"], "tipe": it["tipe"], "room_tipe": it.get("room_tipe"),
            "tanggal_checkin": it["tanggal_checkin"], "tanggal_checkout": it.get("tanggal_checkout"),
            "status": status_efektif, "booking_ringkasan": booking_ringkasan,
            "created_at": it["created_at"],
        })

    # Bookings LANGSUNG (public /book, walk-in Quick Book, OTA) TIDAK PERNAH punya dokumen
    # booking_requests (2026-07-19, ditemukan saat audit reliabilitas) - sebelumnya tamu yang
    # booking Day Use lewat website publik lalu coba batalkan via chat AI WhatsApp SELALU
    # dijawab "tidak ditemukan", padahal booking-nya nyata & ajukan_pembatalan_ai
    # (routes/pembatalan.py) sendiri sudah bekerja untuk booking manapun by kode - gap-nya
    # murni di pencarian ini. Disatukan di sini supaya AI bisa temukan & bantu batalkan
    # booking dari channel manapun, bukan cuma yang dia buat sendiri.
    sudah_termasuk = {b["kode"] for it in out for b in (it.get("booking_ringkasan") or [])}
    direct_bookings = await db.bookings.find({
        "no_hp": {"$in": list(variasi)},
        "status": {"$in": ["aktif", "booking_pending", "booking_paid", "checked_in"]},
    }, {"_id": 0}).sort("created_at", -1).to_list(5)
    for b in direct_bookings:
        if b["kode"] in sudah_termasuk:
            continue
        sb = status_bayar_booking(b)
        out.append({
            "kode": b["kode"], "tipe": b.get("tipe"), "room_tipe": b.get("room_tipe"),
            "tanggal_checkin": (b.get("jam_mulai") or "")[:10],
            "tanggal_checkout": (b.get("jam_selesai") or "")[:10] if b.get("tipe") == "menginap" else None,
            "status": "lunas" if sb["status_bayar"] == "lunas" else "waiting_payment",
            "booking_ringkasan": [{
                "kode": b["kode"], "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
                "sync_status": b.get("sync_status"), **sb,
            }],
            "created_at": b.get("created_at"),
        })
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"no_hp": no_hp, "permintaan": out[:5]}


class AiBotBookingRequestIn(BaseModel):
    nama_tamu: str
    no_hp: str
    tipe: str  # day_use | menginap
    tanggal_checkin: str
    room_tipe: Optional[str] = None
    jumlah_kamar: Optional[int] = None
    jumlah_tamu: Optional[int] = None
    jam_checkin: Optional[str] = None
    tanggal_checkout: Optional[str] = None
    catatan: Optional[str] = None
    payment_option: Optional[str] = None  # dp50 | full, kalau tamu sudah sebutkan sendiri


@api.post("/integrasi-ai-bot/booking-request")
async def ai_bot_buat_booking_request(body: AiBotBookingRequestIn, _: None = Depends(verifikasi_ai_bot_key)):
    """Non-binding, persis alur booking AI WhatsApp internal (`_proses_giliran_booking` di
    pesan_whatsapp.py) — staf tetap yang Terima/Tolak manual di /booking-requests, endpoint
    ini TIDAK PERNAH membuat booking sungguhan langsung."""
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "tipe harus 'day_use' atau 'menginap'")
    hasil = await buat_booking_request(body.model_dump())
    return {"ok": True, "booking_request": hasil}


class AiBotCancelRequestIn(BaseModel):
    kode: str  # kode booking (BKO-...), BUKAN kode booking_request (REQ-...)
    no_hp: str
    alasan: Optional[str] = ""


@api.post("/integrasi-ai-bot/cancel-request")
async def ai_bot_ajukan_pembatalan(body: AiBotCancelRequestIn, _: None = Depends(verifikasi_ai_bot_key)):
    """Non-binding — sama seperti booking-request, endpoint ini TIDAK PERNAH mengeksekusi
    pembatalan sungguhan langsung (lihat routes/pembatalan.py). AI cuma menyampaikan info
    (kode booking, nomor tamu, alasan) ke PMS; PMS mencatat & staf yang approve/reject
    manual di Dashboard/halaman Pembatalan."""
    hasil = await ajukan_pembatalan_ai(body.kode, body.no_hp, body.alasan or "")
    if not hasil.get("ok"):
        raise HTTPException(400, hasil.get("error") or "Gagal mengajukan pembatalan")
    return hasil
