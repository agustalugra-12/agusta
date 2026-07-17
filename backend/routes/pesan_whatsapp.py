from core import *
import asyncio
import httpx
import json
from openai import OpenAI
from fastapi.responses import PlainTextResponse
from routes.public import public_availability
from routes.issues import buat_issue
from routes.booking_requests import buat_booking_request
from scheduling_engine import rekomendasi_slot_kosong as _rekomendasi_slot_kosong_engine, WIB

_openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

ISSUE_CLASSIFY_PROMPT = """Kamu mengklasifikasi pesan WhatsApp tamu hotel sebagai Complaint,
Maintenance, atau bukan keduanya. Balas HANYA JSON:
{"tipe": "complaint" | "maintenance" | null, "deskripsi": "<ringkasan singkat masalah, Bahasa Indonesia>"}

Maintenance = kerusakan fasilitas/perangkat (TV mati, AC rusak, shower bocor, air panas mati,
lampu mati, wifi tidak jalan, dst).
Complaint = keluhan pelayanan/kebersihan/kelengkapan (kamar kotor, handuk belum ada, air minum
habis, sarapan terlambat, dst) yang BUKAN kerusakan alat.
Kalau pesan BUKAN komplain/kerusakan sama sekali (tanya harga, booking, obrolan biasa, ucapan
terima kasih, dll), balas {"tipe": null, "deskripsi": ""}. JANGAN membuat tiket dari pertanyaan
atau pernyataan yang ambigu — hanya kalau tamu JELAS melaporkan masalah nyata."""

_WA_ISSUE_USER = {"id": "ai-whatsapp", "nama": "AI WhatsApp", "role": "owner"}


