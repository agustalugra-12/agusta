"""Jadwal Kerja Staf — PRD baru dari user (2026-07-17), TERPISAH dari PRD "Modul Reservasi
& Priority Booking". Fitur Phase 1: Dashboard Jadwal, Generate (murni algoritmik — lihat
`_buat_jadwal_acak`), Optimizer (diimplementasikan sebagai validasi+peringatan transparan
saat edit manual di `update_shift`/`_detail_jadwal`, bukan auto-rewrite sel lain secara
diam-diam), Publish, Riwayat Jadwal, Audit Log (reuse `log_activity`), Tukar Shift.
Integrasi absensi (attendance) SENGAJA belum dikerjakan (di luar Phase 1). Print/Export PDF
SENGAJA DIHAPUS (2026-07-17, permintaan user "jangan pdf" — simplifikasi setelah generate
sempat crash, lihat catatan di `generate_jadwal`).

Data model:
- `db.staff_kerja`   — roster staf yang dijadwalkan (nama, shift_terlarang, aktif).
- `db.jadwal_kerja`  — 1 dokumen per bulan (year, month, status draft/published).
- `db.jadwal_shifts` — 1 dokumen per (jadwal_id, staff_id, tanggal) = shift hari itu.
"""
from core import *
import asyncio
import calendar
import random
from pymongo import ReplaceOne

# Kunci in-process (satu proses uvicorn, tidak ada --workers > 1) — serialisasi generate
# supaya dua request bersamaan (mis. double-click) tidak saling tumpang tindih menulis
# jadwal_kerja/jadwal_shifts. Satu kunci global cukup (aksi ini jarang & owner-only, tidak
# butuh kunci per-bulan yang lebih rumit).
_generate_lock = asyncio.Lock()

SHIFT_KERJA = ["morning", "middle", "night"]
SHIFT_VALUES = SHIFT_KERJA + ["off"]
SHIFT_LABEL = {"morning": "Morning", "middle": "Middle", "night": "Night", "off": "Off"}
WAJIB_OFF_PER_BULAN = 4
BULAN_LABEL = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
               "Agustus", "September", "Oktober", "November", "Desember"]


def _semua_tanggal(year: int, month: int) -> List[str]:
    n_hari = calendar.monthrange(year, month)[1]
    return [f"{year:04d}-{month:02d}-{d:02d}" for d in range(1, n_hari + 1)]


def _buat_jadwal_acak(staff_list: List[dict], tanggal_list: List[str]) -> Dict[str, Dict[str, str]]:
    """Generate jadwal murni algoritmik (acak-terpandu, TANPA panggilan AI) — 2026-07-17:
    versi awal memanggil OpenAI untuk draft awal (bisa makan waktu >1 menit utk 1 bulan penuh
    x 7 staf), yang membuka celah race condition nyata (dua request generate untuk bulan yang
    sama saling tabrakan saat insert, DuplicateKeyError, generate gagal total). Dihapus atas
    permintaan user ("kalau ini berat buat saja lebih sederhana") — hasilnya SAMA-SAMA
    menjamin tiap staf PERSIS WAJIB_OFF_PER_BULAN hari "off" & tidak pernah shift terlarang
    (jaminan itu sebenarnya selalu berasal dari kode di bawah, bukan dari AI), cuma
    distribusi antar-shift tidak "dioptimalkan" AI — instan & tidak pernah gagal karena
    network/timeout."""
    hasil: Dict[str, Dict[str, str]] = {}
    for s in staff_list:
        terlarang = set(s.get("shift_terlarang") or [])
        boleh_kerja = [sh for sh in SHIFT_KERJA if sh not in terlarang] or list(SHIFT_KERJA)
        hari: Dict[str, str] = {tgl: random.choice(boleh_kerja) for tgl in tanggal_list}
        off_days: List[str] = []
        kerja_days = list(tanggal_list)
        while len(off_days) < WAJIB_OFF_PER_BULAN and kerja_days:
            pilih = random.choice(kerja_days)
            hari[pilih] = "off"
            kerja_days.remove(pilih)
            off_days.append(pilih)
        hasil[s["id"]] = hari
    return hasil


