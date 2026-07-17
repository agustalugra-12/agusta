from core import *

# ---- Business Rules ----
# PMS = "Business Platform" (kesepakatan arsitektur dengan user 2026-07-17): kebijakan
# operasional (DP, cancellation, jam checkin/checkout, promo, kebijakan umum) dimiliki &
# dikelola staf/owner DI SINI — bukan di ai-chat-bot ("Brain Platform"). ai-chat-bot menarik
# data ini lewat endpoint integrasi (`routes/integrasi_ai_bot.py`, GET .../rules) supaya AI
# bisa menjawab tamu dengan kebijakan yang akurat & satu sumber kebenaran, bukan menghafal
# teks bebas yang bisa basi/menyimpang dari kebijakan asli.
BUSINESS_RULE_CATEGORIES = {"dp", "cancellation", "checkin", "checkout", "promo", "smoking", "pet", "other"}


@api.get("/business-rules/categories")
async def business_rule_categories(user: dict = Depends(get_current_user)):
    return sorted(BUSINESS_RULE_CATEGORIES)


@api.get("/business-rules")
async def list_business_rules(category: Optional[str] = None, user: dict = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if category:
        q["category"] = category
    return await db.business_rules.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.post("/business-rules")
async def create_business_rule(body: BusinessRuleIn, user: dict = Depends(require_owner)):
    if body.category not in BUSINESS_RULE_CATEGORIES:
        raise HTTPException(400, f"Kategori harus salah satu dari: {', '.join(sorted(BUSINESS_RULE_CATEGORIES))}")
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(400, "Judul & deskripsi wajib diisi")
    doc = {
        "id": str(uuid.uuid4()), "category": body.category, "title": body.title.strip(),
        "description": body.description.strip(), "value": body.value, "is_active": body.is_active,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.business_rules.insert_one(doc)
    await log_activity(user, "create_business_rule", f"{body.category}: {body.title}")
    doc.pop("_id", None)
    return doc


@api.put("/business-rules/{rule_id}")
async def update_business_rule(rule_id: str, body: BusinessRuleUpdate, user: dict = Depends(require_owner)):
    existing = await db.business_rules.find_one({"id": rule_id})
    if not existing:
        raise HTTPException(404, "Rule tidak ditemukan")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "category" in updates and updates["category"] not in BUSINESS_RULE_CATEGORIES:
        raise HTTPException(400, f"Kategori harus salah satu dari: {', '.join(sorted(BUSINESS_RULE_CATEGORIES))}")
    updates["updated_at"] = now_iso()
    await db.business_rules.update_one({"id": rule_id}, {"$set": updates})
    await log_activity(user, "update_business_rule", f"{existing['category']}: {existing['title']}")
    doc = await db.business_rules.find_one({"id": rule_id}, {"_id": 0})
    return doc


@api.delete("/business-rules/{rule_id}")
async def delete_business_rule(rule_id: str, user: dict = Depends(require_owner)):
    existing = await db.business_rules.find_one({"id": rule_id})
    if not existing:
        raise HTTPException(404, "Rule tidak ditemukan")
    await db.business_rules.delete_one({"id": rule_id})
    await log_activity(user, "delete_business_rule", f"{existing['category']}: {existing['title']}")
    return {"ok": True}
