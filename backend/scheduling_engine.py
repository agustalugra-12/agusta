"""Scheduling Engine — logika terpusat untuk slot & konflik Day Use/Menginap.

Dipakai bareng oleh AI WhatsApp (routes/pesan_whatsapp.py) dan endpoint
/scheduling/* (dipanggil Dashboard staf saat Quick Book) — supaya tidak ada
penghitungan jadwal yang tercecer/berbeda-beda di tiap modul (PRD Revisi #6:
"Seluruh modul menggunakan Scheduling Engine yang sama").

PENTING — modul ini TIDAK mengubah/menggantikan check_room_available
(reservation_service.py), yang tetap satu-satunya hard validator anti-
overbooking dipakai semua jalur create/update booking yang sudah ada dan
teruji. Semua fungsi di sini murni ADVISORY: rekomendasi & peringatan,
tidak pernah memblokir atau membatalkan booking dengan sendirinya (PRD Rule 5:
sistem boleh mengurangi/menyarankan ulang slot Day Use dan memberi notifikasi,
TAPI tidak boleh otomatis membatalkan booking yang sudah dikonfirmasi —
keputusan akhir tetap di tangan resepsionis/owner).
"""
from core import *
from reservation_service import check_room_available

DAYUSE_DURASI_JAM = 6
BUFFER_HOUSEKEEPING_MENIT = 30
WIB = timezone(timedelta(hours=7))  # konsisten dengan konvensi WIB di public.py/pesan_whatsapp.py/dll

BOOKING_AKTIF_STATUS = ["aktif", "booking_paid", "checked_in"]
BOOKING_TERKONFIRMASI_STATUS = ["aktif", "booking_pending", "booking_paid", "checked_in"]


async def estimasi_kamar_siap(room_id: str, property_id: str) -> Optional[datetime]:
    """Kalau kamar sedang ditempati booking DAY USE yang aktif SEKARANG, kembalikan estimasi
    waktu siap dipakai lagi (jam_selesai booking tsb + buffer housekeeping). None kalau kamar
    tidak sedang ditempati Day Use saat ini - SENGAJA dibatasi hanya Day Use (dikonfirmasi
    user 2026-07-19): rekomendasi "kamar akan kosong lagi jam X" cuma jujur kalau penghuni
    sekarang memang akan checkout hari ini. Tamu Menginap tidak checkout hari ini, jadi kamar
    yang penuh karena Menginap TIDAK PERNAH dikasih estimasi - harus dijawab "penuh" apa
    adanya, bukan janji palsu kapan kosong."""
    now = datetime.now(timezone.utc)
    kandidat_siap = []

    aktif = await db.bookings.find_one(scoped({
        "room_id": room_id, "tipe": "day_use", "status": {"$in": BOOKING_AKTIF_STATUS},
        "jam_mulai": {"$lte": now.isoformat()}, "jam_selesai": {"$gt": now.isoformat()},
    }, property_id), sort=[("jam_selesai", 1)])
    if aktif and aktif.get("jam_selesai"):
        kandidat_siap.append(datetime.fromisoformat(aktif["jam_selesai"]) + timedelta(minutes=BUFFER_HOUSEKEEPING_MENIT))

    # Walk-in Day Use lewat db.checkins (2026-08-01, bug nyata ditemukan: Harmoni SEMUA
    # kamarnya walk-in via checkin staf langsung, bukan db.bookings sama sekali - fungsi
    # ini sebelumnya cuma cek db.bookings, jadi SELALU return None utk properti yang
    # walk-in-nya lewat checkins - AI salah bilang "penuh, tidak ada estimasi" padahal
    # datanya sebenarnya ada: jam_checkin + durasi Day Use standar). checkins tidak
    # menyimpan jam_selesai terjadwal (checkout riil ditentukan pas tamu benar2 keluar),
    # jadi diestimasi dari jam_checkin + DAYUSE_DURASI_JAM standar - PERKIRAAN, bukan
    # jaminan (konsisten dengan framing "estimasi_kosong_lagi" yang sudah ada).
    checkin_aktif = await db.checkins.find_one(scoped({
        "room_id": room_id, "status": "aktif", "jam_checkout": None,
    }, property_id), sort=[("jam_checkin", 1)])
    if checkin_aktif and checkin_aktif.get("jam_checkin"):
        estimasi = datetime.fromisoformat(checkin_aktif["jam_checkin"]) + timedelta(hours=DAYUSE_DURASI_JAM)
        if estimasi > now:  # kalau sudah lewat estimasi (overtime), jangan kasih waktu masa lalu
            kandidat_siap.append(estimasi + timedelta(minutes=BUFFER_HOUSEKEEPING_MENIT))

    if not kandidat_siap:
        return None
    return min(kandidat_siap)


