from core import *
from urllib.parse import urlencode

import asyncio
import base64
import json
import logging
import httpx
from fastapi.responses import RedirectResponse
from openai import OpenAI

from reservation_service import check_room_available, create_reservation

_openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GMAIL_SCOPES = "openid email https://www.googleapis.com/auth/gmail.readonly"

# State CSRF sementara untuk alur OAuth (single-process, in-memory — cukup karena backend
# ini berjalan sebagai satu instance uvicorn, lihat server.py).
_oauth_states: Dict[str, datetime] = {}
_STATE_TTL_MINUTES = 10


def _new_state() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_STATE_TTL_MINUTES)
    for s, t in list(_oauth_states.items()):
        if t < cutoff:
            _oauth_states.pop(s, None)
    state = uuid.uuid4().hex
    _oauth_states[state] = datetime.now(timezone.utc)
    return state


def _consume_state(state: str) -> bool:
    return _oauth_states.pop(state, None) is not None


@api.get("/otomasi-email/gmail/status")
async def gmail_status(user: dict = Depends(get_current_user)):
    conn = await db.integrations.find_one(
        {"provider": "gmail"}, {"_id": 0, "access_token": 0, "refresh_token": 0}
    )
    if not conn:
        return {"connected": False}
    return {"connected": True, "email": conn.get("email"), "connected_at": conn.get("connected_at")}