async def _klasifikasi_pesan_tamu(pesan: str) -> Optional[Dict[str, str]]:
    if not _openai_client or not (pesan or "").strip():
        return None
    try:
        resp = await asyncio.to_thread(
            _openai_client.chat.completions.create,
            model="gpt-4o-mini", temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": ISSUE_CLASSIFY_PROMPT},
                {"role": "user", "content": pesan},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        tipe = data.get("tipe")
        if tipe not in ("complaint", "maintenance"):
            return None
        deskripsi = (data.get("deskripsi") or pesan).strip()
        return {"tipe": tipe, "deskripsi": deskripsi} if deskripsi else None
    except Exception as e:
        logging.getLogger("pesan_whatsapp").warning(f"Gagal klasifikasi pesan tamu: {e}")
        return None


async def _cari_kamar_dari_no_hp(no_hp: str):
    """Cari kamar aktif tamu dari nomor HP-nya (checkin aktif, lalu booking checked_in sebagai
    fallback) — dicoba beberapa variasi format (0xxx vs 62xxx) karena provider WA & PMS bisa
    beda konvensi penyimpanan nomor."""
    digits = re.sub(r"\D", "", no_hp or "")
    if not digits:
        return None, ""
    variasi = {digits}
    if digits.startswith("62"):
        variasi.add("0" + digits[2:])
    elif digits.startswith("0"):
        variasi.add("62" + digits[1:])
    ci = await db.checkins.find_one({"no_hp": {"$in": list(variasi)}, "status": "aktif"}, {"_id": 0, "room_id": 1, "room_nomor": 1})
    if ci:
        return ci["room_id"], ci["room_nomor"]
    bk = await db.bookings.find_one(
        {"no_hp": {"$in": list(variasi)}, "status": "checked_in"},
        {"_id": 0, "room_id": 1, "room_nomor": 1}, sort=[("created_at", -1)],
    )
    if bk:
        return bk["room_id"], bk["room_nomor"]
    return None, ""


async def _klasifikasi_dan_buat_tiket(no_hp: str, nama: str, pesan_masuk: str):
    """Dipanggil dari kedua webhook WhatsApp (generik & BalesOtomatis) setelah pesan tamu
    tersimpan — auto-buat tiket Komplain/Maintenance kalau AI yakin pesannya memang laporan
    masalah. Gagal (OpenAI error, dsb) sengaja tidak melempar exception ke pemanggil supaya
    tidak mengganggu jalur balas-ke-tamu yang lebih penting."""
    hasil = await _klasifikasi_pesan_tamu(pesan_masuk)
    if not hasil:
        return None
    room_id, room_nomor = await _cari_kamar_dari_no_hp(no_hp)
    try:
        return await buat_issue(
            hasil["tipe"], hasil["deskripsi"], _WA_ISSUE_USER,
            room_id=room_id, room_nomor=room_nomor, nama_tamu=nama or "",
        )
    except HTTPException as e:
        logging.getLogger("pesan_whatsapp").warning(f"Gagal auto-buat tiket dari WA: {e.detail}")
        return None

async def _rekomendasi_slot_kosong(tipe: str) -> Optional[str]:
    """Wrapper teks di atas Scheduling Engine terpusat (scheduling_engine.py) — perhitungan
    slot-nya sendiri sudah dipusatkan di sana (dipakai bareng endpoint /scheduling/* untuk
    Dashboard staf) supaya tidak ada logika jadwal yang tercecer per modul (PRD Revisi #6)."""
    kandidat = await _rekomendasi_slot_kosong_engine(tipe)
    if not kandidat:
        return None
    jam_lokal = kandidat["siap_pakai"].astimezone(WIB)
    return (f"Kamar {tipe} sedang penuh, tapi Kamar {kandidat['room_nomor']} diperkirakan siap dipakai lagi "
            f"mulai pukul {jam_lokal.strftime('%H:%M')} WIB tanggal {jam_lokal.strftime('%d %B %Y')} "
            f"(setelah tamu check-out & kamar selesai dibersihkan).")

# ---- Pesan WhatsApp Otomatis / Pemantauan Status ----
# Satu collection `wa_conversations` jadi sumber kebenaran untuk kedua nama fitur mirip
# di plan (entitas WHATSAPP_LOGS di PRD: guest_phone, message, ai_response, sent_at).
# "Log Percakapan" & "Pemantauan Status" cuma dua cara pandang berbeda atas data yang sama.

AI_SYSTEM_PROMPT = """Kamu adalah asisten WhatsApp Pelangi Homestay. Jawab singkat, ramah,
dalam Bahasa Indonesia, berdasarkan HANYA data ketersediaan & harga kamar yang diberikan.
Jangan mengarang data yang tidak ada. Kalau ada baris estimasi waktu kamar berikutnya kosong,
sampaikan sebagai PERKIRAAN (bukan jaminan pasti) dan tawarkan bantu reservasikan untuk jam
tersebut. Kalau pertanyaan di luar itu (pembatalan, komplain, dll), arahkan tamu menghubungi
resepsionis."""


async def _ringkasan_ketersediaan_untuk_ai() -> str:
    rooms = await db.rooms.find({}, {"_id": 0, "tipe": 1, "tarif": 1, "status": 1}).to_list(200)
    per_tipe: Dict[str, Dict[str, Any]] = {}
    for r in rooms:
        t = per_tipe.setdefault(r["tipe"], {"tarif": r["tarif"], "kosong": 0, "total": 0})
        t["total"] += 1
        if r["status"] == "kosong":
            t["kosong"] += 1
    baris = [f"{tipe}: {v['kosong']}/{v['total']} kamar kosong sekarang, tarif Rp{v['tarif']:,}".replace(",", ".")
             for tipe, v in per_tipe.items()]
    # Kalau ada tipe yang penuh (0 kosong), tambahkan estimasi kapan kamar berikutnya siap —
    # supaya AI bisa jawab "penuh, tapi diperkirakan kosong jam X" alih-alih cuma "penuh".
    for tipe, v in per_tipe.items():
        if v["kosong"] == 0:
            rekom = await _rekomendasi_slot_kosong(tipe)
            if rekom:
                baris.append(rekom)
    return "Ketersediaan kamar saat ini:\n" + "\n".join(baris)


async def _generate_balasan_ai(pesan_masuk: str) -> Optional[str]:
    if not _openai_client:
        return None
    konteks = await _ringkasan_ketersediaan_untuk_ai()
    resp = await asyncio.to_thread(
        _openai_client.chat.completions.create,
        model="gpt-4o-mini",
        temperature=0.3,
        messages=[
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": f"{konteks}\n\nPesan tamu: {pesan_masuk}"},
        ],
    )
    return resp.choices[0].message.content


# ---- Alur pengumpulan data Booking Request (PRD Modul Reservasi & Priority Booking,
# disetujui user 2026-07-17) — AI mengumpulkan data lewat beberapa balasan berturut-turut,
# BUKAN sekali tanya-jawab. Sesi disimpan per no_hp di `wa_booking_sessions` supaya tiap
# pesan tamu berikutnya melanjutkan data yang sudah terkumpul, bukan mulai dari nol.
#
# BATASAN KERAS (jangan dilonggarkan): AI di sini TIDAK PERNAH membuat booking sungguhan —
# titik akhir satu-satunya alur ini adalah `buat_booking_request()` (permintaan non-binding),
# persis sama seperti batasan AI tidak boleh mengubah stok/booking/pemasukan yang sudah
# berlaku untuk bot Telegram (lihat OWNER_AI_SYSTEM_PROMPT di telegram_bot.py).

BOOKING_INTENT_CLASSIFY_PROMPT = """Tentukan apakah pesan tamu ini mengekspresikan NIAT untuk
MEMESAN/BOOKING kamar (bukan sekadar tanya harga/ketersediaan untuk info umum, bukan komplain,
bukan obrolan biasa). Balas HANYA JSON: {"niat_booking": true|false}.
True: tamu bilang mau booking/pesan kamar/reservasi, atau langsung sebut tanggal & tipe kamar
dengan maksud memesan sekarang.
False: pertanyaan umum ("ada kamar kosong?", "berapa harganya?") tanpa maksud langsung memesan,
komplain, atau obrolan lain."""

BOOKING_FLOW_SYSTEM_PROMPT = """Kamu asisten WhatsApp Pelangi Homestay yang membantu tamu
MENGAJUKAN PERMINTAAN booking (bukan booking final — permintaan ini akan ditinjau resepsionis
dulu sebelum dikonfirmasi & dikirim link pembayaran). Balas HANYA JSON dengan bentuk persis:
{{
  "fields": {{
    "nama_tamu": "<string atau null kalau belum disebut>",
    "tipe": "day_use" atau "menginap" atau null,
    "room_tipe": "Standard" atau "Cottage" atau null,
    "jumlah_kamar": <int atau null>,
    "jumlah_tamu": <int atau null>,
    "tanggal_checkin": "<YYYY-MM-DD atau null>",
    "jam_checkin": "<HH:mm atau null, hanya relevan utk tipe day_use>",
    "tanggal_checkout": "<YYYY-MM-DD atau null, hanya relevan utk tipe menginap>",
    "payment_option": "<'dp50' kalau tamu sebut mau bayar DP/uang muka/setengah/sebagian, 'full' kalau tamu sebut mau bayar penuh/lunas/full payment, null kalau belum disebut sama sekali>"
  }},
  "confirmed": <bool — true HANYA kalau pesan ini adalah jawaban YA/setuju/oke tamu terhadap
                ringkasan permintaan yang barusan kamu tunjukkan>,
  "cancelled": <bool — true kalau tamu jelas ingin membatalkan/berhenti proses ini>,
  "balasan": "<balasan natural, ramah, singkat, Bahasa Indonesia, seperti resepsionis manusia —
              BUKAN bahasa robot. Kalau ada field WAJIB yang masih kosong, tanyakan HANYA yang
              masih kurang (jangan tanya ulang yang sudah terjawab, boleh gabung beberapa
              pertanyaan sekaligus). Kalau semua field wajib sudah lengkap dan belum pernah
              diringkas, ringkas permintaannya lalu minta konfirmasi tamu. Kalau tamu baru saja
              konfirmasi (confirmed=true), sampaikan permintaannya sudah diteruskan ke
              resepsionis untuk ditinjau & akan dikirim link pembayaran kalau disetujui. Kalau
              cancelled=true, konfirmasi proses dibatalkan dengan ramah. JANGAN PERNAH
              menjanjikan kamar pasti tersedia atau bilang bookingnya sudah pasti/dikonfirmasi —
              status sebenarnya baru 'permintaan', keputusan akhir ada di resepsionis.>"
}}

Field WAJIB sebelum bisa diringkas & minta konfirmasi: nama_tamu, tipe, room_tipe,
tanggal_checkin, lalu jam_checkin (kalau tipe=day_use) ATAU tanggal_checkout (kalau
tipe=menginap). jumlah_kamar & jumlah_tamu default 1 kalau tamu tidak menyebutkan apa pun —
JANGAN ditanya kecuali tamu sendiri menyinggung lebih dari 1 kamar/orang. payment_option
OPSIONAL — JANGAN pernah ditanya proaktif (baru dibahas resepsionis setelah permintaan
disetujui), tapi kalau tamu MENYEBUTKAN sendiri preferensinya (mis. "saya DP dulu ya", "mau
bayar 50% aja", "bayar lunas langsung") di pesan mana pun selama percakapan, catat sebagai
payment_option supaya link pembayaran yang dikirim nanti sesuai permintaan tamu, bukan
staf menebak-nebak.

Tanggal hari ini: {tanggal_hari_ini} (WIB) — SEMUA kata relatif waktu (besok, lusa, hari ini,
nama hari, dst) selalu dihitung relatif tanggal HARI INI itu, BUKAN relatif tanggal lain yang
sudah disebut sebelumnya di percakapan (mis. bukan relatif tanggal check-in). Contoh persis:
kalau hari ini {tanggal_hari_ini}, "besok" = hari ini + 1 hari, "lusa" = hari ini + 2 hari.
Kalau tamu bilang "check-in besok, check-out lusa", checkout HARUS cuma 1 malam dari checkin
(besok+1 hari = lusa), BUKAN 2 malam — hitung ulang selisih harinya, jangan asal tebak."""


async def _klasifikasi_niat_booking(pesan: str) -> bool:
    try:
        resp = await asyncio.to_thread(
            _openai_client.chat.completions.create,
            model="gpt-4o-mini", temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": BOOKING_INTENT_CLASSIFY_PROMPT},
                {"role": "user", "content": pesan},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return bool(data.get("niat_booking"))
    except Exception as e:
        logging.getLogger("pesan_whatsapp").warning(f"Gagal klasifikasi niat booking: {e}")
        return False


async def _sesi_booking_aktif(no_hp: str) -> Optional[Dict[str, Any]]:
    """Sesi lebih dari 2 jam dianggap basi (tamu kemungkinan sudah pindah topik) — dibuang
    supaya pesan baru mulai dari nol, bukan melanjutkan konteks yang sudah tidak relevan."""
    sesi = await db.wa_booking_sessions.find_one({"no_hp": no_hp})
    if not sesi:
        return None
    try:
        updated = datetime.fromisoformat(sesi["updated_at"])
    except Exception:
        updated = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) - updated > timedelta(hours=2):
        await db.wa_booking_sessions.delete_one({"no_hp": no_hp})
        return None
    return sesi


def _field_wajib_kurang(data: Dict[str, Any]) -> List[str]:
    wajib = ["nama_tamu", "tipe", "room_tipe", "tanggal_checkin"]
    if data.get("tipe") == "day_use":
        wajib.append("jam_checkin")
    elif data.get("tipe") == "menginap":
        wajib.append("tanggal_checkout")
    return [f for f in wajib if not data.get(f)]


async def _proses_giliran_booking(no_hp: str, nama: str, pesan_masuk: str, sesi: Optional[Dict[str, Any]]) -> str:
    data_terkumpul = dict(sesi["data"]) if sesi else {}
    konteks_ketersediaan = await _ringkasan_ketersediaan_untuk_ai()
    prompt = BOOKING_FLOW_SYSTEM_PROMPT.format(tanggal_hari_ini=datetime.now(WIB).strftime("%Y-%m-%d"))
    resp = await asyncio.to_thread(
        _openai_client.chat.completions.create,
        model="gpt-4o-mini", temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": (
                f"{konteks_ketersediaan}\n\nData permintaan yang sudah terkumpul sejauh ini: "
                f"{json.dumps(data_terkumpul, ensure_ascii=False)}\n\nPesan tamu: {pesan_masuk}"
            )},
        ],
    )
    hasil = json.loads(resp.choices[0].message.content or "{}")
    for k, v in (hasil.get("fields") or {}).items():
        if v not in (None, ""):
            data_terkumpul[k] = v
    balasan = hasil.get("balasan") or "Maaf, bisa diulangi?"

    if hasil.get("cancelled"):
        await db.wa_booking_sessions.delete_one({"no_hp": no_hp})
        return balasan

    kurang = _field_wajib_kurang(data_terkumpul)
    if hasil.get("confirmed") and not kurang:
        data_terkumpul.setdefault("jumlah_kamar", 1)
        data_terkumpul.setdefault("jumlah_tamu", 1)
        data_terkumpul["nama_tamu"] = data_terkumpul.get("nama_tamu") or nama
        data_terkumpul["no_hp"] = no_hp
        await buat_booking_request(data_terkumpul)
        await db.wa_booking_sessions.delete_one({"no_hp": no_hp})
        return balasan

    await db.wa_booking_sessions.update_one(
        {"no_hp": no_hp},
        {"$set": {"nama": nama, "data": data_terkumpul, "updated_at": now_iso()}},
        upsert=True,
    )
    return balasan


