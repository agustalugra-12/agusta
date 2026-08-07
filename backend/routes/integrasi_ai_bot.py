from core import *
import secrets
from routes.public import public_availability
from routes.issues import buat_issue
from routes.booking_requests import buat_booking_request
from routes.pesan_whatsapp import _cari_kamar_dari_no_hp
from routes.pembatalan import ajukan_pembatalan_ai
from scheduling_engine import rekomendasi_slot_kosong, timeline_kamar_hari_ini, BUFFER_HOUSEKEEPING_MENIT

# ---- Integrasi AI Chat Bot Eksternal ----
# Untuk "ai-chat-bot" (repo terpisah milik user, dirancang reusable lintas sistem — BUKAN
# cuma untuk Pelangi PMS). Arahnya SELALU satu arah: ai-chat-bot yang memanggil endpoint di
# sini (baca data live + tulis balik hasil klasifikasi/booking request); PMS ini TIDAK
# pernah memanggil ai-chat-bot atau WAHA sama sekali — transport WhatsApp (WAHA dkk) jadi
# urusan ai-chat-bot sendiri, sama seperti pola AI Trigger BalesOtomatis di
# pesan_whatsapp.py tapi digeneralisasi supaya tidak terikat satu WA provider/vendor.
#
# Auth pakai API key sendiri (collection `ai_bot_integration_config`, header
# `Authorization: Bearer <api_key>`) — BUKAN JWT staf (`get_current_user`), karena
# pemanggilnya sistem lain, bukan user login.
#
# BATASAN KERAS (sama seperti alur booking AI WhatsApp bawaan, lihat CLAUDE.md): endpoint
# tulis di sini SENGAJA TIDAK PERNAH bisa membuat booking sungguhan langsung — cuma bisa
# memanggil `buat_booking_request` (non-binding, staf approve manual) & `buat_issue`
# (tiket komplain/maintenance), fungsi yang sama persis dipakai jalur AI WhatsApp internal,
# supaya tidak ada logika ganda yang bisa saling menyimpang.

DEFAULT_AI_BOT_CONFIG = {"aktif": False, "api_key": None, "updated_at": None}


async def verifikasi_ai_bot_key(request: Request) -> str:
    """Multi-properti (Fase 4, 2026-07-25): `ai_bot_integration_config` bukan lagi
    singleton - 1 dokumen per properti, masing-masing punya API key sendiri (1 nomor
    WhatsApp/bot ai-chat-bot = 1 properti). Auth di sini TIDAK bisa lagi filter by
    property_id dari header (pemanggilnya ai-chat-bot, bukan user login PMS yang tahu
    konteks properti) - satu-satunya cara tahu properti mana adalah dari API KEY mana
    yang cocok. Return property_id yang cocok, supaya semua endpoint di file ini
    (Depends(verifikasi_ai_bot_key)) otomatis tahu harus scope ke properti mana.

    Loop bandingkan tiap kandidat key satu-satu (bukan query by api_key langsung) supaya
    tetap pakai secrets.compare_digest (constant-time) - jumlah properti kecil (2-5),
    jadi variasi waktu antar kandidat diabaikan (ini API key server-to-server milik
    sistem sendiri, bukan permukaan auth publik yang jadi target timing attack nyata)."""
    auth = request.headers.get("Authorization", "")
    key = auth[7:] if auth.startswith("Bearer ") else ""
    if not key:
        raise HTTPException(404, "Not Found")
    async for cfg in db.ai_bot_integration_config.find({"aktif": True, "api_key": {"$ne": None}}):
        if not cfg.get("property_id"):
            continue  # dokumen lama sebelum migrasi backfill sempat jalan - lewati, bukan crash
        if secrets.compare_digest(key, cfg["api_key"]):
            return cfg["property_id"]
    raise HTTPException(401, "API key tidak valid")


