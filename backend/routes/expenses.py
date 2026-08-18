from core import *

# ---- Expenses ----
@api.post("/expenses")
async def create_expense(body: ExpenseCreate, user: dict = Depends(get_current_user),
                         property_id: str = Depends(get_active_property)):
    doc = {
        "id": str(uuid.uuid4()),
        "tanggal": body.tanggal or now_iso(),
        "kategori": body.kategori,
        "deskripsi": body.deskripsi,
        "nominal": body.nominal,
        "foto_url": body.foto_url or "",
        "user": user["nama"],
        "user_id": user["id"],
        "created_at": now_iso(),
        "property_id": property_id,
    }
    await db.expenses.insert_one(doc)
    await log_activity(user, "expense", f"Pengeluaran {body.kategori} Rp{body.nominal:,}".replace(",", "."))
    from routes.rekening import auto_posting
    # (2026-08-02, bug nyata ditemukan - input pengeluaran BACKDATE tanggal 1 Agustus
    # sambil ngerjain task ini) - `body.tanggal` TIDAK PERNAH diteruskan ke auto_posting(),
    # jadi pengeluaran yang di-backdate/postdate tetap keposting ke rekening_transaksi
    # dgn tanggal HARI INI (default auto_posting kalau tanggal=None), bikin laporan kas
    # harian tanggal yang benar jadi tidak lengkap & tanggal input jadi salah nambah.
    await auto_posting("pengeluaran", body.nominal, body.kategori, body.deskripsi, property_id, tanggal=body.tanggal)
    doc.pop("_id", None)
    return doc

@api.get("/expenses")
async def list_expenses(from_date: Optional[str] = None, to_date: Optional[str] = None,
                        user: dict = Depends(get_current_user),
                        property_id: str = Depends(get_active_property)):
    # Bug nyata ditemukan Agus (2026-08-18) - "Laporan Pengeluaran" tanggal 18 Agustus
    # tampil KOSONG padahal 2 pengeluaran asli ada hari itu, sementara tab "Ringkasan"
    # (laporan_analitik.py, sudah pakai wita_date_range_to_utc) benar menampilkannya.
    # Root cause: from_date/to_date dari frontend selalu "YYYY-MM-DD" polos (date picker),
    # TAPI expenses.tanggal HAMPIR SELALU timestamp UTC PENUH (create_expense's
    # `body.tanggal or now_iso()` - form web Pengeluaran.jsx TIDAK PUNYA input tanggal
    # sama sekali, Telegram bot & payroll auto-post jg selalu now_iso()) - perbandingan
    # STRING MENTAH "2026-08-18T05:24:55+00:00" <= "2026-08-18" itu FALSE (string lebih
    # panjang yg diawali string pembanding dianggap "lebih besar" scr leksikografis) -
    # SEMUA pengeluaran hari itu gagal lolos filter $lte, bukan cuma kasus tepi. Fix:
    # konversi from_date/to_date (dimaksud tanggal WITA, sama asumsi dgn seluruh laporan
    # lain di app ini) ke rentang UTC yg presisi via wita_date_range_to_utc - pola SAMA
    # persis yg sudah dipakai reports.py/laporan_analitik.py, cuma belum pernah diterapkan
    # di endpoint ini.
    q: Dict[str, Any] = {}
    if from_date or to_date:
        start_utc, end_utc = wita_date_range_to_utc(from_date or "1970-01-01", to_date or "2999-12-31")
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = start_utc
        if to_date: rng["$lte"] = end_utc
        q["tanggal"] = rng
    items = await db.expenses.find(scoped(q, property_id), {"_id": 0}).sort("tanggal", -1).to_list(1000)
    return items

@api.delete("/expenses/{eid}")
async def delete_expense(eid: str, user: dict = Depends(require_owner),
                         property_id: str = Depends(get_active_property)):
    await db.expenses.delete_one(scoped({"id": eid}, property_id))
    await log_activity(user, "delete_expense", f"Hapus pengeluaran {eid}")
    return {"ok": True}