async def _balasan_dengan_alur_booking(no_hp: str, nama: str, pesan_masuk: str) -> Optional[str]:
    """Pengganti pemanggilan langsung `_generate_balasan_ai` di kedua webhook WhatsApp —
    menyisipkan alur Booking Request TANPA mengubah perilaku balasan untuk pesan biasa
    (pertanyaan umum tetap lewat _generate_balasan_ai persis seperti sebelumnya)."""
    if not _openai_client or not (pesan_masuk or "").strip():
        return None
    sesi = await _sesi_booking_aktif(no_hp)
    if sesi or await _klasifikasi_niat_booking(pesan_masuk):
        return await _proses_giliran_booking(no_hp, nama, pesan_masuk, sesi)
    return await _generate_balasan_ai(pesan_masuk)


async def _kirim_via_provider(no_hp: str, pesan: str) -> tuple[bool, Optional[str]]:
    """Kirim balasan lewat webhook provider yang staf konfigurasi sendiri. Generic —
    tidak terikat satu provider tertentu (Fonnte/Wablas/dll punya kontrak beda-beda),
    payload dikirim dalam bentuk umum {to, message}."""
    cfg = await db.webhook_config.find_one({})
    if not cfg or not cfg.get("aktif") or not cfg.get("webhook_url") or not cfg.get("api_key"):
        return False, "Webhook belum dikonfigurasi/aktif"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                cfg["webhook_url"],
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json={"to": no_hp, "message": pesan},
            )
        if resp.status_code >= 400:
            return False, f"Provider merespons HTTP {resp.status_code}"
        return True, None
    except Exception as e:
        return False, f"Gagal menghubungi provider: {e}"


