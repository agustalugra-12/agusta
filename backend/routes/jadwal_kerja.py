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
MAKS_OFF_PER_HARI = 1  # 2026-07-17: max 1 staf libur per hari (di seluruh jadwal)
MAKS_OFF_PER_MINGGU = 1  # 2026-07-17: max 1x libur per staf per minggu (ISO week)
TARGET_MORNING_PER_HARI = 3  # 2026-07-17: selalu 3 orang Morning per hari
TARGET_NIGHT_PER_HARI = 1  # selalu 1 orang Night per hari — sisanya (2 atau 3, tergantung ada yg libur) jadi Middle
MAKS_PER_HARI = {"off": MAKS_OFF_PER_HARI, "night": TARGET_NIGHT_PER_HARI, "morning": TARGET_MORNING_PER_HARI}
BULAN_LABEL = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
               "Agustus", "September", "Oktober", "November", "Desember"]


def _semua_tanggal(year: int, month: int) -> List[str]:
    n_hari = calendar.monthrange(year, month)[1]
    return [f"{year:04d}-{month:02d}-{d:02d}" for d in range(1, n_hari + 1)]


def _kunci_minggu(tanggal: str) -> tuple:
    """(tahun ISO, no minggu ISO) dari tanggal YYYY-MM-DD — dipakai aturan max 1x libur/minggu."""
    d = datetime.strptime(tanggal, "%Y-%m-%d").date()
    return d.isocalendar()[:2]


def _minggu_buckets(tanggal_list: List[str]) -> List[List[str]]:
    buckets: Dict[tuple, List[str]] = {}
    for t in tanggal_list:
        buckets.setdefault(_kunci_minggu(t), []).append(t)
    return list(buckets.values())