@api.get("/otomasi-email/gmail/connect")
async def gmail_connect(user: dict = Depends(require_owner)):
    """Bangun URL consent Google OAuth. Frontend melakukan redirect penuh (window.location)
    ke auth_url ini, bukan panggilan fetch biasa, karena Google butuh navigasi browser asli.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_OAUTH_REDIRECT_URI:
        raise HTTPException(500, "Integrasi Gmail belum dikonfigurasi di server (GOOGLE_CLIENT_ID/GOOGLE_OAUTH_REDIRECT_URI)")
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GMAIL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": _new_state(),
    }
    return {"auth_url": f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"}


@api.get("/otomasi-email/gmail/callback")
async def gmail_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    user: dict = Depends(require_owner),
):
    """Redirect target dari Google setelah pemilik akun memberi consent. Cookie sesi ikut
    terkirim karena ini navigasi top-level (samesite=lax), jadi require_owner tetap berlaku.
    """
    target = f"{os.environ.get('FRONTEND_URL', '')}/otomasi-email"
    if error:
        return RedirectResponse(f"{target}?gmail=error&reason={error}")
    if not code or not state or not _consume_state(state):
        return RedirectResponse(f"{target}?gmail=error&reason=state_invalid")

    async with httpx.AsyncClient(timeout=10) as http:
        token_resp = await http.post(GOOGLE_TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            return RedirectResponse(f"{target}?gmail=error&reason=token_exchange_failed")
        tokens = token_resp.json()

        email = None
        userinfo_resp = await http.get(
            GOOGLE_USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {tokens.get('access_token', '')}"}
        )
        if userinfo_resp.status_code == 200:
            email = userinfo_resp.json().get("email")

    existing = await db.integrations.find_one({"provider": "gmail"})
    refresh_token = tokens.get("refresh_token") or (existing or {}).get("refresh_token")
    # Google hanya mengirim refresh_token pada consent pertama; re-connect berikutnya
    # (tanpa consent baru) tetap pertahankan refresh_token lama supaya tidak putus.
    doc = {
        "provider": "gmail",
        "email": email,
        "access_token": tokens.get("access_token"),
        "refresh_token": refresh_token,
        "token_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat(),
        "scope": tokens.get("scope"),
        "connected_by": user["id"],
        "connected_at": now_iso(),
    }
    await db.integrations.update_one({"provider": "gmail"}, {"$set": doc}, upsert=True)
    await log_activity(user, "gmail_connect", f"Hubungkan Gmail: {email}")
    return RedirectResponse(f"{target}?gmail=connected")


GMAIL_MESSAGES_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages"

# Domain pengirim -> sumber OTA, dipakai untuk menandai `sumber` di email_logs saat
# fetch (deteksi kasar dari alamat email, bukan AI — cukup untuk tahap pengambilan email;
# ekstraksi detail reservasi tetap tugas AI Email Parser di task backend terpisah).
SENDER_DOMAIN_SUMBER = {
    "agoda.com": "Agoda",
    "traveloka.com": "Traveloka",
    "booking.com": "Booking.com",
}
OTA_QUERY = "from:(" + " OR ".join(SENDER_DOMAIN_SUMBER.keys()) + ")"


def _tebak_sumber(pengirim: str) -> str:
    pengirim_lower = (pengirim or "").lower()
    for domain, sumber in SENDER_DOMAIN_SUMBER.items():
        if domain in pengirim_lower:
            return sumber
    return "Lainnya"


async def _ambil_access_token_valid(conn: dict) -> str:
    """Ambil access_token yang masih berlaku, refresh dulu via refresh_token kalau sudah
    (atau hampir) kedaluwarsa. `conn` = dokumen `integrations` provider gmail.
    """
    expires_at = conn.get("token_expires_at")
    masih_valid = False
    if expires_at:
        try:
            masih_valid = datetime.fromisoformat(expires_at) - datetime.now(timezone.utc) > timedelta(seconds=60)
        except Exception:
            masih_valid = False
    if masih_valid:
        return conn["access_token"]
    if not conn.get("refresh_token"):
        raise HTTPException(400, "Koneksi Gmail kedaluwarsa dan tidak ada refresh_token — hubungkan ulang Gmail")
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.post(GOOGLE_TOKEN_ENDPOINT, data={
            "refresh_token": conn["refresh_token"],
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        })
    if resp.status_code != 200:
        raise HTTPException(400, "Gagal memperbarui token Gmail — coba hubungkan ulang")
    tokens = resp.json()
    new_expiry = (datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat()
    await db.integrations.update_one(
        {"provider": "gmail"},
        {"$set": {"access_token": tokens["access_token"], "token_expires_at": new_expiry}},
    )
    return tokens["access_token"]


def _decode_body_part(data: str) -> str:
    padded = data.replace("-", "+").replace("_", "/")
    padded += "=" * (-len(padded) % 4)
    return base64.b64decode(padded).decode("utf-8", errors="replace")


def _extract_plain_body(payload: dict) -> str:
    """Cari bagian text/plain (fallback text/html) di payload Gmail message, termasuk
    yang bersarang di dalam `parts` (email multipart)."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_body_part(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        found = _extract_plain_body(part)
        if found:
            return found
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        import re
        html = _decode_body_part(payload["body"]["data"])
        return re.sub("<[^<]+?>", " ", html)
    return ""


PARSE_SYSTEM_PROMPT = """Kamu adalah AI Email Parser untuk sistem reservasi hotel Pelangi PMS.
Tugasmu: klasifikasi jenis notifikasi lalu ekstrak data dari isi email OTA (Agoda, Traveloka, Booking.com, dst).
Balas HANYA dengan JSON valid, tanpa teks lain.

Jika email BUKAN notifikasi reservasi (bukan booking baru/modifikasi/pembatalan) atau
informasinya tidak cukup untuk diekstrak, balas:
{"is_reservation": false, "alasan": "<alasan singkat kenapa gagal/kurang, dalam Bahasa Indonesia>"}

Jika email notifikasi RESERVASI BARU, balas:
{"is_reservation": true, "jenis": "baru", "data": {
  "no_reservasi": "<string>",
  "nama_tamu": "<string>",
  "tipe_kamar": "<string, nama tipe kamar apa adanya sesuai istilah di email>",
  "check_in": "<ISO 8601 datetime, asumsikan jam 14:00 kalau jam tidak disebutkan>",
  "check_out": "<ISO 8601 datetime, asumsikan jam 12:00 kalau jam tidak disebutkan>",
  "jumlah_tamu": <integer>,
  "harga": <integer, total harga dalam Rupiah tanpa simbol/pemisah ribuan>,
  "status_pembayaran": "<salah satu persis: Lunas | Belum Bayar | Dibatalkan>"
}}

Jika email notifikasi MODIFIKASI (perubahan tanggal/kamar/detail atas reservasi yang SUDAH
ADA sebelumnya) atau PEMBATALAN reservasi yang sudah ada, balas — cukup data seperlunya untuk
mencocokkan reservasi lama, JANGAN karang ulang detail kamar/tanggal baru:
{"is_reservation": true, "jenis": "<persis "modifikasi" atau "pembatalan">", "data": {
  "no_reservasi": "<string, WAJIB — nomor reservasi OTA yang dimodifikasi/dibatalkan>",
  "nama_tamu": "<string, kalau disebutkan, boleh kosong>"
}}
"""

