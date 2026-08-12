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

WITA = timezone(timedelta(hours=8))  # Bedugul/Bali = WITA (UTC+8) - lihat catatan perbaikan 2026-08-07 di reservation_service.py
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


async def _kirim_pesan_dengan_tombol(bot_token: str, chat_id: Any, text: str, tombol: list) -> Optional[dict]:
    """Sama pola dgn _kirim_pesan, versi dgn inline keyboard (2026-08-12, PRD "Owner
    Control Center" Fase 1 - Action Center). TIDAK dipecah multi-bagian spt _kirim_pesan
    (pesan Action Center selalu pendek by design, daftar dibatasi 15 item) - kalau nanti
    butuh, tangani terpisah krn tombol cuma bisa nempel di 1 pesan. TIDAK pakai parse_mode
    (sama konvensi teks-polos _kirim_pesan) - hindari bug escaping Markdown di kode
    booking/rupiah yang mengandung "_"/".". Return `result` Telegram (ada `message_id`,
    dipakai _edit_pesan) atau None kalau gagal."""
    if not bot_token:
        return None
    try:
        r = await _telegram_api(bot_token, "sendMessage", chat_id=chat_id, text=text,
                                 reply_markup={"inline_keyboard": tombol})
        return r.get("result")
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal kirim pesan+tombol ke {chat_id}: {e}")
        return None


async def _edit_pesan(bot_token: str, chat_id: Any, message_id: int, text: str, tombol: Optional[list] = None):
    """Edit pesan yang sudah terkirim (2026-08-12) - dipakai navigasi Action Center (tap
    tombol -> pesan yang SAMA berubah isi+tombolnya, bukan kirim pesan baru tiap tap)."""
    try:
        params: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if tombol is not None:
            params["reply_markup"] = {"inline_keyboard": tombol}
        await _telegram_api(bot_token, "editMessageText", **params)
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal edit pesan {message_id} utk {chat_id}: {e}")


async def _answer_callback_query(bot_token: str, callback_query_id: str, text: str = ""):
    """WAJIB dipanggil tiap kali callback_query masuk (2026-08-12) - kalau tidak, tombol
    yang di-tap tetap terlihat "loading" (jam pasir) di UI Telegram walau aksinya sudah
    diproses server."""
    try:
        await _telegram_api(bot_token, "answerCallbackQuery", callback_query_id=callback_query_id, text=text)
    except Exception as e:
        logging.getLogger("telegram_bot").warning(f"Gagal answerCallbackQuery: {e}")


async def _label_properti(property_id: Optional[str]) -> str:
    """Label "[Nama Properti] " di depan judul incident (2026-08-12) - owner belum
    di-scope 1 properti di Action Center (lihat catatan di _render_daftar_incident),
    daftar tampil gabungan Pelangi+Harmoni, label ini yang membedakan sekilas pandang."""
    if not property_id:
        return ""
    p = await db.properties.find_one({"id": property_id}, {"_id": 0, "nama": 1})
    return f"[{p['nama']}] " if p else ""


async def _render_daftar_incident() -> tuple:
    """Render teks+tombol daftar Action Center (2026-08-12) - dipanggil dari command
    /aksi MAUPUN tombol "⬅️ Kembali" (callback_data "aksi"), makanya dipisah jadi fungsi
    sendiri drpd inline di 2 tempat."""
    from routes.incidents import list_open_incidents, SEVERITY_EMOJI
    incidents = await list_open_incidents()
    if not incidents:
        return "✅ Tidak ada incident terbuka saat ini.", []
    tombol = []
    for it in incidents[:15]:
        label = await _label_properti(it.get("property_id"))
        teks_tombol = f"{SEVERITY_EMOJI.get(it['severity'], '⚪')} {label}{it['title'][:45]}"
        tombol.append([{"text": teks_tombol, "callback_data": f"show:{it['id']}"}])
    return f"🗒 Action Center — {len(incidents)} incident terbuka:", tombol


async def _render_detail_incident(incident_id: str) -> tuple:
    from routes.incidents import get_incident, SEVERITY_EMOJI
    it = await get_incident(incident_id)
    if not it:
        return "Incident tidak ditemukan.", [[{"text": "⬅️ Kembali", "callback_data": "aksi"}]]
    label = await _label_properti(it.get("property_id"))
    teks = f"{SEVERITY_EMOJI.get(it['severity'], '⚪')} {label}{it['title']}\n\n{it['detail']}"
    if it["status"] == "resolved":
        return teks + "\n\n✅ Sudah selesai.", [[{"text": "⬅️ Kembali", "callback_data": "aksi"}]]
    tombol = []
    # Checkout Payment Protection (2026-08-12, §16) - HANYA event_type ini yang dapat
    # tombol override, SENGAJA tidak digeneralisasi ke semua incident (override checkout
    # itu aksi spesifik dgn efek nyata ke operasional, beda dari "Tandai Selesai" biasa
    # yang cuma menutup catatan).
    if it["event_type"] == "checkout_blocked" and it.get("meta", {}).get("checkin_id"):
        tombol.append([{"text": "🔐 Override & Izinkan Checkout", "callback_data": f"override_checkout:{incident_id}"}])
    tombol.append([{"text": "✅ Tandai Selesai", "callback_data": f"resolve:{incident_id}"}])
    tombol.append([{"text": "⬅️ Kembali", "callback_data": "aksi"}])
    return teks, tombol