@api.get("/konfigurasi-integrasi-ai-bot")
async def get_ai_bot_config(user: dict = Depends(require_owner), property_id: str = Depends(get_active_property)):
    """`api_key` dibuat sekali otomatis kalau belum ada, supaya owner selalu punya key
    untuk ditempel ke konfigurasi ai-chat-bot sejak GET pertama (pola sama seperti
    `webhook_token` di konfigurasi_webhook.py). 1 dokumen per properti - owner kelola
    key propertinya masing-masing lewat switcher, bukan 1 key global untuk semua."""
    cfg = await db.ai_bot_integration_config.find_one(scoped({}, property_id), {"_id": 0})
    cfg = {**DEFAULT_AI_BOT_CONFIG, **(cfg or {}), "property_id": property_id}
    if not cfg.get("api_key"):
        cfg["api_key"] = secrets.token_hex(24)
        await db.ai_bot_integration_config.update_one(scoped({}, property_id), {"$set": cfg}, upsert=True)
    return cfg


@api.put("/konfigurasi-integrasi-ai-bot")
async def update_ai_bot_config(body: Dict[str, Any], user: dict = Depends(require_owner),
                               property_id: str = Depends(get_active_property)):
    updates = {"aktif": bool(body.get("aktif"))} if "aktif" in body else {}
    updates["updated_at"] = now_iso()
    updates["property_id"] = property_id
    await db.ai_bot_integration_config.update_one(scoped({}, property_id), {"$set": updates}, upsert=True)
    await log_activity(user, "update_ai_bot_config", "Update status integrasi AI Chat Bot eksternal")
    return await db.ai_bot_integration_config.find_one(scoped({}, property_id), {"_id": 0}) or DEFAULT_AI_BOT_CONFIG


@api.post("/konfigurasi-integrasi-ai-bot/regenerate-key")
async def regenerate_ai_bot_key(user: dict = Depends(require_owner), property_id: str = Depends(get_active_property)):
    new_key = secrets.token_hex(24)
    await db.ai_bot_integration_config.update_one(
        scoped({}, property_id), {"$set": {"api_key": new_key, "updated_at": now_iso(), "property_id": property_id}}, upsert=True
    )
    await log_activity(user, "regenerate_ai_bot_key", "Generate ulang API key integrasi AI Chat Bot")
    return await db.ai_bot_integration_config.find_one(scoped({}, property_id), {"_id": 0})


