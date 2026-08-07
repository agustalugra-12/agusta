"""Booking Request — Tahap 1 dari PRD "Modul Reservasi, Priority Booking & Payment Flow"
(diberi lampu hijau user 2026-07-17, lihat CLAUDE.md & memory project_reservasi_priority_booking_prd).

Entitas baru (`db.booking_requests`) — permintaan booking dikumpulkan AI WhatsApp
(routes/pesan_whatsapp.py, atau ai-chat-bot lewat routes/integrasi_ai_bot.py), baru
menjadi booking sungguhan (`db.bookings`) lewat `buat_booking_request()` — fungsi itu
sendiri tidak pernah membuat booking, cuma permintaan.

**Perubahan 2026-07-19 (dikonfirmasi user)**: Day Use dengan `payment_option` yang sudah
jelas dari tamu sekarang di-AUTO-APPROVE (`_coba_auto_approve_day_use`) - kamar dipilih
otomatis dari ketersediaan real-time, booking + transaksi Tripay dibuat langsung, link
bayar auto-terkirim, TANPA menunggu staf klik Terima di PMS. Menginap TETAP WAJIB direview
manual staf (butuh sinkron manual ke PMS RedDoorz, tidak bisa diotomatisasi sepenuhnya).
Kalau Day Use BENAR-BENAR penuh (tidak ada kamar kosong sama sekali di tanggal/tipe itu),
`_auto_reject_penuh` langsung menolak otomatis & mengabari tamu SAAT ITU JUGA (status
"rejected", `rejected_by="AI WhatsApp (otomatis)"`) - TIDAK dibiarkan nyangkut menunggu
staf sadar sendiri, karena staf pun tidak akan pernah bisa approve request yang memang
tidak ada kamarnya. Kalau auto-approve gagal/tidak berlaku karena alasan LAIN (>1 kamar,
payment_option belum disebutkan tamu), fallback ke alur lama: booking_request tetap
non-binding "waiting_approval", staf review manual (approve/reject di bawah).

Tahap 1 SENGAJA berhenti setelah tamu membayar (booking real dibuat & dibayar via Tripay
persis seperti alur publik yang sudah ada — reuse `create_reservation`/`tripay_create_transaction`,
tidak ada jalur pembayaran paralel baru). Bagian PRD yang BELUM dibangun di sini (Tahap 2,
menyusul terpisah): status "Action Required" untuk booking Menginap (input manual ke PMS
RedDoorz), penyaringan booking Menginap dari Calendar/Dashboard/Housekeeping/Laporan sampai
email konfirmasi RedDoorz diterima, dan mematikan/redirect tombol Book Now publik.
"""
from core import *
from reservation_service import create_reservation
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

STATUS_TERBUKA = ["waiting_approval"]

# Lock in-process per booking_request (2026-07-19, lanjutan audit anti-race-condition -
# lihat room_locks di reservation_service.py untuk pola & alasan yang sama: MongoDB
# standalone tanpa transaction, backend 1 proses). Mencegah 2 staf approve/reject
# permintaan yang SAMA nyaris bersamaan sama-sama lolos cek status "waiting_approval"
# sebelum salah satu sempat menulis - yang bisa menghasilkan 2 booking asli (+2 transaksi
# Tripay) dari 1 permintaan tamu. Ini BUKAN soal bentrok kamar (itu sudah aman lewat
# room_locks di create_reservation, kamar berbeda pun bisa dipilih tiap approval) - ini
# soal jangan sampai 1 permintaan tamu diproses/dipenuhi dua kali.
_request_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def _request_lock(rid: str):
    lock = _request_locks[rid]
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()

# Channel Tripay FALLBACK untuk auto-approve (QRIS - paling universal di Indonesia,
# hampir semua e-wallet/mobile banking bisa scan) - dipakai HANYA kalau tamu tidak
# menyebutkan preferensi metode pembayaran sendiri di chat. Kode Tripay sungguhan "QRIS2",
# BUKAN "QRIS" - dicek langsung ke GET /payments/tripay/channels sebelum dipakai di sini.
AUTO_APPROVE_PAYMENT_METHOD = "QRIS2"

# Metode pembayaran valid yang boleh dipilih tamu lewat AI WhatsApp (2026-08-01, permintaan
# user - sebelumnya AI selalu memaksa QRIS tanpa menawarkan pilihan lain walau Tripay
# sudah aktif dengan banyak channel). Dicocokkan ke kode channel Tripay sungguhan yang
# aktif di akun T51494 (GET /payments/tripay/channels) - kalau Tripay nambah/kurangi
# channel aktif di masa depan, sesuaikan set ini juga.
TRIPAY_METODE_VALID = {"QRIS2", "PERMATAVA", "BNIVA", "BRIVA", "MANDIRIVA"}


def _kode_request() -> str:
    return f"REQ-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"


def _hitung_malam(data: Dict[str, Any]) -> int:
    """Jumlah malam menginap dari tanggal_checkin/checkout - 1 untuk day_use (tidak
    relevan). Diekstrak dari _hitung_preview_harga (2026-07-21) supaya bisa dipakai juga
    oleh hitung_diskon_ai_diskresi di buat_booking_request tanpa hitung ulang terpisah."""
    if data.get("tipe") != "menginap":
        return 1
    try:
        ci = datetime.fromisoformat(data["tanggal_checkin"]).date()
        co = datetime.fromisoformat(data["tanggal_checkout"]).date()
        return max(1, (co - ci).days)
    except Exception:
        return 1


async def _hitung_preview_harga(data: Dict[str, Any], diskon_persen: int, property_id: str) -> Optional[Dict[str, Any]]:
    """Preview rincian harga (subtotal, diskon, service fee 3%, total) SEBELUM kamar
    spesifik dipilih/staf approve - pakai tarif TIPE kamar (sama untuk semua kamar tipe itu
    di db.rooms), supaya AI bisa jelaskan rincian ke tamu SAAT itu juga (2026-07-20,
    permintaan user: tamu harus dijelaskan harga kamar, service 3%, & diskon yang didapat
    setelah menawarkan DP/lunas). None kalau room_tipe tidak ditemukan - AI tetap bisa
    lanjut tanpa rincian (fallback aman, bukan tool gagal total)."""
    if not data.get("room_tipe"):
        return None
    room = await db.rooms.find_one(scoped({"tipe": data["room_tipe"]}, property_id))
    if not room:
        return None
    jumlah_kamar = max(1, int(data.get("jumlah_kamar") or 1))
    if data.get("tipe") == "menginap":
        nights = _hitung_malam(data)
        # Sarapan (2026-08-07, bug nyata ditemukan - tamu Riyan Sumardika: AI benar
        # menyebutkan harga "dengan sarapan Rp175.000" ke tamu, TAPI create_booking
        # tool-nya tidak pernah punya parameter dengan_sarapan sama sekali - preview
        # & booking_request selalu pakai tarif TANPA sarapan (150.000) walau tamu
        # eksplisit minta sarapan. Sama pola BREAKFAST_PRICE yang SUDAH benar di
        # routes/public.py & routes/bookings.py, cuma alur booking_request (AI
        # WhatsApp) yang kelupaan dari awal.
        tarif_dasar_per_malam = int(room["tarif_menginap"])
        if data.get("dengan_sarapan") and await property_ada_sarapan(property_id):
            tarif_dasar_per_malam += BREAKFAST_PRICE
        tarif_per_kamar = tarif_dasar_per_malam * nights
    else:
        tarif_per_kamar = int(room["tarif"])
    subtotal_sebelum_diskon = tarif_per_kamar * jumlah_kamar
    hasil_diskon = terapkan_diskon_member(subtotal_sebelum_diskon, diskon_persen)
    subtotal = hasil_diskon["subtotal"]
    diskon_rp = hasil_diskon["diskon_rp"]
    # Bug nyata ditemukan 2026-07-28 (audit akurasi diskon member, permintaan user): service
    # fee di sini SEBELUMNYA dihitung dari `subtotal` (SUDAH dipotong diskon) - beda dari
    # reservation_service.py (jalur SUNGGUHAN saat staf approve booking request ini), yang
    # menghitung service_fee dari subtotal SEBELUM diskon lalu TIDAK menghitung ulang setelah
    # diskon diterapkan (`terapkan_diskon_member` cuma ubah `subtotal`, `service_fee` tetap
    # nilai pre-diskon - lihat komentar 2026-07-19 di core.py). Akibatnya AI menyebutkan/
    # menjanjikan total yang LEBIH RENDAH ke tamu drpd yang benar-benar akan ditagih staf
    # nanti (utk kedatangan ke-10/diskon 100%, preview bahkan menunjukkan Rp0 total, padahal
    # service fee tetap harus dibayar) - dites nyata lewat simulator, selisih preview vs
    # charge sungguhan Rp2.025 di 1 skenario contoh. Diperbaiki: hitung dari
    # subtotal_sebelum_diskon, PERSIS sama seperti reservation_service.py.
    service_fee = round(subtotal_sebelum_diskon * SERVICE_FEE_PCT)
    total = subtotal + service_fee
    return {
        "tarif_kamar": subtotal_sebelum_diskon, "diskon_rp": diskon_rp,
        "subtotal_setelah_diskon": subtotal, "service_fee": service_fee,
        "service_fee_persen": int(SERVICE_FEE_PCT * 100), "total": total,
    }


