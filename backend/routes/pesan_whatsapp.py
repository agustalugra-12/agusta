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


async def _cari_kamar_dari_no_hp(no_hp: str, property_id: str):
    """Cari kamar aktif tamu dari nomor HP-nya (checkin aktif, lalu booking checked_in sebagai
    fallback) — dicoba beberapa variasi format (0xxx vs 62xxx) karena provider WA & PMS bisa
    beda konvensi penyimpanan nomor.

    Multi-properti (2026-07-25) - `property_id` WAJIB diisi: tanpa ini, nomor HP tamu yang
    kebetulan sama/mirip di 2 properti berbeda bisa salah cocok ke kamar properti lain -
    ditemukan lewat evaluasi multi-properti, satu-satunya pemanggil (integrasi_ai_bot.py,
    tiket komplain AI) sudah tahu property_id dari API key bot yang dipakai."""
    digits = re.sub(r"\D", "", no_hp or "")
    if not digits:
        return None, ""
    variasi = {digits}
    if digits.startswith("62"):
        variasi.add("0" + digits[2:])
    elif digits.startswith("0"):
        variasi.add("62" + digits[1:])
    ci = await db.checkins.find_one(scoped({"no_hp": {"$in": list(variasi)}, "status": "aktif"}, property_id), {"_id": 0, "room_id": 1, "room_nomor": 1})
    if ci:
        return ci["room_id"], ci["room_nomor"]
    bk = await db.bookings.find_one(
        scoped({"no_hp": {"$in": list(variasi)}, "status": "checked_in"}, property_id),
        {"_id": 0, "room_id": 1, "room_nomor": 1}, sort=[("created_at", -1)],
    )
    if bk:
        return bk["room_id"], bk["room_nomor"]
    return None, ""


# ai-chat-bot's db.ai_bots.property_slug pakai konvensi singkat ("pelangi") - BEDA dari
# db.properties.slug di PMS ("pelangi-homestay") yang lebih deskriptif. Bukan pola
# slugify yang bisa diturunkan otomatis, jadi dipetakan manual di sini (2026-07-31,
# ditemukan lewat audit alur notifikasi WA - tanpa pemetaan ini, property_slug yang
# dikirim ke relay tidak akan pernah cocok dengan bot manapun untuk Pelangi).
_AI_BOT_PROPERTY_SLUG = {"pelangi-homestay": "pelangi", "harmoni": "harmoni"}


async def _property_slug_untuk_relay(property_id: Optional[str]) -> Optional[str]:
    if not property_id:
        return None
    slug = await property_slug_for(property_id)
    return _AI_BOT_PROPERTY_SLUG.get(slug, slug)


