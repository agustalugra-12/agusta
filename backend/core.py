"""Core module — shared dependencies for the Pelangi Homestay API.

Contains: env config, Mongo client, shared APIRouter instance, JWT helpers,
Pydantic models, and cross-cutting utilities (audit log, calc_tagihan, etc).

All route modules should do:  from core import *
"""
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import re
import uuid
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import jwt
import bcrypt
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query, UploadFile, File
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

# ---- Mongo Setup ----
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_ALGO = "HS256"
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")

# ---- Shared APIRouter — every route module registers on this instance ----
api = APIRouter(prefix="/api")

# ---- Tripay setup (menggantikan Midtrans, 2026-07-13 — lihat routes/tripay.py) ----
# Kosong sampai kredensial (sandbox/production) diberikan lewat env var pms-backend.service;
# endpoint callback tetap bisa didaftarkan di Tripay walau TRIPAY_PRIVATE_KEY belum diisi.
TRIPAY_MERCHANT_CODE = os.environ.get("TRIPAY_MERCHANT_CODE", "")
TRIPAY_API_KEY = os.environ.get("TRIPAY_API_KEY", "")
TRIPAY_PRIVATE_KEY = os.environ.get("TRIPAY_PRIVATE_KEY", "")
TRIPAY_IS_PRODUCTION = os.environ.get("TRIPAY_IS_PRODUCTION", "false").lower() == "true"
TRIPAY_BASE_URL = "https://tripay.co.id/api" if TRIPAY_IS_PRODUCTION else "https://tripay.co.id/api-sandbox"

# ---- Google OAuth (Otomasi Email — koneksi Gmail) ----
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")

# ---- OpenAI (Otomasi Email — AI Email Parser) ----
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ---- Brevo (Pengiriman Voucher Otomatis — email transaksional) ----
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "")
BREVO_FROM_NAME = os.environ.get("BREVO_FROM_NAME", "Pelangi Homestay")

# ---- Telegram Bot (owner: laporan ringkas, staff: kirim pengeluaran foto+teks) ----
TELEGRAM_OWNER_BOT_TOKEN = os.environ.get("TELEGRAM_OWNER_BOT_TOKEN", "")
TELEGRAM_STAFF_BOT_TOKEN = os.environ.get("TELEGRAM_STAFF_BOT_TOKEN", "")
TELEGRAM_OWNER_WEBHOOK_SECRET = os.environ.get("TELEGRAM_OWNER_WEBHOOK_SECRET", "")
TELEGRAM_STAFF_WEBHOOK_SECRET = os.environ.get("TELEGRAM_STAFF_WEBHOOK_SECRET", "")

# ---- Web Push (notifikasi PWA — booking baru, pembayaran diterima, komplain, housekeeping) ----
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", "mailto:booking@pelangihomestay.com")

# ---- Constants ----
SERVICE_FEE_PCT = 0.03  # 3% service fee diaplikasikan ke checkin & booking
EXTRA_BED_PRICE = 50000  # per extra bed, flat (PRD: "Extra Bed Rp 50.000 berlaku untuk kedua jenis layanan")
EXTRA_BED_MAX = 2  # maksimal per kamar (sama seperti ExtraBedSelector di frontend)
BREAKFAST_PRICE = 25000  # per malam, opsional, hanya berlaku untuk tipe menginap
# `rooms.tarif` = harga Day Use (flat per sesi 6 jam) — Standard 120rb/Cottage 140rb.
# `rooms.tarif_menginap` = harga Menginap per malam TANPA sarapan — Standard 150rb/Cottage 200rb,
# +BREAKFAST_PRICE kalau dengan_sarapan (jadi 175rb/225rb). Dua tarif dasar terpisah sejak 2026-07-12
# (sebelumnya sempat memakai satu field `tarif` untuk keduanya — salah, dikoreksi atas instruksi user).

# ---- Rate limiting (2026-07-21, audit keamanan — login staf/owner & endpoint publik
# booking sebelumnya tidak ada penghalang percobaan berulang sama sekali) ----
# In-memory sliding window per-proses - cukup untuk skala 1 homestay (1 proses backend,
# bukan multi-worker), pola sama persis dengan yang sudah dipakai di ai-chat-bot.
import time as _time
_rate_limit_buckets: Dict[str, List[float]] = {}

def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def rate_limiter(max_requests: int, window_seconds: int):
    async def _check(request: Request) -> None:
        key = f"{request.url.path}:{_client_ip(request)}"
        now = _time.time()
        cutoff = now - window_seconds
        bucket = [t for t in _rate_limit_buckets.get(key, []) if t >= cutoff]
        if len(bucket) >= max_requests:
            _rate_limit_buckets[key] = bucket
            raise HTTPException(429, "Terlalu banyak permintaan, coba lagi sebentar lagi")
        bucket.append(now)
        _rate_limit_buckets[key] = bucket
        if len(_rate_limit_buckets) > 20000:
            _rate_limit_buckets.clear()
    return _check


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False

def create_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id, "username": username, "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = None
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(401, "Tidak terautentikasi")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Sesi habis, silakan login lagi")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token tidak valid")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "User tidak ditemukan")
    return user

async def require_owner(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "owner":
        raise HTTPException(403, "Hanya Owner yang dapat melakukan aksi ini")
    return user

async def log_activity(user: dict, action: str, detail: str = "", entity: str = ""):
    """AuditLogger — dipanggil di semua route yang mengubah data (stok kamar, reservasi,
    pengguna, dst). Tiap panggilan menulis satu dokumen `AuditLog` ke collection `audit_log`.
    """
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.get("id"),
        "username": user.get("username"),
        "action": action,
        "entity": entity,
        "detail": detail,
        "timestamp": now_iso(),
    })