@api.get("/integrasi-ai-bot/ketersediaan")
async def ai_bot_ketersediaan(
    tanggal: Optional[str] = None, tipe: Optional[str] = None, jumlah_kamar: Optional[int] = None,
    jam_checkin: Optional[str] = None, property_id: str = Depends(verifikasi_ai_bot_key)
):
    """Ketersediaan & tarif kamar live per tanggal — logika sama dengan halaman publik
    `/book` (`public_availability`, termasuk fix hari checkout tidak dianggap booked),
    bukan hitungan ulang terpisah.

    **Perubahan 2026-07-19**: sebelumnya tipe yang 0 kamar kosong SAMA SEKALI TIDAK MUNCUL
    di hasil (AI tidak bisa membedakan "penuh" dari "tipe tidak ada") - sekarang SEMUA tipe
    kamar yang ada selalu muncul, termasuk yang `kamar_tersedia: 0`, supaya AI bisa jujur
    bilang "penuh" alih-alih menebak. Kalau penuhnya tanggal HARI INI khusus karena ada
    kamar Day Use yang akan checkout (bukan Menginap - lihat `estimasi_kamar_siap` di
    scheduling_engine.py), disertakan `estimasi_kosong_lagi` sebagai perkiraan jujur; kalau
    penuh karena Menginap atau tanggal bukan hari ini, field itu TIDAK ADA sama sekali -
    AI wajib bilang penuh apa adanya, tidak boleh menawarkan estimasi kosong.

    **Perubahan 2026-08-01** (keluhan Agus - test chat tamu minta 3 kamar tapi cuma 1
    kosong, AI tidak pernah kasih opsi menunggu): tambah `jumlah_kamar` opsional - kalau
    diisi (tamu sebutkan jumlah kamar yang dibutuhkan), estimasi_kosong_lagi dkk dihitung
    begitu `kamar_tersedia < jumlah_kamar` (bukan cuma pas PERSIS 0), dan jumlah kandidat
    yang dicari via rekomendasi_slot_kosong disesuaikan dgn KEKURANGANNYA. Field baru
    `kamar_diminta`/`kamar_kurang` disertakan kalau kondisi ini terpenuhi, supaya AI bisa
    bilang "X kamar sudah ada sekarang, Y kamar lagi kemungkinan siap sekitar jam Z" alih-
    alih cuma bilang "cuma ada X" tanpa opsi menunggu. Tidak diisi = perilaku lama
    (default 1, sama seperti sebelum perubahan ini).

    **Perubahan 2026-08-01** (bug nyata ditemukan dari laporan Agus - tamu Vina tanya Day
    Use BESOK jam 10 pagi, AI jawab "tersedia banyak" padahal SEMUA kamar Standard baru
    checkout tamu menginap jam 12 siang hari itu): tambah `jam_checkin` opsional ("HH:MM"
    WIB) - diteruskan ke public_availability, yang utk Day Use (bukan multi-malam menginap)
    akan menyaring ulang pakai overlap presisi jam, bukan cuma tanggal (lihat docstring
    public_availability utk detail). Tidak diisi = perilaku lama (cuma cek tanggal)."""
    tanggal = tanggal or datetime.now().strftime("%Y-%m-%d")
    hasil = await public_availability(tanggal=tanggal, tipe=tipe, property_id_override=property_id, jam_checkin=jam_checkin)

    q: Dict[str, Any] = {"tipe": tipe} if tipe else {}
    semua_kamar = await db.rooms.find(scoped(q, property_id), {"_id": 0, "tipe": 1, "tarif": 1, "tarif_menginap": 1}).to_list(500)
    # Harmoni tidak menyediakan sarapan sama sekali (2026-07-31, permintaan user) - field
    # tarif_menginap_dengan_sarapan HANYA disertakan kalau propertinya memang menyediakan,
    # supaya AI tidak menawarkan/mengarang opsi sarapan yang tidak nyata ada.
    ada_sarapan = await property_ada_sarapan(property_id)
    per_tipe: Dict[str, Dict[str, Any]] = {}
    for r in semua_kamar:
        item = {"tarif_day_use": r["tarif"], "tarif_menginap": r["tarif_menginap"], "kamar_tersedia": 0}
        if ada_sarapan:
            # (2026-07-31, permintaan user) - AI sebelumnya tidak pernah tahu harga
            # menginap+sarapan sama sekali (cuma tarif_menginap tanpa sarapan), jadi tidak
            # bisa menjawab benar kalau tamu tanya "kalau dengan sarapan berapa?". Dihitung
            # di sini (SATU sumber kebenaran, sama dgn calc_tagihan/generate_voucher_pdf),
            # bukan ditebak/dihitung ulang oleh AI sendiri.
            item["tarif_menginap_dengan_sarapan"] = r["tarif_menginap"] + BREAKFAST_PRICE
        per_tipe.setdefault(r["tipe"], item)
    for r in hasil["rooms"]:
        if r["tipe"] in per_tipe:
            per_tipe[r["tipe"]]["kamar_tersedia"] += 1

    is_today = tanggal == datetime.now().strftime("%Y-%m-%d")
    # Bug nyata ditemukan 2026-08-01 (keluhan Agus - test chat tamu minta 3 kamar tapi cuma
    # 1 yang kosong): SEBELUMNYA estimasi_kosong_lagi cuma dihitung kalau kamar_tersedia
    # PERSIS 0 - kalau tamu minta LEBIH dari yang tersedia (mis. minta 3, ada 1), AI tidak
    # pernah dikasih tahu ada kemungkinan kamar tambahan siap lagi hari ini (dari Day Use
    # yang akan checkout) - cuma bilang "cuma ada 1" tanpa menawarkan opsi menunggu. Sekarang
    # `jumlah_kamar` (opsional, dari check_availability tool - diisi AI kalau tamu sebut
    # jumlah kamar) dipakai: estimasi dihitung kalau kamar_tersedia < jumlah yang diminta
    # (default 1, sama seperti perilaku lama kalau tidak diisi), dan jumlah kandidat yang
    # diminta ke rekomendasi_slot_kosong disesuaikan dengan KEKURANGANNYA, bukan selalu 3.
    diminta = max(1, int(jumlah_kamar or 1))
    out = []
    for t, v in per_tipe.items():
        item = {"tipe": t, **v}
        kekurangan = diminta - v["kamar_tersedia"]
        if kekurangan > 0 and diminta > 1:
            item["kamar_diminta"] = diminta
            item["kamar_kurang"] = kekurangan
        if kekurangan > 0 and is_today:
            rekom = await rekomendasi_slot_kosong(t, property_id, jumlah=kekurangan)
            if rekom:
                item["estimasi_kosong_lagi"] = rekom["siap_pakai"].isoformat()
                item["estimasi_kamar_nomor"] = rekom["room_nomor"]
                # Jam checkout MENTAH, terpisah dari "siap_pakai" (2026-08-02, permintaan
                # Agus - contoh nyata: "saat ini full kk, tersedia lagi 15.56 dan ready jam
                # 16.30 apa kk mau?"). `siap_pakai` SUDAH termasuk buffer housekeeping
                # (BUFFER_HOUSEKEEPING_MENIT, lihat estimasi_kamar_siap) - dulu itu SATU-
                # SATUNYA angka yang dikasih ke AI, jadi AI tidak bisa membedakan "kapan tamu
                # lama checkout" vs "kapan benar-benar siap dipakai tamu baru setelah
                # dibersihkan". Sekarang keduanya dikirim terpisah supaya AI bisa jujur & lebih
                # jelas ke tamu ("checkout jam X, siap dipakai lagi ~jam Y setelah
                # dibersihkan") - dihitung mundur dari siap_pakai (bukan hitung ulang terpisah)
                # supaya tetap 1 sumber kebenaran (estimasi_kamar_siap), tidak ada risiko dua
                # angka saling menyimpang.
                item["estimasi_checkout_asli"] = (
                    rekom["siap_pakai"] - timedelta(minutes=BUFFER_HOUSEKEEPING_MENIT)
                ).isoformat()
                # Durasi Day Use utk kandidat ini mungkin lebih pendek dari 6 jam standar
                # kalau ada tamu Menginap check-in tak lama setelah kamar ini siap
                # (2026-08-01) - AI wajib sampaikan ini, jangan janjikan durasi penuh.
                if rekom.get("dipersingkat"):
                    item["estimasi_durasi_dipersingkat"] = True
                    item["estimasi_selesai_max"] = rekom["usulan_selesai"].isoformat()
                # Kandidat kamar/tipe lain yang juga akan siap hari ini (2026-08-01,
                # permintaan Agus - tawarkan pilihan seperti CS manusia, bukan cuma 1 opsi).
                if rekom.get("alternatif"):
                    item["estimasi_alternatif"] = [
                        {"room_nomor": a["room_nomor"], "siap_pakai": a["siap_pakai"].isoformat()}
                        for a in rekom["alternatif"]
                    ]
        out.append(item)
    return {"tanggal": tanggal, "ketersediaan": out}


