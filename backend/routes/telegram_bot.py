from core import *
import asyncio
import re
import secrets as pysecrets
import httpx
from openai import OpenAI
from routes.reports import report_summary, report_kas_metode_bayar

_openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

OWNER_AI_SYSTEM_PROMPT = """Kamu asisten pribadi owner Pelangi Homestay lewat Telegram — bukan
robot pembaca laporan. Jawab natural, santai, kayak asisten manusia yang benar-benar paham
kondisi hotel saat ini: boleh kasih insight singkat atau soroti hal yang perlu perhatian owner,
bukan cuma menyalin ulang angka mentah. Jawab SESUAI pertanyaan owner (kalau dia tanya spesifik
soal komplain, fokus jawab itu, tidak perlu dump semua angka). JANGAN PERNAH mengarang data yang
tidak ada di konteks di bawah — kalau owner tanya sesuatu yang datanya tidak tersedia, jujur
bilang belum ada datanya. Jawaban ringkas (maks beberapa paragraf pendek), enak dibaca di HP,
Bahasa Indonesia santai tapi sopan."""

# ---- Telegram Bot: owner (laporan ringkas on-demand) & staff (kirim pengeluaran foto+teks) ----
# Dua bot terpisah (bukan satu bot dibedakan lewat role) sesuai yang user sudah buat sendiri
# lewat @BotFather. Linking akun PMS <-> chat Telegram pakai kode sekali pakai (6 digit,
# berlaku 10 menit) yang di-generate dari halaman Profil, dikirim user via /start <kode>.

WIB = timezone(timedelta(hours=7))
UPLOAD_DIR = ROOT_DIR / "uploads" / "pengeluaran"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

BOT_CONFIG = {
    "owner": {"token": TELEGRAM_OWNER_BOT_TOKEN, "secret": TELEGRAM_OWNER_WEBHOOK_SECRET, "role": "owner"},
    "staff": {"token": TELEGRAM_STAFF_BOT_TOKEN, "secret": TELEGRAM_STAFF_WEBHOOK_SECRET, "role": "resepsionis"},
}
_DUMMY_USER = {"id": "telegram-bot", "nama": "Telegram Bot", "role": "owner"}
_bot_username_cache: Dict[str, str] = {}


def _rp(n) -> str:
    return "Rp " + f"{int(n or 0):,}".replace(",", ".")


async def _telegram_api(bot_token: str, method: str, **params) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(f"https://api.telegram.org/bot{bot_token}/{method}", json=params)
        return resp.json()


async def _kirim_pesan(bot_token: str, chat_id: Any, text: str):
    if not bot_token:
        return
    try:
        await _telegram_api(bot_token, "sendMessage", chat_id=chat_id, text=text)
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal kirim pesan Telegram ke {chat_id}: {e}")


async def _get_bot_username(kind: str) -> str:
    if kind in _bot_username_cache:
        return _bot_username_cache[kind]
    token = BOT_CONFIG[kind]["token"]
    if not token:
        return ""
    try:
        r = await _telegram_api(token, "getMe")
        username = (r.get("result") or {}).get("username", "")
        if username:
            _bot_username_cache[kind] = username
        return username
    except Exception:
        return ""


async def _unduh_foto_telegram(bot_token: str, file_id: str) -> Optional[str]:
    """Download foto dari Telegram Bot API, simpan ke disk lokal, return path publik
    (/uploads/pengeluaran/...) yang di-serve lewat StaticFiles di server.py."""
    try:
        info = await _telegram_api(bot_token, "getFile", file_id=file_id)
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            return None
        async with httpx.AsyncClient(timeout=20) as http:
            resp = await http.get(f"https://api.telegram.org/file/bot{bot_token}/{file_path}")
            resp.raise_for_status()
        ext = file_path.rsplit(".", 1)[-1] if "." in file_path else "jpg"
        fname = f"{uuid.uuid4().hex}.{ext}"
        (UPLOAD_DIR / fname).write_bytes(resp.content)
        return f"/uploads/pengeluaran/{fname}"
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal unduh foto Telegram: {e}")
        return None