async def _auto_reject_penuh(doc: Dict[str, Any]) -> None:
    """Day Use (atau Menginap di properti yang auto-approve, lihat _coba_auto_approve_menginap)
    yang BENAR-BENAR tidak ada kamar kosong (bukan gagal krn payment_option belum jelas atau
    >1 kamar) - langsung tolak otomatis & kabari tamu jujur SAAT ITU JUGA (dikonfirmasi user
    2026-07-19), JANGAN dibiarkan nyangkut "waiting_approval" menunggu staf sadar sendiri -
    staf pun tidak akan pernah bisa approve ini (create_reservation pasti gagal, memang tidak
    ada kamar). Konsisten dengan filosofi auto-approve end-to-end: hasil negatif pun harus
    otomatis & cepat, bukan cuma hasil positif."""
    now = now_iso()
    await db.booking_requests.update_one({"id": doc["id"]}, {"$set": {
        "status": "rejected", "rejected_by": "AI WhatsApp (otomatis)",
        "rejected_reason": "Kamar penuh - tidak ada kamar kosong pada tanggal & tipe yang diminta",
        "updated_at": now,
    }})
    label_tipe = "Menginap" if doc["tipe"] == "menginap" else "Day Use"
    pesan = (
        f"Mohon maaf {doc['nama_tamu']}, kamar {doc.get('room_tipe') or ''} untuk {label_tipe} "
        f"tanggal {doc['tanggal_checkin']} sedang penuh. Silakan coba tanggal lain atau tipe "
        f"kamar lain, kami siap bantu."
    )
    from routes.pesan_whatsapp import _kirim_dengan_alert
    nama_prop = await nama_properti(doc["property_id"])
    await _kirim_dengan_alert(
        doc["no_hp"], pesan, konteks=f"auto-tolak booking penuh {doc['id']}",
        template_name="menginap_ditolak_v1",
        template_params=[doc["nama_tamu"], nama_prop, doc["tanggal_checkin"]],
        property_id=doc["property_id"],
    )


async def _coba_auto_approve_day_use(doc: Dict[str, Any]) -> None:
    """Auto-approve + auto-kirim link bayar untuk booking Day Use yang tamu sudah sebutkan
    preferensi DP/Lunas-nya sendiri (dikonfirmasi user 2026-07-19: Day Use tidak perlu lagi
    ditinjau staf, langsung diproses berdasarkan ketersediaan kamar real-time - BEDA dari
    Menginap yang TETAP wajib direview staf manual, lihat catatan Business Rules di
    CLAUDE.md soal RedDoorz). Update `doc` di db.bookings_requests LANGSUNG kalau berhasil
    ATAU kalau benar-benar penuh (auto-reject, lihat `_auto_reject_penuh`); kalau tidak
    berlaku sama sekali (bukan day_use, belum ada payment_option, >1 kamar), diam-diam TIDAK
    melakukan apa pun - booking_request tetap "waiting_approval" seperti biasa, staf yang
    proses manual seperti sebelumnya. Tidak pernah melempar exception ke caller (auto-approve
    SELALU best-effort, kegagalannya tidak boleh menggagalkan pembuatan booking_request itu
    sendiri)."""
    try:
        if doc["tipe"] != "day_use" or doc["payment_option_diminta"] not in ("dp50", "full"):
            return
        if doc["jumlah_kamar"] != 1:
            return  # grup >1 kamar tetap lewat review staf (auto-pilih banyak kamar sekaligus lebih berisiko)

        from routes.public import public_availability
        # Bug nyata ditemukan 2026-08-02 (insiden langsung: tamu "Frisnanda Maulana" coba
        # booking Day Use berkali-kali ~30 menit, semua ditolak "kamar penuh" padahal
        # ai_bot_ketersediaan/check_availability tool AI - preview yang dilihat tamu -
        # SAMA PERSIS jam & tipe-nya menunjukkan banyak kamar tersedia): panggilan
        # public_availability ini TIDAK PERNAH menyertakan `jam_checkin`, padahal `doc`
        # sudah punya field itu (dipakai di bawah, baris berikutnya) - tanpa jam_checkin,
        # public_availability (utk HARI INI) jatuh ke gate konservatif lama "status kamar
        # == kosong SAAT INI" (lihat fix jam_checkin sebelumnya di routes/public.py) -
        # BEDA dari apa yang tamu lihat di preview (yang benar menyertakan jam_checkin).
        # Preview bilang "tersedia", tapi proses booking sungguhan pakai jalur INI dengan
        # gate yang berbeda - tamu berulang kali dapat "penuh" palsu padahal kamarnya ada.
        avail = await public_availability(
            doc["tanggal_checkin"], tipe=doc.get("room_tipe"), jam_checkin=doc.get("jam_checkin"),
            property_id_override=doc["property_id"],
        )
        if not avail["rooms"]:
            await _auto_reject_penuh(doc)
            return

        jam = doc.get("jam_checkin") or "14:00"
        start = datetime.fromisoformat(f"{doc['tanggal_checkin']}T{jam}:00+07:00").astimezone(timezone.utc)
        end = start + timedelta(hours=6)

        # `public_availability` cuma cek bentrok di granularitas TANGGAL (checkout day
        # dianggap kosong lagi), bukan jam presisi - room pertama di daftarnya BISA tetap
        # bentrok kalau booking lain (mis. Menginap OTA) checkout-nya lewat tengah hari yang
        # sama (insiden nyata 2026-07-22: RedDoorz checkout siang WIB tapi masih overlap
        # dengan slot Day Use jam 14:00-20:00). `create_reservation` yang validasi jam penuh
        # jadi sumber kebenaran akhir - coba semua kandidat kamar berurutan, bukan cuma yang
        # pertama, sebelum menyerah ke review staf manual (supaya Day Use tetap konsisten
        # auto-approve selama MASIH ADA kamar yang benar-benar kosong di jam itu).
        room = None
        booking = None
        last_conflict: Optional[Exception] = None
        for kandidat_room in avail["rooms"]:
            try:
                booking = await create_reservation({
                    "room_id": kandidat_room["id"], "nama_tamu": doc["nama_tamu"], "no_hp": doc["no_hp"],
                    "email": "", "no_identitas": "", "kendaraan": "",
                    "jumlah_tamu": doc.get("jumlah_tamu", 1),
                    "jam_mulai": start, "jam_selesai": end,
                    "catatan": doc.get("catatan") or "", "created_by": "AI WhatsApp (otomatis)",
                    "tipe": "day_use", "dengan_sarapan": False,
                }, doc["property_id"], source="whatsapp_auto", diskon_ai_persen=doc.get("diskon_ai_persen") or 0)
                room = kandidat_room
                break
            except HTTPException as e:
                if e.status_code == 400 and "sudah dibooking" in str(e.detail):
                    last_conflict = e
                    continue  # kamar ini bentrok jam presisi - coba kandidat berikutnya
                raise
        if booking is None:
            # Semua kandidat dari public_availability ternyata bentrok jam presisi -
            # kemungkinan besar memang penuh untuk slot ini, tapi biar aman (bukan
            # false-negative dari precheck kasar) diserahkan ke staf, bukan auto-reject.
            logging.getLogger("booking_requests").warning(
                f"Auto-approve day_use {doc.get('kode')}: semua {len(avail['rooms'])} kandidat "
                f"kamar bentrok jam presisi, fallback ke review staf. Konflik terakhir: {last_conflict}"
            )
            return

        try:
            from routes.tripay import tripay_create_transaction
            trx = await tripay_create_transaction(TripayCreateTransactionBody(
                booking_id=booking["id"], payment_option=doc["payment_option_diminta"],
                method=doc.get("metode_pembayaran_diminta") or AUTO_APPROVE_PAYMENT_METHOD,
            ))

            now = now_iso()
            await db.booking_requests.update_one({"id": doc["id"]}, {"$set": {
                "status": "waiting_payment", "booking_ids": [booking["id"]], "group_id": None,
                "approved_by": "AI WhatsApp (otomatis)", "approved_at": now, "updated_at": now,
                "checkout_url": trx.get("checkout_url"), "total": booking["total"],
            }})
            await log_availability_change(room["id"], room["tipe"], 0, "booking_auto_approve_ai", doc["property_id"], booking_id=booking["id"])

            pesan = (
                f"Halo {doc['nama_tamu']}, booking Day Use Anda *otomatis dikonfirmasi* berdasarkan "
                f"ketersediaan kamar saat ini!\n\n"
                f"Kamar: {room['nomor']} ({room['tipe']})\n"
                f"Total: Rp{int(booking['total']):,}".replace(",", ".") + "\n"
                f"Silakan selesaikan pembayaran melalui link berikut:\n{trx.get('checkout_url')}"
            )
            # Kirim SAAT ITU JUGA (same-turn dgn pesan tamu), selalu dalam jendela 24 jam -
            # tidak perlu template, tetap pakai wrapper alert supaya staf tahu kalau WAHA
            # down/gagal kirim (2026-07-26, lihat _kirim_dengan_alert).
            from routes.pesan_whatsapp import _kirim_dengan_alert
            await _kirim_dengan_alert(doc["no_hp"], pesan, konteks=f"auto-approve day use {doc['id']}", property_id=doc["property_id"])
        except Exception:
            # Bug nyata ditemukan & diperbaiki (2026-07-26): kalau Tripay gagal SETELAH
            # booking asli sudah terlanjur dibuat, booking itu sebelumnya dibiarkan
            # "yatim" (booking_pending, mengunci kamar, tidak pernah dibayar) - staf tidak
            # tahu itu ada karena booking_request tetap terlihat "waiting_approval" seperti
            # belum diproses sama sekali. Sekarang di-rollback (sama pola dengan
            # approve_booking_request manual) supaya kamar kembali bebas & staf yang proses
            # ulang manual tidak bentrok dengan booking hantu.
            await db.bookings.update_one({"id": booking["id"]}, {"$set": {
                "status": "cancelled", "cancelled_at": now_iso(),
                "cancelled_by": "system_rollback_auto_approve_gagal",
            }})
            await log_availability_change(
                room["id"], room["tipe"], 1, "booking_dibatalkan_rollback_auto_approve_gagal",
                doc["property_id"], booking_id=booking["id"],
            )
            raise
    except Exception as e:
        # Best-effort murni - kalau ADA yang gagal di tengah jalan (Tripay down, kamar
        # keburu terisi race condition, dst), booking_request tetap "waiting_approval",
        # staf tetap bisa proses manual seperti biasa. Tidak pernah bikin buat_booking_request
        # gagal gara-gara ini.
        logging.getLogger("booking_requests").warning(f"Auto-approve day_use {doc.get('kode')} gagal: {e}")


