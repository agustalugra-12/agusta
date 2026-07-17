from core import *
import asyncio
import base64
import json
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
soal komplain, fokus jawab itu, tidak perlu dump semua angka). Kalau owner minta daftar
pengeluaran/transaksi yang panjang, tampilkan SEMUA item yang ada di data (jangan dipotong/
diringkas jadi cuma total), rapikan dalam list per baris. JANGAN PERNAH mengarang data yang
tidak ada di konteks di bawah — kalau owner tanya sesuatu yang datanya tidak tersedia, jujur
bilang belum ada datanya.

Catatan: pesan yang jelas-jelas berisi pengeluaran (nominal + keterangan) sudah otomatis
tercatat sistem SEBELUM sampai ke kamu — kamu tidak perlu (dan tidak akan) diminta menanganinya.
Pesan yang sampai ke kamu berarti bukan pengeluaran, atau owner sedang tanya balik soal itu.

PENTING — batasan keras: kamu TIDAK bisa mengubah stok produk, status/booking kamar, atau
mencatat pemasukan/income dalam bentuk apa pun — tidak peduli owner memintanya seperti apa.
Kalau diminta itu, tolak dengan sopan dan arahkan ke dashboard PMS. Jangan pernah berpura-pura
atau mengklaim sudah melakukan perubahan semacam itu.

Jawaban enak dibaca di HP, Bahasa Indonesia santai tapi sopan."""

EXPENSE_EXTRACT_PROMPT = """Kamu mengekstrak daftar PENGELUARAN (uang keluar/belanja/beban biaya)
dari pesan staf/owner hotel. Balas HANYA JSON: {"items": [{"nominal": <integer rupiah>, "deskripsi": "<keterangan singkat>"}, ...]}.
Satu pesan boleh berisi beberapa pengeluaran sekaligus — pisahkan jadi beberapa item.
Nominal harus angka murni (tanpa "Rp", titik, atau koma pemisah ribuan) — kalau ditulis "500rb"
atau "500 ribu" artinya 500000, "1jt"/"1 juta" artinya 1000000.
Kalau pesan TIDAK menyebutkan pengeluaran sama sekali (pertanyaan, sapaan, obrolan biasa, atau
justru menyebut PEMASUKAN/pendapatan bukan pengeluaran), balas {"items": []} — JANGAN mengarang
nominal yang tidak jelas disebutkan di pesan."""

EXPENSE_PHOTO_EXTRACT_PROMPT = """Kamu mengekstrak PENGELUARAN dari FOTO nota/struk/bukti
pembayaran hotel. Balas HANYA JSON: {"items": [{"nominal": <integer rupiah>, "deskripsi": "<keterangan singkat>"}]}.

ATURAN WAJIB — SELALU balas TEPAT SATU item per struk (array "items" isinya 1 elemen saja),
walau struk berisi banyak barang:
- "nominal" = TOTAL AKHIR yang dibayar di struk itu (baris "Total"/"Total Bayar"/"Grand Total"
  paling bawah) — BUKAN salah satu subtotal/harga per barang.
- "deskripsi" = ringkasan singkat barang/jasa yang dibeli (gabungkan nama item kalau lebih dari
  satu, mis. "Galon air & bensin"), atau nama toko/keperluan kalau item tidak jelas.
- JANGAN PERNAH memecah 1 struk jadi beberapa item terpisah — itu akan membuat pengeluaran
  tercatat DOBEL (subtotal per barang + total sekaligus).