@api.post("/webhook/whatsapp/incoming")
async def whatsapp_incoming(request: Request, token: Optional[str] = None):
    """Endpoint publik yang dipanggil provider WhatsApp saat ada pesan masuk. Kontrak
    generik {sender/from, message/text, name} supaya kompatibel dengan provider apa pun
    (Fonnte/Wablas/dll biasanya mengirim salah satu dari nama field ini).

    `?token=` divalidasi ke `webhook_config.webhook_token` yang sama dipakai endpoint
    BalesOtomatis (self-review 2026-07-17: endpoint ini sebelumnya 100% tanpa validasi
    apa pun, terbuka untuk siapa saja di internet — sekarang ada auto-klasifikasi AI +
    auto-buat tiket di jalur ini, jadi celah itu lebih berisiko dari sebelumnya. Provider
    lain (Fonnte/Wablas/dll) tinggal tambahkan `?token=<webhook_token>` di URL webhook
    yang didaftarkan ke mereka)."""
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("webhook_token") or cfg["webhook_token"] != token:
        raise HTTPException(404, "Not Found")
    payload = await request.json()
    no_hp = payload.get("sender") or payload.get("from") or payload.get("no_hp") or ""
    pesan_masuk = payload.get("message") or payload.get("text") or payload.get("pesan") or ""
    nama = payload.get("name") or payload.get("nama") or no_hp
    if not no_hp or not pesan_masuk:
        raise HTTPException(400, "Payload harus berisi pengirim & isi pesan")

    mulai = datetime.now(timezone.utc)
    balasan_ai = await _balasan_dengan_alur_booking(no_hp, nama, pesan_masuk)
    response_detik = round((datetime.now(timezone.utc) - mulai).total_seconds(), 1)

    status_kirim, error = "Gagal", "AI Email Parser/OpenAI belum dikonfigurasi (OPENAI_API_KEY kosong)"
    if balasan_ai:
        ok, err = await _kirim_via_provider(no_hp, balasan_ai)
        status_kirim = "Terkirim" if ok else "Gagal"
        error = err

    doc = {
        "id": str(uuid.uuid4()), "nama": nama, "no_hp": no_hp,
        "pesan_masuk": pesan_masuk, "balasan_ai": balasan_ai,
        "status_kirim": status_kirim, "error": error,
        "response_detik": response_detik, "waktu": now_iso(),
    }
    await db.wa_conversations.insert_one(doc)
    if status_kirim == "Gagal":
        await db.wa_connection_log.insert_one({
            "id": str(uuid.uuid4()), "event": "kirim_gagal",
            "detail": error, "ok": False, "waktu": now_iso(),
        })
    await _klasifikasi_dan_buat_tiket(no_hp, nama, pesan_masuk)
    doc.pop("_id", None)
    return {"ok": True, "balasan_ai": balasan_ai}