@api.get("/integrasi-ai-bot/timeline-kamar")
async def ai_bot_timeline_kamar(property_id: str = Depends(verifikasi_ai_bot_key)):
    """Gambaran operasional PENUH kamar hari ini - SEMUA kamar Day Use yang sedang
    berlangsung + kamar yang sedang/menunggu dibersihkan, masing-masing dengan estimasi
    jam siap lagi (2026-08-01, permintaan Agus: AI selalu sinkron dengan situasi kamar
    terkini PMS, bukan cuma tahu pas ditanya spesifik). Beda dari /ketersediaan (yang fokus
    hitung slot per tipe kamar) - endpoint ini daftar mentah tiap kamar individual, dipakai
    ai-chat-bot untuk konteks yang SELALU disuntik tiap giliran chat (lihat _build_context),
    bukan tool yang perlu dipanggil AI secara eksplisit. Lihat timeline_kamar_hari_ini di
    scheduling_engine.py untuk detail perhitungan tiap jenis estimasi."""
    return {"timeline": await timeline_kamar_hari_ini(property_id)}


@api.get("/integrasi-ai-bot/menu")
async def ai_bot_menu(property_id: str = Depends(verifikasi_ai_bot_key)):
    """Menu makanan/minuman kasir - LIVE dari data kasir PMS (db.products), SATU sumber
    kebenaran yang sama dipakai halaman Kasir staf, BUKAN salinan terpisah yang bisa basi
    (2026-08-01, permintaan Agus - pengetahuan menu ai-chat-bot sebelumnya data seed/demo
    yang sama sekali tidak sinkron dengan menu kasir asli). Cuma produk `aktif:true` yang
    disertakan (produk nonaktif/dihapus staf tidak boleh muncul ke tamu). `stok` disertakan
    apa adanya supaya AI bisa jujur bilang jumlah tersisa atau "stok terbatas"/habis -
    JANGAN dibulatkan/disamarkan di sini, biar AI sendiri yang putuskan cara menyampaikan
    berdasar aturan di prompt-nya."""
    produk = await db.products.find(
        scoped({"aktif": True}, property_id),
        {"_id": 0, "nama": 1, "kategori": 1, "harga": 1, "stok": 1},
    ).sort("kategori", 1).to_list(500)
    return {"menu": produk}


