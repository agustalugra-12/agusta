"""Payroll — Penggajian Staff, Kasbon, & Service Charge (2026-07-20, permintaan user).

Owner-only (semua endpoint pakai `require_owner`) - data gaji & kasbon staf sensitif,
tidak ditampilkan ke resepsionis/staf biasa lewat modul ini.

Data model (3 collection baru, independen dari `staff_kerja`/roster shift):
- `db.staff_profil`  — daftar staf untuk payroll (nama, posisi, gaji_pokok, aktif) — owner
                        bebas isi/edit sendiri, TIDAK terikat ke staff_kerja.
- `db.kasbon`         — catatan kasbon per staf. Tiap entri simpan `nominal` (jumlah kasbon
                        asli) & `sisa` (belum terpotong dari payroll) - berkurang FIFO
                        (tanggal terlama duluan) begitu payroll ditandai "dibayar".
- `db.payroll`        — 1 dokumen per (staff_id, periode bulan). Semua nominal (gaji_pokok,
                        service_charge, tunjangan_lain, potongan_kasbon, potongan_lain) BISA
                        diedit manual oleh owner (permintaan eksplisit "flexible") - sistem
                        cuma PRE-FILL gaji_pokok dari staff_profil & potongan_kasbon dari
                        sisa kasbon aktif sebagai saran, bukan angka yang dipaksakan.
                        Status draft -> dibayar (finalisasi: baru di titik ini kasbon
                        BENAR-BENAR terpotong - draft tidak menyentuh saldo kasbon sama
                        sekali, supaya aman diedit/dihapus sebelum final).
"""
from core import *

PAYROLL_STATUS = ["draft", "dibayar"]


# ---- Staff Profil ----

@api.get("/staff-profil")
async def list_staff_profil(aktif: Optional[bool] = None, user: dict = Depends(require_owner)):
    q: Dict[str, Any] = {}
    if aktif is not None:
        q["aktif"] = aktif
    staff = await db.staff_profil.find(q, {"_id": 0}).sort("nama", 1).to_list(500)
    # Lampirkan total kasbon aktif per staf (informasional, memudahkan owner lihat sekilas
    # tanpa buka tab Kasbon terpisah).
    for s in staff:
        s["kasbon_aktif"] = await _total_kasbon_aktif(s["id"])
    return staff


@api.post("/staff-profil")
async def create_staff_profil(body: StaffProfilCreate, user: dict = Depends(require_owner)):
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()), "nama": body.nama.strip(), "posisi": body.posisi.strip(),
        "gaji_pokok": max(0, int(body.gaji_pokok or 0)), "aktif": body.aktif,
        "catatan": body.catatan.strip(), "created_at": now, "updated_at": now,
        "created_by": user["nama"],
    }
    await db.staff_profil.insert_one(doc)
    await log_activity(user, "create_staff_profil", f"Tambah staf payroll: {doc['nama']}")
    doc.pop("_id", None)
    return doc


@api.put("/staff-profil/{sid}")
async def update_staff_profil(sid: str, body: StaffProfilUpdate, user: dict = Depends(require_owner)):
    s = await db.staff_profil.find_one({"id": sid})
    if not s:
        raise HTTPException(404, "Staf tidak ditemukan")
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "nama" in upd:
        upd["nama"] = upd["nama"].strip()
    if "posisi" in upd:
        upd["posisi"] = upd["posisi"].strip()
    if "catatan" in upd:
        upd["catatan"] = upd["catatan"].strip()
    if "gaji_pokok" in upd:
        upd["gaji_pokok"] = max(0, int(upd["gaji_pokok"]))
    upd["updated_at"] = now_iso()
    await db.staff_profil.update_one({"id": sid}, {"$set": upd})
    await log_activity(user, "update_staff_profil", f"Update staf payroll: {s['nama']}")
    return await db.staff_profil.find_one({"id": sid}, {"_id": 0})


@api.delete("/staff-profil/{sid}")
async def delete_staff_profil(sid: str, user: dict = Depends(require_owner)):
    s = await db.staff_profil.find_one({"id": sid})
    if not s:
        raise HTTPException(404, "Staf tidak ditemukan")
    if await db.payroll.count_documents({"staff_id": sid}):
        raise HTTPException(400, "Staf ini sudah punya riwayat payroll - nonaktifkan saja (aktif=false), jangan dihapus supaya riwayat tetap utuh")
    await db.staff_profil.delete_one({"id": sid})
    await db.kasbon.delete_many({"staff_id": sid})
    await log_activity(user, "delete_staff_profil", f"Hapus staf payroll: {s['nama']}")
    return {"ok": True}


# ---- Kasbon ----

async def _total_kasbon_aktif(staff_id: str) -> int:
    kasbon_aktif = await db.kasbon.find({"staff_id": staff_id, "sisa": {"$gt": 0}}, {"_id": 0, "sisa": 1}).to_list(500)
    return sum(int(k["sisa"]) for k in kasbon_aktif)