@api.post("/webhook/whatsapp/balesotomatis/{token}")
async def whatsapp_incoming_balesotomatis(token: str, request: Request):
    """Endpoint publik untuk BalesOtomatis.id (WA gateway resmi Meta yang dipakai user sejak
    2026-07-13) — kontrak payloadnya beda dari webhook generik di atas: nested
    {"type": "incoming_chat", "data": {chat_id, message_body, name, is_from_me, ...}}
    (contoh dari user), bukan {sender/from, message/text}. `token` dicocokkan ke
    `webhook_config.webhook_token` (dibuat otomatis di GET /konfigurasi-webhook) supaya URL
    ini tidak bisa dipanggil sembarang orang untuk menyuntik log palsu.

    Keputusan bisnis user (2026-07-13, revisi): BalesOtomatis tidak punya REST API publik
    untuk kirim pesan (dicek langsung ke halaman /rest-api mereka — cuma ada config webhook
    masuk, token pribadi, & daftar Device ID, tidak ada endpoint "send message"). TAPI
    BalesOtomatis konfirmasi (via CS) mereka punya fitur: begitu ada balasan yang dikirim
    "di luar AI bawaan mereka" untuk suatu chat, AI mereka otomatis freeze sementara
    (durasi diatur di dashboard mereka) lalu ON lagi sendiri — dipakai di sini supaya
    balasan PMS tidak dobel dengan AI bawaan.

    Karena tidak ada endpoint kirim pesan terpisah, satu-satunya jalur PMS untuk "membalas
    di luar AI mereka" adalah lewat response JSON webhook AI Trigger ini (field ini yang
    dipanggil BalesOtomatis saat pesan masuk) — makanya balasan AI di sini dikembalikan di
    body dengan beberapa nama field sekaligus (reply/message/balasan/text) karena skema
    persis yang mereka expect belum terkonfirmasi dari dokumentasi resmi. BELUM DIVERIFIKASI
    LIVE apakah BalesOtomatis benar-benar merelai response ini ke tamu — perlu tes end-to-end
    dulu (kirim pesan WA, cek apakah balasan di bawah benar-benar sampai ke tamu & AI mereka
    freeze setelahnya). Kalau ternyata tidak ada field yang cocok, balasan ini tidak akan
    terkirim ke tamu meski tersimpan di `wa_conversations` — perlu tanya CS field yang benar.
    """
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("webhook_token") or cfg["webhook_token"] != token:
        raise HTTPException(404, "Token webhook tidak valid")

    payload = await request.json()
    if payload.get("type") != "incoming_chat":
        return {"ok": True, "diabaikan": f"tipe event '{payload.get('type')}' tidak diproses"}

    data = payload.get("data") or {}
    if data.get("is_from_me"):
        return {"ok": True, "diabaikan": "pesan keluar dari nomor bisnis sendiri, bukan pesan masuk tamu"}

    chat_id = data.get("chat_id") or ""
    no_hp = chat_id.split("@")[0] if "@" in chat_id else chat_id
    nama = data.get("name") or no_hp or "Tidak diketahui"
    if data.get("has_media"):
        pesan_masuk = data.get("message_body") or f"[Lampiran: {data.get('media_name') or data.get('media_mime') or 'media'}]"
    else:
        pesan_masuk = data.get("message_body") or ""

    mulai = datetime.now(timezone.utc)
    balasan_ai = await _balasan_dengan_alur_booking(no_hp, nama, pesan_masuk) if pesan_masuk else None
    response_detik = round((datetime.now(timezone.utc) - mulai).total_seconds(), 1)

    await db.wa_conversations.insert_one({
        "id": str(uuid.uuid4()), "nama": nama, "no_hp": no_hp,
        "pesan_masuk": pesan_masuk, "balasan_ai": balasan_ai,
        "status_kirim": "Terkirim (via response webhook)" if balasan_ai else "Ditangani Provider",
        "error": None, "response_detik": response_detik, "waktu": now_iso(),
        "provider_message_id": data.get("message_id"),
    })
    if pesan_masuk:
        await _klasifikasi_dan_buat_tiket(no_hp, nama, pesan_masuk)
    if not balasan_ai:
        return {"ok": True}
    return {"ok": True, "reply": balasan_ai, "message": balasan_ai, "balasan": balasan_ai, "text": balasan_ai}