async def log_availability_change(room_id: str, room_tipe: str, stock_change: int, reason: str, booking_id: Optional[str] = None):
    """Catat pergerakan ketersediaan kamar (Dasbor Ketersediaan — riwayat stok & okupansi).
    stock_change: +1 saat kamar dilepas kembali jadi tersedia, -1 saat kamar terisi/dibooking.
    """
    await db.availability_logs.insert_one({
        "id": str(uuid.uuid4()),
        "room_id": room_id,
        "room_tipe": room_tipe,
        "stock_change": stock_change,
        "reason": reason,
        "booking_id": booking_id,
        "changed_at": now_iso(),
    })
    await push_sync_event("ketersediaan", f"Stok {room_tipe} berubah ({stock_change:+d}): {reason}")

async def cari_guest(no_hp: str = "", no_identitas: str = "") -> Optional[Dict[str, Any]]:
    """Resolusi identitas tamu di `db.guests` - dicari lewat no_identitas dulu (lebih pasti
    unik per orang), fallback no_hp. Satu fungsi dipakai upsert_guest (tulis) DAN
    hitung_diskon_member (baca) supaya tidak ada logika pencarian ganda yang bisa
    menyimpang."""
    if no_identitas:
        guest = await db.guests.find_one({"no_identitas": no_identitas})
        if guest:
            return guest
    if no_hp:
        return await db.guests.find_one({"no_hp": no_hp})
    return None


# ---- Program Loyalitas Kedatangan (diskon member) ----
# Dikonfirmasi user 2026-07-19: persentase diskon subtotal kamar berdasarkan urutan
# kedatangan tamu (kedatangan ke-1 = pertama kali datang). Siklus 10 kedatangan, lalu
# reset otomatis (kedatangan ke-11 dihitung sebagai posisi 1 lagi, dst) - modulo, TIDAK
# perlu field reset terpisah & TIDAK mereset total_kunjungan (tetap angka kunjungan
# seumur hidup apa adanya, cuma dipakai sebagai basis hitung posisi siklus).
DISKON_MEMBER_TABLE = {1: 0, 2: 10, 3: 0, 4: 10, 5: 30, 6: 0, 7: 10, 8: 0, 9: 10, 10: 100}


def diskon_member_untuk_total_kunjungan(total_kunjungan: int) -> Dict[str, int]:
    """Bagian murni (tanpa akses DB) dari hitung_diskon_member - dipakai juga di
    GET /guests (halaman Data Tamu) supaya badge diskon per tamu tidak perlu query
    tambahan per baris, cukup dari total_kunjungan yang sudah ada di tangan."""
    kedatangan_ke = (total_kunjungan or 0) + 1
    posisi = ((kedatangan_ke - 1) % 10) + 1
    return {"kedatangan_ke": kedatangan_ke, "diskon_persen": DISKON_MEMBER_TABLE[posisi]}


async def hitung_diskon_member(no_hp: str = "", no_identitas: str = "") -> Dict[str, int]:
    """`kedatangan_ke` = total_kunjungan tercatat SAAT INI + 1 (kedatangan yang sedang
    dibuat booking-nya sekarang, karena total_kunjungan cuma naik saat check-in sungguhan
    terjadi - lihat upsert_guest). Tamu baru (belum pernah tercatat) = kedatangan ke-1."""
    guest = await cari_guest(no_hp, no_identitas)
    return diskon_member_untuk_total_kunjungan((guest or {}).get("total_kunjungan", 0))


def terapkan_diskon_member(subtotal: int, diskon_persen: int) -> Dict[str, int]:
    """Diskon HANYA memotong subtotal kamar - service_fee tetap dihitung/dibayar penuh dari
    subtotal SEBELUM diskon (keputusan user 2026-07-19), dipanggil dengan subtotal asli
    (sebelum dipotong) supaya service_fee di caller tidak perlu dihitung ulang."""
    diskon_rp = round(subtotal * diskon_persen / 100) if diskon_persen else 0
    return {"subtotal": subtotal - diskon_rp, "diskon_rp": diskon_rp}


async def upsert_guest(nama: str, no_hp: str = "", no_identitas: str = "", kendaraan: str = "",
                        count_kunjungan: bool = True) -> str:
    """Catat/perbarui 1 data tamu di `db.guests` — dipanggil dari SEMUA jalur yang menghasilkan
    booking (create/update booking staf, booking publik, booking OTA) maupun check-in sungguhan
    (`/checkins`, `/bookings/{id}/checkin`), supaya tab "Data Tamu" di Reservasi mencerminkan
    semua orang yang pernah booking, bukan cuma yang sempat check-in. Dicari dulu berdasarkan
    no_identitas, lalu no_hp; kalau tidak ketemu keduanya, buat data tamu baru.

    `count_kunjungan` membedakan "booking dibuat/diubah" dari "tamu benar-benar datang":
    cuma jalur check-in sungguhan yang menaikkan `total_kunjungan` (default True, dipanggil
    dengan False dari create/update booking supaya angka kunjungan tetap berarti "berapa kali
    benar-benar menginap/check-in", bukan ikut naik tiap booking dibuat/diedit/dibatalkan).

    `nama_varian` (2026-07-21, permintaan user): tamu kadang mengetik nama beda-beda tiap
    booking (typo, panggilan, dst) walau nomor HP sama - pencocokan member (cari_guest/
    hitung_diskon_member) SUDAH BENAR jalan dari no_hp/no_identitas, TIDAK terpengaruh nama
    sama sekali. Sebelumnya field `nama` cuma ditimpa nama terbaru tiap kali (riwayat nama
    lama hilang, staf bisa bingung lihat nama "flip-flop"). Sekarang setiap nama yang pernah
    dipakai dihitung frekuensinya di `nama_varian` ({nama: jumlah_pemakaian}), field `nama`
    tampil = varian yang PALING SERING dipakai (bukan cuma yang terakhir) - staf tetap bisa
    lihat semua variasi nama yang pernah dipakai tamu ini di `nama_varian`."""
    nama = (nama or "").strip()
    guest = await cari_guest(no_hp, no_identitas)
    if guest:
        varian = dict(guest.get("nama_varian") or {})
        if not varian and guest.get("nama"):
            varian[guest["nama"]] = 1  # migrasi data lama yang belum punya nama_varian
        if nama:
            varian[nama] = varian.get(nama, 0) + 1
        nama_utama = max(varian, key=varian.get) if varian else nama
        update: Dict[str, Any] = {"$set": {
            "nama": nama_utama,
            "nama_varian": varian,
            "no_hp": no_hp or guest.get("no_hp", ""),
            "kendaraan": kendaraan or guest.get("kendaraan", ""),
            "last_visit": now_iso(),
        }}
        if count_kunjungan:
            update["$inc"] = {"total_kunjungan": 1}
        await db.guests.update_one({"id": guest["id"]}, update)
        return guest["id"]
    guest_id = str(uuid.uuid4())
    await db.guests.insert_one({
        "id": guest_id,
        "nama": nama,
        "nama_varian": {nama: 1} if nama else {},
        "no_hp": no_hp,
        "no_identitas": no_identitas,
        "kendaraan": kendaraan,
        "total_kunjungan": 1 if count_kunjungan else 0,
        "last_visit": now_iso(),
        "created_at": now_iso(),
    })
    return guest_id