# ---- Staf ----
@api.get("/staff-kerja")
async def list_staff_kerja(user: dict = Depends(get_current_user)):
    return await db.staff_kerja.find({}, {"_id": 0}).sort("nama", 1).to_list(200)


@api.post("/staff-kerja")
async def create_staff_kerja(body: StaffKerjaCreate, user: dict = Depends(require_owner)):
    invalid = set(body.shift_terlarang) - set(SHIFT_KERJA)
    if invalid:
        raise HTTPException(400, f"shift_terlarang tidak valid: {sorted(invalid)}")
    doc = {"id": str(uuid.uuid4()), "nama": body.nama, "shift_terlarang": body.shift_terlarang,
           "aktif": body.aktif, "created_at": now_iso()}
    await db.staff_kerja.insert_one(doc)
    await log_activity(user, "create_staff_kerja", f"Tambah staf jadwal kerja: {body.nama}")
    doc.pop("_id", None)
    return doc


@api.put("/staff-kerja/{sid}")
async def update_staff_kerja(sid: str, body: StaffKerjaUpdate, user: dict = Depends(require_owner)):
    s = await db.staff_kerja.find_one({"id": sid})
    if not s:
        raise HTTPException(404, "Staf tidak ditemukan")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "shift_terlarang" in updates:
        invalid = set(updates["shift_terlarang"]) - set(SHIFT_KERJA)
        if invalid:
            raise HTTPException(400, f"shift_terlarang tidak valid: {sorted(invalid)}")
    if updates:
        await db.staff_kerja.update_one({"id": sid}, {"$set": updates})
    await log_activity(user, "update_staff_kerja", f"Update staf jadwal kerja: {s['nama']}")
    return {"ok": True}


@api.delete("/staff-kerja/{sid}")
async def delete_staff_kerja(sid: str, user: dict = Depends(require_owner)):
    s = await db.staff_kerja.find_one({"id": sid})
    if not s:
        raise HTTPException(404, "Staf tidak ditemukan")
    await db.staff_kerja.delete_one({"id": sid})
    await log_activity(user, "delete_staff_kerja", f"Hapus staf jadwal kerja: {s['nama']}")
    return {"ok": True}


# ---- Jadwal per bulan ----
async def _shift_map_untuk_jadwal(jadwal_id: str) -> Dict[str, Dict[str, str]]:
    rows = await db.jadwal_shifts.find({"jadwal_id": jadwal_id}, {"_id": 0}).to_list(5000)
    out: Dict[str, Dict[str, str]] = {}
    for r in rows:
        out.setdefault(r["staff_id"], {})[r["tanggal"]] = r["shift"]
    return out


def _statistik_staf(hari: Dict[str, str]) -> Dict[str, int]:
    stat = {"morning": 0, "middle": 0, "night": 0, "off": 0}
    for v in hari.values():
        if v in stat:
            stat[v] += 1
    return stat