async def parse_email_with_ai(subjek: str, pengirim: str, isi_email: str) -> dict:
    if not _openai_client:
        raise HTTPException(500, "OPENAI_API_KEY belum dikonfigurasi di server")
    resp = await asyncio.to_thread(
        _openai_client.chat.completions.create,
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        temperature=0,
        messages=[
            {"role": "system", "content": PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Subjek: {subjek}\nPengirim: {pengirim}\n\nIsi email:\n{isi_email[:6000]}"},
        ],
    )
    return json.loads(resp.choices[0].message.content)


async def buat_reservasi_otomatis(log_id: str, data: dict, sumber: str, subjek: str) -> None:
    """Reservation Automation (PRD): dari data hasil AI Email Parser, buat reservasi
    otomatis di Pelangi PMS tanpa input manual staf — asalkan (a) tipe kamar OTA sudah
    dipetakan ke tipe kamar PMS, dan (b) ada kamar tipe itu yang benar-benar kosong di
    rentang tanggalnya (anti double-booking, pakai check_room_available yang sama dengan
    booking publik). Kalau salah satu syarat gagal, log tetap Manual_Required dengan alasan
    jelas supaya staf yang selesaikan — TIDAK memaksakan buat reservasi yang berisiko bentrok.
    """
    mapping = await db.room_mappings.find_one({"ota_nama": data.get("tipe_kamar"), "sumber": sumber})
    if not mapping:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": f'Tipe kamar OTA "{data.get("tipe_kamar")}" ({sumber}) belum dipetakan ke tipe kamar PMS — petakan dulu di halaman Pemetaan Tipe Kamar, lalu proses ulang.',
        }})
        return

    try:
        check_in = parse_iso(data["check_in"], "check_in")
        check_out = parse_iso(data["check_out"], "check_out")
    except HTTPException:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required", "alasan": "Format tanggal check-in/check-out hasil AI tidak valid — isi manual.",
        }})
        return

    kandidat = await db.rooms.find({"tipe": mapping["pms_tipe"]}, {"_id": 0}).to_list(200)
    room = None
    for r in kandidat:
        try:
            await check_room_available(r["id"], check_in, check_out)
            room = r
            break
        except HTTPException:
            continue
    if not room:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": f'Tidak ada kamar {mapping["pms_tipe"]} yang kosong pada {check_in.date()}–{check_out.date()} (kemungkinan bentrok) — perlu ditinjau manual staf.',
        }})
        return

    total = int(data.get("harga") or 0) or room["tarif"]
    booking = await create_reservation(
        {
            "room_id": room["id"],
            "nama_tamu": data.get("nama_tamu", ""), "no_hp": "", "email": "",
            "no_identitas": "", "kendaraan": "",
            "jumlah_tamu": data.get("jumlah_tamu") or 1,
            "jam_mulai": check_in, "jam_selesai": check_out,
            "catatan": f'Reservasi OTA otomatis dari email "{subjek}" ({sumber}, no. {data.get("no_reservasi", "-")})',
            "created_by": "ai_email_parser",
            "tipe": "menginap",
        },
        source="ota",
        harga_override={"subtotal": total, "service_fee": 0, "total": total, "dp_min": 0},
    )
    update_fields = {"ota_reservation_no": data.get("no_reservasi")}
    if data.get("status_pembayaran") == "Lunas":
        update_fields.update({"payment_status": "paid", "status": "aktif"})
    await db.bookings.update_one({"id": booking["id"]}, {"$set": update_fields})
    await db.email_logs.update_one({"id": log_id}, {"$set": {"reservation_id": booking["id"], "aksi": "reservasi_baru_dibuat"}})


