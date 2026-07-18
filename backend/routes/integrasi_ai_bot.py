from core import *
import secrets
from routes.public import public_availability
from routes.issues import buat_issue
from routes.booking_requests import buat_booking_request
from routes.pesan_whatsapp import _cari_kamar_dari_no_hp
from routes.pembatalan import ajukan_pembatalan_ai

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
    bukan hitungan ulang terpisah."""
    tanggal = tanggal or datetime.now().strftime("%Y-%m-%d")
    hasil = await public_availability(tanggal=tanggal, tipe=tipe)
    per_tipe: Dict[str, Dict[str, Any]] = {}
    for r in hasil["rooms"]:
        t = per_tipe.setdefault(
            r["tipe"],
            {"tarif_day_use": r["tarif"], "tarif_menginap": r["tarif_menginap"], "kamar_tersedia": 0},
        )
        t["kamar_tersedia"] += 1
    return {"tanggal": tanggal, "ketersediaan": [{"tipe": t, **v} for t, v in per_tipe.items()]}


class AiBotTiketIn(BaseModel):
    tipe: str  # complaint | maintenance (divalidasi di buat_issue)
    deskripsi: str
    no_hp: str
    nama_tamu: str = ""


@api.post("/integrasi-ai-bot/tiket")
async def ai_bot_buat_tiket(body: AiBotTiketIn, _: None = Depends(verifikasi_ai_bot_key)):
    """Sama seperti `_klasifikasi_dan_buat_tiket` di pesan_whatsapp.py — tapi klasifikasinya
    sudah dilakukan ai-chat-bot sendiri, di sini cuma menulis tiketnya."""
    room_id, room_nomor = await _cari_kamar_dari_no_hp(body.no_hp)
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
    return {"no_hp": no_hp, "permintaan": out}


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
