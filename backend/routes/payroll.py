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
import io
import base64
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

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
        "no_hp": body.no_hp.strip(),
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
    if "no_hp" in upd:
        upd["no_hp"] = upd["no_hp"].strip()
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


def _tanggal_expense_payroll(periode: str) -> str:
    """periode 'YYYY-MM' -> tanggal expense ('YYYY-MM-DD') = akhir bulan periode itu,
    DIBATASI maksimal hari ini - supaya gaji periode Juli yang difinalisasi 8 Agustus
    tetap tercatat sebagai pengeluaran akhir Juli (bukan tanggal bayarnya), TAPI gaji
    yang difinalisasi lebih awal (mis. tanggal 21 Juli, sebelum bulan itu selesai) tidak
    diberi tanggal masa depan (31 Juli) yang bisa ke-filter keluar dari semua rentang
    laporan default "s/d hari ini"."""
    y, m = map(int, periode.split("-"))
    akhir = datetime(y, m + 1, 1) - timedelta(days=1) if m < 12 else datetime(y, 12, 31)
    hari_ini = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return min(akhir.strftime("%Y-%m-%d"), hari_ini)


@api.post("/payroll/{pid}/tandai-dibayar")
async def bayar_payroll(pid: str, user: dict = Depends(require_owner)):
    """Finalisasi: potongan_kasbon di dokumen ini BENAR-BENAR dipotong dari saldo kasbon
    aktif staf (FIFO) di titik ini - draft sebelumnya tidak pernah menyentuh saldo kasbon,
    supaya aman diedit/dihapus tanpa efek samping sebelum benar-benar dibayar.

    Juga membuat 1 dokumen `db.expenses` (kategori "Gaji") di titik yang sama, supaya
    Laporan Keuangan otomatis ikut mencatat pengeluaran gaji tanpa entry manual dobel.
    `tanggal` expense = akhir bulan `periode` dibatasi maksimal hari ini (lihat
    `_tanggal_expense_payroll`) - gaji periode Juli yang baru difinalisasi 8 Agustus
    tetap masuk laporan Juli, konsisten dengan cara laporan OTA prepaid membaca
    `paid_at` bukan tanggal konfirmasi, tanpa pernah menaruh tanggal masa depan."""
    p = await db.payroll.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Payroll tidak ditemukan")
    if p["status"] == "dibayar":
        raise HTTPException(400, "Payroll ini sudah ditandai dibayar sebelumnya")
    terpotong = await _potong_kasbon_fifo(p["staff_id"], int(p.get("potongan_kasbon") or 0))
    now = now_iso()
    expense_id = str(uuid.uuid4())
    await db.payroll.update_one({"id": pid}, {"$set": {
        "status": "dibayar", "potongan_kasbon_terpotong_aktual": terpotong,
        "dibayar_at": now, "dibayar_by": user["nama"], "updated_at": now,
        "expense_id": expense_id,
    }})
    await db.expenses.insert_one({
        "id": expense_id,
        "tanggal": _tanggal_expense_payroll(p["periode"]),
        "kategori": "Gaji",
        "deskripsi": f"Gaji {p['staff_nama']} periode {p['periode']}",
        "nominal": int(p["total_diterima"]),
        "foto_url": "",
        "user": user["nama"],
        "user_id": user["id"],
        "created_at": now,
        "source": "payroll",
        "payroll_id": pid,
    })
    await log_activity(
        user, "bayar_payroll",
        f"Tandai dibayar payroll {p['staff_nama']} periode {p['periode']}: Rp{p['total_diterima']:,}".replace(",", "."),
    )
    from routes.rekening import auto_posting
    await auto_posting("pengeluaran", int(p["total_diterima"]), "Gaji", f"Gaji {p['staff_nama']} periode {p['periode']}",
                        tanggal=_tanggal_expense_payroll(p["periode"]))
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


# ---- Slip Gaji PDF & Kirim WhatsApp (2026-07-20) ----

def _fmt_rp_pdf(n) -> str:
    return f"Rp {int(n or 0):,}".replace(",", ".")


