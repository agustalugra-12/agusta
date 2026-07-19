"""Pelangi Homestay API — main application entry point.

Thin orchestrator: sets up FastAPI, CORS, mounts the shared `api` router
(populated by importing the `routes` package), and defines startup/shutdown
lifecycle hooks (indexes + seed data).

Business logic lives in:
- core.py            — shared models, helpers, security, DB client
- routes/*.py        — endpoint definitions grouped by domain
"""
import os
import uuid
import asyncio
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from core import api, client, db, now_iso, hash_password, verify_password, ROOT_DIR
import routes  # noqa: F401  — importing registers all endpoints on `api`
from routes.sinkronisasi_ketersediaan import background_sync_loop
from routes.otomasi_email import background_gmail_fetch_loop
from routes.telegram_bot import background_telegram_daily_report_loop

app = FastAPI(title="Pelangi Homestay API")
app.mount("/uploads", StaticFiles(directory=str(ROOT_DIR / "uploads")), name="uploads")

@app.on_event("startup")
async def startup():
    # Indexes
    await db.users.create_index("username", unique=True)
    await db.users.create_index("email", unique=True, sparse=True)
    await db.rooms.create_index("nomor", unique=True)
    await db.products.create_index("kode", unique=True)
    await db.checkins.create_index("jam_checkin")
    await db.kasir.create_index("timestamp")
    await db.expenses.create_index("tanggal")
    await db.services.create_index("tanggal")
    await db.audit_log.create_index("timestamp")
    await db.bookings.create_index("room_id")
    await db.bookings.create_index("jam_mulai")
    await db.bookings.create_index([("room_id", 1), ("status", 1), ("jam_mulai", 1)])  # check_room_available/scheduling_engine hot path
    await db.bookings.create_index([("payment_status", 1), ("paid_at", 1)])
    await db.bookings.create_index("source")
    await db.bookings.create_index("ota_reservation_no", sparse=True)
    await db.bookings.create_index("modifikasi_status", sparse=True)
    await db.bookings.create_index("sync_status", sparse=True)
    await db.rates.create_index([("room_type", 1), ("tanggal", 1)], unique=True)
    await db.availability_logs.create_index("room_id")
    await db.availability_logs.create_index("changed_at")
    await db.integrations.create_index("provider", unique=True)
    await db.push_subscriptions.create_index("endpoint", unique=True)
    await db.push_subscriptions.create_index("user_id")
    await db.issues.create_index([("tipe", 1), ("status", 1)])
    await db.issues.create_index("created_at")
    await db.housekeeping_log.create_index([("room_id", 1), ("status", 1)])
    await db.housekeeping_log.create_index("tanggal")
    await db.push_subscriptions.create_index("user_id")
    await db.booking_requests.create_index("status")
    await db.booking_requests.create_index("created_at")
    await db.wa_booking_sessions.create_index("no_hp", unique=True)
    await db.jadwal_kerja.create_index([("year", 1), ("month", 1)], unique=True)
    await db.jadwal_shifts.create_index([("jadwal_id", 1), ("staff_id", 1), ("tanggal", 1)], unique=True)

    # Seed users - SEKALI SAJA saat akun belum ada. Sebelumnya ada cabang elif yang
    # menimpa password_hash tiap restart kalau tidak cocok dengan ADMIN_PASSWORD/
    # RECEPTIONIST_PASSWORD env (default "owner123"/"resep123" kalau env belum diisi) -
    # bug keamanan nyata: password yang diganti sendiri oleh owner/staf lewat PUT /auth/me
    # atau PUT /users/{id} diam-diam KEMBALI ke password lama/default tiap kali service
    # restart/deploy. Dihapus 2026-07-19 - begitu akun ada, password_hash HANYA boleh
    # berubah lewat endpoint ganti password yang eksplisit.
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

    await ensure_user(
        os.environ.get("ADMIN_USERNAME", "owner"),
        os.environ.get("ADMIN_PASSWORD", "owner123"),
        os.environ.get("ADMIN_NAME", "Pemilik Pelangi"),
        "owner",
    )
    await ensure_user(
        os.environ.get("RECEPTIONIST_USERNAME", "resepsionis"),
        os.environ.get("RECEPTIONIST_PASSWORD", "resep123"),
        "Resepsionis Pelangi",
        "resepsionis",
    )

    # Seed rooms (18 total: 12 Standard 1-12 + 6 Cottage 13-18)
    count = await db.rooms.count_documents({})
    if count == 0:
        rooms = []
        for i in range(1, 13):
            rooms.append({
                "id": str(uuid.uuid4()),
                "nomor": str(i), "tipe": "Standard", "tarif": 120000, "tarif_menginap": 150000,
                "status": "kosong", "info": {}, "created_at": now_iso(),
            })
        for i in range(13, 19):
            rooms.append({
                "id": str(uuid.uuid4()),
                "nomor": str(i), "tipe": "Cottage", "tarif": 140000, "tarif_menginap": 200000,
                "status": "kosong", "info": {}, "created_at": now_iso(),
            })
        await db.rooms.insert_many(rooms)

    # Seed products (starter menu)
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

    # Seed staf Jadwal Kerja (PRD baru user 2026-07-17) — 7 staf, Pita & Indah tidak boleh
    # Night Shift (disimpan sebagai DATA shift_terlarang, bukan hardcode nama di kode, supaya
    # owner bisa ubah lewat UI kalau aturan/personel berubah tanpa perlu deploy ulang).
    scount = await db.staff_kerja.count_documents({})
    if scount == 0:
        staf_awal = [
            ("Pita", ["night"]), ("Fendi", []), ("Edi", []), ("Esa", []),
            ("Erik", []), ("Indah", ["night"]), ("Putu Kusuma", []),
        ]
        await db.staff_kerja.insert_many([{
            "id": str(uuid.uuid4()), "nama": nama, "shift_terlarang": terlarang,
            "aktif": True, "created_at": now_iso(),
        } for (nama, terlarang) in staf_awal])

    # Penjadwalan sinkronisasi otomatis (Sinkronisasi Ketersediaan) — jalan di background
    # selama proses uvicorn ini hidup, interval mengikuti `sync_settings.frekuensi_menit`.
    asyncio.create_task(background_sync_loop())

    # Auto-fetch email Gmail OTA berkala (keputusan bisnis user 2026-07-12: reservasi baru
    # dibuat & modifikasi/pembatalan diproses otomatis tanpa staf klik "Cek Email Baru").
    asyncio.create_task(background_gmail_fetch_loop())

    # Laporan akhir hari otomatis ke Telegram (owner & staff yang sudah terhubung), jam 22:00 WIB.
    asyncio.create_task(background_telegram_daily_report_loop())


@app.on_event("shutdown")
async def shutdown():
    client.close()


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
