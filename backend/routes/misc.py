from core import *

@api.get("/audit-log")
async def list_audit(limit: int = 200, user: dict = Depends(get_current_user)):
    items = await db.audit_log.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return items

# ---- Housekeeping ----
@api.get("/housekeeping")
async def list_housekeeping(user: dict = Depends(get_current_user)):
    items = await db.housekeeping_log.find({}, {"_id": 0}).sort("tanggal", -1).to_list(500)
    return items

@api.get("/")
async def root():
    return {"app": "Pelangi Homestay API", "status": "ok"}

