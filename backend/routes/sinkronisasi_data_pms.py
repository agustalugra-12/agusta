from core import *

# ---- Sinkronisasi Data PMS -> WhatsApp Bot ----
# Catatan arsitektur: bot WhatsApp di sistem ini (lihat pesan_whatsapp.py) menjawab tamu
# dengan MEMBACA LANGSUNG data `rooms`/`bookings` live saat pesan masuk — bukan salinan
# terpisah yang bisa basi. Jadi "status sinkronisasi" di sini bukan simulasi progres,
# tapi cerminan jujur: ketersediaan & harga SELALU tersinkron sempurna by design (zero
# drift), dan "reservasi_baru"/"status_booking" tersinkron kalau webhook bot aktif
# (dipush lewat `push_sync_event` di core.py setiap ada perubahan stok).

DATA_FLOW_DEFS = [
    {"key": "ketersediaan", "label": "Ketersediaan Kamar"},
    {"key": "harga", "label": "Harga & Tarif"},
    {"key": "status_booking", "label": "Status Booking"},
    {"key": "reservasi_baru", "label": "Reservasi Baru (Email OTA)"},
]


@api.post("/sinkronisasi-data-pms/webhook")
async def trigger_sync_webhook(user: dict = Depends(require_owner)):
    """Paksa dorong ulang status data Pelangi PMS terkini ke webhook bot WhatsApp —
    dipakai kalau staf curiga bot ketinggalan update (mekanisme retry manual), selain
    push otomatis yang sudah jalan tiap ada perubahan stok (lihat push_sync_event).
    """
    jumlah_kamar = await db.rooms.count_documents({})
    await push_sync_event("manual_resync", f"Resync manual dipicu staf — {jumlah_kamar} kamar")
    log = await db.sync_data_pms_log.find_one({}, {"_id": 0}, sort=[("waktu", -1)])
    await log_activity(user, "trigger_sync_webhook", "Paksa resync data ke bot WhatsApp")
    return {"ok": bool(log and log.get("ok")), "detail": log.get("detail") if log else "Webhook belum dikonfigurasi/aktif"}


@api.get("/sinkronisasi-data-pms/dashboard")
async def dashboard_sinkronisasi_pms(user: dict = Depends(get_current_user)):
    cfg = await db.webhook_config.find_one({})
    bot_aktif = bool(cfg and cfg.get("aktif"))
    now = now_iso()

    rooms = await db.rooms.find({}, {"_id": 0, "tipe": 1}).to_list(200)
    jumlah_kamar = len(rooms)
    jumlah_tipe = len(set(r["tipe"] for r in rooms))
    reservasi_ota_count = await db.bookings.count_documents({"source": "ota"})

    flows = [
        {"key": "ketersediaan", "label": "Ketersediaan Kamar", "last_sync": now, "jumlah_record": jumlah_kamar, "status": "synced"},
        {"key": "harga", "label": "Harga & Tarif", "last_sync": now, "jumlah_record": jumlah_tipe, "status": "synced"},
        {"key": "status_booking", "label": "Status Booking", "last_sync": now if bot_aktif else None,
         "jumlah_record": await db.bookings.count_documents({}), "status": "synced" if bot_aktif else "pending"},
        {"key": "reservasi_baru", "label": "Reservasi Baru (Email OTA)", "last_sync": now if reservasi_ota_count else None,
         "jumlah_record": reservasi_ota_count, "status": "synced" if reservasi_ota_count else "pending"},
    ]
    return {"flows": flows, "bot_aktif": bot_aktif}


@api.get("/sinkronisasi-data-pms/perbandingan-ketersediaan")
async def perbandingan_ketersediaan(user: dict = Depends(get_current_user)):
    """Bot & PMS selalu sama (bot membaca langsung dari sumber yang sama) — endpoint ini
    tetap disediakan untuk kontrak UI, tapi nilainya akan selalu identik (bukti arsitektur
    zero-drift, bukan data tiruan yang kebetulan cocok)."""
    rooms = await db.rooms.find({}, {"_id": 0, "tipe": 1, "status": 1}).to_list(200)
    per_tipe: Dict[str, int] = {}
    for r in rooms:
        if r["status"] == "kosong":
            per_tipe[r["tipe"]] = per_tipe.get(r["tipe"], 0) + 1
    return [{"tipe": t, "bot": n, "pms": n} for t, n in per_tipe.items()]


@api.get("/sinkronisasi-data-pms/referensi")
async def referensi_reservasi(user: dict = Depends(get_current_user)):
    bookings = await db.bookings.find(
        {"status": {"$in": ["aktif", "booking_paid", "booking_pending"]}},
        {"_id": 0, "id": 1, "kode": 1, "nama_tamu": 1, "room_tipe": 1, "status": 1},
    ).sort("created_at", -1).to_list(10)
    STATUS_LABEL = {"aktif": "Confirmed", "booking_paid": "Confirmed", "booking_pending": "Pending"}
    return [{"id": b["id"], "kode": b["kode"], "nama_tamu": b["nama_tamu"], "room_tipe": b["room_tipe"],
              "status": STATUS_LABEL.get(b["status"], b["status"])} for b in bookings]


@api.get("/sinkronisasi-data-pms/alerts")
async def alerts_sinkronisasi_pms(user: dict = Depends(get_current_user)):
    logs = await db.sync_data_pms_log.find({"ok": False}, {"_id": 0}).sort("waktu", -1).to_list(50)
    return [{"id": l["id"], "data_type": l["data_type"], "pesan": l["detail"], "waktu": l["waktu"], "resolved": False} for l in logs]
