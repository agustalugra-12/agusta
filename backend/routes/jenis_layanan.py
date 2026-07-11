from core import *
from reservation_service import check_room_available

# ---- Jenis Layanan & Paket / Jenis Reservasi ----
# Satu endpoint referensi dipakai untuk kedua nama fitur di plan NgodingPakeAI (tugasnya
# sama: sediakan daftar jenis layanan + aturan bisnisnya untuk ditampilkan ke tamu/staf).
# Aturan di sini SAMA PERSIS dengan yang sudah diimplementasikan nyata di kode lain
# (bukan duplikat baru): durasi & overtime Day Use dari `calc_tagihan`, kebijakan
# pembatalan H-3/H-1 dari `batasJamBebasBiaya` di PublicBook.jsx.

DEFAULT_SERVICE_CONFIG = {
    "jenis": [
        {
            "key": "day_use",
            "nama": "Day Use",
            "durasi_jam": 6,
            "jam_checkin_minggu": "12:00",
            "jam_checkin_lainnya": "10:00",
            "overtime_per_jam": 20000,
            "pembatalan_jam_bebas_biaya": 24,
        },
        {
            "key": "menginap",
            "nama": "Menginap",
            "jam_checkin": "14:00",
            "jam_checkout": "12:00",
            "pembatalan_jam_bebas_biaya": 72,
        },
    ],
}


@api.get("/jenis-reservasi")
async def get_jenis_reservasi(user: dict = Depends(get_current_user)):
    cfg = await db.service_config.find_one({}, {"_id": 0})
    return cfg or DEFAULT_SERVICE_CONFIG


# ---- Rekomendasi AI untuk Check-in Day Use ----
CLEANING_BUFFER_JAM = 1


def _jam_checkin_paling_awal(tanggal: str) -> str:
    hari = datetime.fromisoformat(tanggal).weekday()  # Python: Monday=0..Sunday=6
    return "12:00" if hari == 6 else "10:00"


def _jam_tambah(jam: str, tambah_jam: int) -> str:
    h, m = map(int, jam.split(":"))
    total = h * 60 + m + tambah_jam * 60
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


@api.get("/rekomendasi-checkin")
async def rekomendasi_checkin(
    tanggal: str = Query(...), tipe_kamar: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """Rekomendasi jam check-in Day Use per kamar (tipe tertentu), berdasarkan data
    reservasi Menginap sungguhan yang check-out pagi itu (bukan data tiruan) + jeda
    bersih-bersih, dan hanya menyarankan slot yang benar-benar kosong (anti double-booking,
    pakai check_room_available yang sama dengan booking publik).
    """
    batas_awal = _jam_checkin_paling_awal(tanggal)
    rooms = await db.rooms.find({"tipe": tipe_kamar}, {"_id": 0}).to_list(200)

    d_start = datetime.fromisoformat(f"{tanggal}T00:00:00+07:00")
    d_end = d_start + timedelta(days=1)

    opsi = []
    for r in rooms:
        # Booking Menginap yang check-out pagi/siang itu (jam_selesai jatuh di tanggal ini)
        menginap = await db.bookings.find_one({
            "room_id": r["id"], "tipe": "menginap",
            "status": {"$in": ["aktif", "booking_paid"]},
            "jam_selesai": {"$gte": d_start.isoformat(), "$lt": d_end.isoformat()},
        })
        if menginap:
            checkout_local = parse_iso(menginap["jam_selesai"], "jam_selesai").astimezone(timezone(timedelta(hours=7)))
            siap_jam = _jam_tambah(checkout_local.strftime("%H:%M"), CLEANING_BUFFER_JAM)
            ada_riwayat = True
        else:
            siap_jam = batas_awal
            ada_riwayat = False
        rekomendasi = max(siap_jam, batas_awal)

        try:
            mulai = datetime.fromisoformat(f"{tanggal}T{rekomendasi}:00+07:00")
            selesai = mulai + timedelta(hours=6)
            await check_room_available(r["id"], mulai, selesai)
        except HTTPException:
            continue  # slot ini sudah kepakai day_use lain, kamar ini tidak dipakai sebagai opsi

        opsi.append({"nomor": r["nomor"], "rekomendasi": rekomendasi, "ada_riwayat": ada_riwayat})

    opsi.sort(key=lambda o: o["rekomendasi"])
    is_penuh = len(opsi) == 0
    return {
        "batas_awal": batas_awal,
        "is_penuh": is_penuh,
        "utama": opsi[0] if opsi else None,
        "alternatif": opsi[1:],
    }