async def _kirim_via_provider(no_hp: str, pesan: str, template_name: Optional[str] = None,
                               template_params: Optional[list] = None,
                               property_id: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Kirim balasan lewat webhook provider yang staf konfigurasi sendiri (`webhook_config`,
    lihat routes/konfigurasi_webhook.py) — dalam praktiknya sekarang selalu mengarah ke
    relay ai-chat-bot (`/api/send-message`), yang meneruskan lewat WhatsApp Cloud API asli.
    Generic — payload dikirim dalam bentuk umum {to, message}.
    `template_name`/`template_params` (2026-07-26, opsional) - WAJIB diisi untuk notifikasi
    proaktif yang bisa terjadi lama setelah pesan terakhir tamu (approve/tolak staf,
    pembatalan, dst) - relay ai-chat-bot akan pakai Message Template resmi kalau nomor ini
    sudah di luar jendela layanan 24 jam Meta (teks bebas `pesan` ditolak Meta kalau itu
    terjadi). Lihat CHANGELOG 2026-07-26 untuk daftar lengkap template & pemetaan skenario.
    `property_id` (2026-07-31) - WAJIB diisi caller kalau tahu (hampir semua sudah tahu,
    tinggal dari `property_id`/`doc["property_id"]` yang sudah ada di scope) supaya relay
    ai-chat-bot bisa resolve channel WA yang BENAR (Fonnte Harmoni vs Cloud API Pelangi)
    kalau tamu ini belum pernah chat AI sama sekali - sebelumnya kasus itu SELALU fallback
    diam-diam ke Cloud API nomor Pelangi, salah utk tamu Harmoni (bug nyata ditemukan lewat
    audit alur booking/payment/invoice)."""
    cfg = await db.webhook_config.find_one({})
    if not cfg or not cfg.get("aktif") or not cfg.get("webhook_url") or not cfg.get("api_key"):
        return False, "Webhook belum dikonfigurasi/aktif"
    payload = {"to": no_hp, "message": pesan}
    if template_name:
        payload["template_name"] = template_name
        payload["template_params"] = template_params or []
    property_slug = await _property_slug_untuk_relay(property_id)
    if property_slug:
        payload["property_slug"] = property_slug
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                cfg["webhook_url"],
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json=payload,
            )
        if resp.status_code >= 400:
            return False, f"Provider merespons HTTP {resp.status_code}"
        return True, None
    except Exception as e:
        return False, f"Gagal menghubungi provider: {e}"


async def _kirim_dokumen_via_provider(no_hp: str, filename: str, mimetype: str, data_base64: str, caption: str = "",
                                       url: str = "", property_id: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Kirim FILE (PDF slip gaji, voucher, dst) lewat provider yang sama dengan
    _kirim_via_provider - dipakai routes/payroll.py & email_service.py. Endpoint dokumen
    diturunkan dari `webhook_url` yang sudah dikonfigurasi (ganti segmen path terakhir
    "send-message" -> "send-document") supaya tidak perlu field konfigurasi terpisah -
    kedua endpoint ada di server ai-chat-bot yang sama, kredensial `api_key` sama.

    `url` (2026-07-31, opsional) - link publik ke dokumen yang sama, diteruskan apa
    adanya ke relay ai-chat-bot supaya channel yang tidak support attachment (mis.
    paket Fonnte Agus) bisa kirim link teks sbg gantinya - lihat email_service.py
    kirim_voucher_wa utk contoh pengisiannya.
    `property_id` (2026-07-31) - sama alasannya dgn _kirim_via_provider: relay perlu tahu
    properti mana supaya voucher/dokumen tamu Harmoni tidak salah kirim lewat channel
    Pelangi kalau tamu itu belum pernah chat AI."""
    cfg = await db.webhook_config.find_one({})
    if not cfg or not cfg.get("aktif") or not cfg.get("webhook_url") or not cfg.get("api_key"):
        return False, "Webhook belum dikonfigurasi/aktif"
    doc_url = cfg["webhook_url"].rsplit("/", 1)[0] + "/send-document"
    payload = {"to": no_hp, "filename": filename, "mimetype": mimetype, "data_base64": data_base64,
               "caption": caption, "url": url}
    property_slug = await _property_slug_untuk_relay(property_id)
    if property_slug:
        payload["property_slug"] = property_slug
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                doc_url,
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json=payload,
            )
        if resp.status_code >= 400:
            return False, f"Provider merespons HTTP {resp.status_code}: {resp.text[:200]}"
        return True, None
    except Exception as e:
        return False, f"Gagal menghubungi provider: {e}"


async def _kirim_dengan_alert(no_hp: str, pesan: str, konteks: str, template_name: Optional[str] = None,
                               template_params: Optional[list] = None, property_id: Optional[str] = None) -> bool:
    """Wrapper `_kirim_via_provider` yang WAJIB dipakai semua notifikasi proaktif ke tamu
    (approve/tolak booking, pembatalan, kamar siap, dst) - 2026-07-26, ditemukan lewat audit
    bahwa 8 titik notifikasi proaktif SEMUANYA memanggil `_kirim_via_provider` tanpa pernah
    membaca hasilnya, jadi kalau gagal terkirim (WAHA down, atau di luar jendela 24 jam Meta
    tanpa template), staf TIDAK PERNAH TAHU tamu tidak dapat notifikasinya. Sekarang WAJIB
    alert Telegram owner supaya staf bisa follow-up manual (telepon/WA manual) kalau gagal."""
    ok, err = await _kirim_via_provider(no_hp, pesan, template_name=template_name, template_params=template_params,
                                        property_id=property_id)
    if not ok:
        from routes.telegram_bot import kirim_alert_owner
        await kirim_alert_owner(
            f"⚠️ GAGAL kirim WA ke tamu ({konteks}), no {no_hp}: {err}. "
            f"Tamu kemungkinan belum tahu update ini - mohon follow-up manual."
        )
    return ok
