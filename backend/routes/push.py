from core import *
import asyncio
import json
from pywebpush import webpush, WebPushException

# ---- Web Push Notifications (PWA) ----
# Notifikasi push lewat service worker (booking baru, pembayaran diterima, komplain baru,
# kamar perlu dibersihkan) — tetap sampai ke staf/owner walau tab PMS tidak sedang dibuka.
# Subscription (per browser/device) disimpan di db.push_subscriptions, terikat ke user_id +
# role supaya bisa broadcast per-role (mis. semua resepsionis) atau ke satu user spesifik.

class PushSubscribeBody(BaseModel):
    endpoint: str
    keys: Dict[str, str]

class PushUnsubscribeBody(BaseModel):
    endpoint: str


@api.get("/push/vapid-public-key")
async def get_vapid_public_key():
    return {"public_key": VAPID_PUBLIC_KEY}


@api.get("/push/status")
async def push_status(user: dict = Depends(get_current_user)):
    count = await db.push_subscriptions.count_documents({"user_id": user["id"]})
    return {"subscribed": count > 0, "vapid_configured": bool(VAPID_PUBLIC_KEY)}


@api.post("/push/subscribe")
async def push_subscribe(body: PushSubscribeBody, user: dict = Depends(get_current_user)):
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(400, "Push notification belum dikonfigurasi di server")
    await db.push_subscriptions.update_one(
        {"endpoint": body.endpoint},
        {
            "$set": {
                "endpoint": body.endpoint, "keys": body.keys,
                "user_id": user["id"], "role": user["role"], "updated_at": now_iso(),
            },
            "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now_iso()},
        },
        upsert=True,
    )
    return {"ok": True}


@api.post("/push/unsubscribe")
async def push_unsubscribe(body: PushUnsubscribeBody, user: dict = Depends(get_current_user)):
    await db.push_subscriptions.delete_one({"endpoint": body.endpoint, "user_id": user["id"]})
    return {"ok": True}


def _send_one(sub: dict, payload: str) -> bool:
    """True = subscription masih valid (atau error sementara, jangan dihapus).
    False = subscription kadaluwarsa/dicabut user (410/404), boleh dibersihkan."""
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIM_EMAIL},
        )
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            return False
        logging.getLogger("push").warning(f"Gagal kirim push ke {sub.get('endpoint','?')[:60]}: {e}")
        return True
    except Exception as e:
        logging.getLogger("push").warning(f"Gagal kirim push: {e}")
        return True


async def send_push(title: str, body: str, url: str = "/", role: Optional[str] = None, user_id: Optional[str] = None):
    """Kirim push ke semua subscription milik `role` (mis. "owner"/"resepsionis") atau ke
    satu `user_id` spesifik. Best-effort: gagal ke 1 device tidak menghentikan device lain,
    dan tidak pernah melempar exception ke pemanggil (dipanggil fire-and-forget dari alur
    bisnis utama seperti booking/pembayaran/komplain — kegagalan push tidak boleh membatalkan
    transaksi bisnis)."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return
    try:
        q: Dict[str, Any] = {}
        if user_id:
            q["user_id"] = user_id
        elif role:
            q["role"] = role
        subs = await db.push_subscriptions.find(q, {"_id": 0}).to_list(500)
        if not subs:
            return
        payload = json.dumps({"title": title, "body": body, "url": url})
        expired = []
        for sub in subs:
            ok = await asyncio.to_thread(_send_one, sub, payload)
            if not ok:
                expired.append(sub["endpoint"])
        if expired:
            await db.push_subscriptions.delete_many({"endpoint": {"$in": expired}})
    except Exception as e:
        logging.getLogger("push").warning(f"send_push gagal total: {e}")