async def rekomendasi_slot_kosong(tipe_kamar: str, property_id: str, jumlah: int = 1) -> Optional[Dict[str, Any]]:
    """Kalau semua kamar tipe ini penuh SEKARANG, cari kandidat kamar paling cepat siap +
    slot Day Use yang tidak bentrok booking lain yang sudah terkonfirmasi. Dipakai AI
    WhatsApp untuk jawab "penuh, tapi kamar X siap jam Y". None kalau tidak ada kandidat
    yang bisa diestimasi.

    `jumlah` (2026-08-01, optimasi permintaan Agus - "tentukan fungsinya apa saja/optimal"):
    balikin sampai N kandidat terurut waktu tercepat (bukan cuma 1) lewat field "alternatif"
    di hasil, supaya AI bisa tawarkan pilihan seperti CS manusia ("kamar 3 jam 14:30, atau
    kamar 5 jam 15:00") - bukan cuma satu opsi kaku. Kandidat utama (return value top-level)
    tetap yang PALING CEPAT siap, jadi pemanggil lama yang cuma pakai field top-level tidak
    perlu berubah.

    Durasi slot per kandidat SEKARANG pakai slot_dayuse_aman (2026-08-01, bug/optimasi
    ditemukan: sebelumnya selalu coba slot 6 jam PENUH lewat check_room_available - kalau
    ada booking Menginap yang check-in beberapa jam setelah kamar siap, hard validator itu
    MENOLAK seluruh kandidat & kamar itu jadi terlihat "tidak ada rekomendasi" padahal kamar
    itu sebenarnya BISA dipakai Day Use durasi lebih pendek sebelum tamu Menginap datang -
    slot_dayuse_aman yang sudah ada persis dibuat untuk menghitung durasi aman ini, tapi
    belum pernah dipakai di sini sebelumnya)."""
    rooms = await db.rooms.find(scoped({"tipe": tipe_kamar}, property_id), {"_id": 0}).to_list(200)
    kandidat = []
    for r in rooms:
        siap = await estimasi_kamar_siap(r["id"], property_id)
        if not siap:
            continue
        aman = await slot_dayuse_aman(r["id"], siap, property_id)
        usulan_selesai = aman["jam_selesai_aman"]
        if usulan_selesai <= siap:
            continue  # tidak ada durasi Day Use yang muat sama sekali sebelum tamu Menginap berikutnya
        try:
            await check_room_available(r["id"], siap, usulan_selesai, property_id)
        except HTTPException:
            continue  # tetap bentrok meski sudah dipersingkat (mis. Day Use lain sudah booked di situ), lewati
        kandidat.append({
            "room_id": r["id"], "room_nomor": r["nomor"], "siap_pakai": siap, "usulan_selesai": usulan_selesai,
            "dipersingkat": aman["dipersingkat"], "alasan_dipersingkat": aman["alasan"],
        })
    if not kandidat:
        return None
    kandidat.sort(key=lambda x: x["siap_pakai"])
    utama = dict(kandidat[0])
    utama["alternatif"] = kandidat[1:jumlah] if jumlah > 1 else []
    return utama


