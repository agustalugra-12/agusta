from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import jwt
import bcrypt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Query
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

# ---- Mongo Setup ----
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_ALGO = "HS256"
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")

app = FastAPI(title="Pelangi Homestay API")
api = APIRouter(prefix="/api")

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
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.get("id"),
        "username": user.get("username"),
        "action": action,
        "entity": entity,
        "detail": detail,
        "timestamp": now_iso(),
    })

# ---- Models ----
class LoginIn(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    nama: str
    username: str
    password: str
    role: str  # owner | resepsionis

class UserUpdate(BaseModel):
    nama: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None  # aktif | nonaktif

class RoomCreate(BaseModel):
    nomor: str
    tipe: str  # Standard | Cottage
    tarif: int

class RoomUpdate(BaseModel):
    nomor: Optional[str] = None
    tipe: Optional[str] = None
    tarif: Optional[int] = None

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

class CheckoutIn(BaseModel):
    pembayaran: List[Dict[str, Any]] = []  # [{"metode":"tunai","jumlah":100000}]
    overtime_manual: Optional[int] = None  # jika ingin override jam overtime
    jam_checkout: Optional[str] = None  # opsional, ISO datetime
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

# ---- Public Booking (no-auth) ----
class PublicBookingCreate(BaseModel):
    nama_tamu: str
    no_hp: str
    no_identitas: str = ""
    jumlah_tamu: int = 1
    kendaraan: str = ""
    room_id: str
    tanggal: str  # YYYY-MM-DD
    jam_checkin: str  # HH:mm (24h)
    catatan: str = ""

@api.get("/public/rooms-catalog")
async def public_rooms_catalog():
    """Katalog kamar untuk halaman publik. Mengelompokkan berdasarkan tipe.
    Tidak mengekspos field internal seperti info / status detail.
    """
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    rooms.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    grouped: Dict[str, Any] = {}
    for r in rooms:
        t = r["tipe"]
        if t not in grouped:
            grouped[t] = {
                "tipe": t,
                "tarif": r["tarif"],
                "fasilitas": [
                    "AC", "Wi-Fi gratis", "TV LED", "Kamar mandi dalam",
                    "Air panas", "Handuk & toiletries",
                ] + (["Cottage Style", "Area Outdoor"] if t == "Cottage" else []),
                "rooms": [],
            }
        grouped[t]["rooms"].append({"id": r["id"], "nomor": r["nomor"]})
    return list(grouped.values())

@api.get("/public/availability")
async def public_availability(tanggal: str, tipe: Optional[str] = None):
    """List kamar tersedia pada tanggal tertentu (halaman publik).
    Untuk tanggal MASA DEPAN, status realtime kamar (day_use/menginap/perlu_dibersihkan) TIDAK relevan
    karena akan kembali kosong sebelum tanggal tersebut. Hanya `maintenance` (long-term) yang di-exclude.
    Filter utama: tidak ada booking_pending/booking_paid/aktif yang overlap dengan tanggal target.
    """
    try:
        d = datetime.fromisoformat(tanggal)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    d_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    d_end = d_start + timedelta(days=1)
    # Untuk hari INI, kamar yang sedang dipakai (day_use/menginap/perlu_dibersihkan) tidak tersedia.
    # Untuk hari LAIN (masa depan), hanya 'maintenance' yang dikecualikan.
    today_local = datetime.now().strftime("%Y-%m-%d")
    is_today = tanggal == today_local
    q: Dict[str, Any] = {}
    if tipe:
        q["tipe"] = tipe
    if is_today:
        q["status"] = "kosong"
    else:
        q["status"] = {"$ne": "maintenance"}
    rooms = await db.rooms.find(q, {"_id": 0}).to_list(500)
    # Filter rooms yang punya booking overlap di tanggal tsb
    out = []
    for r in rooms:
        bk = await db.bookings.find_one({
            "room_id": r["id"],
            "status": {"$in": ["aktif", "booking_paid", "booking_pending"]},
            "jam_mulai": {"$lt": d_end.isoformat()},
            "jam_selesai": {"$gt": d_start.isoformat()},
        })
        if not bk:
            out.append({"id": r["id"], "nomor": r["nomor"], "tipe": r["tipe"], "tarif": r["tarif"]})
    out.sort(key=lambda r: (0 if r["tipe"] == "Standard" else 1, int(r["nomor"]) if r["nomor"].isdigit() else 9999))
    return {"tanggal": tanggal, "tipe": tipe, "rooms": out}

@api.post("/public/bookings")
async def public_create_booking(body: PublicBookingCreate):
    """Booking publik (tanpa login). Membuat booking dengan status 'booking_pending'.
    Tarif = tarif kamar + 3% service fee. Wajib bayar (DP 50% min) via Xendit (Fase C).
    Sementara Xendit belum ada, booking tetap berstatus pending sampai resepsionis approve.
    """
    r = await db.rooms.find_one({"id": body.room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, "Kamar tidak tersedia")
    # Parse tanggal + jam check-in (WIB +07:00)
    try:
        local_in = datetime.fromisoformat(f"{body.tanggal}T{body.jam_checkin}:00+07:00")
    except Exception:
        raise HTTPException(400, "Format tanggal/jam tidak valid")
    start = local_in.astimezone(timezone.utc)
    end = start + timedelta(hours=6)  # day use 6 jam default
    # Validasi overlap (semua status booking yang block: aktif, booking_pending, booking_paid)
    overlap = await db.bookings.find_one({
        "room_id": body.room_id,
        "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": end.isoformat()},
        "jam_selesai": {"$gt": start.isoformat()},
    })
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")
    subtotal = r["tarif"]
    service_fee = round(subtotal * SERVICE_FEE_PCT)
    total = subtotal + service_fee
    dp_min = round(total * 0.5)
    kode = f"BKO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    doc = {
        "id": str(uuid.uuid4()), "kode": kode,
        "room_id": body.room_id, "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tipe": "day_use",
        "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
        "no_identitas": body.no_identitas, "kendaraan": body.kendaraan,
        "jumlah_tamu": body.jumlah_tamu,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": body.catatan,
        "status": "booking_pending",          # status booking utama (untuk public booking)
        "payment_status": "pending",          # pending | paid | expired | failed | refunded
        "subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": dp_min,
        "source": "online",                   # online | walk_in
        "invoice_id": None, "payment_id": None,
        "created_at": now_iso(), "created_by": body.nama_tamu,
    }
    await db.bookings.insert_one(doc)
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()), "user_id": None, "username": "public",
        "action": "public_create_booking",
        "detail": f"Public booking {kode} kamar {r['nomor']} ({r['tipe']}) untuk {body.nama_tamu}",
        "entity": r["nomor"], "timestamp": now_iso(),
    })
    doc.pop("_id", None)
    return doc

@api.get("/public/bookings/{bid}")
async def public_get_booking(bid: str):
    b = await db.bookings.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    # batasi field yang dikembalikan ke publik
    safe = {k: b.get(k) for k in [
        "id", "kode", "room_nomor", "room_tipe", "tipe", "nama_tamu", "no_hp",
        "jumlah_tamu", "jam_mulai", "jam_selesai", "status", "payment_status",
        "subtotal", "service_fee", "total", "dp_min", "invoice_id",
    ]}
    return safe

# ---- Midtrans Payment Gateway ----
import hashlib
import midtransclient

MIDTRANS_SERVER_KEY = os.environ.get("MIDTRANS_SERVER_KEY", "")
MIDTRANS_CLIENT_KEY = os.environ.get("MIDTRANS_CLIENT_KEY", "")
MIDTRANS_IS_PRODUCTION = os.environ.get("MIDTRANS_IS_PRODUCTION", "false").lower() == "true"

snap_client = midtransclient.Snap(
    is_production=MIDTRANS_IS_PRODUCTION,
    server_key=MIDTRANS_SERVER_KEY,
    client_key=MIDTRANS_CLIENT_KEY,
)

class CreateSnapTokenBody(BaseModel):
    booking_id: str
    payment_option: str  # "dp50" atau "full"

@api.get("/payments/midtrans/config")
async def get_midtrans_config():
    """Endpoint public untuk ambil client key (dipakai Snap.js di frontend)."""
    return {
        "client_key": MIDTRANS_CLIENT_KEY,
        "is_production": MIDTRANS_IS_PRODUCTION,
        "snap_url": (
            "https://app.midtrans.com/snap/snap.js" if MIDTRANS_IS_PRODUCTION
            else "https://app.sandbox.midtrans.com/snap/snap.js"
        ),
    }