async def _coba_auto_approve_menginap(doc: Dict[str, Any]) -> None:
    """Auto-approve + auto-kirim link bayar untuk booking Menginap, SAMA seperti Day Use,
    TAPI HANYA untuk properti yang tidak butuh sinkron manual RedDoorz (dikonfirmasi user
    2026-07-26: properti "harmoni" tidak listing di RedDoorz sama sekali, jadi Menginap-nya
    bisa langsung diproses otomatis berdasarkan ketersediaan real-time, sama seperti Day
    Use). Properti yang MASIH butuh RedDoorz (mis. Pelangi Homestay) TETAP wajib direview
    manual staf seperti sebelumnya - fungsi ini diam-diam tidak melakukan apa pun untuk
    properti itu (lihat property_butuh_reddoorz di core.py). Sisanya sama persis dengan
    _coba_auto_approve_day_use: payment_option harus sudah disebutkan tamu, hanya 1 kamar,
    tarif pakai tarif_menginap x jumlah malam (sama seperti approve_booking_request manual),
    best-effort (gagal = fallback ke review staf manual, tidak pernah melempar exception ke
    caller)."""
    try:
        if doc["tipe"] != "menginap" or doc["payment_option_diminta"] not in ("dp50", "full"):
            return
        if doc["jumlah_kamar"] != 1:
            return  # grup >1 kamar tetap lewat review staf, sama seperti Day Use
        if not doc.get("tanggal_checkout"):
            return  # data belum lengkap - AI seharusnya selalu minta ini utk Menginap, jaga-jaga saja
        if await property_butuh_reddoorz(doc["property_id"]):
            return  # properti ini tetap wajib direview manual staf (RedDoorz)

        # jam_checkin custom (2026-08-02, sama pola dgn fix _coba_auto_approve_day_use) -
        # sebelumnya HARDCODE "14:00:00" apa pun jam yang tamu minta (create_booking AI
        # dulu memang tidak pernah kirim jam_checkin utk menginap sama sekali). Sekarang
        # pakai jam yang benar-benar diminta tamu kalau ada (mis. tamu Harmoni chat pagi
        # minta check-in Menginap jam 11 saat kamar masih dipakai Day Use tapi akan kosong
        # sebelum jam itu) - default tetap "14:00" (standar hotel) kalau tamu tidak minta
        # jam spesifik.
        jam_checkin = (doc.get("jam_checkin") or "14:00").strip()
        try:
            ci = datetime.fromisoformat(f"{doc['tanggal_checkin']}T{jam_checkin}:00+07:00")
            co = datetime.fromisoformat(f"{doc['tanggal_checkout']}T12:00:00+07:00")
        except Exception:
            return
        if co <= ci:
            return
        nights = max(1, (co.date() - ci.date()).days)

        from routes.public import public_availability
        avail = await public_availability(
            doc["tanggal_checkin"], tipe=doc.get("room_tipe"), checkout=doc["tanggal_checkout"],
            property_id_override=doc["property_id"], jam_checkin=doc.get("jam_checkin"),
        )

        if not avail["rooms"]:
            # Tidak ada kamar genuinely kosong SEKARANG. Kalau penuhnya HARI INI khusus karena
            # Day Use (dikonfirmasi user 2026-07-26) - jangan buru-buru tolak: kasih tahu tamu
            # perkiraan jam kamar siap SEKARANG, tandai booking_request ini untuk di-retry
            # otomatis begitu kamar itu BENAR-BENAR selesai dibersihkan (lihat
            # coba_retry_menginap_dayuse, dipanggil dari housekeeping_done di routes/rooms.py) -
            # `create_reservation` tetap menolak booking utk kamar yang status live-nya belum
            # "kosong" apa pun jam yang diminta (safety guard yang sudah lama ada, sengaja TIDAK
            # disentuh/dilewati di sini - andalkan status yang benar-benar diperbarui staf/sistem,
            # bukan perkiraan waktu). `estimasi_kamar_siap` SENGAJA cuma pernah menghitung ini utk
            # Day Use, tidak pernah utk Menginap yang sedang berlangsung (Menginap tidak checkout
            # hari itu) - konsisten dengan filosofi yang sama dipakai `rekomendasi_slot_kosong`.
            # Guard: request untuk tanggal yang SUDAH LEWAT (mis. dibuat larut malam utk
            # "hari ini", lalu di-retry setelah lewat tengah malam) - jangan diam-diam
            # dianggap "masih menunggu hari ini" selamanya, tidak masuk akal diproses lagi.
            today_local = datetime.now().strftime("%Y-%m-%d")
            if doc["tanggal_checkin"] < today_local:
                if doc.get("auto_retry_dayuse"):
                    await db.booking_requests.update_one({"id": doc["id"]}, {"$set": {"auto_retry_dayuse": False}})
                await _auto_reject_penuh(doc)
                return

            if doc["tanggal_checkin"] == today_local:
                from scheduling_engine import estimasi_kamar_siap, WIB
                q_tipe = {"tipe": doc["room_tipe"]} if doc.get("room_tipe") else {}
                rooms_tipe_sama = await db.rooms.find(scoped(q_tipe, doc["property_id"]), {"_id": 0}).to_list(200)
                estimasi_list = []
                for r in rooms_tipe_sama:
                    siap = await estimasi_kamar_siap(r["id"], doc["property_id"])
                    if siap:
                        estimasi_list.append(siap)
                if estimasi_list:
                    # Kirim pesan "kamar penuh, tunggu jam X" CUMA sekali (percobaan pertama) -
                    # retry berikutnya yang masih belum dapat kamar (mis. direbut booking lain
                    # yang menunggu duluan) TIDAK mengulang pesan yang sama supaya tamu tidak
                    # di-spam tiap kali kamar tipe ini ada yang selesai dibersihkan.
                    sudah_dikabari = bool(doc.get("auto_retry_dayuse"))
                    if not sudah_dikabari:
                        siap_paling_cepat = min(estimasi_list)
                        jam_str = siap_paling_cepat.astimezone(WIB).strftime("%H:%M")
                        pesan = (
                            f"Halo {doc['nama_tamu']}, untuk saat ini kamar {doc.get('room_tipe') or ''} "
                            f"sedang penuh karena masih dipakai tamu Day Use. Perkiraan kamar siap "
                            f"sekitar pukul {jam_str} WIB (setelah tamu checkout & dibersihkan) — "
                            f"begitu siap, booking Menginap Anda akan *otomatis diproses* dan link "
                            f"pembayaran dikirim ke nomor ini. Tidak perlu booking ulang."
                        )
                        # Kirim SAAT ITU JUGA (same-turn dgn permintaan tamu) - selalu
                        # dalam jendela 24 jam, tidak perlu template.
                        from routes.pesan_whatsapp import _kirim_dengan_alert
                        await _kirim_dengan_alert(doc["no_hp"], pesan, konteks=f"kamar penuh day-use, tunggu jam {jam_str} ({doc['id']})", property_id=doc["property_id"])
                    await db.booking_requests.update_one({"id": doc["id"]}, {"$set": {
                        "auto_retry_dayuse": True, "updated_at": now_iso(),
                    }})
                    return  # tetap "waiting_approval" - auto-retry akan diproses saat kamar siap

            await _auto_reject_penuh(doc)
            return

        end = co.astimezone(timezone.utc)
        start = ci.astimezone(timezone.utc)
        room = None
        booking = None
        last_conflict: Optional[Exception] = None
        # Sarapan (2026-08-07) - sama fix dgn _hitung_preview_harga, alur auto-approve
        # ini sebelumnya JUGA hardcode dengan_sarapan=False & tidak pernah tambah
        # BREAKFAST_PRICE walau tamu eksplisit minta.
        dengan_sarapan_req = bool(doc.get("dengan_sarapan")) and await property_ada_sarapan(doc["property_id"])
        for kandidat_room in avail["rooms"]:
            tarif_per_malam = int(kandidat_room["tarif_menginap"]) + (BREAKFAST_PRICE if dengan_sarapan_req else 0)
            subtotal = tarif_per_malam * nights
            service_fee = round(subtotal * SERVICE_FEE_PCT)
            total = subtotal + service_fee
            harga_override = {"subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": round(total * 0.5)}
            try:
                booking = await create_reservation({
                    "room_id": kandidat_room["id"], "nama_tamu": doc["nama_tamu"], "no_hp": doc["no_hp"],
                    "email": "", "no_identitas": "", "kendaraan": "",
                    "jumlah_tamu": doc.get("jumlah_tamu", 1),
                    "jam_mulai": start, "jam_selesai": end,
                    "catatan": doc.get("catatan") or "", "created_by": "AI WhatsApp (otomatis)",
                    "tipe": "menginap", "dengan_sarapan": dengan_sarapan_req,
                }, doc["property_id"], source="whatsapp_auto", harga_override=harga_override,
                   diskon_ai_persen=doc.get("diskon_ai_persen") or 0)
                room = kandidat_room
                break
            except HTTPException as e:
                if e.status_code == 400 and "sudah dibooking" in str(e.detail):
                    last_conflict = e
                    continue  # kamar ini bentrok - coba kandidat berikutnya
                raise
        if booking is None:
            logging.getLogger("booking_requests").warning(
                f"Auto-approve menginap {doc.get('kode')}: semua {len(avail['rooms'])} kandidat "
                f"kamar bentrok, fallback ke review staf. Konflik terakhir: {last_conflict}"
            )
            return

        # Properti ini tidak butuh RedDoorz (sudah dicek di atas) - langsung "not_required",
        # BEDA dari approve_booking_request manual yang selalu set "waiting_reddoorz_input"
        # untuk tipe menginap (properti lain yang masih butuh RedDoorz).
        await db.bookings.update_one({"id": booking["id"]}, {"$set": {"sync_status": "not_required"}})
        booking["sync_status"] = "not_required"

        try:
            from routes.tripay import tripay_create_transaction
            trx = await tripay_create_transaction(TripayCreateTransactionBody(
                booking_id=booking["id"], payment_option=doc["payment_option_diminta"],
                method=doc.get("metode_pembayaran_diminta") or AUTO_APPROVE_PAYMENT_METHOD,
            ))

            now = now_iso()
            await db.booking_requests.update_one({"id": doc["id"]}, {"$set": {
                "status": "waiting_payment", "booking_ids": [booking["id"]], "group_id": None,
                "approved_by": "AI WhatsApp (otomatis)", "approved_at": now, "updated_at": now,
                "checkout_url": trx.get("checkout_url"), "total": booking["total"],
            }})
            await log_availability_change(room["id"], room["tipe"], 0, "booking_auto_approve_ai", doc["property_id"], booking_id=booking["id"])

            # Kalau ini hasil auto-retry (sebelumnya sempat dikasih tahu "kamar penuh karena
            # Day Use, tunggu sampai jam segini") - tegaskan kamarnya sekarang benar-benar
            # siap, supaya tamu tidak bingung kenapa tiba-tiba dapat konfirmasi.
            intro = (
                "Kabar baik! Kamar sudah siap - booking Menginap Anda *otomatis dikonfirmasi*!"
                if doc.get("auto_retry_dayuse")
                else "booking Menginap Anda *otomatis dikonfirmasi* berdasarkan ketersediaan kamar saat ini!"
            )
            pesan = (
                f"Halo {doc['nama_tamu']}, {intro}\n\n"
                f"Kamar: {room['nomor']} ({room['tipe']})\n"
                f"Check-in: {doc['tanggal_checkin']} — Check-out: {doc['tanggal_checkout']} ({nights} malam)\n"
                f"Total: Rp{int(booking['total']):,}".replace(",", ".") + "\n"
                f"Silakan selesaikan pembayaran melalui link berikut:\n{trx.get('checkout_url')}"
            )
            # Kalau ini hasil retry setelah housekeeping (auto_retry_dayuse) - bisa terjadi
            # BERJAM-JAM setelah pesan terakhir tamu, jadi mungkin sudah di luar jendela 24
            # jam Meta (2026-07-26) - WAJIB sertakan template, `_kirim_dengan_alert` yang
            # menentukan pakai teks bebas atau template lewat relay ai-chat-bot.
            from routes.pesan_whatsapp import _kirim_dengan_alert
            nama_prop = await nama_properti(doc["property_id"])
            total_str = f"{int(booking['total']):,}".replace(",", ".")
            tanggal_str = f"{doc['tanggal_checkin']} - {doc['tanggal_checkout']}"
            await _kirim_dengan_alert(
                doc["no_hp"], pesan, konteks=f"auto-approve menginap {doc['id']}",
                template_name="menginap_disetujui_v1",
                template_params=[doc["nama_tamu"], nama_prop, tanggal_str, total_str, trx.get("checkout_url") or ""],
                property_id=doc["property_id"],
            )
        except Exception:
            # Sama seperti _coba_auto_approve_day_use (bug nyata ditemukan & diperbaiki
            # 2026-07-26) - kalau Tripay gagal SETELAH booking asli sudah dibuat, rollback
            # supaya tidak ada booking "yatim" yang mengunci kamar tanpa pembayaran.
            await db.bookings.update_one({"id": booking["id"]}, {"$set": {
                "status": "cancelled", "cancelled_at": now_iso(),
                "cancelled_by": "system_rollback_auto_approve_gagal",
            }})
            await log_availability_change(
                room["id"], room["tipe"], 1, "booking_dibatalkan_rollback_auto_approve_gagal",
                doc["property_id"], booking_id=booking["id"],
            )
            raise
    except Exception as e:
        logging.getLogger("booking_requests").warning(f"Auto-approve menginap {doc.get('kode')} gagal: {e}")