async def _render_daftar_payment() -> tuple:
    """Payment Center (2026-08-12, PRD "Owner Control Center" §12-13, Fase 2 - MURNI
    monitoring, TIDAK mengubah perilaku sistem apa pun) - daftar booking Menginap/Day Use
    yang BELUM lunas (belum_bayar/dp), diurutkan check-in terdekat dulu (paling mendesak
    di atas). Reuse penuh status_bayar_booking() (core.py) - SATU sumber kebenaran yang
    sama dipakai halaman staf Pembayaran, bukan hitungan terpisah yang bisa menyimpang.

    Dibatasi status booking yang masih relevan (aktif/booking_pending/booking_paid/
    checked_in) - booking cancelled/checked_out tidak perlu muncul di sini (kalaupun
    belum lunas, itu bukan hal yang butuh tindakan owner lagi)."""
    bookings = await db.bookings.find(
        {"status": {"$in": ["aktif", "booking_pending", "booking_paid", "checked_in"]}},
        {"_id": 0, "id": 1, "kode": 1, "nama_tamu": 1, "room_nomor": 1, "tipe": 1,
         "total": 1, "payment_status": 1, "amount_due": 1, "jam_mulai": 1, "status": 1, "property_id": 1},
    ).sort("jam_mulai", 1).to_list(500)
    belum_lunas = []
    for b in bookings:
        sb = status_bayar_booking(b)
        if sb["status_bayar"] in ("belum_bayar", "dp"):
            belum_lunas.append((b, sb))
    if not belum_lunas:
        return "✅ Semua booking aktif sudah lunas.", []
    tombol = []
    for b, sb in belum_lunas[:15]:
        label = await _label_properti(b.get("property_id"))
        status_label = "Belum Bayar" if sb["status_bayar"] == "belum_bayar" else "DP"
        cek_in = "-"
        try:
            cek_in = datetime.fromisoformat(b["jam_mulai"]).strftime("%d/%m")
        except Exception:
            pass
        # Nominal SENGAJA tidak ditaruh di label tombol (Telegram batasi panjang teks
        # tombol, angka rupiah bisa kepotong di tengah & tampak salah) - lihat detail
        # lewat _render_detail_payment stlh tap, di sana ruang lebih longgar.
        teks_tombol = f"🟡 {label}{b.get('kode', b['id'])[:24]} · {status_label} · {cek_in}"
        tombol.append([{"text": teks_tombol, "callback_data": f"paydetail:{b['id']}"}])
    return f"💰 Payment Center — {len(belum_lunas)} booking belum lunas:", tombol


async def _render_detail_payment(booking_id: str) -> tuple:
    b = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not b:
        return "Booking tidak ditemukan.", [[{"text": "⬅️ Kembali", "callback_data": "pembayaran"}]]
    sb = status_bayar_booking(b)
    label = await _label_properti(b.get("property_id"))
    teks = (
        f"💰 {label}{b.get('kode')}\n\n"
        f"Tamu: {b.get('nama_tamu') or '-'}\n"
        f"Kamar: {b.get('room_nomor') or '-'} ({b.get('tipe')})\n"
        f"Status: {b.get('status')}\n\n"
        f"Total: {_rp(b.get('total'))}\n"
        f"Sudah dibayar: {_rp(sb['jumlah_dibayar'])}\n"
        f"Sisa: {_rp(sb['sisa_tagihan'])}"
    )
    return teks, [[{"text": "⬅️ Kembali", "callback_data": "pembayaran"}]]


async def _cari_booking(query: str, limit: int = 10) -> list:
    """Cari booking by kode ATAU nama tamu (2026-08-12, Booking Center - Fase 2 PRD).
    re.escape() (sama pola audit keamanan 2026-07-27 di routes/bookings.py GET /bookings)
    - query dari Telegram TETAP diperlakukan sbg teks harfiah, bukan pola regex, cegah
    ReDoS dari input bebas."""
    q_escaped = re.escape(query.strip())
    if not q_escaped:
        return []
    return await db.bookings.find(
        {"$or": [{"kode": {"$regex": q_escaped, "$options": "i"}},
                 {"nama_tamu": {"$regex": q_escaped, "$options": "i"}}]},
        {"_id": 0},
    ).sort("jam_mulai", -1).to_list(limit)