Nominal harus angka murni tanpa "Rp"/titik/koma pemisah ribuan.
Kalau pengirim menyertakan catatan teks tambahan, jadikan itu konteks untuk keterangan saja —
nominal tetap harus dari TOTAL di struk, kecuali struk sama sekali tidak menunjukkan angka total
yang jelas (baru boleh pakai angka dari catatan kalau ada).
Kalau gambar SAMA SEKALI bukan nota/struk/bukti pembayaran, atau totalnya tidak terbaca sama
sekali, balas {"items": []} — JANGAN mengarang angka."""

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


_TELEGRAM_MAX_LEN = 4000  # batas resmi 4096 karakter/pesan, kasih margin


async def _kirim_pesan(bot_token: str, chat_id: Any, text: str):
    """Kirim pesan, dipecah jadi beberapa bagian kalau melewati batas panjang pesan Telegram
    (mis. owner minta daftar pengeluaran panjang) — supaya sendMessage tidak gagal diam-diam."""
    if not bot_token:
        return
    potongan = [text[i:i + _TELEGRAM_MAX_LEN] for i in range(0, len(text), _TELEGRAM_MAX_LEN)] or [text]
    for bagian in potongan:
        try:
            await _telegram_api(bot_token, "sendMessage", chat_id=chat_id, text=bagian)
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


async def _unduh_foto_telegram(bot_token: str, file_id: str) -> Optional[tuple]:
    """Download foto dari Telegram Bot API, simpan ke disk lokal. Return (path publik
    /uploads/pengeluaran/... yang di-serve lewat StaticFiles di server.py, isi bytes, mime) —
    bytes dikembalikan sekalian (bukan cuma path) supaya AI vision bisa baca langsung tanpa
    perlu download foto yang sama dua kali."""
    try:
        info = await _telegram_api(bot_token, "getFile", file_id=file_id)
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            return None
        async with httpx.AsyncClient(timeout=20) as http:
            resp = await http.get(f"https://api.telegram.org/file/bot{bot_token}/{file_path}")
            resp.raise_for_status()
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "jpg"
        mime = "image/png" if ext == "png" else "image/jpeg"
        fname = f"{uuid.uuid4().hex}.{ext}"
        (UPLOAD_DIR / fname).write_bytes(resp.content)
        return f"/uploads/pengeluaran/{fname}", resp.content, mime
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

    # Daftar pengeluaran 30 hari terakhir (bukan cuma total) — supaya owner bisa minta
    # "list-in semua pengeluaran bulan ini" dan AI benar-benar menyebut tiap item, bukan
    # cuma angka total. Dibatasi 60 entri terbaru untuk jaga ukuran konteks & batas pesan Telegram.
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    expenses_30d = await db.expenses.find(
        {"tanggal": {"$gte": since_30d}}, {"_id": 0, "tanggal": 1, "kategori": 1, "deskripsi": 1, "nominal": 1, "user": 1}
    ).sort("tanggal", -1).to_list(60)
    if expenses_30d:
        expenses_teks = "\n".join(
            f"  - {e['tanggal'][:10]} · {e['kategori']} · {e['deskripsi']} · {_rp(e['nominal'])} · dicatat oleh {e.get('user', '-')}"
            for e in expenses_30d
        )
    else:
        expenses_teks = "Tidak ada pengeluaran tercatat 30 hari terakhir."

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
        f"Stok produk (di luar laundry):\n{stok_teks}\n"
        f"Daftar pengeluaran 30 hari terakhir (terbaru dulu, maks 60 entri):\n{expenses_teks}"
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


async def _pendapatan_kamar_per_tipe_hari_ini() -> Dict[str, int]:
    """Pendapatan kamar hari ini dipecah Menginap vs Day Use + jumlah kamar/transaksi.
    Day Use SELALU lewat `checkins` (checkin langsung ATAU dari booking yang sudah check-in —
    /checkins tidak pernah dipakai utk menginap, lihat docstring create_checkin) — booking
    day_use yang lunas tapi BELUM check-in ditambah terpisah dari `bookings` (checkin_id belum
    ada) supaya tidak dobel dengan yang sudah masuk checkins. Menginap SELALU lewat `bookings`
    (checkins tidak pernah representasikan menginap sama sekali) — tidak ada risiko dobel hitung."""
    today_iso = datetime.now(timezone.utc).date().isoformat()

    co_today = await db.checkins.find(
        {"jam_checkout": {"$gte": today_iso}, "status": "selesai"}, {"_id": 0, "total": 1}
    ).to_list(500)
    dayuse_total = sum(c.get("total", 0) for c in co_today)
    dayuse_kamar = len(co_today)

    dayuse_bk_belum_checkin = await db.bookings.find({
        "tipe": "day_use", "payment_status": "paid", "paid_at": {"$gte": today_iso},
        "checkin_id": {"$exists": False},
    }, {"_id": 0, "total": 1}).to_list(200)
    dayuse_total += sum(int(b.get("total") or 0) for b in dayuse_bk_belum_checkin)
    dayuse_kamar += len(dayuse_bk_belum_checkin)

    menginap_bk = await db.bookings.find({
        "tipe": "menginap", "payment_status": "paid", "paid_at": {"$gte": today_iso},
    }, {"_id": 0, "total": 1}).to_list(200)
    menginap_total = sum(int(b.get("total") or 0) for b in menginap_bk)
    menginap_kamar = len(menginap_bk)

    return {
        "dayuse_total": dayuse_total, "dayuse_kamar": dayuse_kamar,
        "menginap_total": menginap_total, "menginap_kamar": menginap_kamar,
    }


async def _laporan_harian_text() -> str:
    """Laporan akhir hari (dikirim otomatis jam 22:00 WIB ke owner & staff yang terhubung) —
    rinci: pemasukan dipecah menginap/day use (+ jumlah kamar) & metode bayar, pengeluaran
    dengan total DAN daftar detail per item."""
    s = await report_summary(user=_DUMMY_USER)
    today_iso = datetime.now(timezone.utc).date().isoformat()
    kas = await report_kas_metode_bayar(from_date=today_iso, to_date=today_iso, user=_DUMMY_USER)
    kamar = await _pendapatan_kamar_per_tipe_hari_ini()
    tanggal = datetime.now(timezone.utc).astimezone(WIB).strftime("%d %B %Y")

    total_pemasukan = kamar["dayuse_total"] + kamar["menginap_total"] + s["pendapatan_kasir_hari_ini"] + s["pendapatan_service_hari_ini"]

    exp_today = await db.expenses.find(
        {"tanggal": {"$gte": today_iso}}, {"_id": 0, "kategori": 1, "deskripsi": 1, "nominal": 1, "user": 1}
    ).sort("nominal", -1).to_list(200)
    total_pengeluaran = sum(e.get("nominal", 0) for e in exp_today)
    if exp_today:
        pengeluaran_detail = "\n".join(
            f"  - {e.get('deskripsi', '-')} ({e.get('kategori', '-')}): {_rp(e['nominal'])} — {e.get('user', '-')}"
            for e in exp_today
        )
    else:
        pengeluaran_detail = "  Tidak ada pengeluaran hari ini."

    return (
        f"📋 Laporan Akhir Hari — {tanggal}\n\n"
        f"💰 PEMASUKAN: {_rp(total_pemasukan)}\n"
        f"  🛏 Menginap: {_rp(kamar['menginap_total'])} ({kamar['menginap_kamar']} kamar)\n"
        f"  ☀️ Day Use: {_rp(kamar['dayuse_total'])} ({kamar['dayuse_kamar']} kamar)\n"
        f"  🛒 Kasir (POS): {_rp(s['pendapatan_kasir_hari_ini'])}\n"
        f"  🧰 Service: {_rp(s['pendapatan_service_hari_ini'])}\n\n"
        f"  Metode Bayar (Kasir & Check-In):\n"
        f"    Tunai: {_rp(kas['tunai'])} · QRIS: {_rp(kas['qris'])} · Transfer: {_rp(kas['transfer'])}\n\n"
        f"💸 PENGELUARAN: {_rp(total_pengeluaran)}\n"
        f"{pengeluaran_detail}\n\n"
        f"Terima kasih atas kerja hari ini! 🙏"
    )


_NOMINAL_RE = re.compile(r"^\s*([\d.,]+)\s*(.*)$", re.DOTALL)


async def _catat_pengeluaran_items(user_doc: dict, items: list, foto_url: str = "") -> str:
    """Satu-satunya jalur insert ke db.expenses dari bot Telegram (owner & staff) — sengaja
    TIDAK PERNAH menyentuh db.bookings/kasir/payment_log, jadi struktural tidak mungkin
    'pemasukan' tercatat lewat sini apa pun yang diminta/dikirim user."""
    baris, total = [], 0
    for it in items:
        doc = {
            "id": str(uuid.uuid4()), "tanggal": now_iso(), "kategori": "Operasional",
            "deskripsi": it["deskripsi"], "nominal": it["nominal"], "foto_url": foto_url or "",
            "user": user_doc["nama"], "user_id": user_doc["id"], "created_at": now_iso(),
            "source": "telegram",
        }
        await db.expenses.insert_one(doc)
        await log_activity(user_doc, "expense", f"Pengeluaran (Telegram) Operasional Rp{it['nominal']:,}".replace(",", "."))
        baris.append(f"  - {it['deskripsi']}: {_rp(it['nominal'])}")
        total += it["nominal"]
    prefix = "✅ Pengeluaran tercatat:" if len(items) == 1 else f"✅ {len(items)} pengeluaran tercatat:"
    teks = prefix + "\n" + "\n".join(baris)
    if len(items) > 1:
        teks += f"\n\nTotal: {_rp(total)}"
    return teks


async def _ekstrak_pengeluaran_dari_teks(text: str) -> list:
    """Ekstrak 0/1/banyak item pengeluaran dari pesan bebas via AI (mis. "bensin 500rb,
    service mobil 200rb"). List kosong berarti pesan bukan pengeluaran (pertanyaan/obrolan)."""
    if not _openai_client or not text.strip():
        return []
    try:
        resp = await asyncio.to_thread(
            _openai_client.chat.completions.create,
            model="gpt-4o-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXPENSE_EXTRACT_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        out = []
        for it in (data.get("items") or []):
            try:
                nominal = int(it.get("nominal"))
                deskripsi = str(it.get("deskripsi") or "").strip()
                if nominal > 0 and deskripsi:
                    out.append({"nominal": nominal, "deskripsi": deskripsi})
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal ekstrak pengeluaran dari teks: {e}")
        return []


async def _ekstrak_pengeluaran_dari_foto(image_bytes: bytes, mime: str, caption: str) -> list:
    """AI baca langsung isi foto struk/nota (vision, gpt-4o-mini) — pengganti utama caption
    berformat "<nominal> <keterangan>" (permintaan user 2026-07-17: staf/owner kirim foto
    harusnya langsung dibaca, bukan diminta format ulang)."""
    if not _openai_client:
        return []
    try:
        b64 = base64.b64encode(image_bytes).decode()
        user_content = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
        if caption.strip():
            user_content.append({"type": "text", "text": f"Catatan dari pengirim: {caption.strip()}"})
        resp = await asyncio.to_thread(
            _openai_client.chat.completions.create,
            model="gpt-4o-mini", temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXPENSE_PHOTO_EXTRACT_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        out = []
        for it in (data.get("items") or []):
            try:
                nominal = int(it.get("nominal"))
                deskripsi = str(it.get("deskripsi") or "").strip()
                if nominal > 0 and deskripsi:
                    out.append({"nominal": nominal, "deskripsi": deskripsi})
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal ekstrak pengeluaran dari foto (vision): {e}")
        return []


async def _proses_pengeluaran_foto(user_doc: dict, bot_token: str, file_id: str, caption: str) -> str:
    """AI baca foto struk langsung (vision) — caption TIDAK LAGI wajib berformat khusus,
    cukup kirim foto struk apa adanya. Caption (kalau ada) dipakai sebagai konteks tambahan.
    Fallback ke parsing caption manual "<nominal> <keterangan>" kalau AI gagal baca gambar
    tapi caption-nya kebetulan sudah dalam format lama itu (kompatibel mundur)."""
    caption = (caption or "").strip()
    hasil_unduh = await _unduh_foto_telegram(bot_token, file_id)
    if not hasil_unduh:
        return "Gagal mengunduh foto dari Telegram, coba kirim ulang."
    foto_url, image_bytes, mime = hasil_unduh

    items = await _ekstrak_pengeluaran_dari_foto(image_bytes, mime, caption)
    if not items and caption:
        m = _NOMINAL_RE.match(caption)
        if m:
            try:
                nominal = int(m.group(1).replace(".", "").replace(",", ""))
                if nominal > 0:
                    items = [{"nominal": nominal, "deskripsi": m.group(2).strip() or "Pengeluaran via Telegram"}]
            except ValueError:
                pass
    if not items:
        return (
            "Belum berhasil membaca nominal pengeluaran dari foto ini — pastikan foto struk/nota "
            "jelas & nominalnya terbaca.\nBisa juga kirim ulang dengan caption manual: "
            "<nominal> <keterangan>\nContoh: 50000 beli galon air"
        )
    return await _catat_pengeluaran_items(user_doc, items, foto_url)


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
    lanjutan = (
        "Tanya apa saja soal kondisi bisnis, atau kirim pengeluaran (teks/foto) — mis. \"bensin 500rb, service mobil 200rb\"."
        if kind == "owner" else
        "Kirim pengeluaran lewat teks (mis. \"50000 beli galon air\") atau foto struk dengan caption serupa."
    )
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

    photos = msg.get("photo")
    if photos:
        file_id = photos[-1]["file_id"]  # elemen terakhir = resolusi terbesar
        reply = await _proses_pengeluaran_foto(u, token, file_id, msg.get("caption", ""))
    elif text:
        items = await _ekstrak_pengeluaran_dari_teks(text)
        if items:
            reply = await _catat_pengeluaran_items(u, items)
        elif kind == "owner":
            reply = await _balasan_ai_owner(text)
        else:
            reply = "Kirim pengeluaran lewat teks, mis. \"50000 beli galon air\" (boleh lebih dari satu sekaligus), atau foto struk dengan caption serupa."
    else:
        reply = "Kirim teks atau foto struk untuk catat pengeluaran." if kind == "staff" else await _balasan_ai_owner("")
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


async def kirim_alert_owner(pesan: str):
    """Kirim pesan alert ke SEMUA owner yang sudah terhubung Telegram — kanal tambahan di
    luar Web Push PMS (Payment Alert & Action Center), supaya owner tetap tahu ada
    pembayaran masuk meski PMS-nya tidak sedang dibuka di HP/laptop mana pun."""
    owners = await db.users.find({"role": "owner", "telegram_chat_id": {"$ne": None}}, {"_id": 0, "telegram_chat_id": 1}).to_list(50)
    for u in owners:
        await _kirim_pesan(BOT_CONFIG["owner"]["token"], u["telegram_chat_id"], pesan)


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
