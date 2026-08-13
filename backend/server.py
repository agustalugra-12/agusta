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
from routes.rekening import background_smart_rule_loop
from routes.ai_grow import background_ai_grow_cache_loop
from routes.incidents import background_collection_required_scan_loop, background_business_truth_scan_loop
from routes.claude_fix import reconcile_stale_claude_runs

app = FastAPI(title="Pelangi Homestay API")
app.mount("/uploads", StaticFiles(directory=str(ROOT_DIR / "uploads")), name="uploads")

async def _replace_unique_index(collection, old_name: str, new_keys, **kwargs):
    """2026-07-24, multi-properti: beberapa index unique lama (nomor kamar/kode produk/dst)
    perlu jadi compound dengan property_id supaya 2 properti boleh punya nilai sama (mis.
    2 properti sama-sama punya "Kamar 1"). drop_index dibungkus try/except supaya idempotent
    lintas restart (index lama cuma ada sekali, restart berikutnya sudah tidak ketemu lagi)."""
    try:
        await collection.drop_index(old_name)
    except Exception:
        pass
    await collection.create_index(new_keys, unique=True, **kwargs)

@app.on_event("startup")
async def startup():
    # Indexes
    await db.users.create_index("username", unique=True)
    await db.users.create_index("email", unique=True, sparse=True)
    await db.properties.create_index("slug", unique=True)
    await _replace_unique_index(db.rooms, "nomor_1", [("property_id", 1), ("nomor", 1)])
    await _replace_unique_index(db.products, "kode_1", [("property_id", 1), ("kode", 1)])
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
    await _replace_unique_index(db.rates, "room_type_1_tanggal_1",
                                 [("property_id", 1), ("room_type", 1), ("tanggal", 1)])
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
    await _replace_unique_index(db.jadwal_kerja, "year_1_month_1",
                                 [("property_id", 1), ("year", 1), ("month", 1)])
    await db.jadwal_shifts.create_index([("jadwal_id", 1), ("staff_id", 1), ("tanggal", 1)], unique=True)
    await db.kasbon.create_index("staff_id")
    await db.payroll.create_index([("staff_id", 1), ("periode", 1)], unique=True)
    await db.payroll.create_index("periode")

    # Incident Engine (2026-08-12, PRD "Owner Control Center" Fase 1)
    await db.incidents.create_index([("status", 1), ("created_at", -1)])
    await db.incidents.create_index("dedup_key", sparse=True)

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

    # Laporan akhir hari otomatis ke Telegram (owner & staff yang sudah terhubung), jam
    # 23:00 WIB (2026-08-04, dipindah dari 22:00 - permintaan Agus, data hari itu biasanya
    # sudah masuk semua di jam ini) - sekaligus memicu rekomendasi final AI Grow, disatukan
    # ke pesan yang sama (lihat _laporan_harian_text/background_telegram_daily_report_loop).
    asyncio.create_task(background_telegram_daily_report_loop())

    # Cash & Account Intelligence - Smart Allocation Rule trigger tanggal_bulanan (cek 1x/6 jam).
    asyncio.create_task(background_smart_rule_loop())

    # AI Grow - refresh cache Daily Brief jam 10:00 & 18:00 WIB (2026-08-04, permintaan
    # Agus - kurangi panggilan OpenAI, dashboard baca cache bukan live-generate tiap
    # dibuka). Slot ke-3 (23:00 WIB) dipicu dari background_telegram_daily_report_loop
    # sendiri, lihat catatan di sana.
    asyncio.create_task(background_ai_grow_cache_loop())

    # Incident Engine - Collection Required (2026-08-12, PRD "Owner Control Center" Fase 1)
    # scan booking Menginap checked_in dgn sisa tagihan tiap 15 menit (lihat
    # routes/incidents.py utk detail lengkap kenapa dibatasi tipe="menginap" dulu).
    asyncio.create_task(background_collection_required_scan_loop())

    # Business Truth Reconciliation (2026-08-13, PRD "Owner Control Center" §21) - silang
    # cek settlement Tripay (db.payment_log) vs ledger kas (db.rekening_transaksi) tiap
    # 1 jam, lihat routes/incidents.py utk detail 2 cek yang dijalankan.
    asyncio.create_task(background_business_truth_scan_loop())

    # Fase 4 Claude Code Control (2026-08-13) - restart-safety: run yang masih "in
    # progress" saat backend restart ditandai error, jangan nyangkut lock/status
    # ambigu selamanya (lihat routes/claude_fix.py).
    await reconcile_stale_claude_runs()


@app.on_event("shutdown")
async def shutdown():
    client.close()


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    # 2026-07-24, diperbaiki saat audit kesiapan produksi - sebelumnya wildcard ("*" +
    # allow_origin_regex=".*") dikombinasikan dengan allow_credentials=True & cookie sesi,
    # kombinasi yang tidak dianjurkan (browser modern otomatis meng-echo origin asli begitu
    # credentials=True dipakai bareng wildcard, jadi efeknya SEMUA origin diizinkan bawa
    # cookie). Risikonya sudah agak diredam oleh cookie httponly+samesite=lax yang sudah
    # ada, tapi tetap dibatasi ke domain yang benar-benar melayani frontend PMS -
    # book.pelangihomestay.com cuma redirect 301 (tidak pernah jadi origin browser
    # sungguhan), bot./web pelangi tidak pernah panggil API ini langsung dari browser
    # (selalu server-to-server), jadi TIDAK perlu masuk daftar ini.
    allow_origins=[
        "https://pms.pelangihomestay.com",
        "https://pmspelangi.my.id",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
