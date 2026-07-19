from core import *
from urllib.parse import urlencode

import asyncio
import base64
import json
import logging
import httpx
from fastapi.responses import RedirectResponse
from openai import OpenAI

from reservation_service import check_room_available, create_reservation, room_locks

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
#
# Keputusan bisnis user (2026-07-12): PMS ini HANYA fokus baca email reservasi dari
# bookings-indonesia@reddoorz.com di inbox agus.lugra@gmail.com — bukan lagi Agoda/
# Traveloka/Booking.com generik seperti sebelumnya (itu sebabnya booking RedDoorz
# nyata yang masuk sebelumnya tidak pernah kesync: query Gmail lama tidak pernah
# mencari domain reddoorz.com sama sekali).
SENDER_DOMAIN_SUMBER = {
    "reddoorz.com": "RedDoorz",
}
OTA_QUERY = "from:bookings-indonesia@reddoorz.com"


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
Tugasmu: klasifikasi jenis notifikasi lalu ekstrak data dari isi email reservasi OTA RedDoorz
(pengirim bookings-indonesia@reddoorz.com).
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
  "jumlah_tamu": <integer, jumlah tamu PER KAMAR — kalau email menyebut field "Jumlah Tamu" berformat "A*B" (mis. "2*3"), A adalah jumlah tamu per kamar dan B adalah jumlah kamar (harus sama dengan "Jumlah Kamar" di bawah); ambil HANYA A untuk field ini>,
  "harga": <integer, TOTAL harga SELURUH kamar dalam Rupiah tanpa simbol/pemisah ribuan (kalau ada field "Jumlah Yang Dibayarkan", itu totalnya)>,
  "status_pembayaran": "<salah satu persis: Lunas | Belum Bayar | Dibatalkan>",
  "jumlah_kamar": <integer, dari field "Jumlah Kamar" di email kalau ada disebutkan eksplisit, kalau tidak disebutkan asumsikan 1>
}}

Jika email notifikasi MODIFIKASI (perubahan tanggal/kamar/detail atas reservasi yang SUDAH ADA
sebelumnya), balas — sertakan tanggal check-in/check-out BARU HANYA kalau disebutkan eksplisit
di isi email (dipakai sistem untuk membandingkan dengan jadwal lama di PMS dan menentukan
otomatis apakah ini reschedule atau pembatalan terselubung); JANGAN MENGARANG kalau tidak
disebutkan jelas — kosongkan string-nya:
{"is_reservation": true, "jenis": "modifikasi", "data": {
  "no_reservasi": "<string, WAJIB — nomor reservasi OTA yang dimodifikasi>",
  "nama_tamu": "<string, kalau disebutkan, boleh kosong>",
  "check_in": "<ISO 8601 datetime check-in BARU kalau disebutkan eksplisit, kalau tidak: string kosong "">",
  "check_out": "<ISO 8601 datetime check-out BARU kalau disebutkan eksplisit, kalau tidak: string kosong "">"
}}