async def batalkan_reservasi_otomatis(log_id: str, data: dict, sumber: str, subjek: str) -> None:
    """Reservation Automation untuk email MODIFIKASI/PEMBATALAN (keputusan bisnis user
    2026-07-12): OTA mengirim notifikasi modifikasi/pembatalan terpisah dari notifikasi
    reservasi baru — daripada menebak detail baru (berisiko salah), reservasi PMS yang cocok
    (dicari dari `ota_reservation_no` yang disimpan saat reservasi baru dibuat) langsung
    DIBATALKAN otomatis, sama persis kedua jenis notifikasi ini. Kalau OTA mengirim reservasi
    baru pengganti (dengan no. reservasi baru), itu akan masuk lagi lewat buat_reservasi_otomatis
    seperti biasa. Kalau reservasi lama tidak ditemukan, log Manual_Required — tidak menebak.
    """
    no_reservasi = data.get("no_reservasi")
    if not no_reservasi:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": "Email modifikasi/pembatalan tidak menyebutkan nomor reservasi OTA — tidak bisa dicocokkan otomatis, cek manual.",
        }})
        return

    booking = await db.bookings.find_one({
        "ota_reservation_no": no_reservasi,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
    })
    if not booking:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": f'Tidak ditemukan reservasi PMS aktif dengan no. OTA "{no_reservasi}" untuk dibatalkan — kemungkinan sudah dibatalkan/selesai sebelumnya, atau reservasi awalnya belum pernah berhasil dibuat otomatis. Cek manual.',
        }})
        return

    now = now_iso()
    await db.bookings.update_one({"id": booking["id"]}, {"$set": {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": "ai_email_parser",
        "cancel_reason": f'Dibatalkan otomatis: email {data.get("jenis", "modifikasi/pembatalan")} OTA "{subjek}" ({sumber}, no. {no_reservasi})',
        "cancel_fee": 0, "refund_amount": 0,
    }})
    await log_availability_change(booking["room_id"], booking.get("room_tipe", ""), 1, "booking_dibatalkan_otomatis_ota", booking_id=booking["id"])
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "ai_email_parser",
        "action": "cancel_ota_auto",
        "detail": f'Batalkan otomatis {booking["kode"]} (no. OTA {no_reservasi}) dari email modifikasi/pembatalan "{subjek}"',
        "entity": booking.get("room_nomor", ""), "timestamp": now,
    })
    await db.email_logs.update_one({"id": log_id}, {"$set": {"reservation_id": booking["id"], "aksi": "reservasi_dibatalkan"}})