async def _detail_jadwal(jadwal: dict) -> dict:
    """Bentuk respons dipakai bareng oleh get/generate/edit/swap/publish supaya frontend
    selalu dapat state penuh (termasuk pelanggaran aturan) setelah aksi apa pun."""
    staff_list = await db.staff_kerja.find({}, {"_id": 0}).sort("nama", 1).to_list(200)
    tanggal_list = _semua_tanggal(jadwal["year"], jadwal["month"])
    shift_map = await _shift_map_untuk_jadwal(jadwal["id"])
    staf_out = []
    for s in staff_list:
        hari = shift_map.get(s["id"], {})
        stat = _statistik_staf(hari)
        pelanggaran = []
        if hari and stat["off"] != WAJIB_OFF_PER_BULAN:
            pelanggaran.append(f"Hari off {stat['off']}, seharusnya {WAJIB_OFF_PER_BULAN}")
        terlarang = set(s.get("shift_terlarang") or [])
        for tgl, sh in hari.items():
            if sh in terlarang:
                pelanggaran.append(f"{tgl}: shift {SHIFT_LABEL.get(sh, sh)} terlarang untuk staf ini")
        staf_out.append({**s, "shift": hari, "statistik": stat, "pelanggaran": pelanggaran})
    return {
        "id": jadwal["id"], "year": jadwal["year"], "month": jadwal["month"],
        "status": jadwal["status"], "generated_at": jadwal.get("generated_at"),
        "generated_by": jadwal.get("generated_by"), "published_at": jadwal.get("published_at"),
        "published_by": jadwal.get("published_by"),
        "tanggal": tanggal_list, "staf": staf_out,
        "valid": all(not s["pelanggaran"] for s in staf_out) if staf_out else False,
    }


@api.get("/jadwal-kerja")
async def get_jadwal_bulan(year: int, month: int, user: dict = Depends(get_current_user)):
    jadwal = await db.jadwal_kerja.find_one({"year": year, "month": month})
    if not jadwal:
        return None
    return await _detail_jadwal(jadwal)


@api.get("/jadwal-kerja/riwayat")
async def list_riwayat_jadwal(user: dict = Depends(get_current_user)):
    return await db.jadwal_kerja.find({}, {"_id": 0}).sort([("year", -1), ("month", -1)]).to_list(200)


@api.post("/jadwal-kerja/generate")
async def generate_jadwal(body: JadwalGenerateBody, user: dict = Depends(require_owner)):
    """Generate jadwal (algoritmik, lihat `_buat_jadwal_acak`). Boleh dipanggil ulang untuk
    regenerasi TOTAL selama status masih draft (menimpa semua sel lama) — begitu published,
    tidak bisa digenerate ulang di sini (jaga hasil yang sudah dibagikan staf supaya tidak
    berubah diam-diam).

    Kunci in-process (`_generate_lock`) + upsert atomik — 2026-07-17: versi awal sempat CRASH
    nyata di produksi (DuplicateKeyError) kalau dua request generate utk bulan yang sama
    tumpang tindih (mis. double-click sebelum tombol sempat disabled, atau retry browser
    saat request AI yang lama belum selesai). Upsert atomik saja ternyata belum cukup kalau
    beberapa request BENAR-BENAR simultan (diverifikasi lewat stress test asyncio.gather) —
    tiap request bisa terlanjur baca `existing=None` sebelum request lain sempat commit,
    lalu masing-masing generate jadwal_id/hasil acak SENDIRI-SENDIRI yang saling menimpa.
    Kunci ini menghilangkan kemungkinan itu sama sekali dengan menyerialkan seluruh isi
    fungsi, bukan cuma operasi tulis individualnya."""
    if not (1 <= body.month <= 12):
        raise HTTPException(400, "month harus 1-12")
    async with _generate_lock:
        staff_list = await db.staff_kerja.find({"aktif": True}, {"_id": 0}).to_list(200)
        if not staff_list:
            raise HTTPException(400, "Belum ada staf aktif — tambah staf dulu di pengaturan Jadwal Kerja")

        existing = await db.jadwal_kerja.find_one({"year": body.year, "month": body.month})
        if existing and existing.get("status") == "published":
            raise HTTPException(400, "Jadwal bulan ini sudah dipublish — tidak bisa digenerate ulang otomatis")

        tanggal_list = _semua_tanggal(body.year, body.month)
        hasil = _buat_jadwal_acak(staff_list, tanggal_list)

        now = now_iso()
        jadwal_id = existing["id"] if existing else str(uuid.uuid4())
        await db.jadwal_kerja.update_one(
            {"year": body.year, "month": body.month},
            {
                "$set": {"id": jadwal_id, "status": "draft", "generated_at": now, "generated_by": user["nama"]},
                "$setOnInsert": {"year": body.year, "month": body.month, "published_at": None, "published_by": None, "created_at": now},
            },
            upsert=True,
        )

        ops = [
            ReplaceOne(
                {"jadwal_id": jadwal_id, "staff_id": sid, "tanggal": tgl},
                {"id": str(uuid.uuid4()), "jadwal_id": jadwal_id, "staff_id": sid, "tanggal": tgl, "shift": sh},
                upsert=True,
            )
            for sid, hari in hasil.items() for tgl, sh in hari.items()
        ]
        if ops:
            await db.jadwal_shifts.bulk_write(ops, ordered=False)
        # Buang sel staf yang sudah tidak aktif/dihapus sejak generate terakhir kali (kalau
        # ada) — supaya tidak ada sisa data yatim dari staf lama yang tidak lagi dijadwalkan.
        staff_ids_aktif = [s["id"] for s in staff_list]
        await db.jadwal_shifts.delete_many({"jadwal_id": jadwal_id, "staff_id": {"$nin": staff_ids_aktif}})

        await log_activity(user, "generate_jadwal_kerja", f"Generate jadwal kerja {body.month}/{body.year} ({len(staff_list)} staf aktif)")
        jadwal = await db.jadwal_kerja.find_one({"id": jadwal_id})
        return await _detail_jadwal(jadwal)