async def push_sync_event(data_type: str, detail: str) -> None:
    """Dorong notifikasi perubahan data Pelangi PMS ke bot WhatsApp (Sinkronisasi Data
    PMS) — best-effort, tidak boleh menggagalkan aksi utama (booking/checkin/dst) kalau
    provider bot sedang bermasalah. Satu kali retry otomatis; kegagalan dicatat ke
    `wa_connection_log` supaya bisa dipantau di Pemantauan Status / Sinkronisasi Data PMS.
    """
    cfg = await db.webhook_config.find_one({})
    if not cfg or not cfg.get("aktif") or not cfg.get("webhook_url") or not cfg.get("api_key"):
        return
    import httpx
    payload = {"event": "pms_data_sync", "data_type": data_type, "detail": detail, "waktu": now_iso()}
    for attempt in range(2):  # 1x percobaan awal + 1x retry
        try:
            async with httpx.AsyncClient(timeout=8) as http:
                resp = await http.post(cfg["webhook_url"], headers={"Authorization": f"Bearer {cfg['api_key']}"}, json=payload)
            if resp.status_code < 400:
                await db.sync_data_pms_log.insert_one({
                    "id": str(uuid.uuid4()), "data_type": data_type, "detail": detail,
                    "ok": True, "waktu": now_iso(),
                })
                return
        except Exception:
            pass
    await db.sync_data_pms_log.insert_one({
        "id": str(uuid.uuid4()), "data_type": data_type,
        "detail": f"Gagal mendorong sinkron setelah 2 percobaan: {detail}",
        "ok": False, "waktu": now_iso(),
    })