@api.api_route("/webhook/whatsapp/balesotomatis/{token}/pengetahuan", methods=["GET", "POST"])
async def balesotomatis_pengetahuan(token: str, request: Request):
    """Teks polos ketersediaan & harga kamar TERKINI, dipakai untuk mengisi Knowledge
    Base/FAQ AI bawaan BalesOtomatis (kalau dashboard mereka mendukung ambil info dari
    URL) atau disalin manual staf ke sana secara berkala. Ini jalan keluar dari
    keterbatasan `whatsapp_incoming_balesotomatis` di atas: AI bawaan BalesOtomatis yang
    balas (bukan PMS), jadi PMS hanya bisa menyuplai datanya lewat sini, bukan lewat
    balasan langsung. Token sama dengan URL Webhook Masuk supaya tidak perlu kredensial
    baru, dan publik (tanpa header Authorization) karena kolom URL sumber pengetahuan di
    dashboard provider pihak ketiga biasanya tidak bisa diisi header custom.

    Terima GET maupun POST: log nginx (2026-07-13) menunjukkan URL ini juga dipanggil
    lewat POST oleh sebuah AI Trigger di dashboard BalesOtomatis (bukan cuma fetch
    Knowledge-Base-dari-URL yang aslinya GET) — semula 405 di method POST, diduga jadi
    penyebab AI berhenti total tanpa balas ke tamu. GET tetap balas plain text (kontrak
    Knowledge Base), POST dibalas JSON multi-field sama seperti `cek_ketersediaan` di
    bawah karena skema respons AI Trigger belum terkonfirmasi.
    """
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("webhook_token") or cfg["webhook_token"] != token:
        raise HTTPException(404, "Token webhook tidak valid")
    teks = await _ringkasan_ketersediaan_untuk_ai()
    if request.method == "POST":
        return {"ok": True, "reply": teks, "message": teks, "balasan": teks, "text": teks, "response": teks, "output": teks}
    return PlainTextResponse(teks)


def _ambil_ai_input(payload: Dict[str, Any], key: str) -> Optional[str]:
    """AI Trigger BalesOtomatis belum ada dokumentasi kontrak payload resmi (How-to Guide
    mereka cuma generik API/webhook, bukan skema AI Trigger spesifik) — jaga-jaga baca key
    di top-level body ATAU di dalam salah satu wrapper umum yang biasa dipakai platform
    serupa, supaya tidak bergantung pada satu asumsi struktur yang belum terkonfirmasi."""
    if payload.get(key):
        return payload.get(key)
    for wrapper in ("data", "inputs", "ai_inputs", "variables", "payload"):
        nested = payload.get(wrapper)
        if isinstance(nested, dict) and nested.get(key):
            return nested.get(key)
    return None


async def _cocokkan_tipe_kamar(nilai: Optional[str]) -> Optional[str]:
    """AI mengekstrak tipe kamar dari bahasa bebas tamu (mis. 'cottage', 'kamar standard'),
    jadi dicocokkan longgar (substring, case-insensitive) ke tipe asli di `db.rooms`
    daripada exact-match yang gampang meleset."""
    if not nilai:
        return None
    semua_tipe = await db.rooms.distinct("tipe")
    nilai_lower = nilai.strip().lower()
    for t in semua_tipe:
        if nilai_lower in t.lower() or t.lower() in nilai_lower:
            return t
    return None


def _parse_tanggal_input(nilai: Optional[str]) -> str:
    if nilai:
        try:
            datetime.fromisoformat(nilai)
            return nilai
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m-%d")