async def _ringkasan_owner_fallback_text() -> str:
    """Fallback template kalau OPENAI_API_KEY belum/tidak dikonfigurasi — dipakai juga
    sebagai bagian dari konteks yang disuplai ke AI (_kumpulkan_konteks_bisnis)."""
    s = await report_summary(user=_DUMMY_USER)
    today = datetime.now(timezone.utc).date().isoformat()
    kas = await report_kas_metode_bayar(from_date=today, to_date=today, user=_DUMMY_USER)
    r = s["rooms"]
    terisi = r.get("day_use", 0) + r.get("menginap", 0)
    return (
        f"📊 Ringkasan Pelangi Homestay\n\n"
        f"🏨 Okupansi: {terisi}/{s['total_rooms']} kamar terisi\n"
        f"   Kosong: {r.get('kosong', 0)} · Dipesan hari ini: {r.get('dipesan_hari_ini', 0)} · Perlu dibersihkan: {r.get('perlu_dibersihkan', 0)}\n"
        f"👥 Tamu check-in hari ini: {s['tamu_hari_ini']}\n\n"
        f"💰 Pendapatan hari ini: {_rp(s['pendapatan_hari_ini'])}\n"
        f"   Tunai: {_rp(kas['tunai'])} · QRIS: {_rp(kas['qris'])} · Transfer: {_rp(kas['transfer'])}\n"
        f"💸 Pengeluaran hari ini: {_rp(s['pengeluaran_hari_ini'])}\n\n"
        f"📈 Bulan ini: Pendapatan {_rp(s['pendapatan_bulan_ini'])} · Laba Bersih {_rp(s['laba_bersih_bulan_ini'])}"
    )


async def _kumpulkan_konteks_bisnis() -> str:
    """Snapshot kondisi bisnis yang lebih dalam dari sekadar angka pendapatan — dipasok ke
    AI supaya owner bisa tanya apa saja (komplain, stok, housekeeping, dst) bukan cuma
    laporan keuangan, dan jawabannya tetap akurat (bukan karangan AI)."""
    s = await report_summary(user=_DUMMY_USER)
    today = datetime.now(timezone.utc).date().isoformat()
    kas = await report_kas_metode_bayar(from_date=today, to_date=today, user=_DUMMY_USER)
    r = s["rooms"]

    issues = await db.issues.find(
        {"status": {"$in": ["open", "in_progress"]}}, {"_id": 0, "tipe": 1, "room_nomor": 1, "deskripsi": 1, "status": 1}
    ).to_list(50)
    issues_teks = "Tidak ada komplain/maintenance aktif." if not issues else "\n".join(
        f"  - [{'Komplain' if it['tipe'] == 'complaint' else 'Maintenance'}] Kamar {it.get('room_nomor') or '-'}: {it['deskripsi']} (status: {it['status']})"
        for it in issues
    )

    hk_antrian = await db.rooms.count_documents({"status": "perlu_dibersihkan"})

    semua_produk = await db.products.find(
        {"aktif": True}, {"_id": 0, "nama": 1, "kategori": 1, "stok": 1, "stok_minimal": 1}
    ).sort("kategori", 1).to_list(200)
    per_kategori: Dict[str, list] = {}
    for p in semua_produk:
        per_kategori.setdefault(p["kategori"], []).append(p)
    stok_teks_parts = []
    for kat, produk_list in per_kategori.items():
        if kat == "laundry":
            continue
        detail = ", ".join(
            f"{p['nama']} ({p['stok']}{' — MENIPIS' if p['stok'] < p.get('stok_minimal', 0) else ''})"
            for p in produk_list
        )
        stok_teks_parts.append(f"  - {kat}: {detail}")
    stok_teks = "\n".join(stok_teks_parts) if stok_teks_parts else "Belum ada data produk."

    return (
        f"Okupansi: {r.get('day_use', 0) + r.get('menginap', 0)}/{s['total_rooms']} kamar terisi "
        f"(kosong {r.get('kosong', 0)}, dipesan hari ini {r.get('dipesan_hari_ini', 0)}, "
        f"perlu dibersihkan {r.get('perlu_dibersihkan', 0)}, maintenance {r.get('maintenance', 0)})\n"
        f"Tamu check-in hari ini: {s['tamu_hari_ini']}, check-out hari ini: {s['checkout_hari_ini']}\n"
        f"Pendapatan hari ini: {_rp(s['pendapatan_hari_ini'])} "
        f"(Tunai {_rp(kas['tunai'])}, QRIS {_rp(kas['qris'])}, Transfer {_rp(kas['transfer'])})\n"
        f"Pendapatan service hari ini: {_rp(s['pendapatan_service_hari_ini'])}\n"
        f"Pengeluaran hari ini: {_rp(s['pengeluaran_hari_ini'])}\n"
        f"Bulan ini: Pendapatan {_rp(s['pendapatan_bulan_ini'])}, Laba Bersih {_rp(s['laba_bersih_bulan_ini'])}\n"
        f"Kamar antre dibersihkan (housekeeping): {hk_antrian}\n"
        f"Komplain & Maintenance aktif:\n{issues_teks}\n"
        f"Stok produk (di luar laundry):\n{stok_teks}"
    )