async def _potong_kasbon_fifo(staff_id: str, jumlah: int) -> int:
    """Kurangi kasbon AKTIF staf ini FIFO (tanggal terlama duluan) sebesar `jumlah`. Return
    jumlah yang BENAR-BENAR terpotong (bisa < jumlah diminta kalau saldo kasbon aktif tidak
    cukup - tidak pernah membuat sisa negatif)."""
    if jumlah <= 0:
        return 0
    kasbon_aktif = await db.kasbon.find(
        {"staff_id": staff_id, "sisa": {"$gt": 0}}, {"_id": 0}
    ).sort("tanggal", 1).to_list(500)
    sisa_potong = jumlah
    total_terpotong = 0
    for k in kasbon_aktif:
        if sisa_potong <= 0:
            break
        potong = min(int(k["sisa"]), sisa_potong)
        baru = int(k["sisa"]) - potong
        await db.kasbon.update_one({"id": k["id"]}, {"$set": {
            "sisa": baru, "lunas": baru == 0, "updated_at": now_iso(),
        }})
        sisa_potong -= potong
        total_terpotong += potong
    return total_terpotong


@api.get("/kasbon")
async def list_kasbon(staff_id: Optional[str] = None, hanya_aktif: bool = False, user: dict = Depends(require_owner)):
    q: Dict[str, Any] = {}
    if staff_id:
        q["staff_id"] = staff_id
    if hanya_aktif:
        q["sisa"] = {"$gt": 0}
    return await db.kasbon.find(q, {"_id": 0}).sort("tanggal", -1).to_list(1000)


@api.post("/kasbon")
async def create_kasbon(body: KasbonCreate, user: dict = Depends(require_owner)):
    s = await db.staff_profil.find_one({"id": body.staff_id})
    if not s:
        raise HTTPException(404, "Staf tidak ditemukan")
    if body.nominal <= 0:
        raise HTTPException(400, "Nominal kasbon harus lebih dari 0")
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()), "staff_id": body.staff_id, "staff_nama": s["nama"],
        "nominal": int(body.nominal), "sisa": int(body.nominal), "lunas": False,
        "tanggal": body.tanggal, "alasan": body.alasan.strip(),
        "created_at": now, "updated_at": now, "created_by": user["nama"],
    }
    await db.kasbon.insert_one(doc)
    await log_activity(user, "create_kasbon", f"Catat kasbon {s['nama']}: Rp{body.nominal:,}".replace(",", "."))
    doc.pop("_id", None)
    return doc


@api.put("/kasbon/{kid}")
async def update_kasbon(kid: str, body: KasbonUpdate, user: dict = Depends(require_owner)):
    k = await db.kasbon.find_one({"id": kid})
    if not k:
        raise HTTPException(404, "Kasbon tidak ditemukan")
    upd = {kk: v for kk, v in body.model_dump().items() if v is not None}
    if "alasan" in upd:
        upd["alasan"] = upd["alasan"].strip()
    if "sisa" in upd:
        upd["sisa"] = max(0, int(upd["sisa"]))
        upd["lunas"] = upd["sisa"] == 0
    upd["updated_at"] = now_iso()
    await db.kasbon.update_one({"id": kid}, {"$set": upd})
    await log_activity(user, "update_kasbon", f"Update kasbon {k['staff_nama']}")
    return await db.kasbon.find_one({"id": kid}, {"_id": 0})


@api.delete("/kasbon/{kid}")
async def delete_kasbon(kid: str, user: dict = Depends(require_owner)):
    k = await db.kasbon.find_one({"id": kid})
    if not k:
        raise HTTPException(404, "Kasbon tidak ditemukan")
    await db.kasbon.delete_one({"id": kid})
    await log_activity(user, "delete_kasbon", f"Hapus kasbon {k['staff_nama']}: Rp{k['nominal']:,}".replace(",", "."))
    return {"ok": True}


# ---- Payroll ----

def _hitung_total(p: Dict[str, Any]) -> int:
    return (
        int(p.get("gaji_pokok") or 0) + int(p.get("service_charge") or 0) + int(p.get("tunjangan_lain") or 0)
        - int(p.get("potongan_kasbon") or 0) - int(p.get("potongan_lain") or 0)
    )


@api.get("/payroll")
async def list_payroll(periode: Optional[str] = None, staff_id: Optional[str] = None, user: dict = Depends(require_owner)):
    q: Dict[str, Any] = {}
    if periode:
        q["periode"] = periode
    if staff_id:
        q["staff_id"] = staff_id
    return await db.payroll.find(q, {"_id": 0}).sort([("periode", -1), ("staff_nama", 1)]).to_list(1000)