async def fetch_gmail_emails(max_results: int = 20) -> int:
    """Ambil email OTA terbaru dari Gmail (isi lengkap), lalu proses lewat AI Email Parser
    dan simpan ke `email_logs`. Status Parsed_Success kalau AI berhasil ekstrak, Manual_Required
    kalau AI bilang bukan/gagal reservasi, Failed kalau ada error teknis. Mengembalikan jumlah
    email baru yang disimpan (skip yang sudah pernah diambil, dicek via gmail_message_id).
    """
    conn = await db.integrations.find_one({"provider": "gmail"})
    if not conn:
        raise HTTPException(400, "Gmail belum terhubung")
    access_token = await _ambil_access_token_valid(conn)
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as http:
        list_resp = await http.get(GMAIL_MESSAGES_ENDPOINT, headers=headers, params={"q": OTA_QUERY, "maxResults": max_results})
        if list_resp.status_code != 200:
            raise HTTPException(502, "Gagal mengambil daftar email dari Gmail")
        message_ids = [m["id"] for m in list_resp.json().get("messages", [])]

        disimpan = 0
        for mid in message_ids:
            if await db.email_logs.find_one({"gmail_message_id": mid}):
                continue  # sudah pernah diambil sebelumnya
            detail_resp = await http.get(f"{GMAIL_MESSAGES_ENDPOINT}/{mid}", headers=headers, params={"format": "full"})
            if detail_resp.status_code != 200:
                continue
            msg = detail_resp.json()
            hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            subjek = hdrs.get("Subject", "(tanpa subjek)")
            pengirim = hdrs.get("From", "")
            isi_email = _extract_plain_body(msg.get("payload", {})) or msg.get("snippet", "")

            status, extracted_data, alasan, jenis = "Failed", None, "Error tidak diketahui saat parsing AI", None
            try:
                hasil = await parse_email_with_ai(subjek, pengirim, isi_email)
                if hasil.get("is_reservation"):
                    extracted_data = hasil["data"]
                    jenis = hasil.get("jenis") or "baru"
                    status, alasan = "Parsed_Success", None
                else:
                    status = "Manual_Required"
                    alasan = hasil.get("alasan", "AI menilai email ini bukan notifikasi reservasi")
            except Exception as e:
                status, alasan = "Failed", f"Gagal memanggil AI Email Parser: {e}"

            sumber = _tebak_sumber(pengirim)
            doc = {
                "id": str(uuid.uuid4()),
                "gmail_message_id": mid,
                "subjek": subjek,
                "pengirim": pengirim,
                "sumber": sumber,
                "status": status,
                "jenis": jenis,
                "extracted_data": extracted_data,
                "alasan": alasan,
                "processed_at": now_iso(),
            }
            await db.email_logs.insert_one(doc)
            disimpan += 1

            if status == "Parsed_Success":
                # Reservation Automation (PRD + keputusan bisnis 2026-07-12): reservasi baru
                # langsung dibuat, modifikasi/pembatalan langsung membatalkan reservasi lama
                # yang cocok — semua tanpa menunggu staf. Bisa mengubah status doc ini balik ke
                # Manual_Required kalau ada yang tidak bisa dicocokkan otomatis (lihat masing2 fungsi).
                if jenis == "baru":
                    await buat_reservasi_otomatis(doc["id"], extracted_data, sumber, subjek)
                else:
                    await batalkan_reservasi_otomatis(doc["id"], {**extracted_data, "jenis": jenis}, sumber, subjek)
    return disimpan


@api.post("/otomasi-email/gmail/fetch")
async def gmail_fetch(user: dict = Depends(require_owner)):
    jumlah = await fetch_gmail_emails()
    await log_activity(user, "gmail_fetch", f"Ambil {jumlah} email baru dari Gmail")
    return {"fetched": jumlah}


GMAIL_AUTO_FETCH_INTERVAL_SECONDS = 60  # cek email OTA baru tiap 1 menit, tanpa staf klik manual


async def background_gmail_fetch_loop():
    """Auto-fetch Gmail berkala (keputusan bisnis user 2026-07-12: reservasi OTA harus
    otomatis penuh tanpa staf klik "Cek Email Baru"). Hanya jalan kalau Gmail sudah
    terhubung; kegagalan (token expired, Gmail API down, dst) di-log tapi tidak menghentikan
    loop — dicoba lagi di siklus berikutnya, sama seperti background_sync_loop ketersediaan.
    """
    while True:
        try:
            conn = await db.integrations.find_one({"provider": "gmail"})
            if conn:
                await fetch_gmail_emails()
        except Exception as e:
            logging.getLogger("uvicorn.error").warning(f"Gmail auto-fetch gagal: {e}")
        await asyncio.sleep(GMAIL_AUTO_FETCH_INTERVAL_SECONDS)


