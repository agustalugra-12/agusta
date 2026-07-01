from core import *

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