class AiBotTiketIn(BaseModel):
    tipe: str  # complaint | maintenance (divalidasi di buat_issue)
    deskripsi: str
    no_hp: str
    nama_tamu: str = ""
    room_nomor: Optional[str] = None  # kalau tamu sebutkan nomor kamarnya sendiri di chat (2026-07-20)


@api.post("/integrasi-ai-bot/tiket")
async def ai_bot_buat_tiket(body: AiBotTiketIn, property_id: str = Depends(verifikasi_ai_bot_key)):
    """Sama seperti `_klasifikasi_dan_buat_tiket` di pesan_whatsapp.py — tapi klasifikasinya
    sudah dilakukan ai-chat-bot sendiri, di sini cuma menulis tiketnya.

    room_nomor yang tamu sebutkan LANGSUNG di chat lebih diprioritaskan daripada pencarian
    otomatis by no_hp (2026-07-20, ditemukan lewat tes live: guest_service belum pernah
    dites sama sekali karena nomor WA Resepsionis belum pernah dihubungkan - begitu dites
    via Simulator, tiket maintenance/service_request selalu punya room_nomor KOSONG walau
    tamu jelas menyebut nomor kamarnya, karena pencarian by no_hp gagal kalau nomor WA tamu
    tidak persis cocok dengan yang tercatat di checkin/booking aktif)."""
    room_id, room_nomor = None, ""
    if body.room_nomor:
        raw = body.room_nomor.strip()
        r = await db.rooms.find_one(scoped({"nomor": raw}, property_id))
        if not r:
            # AI kadang kirim teks bebas ("kamar 12"/"room 12") bukan cuma angka murni
            # seperti tersimpan di db.rooms.nomor ("12") - coba ekstrak angkanya.
            m = re.search(r"\d+", raw)
            if m:
                r = await db.rooms.find_one(scoped({"nomor": m.group(0)}, property_id))
        if r:
            room_id, room_nomor = r["id"], r["nomor"]
    if not room_id:
        room_id, room_nomor = await _cari_kamar_dari_no_hp(body.no_hp, property_id)
    if not room_id and body.room_nomor:
        room_nomor = body.room_nomor.strip()  # tidak match db.rooms persis, tetap tampilkan apa adanya
    tiket = await buat_issue(
        body.tipe, body.deskripsi, {"id": "ai-chat-bot", "nama": "AI Chat Bot", "role": "owner"}, property_id,
        room_id=room_id, room_nomor=room_nomor, nama_tamu=body.nama_tamu, no_hp=body.no_hp,
    )
    return {"ok": True, "tiket": tiket}


@api.get("/integrasi-ai-bot/rules")
async def ai_bot_rules(category: Optional[str] = None, _: str = Depends(verifikasi_ai_bot_key)):
    """Business Rules (DP/cancellation/checkin/checkout/promo/dll) — PMS jadi satu-satunya
    sumber kebenaran (lihat routes/business_rules.py), ai-chat-bot menarik ini untuk
    dijadikan konteks AI menjawab tamu, bukan menyimpan salinan kebijakan sendiri yang bisa
    basi. Hanya rule aktif yang diekspos, field internal (id/created_at/dll) disederhanakan."""
    q: Dict[str, Any] = {"is_active": True}
    if category:
        q["category"] = category
    rules = await db.business_rules.find(q, {"_id": 0}).to_list(500)
    return {
        "rules": [
            {"category": r["category"], "title": r["title"], "description": r["description"], "value": r.get("value")}
            for r in rules
        ],
    }