def calc_tagihan(tarif_dasar: int, jam_checkin: datetime, jam_checkout: datetime, overtime_manual: Optional[int] = None):
    """Hitung tagihan check-out: 6 jam pertama = tarif dasar, sisanya Rp 20.000/jam (ceiling)."""
    delta = jam_checkout - jam_checkin
    hours = delta.total_seconds() / 3600
    durasi = max(0.0, hours)
    over = 0
    if durasi > 6:
        over = int(-(-(durasi - 6) // 1))  # ceil
    if overtime_manual is not None:
        over = max(0, int(overtime_manual))
    biaya_over = over * 20000
    subtotal = int(tarif_dasar) + biaya_over
    service_fee = round(subtotal * SERVICE_FEE_PCT)
    total = subtotal + service_fee
    return {
        "durasi_jam": round(durasi, 2), "overtime_jam": over,
        "biaya_tambahan": biaya_over, "subtotal": subtotal,
        "service_fee": service_fee, "service_fee_pct": SERVICE_FEE_PCT,
        "total": total,
    }

_ORDER_ID_SUFFIX_RE = re.compile(r"^(.+)-(\d{6}[0-9A-F]{3})$")

def guess_booking_kode_from_order_id(order_id: str) -> Optional[str]:
    """Tebak kode booking dari order_id/merchant_ref Midtrans & Tripay, keduanya dibentuk
    `f"{kode}-{HHMMSS}{uuid4hex[:3].upper()}"` (create-snap-token/create-transaction) — dipakai
    webhook sebagai fallback kalau payment_log yang seharusnya dibuat saat create-transaction
    ternyata tidak ada (mis. proses sempat gagal di antara panggilan ke gateway dan insert log),
    supaya booking tetap ter-update & voucher tetap terkirim alih-alih diam-diam jadi entri yatim."""
    m = _ORDER_ID_SUFFIX_RE.match(order_id or "")
    return m.group(1) if m else None

def status_bayar_booking(b: dict) -> dict:
    """Derive status bayar 3-keadaan (belum_bayar/dp/lunas) + sisa tagihan dari booking.
    `payment_status` di skema booking cuma 2 keadaan gateway-level (pending/paid/dst) —
    itu TIDAK cukup untuk bedakan tamu yang baru bayar DP vs bayar lunas, karena webhook
    Midtrans/Tripay sama-sama set payment_status="paid" begitu ada settlement, apapun
    payment_option-nya. Dipakai bersama oleh halaman staf (Pembayaran) dan permukaan tamu
    (voucher PDF, email, /public/bookings/{id}) supaya konsisten."""
    total = int(b.get("total") or 0)
    terkumpul = int(b.get("amount_due") or 0) if b.get("payment_status") == "paid" else 0
    if b.get("payment_status") != "paid":
        status_bayar = "belum_bayar"
    else:
        status_bayar = "lunas" if total > 0 and terkumpul >= total else "dp"
    return {"status_bayar": status_bayar, "jumlah_dibayar": terkumpul, "sisa_tagihan": max(0, total - terkumpul)}

DISKON_AI_MAX_PERSEN = 10

def hitung_diskon_ai_diskresi(malam: int, jumlah_kamar: int) -> int:
    """Diskon diskresi yang AI boleh berikan KALAU DAN HANYA KALAU tamu sendiri yang minta
    diskon (kebijakan bisnis user 2026-07-21, tujuan: jaga margin, AI tidak boleh menawarkan
    duluan). Dihitung SERVER-SIDE dari data booking sungguhan (bukan dipercaya dari angka
    yang AI kirim) - AI cuma mengirim sinyal "tamu minta diskon" (lihat
    diskon_diminta_tamu di buat_booking_request), server yang menentukan persentase
    persisnya supaya tidak ada risiko AI salah hitung/menjanjikan angka yang tidak sesuai
    kebijakan.

    Berdasarkan lama menginap ATAU jumlah kamar (ambil yang TERBESAR, TIDAK dijumlah):
    - 2 malam: 5% | 3-4 malam: 8% | >=5 malam: 10%
    - 2-3 kamar: 5% | 4-5 kamar: 8% | >=6 kamar: 10%
    Maksimum 10% (DISKON_AI_MAX_PERSEN) - tidak pernah lebih tanpa persetujuan admin."""
    diskon_malam = 10 if malam >= 5 else 8 if malam >= 3 else 5 if malam >= 2 else 0
    diskon_kamar = 10 if jumlah_kamar >= 6 else 8 if jumlah_kamar >= 4 else 5 if jumlah_kamar >= 2 else 0
    return min(DISKON_AI_MAX_PERSEN, max(diskon_malam, diskon_kamar))


def parse_iso(s: str, field: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        raise HTTPException(400, f"Format {field} tidak valid (harus ISO 8601)")

def phone_variants(no_hp: str) -> set:
    """Varian format nomor HP Indonesia (62xxx vs 0xxx) yang dianggap SAMA orang - dipakai
    verifikasi kepemilikan booking (bukan cuma tahu ID/UUID booking-nya) di endpoint
    self-service tamu (public.py: batalkan, retry-bayar) & permintaan pembatalan AI
    WhatsApp (pembatalan.py). Pindah ke sini 2026-07-21 (audit keamanan) supaya bisa
    dipakai bersama - sebelumnya cuma ada di pembatalan.py, endpoint self-service tamu di
    public.py sama sekali tidak verifikasi siapa yang minta (IDOR: siapapun yang tahu/
    dapat UUID booking bisa langsung batalkan booking orang lain)."""
    digits = re.sub(r"\D", "", no_hp or "")
    variasi = {digits}
    if digits.startswith("62"):
        variasi.add("0" + digits[2:])
    elif digits.startswith("0"):
        variasi.add("62" + digits[1:])
    return variasi


def verifikasi_pemilik_booking(booking_no_hp: str, no_hp_konfirmasi: str) -> None:
    """Raise 403 kalau no_hp_konfirmasi tidak cocok dengan pemilik booking. Dipanggil di
    setiap endpoint self-service tamu yang mengubah data (batalkan, retry-bayar) sebelum
    eksekusi apapun."""
    digits = re.sub(r"\D", "", no_hp_konfirmasi or "")
    if not digits or digits not in phone_variants(booking_no_hp):
        raise HTTPException(403, "Nomor WhatsApp tidak cocok dengan pemilik booking ini")


def hitung_kebijakan_pembatalan(jam_mulai_iso: str) -> dict:
    """Kebijakan pembatalan TUNGGAL untuk SEMUA channel (2026-07-19, keputusan user
    "samakan semua channel"): sebelumnya self-service website (public.py, beda per
    tipe day_use/menginap 24/72 jam, biaya 10%) dan AI WhatsApp (pembatalan.py, H-7/H-3,
    biaya 50%) punya 2 aturan berbeda, plus 2 artikel Knowledge Base ai-chat-bot yang beda
    lagi dari keduanya - membingungkan tamu kalau ketemu angka beda-beda tergantung jalur.

    Aturan final (SAMA untuk day_use & menginap, tidak dibedakan per tipe lagi):
    - H-7 s/d H-3 sebelum check-in (masih >= 72 jam): refund 100% (biaya_persen 0).
    - H-2 s/d hari check-in (< 72 jam): biaya 50%.

    Dipakai bersama oleh routes/public.py (pembatalan mandiri tamu) & routes/pembatalan.py
    (permintaan pembatalan via AI WhatsApp, staf yang approve) - SATU-SATUNYA sumber
    kebenaran, jangan hitung ulang terpisah di kedua tempat itu lagi."""
    jam_checkin = parse_iso(jam_mulai_iso, "jam_mulai")
    jam_tersisa = (jam_checkin - datetime.now(timezone.utc)).total_seconds() / 3600
    if jam_tersisa >= 72:
        return {"label": "H-7 s/d H-3 (masih ≥ 72 jam sebelum check-in): refund 100%", "biaya_persen": 0, "gratis": True}
    return {"label": "H-2 s/d Hari-H (<72 jam sebelum check-in): biaya 50%", "biaya_persen": 50, "gratis": False}

# ---- Models ----
class LoginIn(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    nama: str
    username: str
    password: str
    role: str  # owner | resepsionis

class RegisterIn(BaseModel):
    """Pendaftaran akun mandiri (halaman Daftar Akun, Fase 3) — beda dari UserCreate
    (dibuat Owner lewat halaman Pengguna, berbasis username). Akun hasil daftar mandiri
    diidentifikasi lewat email, role default 'resepsionis', status 'pending' sampai
    diaktifkan Owner lewat halaman Pengguna."""
    nama: str
    email: str
    password: str

class UserUpdate(BaseModel):
    nama: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None  # aktif | nonaktif

class MeUpdate(BaseModel):
    """Update profil sendiri (halaman Profil) — beda dari UserUpdate (admin-only):
    tidak boleh ganti role/status diri sendiri, wajib password lama untuk ganti password baru."""
    nama: Optional[str] = None
    password_lama: Optional[str] = None
    password_baru: Optional[str] = None

class RoomCreate(BaseModel):
    nomor: str
    tipe: str  # Standard | Cottage
    tarif: int  # harga Day Use (flat per sesi 6 jam)
    tarif_menginap: int  # harga Menginap per malam, TANPA sarapan (beda dari `tarif` Day Use — dua jenis layanan, dua tarif dasar)

class RoomUpdate(BaseModel):
    nomor: Optional[str] = None
    tipe: Optional[str] = None
    tarif: Optional[int] = None
    tarif_menginap: Optional[int] = None
    foto_utama: Optional[str] = None  # harus salah satu dari foto_urls kamar ini

class RoomStatusUpdate(BaseModel):
    status: str  # kosong, day_use, menginap, perlu_dibersihkan, maintenance
    catatan: Optional[str] = ""
    nama_tamu: Optional[str] = ""

class GuestCreate(BaseModel):
    nama: str
    no_hp: str = ""
    no_identitas: str = ""
    kendaraan: str = ""

class GuestUpdate(BaseModel):
    nama: Optional[str] = None
    no_hp: Optional[str] = None
    no_identitas: Optional[str] = None
    kendaraan: Optional[str] = None

class CheckinCreate(BaseModel):
    nama_tamu: str
    no_hp: str = ""
    no_identitas: str = ""
    kendaraan: str = ""
    jumlah_tamu: int = 1
    room_id: Optional[str] = None  # 1 kamar (alur lama) — diabaikan kalau room_ids diisi
    room_ids: Optional[List[str]] = None  # >1 kamar Day Use sekaligus (mis. rombongan), tarif_override berlaku sama utk tiap kamar
    catatan: str = ""
    foto_identitas_url: Optional[str] = ""
    jam_checkin: Optional[str] = None  # ISO datetime; default = now
    tarif_override: Optional[int] = None  # staf boleh set harga custom, beda dari tarif dasar kamar

class CheckoutIn(BaseModel):
    pembayaran: List[Dict[str, Any]] = []  # [{"metode":"tunai","jumlah":100000}]
    overtime_manual: Optional[int] = None
    jam_checkout: Optional[str] = None
    catatan: str = ""

class ProductCreate(BaseModel):
    kode: str
    nama: str
    kategori: str  # makanan | minuman | laundry
    harga: int
    stok: int = 0
    stok_minimal: int = 0
    aktif: bool = True

class ProductUpdate(BaseModel):
    kode: Optional[str] = None
    nama: Optional[str] = None
    kategori: Optional[str] = None
    harga: Optional[int] = None
    stok: Optional[int] = None
    stok_minimal: Optional[int] = None
    aktif: Optional[bool] = None

class StockAdjust(BaseModel):
    delta: int
    catatan: str = ""

class CartItem(BaseModel):
    product_id: str
    qty: int

class KasirCreate(BaseModel):
    items: List[CartItem]
    diskon: int = 0
    catatan: str = ""
    pembayaran: List[Dict[str, Any]]  # [{metode, jumlah}]

class ExpenseCreate(BaseModel):
    tanggal: Optional[str] = None  # ISO date
    kategori: str
    deskripsi: str
    nominal: int
    foto_url: Optional[str] = ""

class ServiceCreate(BaseModel):
    tanggal: Optional[str] = None  # ISO datetime (auto now if None)
    deskripsi: str
    nominal: int
    kategori: Optional[str] = "Layanan Tambahan"
    tamu: Optional[str] = ""
    no_hp: Optional[str] = ""
    room_nomor: Optional[str] = ""
    metode_pembayaran: Optional[str] = "tunai"  # tunai|qris|transfer

class HousekeepingDone(BaseModel):
    petugas: Optional[str] = ""
    catatan: Optional[str] = ""

class IssueCreate(BaseModel):
    tipe: str  # complaint | maintenance
    room_id: Optional[str] = None
    room_nomor: Optional[str] = ""
    deskripsi: str
    nama_tamu: Optional[str] = ""            # khusus complaint
    prioritas: Optional[str] = "normal"      # khusus complaint: rendah | normal | tinggi
    teknisi: Optional[str] = ""              # khusus maintenance
    estimasi_selesai: Optional[str] = None   # khusus maintenance, ISO datetime

class IssueStatusUpdate(BaseModel):
    status: str  # open | in_progress | resolved
    catatan_penyelesaian: Optional[str] = ""
    teknisi: Optional[str] = None
    estimasi_selesai: Optional[str] = None
    prioritas: Optional[str] = None

class MoveRoomBody(BaseModel):
    new_room_id: str
    alasan: Optional[str] = ""

class BookingCreate(BaseModel):
    room_id: Optional[str] = None  # 1 kamar (alur lama) — diabaikan kalau room_ids diisi
    room_ids: Optional[List[str]] = None  # >1 kamar sekaligus (mis. rombongan walk-in), tarif_override/dengan_sarapan berlaku sama utk tiap kamar
    tipe: str  # "day_use" | "menginap"
    nama_tamu: str
    no_hp: str = ""
    no_identitas: str = ""
    kendaraan: str = ""
    jumlah_tamu: int = 1
    jam_mulai: str
    jam_selesai: Optional[str] = None
    catatan: str = ""
    tarif_override: Optional[int] = None  # staf boleh set harga custom per malam/per sesi, beda dari tarif dasar kamar
    dengan_sarapan: bool = False  # hanya berlaku tipe menginap, diabaikan kalau tarif_override diisi (staf sudah tentukan harga akhir sendiri)

class BookingUpdate(BaseModel):
    nama_tamu: Optional[str] = None
    no_hp: Optional[str] = None
    no_identitas: Optional[str] = None
    kendaraan: Optional[str] = None
    jumlah_tamu: Optional[int] = None
    jam_mulai: Optional[str] = None
    jam_selesai: Optional[str] = None
    catatan: Optional[str] = None
    room_id: Optional[str] = None
    tipe: Optional[str] = None

class PublicBookingCreate(BaseModel):
    nama_tamu: str
    no_hp: str
    email: str  # Wajib — untuk kirim bukti pembayaran
    no_identitas: str = ""
    jumlah_tamu: int = 1
    kendaraan: str = ""
    room_id: Optional[str] = None  # 1 kamar (alur lama) — diabaikan kalau room_ids diisi
    room_ids: Optional[List[str]] = None  # >1 kamar sekaligus (tamu pilih beberapa kamar dalam 1 transaksi/pembayaran)
    tanggal: str  # YYYY-MM-DD
    jam_checkin: str  # HH:mm (24h)
    catatan: str = ""
    extra_bed_qty: int = 0  # maks divalidasi di public_create_booking (EXTRA_BED_MAX), berlaku sama tiap kamar kalau grup
    tipe: str = "day_use"  # "day_use" | "menginap"
    tanggal_checkout: Optional[str] = None  # YYYY-MM-DD, wajib jika tipe == "menginap"
    dengan_sarapan: bool = False  # hanya berlaku tipe menginap, +BREAKFAST_PRICE/malam, berlaku sama tiap kamar kalau grup

class TripayCreateTransactionBody(BaseModel):
    booking_id: str
    payment_option: str  # "dp50" atau "full"
    method: str  # kode channel Tripay, mis. QRIS/BRIVA/ALFAMART — dari GET /payments/tripay/channels

class CancelWithFeeBody(BaseModel):
    alasan: Optional[str] = ""
    no_hp_konfirmasi: str = ""

class RetryBayarBody(BaseModel):
    no_hp_konfirmasi: str = ""

class NoShowBody(BaseModel):
    alasan: Optional[str] = ""

class ManualMarkPaidBody(BaseModel):
    alasan: Optional[str] = ""
    metode: Optional[str] = "transfer_manual"
    nominal: Optional[int] = None  # if not provided, use total

class KonfirmasiHargaOtaBody(BaseModel):
    total_nominal: int  # nominal settlement ASLI dari OTA (mis. laporan RedDoorz), untuk SEMUA
                         # kamar dalam 1 reservasi OTA ini (dibagi rata jika grup >1 kamar)

class CollectBalanceBody(BaseModel):
    nominal: int
    metode: str = "cash"  # cash / qris

class CheckinFromBookingBody(BaseModel):
    no_hp: Optional[str] = None  # wajib diisi kalau booking.no_hp masih kosong (mis. booking OTA)

class PaymentStatusUpdateBody(BaseModel):
    """Body untuk ubah status pembayaran manual (halaman Pembayaran, Fase 3) — staf koreksi
    status transaksi payment_log secara manual (mis. bukti transfer dicek manual, atau
    salah catat). Beda dari webhook Tripay (otomatis) — perubahan ini dicatat sumbernya."""
    status: str  # settlement | pending | expire | deny | cancel | refund
    alasan: Optional[str] = ""

class AvailabilityLog(BaseModel):
    """Dokumen di collection `availability_logs` — riwayat pergerakan ketersediaan kamar
    (Dasbor Ketersediaan). Dicatat setiap kali kamar berpindah status tersedia <-> terisi.
    """
    id: str
    room_id: str
    room_tipe: str  # Standard | Cottage
    stock_change: int  # +1 tersedia kembali, -1 terisi/dibooking
    reason: str  # mis: booking_dibuat, booking_dibatalkan, checkin, checkout
    booking_id: Optional[str] = None
    changed_at: str

class AuditLog(BaseModel):
    """Dokumen di collection `audit_log` (Log Aktivitas / Audit Trail) — rekam jejak siapa
    mengubah apa dan kapan. Ditulis oleh `log_activity()` di setiap route yang mengubah data
    (stok kamar/rooms, reservasi/bookings, pengguna, dst — lihat pemanggilnya di seluruh
    `backend/routes/*.py`). MongoDB schemaless, jadi tidak ada migrasi terpisah; model ini
    murni dokumentasi bentuk dokumennya, dibaca lewat `GET /api/audit-log`.
    """
    id: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    action: str  # mis: create_booking, cancel_booking, change_room_status, update_user
    entity: str = ""  # mis: nomor kamar atau kode booking terkait
    detail: str = ""
    timestamp: str

class EmailExtractedData(BaseModel):
    """Bentuk `extracted_data` — hasil ekstraksi AI Email Parser dari satu email OTA.
    Sesuai kontrak yang sudah dipakai frontend (lihat MOCK_EMAIL_LOGS di OtomasiEmail.jsx).
    """
    no_reservasi: str
    nama_tamu: str
    tipe_kamar: str
    check_in: str
    check_out: str
    jumlah_tamu: int
    harga: int
    status_pembayaran: str  # Lunas | Belum Bayar | Dibatalkan
    jumlah_kamar: int = 1  # satu email OTA bisa memesan lebih dari 1 kamar sekaligus (mis. RedDoorz "Jumlah Kamar : 3")

class RoomMappingCreate(BaseModel):
    """Dokumen di collection `room_mappings` — entitas ROOM_MAPPINGS di PRD, menyamakan
    nama tipe kamar tiap OTA dengan tipe kamar yang dipakai Pelangi PMS.
    """
    ota_nama: str
    pms_tipe: str  # Standard | Cottage
    sumber: str  # Agoda | Traveloka | Booking.com

class RoomMappingUpdate(BaseModel):
    ota_nama: Optional[str] = None
    pms_tipe: Optional[str] = None
    sumber: Optional[str] = None

class MappingRuleCreate(BaseModel):
    """Dokumen di collection `mapping_rules` — pola/kata kunci per sumber OTA yang dipakai
    staf untuk mengecek (lewat 'Uji Aturan') bagaimana tiap field bisa ditemukan di badan
    email. Bersifat referensi/dokumentasi staf; AI Email Parser sungguhan (OpenAI) tidak
    butuh regex ini untuk ekstraksi — ia membaca isi email langsung.
    """
    sumber: str
    field: str  # salah satu FIELD_OPTIONS di frontend: no_reservasi, nama_tamu, dst
    pola: str  # pola regex/kata kunci
    aktif: bool = True

class MappingRuleUpdate(BaseModel):
    sumber: Optional[str] = None
    field: Optional[str] = None
    pola: Optional[str] = None
    aktif: Optional[bool] = None

class ReschedulePMSBody(BaseModel):
    """Body untuk staf konfirmasi reschedule booking OTA setelah tinjau email modifikasi
    (`POST /otomasi-email/modifikasi/{booking_id}/reschedule`) — harga TIDAK dihitung ulang,
    cuma jadwal yang berubah, konsisten dengan konvensi reschedule staf yang sudah ada
    (`PUT /bookings/{id}`)."""
    jam_mulai: str  # ISO datetime
    jam_selesai: str  # ISO datetime

class WebhookConfigUpdate(BaseModel):
    """Dokumen tunggal di collection `webhook_config` — kredensial penyedia WhatsApp
    pihak ketiga (Fonnte/Wablas/Qontak/custom) yang dimasukkan staf sendiri.
    """
    aktif: Optional[bool] = None
    provider: Optional[str] = None
    webhook_url: Optional[str] = None
    api_key: Optional[str] = None
    nomor_whatsapp: Optional[str] = None

class BusinessRuleIn(BaseModel):
    """PMS = Business Platform, pemilik kebenaran aturan bisnis (DP, cancellation, jam
    checkin/checkout, promo, kebijakan umum) — ai-chat-bot (Brain Platform) menarik ini
    lewat endpoint integrasi, bukan menyimpan salinan otoritatif sendiri."""
    category: str
    title: str
    description: str
    value: Optional[Dict[str, Any]] = None
    is_active: bool = True

class BusinessRuleUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    value: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

class SyncSettingsUpdate(BaseModel):
    """Dokumen tunggal di collection `sync_settings` (Pengaturan Sinkronisasi Ketersediaan)."""
    frekuensi_menit: Optional[int] = None
    prioritas: Optional[List[str]] = None

class EmailSendLog(BaseModel):
    """Dokumen di collection `email_send_log` — riwayat pengiriman voucher/bukti booking
    ke tamu (Pengiriman Voucher Otomatis). Pengiriman sungguhan (SMTP/API) BELUM aktif
    (butuh kredensial yang belum diberikan) — collection & endpoint sudah siap, tinggal
    diisi begitu service pengiriman diaktifkan.
    """
    id: str
    booking_id: str
    kode_booking: str
    nama_tamu: str
    tujuan_email: str
    metode: str = "Email"
    status: str  # Terkirim | Gagal
    error: Optional[str] = None
    waktu: str

class EmailLog(BaseModel):
    """Dokumen di collection `email_logs` — riwayat email OTA yang masuk ke Gmail dan
    diproses (atau gagal diproses) oleh AI Email Parser. Entitas EMAIL_LOGS di PRD
    (gmail_message_id, status, extracted_data, processed_at), ditambah field tampilan
    (subjek/pengirim/sumber/alasan) yang sudah dipakai frontend Otomasi Email & Pemesanan.
    """
    id: str
    gmail_message_id: str
    subjek: str
    pengirim: str
    sumber: str  # Agoda | Traveloka | Booking.com | Lainnya, dst — hasil deteksi domain pengirim
    status: str  # Parsed_Success | Failed | Manual_Required | Perlu_Review_Modifikasi | Sudah_Diproses
    jenis: Optional[str] = None  # baru | modifikasi | pembatalan — klasifikasi AI, None kalau is_reservation false
    extracted_data: Optional[EmailExtractedData] = None
    reservation_id: Optional[str] = None  # booking PMS yang dibuat/dibatalkan otomatis dari email ini (pertama, kalau lebih dari satu)
    reservation_ids: Optional[List[str]] = None  # semua booking PMS terkait (kalau 1 email OTA = beberapa kamar sekaligus)
    aksi: Optional[str] = None  # reservasi_baru_dibuat | reservasi_dibatalkan — hasil Reservation Automation
    alasan: Optional[str] = None  # diisi kalau status Failed/Manual_Required
    processed_at: str

class RateOverride(BaseModel):
    """Dokumen di collection `rates` (Fase 3 - Manajemen Harga/Rates, halaman Kalender Harga).
    Satu dokumen = override harga satu tipe kamar pada satu tanggal (kunci unik room_type+tanggal).
    Tanggal tanpa dokumen di sini memakai tarif dasar `rooms.tarif` (per tipe kamar)."""
    id: str
    room_type: str
    tanggal: str  # YYYY-MM-DD
    harga: int
    updated_at: str
    updated_by: str

class BookingRequestApprove(BaseModel):
    """Body untuk staf menyetujui Booking Request (PRD Modul Reservasi & Priority Booking) —
    staf memilih kamar spesifik SETELAH mengecek ketersediaan manual (termasuk cek silang ke
    PMS RedDoorz, yang sistem ini tidak bisa cek otomatis)."""
    room_ids: List[str]  # wajib sejumlah booking_request.jumlah_kamar
    payment_option: str = "dp50"  # dp50 | full
    method: str  # kode channel Tripay (mis. QRIS/BRIVA), dari GET /payments/tripay/channels

class BookingRequestReject(BaseModel):
    alasan: Optional[str] = ""

class StaffKerjaCreate(BaseModel):
    """Dokumen di collection `staff_kerja` — roster staf yang dijadwalkan shift (Jadwal
    Kerja). SENGAJA terpisah dari `users` (akun login PMS) — staf shift (housekeeping/
    umum) tidak wajib punya akun PMS sendiri, sama seperti nama `petugas` yang sudah
    dipakai bebas di checkins/housekeeping_log tanpa perlu akun."""
    nama: str
    shift_terlarang: List[str] = []  # subset dari ["morning","middle","night"]
    aktif: bool = True

class StaffKerjaUpdate(BaseModel):
    nama: Optional[str] = None
    shift_terlarang: Optional[List[str]] = None
    aktif: Optional[bool] = None

class JadwalGenerateBody(BaseModel):
    year: int
    month: int

class JadwalShiftUpdateBody(BaseModel):
    staff_id: str
    tanggal: str  # YYYY-MM-DD
    shift: str  # morning | middle | night | off

class JadwalSwapBody(BaseModel):
    staff_id_a: str
    tanggal_a: str
    staff_id_b: str
    tanggal_b: str

# ---- Payroll (2026-07-20, permintaan user) ----
# SENGAJA collection staf terpisah dari `staff_kerja` (roster shift) - payroll butuh field
# beda (gaji pokok, posisi) dan owner ingin bebas isi/edit staf untuk payroll tanpa terikat
# ke aturan shift. Nama staf boleh sama persis dengan staff_kerja kalau memang orang yang
# sama, tapi tidak ada relasi/foreign key otomatis - dua daftar independen.
class StaffProfilCreate(BaseModel):
    nama: str
    posisi: str = ""
    no_hp: str = ""  # untuk kirim slip gaji/kasbon via WhatsApp (2026-07-20)
    gaji_pokok: int = 0  # per bulan, Rupiah - owner isi manual, boleh 0/kosong dulu
    aktif: bool = True
    catatan: str = ""

class StaffProfilUpdate(BaseModel):
    nama: Optional[str] = None
    posisi: Optional[str] = None
    no_hp: Optional[str] = None
    gaji_pokok: Optional[int] = None
    aktif: Optional[bool] = None
    catatan: Optional[str] = None

class KasbonCreate(BaseModel):
    staff_id: str
    nominal: int
    tanggal: str  # YYYY-MM-DD
    alasan: str = ""

class KasbonUpdate(BaseModel):
    """Edit manual - dipakai kalau owner mau koreksi nominal/alasan, atau tandai lunas
    manual di luar mekanisme potong-otomatis-dari-payroll."""
    nominal: Optional[int] = None
    tanggal: Optional[str] = None
    alasan: Optional[str] = None
    sisa: Optional[int] = None

class PayrollCreate(BaseModel):
    """Semua nominal opsional & bisa diisi manual oleh owner (permintaan user "flexible") -
    gaji_pokok & potongan_kasbon PRE-FILL otomatis dari staff_profil/kasbon aktif kalau tidak
    diisi eksplisit, tapi owner boleh override angka apa pun sebelum simpan."""
    staff_id: str
    periode: str  # YYYY-MM
    gaji_pokok: Optional[int] = None  # None = pre-fill dari staff_profil.gaji_pokok
    service_charge: int = 0
    tunjangan_lain: int = 0
    potongan_kasbon: Optional[int] = None  # None = pre-fill otomatis dari sisa kasbon aktif
    potongan_lain: int = 0
    catatan: str = ""

class PayrollUpdate(BaseModel):
    gaji_pokok: Optional[int] = None
    service_charge: Optional[int] = None
    tunjangan_lain: Optional[int] = None
    potongan_kasbon: Optional[int] = None
    potongan_lain: Optional[int] = None
    catatan: Optional[str] = None
    status: Optional[str] = None  # draft | dibayar

class RateBulkUpdateBody(BaseModel):
    """Body untuk Update Harga Massal (halaman Kalender Harga): terapkan satu harga ke
    rentang tanggal [dari, sampai] untuk satu tipe kamar, atau 'Semua' tipe sekaligus."""
    room_type: str  # nama tipe kamar, atau "Semua"
    dari: str  # YYYY-MM-DD
    sampai: str  # YYYY-MM-DD
    harga: int


# ---- Cash & Account Intelligence (2026-07-22, PRD "AI Grow") ----
# V1: ledger MANUAL berdiri sendiri (bukan auto-sync dari booking/expenses yang sudah ada -
# keputusan sadar bareng user supaya cepat kepakai & tidak menyentuh alur uang production
# yang sudah ada). Owner catat sendiri saldo awal, pemasukan/pengeluaran, & transfer per
# rekening. V2 tambah rekonsiliasi CSV mutasi bank (mencocokkan, bukan menggantikan ledger
# manual), smart allocation (transfer otomatis), forecast, & deteksi risiko saldo.
REKENING_JENIS = ["operasional", "tabungan", "pinjaman"]

class RekeningCreate(BaseModel):
    nama: str
    bank: str = ""
    no_rekening: str = ""
    pemilik: str = ""
    jenis: str  # operasional | tabungan | pinjaman
    saldo_awal: int = 0
    target: Optional[int] = None  # goal tabungan, cuma relevan kalau jenis=tabungan
    warna: str = "#0F4C5C"
    icon: str = "Wallet"

class RekeningUpdate(BaseModel):
    nama: Optional[str] = None
    bank: Optional[str] = None
    no_rekening: Optional[str] = None
    pemilik: Optional[str] = None
    target: Optional[int] = None
    warna: Optional[str] = None
    icon: Optional[str] = None
    status: Optional[str] = None  # aktif | nonaktif

class RekeningTransaksiCreate(BaseModel):
    """Pemasukan/pengeluaran manual pada 1 rekening (BUKAN transfer - lihat TransferIn)."""
    rekening_id: str
    jenis: str  # pemasukan | pengeluaran
    nominal: int
    kategori: str = ""
    deskripsi: str = ""
    tanggal: Optional[str] = None  # ISO date, default hari ini

class TransferIn(BaseModel):
    rekening_asal_id: str
    rekening_tujuan_id: str
    nominal: int
    deskripsi: str = ""
    tanggal: Optional[str] = None

class SmartAllocationRuleCreate(BaseModel):
    """2 mode trigger (WAJIB isi salah satu, bukan dua-duanya):
    - saldo_diatas: begitu saldo rekening_asal_id > ambang_saldo, transfer nominal_transfer
      ke rekening_tujuan_id (dicek tiap kali rekening_asal saldonya berubah).
    - tanggal_bulanan: tiap tanggal_hari (1-28) tiap bulan, transfer nominal_transfer
      (dicek oleh background loop harian, lihat routes/rekening.py)."""
    nama: str
    rekening_asal_id: str
    rekening_tujuan_id: str
    trigger_tipe: str  # saldo_diatas | tanggal_bulanan
    ambang_saldo: Optional[int] = None  # wajib kalau trigger_tipe=saldo_diatas
    tanggal_hari: Optional[int] = None  # 1-28, wajib kalau trigger_tipe=tanggal_bulanan
    nominal_transfer: int
    aktif: bool = True

class SmartAllocationRuleUpdate(BaseModel):
    nama: Optional[str] = None
    ambang_saldo: Optional[int] = None
    tanggal_hari: Optional[int] = None
    nominal_transfer: Optional[int] = None
    aktif: Optional[bool] = None