@api.post("/payments/midtrans/create-snap-token")
async def create_snap_token(body: CreateSnapTokenBody):
    """Buat Snap transaction token untuk booking publik. No-auth (tamu publik).
    payment_option: dp50 = bayar 50%, full = bayar penuh.
    """
    b = await db.bookings.find_one({"id": body.booking_id})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("booking_pending",):
        raise HTTPException(400, f"Booking tidak dapat dibayar (status: {b.get('status')})")
    total = int(b.get("total", 0))
    if body.payment_option == "dp50":
        gross_amount = int(b.get("dp_min") or round(total * 0.5))
    elif body.payment_option == "full":
        gross_amount = total
    else:
        raise HTTPException(400, "payment_option harus 'dp50' atau 'full'")
    # order_id unik per attempt
    order_id = f"{b['kode']}-{datetime.now().strftime('%H%M%S')}{uuid.uuid4().hex[:3].upper()}"
    parameter = {
        "transaction_details": {"order_id": order_id, "gross_amount": gross_amount},
        "enabled_payments": ["qris", "bank_transfer", "echannel", "permata_va",
                              "bca_va", "bni_va", "bri_va", "cimb_va", "mandiri_va"],
        "customer_details": {
            "first_name": b.get("nama_tamu", ""),
            "phone": b.get("no_hp", ""),
        },
        "item_details": [{
            "id": b["room_id"], "name": f"Kamar {b['room_nomor']} ({b['room_tipe']})",
            "price": gross_amount, "quantity": 1,
        }],
        "callbacks": {"finish": f"{os.environ.get('FRONTEND_URL', '')}/book/sukses/{b['id']}"},
    }
    try:
        trx = snap_client.create_transaction(parameter)
    except Exception as e:
        raise HTTPException(502, f"Midtrans error: {e}")
    # simpan ke booking + payment_log
    await db.bookings.update_one({"id": b["id"]}, {"$set": {
        "invoice_id": order_id, "payment_option": body.payment_option,
        "amount_due": gross_amount, "amount_paid_min": gross_amount,
        "updated_at": now_iso(),
    }})
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "booking_id": b["id"], "booking_kode": b["kode"],
        "order_id": order_id, "transaction_token": trx.get("token"),
        "redirect_url": trx.get("redirect_url"),
        "gross_amount": str(gross_amount), "payment_option": body.payment_option,
        "transaction_status": "initiated", "status_code": None,
        "payment_type": None, "fraud_status": None,
        "created_at": now_iso(), "updated_at": now_iso(),
        "midtrans_response": trx,
    })
    return {
        "booking_id": b["id"], "order_id": order_id,
        "transaction_token": trx.get("token"), "redirect_url": trx.get("redirect_url"),
        "client_key": MIDTRANS_CLIENT_KEY, "gross_amount": gross_amount,
        "is_production": MIDTRANS_IS_PRODUCTION,
    }

def _verify_midtrans_signature(order_id: str, status_code: str, gross_amount: str, signature_key: str) -> bool:
    raw = f"{order_id}{status_code}{gross_amount}{MIDTRANS_SERVER_KEY}".encode("utf-8")
    return hashlib.sha512(raw).hexdigest() == signature_key

@api.post("/payments/midtrans/notification")
async def midtrans_notification(request: Request):
    """Webhook Midtrans. URL ini harus di-set di Dashboard Midtrans
    (Settings → Configuration → Payment Notification URL).
    """
    payload = await request.json()
    order_id = payload.get("order_id")
    status_code = payload.get("status_code")
    gross_amount = payload.get("gross_amount")
    signature_key = payload.get("signature_key", "")
    transaction_status = payload.get("transaction_status")
    payment_type = payload.get("payment_type")
    fraud_status = payload.get("fraud_status")
    if not all([order_id, status_code, gross_amount, signature_key]):
        raise HTTPException(400, "Payload Midtrans tidak lengkap")
    if not _verify_midtrans_signature(order_id, status_code, gross_amount, signature_key):
        raise HTTPException(403, "Signature Midtrans tidak valid")
    # update payment_log (idempotent by order_id)
    log = await db.payment_log.find_one({"order_id": order_id})
    log_fields = {
        "transaction_status": transaction_status, "status_code": status_code,
        "gross_amount": gross_amount, "payment_type": payment_type,
        "fraud_status": fraud_status, "notification_payload": payload,
        "updated_at": now_iso(),
    }
    if log:
        await db.payment_log.update_one({"_id": log["_id"]}, {"$set": log_fields})
        booking_id = log.get("booking_id")
    else:
        # fallback insert (jarang terjadi)
        new_log = {"id": str(uuid.uuid4()), "order_id": order_id,
                   "created_at": now_iso(), **log_fields}
        await db.payment_log.insert_one(new_log)
        booking_id = None
    # update booking
    if booking_id:
        b = await db.bookings.find_one({"id": booking_id})
        if b:
            new_status = b.get("status")
            new_payment = b.get("payment_status", "pending")
            now = now_iso()
            if transaction_status in ("settlement", "capture"):
                if transaction_status == "capture" and fraud_status == "challenge":
                    new_payment = "challenge"
                else:
                    new_status = "booking_paid"
                    new_payment = "paid"
            elif transaction_status == "pending":
                new_payment = "pending"
            elif transaction_status in ("expire", "cancel", "deny"):
                new_status = "cancelled"
                new_payment = "expired" if transaction_status == "expire" else "failed"
            elif transaction_status == "refund":
                new_payment = "refunded"
            await db.bookings.update_one({"id": booking_id}, {"$set": {
                "status": new_status, "payment_status": new_payment,
                "paid_at": now if new_payment == "paid" else b.get("paid_at"),
                "payment_type": payment_type,
                "updated_at": now,
            }})
            # log activity
            await db.audit_log.insert_one({
                "id": str(uuid.uuid4()), "user_id": None, "username": "midtrans-webhook",
                "action": f"payment_{transaction_status}",
                "detail": f"Booking {b['kode']} - {transaction_status} ({payment_type or 'n/a'}) Rp{gross_amount}",
                "entity": b.get("room_nomor", ""), "timestamp": now,
            })
    return {"ok": True}

@api.get("/payments/midtrans/status/{order_id}")
async def get_payment_status(order_id: str):
    """Polling status pembayaran untuk frontend (setelah Snap close)."""
    log = await db.payment_log.find_one({"order_id": order_id}, {"_id": 0, "midtrans_response": 0, "notification_payload": 0})
    if not log:
        raise HTTPException(404, "Payment log tidak ditemukan")
    return log

# ---- Auth Endpoints ----
@api.post("/auth/login")
async def login(body: LoginIn, response: Response):
    u = await db.users.find_one({"username": body.username.lower()})
    if not u or not verify_password(body.password, u.get("password_hash", "")):
        raise HTTPException(401, "Username atau password salah")
    if u.get("status") == "nonaktif":
        raise HTTPException(403, "Akun dinonaktifkan")
    token = create_token(u["id"], u["username"], u["role"])
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=7*24*3600, path="/")
    user_data = {k: v for k, v in u.items() if k not in ("_id", "password_hash")}
    await log_activity(u, "login", f"Login berhasil")
    return {"token": token, "user": user_data}

@api.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    await log_activity(user, "logout", "Logout")
    return {"ok": True}

@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user

# ---- Users (Owner only) ----
@api.get("/users")
async def list_users(user: dict = Depends(require_owner)):
    items = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(500)
    return items

@api.post("/users")
async def create_user(body: UserCreate, user: dict = Depends(require_owner)):
    if body.role not in ("owner", "resepsionis"):
        raise HTTPException(400, "Role tidak valid")
    if await db.users.find_one({"username": body.username.lower()}):
        raise HTTPException(400, "Username sudah dipakai")
    doc = {
        "id": str(uuid.uuid4()),
        "nama": body.nama,
        "username": body.username.lower(),
        "password_hash": hash_password(body.password),
        "role": body.role,
        "status": "aktif",
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    await log_activity(user, "create_user", f"Buat pengguna {body.username}")
    return {k: v for k, v in doc.items() if k not in ("password_hash", "_id")}

@api.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, user: dict = Depends(require_owner)):
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(404, "User tidak ditemukan")
    updates: Dict[str, Any] = {}
    if body.nama is not None: updates["nama"] = body.nama
    if body.role is not None: updates["role"] = body.role
    if body.status is not None: updates["status"] = body.status
    if body.password:
        updates["password_hash"] = hash_password(body.password)
    if updates:
        await db.users.update_one({"id": user_id}, {"$set": updates})
    await log_activity(user, "update_user", f"Update user {u['username']}")
    return {"ok": True}

@api.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_owner)):
    if user_id == user["id"]:
        raise HTTPException(400, "Tidak dapat menghapus diri sendiri")
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(404, "User tidak ditemukan")
    await db.users.delete_one({"id": user_id})
    await log_activity(user, "delete_user", f"Hapus user {u['username']}")
    return {"ok": True}

# ---- Rooms ----
@api.get("/rooms")
async def list_rooms(user: dict = Depends(get_current_user)):
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    # tipe order (Standard first, then Cottage), then numeric room number
    tipe_order = {"Standard": 0, "Cottage": 1}
    rooms.sort(key=lambda r: (tipe_order.get(r.get("tipe", ""), 99), int("".join(c for c in r.get("nomor", "0") if c.isdigit()) or 0)))
    return rooms

@api.post("/rooms")
async def create_room(body: RoomCreate, user: dict = Depends(require_owner)):
    if await db.rooms.find_one({"nomor": body.nomor}):
        raise HTTPException(400, "Nomor kamar sudah ada")
    doc = {
        "id": str(uuid.uuid4()),
        "nomor": body.nomor,
        "tipe": body.tipe,
        "tarif": body.tarif,
        "status": "kosong",
        "info": {},  # menginap info: nama_tamu, checkin_date, checkout_date, catatan
        "created_at": now_iso(),
    }
    await db.rooms.insert_one(doc)
    await log_activity(user, "create_room", f"Buat kamar {body.nomor}")
    doc.pop("_id", None)
    return doc