def generate_slip_gaji_pdf(p: Dict[str, Any], staff: Dict[str, Any]) -> bytes:
    """Slip gaji 1 halaman A5 - pola sama dengan generate_voucher_pdf di email_service.py
    (reportlab canvas sederhana), memuat rincian gaji pokok/service charge/tunjangan/
    potongan kasbon & lainnya, plus total diterima."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    w, h = A5
    y = h - 20 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(15 * mm, y, "Pelangi Homestay")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    c.drawString(15 * mm, y, f"Slip Gaji — Periode {p['periode']}")
    y -= 10 * mm
    c.line(15 * mm, y, w - 15 * mm, y)
    y -= 8 * mm

    def baris(label, value, bold=False):
        nonlocal y
        c.setFont("Helvetica", 10)
        c.drawString(15 * mm, y, label)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawRightString(w - 15 * mm, y, str(value))
        y -= 7 * mm

    baris("Nama", staff["nama"], bold=True)
    if staff.get("posisi"):
        baris("Posisi", staff["posisi"])
    y -= 3 * mm
    c.line(15 * mm, y, w - 15 * mm, y)
    y -= 8 * mm

    baris("Gaji Pokok", _fmt_rp_pdf(p["gaji_pokok"]))
    if p.get("service_charge"):
        baris("Service Charge", _fmt_rp_pdf(p["service_charge"]))
    if p.get("tunjangan_lain"):
        baris("Tunjangan Lain", _fmt_rp_pdf(p["tunjangan_lain"]))
    if p.get("potongan_kasbon"):
        baris("Potongan Kasbon", f"-{_fmt_rp_pdf(p['potongan_kasbon'])}")
    if p.get("potongan_lain"):
        baris("Potongan Lain", f"-{_fmt_rp_pdf(p['potongan_lain'])}")
    y -= 3 * mm
    c.line(15 * mm, y, w - 15 * mm, y)
    y -= 8 * mm
    baris("Total Diterima", _fmt_rp_pdf(p["total_diterima"]), bold=True)

    if p.get("catatan"):
        y -= 5 * mm
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(15 * mm, y, f"Catatan: {p['catatan']}")

    y = 20 * mm
    c.setFont("Helvetica", 8)
    status_label = "LUNAS DIBAYAR" if p["status"] == "dibayar" else "DRAFT (belum final)"
    c.drawString(15 * mm, y, f"Status: {status_label}")
    if p.get("dibayar_at"):
        c.drawString(15 * mm, y - 5 * mm, f"Dibayar: {p['dibayar_at'][:10]}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


@api.post("/payroll/{pid}/kirim-wa")
async def kirim_slip_gaji_wa(pid: str, user: dict = Depends(require_owner)):
    """Generate slip gaji PDF & kirim langsung ke WhatsApp staf yang bersangkutan (butuh
    no_hp terisi di staff_profil, dan koneksi WhatsApp/webhook aktif - sama seperti jalur
    _kirim_via_provider yang sudah dipakai notifikasi booking/pembatalan)."""
    p = await db.payroll.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Payroll tidak ditemukan")
    s = await db.staff_profil.find_one({"id": p["staff_id"]}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Data staf tidak ditemukan")
    if not s.get("no_hp"):
        raise HTTPException(400, f"Nomor WhatsApp {s['nama']} belum diisi - lengkapi dulu di Data Staf")

    pdf_bytes = generate_slip_gaji_pdf(p, s)
    caption = (
        f"Slip gaji {s['nama']} periode {p['periode']} — Total diterima {_fmt_rp_pdf(p['total_diterima'])}."
        + (" (Draft, belum final)" if p["status"] != "dibayar" else "")
    )
    from routes.pesan_whatsapp import _kirim_dokumen_via_provider
    ok, err = await _kirim_dokumen_via_provider(
        s["no_hp"], f"slip-gaji-{p['periode']}.pdf", "application/pdf",
        base64.b64encode(pdf_bytes).decode("ascii"), caption,
    )
    await log_activity(
        user, "kirim_slip_gaji_wa",
        f"Kirim slip gaji {s['nama']} periode {p['periode']} via WA: {'berhasil' if ok else f'gagal ({err})'}",
    )
    if not ok:
        raise HTTPException(502, f"Gagal mengirim ke WhatsApp: {err}")
    return {"ok": True}