@api.post("/webhook/whatsapp/balesotomatis/{token}/cek-ketersediaan")
async def balesotomatis_cek_ketersediaan(token: str, request: Request):
    """AI Trigger BalesOtomatis (beda dari Knowledge Base statis di endpoint `pengetahuan`
    di atas) — dipanggil AI mereka secara real-time saat tamu bertanya ketersediaan/harga
    kamar, dengan AI Inputs `tipe_kamar` & `tanggal_checkin` yang diekstrak dari isi chat.
    Ini mengatasi keterbatasan `pengetahuan` yang cuma snapshot statis: di sini data
    ketersediaan dihitung live per tanggal yang ditanyakan, pakai logika yang sama dengan
    halaman publik (`public_availability`, termasuk fix hari checkout tidak dianggap
    booked).

    Sama seperti `whatsapp_incoming_balesotomatis`, skema respons yang BalesOtomatis
    expect dari AI Trigger belum terkonfirmasi dari dokumentasi resmi (How-to Guide
    mereka cuma generik) — balasan dikembalikan di beberapa nama field sekaligus
    (reply/message/balasan/text/response/output). BELUM DIVERIFIKASI LIVE apakah salah
    satu field ini benar-benar dipakai AI mereka untuk membalas tamu.
    """
    cfg = await db.webhook_config.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("webhook_token") or cfg["webhook_token"] != token:
        raise HTTPException(404, "Token webhook tidak valid")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    tipe = await _cocokkan_tipe_kamar(_ambil_ai_input(payload, "tipe_kamar"))
    tanggal = _parse_tanggal_input(_ambil_ai_input(payload, "tanggal_checkin"))

    hasil = await public_availability(tanggal=tanggal, tipe=tipe)
    rooms = hasil["rooms"]

    if rooms:
        per_tipe: Dict[str, Dict[str, Any]] = {}
        for r in rooms:
            t = per_tipe.setdefault(
                r["tipe"], {"tarif": r["tarif"], "tarif_menginap": r["tarif_menginap"], "jumlah": 0}
            )
            t["jumlah"] += 1
        # Tampilkan harga Day Use & Menginap sekaligus (bukan tebak salah satu dari AI Input)
        # supaya AI BalesOtomatis tinggal pilih sendiri sesuai konteks pertanyaan tamu.
        baris = [
            f"{t}: {v['jumlah']} kamar tersedia. Day use Rp{v['tarif']:,} (6 jam), "
            f"Menginap Rp{v['tarif_menginap']:,}/malam".replace(",", ".")
            for t, v in per_tipe.items()
        ]
        teks = f"Ketersediaan kamar tanggal {tanggal}:\n" + "\n".join(baris)
    else:
        keterangan_tipe = f" tipe {tipe}" if tipe else ""
        teks = f"Mohon maaf, tidak ada kamar{keterangan_tipe} yang tersedia pada tanggal {tanggal}."

    return {"ok": True, "reply": teks, "message": teks, "balasan": teks, "text": teks, "response": teks, "output": teks}


@api.get("/pesan-whatsapp/rekomendasi-slot")
async def get_rekomendasi_slot(tipe: str, user: dict = Depends(get_current_user)):
    """Endpoint staf untuk cek/tes manual apa yang akan AI sampaikan ke tamu kalau tipe
    kamar ini penuh — dipakai juga untuk verifikasi logika tanpa perlu WhatsApp aktif."""
    rekom = await _rekomendasi_slot_kosong(tipe)
    return {"tipe": tipe, "rekomendasi": rekom}


@api.get("/pesan-whatsapp/percakapan")
async def list_percakapan(user: dict = Depends(get_current_user)):
    return await db.wa_conversations.find({}, {"_id": 0}).sort("waktu", -1).to_list(200)