async def _render_hasil_cari_booking(query: str) -> tuple:
    hasil = await _cari_booking(query)
    if not hasil:
        return f"🔍 Tidak ada booking cocok dgn \"{query}\".", []
    tombol = []
    for b in hasil:
        label = await _label_properti(b.get("property_id"))
        cek_in = "-"
        try:
            cek_in = datetime.fromisoformat(b["jam_mulai"]).strftime("%d/%m")
        except Exception:
            pass
        teks_tombol = f"{label}{b.get('kode', b['id'])[:24]} · {b.get('nama_tamu') or '-'} · {cek_in}"
        tombol.append([{"text": teks_tombol[:60], "callback_data": f"bookdetail:{b['id']}"}])
    return f"🏨 {len(hasil)} booking cocok dgn \"{query}\":", tombol


async def _render_detail_booking(booking_id: str) -> tuple:
    """Booking 360 (2026-08-12) - detail lengkap 1 booking (bukan cuma sisi pembayaran
    spt _render_detail_payment, walau ada overlap - dipisah krn callback "kembali"-nya
    beda tujuan [balik ke hasil cari, bukan balik ke daftar Payment Center])."""
    b = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not b:
        return "Booking tidak ditemukan.", []
    sb = status_bayar_booking(b)
    label = await _label_properti(b.get("property_id"))
    ci = b.get("jam_mulai", "")[:16].replace("T", " ")
    co = b.get("jam_selesai", "")[:16].replace("T", " ")
    teks = (
        f"🏨 {label}{b.get('kode')}\n\n"
        f"Tamu: {b.get('nama_tamu') or '-'}\n"
        f"WhatsApp: {b.get('no_hp') or '-'}\n"
        f"Kamar: {b.get('room_nomor') or '-'} ({b.get('tipe')})\n"
        f"Check-in: {ci or '-'}\n"
        f"Check-out: {co or '-'}\n"
        f"Status: {b.get('status')}\n"
        f"Sumber: {b.get('source') or '-'}\n\n"
        f"Total: {_rp(b.get('total'))}\n"
        f"Sudah dibayar: {_rp(sb['jumlah_dibayar'])}\n"
        f"Sisa: {_rp(sb['sisa_tagihan'])}"
    )
    return teks, []


async def _cari_tamu(query: str, limit: int = 10) -> list:
    """Cari tamu by nama ATAU no_hp (2026-08-12, Guest 360 - Fase 2 PRD)."""
    q_escaped = re.escape(query.strip())
    if not q_escaped:
        return []
    return await db.guests.find(
        {"$or": [{"nama": {"$regex": q_escaped, "$options": "i"}},
                 {"no_hp": {"$regex": q_escaped, "$options": "i"}}]},
        {"_id": 0},
    ).sort("last_visit", -1).to_list(limit)


async def _render_hasil_cari_tamu(query: str) -> tuple:
    hasil = await _cari_tamu(query)
    if not hasil:
        return f"🔍 Tidak ada tamu cocok dgn \"{query}\".", []
    tombol = []
    for g in hasil:
        label = await _label_properti(g.get("property_id"))
        teks_tombol = f"{label}{g.get('nama') or '-'} · {g.get('no_hp') or '-'}"
        tombol.append([{"text": teks_tombol[:60], "callback_data": f"guestdetail:{g['id']}"}])
    return f"👤 {len(hasil)} tamu cocok dgn \"{query}\":", tombol


async def _render_detail_tamu(guest_id: str) -> tuple:
    g = await db.guests.find_one({"id": guest_id}, {"_id": 0})
    if not g:
        return "Tamu tidak ditemukan.", []
    label = await _label_properti(g.get("property_id"))
    riwayat = g.get("riwayat_kunjungan") or []
    riwayat_teks = "\n".join(
        f"  · {r.get('tanggal', '')[:10]} - {r.get('room_nomor') or '-'} ({r.get('source') or '-'})"
        for r in riwayat[-5:]
    ) or "  (belum ada riwayat tercatat)"
    teks = (
        f"👤 {label}{g.get('nama') or '-'}\n\n"
        f"WhatsApp: {g.get('no_hp') or '-'}\n"
        f"Total kunjungan: {g.get('total_kunjungan') or 0}\n"
        f"Total transaksi: {_rp(g.get('total_transaksi'))}\n"
        f"Kunjungan terakhir: {(g.get('last_visit') or '-')[:10]}\n\n"
        f"Riwayat terakhir:\n{riwayat_teks}"
    )
    # Booking aktif/terkait tamu ini (cross-reference by no_hp) - kalau ada, tampilkan
    # sbg tombol drill-down ke Booking 360 yang sama dipakai /booking.
    tombol = []
    if g.get("no_hp"):
        bookings_tamu = await db.bookings.find(
            {"no_hp": g["no_hp"]}, {"_id": 0, "id": 1, "kode": 1, "status": 1},
        ).sort("jam_mulai", -1).to_list(5)
        for b in bookings_tamu:
            tombol.append([{"text": f"🏨 {b.get('kode')} ({b.get('status')})", "callback_data": f"bookdetail:{b['id']}"}])
    return teks, tombol


