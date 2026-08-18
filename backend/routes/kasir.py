from core import *

# ---- Kasir / Transactions ----
@api.post("/kasir")
async def create_kasir(body: KasirCreate, user: dict = Depends(get_current_user),
                       property_id: str = Depends(get_active_property)):
    if not body.items:
        raise HTTPException(400, "Keranjang kosong")
    rows = []
    subtotal = 0
    for it in body.items:
        p = await db.products.find_one(scoped({"id": it.product_id}, property_id))
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
        "property_id": property_id,
    }
    await db.kasir.insert_one(doc)
    # decrement stok
    for r in rows:
        if r["kategori"] != "laundry":
            await db.products.update_one({"id": r["product_id"]}, {"$inc": {"stok": -r["qty"]}})
    await log_activity(user, "kasir", f"Transaksi kasir {trx_no} total Rp{total:,}".replace(",", "."))
    from routes.rekening import auto_posting
    await auto_posting("pemasukan", total_bayar, "Penjualan Kasir", f"Transaksi {trx_no}", property_id)
    doc.pop("_id", None)
    return doc

@api.get("/kasir")
async def list_kasir(from_date: Optional[str] = None, to_date: Optional[str] = None,
                     user: dict = Depends(get_current_user),
                     property_id: str = Depends(get_active_property)):
    q: Dict[str, Any] = {}
    if from_date or to_date:
        # Bug nyata (2026-08-18, sama akar masalah dgn Laporan Pengeluaran - lihat
        # catatan lengkap di routes/expenses.py) - kasir.timestamp SELALU timestamp
        # UTC penuh, perbandingan string mentah thd from_date/to_date "YYYY-MM-DD"
        # leksikografis SELALU gagal utk hari yg dimaksud. Pakai wita_date_range_to_utc
        # (pola sama reports.py/laporan_analitik.py).
        start_utc, end_utc = wita_date_range_to_utc(from_date or "1970-01-01", to_date or "2999-12-31")
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = start_utc
        if to_date: rng["$lte"] = end_utc
        q["timestamp"] = rng
    items = await db.kasir.find(scoped(q, property_id), {"_id": 0}).sort("timestamp", -1).to_list(1000)
    return items

