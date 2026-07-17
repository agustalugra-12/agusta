from core import *
import secrets
from routes.public import public_availability
from routes.issues import buat_issue
from routes.booking_requests import buat_booking_request
from routes.pesan_whatsapp import _cari_kamar_dari_no_hp

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
