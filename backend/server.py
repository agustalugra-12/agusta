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

class CheckoutIn(BaseModel):
    pembayaran: List[Dict[str, Any]] = []  # [{"metode":"tunai","jumlah":100000}]
    overtime_manual: Optional[int] = None  # jika ingin override jam overtime
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

# ---- Check-in / Check-out ----
def calc_tagihan(tarif_dasar: int, jam_checkin: datetime, jam_checkout: datetime, overtime_manual: Optional[int] = None):
    delta = jam_checkout - jam_checkin
    total_jam = delta.total_seconds() / 3600.0
    base_hours = 6
    if overtime_manual is not None:
        overtime_hours = max(0, overtime_manual)
    else:
        overtime_hours = max(0, int(-(-(total_jam - base_hours) // 1))) if total_jam > base_hours else 0
    biaya_tambahan = overtime_hours * 20000
    total = tarif_dasar + biaya_tambahan
    return {
        "durasi_jam": round(total_jam, 2),
        "overtime_jam": overtime_hours,
        "biaya_tambahan": biaya_tambahan,
        "tarif_dasar": tarif_dasar,
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
        "jam_checkin": now_iso(),
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
    ci = datetime.fromisoformat(c["jam_checkin"])
    calc = calc_tagihan(c["tarif_dasar"], ci, now, body.overtime_manual)
    total_bayar = sum(int(p.get("jumlah", 0)) for p in body.pembayaran)
    if total_bayar < calc["total"]:
        raise HTTPException(400, f"Total pembayaran kurang. Diperlukan Rp{calc['total']:,}".replace(",", "."))
    updates = {
        "jam_checkout": now.isoformat(),
        "durasi_jam": calc["durasi_jam"],
        "overtime_jam": calc["overtime_jam"],
        "biaya_tambahan": calc["biaya_tambahan"],
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

# ---- Audit Log ----
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

    # Seed rooms (18 total: 12 Standard + 6 Cottage) if empty
    count = await db.rooms.count_documents({})
    if count == 0:
        rooms = []
        # Standard: 101..112
        for i in range(1, 13):
            rooms.append({
                "id": str(uuid.uuid4()),
                "nomor": f"1{i:02d}",
                "tipe": "Standard",
                "tarif": 120000,
                "status": "kosong",
                "info": {},
                "created_at": now_iso(),
            })
        # Cottage: 201..206
        for i in range(1, 7):
            rooms.append({
                "id": str(uuid.uuid4()),
                "nomor": f"2{i:02d}",
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