async def _balasan_ai_owner(pesan_masuk: str) -> str:
    if not _openai_client:
        return await _ringkasan_owner_fallback_text()
    konteks = await _kumpulkan_konteks_bisnis()
    try:
        resp = await asyncio.to_thread(
            _openai_client.chat.completions.create,
            model="gpt-4o-mini",
            temperature=0.6,
            messages=[
                {"role": "system", "content": OWNER_AI_SYSTEM_PROMPT},
                {"role": "user", "content": f"Data kondisi bisnis saat ini:\n{konteks}\n\nPesan owner: {pesan_masuk or '(owner buka chat tanpa pesan spesifik — kasih ringkasan singkat kondisi hari ini)'}"},
            ],
        )
        return resp.choices[0].message.content
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal generate balasan AI owner: {e}")
        return await _ringkasan_owner_fallback_text()


async def _laporan_harian_text() -> str:
    """Laporan akhir hari (dikirim otomatis jam 22:00 WIB ke owner & staff yang terhubung)."""
    s = await report_summary(user=_DUMMY_USER)
    today = datetime.now(timezone.utc).date().isoformat()
    kas = await report_kas_metode_bayar(from_date=today, to_date=today, user=_DUMMY_USER)
    tanggal = datetime.now(timezone.utc).astimezone(WIB).strftime("%d %B %Y")
    return (
        f"📋 Laporan Akhir Hari — {tanggal}\n\n"
        f"Total Pendapatan: {_rp(s['pendapatan_hari_ini'])}\n"
        f"  Tunai: {_rp(kas['tunai'])}\n"
        f"  QRIS: {_rp(kas['qris'])}\n"
        f"  Transfer: {_rp(kas['transfer'])}\n"
        f"Total Service: {_rp(s['pendapatan_service_hari_ini'])}\n\n"
        f"Terima kasih atas kerja hari ini! 🙏"
    )


_NOMINAL_RE = re.compile(r"^\s*([\d.,]+)\s*(.*)$", re.DOTALL)


async def _proses_pengeluaran_staff(user_doc: dict, file_id: str, caption: str) -> str:
    caption = (caption or "").strip()
    m = _NOMINAL_RE.match(caption)
    if not m:
        return "Format caption belum sesuai.\nKirim ulang foto dengan caption: <nominal> <keterangan>\nContoh: 50000 beli galon air"
    try:
        nominal = int(m.group(1).replace(".", "").replace(",", ""))
    except ValueError:
        return "Nominal tidak terbaca.\nKirim ulang foto dengan caption: <nominal> <keterangan>\nContoh: 50000 beli galon air"
    if nominal <= 0:
        return "Nominal harus lebih dari 0."
    deskripsi = m.group(2).strip() or "Pengeluaran via Telegram"
    foto_url = await _unduh_foto_telegram(BOT_CONFIG["staff"]["token"], file_id)
    doc = {
        "id": str(uuid.uuid4()), "tanggal": now_iso(), "kategori": "Operasional",
        "deskripsi": deskripsi, "nominal": nominal, "foto_url": foto_url or "",
        "user": user_doc["nama"], "user_id": user_doc["id"], "created_at": now_iso(),
        "source": "telegram",
    }
    await db.expenses.insert_one(doc)
    await log_activity(user_doc, "expense", f"Pengeluaran (Telegram) Operasional Rp{nominal:,}".replace(",", "."))
    return f"✅ Pengeluaran tercatat: {deskripsi} — {_rp(nominal)}" + ("" if foto_url else "\n(foto gagal diunduh, tapi pengeluaran tetap tercatat)")


async def _handle_link_code(kind: str, chat_id: Any, code: str) -> str:
    role = BOT_CONFIG[kind]["role"]
    u = await db.users.find_one({"telegram_link_code": code, "role": role})
    if not u:
        return "Kode tidak valid atau salah bot. Buat kode baru dari halaman Profil di PMS."
    expires = u.get("telegram_link_code_expires")
    if not expires or datetime.now(timezone.utc) > datetime.fromisoformat(expires):
        return "Kode sudah kedaluwarsa. Buat kode baru dari halaman Profil di PMS."
    await db.users.update_one(
        {"id": u["id"]},
        {"$set": {"telegram_chat_id": chat_id}, "$unset": {"telegram_link_code": "", "telegram_link_code_expires": ""}},
    )
    peran = "Owner" if role == "owner" else "Staff"
    lanjutan = "Kirim pesan apa saja untuk lihat ringkasan bisnis kapan pun." if kind == "owner" \
        else "Kirim foto struk dengan caption: <nominal> <keterangan> untuk catat pengeluaran."
    return f"✅ Berhasil terhubung sebagai {u['nama']} ({peran}).\n{lanjutan}"


