from core import *
import asyncio

# ---- Sinkronisasi Ketersediaan ----
# Catatan arsitektur: "Pelangi PMS" dan "Website Booking Engine" adalah aplikasi ini
# sendiri (selalu tersambung). "Email OTA (Gmail)" mencerminkan status koneksi Gmail
# sungguhan (collection `integrations`, lihat otomasi_email.py). "WhatsApp Bot"
# mencerminkan ada/tidaknya konfigurasi webhook (`webhook_config`, dibangun di task
# fitur Konfigurasi Webhook terpisah) — kalau belum ada, dianggap belum tersambung.

SYNC_CHANNEL_DEFS = [
    {"key": "pms", "nama": "Pelangi PMS", "peran": "Sumber Kebenaran Tunggal"},
    {"key": "website", "nama": "Website Booking Engine", "peran": "Saluran Penjualan"},
    {"key": "gmail", "nama": "Email OTA (Gmail)", "peran": "Sumber Reservasi OTA"},
    {"key": "whatsapp", "nama": "WhatsApp Bot", "peran": "Saluran Penjualan"},
]


async def _hitung_status_channel(key: str) -> str:
    if key in ("pms", "website"):
        return "connected"
    if key == "gmail":
        conn = await db.integrations.find_one({"provider": "gmail"})
        return "connected" if conn else "disconnected"
    if key == "whatsapp":
        cfg = await db.webhook_config.find_one({})
        return "connected" if cfg and cfg.get("aktif", True) else "disconnected"
    return "disconnected"


async def refresh_sync_channels() -> List[Dict[str, Any]]:
    waktu = now_iso()
    out = []
    for c in SYNC_CHANNEL_DEFS:
        status = await _hitung_status_channel(c["key"])
        doc = {**c, "status": status, "last_sync": waktu}
        await db.sync_channels.update_one({"key": c["key"]}, {"$set": doc}, upsert=True)
        out.append(doc)
    return out


@api.get("/sinkronisasi-ketersediaan/status")
async def sync_status(user: dict = Depends(get_current_user)):
    channels = await db.sync_channels.find({}, {"_id": 0}).to_list(10)
    if not channels:
        channels = await refresh_sync_channels()
    return {"channels": channels}


@api.post("/sinkronisasi-ketersediaan/paksa-sinkron")
async def paksa_sinkron(user: dict = Depends(require_owner)):
    channels = await refresh_sync_channels()
    await log_activity(user, "paksa_sinkron_ketersediaan", "Paksa sinkronisasi manual semua saluran")
    return {"channels": channels}


@api.get("/sinkronisasi-ketersediaan/riwayat-stok")
async def riwayat_stok(
    dari: Optional[str] = Query(None),
    sampai: Optional[str] = Query(None),
    tipe_kamar: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Riwayat perubahan stok — dari `availability_logs` sungguhan (Fase 1), dilengkapi
    `sumber` hasil lookup ke `bookings.source` (online -> Website, walk_in -> Pelangi PMS,
    ota -> Email OTA) supaya kolom Sumber di UI mencerminkan saluran asli, bukan data tiruan.
    """
    q: Dict[str, Any] = {}
    if tipe_kamar:
        q["room_tipe"] = tipe_kamar
    if dari or sampai:
        rng: Dict[str, Any] = {}
        if dari:
            rng["$gte"] = f"{dari}T00:00:00+00:00"
        if sampai:
            rng["$lte"] = f"{sampai}T23:59:59+00:00"
        q["changed_at"] = rng
    logs = await db.availability_logs.find(q, {"_id": 0}).sort("changed_at", -1).to_list(500)

    booking_ids = list({l["booking_id"] for l in logs if l.get("booking_id")})
    bookings = await db.bookings.find(
        {"id": {"$in": booking_ids}}, {"_id": 0, "id": 1, "source": 1, "room_nomor": 1}
    ).to_list(len(booking_ids) or 1) if booking_ids else []
    booking_map = {b["id"]: b for b in bookings}
    SOURCE_LABEL = {"online": "Website", "walk_in": "Pelangi PMS", "ota": "Email OTA"}

    out = []
    for l in logs:
        bk = booking_map.get(l.get("booking_id"))
        out.append({
            "id": l["id"],
            "changed_at": l["changed_at"],
            "room_tipe": l["room_tipe"],
            "room_nomor": bk["room_nomor"] if bk else None,
            "stock_change": l["stock_change"],
            "reason": l["reason"],
            "sumber": SOURCE_LABEL.get(bk["source"], "Pelangi PMS") if bk else "Pelangi PMS",
        })
    return out


DEFAULT_SYNC_SETTINGS = {"frekuensi_menit": 5, "prioritas": ["Pelangi PMS", "Email OTA", "Website", "WhatsApp Bot"]}


@api.get("/sinkronisasi-ketersediaan/pengaturan")
async def get_sync_settings(user: dict = Depends(get_current_user)):
    s = await db.sync_settings.find_one({}, {"_id": 0})
    return s or DEFAULT_SYNC_SETTINGS


@api.put("/sinkronisasi-ketersediaan/pengaturan")
async def update_sync_settings(body: SyncSettingsUpdate, user: dict = Depends(require_owner)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await db.sync_settings.update_one({}, {"$set": updates}, upsert=True)
    await log_activity(user, "update_sync_settings", "Update pengaturan sinkronisasi ketersediaan")
    return await db.sync_settings.find_one({}, {"_id": 0}) or DEFAULT_SYNC_SETTINGS


async def background_sync_loop():
    """Penjadwalan sinkronisasi otomatis — refresh status semua saluran secara berkala,
    interval dibaca ulang dari `sync_settings` tiap siklus supaya perubahan Pengaturan
    Sinkronisasi langsung berlaku di siklus berikutnya tanpa perlu restart server.
    """
    while True:
        try:
            await refresh_sync_channels()
        except Exception as e:
            logging.getLogger("sinkronisasi_ketersediaan").warning(f"Gagal auto-sync: {e}")
        settings = await db.sync_settings.find_one({}, {"_id": 0}) or DEFAULT_SYNC_SETTINGS
        frekuensi = max(1, int(settings.get("frekuensi_menit", 5)))
        await asyncio.sleep(frekuensi * 60)