@api.get("/otomasi-email/logs")
async def list_email_logs(status: Optional[str] = Query(None), user: dict = Depends(get_current_user)):
    """Log Email Masuk (semua status) — filter opsional `status` juga dipakai untuk
    tab "Proses Manual" (status=Manual_Required atau Failed di frontend, filter di client
    karena keduanya perlu ditampilkan bersama)."""
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    logs = await db.email_logs.find(q, {"_id": 0}).sort("processed_at", -1).to_list(500)
    return logs


@api.post("/otomasi-email/logs/{log_id}/proses-manual")
async def proses_manual_email(log_id: str, body: EmailExtractedData, user: dict = Depends(require_owner)):
    """Staf melengkapi data reservasi secara manual untuk email yang gagal/perlu diproses
    manual — begitu disimpan, tetap lanjut ke Reservation Automation yang sama seperti hasil
    AI (buat_reservasi_otomatis), konsisten dengan alur "Simpan & Buat Reservasi" di UI.
    """
    log = await db.email_logs.find_one({"id": log_id})
    if not log:
        raise HTTPException(404, "Log email tidak ditemukan")
    data = body.model_dump()
    await db.email_logs.update_one({"id": log_id}, {"$set": {
        "status": "Parsed_Success", "extracted_data": data, "alasan": None,
    }})
    await buat_reservasi_otomatis(log_id, data, log["sumber"], log["subjek"])
    await log_activity(user, "proses_manual_email", f'Proses manual email "{log["subjek"]}"')
    return await db.email_logs.find_one({"id": log_id}, {"_id": 0})


@api.get("/otomasi-email/mapping-rules")
async def list_mapping_rules(user: dict = Depends(get_current_user)):
    rules = await db.mapping_rules.find({}, {"_id": 0}).to_list(500)
    rules.sort(key=lambda r: (r["sumber"], r["field"]))
    return rules


@api.post("/otomasi-email/mapping-rules")
async def create_mapping_rule(body: MappingRuleCreate, user: dict = Depends(require_owner)):
    doc = {"id": str(uuid.uuid4()), **body.model_dump(), "created_at": now_iso()}
    await db.mapping_rules.insert_one(doc)
    await log_activity(user, "create_mapping_rule", f"Buat aturan pemetaan {body.field} ({body.sumber})")
    doc.pop("_id", None)
    return doc


@api.put("/otomasi-email/mapping-rules/{rule_id}")
async def update_mapping_rule(rule_id: str, body: MappingRuleUpdate, user: dict = Depends(require_owner)):
    r = await db.mapping_rules.find_one({"id": rule_id})
    if not r:
        raise HTTPException(404, "Aturan tidak ditemukan")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await db.mapping_rules.update_one({"id": rule_id}, {"$set": updates})
    await log_activity(user, "update_mapping_rule", f'Update aturan pemetaan "{r["field"]}" ({r["sumber"]})')
    return {"ok": True}


@api.delete("/otomasi-email/mapping-rules/{rule_id}")
async def delete_mapping_rule(rule_id: str, user: dict = Depends(require_owner)):
    r = await db.mapping_rules.find_one({"id": rule_id})
    if not r:
        raise HTTPException(404, "Aturan tidak ditemukan")
    await db.mapping_rules.delete_one({"id": rule_id})
    await log_activity(user, "delete_mapping_rule", f'Hapus aturan pemetaan "{r["field"]}" ({r["sumber"]})')
    return {"ok": True}


@api.post("/otomasi-email/gmail/disconnect")
async def gmail_disconnect(user: dict = Depends(require_owner)):
    conn = await db.integrations.find_one({"provider": "gmail"})
    if not conn:
        raise HTTPException(404, "Gmail belum terhubung")
    token = conn.get("refresh_token") or conn.get("access_token")
    if token:
        async with httpx.AsyncClient(timeout=10) as http:
            try:
                await http.post(GOOGLE_REVOKE_ENDPOINT, data={"token": token})
            except Exception:
                pass  # revoke bersifat best-effort; koneksi lokal tetap dihapus
    await db.integrations.delete_one({"provider": "gmail"})
    await log_activity(user, "gmail_disconnect", f"Putuskan Gmail: {conn.get('email')}")
    return {"ok": True}