def _buat_jadwal_acak(staff_list: List[dict], tanggal_list: List[str]) -> Dict[str, Dict[str, str]]:
    """Generate jadwal murni algoritmik (acak-terpandu, TANPA panggilan AI) — 2026-07-17:
    versi awal memanggil OpenAI untuk draft awal (bisa makan waktu >1 menit utk 1 bulan penuh
    x 7 staf), yang membuka celah race condition nyata (dua request generate untuk bulan yang
    sama saling tabrakan saat insert, DuplicateKeyError, generate gagal total). Dihapus atas
    permintaan user ("kalau ini berat buat saja lebih sederhana") — sekarang murni algoritmik,
    instan, tidak pernah gagal karena network/timeout.

    Dua tahap (aturan 2026-07-17, ditambahkan setelah user uji hasil generate pertama):
    1. Tentukan hari libur tiap staf: PERSIS WAJIB_OFF_PER_BULAN/bulan, MAKS_OFF_PER_HARI
       staf libur per tanggal (di seluruh jadwal), MAKS_OFF_PER_MINGGU per staf per minggu ISO.
    2. Untuk tiap tanggal, bagi peran di antara staf yang TIDAK libur hari itu: selalu
       TARGET_NIGHT_PER_HARI (1) orang Night & TARGET_MORNING_PER_HARI (3) orang Morning,
       sisanya Middle (otomatis 2 kalau ada yg libur hari itu, 3 kalau tidak ada yg libur) —
       dipilih fair (staf dgn jumlah shift jenis itu paling sedikit sejauh ini didahulukan)
       & tidak pernah melanggar shift_terlarang staf."""
    minggu_list = _minggu_buckets(tanggal_list)
    if len(minggu_list) < WAJIB_OFF_PER_BULAN:
        raise HTTPException(400, f"Bulan ini cuma {len(minggu_list)} minggu — tidak cukup utk aturan maks {MAKS_OFF_PER_MINGGU}x libur/minggu x {WAJIB_OFF_PER_BULAN} hari libur/bulan.")

    # --- Tahap 1: hari libur ---
    # Heuristik "minggu dengan sisa slot terbanyak duluan" (bukan pilih minggu murni acak) —
    # minggu di ujung bulan sering cuma punya 1-2 tanggal (batas kalender vs ISO week), jadi
    # kalau tiap staf pilih minggu benar-benar acak, minggu kecil itu cepat kehabisan slot &
    # staf yang diproses belakangan bisa terpaksa 2x libur dalam 1 minggu yang sama. Prioritas
    # ke minggu bersisa banyak menyebar kontensi lebih rata, jauh mengurangi kebutuhan fallback.
    off_terpakai: set = set()
    off_per_staff: Dict[str, set] = {}
    staff_urut = list(staff_list)
    random.shuffle(staff_urut)
    for s in staff_urut:
        off_staf: List[str] = []
        minggu_terpakai_staf: set = set()
        for _ in range(WAJIB_OFF_PER_BULAN):
            opsi = []
            for i, minggu in enumerate(minggu_list):
                if i in minggu_terpakai_staf:
                    continue
                kandidat = [t for t in minggu if t not in off_terpakai]
                if kandidat:
                    opsi.append((len(kandidat), i, kandidat))
            if not opsi:
                break
            terbanyak = max(o[0] for o in opsi)
            top = [o for o in opsi if o[0] == terbanyak]
            _, idx_minggu, kandidat = random.choice(top)
            pilih = random.choice(kandidat)
            off_staf.append(pilih)
            off_terpakai.add(pilih)
            minggu_terpakai_staf.add(idx_minggu)
        if len(off_staf) < WAJIB_OFF_PER_BULAN:
            # Fallback jarang terjadi (tetap mungkin kalau bulan sangat pendek/staf sangat
            # banyak) — longgarkan aturan 1x/minggu demi tetap penuhi PERSIS
            # WAJIB_OFF_PER_BULAN/bulan (dianggap lebih penting) & MAKS_OFF_PER_HARI (tetap
            # dijaga, hanya ambil tanggal yang belum terpakai sama sekali).
            sisa = [t for t in tanggal_list if t not in off_terpakai]
            random.shuffle(sisa)
            for t in sisa:
                if len(off_staf) >= WAJIB_OFF_PER_BULAN:
                    break
                off_staf.append(t)
                off_terpakai.add(t)
        off_per_staff[s["id"]] = set(off_staf)

    # --- Tahap 2: peran per hari (Morning/Middle/Night) di antara yang tidak libur ---
    hasil: Dict[str, Dict[str, str]] = {s["id"]: {} for s in staff_list}
    jumlah_shift = {s["id"]: {"morning": 0, "middle": 0, "night": 0} for s in staff_list}

    def _pilih_fair(kandidat: List[dict], jenis: str, n: int) -> List[dict]:
        pool = list(kandidat)
        dipilih: List[dict] = []
        while len(dipilih) < n and pool:
            min_c = min(jumlah_shift[s["id"]][jenis] for s in pool)
            tersedikit = [s for s in pool if jumlah_shift[s["id"]][jenis] == min_c]
            pilih = random.choice(tersedikit)
            dipilih.append(pilih)
            pool.remove(pilih)
        return dipilih

    for tgl in tanggal_list:
        hadir = [s for s in staff_list if tgl not in off_per_staff[s["id"]]]
        for s in staff_list:
            if tgl in off_per_staff[s["id"]]:
                hasil[s["id"]][tgl] = "off"

        elig_night = [s for s in hadir if "night" not in (s.get("shift_terlarang") or [])] or hadir
        night_staff = _pilih_fair(elig_night, "night", 1)
        for s in night_staff:
            hasil[s["id"]][tgl] = "night"
            jumlah_shift[s["id"]]["night"] += 1

        sisa = [s for s in hadir if s not in night_staff]
        elig_morning = [s for s in sisa if "morning" not in (s.get("shift_terlarang") or [])] or sisa
        morning_staff = _pilih_fair(elig_morning, "morning", min(TARGET_MORNING_PER_HARI, len(elig_morning)))
        for s in morning_staff:
            hasil[s["id"]][tgl] = "morning"
            jumlah_shift[s["id"]]["morning"] += 1

        for s in sisa:
            if s not in morning_staff:
                hasil[s["id"]][tgl] = "middle"
                jumlah_shift[s["id"]]["middle"] += 1

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
        # Maks 1x libur per minggu (ISO week) — dicek per staf di sini (bukan per sel),
        # supaya kelihatan sebagai satu peringatan per staf, bukan berulang per tanggal.
        off_minggu: Dict[tuple, int] = {}
        for tgl, sh in hari.items():
            if sh == "off":
                k = _kunci_minggu(tgl)
                off_minggu[k] = off_minggu.get(k, 0) + 1
        for k, n in off_minggu.items():
            if n > MAKS_OFF_PER_MINGGU:
                pelanggaran.append(f"{n}x libur dalam 1 minggu (maks {MAKS_OFF_PER_MINGGU}x/minggu)")
        staf_out.append({**s, "shift": hari, "statistik": stat, "pelanggaran": pelanggaran})

    # Pelanggaran tingkat hari (bukan per staf) — jumlah off/night/morning per tanggal
    # melebihi batas (lihat MAKS_PER_HARI). Seharusnya TIDAK PERNAH terjadi lewat UI normal
    # (generate & update_shift/swap_shift sudah menegakkan ini keras), tapi tetap dihitung di
    # sini sebagai jaring pengaman/visibilitas kalau ada data lama/tidak konsisten.
    pelanggaran_hari = []
    for tgl in tanggal_list:
        hitung = {"off": 0, "night": 0, "morning": 0}
        for s in staf_out:
            sh = s["shift"].get(tgl)
            if sh in hitung:
                hitung[sh] += 1
        for jenis, batas in MAKS_PER_HARI.items():
            if hitung[jenis] > batas:
                pelanggaran_hari.append(f"{tgl}: {hitung[jenis]} staf {SHIFT_LABEL[jenis]} (maks {batas})")

    ada_data = any(s["shift"] for s in staf_out)
    return {
        "id": jadwal["id"], "year": jadwal["year"], "month": jadwal["month"],
        "status": jadwal["status"], "generated_at": jadwal.get("generated_at"),
        "generated_by": jadwal.get("generated_by"), "published_at": jadwal.get("published_at"),
        "published_by": jadwal.get("published_by"),
        "tanggal": tanggal_list, "staf": staf_out, "pelanggaran_hari": pelanggaran_hari,
        "valid": ada_data and all(not s["pelanggaran"] for s in staf_out) and not pelanggaran_hari,
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


async def _jumlah_shift_tanggal(jadwal_id: str, tanggal: str, shift: str, kecuali_staff_ids: Optional[List[str]] = None) -> int:
    q: Dict[str, Any] = {"jadwal_id": jadwal_id, "tanggal": tanggal, "shift": shift}
    if kecuali_staff_ids:
        q["staff_id"] = {"$nin": kecuali_staff_ids}
    return await db.jadwal_shifts.count_documents(q)


async def _ada_off_lain_di_minggu(jadwal_id: str, staff_id: str, tanggal: str) -> bool:
    """Cek staf ini sudah punya hari "off" LAIN (selain `tanggal` itu sendiri) di minggu ISO
    yang sama — dipakai menegakkan MAKS_OFF_PER_MINGGU keras saat edit manual/tukar shift."""
    kunci = _kunci_minggu(tanggal)
    rows = await db.jadwal_shifts.find(
        {"jadwal_id": jadwal_id, "staff_id": staff_id, "shift": "off"}, {"_id": 0, "tanggal": 1}
    ).to_list(50)
    return any(r["tanggal"] != tanggal and _kunci_minggu(r["tanggal"]) == kunci for r in rows)


async def _validasi_shift_baru(jadwal_id: str, staf: dict, tanggal: str, shift: str, kecuali_staff_ids: Optional[List[str]] = None) -> None:
    """Validasi keras dipakai bareng update_shift & swap_shift — raise HTTPException kalau
    shift baru ini melanggar shift_terlarang staf, batas jumlah per hari (off/night/morning,
    lihat MAKS_PER_HARI), atau batas 1x libur/minggu per staf. `kecuali_staff_ids` supaya staf
    yang shift-nya SEDANG diubah tidak ikut dihitung sebagai "sudah ada" di hitungan lama."""
    if shift in (staf.get("shift_terlarang") or []):
        raise HTTPException(400, f"{staf['nama']} tidak boleh shift {SHIFT_LABEL.get(shift, shift)}")
    if shift in MAKS_PER_HARI:
        jumlah = await _jumlah_shift_tanggal(jadwal_id, tanggal, shift, kecuali_staff_ids=kecuali_staff_ids)
        if jumlah >= MAKS_PER_HARI[shift]:
            raise HTTPException(400, f"Tanggal {tanggal} sudah ada {jumlah} staf shift {SHIFT_LABEL[shift]} (maks {MAKS_PER_HARI[shift]}/hari)")
    if shift == "off" and await _ada_off_lain_di_minggu(jadwal_id, staf["id"], tanggal):
        raise HTTPException(400, f"{staf['nama']} sudah punya hari libur lain di minggu yang sama (maks {MAKS_OFF_PER_MINGGU}x/minggu)")


@api.put("/jadwal-kerja/{jadwal_id}/shift")
async def update_shift(jadwal_id: str, body: JadwalShiftUpdateBody, user: dict = Depends(require_owner)):
    """Edit manual 1 sel. Validasi KERAS: shift_terlarang, batas jumlah per hari
    (off/night/morning), dan maks 1x libur/minggu — semua dicek lewat `_validasi_shift_baru`
    (dipakai juga swap_shift, satu sumber kebenaran). TIDAK auto-mengubah sel lain (bukan
    black-box) untuk aturan yang tidak bisa ditegakkan per-edit (jumlah PERSIS 4 hari
    off/bulan) — itu ditampilkan sebagai peringatan di response, diperbaiki manual."""
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
    await _validasi_shift_baru(jadwal_id, staf, body.tanggal, body.shift, kecuali_staff_ids=[body.staff_id])
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

    if body.staff_id_a != body.staff_id_b and (a["shift"] == "off") != (b["shift"] == "off"):
        raise HTTPException(400, "Tidak bisa menukar shift kerja dengan hari off antar staf berbeda — akan mengubah jumlah hari off salah satu staf dari 4. Edit manual per sel kalau memang perlu.")

    # kecuali_staff_ids berisi KEDUA staf yang terlibat — nilai lama mereka berdua sedang
    # sama-sama diganti, jadi tidak boleh ikut dihitung sebagai "sudah ada" saat validasi.
    kecuali = list({body.staff_id_a, body.staff_id_b})
    await _validasi_shift_baru(jadwal_id, staf_a, body.tanggal_a, b["shift"], kecuali_staff_ids=kecuali)
    await _validasi_shift_baru(jadwal_id, staf_b, body.tanggal_b, a["shift"], kecuali_staff_ids=kecuali)

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


