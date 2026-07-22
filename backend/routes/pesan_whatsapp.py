"""Utilitas pengiriman WhatsApp KELUAR (relay generik via `webhook_config`, dipanggil
routes/booking_requests.py, pembatalan.py, payroll.py, public.py, email_service.py) +
`_cari_kamar_dari_no_hp` (dipakai routes/integrasi_ai_bot.py).

Sebelumnya file ini (`pesan_whatsapp.py`) juga berisi AI chat WhatsApp MASUK bawaan PMS
sendiri (webhook generik + BalesOtomatis, klasifikasi niat booking, alur pengumpulan data,
log percakapan, pemantauan status) - DIHAPUS 2026-07-22 (permintaan user "rampingkan PMS")
setelah dikonfirmasi `db.wa_conversations` = 0 dokumen SELAMANYA (fitur ini tidak pernah
benar-benar memproses satu percakapan nyata pun sejak dibuat - kanal produksi WhatsApp yang
sungguhan sekarang sepenuhnya lewat sistem ai-chat-bot terpisah, lihat
routes/integrasi_ai_bot.py & konfigurasi-integrasi-ai-bot). Riwayat lengkap kode lama ada
di git history sebelum commit ini kalau suatu saat dibutuhkan lagi."""
from core import *
import httpx


async def _cari_kamar_dari_no_hp(no_hp: str):
    """Cari kamar aktif tamu dari nomor HP-nya (checkin aktif, lalu booking checked_in sebagai
    fallback) — dicoba beberapa variasi format (0xxx vs 62xxx) karena provider WA & PMS bisa
    beda konvensi penyimpanan nomor."""
    digits = re.sub(r"\D", "", no_hp or "")
    if not digits:
        return None, ""
    variasi = {digits}
    if digits.startswith("62"):
        variasi.add("0" + digits[2:])
    elif digits.startswith("0"):
        variasi.add("62" + digits[1:])
    ci = await db.checkins.find_one({"no_hp": {"$in": list(variasi)}, "status": "aktif"}, {"_id": 0, "room_id": 1, "room_nomor": 1})
    if ci:
        return ci["room_id"], ci["room_nomor"]
    bk = await db.bookings.find_one(
        {"no_hp": {"$in": list(variasi)}, "status": "checked_in"},
        {"_id": 0, "room_id": 1, "room_nomor": 1}, sort=[("created_at", -1)],
    )
    if bk:
        return bk["room_id"], bk["room_nomor"]
    return None, ""


async def _kirim_via_provider(no_hp: str, pesan: str) -> tuple[bool, Optional[str]]:
    """Kirim balasan lewat webhook provider yang staf konfigurasi sendiri (`webhook_config`,
    lihat routes/konfigurasi_webhook.py) — dalam praktiknya sekarang selalu mengarah ke
    relay ai-chat-bot (`/api/send-message`), yang meneruskan lewat WhatsApp Cloud API asli.
    Generic — payload dikirim dalam bentuk umum {to, message}."""
    cfg = await db.webhook_config.find_one({})
    if not cfg or not cfg.get("aktif") or not cfg.get("webhook_url") or not cfg.get("api_key"):
        return False, "Webhook belum dikonfigurasi/aktif"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                cfg["webhook_url"],
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json={"to": no_hp, "message": pesan},
            )
        if resp.status_code >= 400:
            return False, f"Provider merespons HTTP {resp.status_code}"
        return True, None
    except Exception as e:
        return False, f"Gagal menghubungi provider: {e}"


async def _kirim_dokumen_via_provider(no_hp: str, filename: str, mimetype: str, data_base64: str, caption: str = "") -> tuple[bool, Optional[str]]:
    """Kirim FILE (PDF slip gaji, voucher, dst) lewat provider yang sama dengan
    _kirim_via_provider - dipakai routes/payroll.py & email_service.py. Endpoint dokumen
    diturunkan dari `webhook_url` yang sudah dikonfigurasi (ganti segmen path terakhir
    "send-message" -> "send-document") supaya tidak perlu field konfigurasi terpisah -
    kedua endpoint ada di server ai-chat-bot yang sama, kredensial `api_key` sama."""
    cfg = await db.webhook_config.find_one({})
    if not cfg or not cfg.get("aktif") or not cfg.get("webhook_url") or not cfg.get("api_key"):
        return False, "Webhook belum dikonfigurasi/aktif"
    doc_url = cfg["webhook_url"].rsplit("/", 1)[0] + "/send-document"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                doc_url,
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json={"to": no_hp, "filename": filename, "mimetype": mimetype, "data_base64": data_base64, "caption": caption},
            )
        if resp.status_code >= 400:
            return False, f"Provider merespons HTTP {resp.status_code}: {resp.text[:200]}"
        return True, None
    except Exception as e:
        return False, f"Gagal menghubungi provider: {e}"
