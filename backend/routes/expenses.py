from core import *

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