async def _override_checkout(incident_id: str, owner_user: dict) -> str:
    """Owner override Checkout Payment Protection (2026-08-12, PRD §16 - "blokir keras +
    tombol override owner"). Tap tombol ini TIDAK langsung menjalankan checkout dari sini
    (data pembayaran overtime/extend checkin cuma ada di form staf di PMS, tidak
    terbawa ke Telegram) - cuma MELEPAS blokir (set owner_override_at di checkin), staf
    diminta ulangi checkout yang SAMA di PMS, kali ini lolos krn c.get("owner_override_at")
    sudah terisi (lihat cek blokir di routes/checkins.py checkout())."""
    from routes.incidents import get_incident, resolve_incident
    it = await get_incident(incident_id)
    if not it or it["event_type"] != "checkout_blocked":
        return "Incident tidak ditemukan atau bukan checkout_blocked."
    if it["status"] == "resolved":
        return "Sudah diproses sebelumnya."
    checkin_id = it.get("meta", {}).get("checkin_id")
    if not checkin_id:
        return "Data checkin tidak lengkap di incident ini, tidak bisa override."
    await db.checkins.update_one(
        {"id": checkin_id},
        {"$set": {"owner_override_at": now_iso(), "owner_override_by": owner_user.get("nama") or "owner"}},
    )
    await log_activity(
        owner_user, "override_checkout_payment_protection",
        f"Override Checkout Payment Protection - booking {it.get('meta', {}).get('booking_kode')}, "
        f"sisa tagihan Rp{it.get('meta', {}).get('sisa_tagihan', 0):,}".replace(",", "."),
        entity=checkin_id,
    )
    await resolve_incident(incident_id, resolved_by=f"owner_override:{owner_user.get('nama') or 'owner'}")
    return f"🔐 Override diberikan — {it['title']}\n\nStaf bisa coba checkout lagi sekarang di PMS."


async def _push_incident_urgent(incident: dict):
    """Push segera utk incident severity="urgent" (2026-08-12) - dipanggil dari
    routes/incidents.py create_incident() lewat import tertunda (hindari circular
    import). 🟠/🟡 SENGAJA TIDAK lewat sini - dibuat diam-diam, baru kelihatan pas owner
    kirim /aksi (prinsip PRD §33-34: jangan banjiri, notify yang penting saja)."""
    owners = await db.users.find({"role": "owner", "telegram_chat_id": {"$ne": None}},
                                  {"_id": 0, "telegram_chat_id": 1}).to_list(50)
    teks = f"🔴 URGENT — {incident['title']}\n\n{incident['detail']}"
    tombol = [[{"text": "✅ Tandai Selesai", "callback_data": f"resolve:{incident['id']}"}]]
    for u in owners:
        await _kirim_pesan_dengan_tombol(BOT_CONFIG["owner"]["token"], u["telegram_chat_id"], teks, tombol)
    await db.incidents.update_one({"id": incident["id"]}, {"$set": {"notified_at": now_iso()}})


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


async def _ringkasan_owner_fallback_text(property_id: str) -> str:
    """Fallback template kalau OPENAI_API_KEY belum/tidak dikonfigurasi — dipakai juga
    sebagai bagian dari konteks yang disuplai ke AI (_kumpulkan_konteks_bisnis)."""
    s = await report_summary(user=_DUMMY_USER, property_id=property_id)
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()  # WITA, bukan UTC mentah - konsisten dgn wita_date_range_to_utc yg dipakai report_kas_metode_bayar di bawah
    kas = await report_kas_metode_bayar(from_date=today, to_date=today, user=_DUMMY_USER, property_id=property_id)
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