@api.put("/rooms/{room_id}")
async def update_room(room_id: str, body: RoomUpdate, user: dict = Depends(require_owner)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await db.rooms.update_one({"id": room_id}, {"$set": updates})
    await log_activity(user, "update_room", f"Update kamar {r['nomor']}")
    return {"ok": True}

@api.delete("/rooms/{room_id}")
async def delete_room(room_id: str, user: dict = Depends(require_owner)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, "Kamar tidak dapat dihapus karena sedang aktif")
    await db.rooms.delete_one({"id": room_id})
    await log_activity(user, "delete_room", f"Hapus kamar {r['nomor']}")
    return {"ok": True}

@api.put("/rooms/{room_id}/status")
async def change_room_status(room_id: str, body: RoomStatusUpdate, user: dict = Depends(get_current_user)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    valid = {"kosong", "day_use", "menginap", "perlu_dibersihkan", "maintenance"}
    if body.status not in valid:
        raise HTTPException(400, "Status tidak valid")
    if body.status == "day_use":
        raise HTTPException(400, "Status day_use diubah otomatis lewat check-in")
    old_status = r["status"]
    info = r.get("info", {}) or {}
    if body.status == "menginap":
        info = {
            "nama_tamu": body.nama_tamu,
            "catatan": body.catatan,
            "checkin_date": now_iso(),
        }
    elif body.status == "maintenance":
        info = {"catatan": body.catatan}
    else:
        info = {}
    await db.rooms.update_one({"id": room_id}, {"$set": {"status": body.status, "info": info}})
    await log_activity(user, "change_room_status",
                       f"Kamar {r['nomor']}: {old_status} -> {body.status}",
                       entity=r["nomor"])
    # housekeeping log
    if body.status == "perlu_dibersihkan":
        await db.housekeeping_log.insert_one({
            "id": str(uuid.uuid4()),
            "room_id": r["id"],
            "room_nomor": r["nomor"],
            "tanggal": now_iso(),
            "jam_mulai": None,
            "jam_selesai": None,
            "petugas": "",
            "catatan": body.catatan or "",
            "status": "pending",
        })
    return {"ok": True}

@api.post("/rooms/{room_id}/housekeeping-done")
async def housekeeping_done(room_id: str, body: HousekeepingDone, user: dict = Depends(get_current_user)):
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "perlu_dibersihkan":
        raise HTTPException(400, "Kamar tidak dalam status Perlu Dibersihkan")
    await db.rooms.update_one({"id": room_id}, {"$set": {"status": "kosong", "info": {}}})
    pending = await db.housekeeping_log.find_one({"room_id": room_id, "status": "pending"}, sort=[("tanggal", -1)])
    if pending:
        await db.housekeeping_log.update_one(
            {"id": pending["id"]},
            {"$set": {
                "jam_selesai": now_iso(),
                "petugas": body.petugas or user["nama"],
                "catatan": body.catatan or pending.get("catatan", ""),
                "status": "selesai",
            }}
        )
    await log_activity(user, "housekeeping_done", f"Kamar {r['nomor']} selesai dibersihkan", entity=r["nomor"])
    return {"ok": True}

@api.post("/rooms/{room_id}/move")
async def move_room(room_id: str, body: MoveRoomBody, user: dict = Depends(get_current_user)):
    """Pindahkan tamu/info dari kamar lama ke kamar baru.
    - day_use: update checkin aktif room_id + room_nomor + room_tipe (tarif_dasar tetap), pindah info.
    - menginap: pindah info dict ke kamar baru.
    - Kamar lama → perlu_dibersihkan (karena tamu pernah masuk). Kamar baru → status sama dengan kamar lama.
    """
    if body.new_room_id == room_id:
        raise HTTPException(400, "Kamar tujuan sama dengan kamar asal")
    old = await db.rooms.find_one({"id": room_id})
    if not old:
        raise HTTPException(404, "Kamar asal tidak ditemukan")
    if old["status"] not in ("day_use", "menginap"):
        raise HTTPException(400, "Hanya kamar Day Use atau Menginap yang bisa dipindahkan")
    new = await db.rooms.find_one({"id": body.new_room_id})
    if not new:
        raise HTTPException(404, "Kamar tujuan tidak ditemukan")
    if new["status"] != "kosong":
        raise HTTPException(400, f"Kamar tujuan tidak kosong (status: {new['status']})")
    new_status = old["status"]
    new_info = dict(old.get("info") or {})
    # update kamar baru
    await db.rooms.update_one({"id": new["id"]}, {"$set": {"status": new_status, "info": new_info}})
    # update kamar lama
    await db.rooms.update_one({"id": old["id"]}, {"$set": {"status": "perlu_dibersihkan", "info": {}}})
    # update active checkin jika day_use
    if old["status"] == "day_use":
        ci = await db.checkins.find_one({"room_id": old["id"], "status": "aktif"})
        if ci:
            await db.checkins.update_one(
                {"id": ci["id"]},
                {"$set": {
                    "room_id": new["id"], "room_nomor": new["nomor"], "room_tipe": new["tipe"],
                    "moved_from_room_id": old["id"], "moved_from_room_nomor": old["nomor"],
                    "moved_at": now_iso(), "moved_by": user["nama"],
                    "move_reason": body.alasan or "",
                }}
            )
    # housekeeping log untuk kamar lama
    await db.housekeeping_log.insert_one({
        "id": str(uuid.uuid4()), "room_id": old["id"], "room_nomor": old["nomor"],
        "tanggal": now_iso(), "jam_mulai": None, "jam_selesai": None,
        "petugas": "", "catatan": f"Pindah tamu ke kamar {new['nomor']}", "status": "pending",
    })
    await log_activity(
        user, "move_room",
        f"Pindah tamu kamar {old['nomor']} → kamar {new['nomor']} ({body.alasan or 'tanpa alasan'})",
        entity=f"{old['nomor']}->{new['nomor']}"
    )
    return {"ok": True, "from": old["nomor"], "to": new["nomor"], "status": new_status}

# ---- Check-in / Check-out ----
SERVICE_FEE_PCT = 0.03  # 3% service fee diaplikasikan ke checkin & booking

def calc_tagihan(tarif_dasar: int, jam_checkin: datetime, jam_checkout: datetime, overtime_manual: Optional[int] = None):
    delta = jam_checkout - jam_checkin
    total_jam = delta.total_seconds() / 3600.0
    base_hours = 6
    if overtime_manual is not None:
        overtime_hours = max(0, overtime_manual)
    else:
        overtime_hours = max(0, int(-(-(total_jam - base_hours) // 1))) if total_jam > base_hours else 0
    biaya_tambahan = overtime_hours * 20000
    subtotal = tarif_dasar + biaya_tambahan
    service_fee = round(subtotal * SERVICE_FEE_PCT)
    total = subtotal + service_fee
    return {
        "durasi_jam": round(total_jam, 2),
        "overtime_jam": overtime_hours,
        "biaya_tambahan": biaya_tambahan,
        "tarif_dasar": tarif_dasar,
        "subtotal": subtotal,
        "service_fee": service_fee,
        "service_fee_pct": SERVICE_FEE_PCT,
        "total": total,
    }


@api.post("/checkins")
async def create_checkin(body: CheckinCreate, user: dict = Depends(get_current_user)):
    r = await db.rooms.find_one({"id": body.room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, "Kamar belum tersedia dan tidak dapat digunakan untuk check-in.")
    # Save / upsert guest
    guest = None
    if body.no_identitas:
        guest = await db.guests.find_one({"no_identitas": body.no_identitas})
    if not guest and body.no_hp:
        guest = await db.guests.find_one({"no_hp": body.no_hp})
    if guest:
        await db.guests.update_one({"id": guest["id"]}, {
            "$set": {
                "nama": body.nama_tamu,
                "no_hp": body.no_hp,
                "kendaraan": body.kendaraan,
                "last_visit": now_iso(),
            },
            "$inc": {"total_kunjungan": 1},
        })
        guest_id = guest["id"]
    else:
        guest_id = str(uuid.uuid4())
        await db.guests.insert_one({
            "id": guest_id,
            "nama": body.nama_tamu,
            "no_hp": body.no_hp,
            "no_identitas": body.no_identitas,
            "kendaraan": body.kendaraan,
            "total_kunjungan": 1,
            "last_visit": now_iso(),
            "created_at": now_iso(),
        })
    # parse jam_checkin
    jam_ci_iso = now_iso()
    if body.jam_checkin:
        try:
            d = datetime.fromisoformat(body.jam_checkin.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            jam_ci_iso = d.astimezone(timezone.utc).isoformat()
        except Exception:
            raise HTTPException(400, "Format jam check-in tidak valid")
    # number generator
    trx_no = f"CI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    doc = {
        "id": str(uuid.uuid4()),
        "trx_no": trx_no,
        "guest_id": guest_id,
        "nama_tamu": body.nama_tamu,
        "no_hp": body.no_hp,
        "no_identitas": body.no_identitas,
        "kendaraan": body.kendaraan,
        "jumlah_tamu": body.jumlah_tamu,
        "room_id": body.room_id,
        "room_nomor": r["nomor"],
        "room_tipe": r["tipe"],
        "tarif_dasar": r["tarif"],
        "jam_checkin": jam_ci_iso,
        "jam_checkout": None,
        "durasi_jam": 0,
        "overtime_jam": 0,
        "biaya_tambahan": 0,
        "total": 0,
        "status": "aktif",
        "catatan": body.catatan,
        "foto_identitas_url": body.foto_identitas_url or "",
        "pembayaran": [],
        "petugas_checkin": user["nama"],
        "petugas_checkin_id": user["id"],
        "created_at": now_iso(),
    }
    await db.checkins.insert_one(doc)
    await db.rooms.update_one({"id": body.room_id}, {"$set": {"status": "day_use", "info": {"checkin_id": doc["id"], "nama_tamu": body.nama_tamu}}})
    await log_activity(user, "checkin", f"Check-in {body.nama_tamu} ke kamar {r['nomor']}", entity=r["nomor"])
    doc.pop("_id", None)
    return doc

@api.get("/checkins")
async def list_checkins(
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = from_date
        if to_date: rng["$lte"] = to_date
        q["jam_checkin"] = rng
    items = await db.checkins.find(q, {"_id": 0}).sort("jam_checkin", -1).to_list(1000)
    return items

@api.get("/checkins/{checkin_id}")
async def get_checkin(checkin_id: str, user: dict = Depends(get_current_user)):
    c = await db.checkins.find_one({"id": checkin_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Check-in tidak ditemukan")
    if c["status"] == "aktif":
        now = datetime.now(timezone.utc)
        ci = datetime.fromisoformat(c["jam_checkin"])
        calc = calc_tagihan(c["tarif_dasar"], ci, now)
        c["preview"] = calc
    return c

@api.post("/checkins/{checkin_id}/checkout")
async def checkout(checkin_id: str, body: CheckoutIn, user: dict = Depends(get_current_user)):
    c = await db.checkins.find_one({"id": checkin_id})
    if not c:
        raise HTTPException(404, "Check-in tidak ditemukan")
    if c["status"] != "aktif":
        raise HTTPException(400, "Check-in sudah selesai")
    now = datetime.now(timezone.utc)
    if body.jam_checkout:
        try:
            d = datetime.fromisoformat(body.jam_checkout.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            now = d.astimezone(timezone.utc)
        except Exception:
            raise HTTPException(400, "Format jam check-out tidak valid")
    ci = datetime.fromisoformat(c["jam_checkin"])
    if now < ci:
        raise HTTPException(400, "Jam check-out tidak boleh sebelum jam check-in")
    calc = calc_tagihan(c["tarif_dasar"], ci, now, body.overtime_manual)
    total_bayar = sum(int(p.get("jumlah", 0)) for p in body.pembayaran)
    if total_bayar < calc["total"]:
        raise HTTPException(400, f"Total pembayaran kurang. Diperlukan Rp{calc['total']:,}".replace(",", "."))
    updates = {
        "jam_checkout": now.isoformat(),
        "durasi_jam": calc["durasi_jam"],
        "overtime_jam": calc["overtime_jam"],
        "biaya_tambahan": calc["biaya_tambahan"],
        "subtotal": calc["subtotal"],
        "service_fee": calc["service_fee"],
        "total": calc["total"],
        "pembayaran": body.pembayaran,
        "status": "selesai",
        "petugas_checkout": user["nama"],
        "petugas_checkout_id": user["id"],
        "catatan_checkout": body.catatan,
    }
    await db.checkins.update_one({"id": checkin_id}, {"$set": updates})
    await db.rooms.update_one({"id": c["room_id"]}, {"$set": {"status": "perlu_dibersihkan", "info": {}}})
    # housekeeping log
    await db.housekeeping_log.insert_one({
        "id": str(uuid.uuid4()),
        "room_id": c["room_id"],
        "room_nomor": c["room_nomor"],
        "tanggal": now.isoformat(),
        "jam_checkout": now.isoformat(),
        "jam_mulai": None,
        "jam_selesai": None,
        "petugas": "",
        "catatan": "",
        "status": "pending",
    })
    if c.get("guest_id"):
        await db.guests.update_one({"id": c["guest_id"]}, {"$inc": {"total_transaksi": calc["total"]}})
    await log_activity(user, "checkout", f"Check-out {c['nama_tamu']} kamar {c['room_nomor']}, total Rp{calc['total']:,}".replace(",", "."), entity=c["room_nomor"])
    res = {**c, **updates}
    res.pop("_id", None)
    return res

# ---- Guests ----
@api.get("/guests")
async def list_guests(q: Optional[str] = None, user: dict = Depends(get_current_user)):
    query: Dict[str, Any] = {}
    if q:
        query = {"$or": [
            {"nama": {"$regex": q, "$options": "i"}},
            {"no_hp": {"$regex": q, "$options": "i"}},
            {"no_identitas": {"$regex": q, "$options": "i"}},
        ]}
    items = await db.guests.find(query, {"_id": 0}).sort("last_visit", -1).to_list(500)
    return items

@api.get("/guests/{guest_id}/history")
async def guest_history(guest_id: str, user: dict = Depends(get_current_user)):
    items = await db.checkins.find({"guest_id": guest_id}, {"_id": 0}).sort("jam_checkin", -1).to_list(500)
    return items

# ---- Products / Inventory ----
@api.get("/products")
async def list_products(kategori: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {}
    if kategori: q["kategori"] = kategori
    items = await db.products.find(q, {"_id": 0}).sort("nama", 1).to_list(500)
    return items

@api.post("/products")
async def create_product(body: ProductCreate, user: dict = Depends(require_owner)):
    if await db.products.find_one({"kode": body.kode}):
        raise HTTPException(400, "Kode produk sudah ada")
    doc = {"id": str(uuid.uuid4()), **body.model_dump(), "created_at": now_iso()}
    await db.products.insert_one(doc)
    await log_activity(user, "create_product", f"Tambah produk {body.nama}")
    doc.pop("_id", None)
    return doc

@api.put("/products/{pid}")
async def update_product(pid: str, body: ProductUpdate, user: dict = Depends(require_owner)):
    p = await db.products.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Produk tidak ditemukan")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await db.products.update_one({"id": pid}, {"$set": updates})
    await log_activity(user, "update_product", f"Update produk {p['nama']}")
    return {"ok": True}

@api.delete("/products/{pid}")
async def delete_product(pid: str, user: dict = Depends(require_owner)):
    p = await db.products.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Produk tidak ditemukan")
    await db.products.delete_one({"id": pid})
    await log_activity(user, "delete_product", f"Hapus produk {p['nama']}")
    return {"ok": True}

@api.post("/products/{pid}/stock")
async def adjust_stock(pid: str, body: StockAdjust, user: dict = Depends(get_current_user)):
    p = await db.products.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Produk tidak ditemukan")
    new_stok = max(0, int(p.get("stok", 0)) + body.delta)
    await db.products.update_one({"id": pid}, {"$set": {"stok": new_stok}})
    await db.stock_log.insert_one({
        "id": str(uuid.uuid4()),
        "product_id": pid,
        "product_nama": p["nama"],
        "delta": body.delta,
        "catatan": body.catatan,
        "user": user["nama"],
        "timestamp": now_iso(),
    })
    await log_activity(user, "adjust_stock", f"Stok {p['nama']} {body.delta:+d}")
    return {"ok": True, "stok": new_stok}

# ---- Kasir / Transactions ----
@api.post("/kasir")
async def create_kasir(body: KasirCreate, user: dict = Depends(get_current_user)):
    if not body.items:
        raise HTTPException(400, "Keranjang kosong")
    rows = []
    subtotal = 0
    for it in body.items:
        p = await db.products.find_one({"id": it.product_id})
        if not p:
            raise HTTPException(400, f"Produk tidak ditemukan")
        if it.qty <= 0:
            raise HTTPException(400, "Qty harus > 0")
        if p["kategori"] != "laundry" and int(p.get("stok", 0)) < it.qty:
            raise HTTPException(400, f"Stok {p['nama']} tidak cukup (tersisa {p.get('stok',0)})")
        line = it.qty * int(p["harga"])
        subtotal += line
        rows.append({
            "product_id": p["id"], "kode": p["kode"], "nama": p["nama"],
            "kategori": p["kategori"], "harga": p["harga"], "qty": it.qty, "subtotal": line,
        })
    diskon = max(0, int(body.diskon or 0))
    total = max(0, subtotal - diskon)
    total_bayar = sum(int(p.get("jumlah", 0)) for p in body.pembayaran)
    if total_bayar < total:
        raise HTTPException(400, f"Pembayaran kurang Rp{total - total_bayar:,}".replace(",", "."))
    trx_no = f"KS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    doc = {
        "id": str(uuid.uuid4()),
        "trx_no": trx_no,
        "items": rows,
        "subtotal": subtotal,
        "diskon": diskon,
        "total": total,
        "catatan": body.catatan,
        "pembayaran": body.pembayaran,
        "petugas": user["nama"],
        "petugas_id": user["id"],
        "timestamp": now_iso(),
    }
    await db.kasir.insert_one(doc)
    # decrement stok
    for r in rows:
        if r["kategori"] != "laundry":
            await db.products.update_one({"id": r["product_id"]}, {"$inc": {"stok": -r["qty"]}})
    await log_activity(user, "kasir", f"Transaksi kasir {trx_no} total Rp{total:,}".replace(",", "."))
    doc.pop("_id", None)
    return doc

@api.get("/kasir")
async def list_kasir(from_date: Optional[str] = None, to_date: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = from_date
        if to_date: rng["$lte"] = to_date
        q["timestamp"] = rng
    items = await db.kasir.find(q, {"_id": 0}).sort("timestamp", -1).to_list(1000)
    return items

# ---- Expenses ----
@api.post("/expenses")
async def create_expense(body: ExpenseCreate, user: dict = Depends(get_current_user)):
    doc = {
        "id": str(uuid.uuid4()),
        "tanggal": body.tanggal or now_iso(),
        "kategori": body.kategori,
        "deskripsi": body.deskripsi,
        "nominal": body.nominal,
        "user": user["nama"],
        "user_id": user["id"],
        "created_at": now_iso(),
    }
    await db.expenses.insert_one(doc)
    await log_activity(user, "expense", f"Pengeluaran {body.kategori} Rp{body.nominal:,}".replace(",", "."))
    doc.pop("_id", None)
    return doc

@api.get("/expenses")
async def list_expenses(from_date: Optional[str] = None, to_date: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = from_date
        if to_date: rng["$lte"] = to_date
        q["tanggal"] = rng
    items = await db.expenses.find(q, {"_id": 0}).sort("tanggal", -1).to_list(1000)
    return items

@api.delete("/expenses/{eid}")
async def delete_expense(eid: str, user: dict = Depends(require_owner)):
    await db.expenses.delete_one({"id": eid})
    await log_activity(user, "delete_expense", f"Hapus pengeluaran {eid}")
    return {"ok": True}

# ---- Bookings ----
def _parse_iso(s: str, field: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        raise HTTPException(400, f"Format {field} tidak valid")

@api.post("/bookings")
async def create_booking(body: BookingCreate, user: dict = Depends(get_current_user)):
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "Tipe booking tidak valid")
    r = await db.rooms.find_one({"id": body.room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    start = _parse_iso(body.jam_mulai, "jam_mulai")
    if body.jam_selesai:
        end = _parse_iso(body.jam_selesai, "jam_selesai")
    else:
        if body.tipe == "menginap":
            raise HTTPException(400, "Booking menginap wajib mengisi jam_selesai")
        end = start + timedelta(hours=6)
    if end <= start:
        raise HTTPException(400, "Jam selesai harus setelah jam mulai")
    overlap = await db.bookings.find_one({
        "room_id": body.room_id, "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": end.isoformat()},
        "jam_selesai": {"$gt": start.isoformat()},
    })
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")
    kode = f"BK-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    # Hitung estimasi tagihan (tarif kamar + 3% service fee). Untuk menginap, durasi jam dipakai sebagai kelipatan 6 jam.
    subtotal = int(r["tarif"])
    if body.tipe == "menginap":
        hours = max(6, int((end - start).total_seconds() / 3600))
        # menginap: tarif per hari (24 jam) — pakai ceil(hours/24) hari × tarif harian (tarif kamar × 4 untuk menginap)
        # Sederhanakan: tarif × ceil(hours/24)
        days = max(1, -(-hours // 24))
        subtotal = int(r["tarif"]) * days
    service_fee = round(subtotal * SERVICE_FEE_PCT)
    total = subtotal + service_fee
    doc = {
        "id": str(uuid.uuid4()), "kode": kode,
        "room_id": body.room_id, "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tipe": body.tipe, "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
        "no_identitas": body.no_identitas, "kendaraan": body.kendaraan, "jumlah_tamu": body.jumlah_tamu,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": body.catatan, "status": "aktif",
        "subtotal": subtotal, "service_fee": service_fee, "total": total,
        "source": "walk_in",
        "created_at": now_iso(), "created_by": user["nama"],
    }
    await db.bookings.insert_one(doc)
    await log_activity(user, "create_booking", f"Booking {body.tipe} kamar {r['nomor']} untuk {body.nama_tamu}", entity=r["nomor"])
    doc.pop("_id", None)
    return doc

@api.get("/bookings")
async def list_bookings(status: Optional[str] = None, tipe: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if status: q["status"] = status
    if tipe: q["tipe"] = tipe
    items = await db.bookings.find(q, {"_id": 0}).sort("jam_mulai", 1).to_list(1000)
    return items

@api.get("/reports/booking-widgets")
async def booking_widgets(user: dict = Depends(get_current_user)):
    """Widget statistik booking untuk Dashboard."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    # Booking hari ini = jam_mulai dalam rentang hari ini
    today_bk = await db.bookings.count_documents({
        "jam_mulai": {"$gte": today_start.isoformat(), "$lt": today_end.isoformat()},
        "status": {"$in": ["aktif", "booking_pending", "booking_paid", "checked_in"]},
    })
    pending_count = await db.bookings.count_documents({"status": "booking_pending"})
    paid_count = await db.bookings.count_documents({"status": "booking_paid"})
    # Pendapatan online = sum total dari booking_paid bulan ini
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    online_paid = await db.bookings.find({
        "source": "online", "payment_status": "paid",
        "paid_at": {"$gte": month_start.isoformat()},
    }, {"_id": 0, "total": 1, "amount_due": 1}).to_list(1000)
    pendapatan_online = sum(int(b.get("amount_due") or b.get("total", 0)) for b in online_paid)
    # Total semua transaksi midtrans (lifetime). gross_amount disimpan sebagai string "61800.00"
    mt_total = await db.payment_log.aggregate([
        {"$match": {"transaction_status": {"$in": ["settlement", "capture"]}}},
        {"$group": {"_id": None, "sum": {"$sum": {"$toDouble": "$gross_amount"}}, "count": {"$sum": 1}}},
    ]).to_list(1)
    mt_sum = int(mt_total[0]["sum"]) if mt_total else 0
    mt_count = mt_total[0]["count"] if mt_total else 0
    # Walk-in vs Online (bulan ini)
    online_bulan = await db.bookings.count_documents({
        "source": "online", "created_at": {"$gte": month_start.isoformat()},
    })
    # Walk-in = check-ins langsung dari dashboard (tanpa booking online) bulan ini
    walk_bulan = await db.checkins.count_documents({
        "jam_checkin": {"$gte": month_start.isoformat()},
    })
    return {
        "booking_hari_ini": today_bk,
        "booking_pending": pending_count,
        "booking_paid": paid_count,
        "pendapatan_online_bulan": pendapatan_online,
        "midtrans_total_count": mt_count,
        "midtrans_total_sum": mt_sum,
        "booking_online_bulan": online_bulan,
        "booking_walkin_bulan": walk_bulan,
    }

class CancelWithFeeBody(BaseModel):
    alasan: Optional[str] = ""

@api.post("/bookings/{bid}/cancel-with-fee")
async def cancel_with_fee(bid: str, body: CancelWithFeeBody, user: dict = Depends(get_current_user)):
    """Cancel booking dengan biaya pembatalan 10% (online dan walk-in).
    - booking_paid: refund = paid - 10% fee. Fee diakui sebagai revenue.
    - booking_pending / aktif: no refund (belum ada uang masuk), 10% fee dicatat sebagai piutang/audit.
    Return: {refund_amount, fee, original_total, status}
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, f"Booking tidak dapat dibatalkan (status: {b.get('status')})")
    total = int(b.get("total") or 0)
    fee = round(total * 0.10) if total else 0
    paid = int(b.get("amount_due") or 0)
    refund = max(0, paid - fee) if b.get("status") == "booking_paid" else 0
    now = now_iso()
    update_fields = {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": user["nama"],
        "cancel_reason": body.alasan, "cancel_fee": fee, "refund_amount": refund,
    }
    if b.get("status") == "booking_paid":
        update_fields["payment_status"] = "refunded" if refund > 0 else "forfeited"
    await db.bookings.update_one({"id": bid}, {"$set": update_fields})
    detail = (
        f"Cancel booking {b['kode']}: total Rp{total:,}, fee Rp{fee:,}, "
        f"{'refund Rp' + format(refund, ',') if refund > 0 else 'tidak ada refund'}"
    ).replace(",", ".")
    await log_activity(user, "cancel_with_fee", detail, entity=b.get("room_nomor", ""))
    return {
        "ok": True, "refund_amount": refund, "fee": fee, "original_paid": paid,
        "original_total": total, "booking_kode": b["kode"], "previous_status": b.get("status"),
    }

class NoShowBody(BaseModel):
    alasan: Optional[str] = ""

class ManualMarkPaidBody(BaseModel):
    alasan: Optional[str] = ""
    metode: Optional[str] = "transfer_manual"  # transfer_manual / cash / etc
    nominal: Optional[int] = None  # if not provided, use total

class CollectBalanceBody(BaseModel):
    nominal: int
    metode: str = "cash"  # cash / qris

@api.post("/bookings/{bid}/collect-balance")
async def collect_balance(bid: str, body: CollectBalanceBody, user: dict = Depends(get_current_user)):
    """Collect sisa pelunasan (untuk DP 50% yang belum lunas).
    Tambah amount_due dengan nominal yang diterima, catat di payment_log.
    """
    if body.nominal <= 0:
        raise HTTPException(400, "Nominal harus > 0")
    if body.metode not in ("cash", "qris"):
        raise HTTPException(400, "Metode harus cash atau qris")
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") not in ("booking_paid", "checked_in"):
        raise HTTPException(400, f"Hanya booking_paid/checked_in yang bisa di-collect (status: {b.get('status')})")
    total = int(b.get("total") or 0)
    paid_now = int(b.get("amount_due") or 0)
    sisa = max(0, total - paid_now)
    if sisa <= 0:
        raise HTTPException(400, "Booking sudah lunas, tidak ada sisa")
    if body.nominal > sisa:
        raise HTTPException(400, f"Nominal terlalu besar. Sisa: Rp{sisa:,}".replace(",", "."))
    new_paid = paid_now + body.nominal
    now = now_iso()
    await db.bookings.update_one({"id": bid}, {"$set": {
        "amount_due": new_paid, "updated_at": now,
    }})
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "booking_id": b["id"], "booking_kode": b["kode"],
        "order_id": f"COLLECT-{b['kode']}-{uuid.uuid4().hex[:4].upper()}",
        "gross_amount": str(body.nominal), "payment_option": "collect_balance",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": body.metode, "fraud_status": None,
        "created_at": now, "updated_at": now,
        "collected_by": user["nama"],
    })
    await log_activity(user, "collect_balance",
                       f"Collect sisa pelunasan booking {b['kode']}: Rp{body.nominal:,} via {body.metode} (total terbayar Rp{new_paid:,}/Rp{total:,})".replace(",", "."),
                       entity=b.get("room_nomor", ""))
    return {"ok": True, "amount_collected": body.nominal, "total_paid": new_paid, "remaining": max(0, total - new_paid), "booking_kode": b["kode"]}

@api.post("/bookings/{bid}/checkin")
async def checkin_from_booking(bid: str, user: dict = Depends(get_current_user)):
    """Check-in tamu dari booking (booking_paid → checked_in).
    Membuat record di db.checkins (status=aktif), update room → day_use, ubah booking status → checked_in.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") != "booking_paid":
        raise HTTPException(400, f"Hanya booking lunas yang bisa di-check-in (status: {b.get('status')})")
    r = await db.rooms.find_one({"id": b["room_id"]})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, f"Kamar {r['nomor']} sedang dipakai (status: {r['status']})")
    # Buat checkin doc
    trx_no = f"CI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    total = int(b.get("total") or 0)
    paid = int(b.get("amount_due") or 0)
    sisa = max(0, total - paid)
    now = now_iso()
    ci_doc = {
        "id": str(uuid.uuid4()),
        "trx_no": trx_no,
        "guest_id": None,
        "nama_tamu": b.get("nama_tamu", ""),
        "no_hp": b.get("no_hp", ""),
        "no_identitas": b.get("no_identitas", ""),
        "kendaraan": b.get("kendaraan", ""),
        "jumlah_tamu": b.get("jumlah_tamu", 1),
        "room_id": b["room_id"], "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tarif_dasar": int(r["tarif"]),
        "jam_checkin": now, "jam_checkout": None,
        "durasi_jam": 0, "overtime_jam": 0, "biaya_tambahan": 0, "total": 0,
        "status": "aktif",
        "catatan": f"Dari booking {b['kode']}. Sudah dibayar Rp{paid:,}/Rp{total:,}. Sisa Rp{sisa:,}".replace(",", "."),
        "foto_identitas_url": "",
        "pembayaran": [],
        "from_booking_id": b["id"], "from_booking_kode": b["kode"],
        "booking_paid": paid, "booking_remaining": sisa,
        "petugas_checkin": user["nama"], "petugas_checkin_id": user["id"],
        "created_at": now,
    }
    await db.checkins.insert_one(ci_doc)
    await db.rooms.update_one({"id": b["room_id"]}, {"$set": {
        "status": "day_use", "info": {"checkin_id": ci_doc["id"], "nama_tamu": b.get("nama_tamu", "")},
    }})
    await db.bookings.update_one({"id": bid}, {"$set": {
        "status": "checked_in", "checked_in_at": now, "checked_in_by": user["nama"],
        "checkin_id": ci_doc["id"],
    }})
    await log_activity(user, "checkin_from_booking",
                       f"Check-in tamu {b.get('nama_tamu','')} dari booking {b['kode']} ke kamar {r['nomor']} (sisa Rp{sisa:,})".replace(",", "."),
                       entity=r["nomor"])
    return {"ok": True, "checkin_id": ci_doc["id"], "trx_no": trx_no, "booking_kode": b["kode"], "remaining": sisa}


@api.post("/bookings/{bid}/mark-paid-manual")
async def mark_paid_manual(bid: str, body: ManualMarkPaidBody, user: dict = Depends(get_current_user)):
    """Staff verifikasi pembayaran manual (transfer rekening). Ubah booking_pending → booking_paid.
    Hanya untuk staff (auth required). Catat di audit + payment_log.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") != "booking_pending":
        raise HTTPException(400, f"Hanya booking_pending yang dapat dikonfirmasi manual (status: {b.get('status')})")
    nominal = body.nominal if body.nominal else int(b.get("total", 0))
    now = now_iso()
    await db.bookings.update_one({"id": bid}, {"$set": {
        "status": "booking_paid", "payment_status": "paid",
        "amount_due": nominal, "payment_type": body.metode,
        "paid_at": now, "manual_paid_by": user["nama"], "manual_paid_reason": body.alasan,
        "updated_at": now,
    }})
    await db.payment_log.insert_one({
        "id": str(uuid.uuid4()), "booking_id": b["id"], "booking_kode": b["kode"],
        "order_id": f"MANUAL-{b['kode']}", "transaction_token": None, "redirect_url": None,
        "gross_amount": str(nominal), "payment_option": "manual",
        "transaction_status": "settlement", "status_code": "200",
        "payment_type": body.metode, "fraud_status": None,
        "created_at": now, "updated_at": now,
        "manual_verified_by": user["nama"], "manual_verified_reason": body.alasan,
    })
    await log_activity(user, "manual_paid",
                       f"Konfirmasi manual booking {b['kode']} kamar {b.get('room_nomor','')}: Rp{nominal:,} via {body.metode}".replace(",", "."),
                       entity=b.get("room_nomor", ""))
    return {"ok": True, "booking_kode": b["kode"], "amount": nominal, "status": "booking_paid"}

@api.get("/public/bank-accounts")
async def public_bank_accounts():
    """Daftar rekening bank untuk transfer manual (tampil di halaman publik /book)."""
    accounts = [
        {"bank": "BRI", "nomor": os.environ.get("BANK_BRI_NUMBER", "464001008162533"),
         "atas_nama": os.environ.get("BANK_BRI_NAME", "Pelangi Homestay")},
    ]
    return {"accounts": accounts, "instruksi": "Transfer sesuai nominal yang tertera, kemudian klik tombol 'Saya Sudah Transfer' untuk verifikasi oleh resepsionis."}

@api.get("/reports/cancellation-revenue")
async def cancellation_revenue(from_date: str, to_date: str, user: dict = Depends(get_current_user)):
    """Pendapatan dari cancel fee (10% × total) + no-show retention (amount_due booking_paid yang jadi no_show).
    from_date/to_date: YYYY-MM-DD (inclusive).
    Returns: { cancel_fees_total, no_show_total, grand_total, by_day:[...], items:[...] }
    """
    try:
        d_from = datetime.fromisoformat(from_date).replace(hour=0, minute=0, second=0, microsecond=0)
        d_to = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59, microsecond=999999)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    cancels = await db.bookings.find({
        "status": "cancelled", "cancel_fee": {"$gt": 0},
        "cancelled_at": {"$gte": d_from.isoformat(), "$lte": d_to.isoformat()},
    }, {"_id": 0}).to_list(2000)
    no_shows = await db.bookings.find({
        "status": "no_show",
        "no_show_at": {"$gte": d_from.isoformat(), "$lte": d_to.isoformat()},
    }, {"_id": 0}).to_list(2000)
    cancel_total = sum(int(b.get("cancel_fee") or 0) for b in cancels)
    noshow_total = sum(int(b.get("amount_due") or 0) for b in no_shows)
    # group per hari
    by_day: Dict[str, Dict[str, int]] = {}
    for b in cancels:
        day = (b.get("cancelled_at") or "")[:10]
        by_day.setdefault(day, {"cancel_fee": 0, "no_show": 0})
        by_day[day]["cancel_fee"] += int(b.get("cancel_fee") or 0)
    for b in no_shows:
        day = (b.get("no_show_at") or "")[:10]
        by_day.setdefault(day, {"cancel_fee": 0, "no_show": 0})
        by_day[day]["no_show"] += int(b.get("amount_due") or 0)
    chart = sorted([{"tanggal": k, **v, "total": v["cancel_fee"] + v["no_show"]} for k, v in by_day.items()], key=lambda x: x["tanggal"])
    items = []
    for b in cancels:
        items.append({"tipe": "cancel", "kode": b["kode"], "room_nomor": b.get("room_nomor"),
                      "nama_tamu": b.get("nama_tamu"), "tanggal": (b.get("cancelled_at") or "")[:19],
                      "nominal": int(b.get("cancel_fee") or 0),
                      "alasan": b.get("cancel_reason") or "",
                      "petugas": b.get("cancelled_by") or "",
                      "source": b.get("source") or "walk_in"})
    for b in no_shows:
        items.append({"tipe": "no_show", "kode": b["kode"], "room_nomor": b.get("room_nomor"),
                      "nama_tamu": b.get("nama_tamu"), "tanggal": (b.get("no_show_at") or "")[:19],
                      "nominal": int(b.get("amount_due") or 0),
                      "alasan": b.get("no_show_reason") or "",
                      "petugas": b.get("no_show_by") or "",
                      "source": b.get("source") or "walk_in"})
    items.sort(key=lambda x: x["tanggal"], reverse=True)
    return {
        "from_date": from_date, "to_date": to_date,
        "cancel_fees_total": cancel_total,
        "no_show_total": noshow_total,
        "grand_total": cancel_total + noshow_total,
        "cancel_count": len(cancels), "no_show_count": len(no_shows),
        "by_day": chart, "items": items,
    }


@api.post("/bookings/{bid}/no-show")
async def mark_no_show(bid: str, body: NoShowBody, user: dict = Depends(get_current_user)):
    """Tandai booking sebagai NO-SHOW (tamu tidak datang).
    Hanya berlaku untuk booking_paid. DP/Full payment TIDAK direfund, tetap masuk pembukuan sebagai revenue.
    """
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b.get("status") != "booking_paid":
        raise HTTPException(400, f"Hanya booking lunas yang dapat ditandai no-show (status: {b.get('status')})")
    paid = int(b.get("amount_due") or 0)
    now = now_iso()
    await db.bookings.update_one({"id": bid}, {"$set": {
        "status": "no_show", "payment_status": "kept",
        "no_show_at": now, "no_show_by": user["nama"], "no_show_reason": body.alasan,
    }})
    await log_activity(user, "no_show",
                       f"No-show booking {b['kode']} kamar {b.get('room_nomor','')}: Rp{paid:,} tetap masuk pembukuan".replace(",", "."),
                       entity=b.get("room_nomor", ""))
    return {"ok": True, "amount_retained": paid, "booking_kode": b["kode"]}


@api.get("/bookings/availability")
async def booking_availability(room_id: str, from_date: str, days: int = 14,
                               user: dict = Depends(get_current_user)):
    """Cek ketersediaan kamar per hari (zona lokal +07:00 / WIB)
    untuk menampilkan saran tanggal alternatif jika kamar penuh.
    Returns: { from_date, room_id, slots: [{date, available, reason}] }
    """
    r = await db.rooms.find_one({"id": room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    days = max(1, min(days, 60))
    try:
        base = datetime.fromisoformat(from_date)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(400, "from_date harus YYYY-MM-DD")
    # Ambil semua booking aktif untuk kamar ini dalam window from..from+days
    end_window = base + timedelta(days=days)
    bks = await db.bookings.find({
        "room_id": room_id,
        "status": {"$in": ["aktif", "booking_paid", "booking_pending"]},
        "jam_mulai": {"$lt": end_window.isoformat()},
        "jam_selesai": {"$gt": base.isoformat()},
    }, {"_id": 0}).to_list(500)
    slots = []
    for i in range(days):
        d = base + timedelta(days=i)
        d_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
        d_end = d_start + timedelta(days=1)
        conflict = None
        for b in bks:
            bs = datetime.fromisoformat(b["jam_mulai"])
            be = datetime.fromisoformat(b["jam_selesai"])
            if bs < d_end and be > d_start:
                conflict = b
                break
        slots.append({
            "date": d.strftime("%Y-%m-%d"),
            "available": conflict is None,
            "reason": f"Booking {conflict['kode']} ({conflict.get('tipe','')})" if conflict else "",
        })
    return {"room_id": room_id, "room_nomor": r["nomor"], "room_tipe": r["tipe"], "from_date": from_date, "days": days, "slots": slots}

@api.put("/bookings/{bid}")
async def update_booking(bid: str, body: BookingCreate, user: dict = Depends(get_current_user)):
    b = await db.bookings.find_one({"id": bid})
    if not b:
        raise HTTPException(404, "Booking tidak ditemukan")
    if b["status"] not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, "Hanya booking aktif/pending/paid yang dapat di-reschedule")
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "Tipe booking tidak valid")
    r = await db.rooms.find_one({"id": body.room_id})
    if not r:
        raise HTTPException(404, "Kamar tidak ditemukan")
    start = _parse_iso(body.jam_mulai, "jam_mulai")
    if body.jam_selesai:
        end = _parse_iso(body.jam_selesai, "jam_selesai")
    else:
        if body.tipe == "menginap":
            raise HTTPException(400, "Booking menginap wajib mengisi jam_selesai")
        end = start + timedelta(hours=6)
    if end <= start:
        raise HTTPException(400, "Jam selesai harus setelah jam mulai")
    overlap = await db.bookings.find_one({
        "id": {"$ne": bid},
        "room_id": body.room_id, "status": {"$in": ["aktif", "booking_pending", "booking_paid"]},
        "jam_mulai": {"$lt": end.isoformat()},
        "jam_selesai": {"$gt": start.isoformat()},
    })
    if overlap:
        raise HTTPException(400, f"Kamar sudah dibooking pada rentang ini ({overlap.get('kode')})")
    update_fields = {
        "room_id": body.room_id, "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tipe": body.tipe, "nama_tamu": body.nama_tamu, "no_hp": body.no_hp,
        "no_identitas": body.no_identitas, "kendaraan": body.kendaraan, "jumlah_tamu": body.jumlah_tamu,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": body.catatan, "updated_at": now_iso(), "updated_by": user["nama"],
    }
    await db.bookings.update_one({"id": bid}, {"$set": update_fields})
    await log_activity(user, "update_booking", f"Edit booking {b['kode']} kamar {r['nomor']} untuk {body.nama_tamu}", entity=r["nomor"])
    doc = await db.bookings.find_one({"id": bid}, {"_id": 0})
    return doc

@api.delete("/bookings/{bid}")
async def cancel_booking(bid: str, user: dict = Depends(get_current_user)):
    b = await db.bookings.find_one({"id": bid})
    if not b: raise HTTPException(404, "Booking tidak ditemukan")
    if b["status"] not in ("aktif", "booking_pending", "booking_paid"):
        raise HTTPException(400, "Booking sudah tidak dapat dibatalkan")
    await db.bookings.update_one({"id": bid}, {"$set": {"status": "cancelled", "cancelled_at": now_iso(), "cancelled_by": user["nama"]}})
    await log_activity(user, "cancel_booking", f"Batalkan booking {b['kode']} kamar {b['room_nomor']}")
    return {"ok": True}

@api.post("/bookings/{bid}/checkin")
async def checkin_booking(bid: str, user: dict = Depends(get_current_user)):
    b = await db.bookings.find_one({"id": bid})
    if not b: raise HTTPException(404, "Booking tidak ditemukan")
    if b["status"] != "aktif": raise HTTPException(400, "Booking tidak aktif")
    r = await db.rooms.find_one({"id": b["room_id"]})
    if not r: raise HTTPException(404, "Kamar tidak ditemukan")
    if r["status"] != "kosong":
        raise HTTPException(400, f"Kamar belum tersedia (status: {r['status']})")
    if b["tipe"] == "menginap":
        info = {
            "nama_tamu": b["nama_tamu"], "no_hp": b["no_hp"],
            "checkin_date": b["jam_mulai"], "checkout_date": b["jam_selesai"],
            "catatan": b.get("catatan", ""), "booking_id": b["id"],
        }
        await db.rooms.update_one({"id": r["id"]}, {"$set": {"status": "menginap", "info": info}})
        await db.bookings.update_one({"id": bid}, {"$set": {"status": "checked_in", "checked_in_at": now_iso()}})
        await log_activity(user, "checkin_booking_menginap", f"Aktivasi booking menginap {b['kode']} kamar {r['nomor']}", entity=r["nomor"])
        return {"ok": True, "tipe": "menginap"}
    # day_use
    guest = None
    if b.get("no_identitas"): guest = await db.guests.find_one({"no_identitas": b["no_identitas"]})
    if not guest and b.get("no_hp"): guest = await db.guests.find_one({"no_hp": b["no_hp"]})
    if guest:
        await db.guests.update_one({"id": guest["id"]}, {"$inc": {"total_kunjungan": 1}, "$set": {"last_visit": now_iso()}})
        guest_id = guest["id"]
    else:
        guest_id = str(uuid.uuid4())
        await db.guests.insert_one({
            "id": guest_id, "nama": b["nama_tamu"], "no_hp": b["no_hp"], "no_identitas": b["no_identitas"],
            "kendaraan": b["kendaraan"], "total_kunjungan": 1, "last_visit": now_iso(), "created_at": now_iso(),
        })
    trx_no = f"CI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    ci_doc = {
        "id": str(uuid.uuid4()), "trx_no": trx_no, "guest_id": guest_id,
        "nama_tamu": b["nama_tamu"], "no_hp": b["no_hp"], "no_identitas": b["no_identitas"],
        "kendaraan": b["kendaraan"], "jumlah_tamu": b["jumlah_tamu"],
        "room_id": r["id"], "room_nomor": r["nomor"], "room_tipe": r["tipe"],
        "tarif_dasar": r["tarif"], "jam_checkin": b["jam_mulai"],
        "jam_checkout": None, "durasi_jam": 0, "overtime_jam": 0, "biaya_tambahan": 0, "total": 0,
        "status": "aktif", "catatan": b.get("catatan", ""), "pembayaran": [],
        "booking_id": b["id"], "petugas_checkin": user["nama"], "petugas_checkin_id": user["id"],
        "created_at": now_iso(),
    }
    await db.checkins.insert_one(ci_doc)
    await db.rooms.update_one({"id": r["id"]}, {"$set": {"status": "day_use", "info": {"checkin_id": ci_doc["id"], "nama_tamu": b["nama_tamu"]}}})
    await db.bookings.update_one({"id": bid}, {"$set": {"status": "checked_in", "checked_in_at": now_iso(), "checkin_id": ci_doc["id"]}})
    await log_activity(user, "checkin_booking_dayuse", f"Aktivasi booking day-use {b['kode']} kamar {r['nomor']}", entity=r["nomor"])
    ci_doc.pop("_id", None)
    return {"ok": True, "tipe": "day_use", "checkin": ci_doc}



@api.get("/audit-log")
async def list_audit(limit: int = 200, user: dict = Depends(get_current_user)):
    items = await db.audit_log.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return items

# ---- Housekeeping ----
@api.get("/housekeeping")
async def list_housekeeping(user: dict = Depends(get_current_user)):
    items = await db.housekeeping_log.find({}, {"_id": 0}).sort("tanggal", -1).to_list(500)
    return items

# ---- Reports ----
@api.get("/reports/summary")
async def report_summary(user: dict = Depends(get_current_user)):
    today_iso = datetime.now(timezone.utc).date().isoformat()
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    # rooms
    rooms = await db.rooms.find({}, {"_id": 0}).to_list(500)
    counts = {"kosong": 0, "day_use": 0, "menginap": 0, "perlu_dibersihkan": 0, "maintenance": 0}
    for r in rooms:
        counts[r.get("status", "kosong")] = counts.get(r.get("status", "kosong"), 0) + 1
    # checkins today
    ci_today = await db.checkins.find({"jam_checkin": {"$gte": today_iso}}, {"_id": 0}).to_list(500)
    co_today = await db.checkins.find({"jam_checkout": {"$gte": today_iso}, "status": "selesai"}, {"_id": 0}).to_list(500)
    rev_room_today = sum(c.get("total", 0) for c in co_today)
    # kasir today / month
    kasir_today = await db.kasir.find({"timestamp": {"$gte": today_iso}}, {"_id": 0}).to_list(1000)
    rev_kasir_today = sum(k.get("total", 0) for k in kasir_today)
    rev_per_kat = {"makanan": 0, "minuman": 0, "laundry": 0}
    for k in kasir_today:
        for it in k.get("items", []):
            rev_per_kat[it["kategori"]] = rev_per_kat.get(it["kategori"], 0) + it["subtotal"]
    # month
    ci_month = await db.checkins.find({"jam_checkout": {"$gte": month_start}, "status": "selesai"}, {"_id": 0}).to_list(2000)
    kasir_month = await db.kasir.find({"timestamp": {"$gte": month_start}}, {"_id": 0}).to_list(2000)
    rev_month = sum(c.get("total", 0) for c in ci_month) + sum(k.get("total", 0) for k in kasir_month)
    # expenses
    exp_today = await db.expenses.find({"tanggal": {"$gte": today_iso}}, {"_id": 0}).to_list(500)
    exp_month = await db.expenses.find({"tanggal": {"$gte": month_start}}, {"_id": 0}).to_list(2000)
    total_exp_today = sum(e.get("nominal", 0) for e in exp_today)
    total_exp_month = sum(e.get("nominal", 0) for e in exp_month)
    return {
        "rooms": counts,
        "total_rooms": len(rooms),
        "tamu_hari_ini": len(ci_today),
        "checkout_hari_ini": len(co_today),
        "pendapatan_hari_ini": rev_room_today + rev_kasir_today,
        "pendapatan_kamar_hari_ini": rev_room_today,
        "pendapatan_kasir_hari_ini": rev_kasir_today,
        "pendapatan_per_kategori": rev_per_kat,
        "pendapatan_bulan_ini": rev_month,
        "pengeluaran_hari_ini": total_exp_today,
        "pengeluaran_bulan_ini": total_exp_month,
        "laba_bersih_bulan_ini": rev_month - total_exp_month,
    }

@api.get("/reports/daily")
async def report_daily(from_date: str = Query(...), to_date: str = Query(...),
                       user: dict = Depends(get_current_user)):
    """Return per-day revenue between dates (inclusive). Dates: YYYY-MM-DD."""
    start = from_date
    end = to_date + "T23:59:59"
    ci = await db.checkins.find({"jam_checkout": {"$gte": start, "$lte": end}, "status": "selesai"}, {"_id": 0}).to_list(5000)
    ks = await db.kasir.find({"timestamp": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
    ex = await db.expenses.find({"tanggal": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
    by_day: Dict[str, Dict[str, int]] = {}
    def bucket(iso):
        return iso[:10]
    for c in ci:
        d = bucket(c["jam_checkout"])
        by_day.setdefault(d, {"kamar": 0, "makanan": 0, "minuman": 0, "laundry": 0, "pengeluaran": 0})
        by_day[d]["kamar"] += c.get("total", 0)
    for k in ks:
        d = bucket(k["timestamp"])
        by_day.setdefault(d, {"kamar": 0, "makanan": 0, "minuman": 0, "laundry": 0, "pengeluaran": 0})
        for it in k.get("items", []):
            by_day[d][it["kategori"]] += it["subtotal"]
    for e in ex:
        d = bucket(e["tanggal"])
        by_day.setdefault(d, {"kamar": 0, "makanan": 0, "minuman": 0, "laundry": 0, "pengeluaran": 0})
        by_day[d]["pengeluaran"] += e.get("nominal", 0)
    result = []
    for d in sorted(by_day.keys()):
        row = by_day[d]
        pendapatan = row["kamar"] + row["makanan"] + row["minuman"] + row["laundry"]
        result.append({
            "tanggal": d, **row,
            "pendapatan": pendapatan,
            "laba": pendapatan - row["pengeluaran"],
        })
    return result

@api.get("/reports/rooms")
async def report_rooms(from_date: str = Query(...), to_date: str = Query(...),
                       user: dict = Depends(get_current_user)):
    start = from_date
    end = to_date + "T23:59:59"
    items = await db.checkins.find(
        {"jam_checkout": {"$gte": start, "$lte": end}, "status": "selesai"},
        {"_id": 0}
    ).sort("jam_checkout", -1).to_list(5000)
    summary = {
        "tanggal_dari": from_date, "tanggal_sampai": to_date,
        "total_transaksi": len(items),
        "total_tamu": sum(int(c.get("jumlah_tamu", 1)) for c in items),
        "kamar_terpakai": len({c["room_nomor"] for c in items}),
        "pendapatan_standard": sum(c.get("total", 0) for c in items if c.get("room_tipe") == "Standard"),
        "pendapatan_cottage": sum(c.get("total", 0) for c in items if c.get("room_tipe") == "Cottage"),
        "total_overtime": sum(c.get("biaya_tambahan", 0) for c in items),
        "total_pendapatan": sum(c.get("total", 0) for c in items),
    }
    return {"summary": summary, "items": items}

@api.get("/reports/kasir-detail")
async def report_kasir_detail(from_date: str = Query(...), to_date: str = Query(...),
                              user: dict = Depends(get_current_user)):
    start = from_date
    end = to_date + "T23:59:59"
    trxs = await db.kasir.find(
        {"timestamp": {"$gte": start, "$lte": end}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(5000)
    per_kat = {"makanan": 0, "minuman": 0, "laundry": 0}
    for t in trxs:
        for it in t.get("items", []):
            per_kat[it["kategori"]] = per_kat.get(it["kategori"], 0) + it.get("subtotal", 0)
    summary = {
        "tanggal_dari": from_date, "tanggal_sampai": to_date,
        "total_transaksi": len(trxs),
        "total_makanan": per_kat["makanan"],
        "total_minuman": per_kat["minuman"],
        "total_laundry": per_kat["laundry"],
        "total_pendapatan": sum(t.get("total", 0) for t in trxs),
    }
    return {"summary": summary, "items": trxs}

@api.get("/reports/items-sold")
async def report_items_sold(from_date: str = Query(...), to_date: str = Query(...),
                            user: dict = Depends(get_current_user)):
    start = from_date
    end = to_date + "T23:59:59"
    trxs = await db.kasir.find({"timestamp": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
    agg: Dict[str, Dict[str, Any]] = {}
    for t in trxs:
        for it in t.get("items", []):
            key = it["product_id"]
            if key not in agg:
                agg[key] = {
                    "product_id": key, "kode": it["kode"], "nama": it["nama"],
                    "kategori": it["kategori"], "harga": it["harga"], "qty": 0, "pendapatan": 0,
                }
            agg[key]["qty"] += it["qty"]
            agg[key]["pendapatan"] += it["subtotal"]
    rows = sorted(agg.values(), key=lambda x: x["qty"], reverse=True)
    return rows

@api.get("/reports/top-products")
async def report_top_products(period: str = Query("month"), limit: int = Query(10),
                              user: dict = Depends(get_current_user)):
    """period: today | month | year"""
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.date().isoformat()
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    trxs = await db.kasir.find({"timestamp": {"$gte": start}}, {"_id": 0}).to_list(10000)
    agg: Dict[str, Dict[str, Any]] = {}
    for t in trxs:
        for it in t.get("items", []):
            key = it["product_id"]
            if key not in agg:
                agg[key] = {"kode": it["kode"], "nama": it["nama"], "kategori": it["kategori"], "qty": 0, "pendapatan": 0}
            agg[key]["qty"] += it["qty"]
            agg[key]["pendapatan"] += it["subtotal"]
    rows = sorted(agg.values(), key=lambda x: x["qty"], reverse=True)[:limit]
    return {"period": period, "rows": rows}

# ---- Setup / seed ----
@app.on_event("startup")
async def startup():
    # Indexes
    await db.users.create_index("username", unique=True)
    await db.rooms.create_index("nomor", unique=True)
    await db.products.create_index("kode", unique=True)
    await db.checkins.create_index("jam_checkin")
    await db.kasir.create_index("timestamp")
    await db.expenses.create_index("tanggal")
    await db.audit_log.create_index("timestamp")
    await db.bookings.create_index("room_id")
    await db.bookings.create_index("jam_mulai")

    # Seed users
    async def ensure_user(username, password, nama, role):
        existing = await db.users.find_one({"username": username})
        if not existing:
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "nama": nama,
                "username": username,
                "password_hash": hash_password(password),
                "role": role,
                "status": "aktif",
                "created_at": now_iso(),
            })
        elif not verify_password(password, existing.get("password_hash", "")):
            await db.users.update_one({"username": username}, {"$set": {"password_hash": hash_password(password)}})

    await ensure_user(os.environ.get("ADMIN_USERNAME", "owner"), os.environ.get("ADMIN_PASSWORD", "owner123"),
                      os.environ.get("ADMIN_NAME", "Pemilik Pelangi"), "owner")
    await ensure_user(os.environ.get("RECEPTIONIST_USERNAME", "resepsionis"),
                      os.environ.get("RECEPTIONIST_PASSWORD", "resep123"), "Resepsionis Pelangi", "resepsionis")

    # Seed rooms (18 total: 12 Standard nomor 1-12 + 6 Cottage nomor 13-18) if empty
    count = await db.rooms.count_documents({})
    if count == 0:
        rooms = []
        # Standard: 1..12
        for i in range(1, 13):
            rooms.append({
                "id": str(uuid.uuid4()),
                "nomor": str(i),
                "tipe": "Standard",
                "tarif": 120000,
                "status": "kosong",
                "info": {},
                "created_at": now_iso(),
            })
        # Cottage: 13..18
        for i in range(13, 19):
            rooms.append({
                "id": str(uuid.uuid4()),
                "nomor": str(i),
                "tipe": "Cottage",
                "tarif": 140000,
                "status": "kosong",
                "info": {},
                "created_at": now_iso(),
            })
        await db.rooms.insert_many(rooms)

    # Seed products if empty
    pcount = await db.products.count_documents({})
    if pcount == 0:
        starter = [
            ("F001", "Nasi Goreng Spesial", "makanan", 25000, 20),
            ("F002", "Mie Goreng", "makanan", 20000, 20),
            ("F003", "Ayam Geprek", "makanan", 22000, 20),
            ("F004", "Pisang Goreng", "makanan", 10000, 30),
            ("D001", "Air Mineral 600ml", "minuman", 5000, 50),
            ("D002", "Teh Botol", "minuman", 8000, 30),
            ("D003", "Kopi Hitam", "minuman", 10000, 30),
            ("D004", "Es Jeruk", "minuman", 12000, 20),
            ("L001", "Cuci Setrika /kg", "laundry", 8000, 0),
            ("L002", "Cuci Kering /kg", "laundry", 6000, 0),
            ("L003", "Express 6 Jam /kg", "laundry", 15000, 0),
        ]
        await db.products.insert_many([{
            "id": str(uuid.uuid4()),
            "kode": k, "nama": n, "kategori": kat, "harga": h, "stok": s,
            "stok_minimal": 5 if kat != "laundry" else 0, "aktif": True,
            "created_at": now_iso(),
        } for (k, n, kat, h, s) in starter])

@app.on_event("shutdown")
async def shutdown():
    client.close()

@api.get("/")
async def root():
    return {"app": "Pelangi Homestay API", "status": "ok"}

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