async def coba_retry_menginap_dayuse(property_id: str, room_tipe: str) -> None:
    """Dipanggil dari routes/rooms.py's housekeeping_done() (2026-07-26) - tepat setelah
    sebuah kamar Day Use SELESAI dibersihkan & statusnya benar-benar jadi "kosong" lagi
    (bukan cuma perkiraan waktu - itu sebabnya retry di-trigger DI SINI, bukan di titik
    checkout atau dari perkiraan `estimasi_kamar_siap` semata, supaya tidak melanggar guard
    keamanan create_reservation yang menolak booking hari ini untuk kamar yang status
    live-nya belum "kosong"). Cari booking_request Menginap yang sempat ditandai
    `auto_retry_dayuse` (dibuat saat kamar tipe ini penuh karena Day Use, lihat
    _coba_auto_approve_menginap) untuk properti & tipe kamar yang sama, proses FIFO (yang
    paling lama nunggu duluan) - tiap retry berhenti sendiri kalau memang tidak ada lagi
    kamar kosong (mis. 2 booking_request menunggu tapi cuma 1 kamar yang baru siap).
    Best-effort murni, tidak pernah melempar exception ke pemanggil (housekeeping_done tidak
    boleh gagal gara-gara ini)."""
    try:
        pending = await db.booking_requests.find(scoped({
            "status": "waiting_approval", "tipe": "menginap", "auto_retry_dayuse": True,
            "room_tipe": {"$in": [room_tipe, None]},
        }, property_id), {"_id": 0}).sort("created_at", 1).to_list(50)
        for doc in pending:
            # Lock + re-fetch SETELAH dapat lock (2026-07-26, audit keamanan lanjutan) - kalau
            # 2 kamar tipe sama kebetulan selesai dibersihkan nyaris bersamaan, 2 pemanggilan
            # coba_retry_menginap_dayuse bisa sama-sama menemukan booking_request yang SAMA
            # dari query di atas sebelum salah satu sempat selesai memprosesnya - tanpa lock
            # ini, keduanya bisa sama-sama lolos & membuat 2 booking asli dari 1 permintaan
            # tamu (sama kelas bug dengan yang sudah dijaga di approve_booking_request manual).
            async with _request_lock(doc["id"]):
                fresh = await db.booking_requests.find_one({"id": doc["id"]}, {"_id": 0})
                if not fresh or fresh["status"] != "waiting_approval":
                    continue  # sudah diproses duluan oleh panggilan lain / staf manual
                await _coba_auto_approve_menginap(fresh)
    except Exception as e:
        logging.getLogger("booking_requests").warning(f"Retry auto-approve menginap (dayuse) gagal: {e}")