async def booking_menginap_berikutnya(room_id: str, setelah: datetime, property_id: str) -> Optional[Dict[str, Any]]:
    """Booking MENGINAP terkonfirmasi berikutnya untuk kamar ini yang check-in setelah
    waktu tertentu — dipakai membatasi slot Day Use flexible (Rule 5 & Flexible Day Use)."""
    return await db.bookings.find_one(scoped({
        "room_id": room_id, "tipe": "menginap",
        "status": {"$in": BOOKING_TERKONFIRMASI_STATUS},
        "jam_mulai": {"$gt": setelah.isoformat()},
    }, property_id), {"_id": 0}, sort=[("jam_mulai", 1)])


async def slot_dayuse_aman(room_id: str, mulai: datetime, property_id: str, durasi_jam: int = DAYUSE_DURASI_JAM) -> Dict[str, Any]:
    """Hitung slot Day Use AMAN mulai dari `mulai` untuk kamar ini — durasi otomatis
    dipersingkat (Flexible Day Use) kalau ada booking Menginap terkonfirmasi yang akan
    check-in sebelum durasi penuh + buffer housekeeping selesai. Booking Menginap TIDAK
    PERNAH digeser/dibatalkan — yang menyesuaikan selalu Day Use (prioritas menginap lebih
    tinggi, sesuai urutan prioritas PRD #6)."""
    jam_selesai_ideal = mulai + timedelta(hours=durasi_jam)
    menginap_berikutnya = await booking_menginap_berikutnya(room_id, mulai, property_id)
    if not menginap_berikutnya:
        return {
            "jam_mulai": mulai, "jam_selesai_ideal": jam_selesai_ideal,
            "jam_selesai_aman": jam_selesai_ideal, "dipersingkat": False, "alasan": None,
        }
    checkin_menginap = datetime.fromisoformat(menginap_berikutnya["jam_mulai"])
    batas_aman = checkin_menginap - timedelta(minutes=BUFFER_HOUSEKEEPING_MENIT)
    if batas_aman >= jam_selesai_ideal:
        return {
            "jam_mulai": mulai, "jam_selesai_ideal": jam_selesai_ideal,
            "jam_selesai_aman": jam_selesai_ideal, "dipersingkat": False, "alasan": None,
        }
    return {
        "jam_mulai": mulai, "jam_selesai_ideal": jam_selesai_ideal,
        "jam_selesai_aman": max(mulai, batas_aman), "dipersingkat": True,
        "alasan": (
            f"Ada booking menginap check-in {checkin_menginap.astimezone(WIB).strftime('%H:%M')} WIB "
            f"— Day Use disarankan selesai lebih awal supaya housekeeping "
            f"({BUFFER_HOUSEKEEPING_MENIT} menit) selesai tepat waktu."
        ),
    }


async def cek_konflik_slot(room_id: str, tipe: str, mulai: datetime, selesai: datetime, property_id: str) -> Optional[Dict[str, Any]]:
    """Peringatan ADVISORY (bukan blocking) sebelum staf submit booking — dipanggil live dari
    Dashboard Quick Book. Tidak menggantikan check_room_available, yang tetap jadi hard
    validator satu-satunya saat submit sungguhan (endpoint ini boleh bilang "aman" lalu
    submit tetap gagal kalau ada race condition — itu wajar & sudah ditangani error submit).
    Return None = tidak ada peringatan apa pun."""
    try:
        await check_room_available(room_id, mulai, selesai, property_id)
    except HTTPException as e:
        return {"level": "blokir", "pesan": e.detail}
    if tipe == "day_use":
        info = await slot_dayuse_aman(room_id, mulai, property_id)
        if info["dipersingkat"] and info["jam_selesai_aman"] < selesai:
            return {
                "level": "peringatan", "pesan": info["alasan"],
                "rekomendasi_selesai": info["jam_selesai_aman"].isoformat(),
            }
    return None