async def _handle_telegram_update(kind: str, request: Request):
    secret = BOT_CONFIG[kind]["secret"]
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        raise HTTPException(403, "Invalid secret token")
    payload = await request.json()
    msg = payload.get("message") or payload.get("edited_message")
    if not msg or "chat" not in msg:
        return {"ok": True}

    chat_id = msg["chat"]["id"]
    token = BOT_CONFIG[kind]["token"]
    role = BOT_CONFIG[kind]["role"]
    text = (msg.get("text") or "").strip()

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            reply = await _handle_link_code(kind, chat_id, parts[1].strip())
        else:
            reply = "Halo! Buat kode link dari halaman Profil di PMS, lalu kirim /start <kode> ke sini untuk menghubungkan akun."
        await _kirim_pesan(token, chat_id, reply)
        return {"ok": True}

    u = await db.users.find_one({"telegram_chat_id": chat_id, "role": role})
    if not u:
        await _kirim_pesan(token, chat_id, "Akun belum terhubung. Buat kode link dari halaman Profil di PMS, lalu kirim /start <kode> ke sini.")
        return {"ok": True}

    if kind == "owner":
        await _kirim_pesan(token, chat_id, await _balasan_ai_owner(text))
    else:
        photos = msg.get("photo")
        if photos:
            file_id = photos[-1]["file_id"]  # elemen terakhir = resolusi terbesar
            reply = await _proses_pengeluaran_staff(u, file_id, msg.get("caption", ""))
        else:
            reply = "Kirim foto struk/nota dengan caption: <nominal> <keterangan>\nContoh: 50000 beli galon air"
        await _kirim_pesan(token, chat_id, reply)
    return {"ok": True}


@api.post("/webhook/telegram/owner")
async def webhook_telegram_owner(request: Request):
    return await _handle_telegram_update("owner", request)


@api.post("/webhook/telegram/staff")
async def webhook_telegram_staff(request: Request):
    return await _handle_telegram_update("staff", request)


@api.post("/profil/telegram/generate-code")
async def generate_telegram_link_code(user: dict = Depends(get_current_user)):
    kind = "owner" if user["role"] == "owner" else "staff"
    if not BOT_CONFIG[kind]["token"]:
        raise HTTPException(400, "Bot Telegram belum dikonfigurasi untuk role ini")
    code = "".join(pysecrets.choice("0123456789") for _ in range(6))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await db.users.update_one({"id": user["id"]}, {"$set": {"telegram_link_code": code, "telegram_link_code_expires": expires}})
    username = await _get_bot_username(kind)
    return {
        "code": code,
        "expires_at": expires,
        "bot_username": username,
        "deep_link": f"https://t.me/{username}?start={code}" if username else None,
    }


@api.get("/profil/telegram/status")
async def get_telegram_status(user: dict = Depends(get_current_user)):
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "telegram_chat_id": 1})
    return {"connected": bool(u and u.get("telegram_chat_id"))}


@api.post("/profil/telegram/putuskan")
async def unlink_telegram(user: dict = Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$unset": {"telegram_chat_id": ""}})
    return {"ok": True}


async def background_telegram_daily_report_loop():
    """Kirim laporan akhir hari ke semua user (owner+staff) yang sudah terhubung Telegram,
    sekali sehari jam 22:00 WIB. Cek tiap 5 menit, jaga guard `last_sent_date` supaya tidak
    dobel kirim kalau proses sempat cek 2x dalam jam yang sama."""
    last_sent_date = None
    while True:
        try:
            now_wib = datetime.now(timezone.utc).astimezone(WIB)
            if now_wib.hour == 22 and now_wib.date() != last_sent_date:
                teks = await _laporan_harian_text()
                users = await db.users.find({"telegram_chat_id": {"$ne": None}}, {"_id": 0}).to_list(200)
                for u in users:
                    kind = "owner" if u.get("role") == "owner" else "staff"
                    await _kirim_pesan(BOT_CONFIG[kind]["token"], u["telegram_chat_id"], teks)
                last_sent_date = now_wib.date()
        except Exception as e:
            logging.getLogger("telegram_bot").warning(f"Gagal kirim laporan harian Telegram: {e}")
        await asyncio.sleep(300)