@api.put("/jadwal-kerja/{jadwal_id}/shift")
async def update_shift(jadwal_id: str, body: JadwalShiftUpdateBody, user: dict = Depends(require_owner)):
    """Edit manual 1 sel. TIDAK auto-mengubah sel lain (bukan black-box) — response berisi
    statistik & pelanggaran terbaru supaya staf/owner ADA yang tahu & sadar kalau edit ini
    bikin jumlah hari off staf itu jadi tidak 4 lagi, lalu perbaiki manual sendiri sel mana
    yang mau diubah. Ini interpretasi "AI Optimizer" yang transparan, bukan auto-rewrite
    hari lain punya staf tanpa sepengetahuan admin."""
    jadwal = await db.jadwal_kerja.find_one({"id": jadwal_id})
    if not jadwal:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    if jadwal.get("status") == "published":
        raise HTTPException(400, "Jadwal sudah dipublish — tidak bisa diedit langsung")
    if body.shift not in SHIFT_VALUES:
        raise HTTPException(400, "Shift tidak valid")
    staf = await db.staff_kerja.find_one({"id": body.staff_id})
    if not staf:
        raise HTTPException(404, "Staf tidak ditemukan")
    if body.tanggal not in _semua_tanggal(jadwal["year"], jadwal["month"]):
        raise HTTPException(400, "Tanggal di luar bulan jadwal ini")
    if body.shift in (staf.get("shift_terlarang") or []):
        raise HTTPException(400, f"{staf['nama']} tidak boleh shift {SHIFT_LABEL.get(body.shift, body.shift)}")
    await db.jadwal_shifts.update_one(
        {"jadwal_id": jadwal_id, "staff_id": body.staff_id, "tanggal": body.tanggal},
        {"$set": {"shift": body.shift}},
        upsert=True,
    )
    await log_activity(user, "edit_shift_jadwal_kerja", f"Ubah shift {staf['nama']} {body.tanggal} -> {SHIFT_LABEL.get(body.shift, body.shift)}")
    jadwal2 = await db.jadwal_kerja.find_one({"id": jadwal_id})
    return await _detail_jadwal(jadwal2)