@api.get("/integrasi-ai-bot/status-member")
async def ai_bot_status_member(no_hp: str, property_id: str = Depends(verifikasi_ai_bot_key)):
    """Status Program Loyalitas Kedatangan tamu (2026-07-21, permintaan user: AI harus bisa
    proaktif sebut diskon member di AWAL percakapan saat tamu tunjukkan niat booking, bukan
    cuma pas booking sudah dibuat) - reuse penuh hitung_diskon_member, satu-satunya sumber
    kebenaran, sama dipakai create_reservation/buat_booking_request."""
    info = await hitung_diskon_member(property_id, no_hp)
    return {"kedatangan_ke": info["kedatangan_ke"], "diskon_persen": info["diskon_persen"]}


@api.get("/integrasi-ai-bot/booking-status")
async def ai_bot_booking_status(no_hp: str, property_id: str = Depends(verifikasi_ai_bot_key)):
    """Status booking request tamu (dicari dari no_hp, 5 permintaan terbaru) — reuse
    penuh logika pengayaan `status_efektif`/`booking_ringkasan` yang sama dipakai halaman
    staf /booking-requests (lihat list_booking_requests), supaya AI menjawab status yang
    sama persis dengan yang staf lihat, bukan hitungan terpisah yang bisa menyimpang."""
    digits = re.sub(r"\D", "", no_hp or "")
    if not digits:
        return {"no_hp": no_hp, "permintaan": []}
    variasi = {digits}
    if digits.startswith("62"):
        variasi.add("0" + digits[2:])
    elif digits.startswith("0"):
        variasi.add("62" + digits[1:])

    items = await db.booking_requests.find(
        scoped({"no_hp": {"$in": list(variasi)}}, property_id), {"_id": 0}
    ).sort("created_at", -1).to_list(5)

    out = []
    for it in items:
        status_efektif = it["status"]
        booking_ringkasan = None
        if it.get("booking_ids"):
            # status != "cancelled": booking yang SUDAH tuntas dibatalkan (approved + refund
            # selesai) sebelumnya tetap muncul di sini apa adanya (jalur ini, beda dari
            # direct_bookings di bawah, tidak pernah filter status booking sama sekali) - AI
            # jadi nawarin/muter balik ke booking yang sudah tuntas dibatalkan seolah masih
            # aktif (ditemukan 2026-07-21 dari laporan user).
            bks = await db.bookings.find(
                scoped({"id": {"$in": it["booking_ids"]}, "status": {"$ne": "cancelled"}}, property_id), {"_id": 0}
            ).to_list(20)
            if bks:
                booking_ringkasan = [{
                    "kode": b["kode"], "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
                    "sync_status": b.get("sync_status"),
                    # sudah_diajukan_pembatalan: ditemukan 2026-07-21 - booking dengan
                    # permintaan pembatalan yang masih menunggu staf TETAP tampil seolah
                    # booking aktif biasa di sini (status_bayar_booking tidak tahu soal ini),
                    # bikin AI muter balik nawarin batalkan booking yang SAMA berulang kali
                    # padahal server (ajukan_pembatalan_ai) akan tolak permintaan kedua.
                    "sudah_diajukan_pembatalan": b.get("cancel_request_status") in ("requested", "pending"),
                    **status_bayar_booking(b),  # status_bayar, jumlah_dibayar, sisa_tagihan
                } for b in bks]
                # Bug ditemukan 2026-07-21: sebelumnya cek `payment_status == "paid"` doang -
                # itu TRUE juga utk DP yang sudah dibayar (gateway cuma tau "ada settlement",
                # bukan "lunas 100%"), jadi tamu yang baru DP 50% salah dilabeli "lunas" di sini
                # (AI ikut2an bilang "sudah lunas" ke tamu, padahal cuma DP - lihat
                # status_bayar_booking utk definisi lunas yang benar: terkumpul >= total).
                if it["status"] == "waiting_payment" and all(br.get("status_bayar") == "lunas" for br in booking_ringkasan):
                    status_efektif = "lunas"
        out.append({
            "kode": it["kode"], "tipe": it["tipe"], "room_tipe": it.get("room_tipe"),
            "tanggal_checkin": it["tanggal_checkin"], "tanggal_checkout": it.get("tanggal_checkout"),
            "status": status_efektif, "booking_ringkasan": booking_ringkasan,
            "created_at": it["created_at"],
        })

    # Bookings LANGSUNG (public /book, walk-in Quick Book, OTA) TIDAK PERNAH punya dokumen
    # booking_requests (2026-07-19, ditemukan saat audit reliabilitas) - sebelumnya tamu yang
    # booking Day Use lewat website publik lalu coba batalkan via chat AI WhatsApp SELALU
    # dijawab "tidak ditemukan", padahal booking-nya nyata & ajukan_pembatalan_ai
    # (routes/pembatalan.py) sendiri sudah bekerja untuk booking manapun by kode - gap-nya
    # murni di pencarian ini. Disatukan di sini supaya AI bisa temukan & bantu batalkan
    # booking dari channel manapun, bukan cuma yang dia buat sendiri.
    sudah_termasuk = {b["kode"] for it in out for b in (it.get("booking_ringkasan") or [])}
    direct_bookings = await db.bookings.find(scoped({
        "no_hp": {"$in": list(variasi)},
        "status": {"$in": ["aktif", "booking_pending", "booking_paid", "checked_in"]},
    }, property_id), {"_id": 0}).sort("created_at", -1).to_list(5)
    for b in direct_bookings:
        if b["kode"] in sudah_termasuk:
            continue
        sb = status_bayar_booking(b)
        out.append({
            "kode": b["kode"], "tipe": b.get("tipe"), "room_tipe": b.get("room_tipe"),
            "tanggal_checkin": (b.get("jam_mulai") or "")[:10],
            "tanggal_checkout": (b.get("jam_selesai") or "")[:10] if b.get("tipe") == "menginap" else None,
            "status": "lunas" if sb["status_bayar"] == "lunas" else "waiting_payment",
            "booking_ringkasan": [{
                "kode": b["kode"], "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
                "sync_status": b.get("sync_status"),
                "sudah_diajukan_pembatalan": b.get("cancel_request_status") in ("requested", "pending"),
                **sb,
            }],
            "created_at": b.get("created_at"),
        })
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"no_hp": no_hp, "permintaan": out[:5]}