async def _hitung_diskon_gabungan(data: Dict[str, Any], property_id: str):
    """Diskon member (Program Loyalitas Kedatangan) digabung dengan diskon diskresi AI
    (2026-07-21, kebijakan bisnis user - HANYA dihitung kalau AI menandai tamu SENDIRI
    minta diskon via diskon_diminta_tamu, persentasenya SELALU dihitung server dari data
    booking sungguhan via hitung_diskon_ai_diskresi, bukan dari angka yang AI kirim) pakai
    MAX (bukan dijumlah). Diekstrak dari buat_booking_request (sebelumnya cuma dipanggil di
    situ) supaya bisa dipakai juga oleh endpoint preview read-only (preview_harga_booking) -
    SATU-SATUNYA sumber kebenaran hitungan harga sebelum booking_request sungguhan dibuat."""
    diskon_info = await hitung_diskon_member(property_id, data["no_hp"])
    diskon_ai_persen = 0
    if data.get("diskon_diminta_tamu"):
        diskon_ai_persen = hitung_diskon_ai_diskresi(_hitung_malam(data), int(data.get("jumlah_kamar") or 1))
    diskon_persen_efektif = max(diskon_info["diskon_persen"], diskon_ai_persen)
    preview_harga = await _hitung_preview_harga(data, diskon_persen_efektif, property_id)
    return diskon_info, diskon_ai_persen, diskon_persen_efektif, preview_harga