Jika email notifikasi PEMBATALAN reservasi yang sudah ada, balas — cukup data seperlunya untuk
mencocokkan reservasi lama, JANGAN karang detail kamar/tanggal:
{"is_reservation": true, "jenis": "pembatalan", "data": {
  "no_reservasi": "<string, WAJIB — nomor reservasi OTA yang dibatalkan>",
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


async def _cocokkan_booking_pending_reddoorz(nama_tamu: str, room_tipe: str, check_in: datetime, jumlah_kamar: int) -> list:
    """Cari booking yang sudah dibuat & lunas lewat Booking Request (AI WhatsApp -> approval
    -> Tripay, `backend/routes/booking_requests.py`) dan sedang menunggu sinkron RedDoorz
    (`sync_status="waiting_reddoorz_sync"` — staf sudah klik "Sudah Input ke RedDoorz") yang
    cocok dengan email konfirmasi ini. Dipakai `buat_reservasi_otomatis` supaya TIDAK membuat
    booking duplikat untuk reservasi yang sebenarnya sudah ada. Cocok = tipe kamar sama,
    check-in beda maksimal 1 hari (RedDoorz kadang beda pembulatan zona waktu), dan nama tamu
    beririsan (longgar, huruf/angka saja, case-insensitive) — tidak exact match karena ejaan
    AI WhatsApp vs RedDoorz bisa sedikit beda. Return maksimal `jumlah_kamar` kandidat."""
    kandidat = await db.bookings.find({
        "source": "whatsapp_request", "sync_status": "waiting_reddoorz_sync",
        "room_tipe": room_tipe, "tipe": "menginap",
    }, {"_id": 0}).to_list(50)
    nama_norm = re.sub(r"[^a-z0-9]", "", (nama_tamu or "").lower())
    cocok = []
    for b in kandidat:
        try:
            b_checkin = parse_iso(b["jam_mulai"], "jam_mulai")
        except HTTPException:
            continue
        if abs((b_checkin.date() - check_in.date()).days) > 1:
            continue
        b_nama_norm = re.sub(r"[^a-z0-9]", "", (b.get("nama_tamu") or "").lower())
        if nama_norm and b_nama_norm and (nama_norm in b_nama_norm or b_nama_norm in nama_norm):
            cocok.append(b)
    return cocok[:jumlah_kamar]


async def buat_reservasi_otomatis(log_id: str, data: dict, sumber: str, subjek: str) -> None:
    """Reservation Automation (PRD): dari data hasil AI Email Parser, buat reservasi
    otomatis di Pelangi PMS tanpa input manual staf — asalkan (a) tipe kamar OTA sudah
    dipetakan ke tipe kamar PMS, dan (b) ada kamar tipe itu yang benar-benar kosong di
    rentang tanggalnya (anti double-booking, pakai check_room_available yang sama dengan
    booking publik). Kalau salah satu syarat gagal, log tetap Manual_Required dengan alasan
    jelas supaya staf yang selesaikan — TIDAK memaksakan buat reservasi yang berisiko bentrok.

    Satu email OTA bisa memesan LEBIH DARI SATU kamar sekaligus (mis. RedDoorz "Jumlah Kamar
    : 3", satu nomor reservasi mencakup beberapa kamar tipe yang sama) — dibuat 1 booking PMS
    per kamar, semuanya menandai `ota_reservation_no` yang sama supaya modifikasi/pembatalan
    berikutnya (dicocokkan lewat nomor itu) ikut memproses semua kamar dalam grup ini, bukan
    cuma satu. Total harga di email (`harga`) mencakup SELURUH kamar, dibagi rata per kamar.
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

    jumlah_kamar = max(1, min(int(data.get("jumlah_kamar") or 1), 20))  # batas atas jaga-jaga dari data OTA yang tidak masuk akal

    # Tahap 2 Modul Reservasi (2026-07-17): kalau ini email konfirmasi RedDoorz untuk booking
    # yang SUDAH dibuat & lunas lewat Booking Request (AI WhatsApp -> approval -> Tripay),
    # jangan buat reservasi baru (jadi duplikat) — tandai booking yang sudah ada sebagai
    # tersinkron. Hanya short-circuit kalau SEMUA kamar di email berhasil dicocokkan dengan
    # keyakinan (1 kandidat unik per kamar); kalau ambigu/sebagian, biarkan jalan ke alur lama
    # di bawah (lebih aman duplikat yang bisa direkonsiliasi manual staf, daripada salah tandai
    # booking orang lain sebagai tersinkron).
    pending_match = await _cocokkan_booking_pending_reddoorz(
        data.get("nama_tamu", ""), mapping["pms_tipe"], check_in, jumlah_kamar
    )
    if len(pending_match) == jumlah_kamar:
        reservation_ids = []
        for b in pending_match:
            await db.bookings.update_one({"id": b["id"]}, {"$set": {
                "sync_status": "synced", "ota_reservation_no": data.get("no_reservasi"), "updated_at": now_iso(),
            }})
            reservation_ids.append(b["id"])
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "reservation_id": reservation_ids[0], "reservation_ids": reservation_ids,
            "aksi": "reservasi_baru_dibuat", "status": "Parsed_Success",
        }})
        return

    kandidat = await db.rooms.find({"tipe": mapping["pms_tipe"]}, {"_id": 0}).to_list(200)
    dipilih = []
    for r in kandidat:
        if len(dipilih) >= jumlah_kamar:
            break
        try:
            await check_room_available(r["id"], check_in, check_out)
            dipilih.append(r)
        except HTTPException:
            continue
    if not dipilih:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": f'Tidak ada kamar {mapping["pms_tipe"]} yang kosong pada {check_in.date()}–{check_out.date()} (kemungkinan bentrok) — perlu ditinjau manual staf.',
        }})
        return

    # Booking "Prepaid" RedDoorz TIDAK mencantumkan nominal di emailnya sama sekali (2026-07-19,
    # ditemukan user) - beda dari booking biasa yang selalu ada field harga. Kalau begitu,
    # total di sini TERPAKSA memakai tarif publik PMS sendiri sebagai PLACEHOLDER supaya kamar
    # tetap ter-booking (nomor kamar/tanggal jauh lebih penting untuk anti-bentrok daripada
    # nominalnya), TAPI ditandai `ota_harga_dikonfirmasi=False` - dikecualikan dari SEMUA
    # laporan pendapatan (reports.py & laporan_analitik.py) sampai staf isi nominal settlement
    # ASLI dari laporan/invoice RedDoorz lewat POST /bookings/{id}/konfirmasi-harga-ota. Ini
    # karena tarif net yang OTA bayar ke hotel biasanya LEBIH RENDAH dari tarif publik (margin
    # OTA) - mencatatnya sebagai pendapatan asli akan OVERSTATE laporan keuangan.
    harga_dari_email = int(data.get("harga") or 0)
    harga_dikonfirmasi = harga_dari_email > 0
    total_semua = harga_dari_email or (dipilih[0]["tarif_menginap"] * jumlah_kamar)  # OTA selalu tipe menginap
    total_per_kamar = round(total_semua / jumlah_kamar)
    dibatalkan = data.get("status_pembayaran") == "Dibatalkan"
    reservation_ids = []
    for r in dipilih:
        booking = await create_reservation(
            {
                "room_id": r["id"],
                "nama_tamu": data.get("nama_tamu", ""), "no_hp": "", "email": "",
                "no_identitas": "", "kendaraan": "",
                "jumlah_tamu": data.get("jumlah_tamu") or 1,
                "jam_mulai": check_in, "jam_selesai": check_out,
                "catatan": f'Reservasi OTA otomatis dari email "{subjek}" ({sumber}, no. {data.get("no_reservasi", "-")})'
                + (f" — {jumlah_kamar} kamar dipesan bersamaan" if jumlah_kamar > 1 else ""),
                "created_by": "ai_email_parser",
                "tipe": "menginap",
            },
            source="ota",
            harga_override={"subtotal": total_per_kamar, "service_fee": 0, "total": total_per_kamar, "dp_min": 0},
        )
        update_fields = {"ota_reservation_no": data.get("no_reservasi")}
        if dibatalkan:
            update_fields["status"] = "cancelled"
        else:
            # Keputusan bisnis user (2026-07-13): tamu RedDoorz sudah bayar ke RedDoorz saat
            # booking, PMS baru terima settlement belakangan — field status_pembayaran di email
            # ("Lunas"/"Belum Bayar") TIDAK merepresentasikan status bayar ke hotel (semua sample
            # email RedDoorz nyatanya selalu "Belum Bayar" walau tamu sudah bayar), jadi booking
            # baru dari RedDoorz selalu langsung dianggap lunas supaya terhitung di laporan
            # pemasukan (yang filter payment_status=paid & paid_at).
            # amount_due wajib diisi = total supaya status_bayar_booking() (dipakai Dashboard/
            # Reservasi/PDF) menyimpulkan "lunas", bukan "dp" — booking OTA tidak pernah lewat
            # payment_option/create-transaction (yang biasanya isi amount_due), jadi kalau
            # dibiarkan kosong dianggap belum ada nominal terkumpul sama sekali. payment_status
            # TETAP "paid" walau harga belum dikonfirmasi (tamu Prepaid SUDAH bayar ke OTA -
            # jangan sampai staf/tamu lihat status "belum bayar" yang salah); yang membedakan
            # nominal asli vs estimasi murni `ota_harga_dikonfirmasi`, bukan payment_status.
            update_fields.update({
                "payment_status": "paid", "status": "aktif", "paid_at": now_iso(),
                "amount_due": total_per_kamar, "ota_harga_dikonfirmasi": harga_dikonfirmasi,
            })
        await db.bookings.update_one({"id": booking["id"]}, {"$set": update_fields})
        reservation_ids.append(booking["id"])

    log_update = {"reservation_id": reservation_ids[0], "reservation_ids": reservation_ids, "aksi": "reservasi_baru_dibuat"}
    if len(dipilih) < jumlah_kamar:
        # Sebagian berhasil dibuat (kamar yang memang kosong), sisanya butuh tinjauan staf —
        # bukan didiamkan seluruhnya supaya staf tidak perlu memesankan ulang yang sudah aman.
        log_update.update({
            "status": "Manual_Required",
            "alasan": f'Email OTA memesan {jumlah_kamar} kamar {mapping["pms_tipe"]}, tapi hanya {len(dipilih)} yang kosong pada {check_in.date()}–{check_out.date()} — {len(dipilih)} reservasi sudah dibuat otomatis, {jumlah_kamar - len(dipilih)} kamar SISANYA perlu ditangani manual staf (cari kamar lain / hubungi tamu).',
        })
    await db.email_logs.update_one({"id": log_id}, {"$set": log_update})


async def batalkan_reservasi_otomatis(log_id: str, data: dict, sumber: str, subjek: str) -> None:
    """Reservation Automation untuk email PEMBATALAN eksplisit (jenis="pembatalan" — sinyal
    tidak ambigu dari OTA). Juga dipanggil dari proses_modifikasi_otomatis kalau tanggal
    check-in/out di email modifikasi ternyata sama persis dengan yang lama (pembatalan
    terselubung, lihat keputusan bisnis user 2026-07-12). SEMUA reservasi PMS yang cocok
    (dicari dari `ota_reservation_no`) langsung DIBATALKAN otomatis — satu no. reservasi OTA
    bisa mencakup lebih dari satu kamar (lihat buat_reservasi_otomatis), jadi semuanya harus
    ikut batal, bukan cuma yang pertama ditemukan. Kalau tidak ada yang ditemukan, log
    Manual_Required.
    """
    no_reservasi = data.get("no_reservasi")
    if not no_reservasi:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": "Email modifikasi/pembatalan tidak menyebutkan nomor reservasi OTA — tidak bisa dicocokkan otomatis, cek manual.",
        }})
        return

    bookings = await db.bookings.find({
        "ota_reservation_no": no_reservasi,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
    }, {"_id": 0}).to_list(50)
    if not bookings:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": f'Tidak ditemukan reservasi PMS aktif dengan no. OTA "{no_reservasi}" untuk dibatalkan — kemungkinan sudah dibatalkan/selesai sebelumnya, atau reservasi awalnya belum pernah berhasil dibuat otomatis. Cek manual.',
        }})
        return

    now = now_iso()
    for booking in bookings:
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
    await db.email_logs.update_one({"id": log_id}, {"$set": {
        "status": "Parsed_Success", "alasan": None,
        "reservation_id": bookings[0]["id"], "reservation_ids": [b["id"] for b in bookings],
        "aksi": "reservasi_dibatalkan",
    }})


async def _modifikasi_menunggu_review(bookings: list, log_id: str, no_reservasi: str, kenapa: str) -> None:
    """Fallback: tandai SEMUA booking dalam grup (satu no. reservasi OTA bisa mencakup lebih
    dari satu kamar) modifikasi_status="menunggu_review" supaya staf yang baca isi email asli
    lalu putuskan lewat endpoint reschedule/batalkan per kamar (dipakai proses_modifikasi_otomatis
    kalau data emailnya tidak cukup jelas untuk auto-tentukan, atau jadwal baru bentrok kamar lain).
    """
    kodes = ", ".join(b["kode"] for b in bookings)
    for b in bookings:
        await db.bookings.update_one(
            {"id": b["id"]},
            {"$set": {"modifikasi_status": "menunggu_review"}, "$push": {"modifikasi_log_ids": log_id}},
        )
    await db.email_logs.update_one({"id": log_id}, {"$set": {
        "status": "Perlu_Review_Modifikasi",
        "reservation_id": bookings[0]["id"], "reservation_ids": [b["id"] for b in bookings],
        "aksi": "menunggu_review_modifikasi",
        "alasan": f'Email modifikasi untuk reservasi OTA {no_reservasi} ({kodes}) — perlu ditinjau staf: reschedule atau batalkan? {kenapa} Cek isi email RedDoorz asli untuk detail perubahan tanggal.',
    }})


async def proses_modifikasi_otomatis(log_id: str, data: dict, sumber: str, subjek: str) -> None:
    """Reservation Automation untuk email MODIFIKASI (keputusan bisnis user 2026-07-12, revisi
    kedua sama hari): AI Email Parser sekarang juga mencoba ekstrak tanggal check-in/check-out
    BARU dari isi email modifikasi (kalau disebutkan eksplisit — lihat PARSE_SYSTEM_PROMPT).
    Aturan penentuan otomatis (keputusan bisnis user):
    - Tanggal check-in ATAU check-out baru SAMA PERSIS dengan yang tersimpan di PMS untuk
      KEDUANYA -> dianggap pembatalan terselubung, diproses lewat batalkan_reservasi_otomatis
      (sama seperti jenis="pembatalan").
    - Salah satu dari keduanya berbeda dari yang tersimpan -> dianggap RESCHEDULE, jadwal
      booking diupdate otomatis ke tanggal baru (tetap dicek anti-overbooking dulu).
    - AI tidak berhasil menemukan check-in/check-out baru yang jelas, atau jadwal baru bentrok
      dengan reservasi lain -> TIDAK menebak, fallback ke tab "Modifikasi OTA" untuk staf.

    Kalau reservasi sedang menunggu_review (staf belum memutuskan), email modifikasi susulan
    dengan no. reservasi yang sama TIDAK menambah apa pun lagi — cuma dicatat sebagai riwayat
    (status Sudah_Diproses) supaya tidak menumpuk item review ganda untuk reservasi yang sama.

    PENTING (bug 2026-07-13): kalau reservasi sudah pernah direschedule sebelumnya, email
    modifikasi SUSULAN tetap diproses (bukan didiamkan sebagai duplikat) — dibandingkan
    terhadap jadwal booking yang SEKARANG (hasil reschedule terakhir), bukan jadwal asli.
    Kasus nyata yang ketahuan: reschedule pertama pindah ke tanggal X, lalu OTA kirim email
    modifikasi KEDUA yang tanggalnya sama persis dengan X (yang sudah tersimpan) — seharusnya
    ini pembatalan terselubung (aturan "tanggal sama = batal" berlaku juga di reschedule
    kedua/ketiga dst, bukan cuma dibanding ke tanggal asli booking), tapi sebelumnya dedup guard
    ini keburu menghentikan proses sehingga bookingnya tetap aktif/dianggap masih menginap.
    """
    no_reservasi = data.get("no_reservasi")
    if not no_reservasi:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": "Email modifikasi tidak menyebutkan nomor reservasi OTA — tidak bisa dicocokkan otomatis, cek manual.",
        }})
        return

    # Satu no. reservasi OTA bisa mencakup lebih dari satu kamar (lihat buat_reservasi_otomatis)
    # — modifikasi/reschedule/pembatalan harus berlaku untuk SEMUA kamar dalam grup ini sekaligus,
    # bukan cuma yang pertama ditemukan.
    bookings = await db.bookings.find({
        "ota_reservation_no": no_reservasi,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
    }, {"_id": 0}).to_list(50)
    if not bookings:
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Manual_Required",
            "alasan": f'Tidak ditemukan reservasi PMS aktif dengan no. OTA "{no_reservasi}" — kemungkinan sudah dibatalkan/selesai sebelumnya, atau reservasi awalnya belum pernah berhasil dibuat otomatis. Cek manual.',
        }})
        return

    if any(b.get("modifikasi_status") == "menunggu_review" for b in bookings):
        for b in bookings:
            await db.bookings.update_one({"id": b["id"]}, {"$push": {"modifikasi_log_ids": log_id}})
        kodes = ", ".join(b["kode"] for b in bookings)
        await db.email_logs.update_one({"id": log_id}, {"$set": {
            "status": "Sudah_Diproses",
            "reservation_id": bookings[0]["id"], "reservation_ids": [b["id"] for b in bookings],
            "aksi": "modifikasi_duplikat",
            "alasan": f'Reservasi OTA {no_reservasi} ({kodes}) sedang menunggu tinjauan staf dari modifikasi sebelumnya — email ini dicatat sebagai riwayat tambahan, staf tetap perlu memutuskan manual.',
        }})
        return
    # Selain itu (semua "direschedule" atau baru pertama kali None) -> lanjut diproses di bawah,
    # dibandingkan terhadap jadwal booking yang sekarang tersimpan.

    check_in_raw, check_out_raw = data.get("check_in"), data.get("check_out")
    try:
        if not check_in_raw or not check_out_raw:
            raise ValueError("tanggal check-in/check-out baru tidak disebutkan di email")
        new_start = parse_iso(check_in_raw, "check_in")
        new_end = parse_iso(check_out_raw, "check_out")
    except (ValueError, HTTPException):
        await _modifikasi_menunggu_review(
            bookings, log_id, no_reservasi,
            "AI tidak berhasil menemukan tanggal check-in/check-out baru yang jelas di email ini.",
        )
        return

    # Semua kamar dalam grup ini berasal dari satu reservasi/tanggal OTA yang sama, jadi jadwal
    # lama dibandingkan dari booking manapun (pakai yang pertama) — cukup satu perbandingan.
    old_start = parse_iso(bookings[0]["jam_mulai"], "jam_mulai")
    old_end = parse_iso(bookings[0]["jam_selesai"], "jam_selesai")

    if new_start.date() == old_start.date() and new_end.date() == old_end.date():
        # Check-in & check-out baru sama persis dengan yang lama -> dianggap pembatalan
        # terselubung (keputusan bisnis user), diproses sama seperti jenis="pembatalan"
        # (batalkan_reservasi_otomatis sudah menangani seluruh grup kamar).
        await batalkan_reservasi_otomatis(log_id, {**data, "jenis": "modifikasi (tanggal tidak berubah)"}, sumber, subjek)
        return

    # Check-in atau check-out berbeda -> reschedule otomatis. Dicek dulu SEMUA kamar dalam grup
    # bisa dipindah sebelum ada satupun yang benar-benar diubah — kalau salah satu kamar bentrok,
    # SELURUH grup dilempar ke tinjauan staf (bukan reschedule sebagian), supaya staf melihat
    # keputusan yang konsisten untuk satu reservasi tamu, bukan campur aduk sebagian pindah
    # sebagian belum.
    # Celah check-lalu-tulis dibungkus lock (2026-07-19, audit anti-race-condition) - lihat
    # catatan di reservation_service.py.
    async with room_locks(*[b["room_id"] for b in bookings]):
        konflik = None
        for b in bookings:
            try:
                await check_room_available(b["room_id"], new_start, new_end, exclude_booking_id=b["id"])
            except HTTPException:
                konflik = b
                break
        if konflik:
            await _modifikasi_menunggu_review(
                bookings, log_id, no_reservasi,
                f"Jadwal baru ({new_start.date()}–{new_end.date()}) bentrok dengan reservasi lain di kamar {konflik.get('room_nomor', konflik['id'])} — tidak bisa direschedule otomatis untuk grup {len(bookings)} kamar ini.",
            )
            return

        now = now_iso()
        for b in bookings:
            await db.bookings.update_one({"id": b["id"]}, {"$set": {
                "jam_mulai": new_start.isoformat(), "jam_selesai": new_end.isoformat(),
                "modifikasi_status": "direschedule", "modifikasi_reviewed_at": now, "modifikasi_reviewed_by": "ai_email_parser",
                "updated_at": now, "updated_by": "ai_email_parser",
            }, "$push": {"modifikasi_log_ids": log_id}})
            await db.audit_log.insert_one({
                "id": str(uuid.uuid4()), "user_id": None, "username": "ai_email_parser",
                "action": "reschedule_ota_auto",
                "detail": f'Reschedule otomatis {b["kode"]} (no. OTA {no_reservasi}) ke {new_start.isoformat()} – {new_end.isoformat()} dari email modifikasi "{subjek}"',
                "entity": b.get("room_nomor", ""), "timestamp": now,
            })
    await db.email_logs.update_one({"id": log_id}, {"$set": {
        "status": "Parsed_Success", "alasan": None,
        "reservation_id": bookings[0]["id"], "reservation_ids": [b["id"] for b in bookings],
        "aksi": "reservasi_direschedule",
    }})


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
                # Reservation Automation (PRD + keputusan bisnis 2026-07-12, direvisi kedua
                # kalinya sama hari): reservasi baru langsung dibuat; pembatalan eksplisit
                # langsung membatalkan reservasi lama yang cocok; modifikasi dibandingkan
                # tanggal check-in/out baru vs lama untuk auto-tentukan reschedule vs
                # pembatalan terselubung (lihat proses_modifikasi_otomatis), fallback ke tab
                # review staf kalau datanya tidak cukup jelas. Bisa mengubah status doc ini
                # balik ke Manual_Required kalau tidak bisa dicocokkan otomatis sama sekali
                # (lihat masing-masing fungsi).
                if jenis == "baru":
                    await buat_reservasi_otomatis(doc["id"], extracted_data, sumber, subjek)
                elif jenis == "pembatalan":
                    await batalkan_reservasi_otomatis(doc["id"], {**extracted_data, "jenis": jenis}, sumber, subjek)
                else:  # modifikasi
                    await proses_modifikasi_otomatis(doc["id"], extracted_data, sumber, subjek)
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


@api.get("/otomasi-email/modifikasi/perlu-review")
async def list_modifikasi_perlu_review(user: dict = Depends(get_current_user)):
    """Reservasi OTA yang punya email modifikasi menunggu keputusan staf — fallback dari
    proses_modifikasi_otomatis kalau AI tidak berhasil menentukan reschedule/batal otomatis.
    Disertakan riwayat email modifikasi terkait (bisa lebih dari satu kalau OTA kirim beberapa
    notifikasi susulan)."""
    bookings = await db.bookings.find({"modifikasi_status": "menunggu_review"}, {"_id": 0}).sort("jam_mulai", 1).to_list(100)
    out = []
    for b in bookings:
        logs = await db.email_logs.find(
            {"id": {"$in": b.get("modifikasi_log_ids", [])}}, {"_id": 0}
        ).sort("processed_at", -1).to_list(20)
        out.append({**b, "modifikasi_emails": logs})
    return out


@api.post("/otomasi-email/modifikasi/{booking_id}/batalkan")
async def modifikasi_batalkan(booking_id: str, user: dict = Depends(get_current_user)):
    """Staf konfirmasi: email modifikasi OTA yang ditinjau ternyata pembatalan — batalkan
    reservasi PMS terkait (sama seperti batalkan_reservasi_otomatis, tapi dipicu staf)."""
    b = await db.bookings.find_one({"id": booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("modifikasi_status") != "menunggu_review":
        raise HTTPException(400, "Booking ini tidak sedang menunggu review modifikasi")

    now = now_iso()
    await db.bookings.update_one({"id": booking_id}, {"$set": {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": user["nama"],
        "cancel_reason": "Dibatalkan staf setelah tinjau email modifikasi OTA (RedDoorz)",
        "cancel_fee": 0, "refund_amount": 0,
        "modifikasi_status": "dibatalkan", "modifikasi_reviewed_at": now, "modifikasi_reviewed_by": user["nama"],
    }})
    await log_availability_change(b["room_id"], b.get("room_tipe", ""), 1, "booking_dibatalkan_modifikasi_ota", booking_id=b["id"])
    await db.email_logs.update_many(
        {"id": {"$in": b.get("modifikasi_log_ids", [])}},
        {"$set": {"status": "Parsed_Success", "aksi": "reservasi_dibatalkan", "alasan": None}},
    )
    await log_activity(user, "modifikasi_batalkan_ota", f"Batalkan {b['kode']} setelah tinjau modifikasi OTA (RedDoorz)", entity=b.get("room_nomor", ""))
    return {"ok": True}


@api.post("/otomasi-email/modifikasi/{booking_id}/reschedule")
async def modifikasi_reschedule(booking_id: str, body: ReschedulePMSBody, user: dict = Depends(get_current_user)):
    """Staf konfirmasi: email modifikasi OTA yang ditinjau ternyata ganti tanggal — pindahkan
    jadwal reservasi PMS ke jadwal baru (staf baca tanggal baru dari isi email RedDoorz asli).
    Harga TIDAK dihitung ulang, konsisten dengan konvensi reschedule staf yang sudah ada
    (`PUT /bookings/{id}`) — anti-overbooking tetap dicek untuk jadwal baru."""
    b = await db.bookings.find_one({"id": booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("modifikasi_status") != "menunggu_review":
        raise HTTPException(400, "Booking ini tidak sedang menunggu review modifikasi")

    start = parse_iso(body.jam_mulai, "jam_mulai")
    end = parse_iso(body.jam_selesai, "jam_selesai")
    if end <= start:
        raise HTTPException(400, "Jam selesai harus setelah jam mulai")

    now = now_iso()
    # Celah check-lalu-tulis dibungkus lock (2026-07-19, audit anti-race-condition) - lihat
    # catatan di reservation_service.py.
    async with room_locks(b["room_id"]):
        await check_room_available(b["room_id"], start, end, exclude_booking_id=booking_id)
        await db.bookings.update_one({"id": booking_id}, {"$set": {
            "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
            "modifikasi_status": "direschedule", "modifikasi_reviewed_at": now, "modifikasi_reviewed_by": user["nama"],
            "updated_at": now, "updated_by": user["nama"],
        }})
    await db.email_logs.update_many(
        {"id": {"$in": b.get("modifikasi_log_ids", [])}},
        {"$set": {"status": "Parsed_Success", "aksi": "reservasi_direschedule", "alasan": None}},
    )
    await log_activity(
        user, "modifikasi_reschedule_ota",
        f"Reschedule {b['kode']} ke {start.isoformat()} - {end.isoformat()} setelah tinjau modifikasi OTA (RedDoorz)",
        entity=b.get("room_nomor", ""),
    )
    doc = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    return doc
