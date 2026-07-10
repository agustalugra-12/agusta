from core import *
from urllib.parse import urlencode

import httpx
from fastapi.responses import RedirectResponse

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GMAIL_SCOPES = "openid email https://www.googleapis.com/auth/gmail.readonly"

# State CSRF sementara untuk alur OAuth (single-process, in-memory — cukup karena backend
# ini berjalan sebagai satu instance uvicorn, lihat server.py).
_oauth_states: Dict[str, datetime] = {}
_STATE_TTL_MINUTES = 10


def _new_state() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_STATE_TTL_MINUTES)
    for s, t in list(_oauth_states.items()):
        if t < cutoff:
            _oauth_states.pop(s, None)
    state = uuid.uuid4().hex
    _oauth_states[state] = datetime.now(timezone.utc)
    return state


def _consume_state(state: str) -> bool:
    return _oauth_states.pop(state, None) is not None


@api.get("/otomasi-email/gmail/status")
async def gmail_status(user: dict = Depends(get_current_user)):
    conn = await db.integrations.find_one(
        {"provider": "gmail"}, {"_id": 0, "access_token": 0, "refresh_token": 0}
    )
    if not conn:
        return {"connected": False}
    return {"connected": True, "email": conn.get("email"), "connected_at": conn.get("connected_at")}


@api.get("/otomasi-email/gmail/connect")
async def gmail_connect(user: dict = Depends(require_owner)):
    """Bangun URL consent Google OAuth. Frontend melakukan redirect penuh (window.location)
    ke auth_url ini, bukan panggilan fetch biasa, karena Google butuh navigasi browser asli.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_OAUTH_REDIRECT_URI:
        raise HTTPException(500, "Integrasi Gmail belum dikonfigurasi di server (GOOGLE_CLIENT_ID/GOOGLE_OAUTH_REDIRECT_URI)")
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GMAIL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": _new_state(),
    }
    return {"auth_url": f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"}


@api.get("/otomasi-email/gmail/callback")
async def gmail_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    user: dict = Depends(require_owner),
):
    """Redirect target dari Google setelah pemilik akun memberi consent. Cookie sesi ikut
    terkirim karena ini navigasi top-level (samesite=lax), jadi require_owner tetap berlaku.
    """
    target = f"{os.environ.get('FRONTEND_URL', '')}/otomasi-email"
    if error:
        return RedirectResponse(f"{target}?gmail=error&reason={error}")
    if not code or not state or not _consume_state(state):
        return RedirectResponse(f"{target}?gmail=error&reason=state_invalid")

    async with httpx.AsyncClient(timeout=10) as http:
        token_resp = await http.post(GOOGLE_TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            return RedirectResponse(f"{target}?gmail=error&reason=token_exchange_failed")
        tokens = token_resp.json()

        email = None
        userinfo_resp = await http.get(
            GOOGLE_USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {tokens.get('access_token', '')}"}
        )
        if userinfo_resp.status_code == 200:
            email = userinfo_resp.json().get("email")

    existing = await db.integrations.find_one({"provider": "gmail"})
    refresh_token = tokens.get("refresh_token") or (existing or {}).get("refresh_token")
    # Google hanya mengirim refresh_token pada consent pertama; re-connect berikutnya
    # (tanpa consent baru) tetap pertahankan refresh_token lama supaya tidak putus.
    doc = {
        "provider": "gmail",
        "email": email,
        "access_token": tokens.get("access_token"),
        "refresh_token": refresh_token,
        "token_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat(),
        "scope": tokens.get("scope"),
        "connected_by": user["id"],
        "connected_at": now_iso(),
    }
    await db.integrations.update_one({"provider": "gmail"}, {"$set": doc}, upsert=True)
    await log_activity(user, "gmail_connect", f"Hubungkan Gmail: {email}")
    return RedirectResponse(f"{target}?gmail=connected")


@api.post("/otomasi-email/gmail/disconnect")
async def gmail_disconnect(user: dict = Depends(require_owner)):
    conn = await db.integrations.find_one({"provider": "gmail"})
    if not conn:
        raise HTTPException(404, "Gmail belum terhubung")
    token = conn.get("refresh_token") or conn.get("access_token")
    if token:
        async with httpx.AsyncClient(timeout=10) as http:
            try:
                await http.post(GOOGLE_REVOKE_ENDPOINT, data={"token": token})
            except Exception:
                pass  # revoke bersifat best-effort; koneksi lokal tetap dihapus
    await db.integrations.delete_one({"provider": "gmail"})
    await log_activity(user, "gmail_disconnect", f"Putuskan Gmail: {conn.get('email')}")
    return {"ok": True}