class AiBotBookingRequestIn(BaseModel):
    nama_tamu: str
    no_hp: str
    tipe: str  # day_use | menginap
    tanggal_checkin: str
    room_tipe: Optional[str] = None
    jumlah_kamar: Optional[int] = None
    jumlah_tamu: Optional[int] = None
    jam_checkin: Optional[str] = None
    tanggal_checkout: Optional[str] = None
    catatan: Optional[str] = None
    payment_option: Optional[str] = None  # dp50 | full, kalau tamu sudah sebutkan sendiri
    # Preferensi metode Tripay (2026-08-01) - QRIS2|PERMATAVA|BNIVA|BRIVA|MANDIRIVA, kalau
    # tamu sudah sebutkan sendiri di chat. None/nilai tidak dikenal = fallback QRIS di
    # auto-approve (lihat TRIPAY_METODE_VALID, routes/booking_requests.py).
    metode_pembayaran: Optional[str] = None
    # Diskon diskresi (2026-07-21) - True HANYA kalau tamu SENDIRI yang minta diskon di
    # chat (kebijakan bisnis: AI tidak boleh menawarkan duluan). Persentasenya TIDAK
    # dipercaya dari sini - dihitung ulang server dari data booking (hitung_diskon_ai_diskresi
    # di core.py), field ini cuma sinyal boolean "apakah diskon berlaku sama sekali".
    diskon_diminta_tamu: bool = False
    # Sarapan (2026-08-07, bug nyata ditemukan - tamu Riyan Sumardika minta Menginap
    # dengan sarapan tapi lapangan ini tidak pernah ada sebelumnya, jadi selalu kena
    # tarif tanpa sarapan) - HANYA relevan untuk tipe menginap, lihat BREAKFAST_PRICE
    # di core.py & _hitung_preview_harga.
    dengan_sarapan: bool = False


class AiBotPreviewHargaIn(BaseModel):
    no_hp: str
    tipe: str  # day_use | menginap
    room_tipe: str
    tanggal_checkin: str
    tanggal_checkout: Optional[str] = None
    jumlah_kamar: Optional[int] = None
    diskon_diminta_tamu: bool = False
    dengan_sarapan: bool = False