@api.post("/jadwal-kerja/{jadwal_id}/swap")
async def swap_shift(jadwal_id: str, body: JadwalSwapBody, user: dict = Depends(require_owner)):
    """Tukar Shift — validasi shift_terlarang kedua staf setelah tukar, dan TOLAK tukar
    yang melibatkan hari "off" antar staf BERBEDA (itu akan mengubah jumlah hari off salah
    satu staf dari wajib 4 tanpa admin sadar) — kalau memang perlu, admin edit manual per
    sel lewat endpoint shift di atas."""
    jadwal = await db.jadwal_kerja.find_one({"id": jadwal_id})
    if not jadwal:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    if jadwal.get("status") == "published":
        raise HTTPException(400, "Jadwal sudah dipublish — tidak bisa tukar shift lagi di sini")

    a = await db.jadwal_shifts.find_one({"jadwal_id": jadwal_id, "staff_id": body.staff_id_a, "tanggal": body.tanggal_a})
    b = await db.jadwal_shifts.find_one({"jadwal_id": jadwal_id, "staff_id": body.staff_id_b, "tanggal": body.tanggal_b})
    if not a or not b:
        raise HTTPException(404, "Sel jadwal tidak ditemukan (staf/tanggal tidak sesuai jadwal ini)")

    staf_a = await db.staff_kerja.find_one({"id": body.staff_id_a})
    staf_b = await db.staff_kerja.find_one({"id": body.staff_id_b})
    if not staf_a or not staf_b:
        raise HTTPException(404, "Staf tidak ditemukan")
    terlarang_a = set(staf_a.get("shift_terlarang") or [])
    terlarang_b = set(staf_b.get("shift_terlarang") or [])

    if b["shift"] in terlarang_a:
        raise HTTPException(400, f"Tidak bisa: {staf_a['nama']} tidak boleh shift {SHIFT_LABEL.get(b['shift'], b['shift'])}")
    if a["shift"] in terlarang_b:
        raise HTTPException(400, f"Tidak bisa: {staf_b['nama']} tidak boleh shift {SHIFT_LABEL.get(a['shift'], a['shift'])}")
    if body.staff_id_a != body.staff_id_b and (a["shift"] == "off") != (b["shift"] == "off"):
        raise HTTPException(400, "Tidak bisa menukar shift kerja dengan hari off antar staf berbeda — akan mengubah jumlah hari off salah satu staf dari 4. Edit manual per sel kalau memang perlu.")

    await db.jadwal_shifts.update_one({"id": a["id"]}, {"$set": {"shift": b["shift"]}})
    await db.jadwal_shifts.update_one({"id": b["id"]}, {"$set": {"shift": a["shift"]}})
    await log_activity(user, "tukar_shift_jadwal_kerja",
                       f"Tukar shift {staf_a['nama']} {body.tanggal_a} <-> {staf_b['nama']} {body.tanggal_b}")
    jadwal2 = await db.jadwal_kerja.find_one({"id": jadwal_id})
    return await _detail_jadwal(jadwal2)


@api.post("/jadwal-kerja/{jadwal_id}/publish")
async def publish_jadwal(jadwal_id: str, user: dict = Depends(require_owner)):
    jadwal = await db.jadwal_kerja.find_one({"id": jadwal_id})
    if not jadwal:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    if jadwal.get("status") == "published":
        raise HTTPException(400, "Jadwal ini sudah dipublish")
    detail = await _detail_jadwal(jadwal)
    if not detail["valid"]:
        raise HTTPException(400, "Masih ada pelanggaran aturan (hari off/shift terlarang) — perbaiki dulu sebelum publish")
    now = now_iso()
    await db.jadwal_kerja.update_one({"id": jadwal_id}, {"$set": {
        "status": "published", "published_at": now, "published_by": user["nama"],
    }})
    await log_activity(user, "publish_jadwal_kerja", f"Publish jadwal kerja {jadwal['month']}/{jadwal['year']}")
    jadwal2 = await db.jadwal_kerja.find_one({"id": jadwal_id})
    return await _detail_jadwal(jadwal2)