async def _kumpulkan_konteks_bisnis(property_id: str) -> str:
    """Snapshot kondisi bisnis yang lebih dalam dari sekadar angka pendapatan — dipasok ke
    AI supaya owner bisa tanya apa saja (komplain, stok, housekeeping, dst) bukan cuma
    laporan keuangan, dan jawabannya tetap akurat (bukan karangan AI)."""
    s = await report_summary(user=_DUMMY_USER, property_id=property_id)
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()  # WITA, bukan UTC mentah - konsisten dgn wita_date_range_to_utc yg dipakai report_kas_metode_bayar di bawah
    kas = await report_kas_metode_bayar(from_date=today, to_date=today, user=_DUMMY_USER, property_id=property_id)
    r = s["rooms"]

    issues = await db.issues.find(
        scoped({"status": {"$in": ["open", "in_progress"]}}, property_id), {"_id": 0, "tipe": 1, "room_nomor": 1, "deskripsi": 1, "status": 1}
    ).to_list(50)
    issues_teks = "Tidak ada komplain/maintenance aktif." if not issues else "\n".join(
        f"  - [{'Komplain' if it['tipe'] == 'complaint' else 'Maintenance'}] Kamar {it.get('room_nomor') or '-'}: {it['deskripsi']} (status: {it['status']})"
        for it in issues
    )

    hk_antrian = await db.rooms.count_documents(scoped({"status": "perlu_dibersihkan"}, property_id))

    semua_produk = await db.products.find(
        scoped({"aktif": True}, property_id), {"_id": 0, "nama": 1, "kategori": 1, "stok": 1, "stok_minimal": 1}
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
        scoped({"tanggal": {"$gte": since_30d}}, property_id), {"_id": 0, "tanggal": 1, "kategori": 1, "deskripsi": 1, "nominal": 1, "user": 1}
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


async def _balasan_ai_owner(pesan_masuk: str, property_id: str) -> str:
    if not _openai_client:
        return await _ringkasan_owner_fallback_text(property_id)
    konteks = await _kumpulkan_konteks_bisnis(property_id)
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
        return await _ringkasan_owner_fallback_text(property_id)


async def _pendapatan_kamar_per_tipe_hari_ini(property_id: str) -> Dict[str, int]:
    """Pendapatan kamar hari ini dipecah Menginap vs Day Use + jumlah kamar/transaksi.
    Day Use SELALU lewat `checkins` (checkin langsung ATAU dari booking yang sudah check-in —
    /checkins tidak pernah dipakai utk menginap, lihat docstring create_checkin) — booking
    day_use yang lunas tapi BELUM check-in ditambah terpisah dari `bookings` (checkin_id belum
    ada) supaya tidak dobel dengan yang sudah masuk checkins. Menginap SELALU lewat `bookings`
    (checkins tidak pernah representasikan menginap sama sekali) — tidak ada risiko dobel hitung."""
    # WITA, bukan UTC mentah (2026-08-07, bug nyata) - lihat catatan lengkap di reservation_service.py
    today_iso, _ = wita_date_range_to_utc(
        (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat(),
        (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat(),
    )

    co_today = await db.checkins.find(
        scoped({"jam_checkout": {"$gte": today_iso}, "status": "selesai"}, property_id), {"_id": 0, "total": 1}
    ).to_list(500)
    dayuse_total = sum(c.get("total", 0) for c in co_today)
    dayuse_kamar = len(co_today)

    dayuse_bk_belum_checkin = await db.bookings.find(scoped({
        "tipe": "day_use", "payment_status": "paid", "paid_at": {"$gte": today_iso},
        "checkin_id": {"$exists": False},
    }, property_id), {"_id": 0, "total": 1}).to_list(200)
    dayuse_total += sum(int(b.get("total") or 0) for b in dayuse_bk_belum_checkin)
    dayuse_kamar += len(dayuse_bk_belum_checkin)

    menginap_bk = await db.bookings.find(scoped({
        "tipe": "menginap", "payment_status": "paid", "paid_at": {"$gte": today_iso},
    }, property_id), {"_id": 0, "total": 1}).to_list(200)
    menginap_total = sum(int(b.get("total") or 0) for b in menginap_bk)
    menginap_kamar = len(menginap_bk)

    return {
        "dayuse_total": dayuse_total, "dayuse_kamar": dayuse_kamar,
        "menginap_total": menginap_total, "menginap_kamar": menginap_kamar,
    }


async def _laporan_harian_text(property_id: str, property_nama: str = "", sertakan_ai_grow: bool = False) -> str:
    """Laporan akhir hari (dikirim otomatis jam 23:00 WITA ke owner & staff yang terhubung) —
    rinci: pemasukan dipecah menginap/day use (+ jumlah kamar) & metode bayar, pengeluaran
    dengan total DAN daftar detail per item.

    `sertakan_ai_grow` (2026-08-04, permintaan Agus) - HANYA True utk versi owner (staf
    tidak perlu Business Health Score/rekomendasi strategis, sama pola dgn AI Grow yang
    dari awal owner-only lewat require_owner di ai_grow.py). Brief diambil dari CACHE
    (bukan generate baru terpisah - lihat ai_grow._generate_dan_cache_brief) supaya narasi
    yang tampil di sini PERSIS yang barusan di-generate slot 23:00, 1 sumber kebenaran."""
    s = await report_summary(user=_DUMMY_USER, property_id=property_id)
    today_iso = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()  # WITA, bukan UTC mentah
    kas = await report_kas_metode_bayar(from_date=today_iso, to_date=today_iso, user=_DUMMY_USER, property_id=property_id)
    kamar = await _pendapatan_kamar_per_tipe_hari_ini(property_id)
    tanggal = datetime.now(timezone.utc).astimezone(WITA).strftime("%d %B %Y")
    label = f" — {property_nama}" if property_nama else ""

    total_pemasukan = kamar["dayuse_total"] + kamar["menginap_total"] + s["pendapatan_kasir_hari_ini"] + s["pendapatan_service_hari_ini"]

    exp_today = await db.expenses.find(
        scoped({"tanggal": {"$gte": today_iso}}, property_id), {"_id": 0, "kategori": 1, "deskripsi": 1, "nominal": 1, "user": 1}
    ).sort("nominal", -1).to_list(200)
    total_pengeluaran = sum(e.get("nominal", 0) for e in exp_today)
    if exp_today:
        pengeluaran_detail = "\n".join(
            f"  - {e.get('deskripsi', '-')} ({e.get('kategori', '-')}): {_rp(e['nominal'])} — {e.get('user', '-')}"
            for e in exp_today
        )
    else:
        pengeluaran_detail = "  Tidak ada pengeluaran hari ini."

    ai_grow_block = ""
    if sertakan_ai_grow:
        try:
            from routes.ai_grow import _generate_dan_cache_brief
            brief = await _generate_dan_cache_brief(property_id)
            skor = brief["health_score"]["skor"]
            ai_grow_block = (
                f"\n\n📊 AI Grow — Rekomendasi Akhir Hari\n"
                f"Business Health Score: {skor}/100\n\n"
                f"{brief['narasi']}"
            )
        except Exception as e:
            logging.getLogger("telegram_bot").warning(f"Gagal sertakan AI Grow di laporan malam properti {property_id}: {e}")

    return (
        f"📋 Laporan Akhir Hari{label} — {tanggal}\n\n"
        f"💰 PEMASUKAN: {_rp(total_pemasukan)}\n"
        f"  🛏 Menginap: {_rp(kamar['menginap_total'])} ({kamar['menginap_kamar']} kamar)\n"
        f"  ☀️ Day Use: {_rp(kamar['dayuse_total'])} ({kamar['dayuse_kamar']} kamar)\n"
        f"  🛒 Kasir (POS): {_rp(s['pendapatan_kasir_hari_ini'])}\n"
        f"  🧰 Service: {_rp(s['pendapatan_service_hari_ini'])}\n\n"
        f"  Metode Bayar (Kasir & Check-In):\n"
        f"    Tunai: {_rp(kas['tunai'])} · QRIS: {_rp(kas['qris'])} · Transfer: {_rp(kas['transfer'])}\n\n"
        f"💸 PENGELUARAN: {_rp(total_pengeluaran)}\n"
        f"{pengeluaran_detail}"
        f"{ai_grow_block}\n\n"
        f"Terima kasih atas kerja hari ini! 🙏"
    )


_NOMINAL_RE = re.compile(r"^\s*([\d.,]+)\s*(.*)$", re.DOTALL)


async def _catat_pengeluaran_items(user_doc: dict, items: list, foto_url: str = "") -> str:
    """Satu-satunya jalur insert ke db.expenses dari bot Telegram (owner & staff) — sengaja
    TIDAK PERNAH menyentuh db.bookings/kasir/payment_log, jadi struktural tidak mungkin
    'pemasukan' tercatat lewat sini apa pun yang diminta/dikirim user."""
    # Multi-properti (2026-07-26) - staf sudah punya property_id di akunnya sendiri
    # (di-set saat akun dibuat), jadi resolve dari situ dulu - SAMA pola dengan
    # _balasan_ai_owner/kirim_briefing_semua_owner di file ini. Sebelumnya selalu pakai
    # get_default_property_id() apa pun propertinya staf pengirim - bug nyata: staf
    # properti kedua (mis. harmoni) yang catat pengeluaran lewat Telegram akan salah
    # tercatat di properti default (Pelangi Homestay). Owner (belum terikat 1 properti)
    # tetap fallback ke default seperti sebelumnya.
    property_id = user_doc.get("property_id") or await get_default_property_id()
    baris, total = [], 0
    for it in items:
        doc = {
            "id": str(uuid.uuid4()), "tanggal": now_iso(), "kategori": "Operasional",
            "deskripsi": it["deskripsi"], "nominal": it["nominal"], "foto_url": foto_url or "",
            "user": user_doc["nama"], "user_id": user_doc["id"], "created_at": now_iso(),
            "source": "telegram", "property_id": property_id,
        }
        await db.expenses.insert_one(doc)
        await log_activity(user_doc, "expense", f"Pengeluaran (Telegram) Operasional Rp{it['nominal']:,}".replace(",", "."))
        from routes.rekening import auto_posting
        await auto_posting("pengeluaran", it["nominal"], "Operasional", it["deskripsi"], property_id)
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

    # Callback_query (2026-08-12, PRD "Owner Control Center" Fase 1 - Action Center) -
    # update jenis BARU, sebelum ini tidak pernah ditangani sama sekali (tombol inline
    # belum pernah ada di bot ini) - kalau tidak ditangani di sini, update ini akan jatuh
    # lewat ke pengecekan `msg` di bawah & di-skip diam-diam (tidak ada "chat" langsung
    # di payload callback_query, adanya di payload["callback_query"]["message"]["chat"]).
    cq = payload.get("callback_query")
    if cq:
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        token = BOT_CONFIG[kind]["token"]
        role = BOT_CONFIG[kind]["role"]
        data = cq.get("data") or ""
        u = await db.users.find_one({"telegram_chat_id": chat_id, "role": role})
        if not u or kind != "owner":
            # Action Center khusus owner (staff bot tidak dapat tombol apa pun sejauh
            # ini) - tombol ini secara desain tidak pernah dikirim ke staff, tapi dijaga
            # di sini juga kalau2 ada yang coba tap dari luar alur normal.
            await _answer_callback_query(token, cq["id"], "Fitur ini khusus owner.")
            return {"ok": True}
        if data == "aksi":
            teks, tombol = await _render_daftar_incident()
            await _edit_pesan(token, chat_id, message_id, teks, tombol)
        elif data.startswith("show:"):
            teks, tombol = await _render_detail_incident(data.split(":", 1)[1])
            await _edit_pesan(token, chat_id, message_id, teks, tombol)
        elif data.startswith("resolve:"):
            from routes.incidents import resolve_incident
            resolved = await resolve_incident(data.split(":", 1)[1], resolved_by=u.get("nama") or str(chat_id))
            konfirmasi = f"✅ Selesai — {resolved['title']}" if resolved else "Sudah ditandai selesai sebelumnya."
            await _edit_pesan(token, chat_id, message_id, konfirmasi, [])
        elif data == "pembayaran":
            teks, tombol = await _render_daftar_payment()
            await _edit_pesan(token, chat_id, message_id, teks, tombol)
        elif data.startswith("paydetail:"):
            teks, tombol = await _render_detail_payment(data.split(":", 1)[1])
            await _edit_pesan(token, chat_id, message_id, teks, tombol)
        elif data.startswith("bookdetail:"):
            teks, tombol = await _render_detail_booking(data.split(":", 1)[1])
            await _edit_pesan(token, chat_id, message_id, teks, tombol)
        elif data.startswith("guestdetail:"):
            teks, tombol = await _render_detail_tamu(data.split(":", 1)[1])
            await _edit_pesan(token, chat_id, message_id, teks, tombol)
        elif data.startswith("override_checkout:"):
            konfirmasi = await _override_checkout(data.split(":", 1)[1], owner_user=u)
            await _edit_pesan(token, chat_id, message_id, konfirmasi, [])
        await _answer_callback_query(token, cq["id"])
        return {"ok": True}

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

    # /aksi (2026-08-12, Action Center) - command BARU terpisah, SENGAJA bukan reuse
    # /start (yang sudah py 2 tanggung jawab: linking akun + instruksi belum-terhubung -
    # entangle command baru ke situ tidak perlu, /aksi independen & 0 risiko ke flow
    # linking yang sudah teruji).
    if kind == "owner" and text.startswith("/aksi"):
        teks, tombol = await _render_daftar_incident()
        if tombol:
            await _kirim_pesan_dengan_tombol(token, chat_id, teks, tombol)
        else:
            await _kirim_pesan(token, chat_id, teks)
        return {"ok": True}

    # /pembayaran (2026-08-12, Payment Center - Fase 2 PRD, murni monitoring) - sama pola
    # dgn /aksi, command terpisah sendiri.
    if kind == "owner" and text.startswith("/pembayaran"):
        teks, tombol = await _render_daftar_payment()
        if tombol:
            await _kirim_pesan_dengan_tombol(token, chat_id, teks, tombol)
        else:
            await _kirim_pesan(token, chat_id, teks)
        return {"ok": True}

    # /booking <kode atau nama> (2026-08-12, Booking Center - Fase 2 PRD) - SENGAJA
    # command+argumen langsung (bukan alur "kirim query, bot nunggu balasan berikutnya")
    # - bot ini stateless per-pesan (tidak ada tracking "sedang menunggu input apa"),
    # nambah itu berisiko bentrok dgn alur pengeluaran teks bebas yang sudah ada &
    # teruji. Command+argumen 0 risiko ke situ, tetap 1 langkah drpd 2.
    if kind == "owner" and text.startswith("/booking"):
        query = text[len("/booking"):].strip()
        if not query:
            await _kirim_pesan(token, chat_id, "Format: /booking <kode atau nama tamu>, mis. /booking Dewi")
            return {"ok": True}
        teks, tombol = await _render_hasil_cari_booking(query)
        if tombol:
            await _kirim_pesan_dengan_tombol(token, chat_id, teks, tombol)
        else:
            await _kirim_pesan(token, chat_id, teks)
        return {"ok": True}

    # /tamu <nama atau nomor HP> (2026-08-12, Guest 360 - Fase 2 PRD) - sama pola /booking.
    if kind == "owner" and text.startswith("/tamu"):
        query = text[len("/tamu"):].strip()
        if not query:
            await _kirim_pesan(token, chat_id, "Format: /tamu <nama atau nomor HP>, mis. /tamu 0812")
            return {"ok": True}
        teks, tombol = await _render_hasil_cari_tamu(query)
        if tombol:
            await _kirim_pesan_dengan_tombol(token, chat_id, teks, tombol)
        else:
            await _kirim_pesan(token, chat_id, teks)
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
            # Owner belum punya cara pilih properti lewat chat Telegram (fitur terpisah,
            # belum ada) - default ke properti utama, sama seperti stopgap lain di file
            # ini, sampai owner benar-benar mengelola >1 properti aktif.
            reply = await _balasan_ai_owner(text, u.get("property_id") or await get_default_property_id())
        else:
            reply = "Kirim pengeluaran lewat teks, mis. \"50000 beli galon air\" (boleh lebih dari satu sekaligus), atau foto struk dengan caption serupa."
    else:
        reply = ("Kirim teks atau foto struk untuk catat pengeluaran." if kind == "staff"
                  else await _balasan_ai_owner("", u.get("property_id") or await get_default_property_id()))
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
    sekali sehari jam 23:00 WITA (2026-08-04, dipindah dari 22:00 - permintaan Agus, data
    hari itu biasanya sudah masuk semua di jam ini). PERBAIKAN 2026-08-07: konstanta jam
    sebelumnya salah pakai WIB (UTC+7), padahal Bedugul/Bali itu WITA (UTC+8) - lihat detail
    lengkap di reservation_service.py. Akibatnya laporan ini SELAMA INI beneran terkirim jam
    00:00 (tengah malam) waktu Bali asli, BUKAN 23:00 seperti yang Agus minta - telat 1 jam
    dari maksud aslinya. Sekarang dgn WITA yang benar, laporan akan terkirim tepat jam 23:00
    Bali asli mulai hari ini. Versi OWNER menyertakan rekomendasi
    final AI Grow (Business Health Score + narasi, di-generate & di-cache SEKALI di sini -
    lihat sertakan_ai_grow di _laporan_harian_text - slot ke-3 dari 3x/hari, 2 slot lain
    di ai_grow.background_ai_grow_cache_loop cuma refresh cache dashboard). Versi STAFF
    TIDAK menyertakan (AI Grow owner-only, sama pola dgn require_owner di ai_grow.py).

    Guard anti-dobel-kirim (2026-08-04, bug nyata dilaporkan Agus - laporan kadang
    terkirim 2x di jam yang sama): SEBELUMNYA guard `last_sent_date` cuma in-memory - kalau
    proses backend restart (mis. auto-deploy GitHub Actions kebetulan landing persis di
    jendela jam 23:00-23:05) SAAT/SETELAH laporan terkirim tapi SEBELUM guard sempat
    diset, proses baru mulai dgn guard kosong lagi & bisa kirim ulang. Sekarang guard
    disimpan di db.scheduler_state (persisten lintas restart) - dicek DI AWAL sebelum
    mulai kirim apa pun, ditulis SEGERA setelah lolos cek (bukan di akhir setelah semua
    pesan terkirim) supaya restart di TENGAH proses kirim juga tidak memicu kirim ulang."""
    while True:
        try:
            now_wita = datetime.now(timezone.utc).astimezone(WITA)
            if now_wita.hour == 23:
                tanggal_ini = now_wita.date().isoformat()
                state = await db.scheduler_state.find_one({"_id": "laporan_harian_telegram"})
                if not state or state.get("last_sent_date") != tanggal_ini:
                    # Tulis guard SEBELUM kirim (bukan setelah) - restart di tengah proses
                    # kirim tidak akan memicu ulang, risiko terburuk kalau proses benar2
                    # crash di tengah adalah SEBAGIAN user tidak kebagian hari itu (jauh
                    # lebih aman drpd owner/staff dapat laporan dobel).
                    await db.scheduler_state.update_one(
                        {"_id": "laporan_harian_telegram"},
                        {"$set": {"last_sent_date": tanggal_ini}},
                        upsert=True,
                    )
                    properti_aktif = await db.properties.find({"aktif": True}, {"_id": 0, "id": 1, "nama": 1}).to_list(50)
                    default_property_id = await get_default_property_id()
                    teks_owner_per_properti = {}
                    teks_staff_per_properti = {}
                    for p in properti_aktif:
                        label = p.get("nama") if len(properti_aktif) > 1 else ""
                        teks_owner_per_properti[p["id"]] = await _laporan_harian_text(p["id"], label, sertakan_ai_grow=True)
                        teks_staff_per_properti[p["id"]] = await _laporan_harian_text(p["id"], label, sertakan_ai_grow=False)

                    users = await db.users.find({"telegram_chat_id": {"$ne": None}}, {"_id": 0}).to_list(200)
                    for u in users:
                        kind = "owner" if u.get("role") == "owner" else "staff"
                        if kind == "owner":
                            for teks in teks_owner_per_properti.values():
                                await _kirim_pesan(BOT_CONFIG[kind]["token"], u["telegram_chat_id"], teks)
                        else:
                            pid = u.get("property_id") or default_property_id
                            teks = teks_staff_per_properti.get(pid) or await _laporan_harian_text(pid, sertakan_ai_grow=False)
                            await _kirim_pesan(BOT_CONFIG[kind]["token"], u["telegram_chat_id"], teks)
        except Exception as e:
            logging.getLogger("telegram_bot").warning(f"Gagal kirim laporan harian Telegram: {e}")
        await asyncio.sleep(300)
