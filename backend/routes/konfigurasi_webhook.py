from core import *
import httpx

# ---- Konfigurasi Webhook (WhatsApp Bot) ----
# Kredensial (webhook_url, api_key) sepenuhnya milik staf/pemilik akun provider mereka
# sendiri (Fonnte/Wablas/Qontak/dst) — endpoint di sini cuma menyimpan & memakai apa yang
# staf masukkan, tidak perlu API key pihak ketiga milik developer.

DEFAULT_WEBHOOK_CONFIG = {
    "aktif": False, "provider": "Fonnte", "webhook_url": "", "api_key": "",
    "nomor_whatsapp": "", "webhook_token": None, "updated_at": None,
}


@api.get("/konfigurasi-webhook")
async def get_webhook_config(user: dict = Depends(get_current_user)):
    """`webhook_token` dipakai untuk URL webhook MASUK (provider seperti BalesOtomatis
    yang memanggil PMS, bukan sebaliknya) — dibuat sekali otomatis di sini kalau belum ada,
    supaya staf selalu punya URL untuk ditempel ke dashboard provider sejak GET pertama,
    bahkan sebelum form disimpan.
    """
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    cfg = {**DEFAULT_WEBHOOK_CONFIG, **(cfg or {})}
    if not cfg.get("webhook_token"):
        cfg["webhook_token"] = uuid.uuid4().hex
        # $set seluruh cfg (bukan cuma webhook_token) — kalau dokumen belum ada sama
        # sekali, upsert cuma menulis field yang di-$set; menulis token doang bikin
        # dokumen di DB jadi setengah (tanpa aktif/provider/dst), dan GET berikutnya
        # balikin objek setengah itu apa adanya karena cfg sudah truthy.
        await db.webhook_config.update_one({}, {"$set": cfg}, upsert=True)
    return cfg


@api.put("/konfigurasi-webhook")
async def save_webhook_config(body: WebhookConfigUpdate, user: dict = Depends(require_owner)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["updated_at"] = now_iso()
    updates["updated_by"] = user["id"]
    await db.webhook_config.update_one({}, {"$set": updates}, upsert=True)
    await log_activity(user, "save_webhook_config", "Simpan konfigurasi webhook WhatsApp")
    return await db.webhook_config.find_one({}, {"_id": 0}) or DEFAULT_WEBHOOK_CONFIG


@api.post("/konfigurasi-webhook/test")
async def test_webhook_config(user: dict = Depends(require_owner)):
    """Uji koneksi. Untuk provider BalesOtomatis arahnya TERBALIK dari Fonnte/Wablas/dst —
    BalesOtomatis yang memanggil PMS (lewat URL Webhook Masuk), bukan PMS yang memanggil
    provider — jadi tidak ada URL keluar untuk di-ping, cukup pastikan kredensial (API key +
    Nomor/Device ID) sudah diisi. Provider lain tetap diuji sungguhan (panggil webhook_url
    tersimpan), bukan simulasi. Berhasil kalau endpoint merespons (status apa pun < 500
    dianggap "endpoint hidup"); dicatat ke `wa_connection_log` supaya riwayat gangguan bisa
    dipantau di Pemantauan Status.
    """
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    if not cfg:
        result = {"ok": False, "message": "Konfigurasi webhook belum disimpan.", "tested_at": now_iso()}
    elif cfg.get("provider") == "BalesOtomatis":
        if not cfg.get("api_key") or not cfg.get("nomor_whatsapp"):
            result = {"ok": False, "message": "API key atau Nomor/Device ID belum diisi.", "tested_at": now_iso()}
        else:
            result = {
                "ok": True,
                "message": "Kredensial tersimpan. Pastikan URL Webhook Masuk di atas sudah ditempel di dashboard BalesOtomatis (Pengaturan Device > Webhook/AI Trigger) — PMS tidak bisa menguji ini dari sisi kita karena arah panggilannya dari BalesOtomatis ke PMS.",
                "tested_at": now_iso(),
            }
    elif not cfg.get("webhook_url") or not cfg.get("api_key"):
        result = {"ok": False, "message": "Endpoint atau API key belum diisi.", "tested_at": now_iso()}
    else:
        try:
            async with httpx.AsyncClient(timeout=8) as http:
                resp = await http.get(cfg["webhook_url"], headers={"Authorization": f"Bearer {cfg['api_key']}"})
            ok = resp.status_code < 500
            result = {
                "ok": ok,
                "message": f"Endpoint merespons (HTTP {resp.status_code})." if ok else f"Endpoint error (HTTP {resp.status_code}).",
                "tested_at": now_iso(),
            }
        except Exception as e:
            result = {"ok": False, "message": f"Gagal terhubung: {e}", "tested_at": now_iso()}
    await db.wa_connection_log.insert_one({
        "id": str(uuid.uuid4()), "event": "test_koneksi",
        "detail": result["message"], "ok": result["ok"], "waktu": result["tested_at"],
    })
    return result