async def buat_booking_request(data: Dict[str, Any], property_id: Optional[str] = None) -> Dict[str, Any]:
    """Dipanggil dari alur pengumpulan data AI WhatsApp (pesan_whatsapp.py) setelah field
    wajib lengkap & tamu konfirmasi — sengaja BUKAN endpoint HTTP publik (tidak menambah
    permukaan serangan baru untuk membuat data). `data` wajib berisi: nama_tamu, no_hp,
    tipe (day_use|menginap), room_tipe, tanggal_checkin, dan (KHUSUS day_use, 2026-07-26)
    jam_checkin - lihat guard di bawah; boleh berisi jumlah_kamar, jumlah_tamu,
    tanggal_checkout (menginap), catatan, payment_option (dp50|full — preferensi tamu
    KALAU disebutkan sendiri di chat, lihat BOOKING_FLOW_SYSTEM_PROMPT; None kalau belum
    disebut — staf yang putuskan saat approve).

    `property_id` (2026-07-25, Fase 4) - diisi pemanggil yang sudah tahu propertinya
    sendiri (ai_bot_buat_booking_request, resolve dari API key ai-chat-bot). Kalau None
    (belum ada pemanggil lain yang kasih ini), fallback ke get_default_property_id()
    stopgap - jaga kompatibilitas kalau ada pemanggil lama."""
    payment_option = data.get("payment_option")

    # Guard nama & no_hp wajib (2026-07-26, permintaan user - berlaku SEMUA tenant, sama
    # pola dengan guard jam_checkin di bawah). Sebelumnya `data["no_hp"]`/`data["nama_tamu"]`
    # diakses langsung tanpa validasi - kalau kosong/hilang, KeyError mentah (bukan pesan
    # jelas yang bisa dipahami AI utk bertanya ulang) ATAU (kalau modelnya str kosong lolos
    # Pydantic) booking_request tersimpan tanpa kontak yang valid - staf tidak bisa hubungi
    # tamu sama sekali kalau approve/tolak perlu konfirmasi lebih lanjut. no_hp juga dicek
    # minimal harus mayoritas digit (bukan validasi format ketat - importir bisa beda-beda,
    # cukup tolak yang jelas-jelas bukan nomor sama sekali, mis. kosong/nama tertukar).
    nama_tamu_bersih = (data.get("nama_tamu") or "").strip()
    # Wajib nama ASLI, bukan cuma non-kosong (2026-08-01, bug nyata ditemukan: AI pernah
    # sama sekali tidak menanyakan nama tamu di sepanjang percakapan, lalu mengisi
    # guest_name dengan EMOJI sebagai pengisi kosong - booking tersimpan tanpa nama tamu
    # yang bisa dibaca staf). Minimal 2 huruf ASLI (unicode letter, dukung nama non-Latin)
    # - cukup untuk menolak emoji/simbol/angka semata tanpa validasi format nama yang kaku.
    if len(nama_tamu_bersih) < 2 or sum(c.isalpha() for c in nama_tamu_bersih) < 2:
        raise HTTPException(
            400,
            "Nama tamu belum valid (kosong/bukan nama asli, mis. emoji/simbol) - WAJIB tanya "
            "nama lengkap tamu sungguhan sebelum lanjut booking, jangan isi dengan placeholder apapun.",
        )
    no_hp_bersih = (data.get("no_hp") or "").strip()
    if not no_hp_bersih or sum(c.isdigit() for c in no_hp_bersih) < 8:
        raise HTTPException(
            400,
            "Nomor WhatsApp tamu wajib diisi & valid - konfirmasi ulang nomor WhatsApp tamu "
            "(bukan cuma nama) sebelum lanjut booking, supaya staf bisa menghubungi kalau perlu.",
        )

    # Guard tanggal masa lalu (2026-07-19, audit reliabilitas AI booking flow) - AI WhatsApp
    # sekarang selalu diberi tanggal hari ini di prompt-nya (lihat build_dynamic_prompt di
    # ai-chat-bot), tapi tetap divalidasi keras di sini sebagai lapis pertahanan kedua kalau
    # model salah ekstrak tanggal (mis. tamu bilang "kemarin" bercanda, atau typo tahun) -
    # jangan sampai booking_request nyangkut untuk tanggal yang sudah lewat, staf pasti bingung.
    try:
        tanggal_checkin_date = datetime.fromisoformat(data["tanggal_checkin"]).date()
    except (ValueError, TypeError):
        raise HTTPException(400, "Format tanggal_checkin tidak valid (harus YYYY-MM-DD)")
    if tanggal_checkin_date < datetime.now().date():
        raise HTTPException(400, "Tanggal check-in tidak boleh di masa lalu - tanya ulang tanggal yang benar ke tamu")

    # Guard jam_checkin wajib untuk Day Use (2026-07-26, permintaan user - berlaku SEMUA
    # tenant karena divalidasi di sini, satu-satunya titik masuk booking_request AI, bukan
    # per-prompt/per-bot). Sebelumnya jam_checkin opsional & diam-diam default ke "14:00"
    # kalau tamu tidak sebutkan (lihat _coba_auto_approve_day_use/approve_booking_request) -
    # bahaya nyata: kamar yang masih ditempati tamu Menginap sampai checkout jam 12 siang
    # bisa salah dicek pakai asumsi 14:00 (aman) padahal tamu Day Use yang sebenarnya
    # datang jam 09:00-10:00 (masih bentrok). Dengan jam kedatangan ASLI selalu terisi,
    # check_room_available (hard validator, dipanggil lewat create_reservation) akan
    # membandingkan jam BENAR tamu terhadap jam checkout Menginap yang keluar - kalau
    # bentrok, kandidat kamar itu otomatis dilewati (coba kamar lain / fallback ke staf),
    # bukan diam-diam dianggap aman gara-gara asumsi jam yang salah.
    if data.get("tipe") == "day_use" and not (data.get("jam_checkin") or "").strip():
        raise HTTPException(
            400,
            "Jam kedatangan wajib diisi untuk Day Use - tanya tamu jam berapa rencana "
            "datang (format HH:MM, contoh 10:00) sebelum lanjut booking.",
        )

    # Guard tanggal_checkout wajib untuk Menginap (2026-08-07, bug nyata - tamu Lugra
    # Agusta bilang "menginap 1 malam" tanpa sebut tanggal checkout eksplisit, AI tidak
    # pernah menghitung/mengisi tanggal_checkout sendiri, booking_request tersimpan dengan
    # tanggal_checkout None - baru ketahuan pas STAF klik Terima ("Permintaan ini tidak
    # punya tanggal_checkout — tidak bisa diproses sebagai menginap" di
    # _proses_kamar_dan_kirim_link), padahal tamu sudah dikasih tahu "booking berhasil
    # diajukan". Sama pola dengan guard jam_checkin di atas - tolak SEKARANG di titik
    # masuk satu-satunya booking_request AI, supaya AI dapat error jelas & tahu harus
    # tanya/hitung ulang tanggal checkout SEBELUM mengaku sukses ke tamu, bukan nyangkut
    # diam-diam sampai staf approve.
    if data.get("tipe") == "menginap":
        try:
            tanggal_checkout_date = datetime.fromisoformat(data.get("tanggal_checkout") or "").date()
        except (ValueError, TypeError):
            raise HTTPException(
                400,
                "Tanggal checkout wajib diisi & valid untuk Menginap - kalau tamu cuma "
                "sebutkan jumlah malam (mis. \"1 malam\"), hitung sendiri tanggal checkout "
                "= tanggal checkin + jumlah malam, jangan dibiarkan kosong.",
            )
        if tanggal_checkout_date <= tanggal_checkin_date:
            raise HTTPException(400, "Tanggal checkout harus setelah tanggal checkin - cek ulang perhitungannya")

    property_id = property_id or await get_default_property_id()
    diskon_info, diskon_ai_persen, diskon_persen_efektif, preview_harga = await _hitung_diskon_gabungan(data, property_id)

    doc = {
        "id": str(uuid.uuid4()), "kode": _kode_request(),
        "property_id": property_id,
        "nama_tamu": data["nama_tamu"], "no_hp": data["no_hp"],
        "tipe": data["tipe"], "room_tipe": data.get("room_tipe"),
        "jumlah_kamar": int(data.get("jumlah_kamar") or 1),
        "jumlah_tamu": int(data.get("jumlah_tamu") or 1),
        "tanggal_checkin": data["tanggal_checkin"], "jam_checkin": data.get("jam_checkin"),
        "tanggal_checkout": data.get("tanggal_checkout"), "catatan": data.get("catatan") or "",
        "dengan_sarapan": bool(data.get("dengan_sarapan")) if data.get("tipe") == "menginap" else False,
        "payment_option_diminta": payment_option if payment_option in ("dp50", "full") else None,
        "metode_pembayaran_diminta": (
            data.get("metode_pembayaran") if data.get("metode_pembayaran") in TRIPAY_METODE_VALID else None
        ),
        "preview_kedatangan_ke": diskon_info["kedatangan_ke"], "preview_diskon_persen": diskon_persen_efektif,
        "preview_diskon_member_persen": diskon_info["diskon_persen"], "diskon_ai_persen": diskon_ai_persen,
        "preview_harga": preview_harga,
        "status": "waiting_approval", "source": "whatsapp",
        "booking_ids": [], "group_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.booking_requests.insert_one(doc)

    from routes.push import send_push
    from routes.telegram_bot import kirim_alert_owner

    # Day Use dengan payment_option jelas: coba auto-approve + auto-kirim link bayar
    # langsung (dikonfirmasi user 2026-07-19), TIDAK perlu menunggu staf klik Terima di
    # PMS. Menginap SAMA-SAMA bisa auto-approve (2026-07-26) TAPI HANYA di properti yang
    # tidak butuh sinkron manual RedDoorz (mis. harmoni) - properti yang masih butuh
    # RedDoorz (mis. Pelangi Homestay) tetap wajib direview manual staf seperti biasa.
    # Best-effort, diam-diam tidak melakukan apa pun kalau gagal/tidak berlaku (lihat
    # docstring masing-masing fungsi) - salah satu dari 2 fungsi ini selalu no-op karena
    # tipe booking cuma bisa salah satu (day_use ATAU menginap).
    await _coba_auto_approve_day_use(doc)
    await _coba_auto_approve_menginap(doc)
    doc = await db.booking_requests.find_one({"id": doc["id"]}, {"_id": 0}) or doc

    ringkas = (
        f"{doc['nama_tamu']} — {doc['tipe']} {doc['room_tipe'] or ''} x{doc['jumlah_kamar']}, "
        f"{doc['tanggal_checkin']}"
    )
    if doc["status"] == "waiting_payment":
        # Auto-approved - FYI ke owner, BUKAN alert "perlu ditinjau" (tidak ada aksi yang
        # perlu staf lakukan, link bayar sudah otomatis terkirim ke tamu).
        await kirim_alert_owner(
            f"✅ Booking Day Use OTOMATIS terkonfirmasi ({doc['kode']})\n\n"
            f"Nama: {doc['nama_tamu']}\nHP: {doc['no_hp']}\n"
            f"Tipe: {doc['tipe']} — {doc['room_tipe'] or '-'}, {doc['tanggal_checkin']}"
            + (f" {doc['jam_checkin']}" if doc.get("jam_checkin") else "") +
            f"\nTotal: Rp{int(doc.get('total') or 0):,}".replace(",", ".") +
            "\n\nLink pembayaran sudah otomatis terkirim ke tamu - tidak perlu tindakan."
        )
    elif doc["status"] == "rejected":
        # Auto-reject karena benar-benar penuh - FYI juga (bukan "perlu ditinjau", tamu
        # sudah otomatis dikabari penuh, tidak ada aksi staf yang perlu diambil).
        await kirim_alert_owner(
            f"❌ Booking Day Use OTOMATIS ditolak - kamar penuh ({doc['kode']})\n\n"
            f"Nama: {doc['nama_tamu']}\nHP: {doc['no_hp']}\n"
            f"Tipe: {doc['tipe']} — {doc['room_tipe'] or '-'}, {doc['tanggal_checkin']}"
            + (f" {doc['jam_checkin']}" if doc.get("jam_checkin") else "") +
            "\n\nTamu sudah otomatis dikabari kamar penuh - tidak perlu tindakan."
        )
    else:
        await send_push("Permintaan Booking Baru", ringkas, url="/booking-requests")
        await kirim_alert_owner(
            f"📩 Permintaan Booking Baru ({doc['kode']})\n\n"
            f"Nama: {doc['nama_tamu']}\nHP: {doc['no_hp']}\n"
            f"Tipe: {doc['tipe']} — {doc['room_tipe'] or '(belum tentu)'} x{doc['jumlah_kamar']}, "
            f"{doc['jumlah_tamu']} tamu\n"
            f"Check-in: {doc['tanggal_checkin']}" + (f" {doc['jam_checkin']}" if doc.get("jam_checkin") else "") +
            (f"\nCheck-out: {doc['tanggal_checkout']}" if doc.get("tanggal_checkout") else "") +
            (f"\nTamu minta: {'DP 50%' if doc['payment_option_diminta'] == 'dp50' else 'Bayar Penuh'}" if doc.get("payment_option_diminta") else "") +
            (f"\nKedatangan ke-{diskon_info['kedatangan_ke']}, diskon member {diskon_info['diskon_persen']}%" if diskon_info["diskon_persen"] else "") +
            "\n\nTinjau di PMS → Booking Request."
        )
    return doc


def _hitung_status_efektif(raw_status: str, bks: list) -> str:
    """Derive status virtual (lunas/kadaluarsa) dari payment_status booking sungguhan yang
    terkait - diekstrak dari list_booking_requests() (2026-08-04) supaya resend_payment_link
    di bawah bisa pakai logika PERSIS SAMA untuk memutuskan boleh/tidaknya kirim ulang link,
    bukan menghitung ulang terpisah (sumber kebenaran tunggal, sama pola dgn _fetch_site_facts
    di AI Blog)."""
    if raw_status == "waiting_payment" and bks:
        if all(b.get("payment_status") == "paid" for b in bks):
            return "lunas"
        if all(b.get("payment_status") in ("expired", "failed") for b in bks):
            return "kadaluarsa"
    return raw_status


async def _proses_kamar_dan_kirim_link(req: dict, room_ids: list, payment_option: str, method: str,
                                        user: dict, property_id: str, pesan_pembuka: str,
                                        log_action: str, log_desc: str) -> dict:
    """Inti pembuatan booking sungguhan + transaksi Tripay + kirim link WA - dipakai
    approve_booking_request (permintaan baru, status waiting_approval) DAN
    resend_payment_link (link lama sudah kadaluarsa, status TETAP waiting_payment) supaya
    tidak ada 2 jalur pembayaran paralel yang beda logika (diekstrak 2026-08-04 dari
    approve_booking_request yang sebelumnya berdiri sendiri). `pesan_pembuka` beda kalimat
    di pesan WA supaya tamu tidak bingung antara "permintaan disetujui" vs "ini link baru
    menggantikan link lama yang sudah mati"."""
    if len(room_ids) != req.get("jumlah_kamar", 1):
        raise HTTPException(400, f"Pilih tepat {req.get('jumlah_kamar', 1)} kamar sesuai permintaan")

    tipe = req["tipe"]
    if tipe == "menginap":
        if not req.get("tanggal_checkout"):
            raise HTTPException(400, "Permintaan ini tidak punya tanggal_checkout — tidak bisa diproses sebagai menginap")
        try:
            ci = datetime.fromisoformat(f"{req['tanggal_checkin']}T14:00:00+07:00")
            co = datetime.fromisoformat(f"{req['tanggal_checkout']}T12:00:00+07:00")
        except Exception:
            raise HTTPException(400, "Tanggal check-in/checkout pada permintaan tidak valid")
        if co <= ci:
            raise HTTPException(400, "Tanggal check-out harus setelah check-in")
        start, end = ci.astimezone(timezone.utc), co.astimezone(timezone.utc)
        nights = max(1, (co.date() - ci.date()).days)
    else:
        try:
            jam = req.get("jam_checkin") or "14:00"
            start = datetime.fromisoformat(f"{req['tanggal_checkin']}T{jam}:00+07:00").astimezone(timezone.utc)
        except Exception:
            raise HTTPException(400, "Tanggal/jam check-in pada permintaan tidak valid")
        end = start + timedelta(hours=6)
        nights = 1

    # Sarapan (2026-08-07) - sama fix dgn _hitung_preview_harga/_coba_auto_approve_menginap,
    # jalur approve MANUAL staf ini JUGA hardcode dengan_sarapan=False & tidak pernah
    # tambah BREAKFAST_PRICE walau tamu eksplisit minta - akar masalah nyata tamu Riyan
    # Sumardika kena tarif tanpa sarapan padahal minta dengan sarapan.
    dengan_sarapan_req = tipe == "menginap" and bool(req.get("dengan_sarapan")) and await property_ada_sarapan(property_id)

    created_bookings = []
    try:
        for room_id in room_ids:
            r = await db.rooms.find_one(scoped({"id": room_id}, property_id))
            if not r:
                raise HTTPException(404, f"Kamar tidak ditemukan (id {room_id})")
            harga_override = None
            if tipe == "menginap":
                tarif_per_malam = int(r["tarif_menginap"]) + (BREAKFAST_PRICE if dengan_sarapan_req else 0)
                subtotal = tarif_per_malam * nights
                service_fee = round(subtotal * SERVICE_FEE_PCT)
                total = subtotal + service_fee
                harga_override = {"subtotal": subtotal, "service_fee": service_fee, "total": total, "dp_min": round(total * 0.5)}
            data = {
                "room_id": room_id, "nama_tamu": req["nama_tamu"], "no_hp": req["no_hp"],
                "email": "", "no_identitas": "", "kendaraan": "",
                "jumlah_tamu": req.get("jumlah_tamu", 1),
                "jam_mulai": start, "jam_selesai": end,
                "catatan": req.get("catatan") or "", "created_by": user["nama"],
                "tipe": tipe, "dengan_sarapan": dengan_sarapan_req,
            }
            booking = await create_reservation(data, property_id, source="whatsapp_request", harga_override=harga_override)
            sync_status = "waiting_reddoorz_input" if (tipe == "menginap" and await property_butuh_reddoorz(property_id)) else "not_required"
            await db.bookings.update_one({"id": booking["id"]}, {"$set": {"sync_status": sync_status}})
            booking["sync_status"] = sync_status
            created_bookings.append(booking)

        group_id = None
        if len(created_bookings) > 1:
            group_id = str(uuid.uuid4())
            for b in created_bookings:
                await db.bookings.update_one({"id": b["id"]}, {"$set": {"group_id": group_id}})

        total_group = sum(int(b["total"]) for b in created_bookings)

        from routes.tripay import tripay_create_transaction
        trx = await tripay_create_transaction(TripayCreateTransactionBody(
            booking_id=created_bookings[0]["id"], payment_option=payment_option, method=method,
        ))

        now = now_iso()
        # Simpan booking_ids/checkout_url LAMA ke riwayat_link sebelum ditimpa (2026-08-04,
        # permintaan Agus - fitur kirim ulang) - supaya kalau nanti perlu ditelusuri, jelas
        # link mana yang sudah mati vs yang aktif, bukan hilang begitu saja.
        riwayat_baru = {
            "booking_ids": req.get("booking_ids") or [], "checkout_url": req.get("checkout_url"),
            "total": req.get("total"), "diganti_at": now, "diganti_oleh": user["nama"],
        } if req.get("checkout_url") else None
        update_set = {
            "status": "waiting_payment", "booking_ids": [b["id"] for b in created_bookings], "group_id": group_id,
            "approved_by": user["nama"], "approved_at": now, "updated_at": now,
            "checkout_url": trx.get("checkout_url"), "total": total_group,
        }
        update_ops = {"$set": update_set}
        if riwayat_baru:
            update_ops["$push"] = {"riwayat_link": riwayat_baru}
        await db.booking_requests.update_one({"id": req["id"]}, update_ops)
        await log_activity(user, log_action, f"{log_desc} {req['kode']} ({req['nama_tamu']})")

        pesan = (
            f"{pesan_pembuka}\n\n"
            f"Total: Rp{total_group:,}".replace(",", ".") + "\n"
            f"Silakan selesaikan pembayaran melalui link berikut:\n{trx.get('checkout_url')}"
        )
        try:
            from routes.pesan_whatsapp import _kirim_dengan_alert
            nama_prop = await nama_properti(property_id)
            total_str = f"{total_group:,}".replace(",", ".")
            tanggal_str = f"{req.get('tanggal_checkin', '')} - {req.get('tanggal_checkout') or req.get('tanggal_checkin', '')}"
            await _kirim_dengan_alert(
                req["no_hp"], pesan, konteks=f"{log_action} {req['id']}",
                template_name="menginap_disetujui_v1",
                template_params=[req["nama_tamu"], nama_prop, tanggal_str, total_str, trx.get("checkout_url") or ""],
                property_id=property_id,
            )
        except Exception as e:
            logging.getLogger("booking_requests").warning(f"Gagal kirim link bayar ke {req['no_hp']}: {e}")
    except Exception:
        for b in created_bookings:
            await db.bookings.update_one({"id": b["id"]}, {"$set": {
                "status": "cancelled", "cancelled_at": now_iso(),
                "cancelled_by": "system_rollback_approve_gagal",
            }})
            await log_availability_change(
                b["room_id"], b.get("room_tipe", ""), 1, "booking_dibatalkan_rollback_approve_gagal",
                b.get("property_id"), booking_id=b["id"],
            )
        raise

    return await db.booking_requests.find_one(scoped({"id": req["id"]}, property_id), {"_id": 0})


@api.get("/booking-requests")
async def list_booking_requests(status: Optional[str] = None, user: dict = Depends(get_current_user),
                                 property_id: str = Depends(get_active_property)):
    """`status` mentah cuma tahu 3 nilai (waiting_approval/waiting_payment/rejected) —
    begitu di-approve, status TIDAK PERNAH otomatis lanjut lagi biar pun tamu sudah bayar
    (lihat approve_booking_request: satu-satunya penulis field ini). Supaya staf bisa lihat
    riwayat permintaan yang SUDAH benar-benar selesai (lunas), tiap item di sini diperkaya
    `status_efektif` (menambah nilai virtual "lunas") + `booking_ringkasan` (status booking
    sungguhan yang terkait) dengan mengecek payment_status booking yang sudah dibuat saat
    approve. `status=lunas` di query jadi filter virtual tambahan (bukan field asli)."""
    raw_status = status if status in ("waiting_approval", "waiting_payment", "rejected") else None
    q: Dict[str, Any] = {}
    if raw_status:
        q["status"] = raw_status
    elif status == "lunas":
        q["status"] = "waiting_payment"
    items = await db.booking_requests.find(scoped(q, property_id), {"_id": 0}).sort("created_at", -1).to_list(500)

    # Satu query $in dibatch di luar loop (2026-07-28, audit performa) - sebelumnya tiap
    # item dengan booking_ids query db.bookings sendiri-sendiri (N+1, sampai 500 query
    # terpisah kalau daftar penuh). Semua booking diambil sekali lalu di-lookup per id
    # lewat dict, hasilnya identik dengan query per-item sebelumnya.
    all_booking_ids = list({bid for it in items for bid in it.get("booking_ids") or []})
    bookings_by_id: Dict[str, dict] = {}
    if all_booking_ids:
        all_bks = await db.bookings.find(scoped({"id": {"$in": all_booking_ids}}, property_id), {"_id": 0}).to_list(len(all_booking_ids))
        bookings_by_id = {b["id"]: b for b in all_bks}

    for it in items:
        it["status_efektif"] = it["status"]
        it["booking_ringkasan"] = None
        if it.get("booking_ids"):
            bks = [bookings_by_id[bid] for bid in it["booking_ids"] if bid in bookings_by_id]
            if bks:
                it["booking_ringkasan"] = [{
                    "kode": b["kode"], "room_nomor": b.get("room_nomor"), "room_tipe": b.get("room_tipe"),
                    "status": b.get("status"), "payment_status": b.get("payment_status"),
                    "sync_status": b.get("sync_status"), "total": b.get("total"),
                    "payment_option": b.get("payment_option"),
                    **status_bayar_booking(b),  # status_bayar, jumlah_dibayar, sisa_tagihan
                } for b in bks]
                it["status_efektif"] = _hitung_status_efektif(it["status"], bks)

    if status == "lunas":
        items = [it for it in items if it["status_efektif"] == "lunas"]
    elif status == "waiting_payment":
        items = [it for it in items if it["status_efektif"] == "waiting_payment"]
    return items


@api.get("/booking-requests/{rid}")
async def get_booking_request(rid: str, user: dict = Depends(get_current_user),
                               property_id: str = Depends(get_active_property)):
    r = await db.booking_requests.find_one(scoped({"id": rid}, property_id), {"_id": 0})
    if not r:
        raise HTTPException(404, "Permintaan booking tidak ditemukan")
    return r


@api.post("/booking-requests/{rid}/approve")
async def approve_booking_request(rid: str, body: BookingRequestApprove, user: dict = Depends(get_current_user),
                                   property_id: str = Depends(get_active_property)):
    """Setujui permintaan: staf sudah mengecek ketersediaan (termasuk RedDoorz, manual di
    luar sistem) & memilih kamar spesifik. Membuat booking SUNGGUHAN (status booking_pending,
    sama seperti alur publik) untuk tiap kamar via create_reservation (tetap lewat
    check_room_available — hard validator anti-overbooking yang sama, tidak dilewati), lalu
    langsung membuat transaksi Tripay & mengirim link bayar ke tamu lewat WhatsApp."""
    # Seluruh proses dibungkus _request_lock(rid) (2026-07-19, audit anti-race-condition
    # lanjutan) - termasuk pengecekan status "waiting_approval" itu sendiri, supaya kalau 2
    # staf klik Terima nyaris bersamaan, yang kedua benar-benar membaca status TERBARU
    # (bukan status basi dari sebelum yang pertama selesai) dan ditolak dengan bersih,
    # bukan sama-sama lolos dan membuat 2 booking asli dari 1 permintaan.
    async with _request_lock(rid):
        req = await db.booking_requests.find_one(scoped({"id": rid}, property_id))
        if not req:
            raise HTTPException(404, "Permintaan booking tidak ditemukan")
        if req["status"] not in STATUS_TERBUKA:
            raise HTTPException(400, f"Hanya permintaan waiting_approval yang bisa disetujui (status: {req['status']})")
        if body.payment_option not in ("dp50", "full"):
            raise HTTPException(400, "payment_option harus 'dp50' atau 'full'")
        room_ids = list(dict.fromkeys(body.room_ids or []))
        pesan_pembuka = f"Halo {req['nama_tamu']}, permintaan booking Anda kami *setujui*!"
        return await _proses_kamar_dan_kirim_link(
            req, room_ids, body.payment_option, body.method, user, property_id,
            pesan_pembuka=pesan_pembuka, log_action="approve_booking_request",
            log_desc="Setujui permintaan booking",
        )


@api.post("/booking-requests/{rid}/resend-link")
async def resend_payment_link(rid: str, body: BookingRequestApprove, user: dict = Depends(get_current_user),
                               property_id: str = Depends(get_active_property)):
    """Kirim ulang link pembayaran (2026-08-04, permintaan Agus) - khusus untuk permintaan
    yang link Tripay-nya SUDAH KADALUARSA (status_efektif "kadaluarsa", lihat
    _hitung_status_efektif) - booking lama sudah otomatis cancelled begitu link mati (lihat
    reservation_service.py), jadi ini BUKAN menghidupkan lagi link lama, tapi bikin booking
    + transaksi Tripay baru sepenuhnya (sama seperti approve_booking_request), lalu kirim
    link baru itu ke tamu. Staf pilih ulang kamar (kamar lama belum tentu masih kosong) &
    boleh ganti metode pembayaran (mis. dari QRIS yang cuma 1 jam ke Virtual Account yang
    24 jam - lihat catatan expired_time di tripay.py)."""
    async with _request_lock(rid):
        req = await db.booking_requests.find_one(scoped({"id": rid}, property_id))
        if not req:
            raise HTTPException(404, "Permintaan booking tidak ditemukan")
        bks = []
        if req.get("booking_ids"):
            bks = await db.bookings.find(scoped({"id": {"$in": req["booking_ids"]}}, property_id), {"_id": 0}).to_list(20)
        status_efektif = _hitung_status_efektif(req["status"], bks)
        if status_efektif != "kadaluarsa":
            raise HTTPException(
                400,
                f"Kirim ulang cuma untuk permintaan yang link-nya sudah kadaluarsa (status saat ini: {status_efektif}) - "
                "kalau masih menunggu pembayaran, link lama masih berlaku, tidak perlu link baru.",
            )
        if datetime.fromisoformat(req["tanggal_checkin"]).date() < datetime.now().date():
            raise HTTPException(
                400,
                "Tanggal check-in permintaan ini sudah lewat - tidak bisa kirim ulang link untuk tanggal lama, "
                "buat permintaan booking baru dengan tanggal yang benar.",
            )
        if body.payment_option not in ("dp50", "full"):
            raise HTTPException(400, "payment_option harus 'dp50' atau 'full'")
        room_ids = list(dict.fromkeys(body.room_ids or []))
        pesan_pembuka = (
            f"Halo {req['nama_tamu']}, link pembayaran sebelumnya sudah *kadaluarsa*. "
            f"Berikut link pembayaran *baru* untuk booking Anda:"
        )
        return await _proses_kamar_dan_kirim_link(
            req, room_ids, body.payment_option, body.method, user, property_id,
            pesan_pembuka=pesan_pembuka, log_action="resend_payment_link",
            log_desc="Kirim ulang link pembayaran (link lama kadaluarsa)",
        )


@api.post("/booking-requests/{rid}/reject")
async def reject_booking_request(rid: str, body: BookingRequestReject, user: dict = Depends(get_current_user),
                                  property_id: str = Depends(get_active_property)):
    # Lock sama (_request_lock) dengan approve - satu rid tidak boleh di-approve & ditolak
    # bersamaan oleh 2 staf berbeda juga (2026-07-19, audit anti-race-condition lanjutan).
    async with _request_lock(rid):
        req = await db.booking_requests.find_one(scoped({"id": rid}, property_id))
        if not req:
            raise HTTPException(404, "Permintaan booking tidak ditemukan")
        if req["status"] not in STATUS_TERBUKA:
            raise HTTPException(400, f"Hanya permintaan waiting_approval yang bisa ditolak (status: {req['status']})")
        now = now_iso()
        await db.booking_requests.update_one({"id": rid}, {"$set": {
            "status": "rejected", "rejected_by": user["nama"], "rejected_reason": body.alasan or "", "updated_at": now,
        }})
        await log_activity(user, "reject_booking_request", f"Tolak permintaan booking {req['kode']} ({req['nama_tamu']}): {body.alasan or '-'}")

        pesan = (
            f"Mohon maaf {req['nama_tamu']}, untuk permintaan booking tanggal {req['tanggal_checkin']} "
            f"kami belum bisa memenuhi" + (f": {body.alasan}." if body.alasan else " saat ini.") +
            " Silakan hubungi kami lagi untuk tanggal lain, kami siap bantu."
        )
        try:
            # Sama seperti approve - antre review staf bisa berjam-jam/berhari, WAJIB
            # sertakan template (2026-07-26).
            from routes.pesan_whatsapp import _kirim_dengan_alert
            nama_prop = await nama_properti(property_id)
            await _kirim_dengan_alert(
                req["no_hp"], pesan, konteks=f"reject booking request {rid}",
                template_name="menginap_ditolak_v1",
                template_params=[req["nama_tamu"], nama_prop, req.get("tanggal_checkin", "")],
                property_id=property_id,
            )
        except Exception as e:
            logging.getLogger("booking_requests").warning(f"Gagal kirim pesan tolak ke {req['no_hp']}: {e}")

    return await db.booking_requests.find_one(scoped({"id": rid}, property_id), {"_id": 0})