@api.post("/integrasi-ai-bot/preview-harga")
async def ai_bot_preview_harga(body: AiBotPreviewHargaIn, property_id: str = Depends(verifikasi_ai_bot_key)):
    """Preview rincian harga (termasuk diskon member & diskresi) SEBELUM booking_request
    sungguhan dibuat - read-only, TIDAK menulis apapun ke DB (2026-07-21, permintaan user:
    AI harus ringkas & konfirmasi data+harga ke tamu SEBELUM benar-benar diajukan, bukan
    setelah). Reuse penuh _hitung_diskon_gabungan, sumber kebenaran yang sama dipakai
    buat_booking_request - angka di sini WAJIB konsisten dengan yang benar-benar terjadi
    kalau lanjut ke create_booking dengan data identik."""
    from routes.booking_requests import _hitung_diskon_gabungan
    diskon_info, diskon_ai_persen, diskon_persen_efektif, preview_harga = await _hitung_diskon_gabungan(body.model_dump(), property_id)
    return {
        "kedatangan_ke": diskon_info["kedatangan_ke"],
        "diskon_member_persen": diskon_info["diskon_persen"],
        "diskon_ai_persen": diskon_ai_persen,
        "preview_harga": preview_harga,
    }


@api.post("/integrasi-ai-bot/booking-request")
async def ai_bot_buat_booking_request(body: AiBotBookingRequestIn, property_id: str = Depends(verifikasi_ai_bot_key)):
    """Non-binding, persis alur booking AI WhatsApp internal (`_proses_giliran_booking` di
    pesan_whatsapp.py) — staf tetap yang Terima/Tolak manual di /booking-requests, endpoint
    ini TIDAK PERNAH membuat booking sungguhan langsung."""
    if body.tipe not in ("day_use", "menginap"):
        raise HTTPException(400, "tipe harus 'day_use' atau 'menginap'")
    hasil = await buat_booking_request(body.model_dump(), property_id)
    return {"ok": True, "booking_request": hasil}


class AiBotCancelRequestIn(BaseModel):
    kode: Optional[str] = None  # kode booking (BKO-...), BUKAN kode booking_request (REQ-...). Opsional - kosong = cari otomatis dari no_hp (lihat ajukan_pembatalan_ai)
    no_hp: str
    alasan: Optional[str] = ""


@api.post("/integrasi-ai-bot/cancel-request")
async def ai_bot_ajukan_pembatalan(body: AiBotCancelRequestIn, property_id: str = Depends(verifikasi_ai_bot_key)):
    """Non-binding — sama seperti booking-request, endpoint ini TIDAK PERNAH mengeksekusi
    pembatalan sungguhan langsung (lihat routes/pembatalan.py). AI cuma menyampaikan info
    (kode booking, nomor tamu, alasan) ke PMS; PMS mencatat & staf yang approve/reject
    manual di Dashboard/halaman Pembatalan."""
    # Sengaja SELALU 200 (bukan raise HTTPException on ok=false) - kalau gagal karena
    # tamu punya >1 booking aktif, field "kandidat" perlu tetap sampai ke ai-chat-bot
    # supaya AI bisa tanya tamu mana yang dimaksud (2026-07-21, HTTPException(400, str)
    # sebelumnya MEMBUANG field kandidat, cuma pesan errornya yang sampai).
    return await ajukan_pembatalan_ai(body.kode, body.no_hp, property_id, body.alasan or "")


class AiBotAlertIn(BaseModel):
    pesan: str


@api.post("/integrasi-ai-bot/alert-owner")
async def ai_bot_alert_owner(body: AiBotAlertIn, _: str = Depends(verifikasi_ai_bot_key)):
    """Relay alert Telegram ke owner (2026-07-20) - dipakai ai-chat-bot untuk lapor masalah
    infrastrukturnya sendiri (mis. koneksi WhatsApp/WAHA terputus) lewat channel yang SUDAH
    ada & sudah terhubung ke HP owner (Telegram bot PMS), bukan bikin integrasi Telegram
    terpisah lagi di ai-chat-bot. Sengaja generik (cuma terima teks bebas) - ai-chat-bot
    yang menentukan isinya, PMS cuma jadi jalur kirim."""
    from routes.telegram_bot import kirim_alert_owner
    await kirim_alert_owner(body.pesan)
    return {"ok": True}
