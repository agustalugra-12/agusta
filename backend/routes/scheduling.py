from core import *
from scheduling_engine import cek_konflik_slot, slot_dayuse_aman

# ---- Scheduling Engine endpoints (advisory, dipakai Dashboard Quick Book) ----
# Lihat scheduling_engine.py untuk penjelasan lengkap kenapa ini murni advisory,
# tidak pernah memblokir/membatalkan booking dengan sendirinya.

@api.get("/scheduling/cek-slot")
async def scheduling_cek_slot(room_id: str, tipe: str, jam_mulai: str, jam_selesai: str,
                              user: dict = Depends(get_current_user)):
    """Cek advisory sebelum staf submit booking dari Quick Book — kasih peringatan real-time
    kalau kamar sudah dibooking (bakal ditolak saat submit) atau slot Day Use mepet booking
    Menginap berikutnya."""
    mulai = parse_iso(jam_mulai, "jam_mulai")
    selesai = parse_iso(jam_selesai, "jam_selesai")
    if selesai <= mulai:
        raise HTTPException(400, "jam_selesai harus setelah jam_mulai")
    hasil = await cek_konflik_slot(room_id, tipe, mulai, selesai)
    return {"konflik": hasil}


@api.get("/scheduling/rekomendasi-dayuse")
async def scheduling_rekomendasi_dayuse(room_id: str, jam_mulai: Optional[str] = None,
                                        user: dict = Depends(get_current_user)):
    """Slot Day Use aman untuk kamar ini mulai dari jam_mulai (default sekarang) — dipakai
    Dashboard buat pre-fill/hint jam selesai yang aman (Flexible Day Use)."""
    mulai = parse_iso(jam_mulai, "jam_mulai") if jam_mulai else datetime.now(timezone.utc)
    info = await slot_dayuse_aman(room_id, mulai)
    return {
        "jam_mulai": info["jam_mulai"].isoformat(),
        "jam_selesai_ideal": info["jam_selesai_ideal"].isoformat(),
        "jam_selesai_aman": info["jam_selesai_aman"].isoformat(),
        "dipersingkat": info["dipersingkat"],
        "alasan": info["alasan"],
    }