@api.post("/payroll")
async def create_payroll(body: PayrollCreate, user: dict = Depends(require_owner)):
    s = await db.staff_profil.find_one({"id": body.staff_id})
    if not s:
        raise HTTPException(404, "Staf tidak ditemukan")
    if await db.payroll.find_one({"staff_id": body.staff_id, "periode": body.periode}):
        raise HTTPException(400, f"Payroll {s['nama']} untuk periode {body.periode} sudah ada - edit yang sudah ada, jangan buat duplikat")

    gaji_pokok = body.gaji_pokok if body.gaji_pokok is not None else int(s.get("gaji_pokok") or 0)
    kotor = gaji_pokok + body.service_charge + body.tunjangan_lain
    # Saran potongan kasbon: SEMUA sisa kasbon aktif, dibatasi maksimal sebesar penghasilan
    # kotor bulan ini (supaya tidak otomatis membuat take-home negatif) - owner tetap bebas
    # mengubah angka ini manual (mis. mencicil sebagian saja) sebelum ditandai dibayar.
    saran_potongan_kasbon = min(await _total_kasbon_aktif(body.staff_id), max(0, kotor))
    potongan_kasbon = body.potongan_kasbon if body.potongan_kasbon is not None else saran_potongan_kasbon

    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()), "staff_id": body.staff_id, "staff_nama": s["nama"],
        "periode": body.periode, "status": "draft",
        "gaji_pokok": gaji_pokok, "service_charge": int(body.service_charge),
        "tunjangan_lain": int(body.tunjangan_lain), "potongan_kasbon": int(potongan_kasbon),
        "potongan_lain": int(body.potongan_lain), "catatan": body.catatan.strip(),
        "created_at": now, "updated_at": now, "created_by": user["nama"],
        "dibayar_at": None, "dibayar_by": None,
    }
    doc["total_diterima"] = _hitung_total(doc)
    await db.payroll.insert_one(doc)
    await log_activity(user, "create_payroll", f"Buat payroll {s['nama']} periode {body.periode}")
    doc.pop("_id", None)
    return doc


@api.put("/payroll/{pid}")
async def update_payroll(pid: str, body: PayrollUpdate, user: dict = Depends(require_owner)):
    p = await db.payroll.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Payroll tidak ditemukan")
    if p["status"] == "dibayar":
        raise HTTPException(400, "Payroll yang sudah dibayar tidak bisa diedit - kasbon sudah terpotong permanen, buat catatan koreksi terpisah kalau perlu")
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "catatan" in upd:
        upd["catatan"] = upd["catatan"].strip()
    if upd.get("status") and upd["status"] not in PAYROLL_STATUS:
        raise HTTPException(400, f"Status harus salah satu dari: {', '.join(PAYROLL_STATUS)}")
    if upd.pop("status", None) == "dibayar":
        raise HTTPException(400, "Pakai POST /payroll/{id}/tandai-dibayar untuk finalisasi, bukan endpoint ini (supaya potongan kasbon diproses benar)")
    merged = {**p, **upd}
    merged["total_diterima"] = _hitung_total(merged)
    upd["total_diterima"] = merged["total_diterima"]
    upd["updated_at"] = now_iso()
    await db.payroll.update_one({"id": pid}, {"$set": upd})
    await log_activity(user, "update_payroll", f"Update payroll {p['staff_nama']} periode {p['periode']}")
    return await db.payroll.find_one({"id": pid}, {"_id": 0})


@api.post("/payroll/{pid}/tandai-dibayar")
async def bayar_payroll(pid: str, user: dict = Depends(require_owner)):
    """Finalisasi: potongan_kasbon di dokumen ini BENAR-BENAR dipotong dari saldo kasbon
    aktif staf (FIFO) di titik ini - draft sebelumnya tidak pernah menyentuh saldo kasbon,
    supaya aman diedit/dihapus tanpa efek samping sebelum benar-benar dibayar."""
    p = await db.payroll.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Payroll tidak ditemukan")
    if p["status"] == "dibayar":
        raise HTTPException(400, "Payroll ini sudah ditandai dibayar sebelumnya")
    terpotong = await _potong_kasbon_fifo(p["staff_id"], int(p.get("potongan_kasbon") or 0))
    now = now_iso()
    await db.payroll.update_one({"id": pid}, {"$set": {
        "status": "dibayar", "potongan_kasbon_terpotong_aktual": terpotong,
        "dibayar_at": now, "dibayar_by": user["nama"], "updated_at": now,
    }})
    await log_activity(
        user, "bayar_payroll",
        f"Tandai dibayar payroll {p['staff_nama']} periode {p['periode']}: Rp{p['total_diterima']:,}".replace(",", "."),
    )
    return await db.payroll.find_one({"id": pid}, {"_id": 0})


@api.delete("/payroll/{pid}")
async def delete_payroll(pid: str, user: dict = Depends(require_owner)):
    p = await db.payroll.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Payroll tidak ditemukan")
    if p["status"] == "dibayar":
        raise HTTPException(400, "Payroll yang sudah dibayar tidak bisa dihapus - riwayat & potongan kasbon harus tetap tercatat")
    await db.payroll.delete_one({"id": pid})
    await log_activity(user, "delete_payroll", f"Hapus draft payroll {p['staff_nama']} periode {p['periode']}")
    return {"ok": True}
