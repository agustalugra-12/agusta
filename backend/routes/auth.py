from core import *

# ---- Auth Endpoints ----
@api.post("/auth/register")
async def register(body: RegisterIn, _rl: None = Depends(rate_limiter(5, 60))):
    """Pendaftaran akun mandiri (halaman Daftar Akun, Fase 3). Akun baru dibuat dengan
    role 'resepsionis' dan status 'pending' — Owner harus mengaktifkannya lewat halaman
    Pengguna sebelum bisa login, konsisten dengan model akses berbasis undangan yang sudah
    ada (lihat POST /users)."""
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Format email tidak valid")
    if len(body.password) < 6:
        raise HTTPException(400, "Password minimal 6 karakter")
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email sudah terdaftar")
    doc = {
        "id": str(uuid.uuid4()),
        "nama": body.nama.strip(),
        "username": email,
        "email": email,
        "password_hash": hash_password(body.password),
        "role": "resepsionis",
        "status": "pending",
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    await log_activity(doc, "register", f"Pendaftaran akun mandiri {email}")
    return {"ok": True, "message": "Pendaftaran berhasil. Menunggu aktivasi Owner sebelum bisa masuk."}

@api.post("/auth/login")
async def login(body: LoginIn, response: Response, _rl: None = Depends(rate_limiter(10, 60))):
    u = await db.users.find_one({"username": body.username.lower()})
    if not u or not verify_password(body.password, u.get("password_hash", "")):
        raise HTTPException(401, "Username atau password salah")
    if u.get("status") in ("nonaktif", "pending"):
        raise HTTPException(403, "Akun belum aktif — hubungi Owner" if u.get("status") == "pending" else "Akun dinonaktifkan")
    token = create_token(u["id"], u["username"], u["role"])
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=7*24*3600, path="/")
    user_data = {k: v for k, v in u.items() if k not in ("_id", "password_hash")}
    await log_activity(u, "login", f"Login berhasil")
    return {"token": token, "user": user_data}

@api.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    await log_activity(user, "logout", "Logout")
    return {"ok": True}

@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user

@api.put("/auth/me")
async def update_me(body: MeUpdate, user: dict = Depends(get_current_user)):
    """Update profil sendiri (halaman Profil): nama, dan/atau password (wajib
    verifikasi password lama). Beda dari PUT /users/{id} yang owner-only dan
    bisa ubah role/status siapa saja tanpa password lama."""
    updates: Dict[str, Any] = {}
    if body.nama is not None and body.nama.strip():
        updates["nama"] = body.nama.strip()
    if body.password_baru:
        u = await db.users.find_one({"id": user["id"]})
        if not body.password_lama or not verify_password(body.password_lama, u.get("password_hash", "")):
            raise HTTPException(400, "Password lama tidak sesuai")
        updates["password_hash"] = hash_password(body.password_baru)
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
        await log_activity(user, "update_profile", "Update profil sendiri" + (" (ganti password)" if "password_hash" in updates else ""))
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return fresh

# ---- Users (Owner only) ----
@api.get("/users")
async def list_users(user: dict = Depends(require_owner)):
    items = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(500)
    return items

@api.post("/users")
async def create_user(body: UserCreate, user: dict = Depends(require_owner)):
    if body.role not in ("owner", "resepsionis"):
        raise HTTPException(400, "Role tidak valid")
    if await db.users.find_one({"username": body.username.lower()}):
        raise HTTPException(400, "Username sudah dipakai")
    doc = {
        "id": str(uuid.uuid4()),
        "nama": body.nama,
        "username": body.username.lower(),
        "password_hash": hash_password(body.password),
        "role": body.role,
        "status": "aktif",
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    await log_activity(user, "create_user", f"Buat pengguna {body.username}")
    return {k: v for k, v in doc.items() if k not in ("password_hash", "_id")}

@api.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, user: dict = Depends(require_owner)):
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(404, "User tidak ditemukan")
    updates: Dict[str, Any] = {}
    if body.nama is not None: updates["nama"] = body.nama
    if body.role is not None: updates["role"] = body.role
    if body.status is not None: updates["status"] = body.status
    if body.password:
        updates["password_hash"] = hash_password(body.password)
    if updates:
        await db.users.update_one({"id": user_id}, {"$set": updates})
    await log_activity(user, "update_user", f"Update user {u['username']}")
    return {"ok": True}

@api.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_owner)):
    if user_id == user["id"]:
        raise HTTPException(400, "Tidak dapat menghapus diri sendiri")
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(404, "User tidak ditemukan")
    await db.users.delete_one({"id": user_id})
    await log_activity(user, "delete_user", f"Hapus user {u['username']}")
    return {"ok": True}