@api.get("/pesan-whatsapp/percakapan/{conv_id}")
async def detail_percakapan(conv_id: str, user: dict = Depends(get_current_user)):
    c = await db.wa_conversations.find_one({"id": conv_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Percakapan tidak ditemukan")
    return c


def _hari_ini_range():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


@api.get("/pesan-whatsapp/stats")
async def whatsapp_stats(user: dict = Depends(get_current_user)):
    start, end = _hari_ini_range()
    convs = await db.wa_conversations.find({"waktu": {"$gte": start, "$lt": end}}, {"_id": 0}).to_list(1000)
    terkirim = sum(1 for c in convs if c["status_kirim"] == "Terkirim")
    total = len(convs)
    # "Ditangani Provider" (mis. BalesOtomatis dengan AI auto-reply sendiri) sengaja tidak
    # dihitung PMS sebagai gagal kirim di rasio ini — bukan PMS yang mencoba (dan gagal)
    # mengirim, jadi tidak representatif dicampur ke tingkat sukses kirim milik PMS sendiri.
    dikirim_pms = [c for c in convs if c["status_kirim"] in ("Terkirim", "Gagal")]
    reservasi_wa = await db.bookings.count_documents({"source": "whatsapp", "created_at": {"$gte": start, "$lt": end}})
    return {
        "pesan_masuk_hari_ini": total,
        "pesan_terkirim_hari_ini": terkirim,
        "tingkat_sukses_kirim": round(terkirim / len(dikirim_pms) * 100) if dikirim_pms else 100,
        "reservasi_via_wa_hari_ini": reservasi_wa,
    }


@api.get("/pemantauan-status-wa/stats")
async def pemantauan_stats(user: dict = Depends(get_current_user)):
    start, end = _hari_ini_range()
    convs = await db.wa_conversations.find({"waktu": {"$gte": start, "$lt": end}}, {"_id": 0}).to_list(1000)
    terkirim = sum(1 for c in convs if c["status_kirim"] == "Terkirim")
    gagal = sum(1 for c in convs if c["status_kirim"] == "Gagal")
    total = terkirim + gagal
    waktu_resp = [c["response_detik"] for c in convs if c.get("response_detik") is not None]
    return {
        "terkirim_hari_ini": terkirim,
        "gagal_hari_ini": gagal,
        "tingkat_sukses": round(terkirim / total * 100) if total else 100,
        "rata_respons_detik": round(sum(waktu_resp) / len(waktu_resp), 1) if waktu_resp else 0,
    }


@api.get("/pemantauan-status-wa/log-pengiriman")
async def log_pengiriman(user: dict = Depends(get_current_user)):
    """Log per-arah (masuk/keluar) — di-derive dari `wa_conversations` (satu percakapan
    menghasilkan satu baris "masuk" + satu baris "keluar" kalau ada balasan)."""
    convs = await db.wa_conversations.find({}, {"_id": 0}).sort("waktu", -1).to_list(200)
    out = []
    for c in convs:
        out.append({"id": f"{c['id']}-masuk", "conv_id": c["id"], "no_hp": c["no_hp"], "arah": "masuk", "status": "Diterima", "waktu": c["waktu"]})
        if c.get("balasan_ai") is not None:
            row = {"id": f"{c['id']}-keluar", "conv_id": c["id"], "no_hp": c["no_hp"], "arah": "keluar", "status": c["status_kirim"], "waktu": c["waktu"]}
            if c["status_kirim"] == "Gagal":
                row["error"] = c.get("error")
            out.append(row)
    return out


@api.post("/pemantauan-status-wa/log-pengiriman/{conv_id}/kirim-ulang")
async def kirim_ulang(conv_id: str, user: dict = Depends(require_owner)):
    c = await db.wa_conversations.find_one({"id": conv_id})
    if not c:
        raise HTTPException(404, "Pesan tidak ditemukan")
    if not c.get("balasan_ai"):
        raise HTTPException(400, "Tidak ada balasan AI untuk dikirim ulang")
    ok, err = await _kirim_via_provider(c["no_hp"], c["balasan_ai"])
    status_kirim = "Terkirim" if ok else "Gagal"
    await db.wa_conversations.update_one({"id": conv_id}, {"$set": {"status_kirim": status_kirim, "error": err}})
    await log_activity(user, "wa_kirim_ulang", f"Kirim ulang pesan ke {c['no_hp']}")
    return {"ok": ok, "status_kirim": status_kirim, "error": err}


@api.get("/pemantauan-status-wa/ringkasan-kegagalan")
async def ringkasan_kegagalan(user: dict = Depends(get_current_user)):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    gagal = await db.wa_conversations.find(
        {"status_kirim": "Gagal", "waktu": {"$gte": cutoff}}, {"_id": 0, "error": 1}
    ).to_list(1000)
    counts: Dict[str, int] = {}
    for g in gagal:
        alasan = g.get("error") or "Tidak diketahui"
        counts[alasan] = counts.get(alasan, 0) + 1
    return [{"alasan": a, "jumlah": n} for a, n in sorted(counts.items(), key=lambda x: -x[1])]


@api.get("/pemantauan-status-wa/connection-log")
async def connection_log(user: dict = Depends(get_current_user)):
    logs = await db.wa_connection_log.find({}, {"_id": 0}).sort("waktu", -1).to_list(100)
    return [{"id": l["id"], "status": "connected" if l.get("ok") else "disconnected", "keterangan": l["detail"], "waktu": l["waktu"]} for l in logs]


@api.get("/pemantauan-status-wa/alerts")
async def alerts(user: dict = Depends(get_current_user)):
    """Deteksi kegagalan beruntun ke nomor yang sama dalam 10 menit terakhir."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    gagal = await db.wa_conversations.find(
        {"status_kirim": "Gagal", "waktu": {"$gte": cutoff}}, {"_id": 0, "no_hp": 1, "waktu": 1}
    ).to_list(1000)
    per_nomor: Dict[str, int] = {}
    for g in gagal:
        per_nomor[g["no_hp"]] = per_nomor.get(g["no_hp"], 0) + 1
    out = []
    for no_hp, jumlah in per_nomor.items():
        if jumlah >= 3:
            out.append({
                "id": no_hp, "level": "error",
                "pesan": f"{jumlah} pesan gagal terkirim ke {no_hp} dalam 10 menit terakhir — nomor mungkin tidak aktif di WhatsApp.",
                "waktu": now_iso(),
            })
    return out


DEFAULT_WA_SYNC_SETTINGS = {
    "data_sync": {"ketersediaan": True, "harga": True, "status_booking": True, "reservasi_baru": False},
    "frekuensi": "realtime",
}


@api.get("/pesan-whatsapp/pengaturan")
async def get_wa_settings(user: dict = Depends(get_current_user)):
    s = await db.wa_sync_settings.find_one({}, {"_id": 0})
    return s or DEFAULT_WA_SYNC_SETTINGS


@api.put("/pesan-whatsapp/pengaturan")
async def update_wa_settings(body: Dict[str, Any], user: dict = Depends(require_owner)):
    await db.wa_sync_settings.update_one({}, {"$set": body}, upsert=True)
    await log_activity(user, "update_wa_settings", "Update pengaturan sinkronisasi WhatsApp Bot")
    return await db.wa_sync_settings.find_one({}, {"_id": 0}) or DEFAULT_WA_SYNC_SETTINGS
