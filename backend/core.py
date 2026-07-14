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
import midtransclient
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
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

# ---- Midtrans setup ----
MIDTRANS_SERVER_KEY = os.environ.get("MIDTRANS_SERVER_KEY", "")
MIDTRANS_CLIENT_KEY = os.environ.get("MIDTRANS_CLIENT_KEY", "")
MIDTRANS_IS_PRODUCTION = os.environ.get("MIDTRANS_IS_PRODUCTION", "false").lower() == "true"

snap_client = midtransclient.Snap(
    is_production=MIDTRANS_IS_PRODUCTION,
    server_key=MIDTRANS_SERVER_KEY,
    client_key=MIDTRANS_CLIENT_KEY,
)

# ---- Tripay setup (menggantikan Midtrans — lihat routes/tripay.py) ----
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

# ---- Constants ----
SERVICE_FEE_PCT = 0.03  # 3% service fee diaplikasikan ke checkin & booking
EXTRA_BED_PRICE = 50000  # per extra bed, flat (PRD: "Extra Bed Rp 50.000 berlaku untuk kedua jenis layanan")
EXTRA_BED_MAX = 2  # maksimal per kamar (sama seperti ExtraBedSelector di frontend)
BREAKFAST_PRICE = 25000  # per malam, opsional, hanya berlaku untuk tipe menginap
# `rooms.tarif` = harga Day Use (flat per sesi 6 jam) — Standard 120rb/Cottage 140rb.
# `rooms.tarif_menginap` = harga Menginap per malam TANPA sarapan — Standard 150rb/Cottage 200rb,
# +BREAKFAST_PRICE kalau dengan_sarapan (jadi 175rb/225rb). Dua tarif dasar terpisah sejak 2026-07-12
# (sebelumnya sempat memakai satu field `tarif` untuk keduanya — salah, dikoreksi atas instruksi user).

# ---- Utilities ----
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

def parse_iso(s: str, field: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        raise HTTPException(400, f"Format {field} tidak valid (harus ISO 8601)")

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

class RoomStatusUpdate(BaseModel):
    status: str  # kosong, day_use, menginap, perlu_dibersihkan, maintenance
    catatan: Optional[str] = ""
    nama_tamu: Optional[str] = ""

class CheckinCreate(BaseModel):
    nama_tamu: str
    no_hp: str = ""
    no_identitas: str = ""
    kendaraan: str = ""
    jumlah_tamu: int = 1
    room_id: str
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

class MoveRoomBody(BaseModel):
    new_room_id: str
    alasan: Optional[str] = ""

class BookingCreate(BaseModel):
    room_id: str
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
    room_id: str
    tanggal: str  # YYYY-MM-DD
    jam_checkin: str  # HH:mm (24h)
    catatan: str = ""
    extra_bed_qty: int = 0  # maks divalidasi di public_create_booking (EXTRA_BED_MAX)
    tipe: str = "day_use"  # "day_use" | "menginap"
    tanggal_checkout: Optional[str] = None  # YYYY-MM-DD, wajib jika tipe == "menginap"
    dengan_sarapan: bool = False  # hanya berlaku tipe menginap, +BREAKFAST_PRICE/malam

class CreateSnapTokenBody(BaseModel):
    booking_id: str
    payment_option: str  # "dp50" atau "full"

class TripayCreateTransactionBody(BaseModel):
    booking_id: str
    payment_option: str  # "dp50" atau "full"
    method: str  # kode channel Tripay, mis. QRIS/BRIVA/ALFAMART — dari GET /payments/tripay/channels

class CancelWithFeeBody(BaseModel):
    alasan: Optional[str] = ""

class NoShowBody(BaseModel):
    alasan: Optional[str] = ""

class ManualMarkPaidBody(BaseModel):
    alasan: Optional[str] = ""
    metode: Optional[str] = "transfer_manual"
    nominal: Optional[int] = None  # if not provided, use total

class CollectBalanceBody(BaseModel):
    nominal: int
    metode: str = "cash"  # cash / qris

class PaymentStatusUpdateBody(BaseModel):
    """Body untuk ubah status pembayaran manual (halaman Pembayaran, Fase 3) — staf koreksi
    status transaksi payment_log secara manual (mis. bukti transfer dicek manual, atau
    salah catat). Beda dari webhook Midtrans (otomatis) — perubahan ini dicatat sumbernya."""
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
    reservation_id: Optional[str] = None  # booking PMS yang dibuat/dibatalkan otomatis dari email ini
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

class RateBulkUpdateBody(BaseModel):
    """Body untuk Update Harga Massal (halaman Kalender Harga): terapkan satu harga ke
    rentang tanggal [dari, sampai] untuk satu tipe kamar, atau 'Semua' tipe sekaligus."""
    room_type: str  # nama tipe kamar, atau "Semua"
    dari: str  # YYYY-MM-DD
    sampai: str  # YYYY-MM-DD
    harga: int
