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


async def estimasi_kamar_siap(room_id: str) -> Optional[datetime]:
    """Kalau kamar sedang ditempati booking yang aktif SEKARANG, kembalikan estimasi waktu
    siap dipakai lagi (jam_selesai booking tsb + buffer housekeeping). None kalau kamar
    tidak sedang ditempati booking apa pun saat ini."""
    now = datetime.now(timezone.utc)
    aktif = await db.bookings.find_one({
        "room_id": room_id, "status": {"$in": BOOKING_AKTIF_STATUS},
        "jam_mulai": {"$lte": now.isoformat()}, "jam_selesai": {"$gt": now.isoformat()},
    }, sort=[("jam_selesai", 1)])
    if not aktif or not aktif.get("jam_selesai"):
        return None
    return datetime.fromisoformat(aktif["jam_selesai"]) + timedelta(minutes=BUFFER_HOUSEKEEPING_MENIT)


async def rekomendasi_slot_kosong(tipe_kamar: str) -> Optional[Dict[str, Any]]:
    """Kalau semua kamar tipe ini penuh SEKARANG, cari kandidat kamar paling cepat siap +
    slot Day Use penuh (6 jam) yang tidak bentrok booking lain yang sudah terkonfirmasi.
    Dipakai AI WhatsApp untuk jawab "penuh, tapi kamar X siap jam Y". None kalau tidak ada
    kandidat yang bisa diestimasi."""
    rooms = await db.rooms.find({"tipe": tipe_kamar}, {"_id": 0}).to_list(200)
    kandidat = []
    for r in rooms:
        siap = await estimasi_kamar_siap(r["id"])
        if not siap:
            continue
        usulan_selesai = siap + timedelta(hours=DAYUSE_DURASI_JAM)
        try:
            await check_room_available(r["id"], siap, usulan_selesai)
        except HTTPException:
            continue  # slot ini bentrok booking lain yang sudah terkonfirmasi, lewati
        kandidat.append({"room_id": r["id"], "room_nomor": r["nomor"], "siap_pakai": siap, "usulan_selesai": usulan_selesai})
    if not kandidat:
        return None
    kandidat.sort(key=lambda x: x["siap_pakai"])
    return kandidat[0]


async def booking_menginap_berikutnya(room_id: str, setelah: datetime) -> Optional[Dict[str, Any]]:
    """Booking MENGINAP terkonfirmasi berikutnya untuk kamar ini yang check-in setelah
    waktu tertentu — dipakai membatasi slot Day Use flexible (Rule 5 & Flexible Day Use)."""
    return await db.bookings.find_one({
        "room_id": room_id, "tipe": "menginap",
        "status": {"$in": BOOKING_TERKONFIRMASI_STATUS},
        "jam_mulai": {"$gt": setelah.isoformat()},
    }, {"_id": 0}, sort=[("jam_mulai", 1)])


async def slot_dayuse_aman(room_id: str, mulai: datetime, durasi_jam: int = DAYUSE_DURASI_JAM) -> Dict[str, Any]:
    """Hitung slot Day Use AMAN mulai dari `mulai` untuk kamar ini — durasi otomatis
    dipersingkat (Flexible Day Use) kalau ada booking Menginap terkonfirmasi yang akan
    check-in sebelum durasi penuh + buffer housekeeping selesai. Booking Menginap TIDAK
    PERNAH digeser/dibatalkan — yang menyesuaikan selalu Day Use (prioritas menginap lebih
    tinggi, sesuai urutan prioritas PRD #6)."""
    jam_selesai_ideal = mulai + timedelta(hours=durasi_jam)
    menginap_berikutnya = await booking_menginap_berikutnya(room_id, mulai)
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


async def cek_konflik_slot(room_id: str, tipe: str, mulai: datetime, selesai: datetime) -> Optional[Dict[str, Any]]:
    """Peringatan ADVISORY (bukan blocking) sebelum staf submit booking — dipanggil live dari
    Dashboard Quick Book. Tidak menggantikan check_room_available, yang tetap jadi hard
    validator satu-satunya saat submit sungguhan (endpoint ini boleh bilang "aman" lalu
    submit tetap gagal kalau ada race condition — itu wajar & sudah ditangani error submit).
    Return None = tidak ada peringatan apa pun."""
    try:
        await check_room_available(room_id, mulai, selesai)
    except HTTPException as e:
        return {"level": "blokir", "pesan": e.detail}
    if tipe == "day_use":
        info = await slot_dayuse_aman(room_id, mulai)
        if info["dipersingkat"] and info["jam_selesai_aman"] < selesai:
            return {
                "level": "peringatan", "pesan": info["alasan"],
                "rekomendasi_selesai": info["jam_selesai_aman"].isoformat(),
            }
    return None
