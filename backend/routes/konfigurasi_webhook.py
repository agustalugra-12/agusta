from core import *
import httpx

# ---- Konfigurasi Webhook (WhatsApp Bot) ----
# Kredensial (webhook_url, api_key) sepenuhnya milik staf/pemilik akun provider mereka
# sendiri (Fonnte/Wablas/Qontak/dst) — endpoint di sini cuma menyimpan & memakai apa yang
# staf masukkan, tidak perlu API key pihak ketiga milik developer.

DEFAULT_WEBHOOK_CONFIG = {
    "aktif": False, "provider": "Fonnte", "webhook_url": "", "api_key": "",
    "nomor_whatsapp": "", "updated_at": None,
}


@api.get("/konfigurasi-webhook")
async def get_webhook_config(user: dict = Depends(get_current_user)):
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    return cfg or DEFAULT_WEBHOOK_CONFIG


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
    """Uji koneksi sungguhan — panggil webhook_url tersimpan (bukan simulasi). Berhasil
    kalau endpoint merespons (status apa pun < 500 dianggap "endpoint hidup"); dicatat ke
    `wa_connection_log` supaya riwayat gangguan bisa dipantau di Pemantauan Status.
    """
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("webhook_url") or not cfg.get("api_key"):
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
