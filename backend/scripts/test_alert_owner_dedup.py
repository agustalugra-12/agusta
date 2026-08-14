"""Regresi dedup in-memory untuk POST /integrasi-ai-bot/alert-owner (2026-08-14, LOW -
temuan #4 audit lanjutan pola bug idempotency_key booking_request/2026-08-14).

Bug: `_pms_alert_owner` (ai-chat-bot, connectors/pms_connector.py) dibungkus
_pms_http_retry - retry pada httpx.ReadTimeout (PMS lambat balas krn `kirim_alert_owner`
loop kirim ke SEMUA owner yang terhubung Telegram satu-satu, bisa lambat kalau owner-nya
banyak/Telegram API sedang lelet, BUKAN gagal sungguhan) sebelumnya bikin teks alert yang
SAMA PERSIS terkirim 2x ke Telegram owner. Trivial (cuma pesan dobel, tidak ada data/uang
yang salah) tapi tetap diperbaiki demi konsistensi.

Fix: BEDA dari 3 fix lain malam ini (endpoint ini tidak buat record DB apa pun utk
"dikembalikan" - kirim_alert_owner murni relay Telegram) - dedup pakai window in-memory
singkat (30 detik) di LEVEL ENDPOINT (`ai_bot_alert_owner`, routes/integrasi_ai_bot.py),
BUKAN di kirim_alert_owner sendiri (fungsi itu juga dipanggil dari banyak tempat lain PMS
yang tidak lewat retry HTTP apa pun - dedup global di sana berisiko salah menelan 2 alert
BEDA yang kebetulan teksnya sama).

Sama pola AMAN dgn skrip idempotency lain malam ini: property_id PALSU (walau endpoint ini
sendiri tidak scope apa pun by property, cuma dipakai konsisten dgn pola file lain),
kirim_alert_owner (Telegram sungguhan) di-monkeypatch total - skrip ini TIDAK PERNAH
mengirim pesan Telegram nyata.

BEDA dari `scripts/test_regresi.py` (gerbang WAJIB, scope reports/laporan/checkin-checkout)
- routes/integrasi_ai_bot.py TIDAK termasuk cakupan gerbang itu, jadi skrip ini BUKAN
bagian dari gerbang wajib push, cuma regresi tambahan utk fix dedup spesifik ini.

Jalankan:
    cd backend && venv/bin/python -m scripts.test_alert_owner_dedup
Exit code 1 kalau ada FAIL.
"""
import asyncio
import sys
import uuid

sys.path.insert(0, ".")


class _TelegramCounter:
    """Pengganti kirim_alert_owner (Telegram sungguhan) - hitung panggilan, TIDAK PERNAH
    benar-benar kirim pesan Telegram nyata."""
    def __init__(self):
        self.calls = 0

    async def fake_kirim_alert_owner(self, pesan: str):
        self.calls += 1


def _pasang_mock(counter: _TelegramCounter):
    """ai_bot_alert_owner melakukan `from routes.telegram_bot import kirim_alert_owner` di
    DALAM fungsi (deferred import) - patch attribute modul routes.telegram_bot langsung,
    otomatis kepakai tiap panggilan berikutnya."""
    import routes.telegram_bot as telegram_bot_mod
    asli = telegram_bot_mod.kirim_alert_owner
    telegram_bot_mod.kirim_alert_owner = counter.fake_kirim_alert_owner
    return telegram_bot_mod, asli


def _lepas_mock(telegram_bot_mod, asli):
    telegram_bot_mod.kirim_alert_owner = asli


def _bersihkan_dedup_state():
    """Guard in-memory global (`_recent_alert_owner_sends`, routes/integrasi_ai_bot.py) -
    bersihkan SEBELUM tiap skenario supaya skenario satu tidak bocor ke skenario lain lewat
    state module-level yang dipakai bersama (beda dari skenario lain malam ini yang isolasi
    lewat property_id palsu di DB - guard ini murni in-memory, tidak ada DB sama sekali)."""
    import routes.integrasi_ai_bot as mod
    mod._recent_alert_owner_sends.clear()


async def skenario_normal_single_call_terkirim() -> tuple:
    nama = "normal_single_call_terkirim_sekali"
    from routes.integrasi_ai_bot import ai_bot_alert_owner, AiBotAlertIn

    _bersihkan_dedup_state()
    counter = _TelegramCounter()
    telegram_bot_mod, asli = _pasang_mock(counter)
    try:
        pesan = f"[TES] alert tunggal {uuid.uuid4().hex[:8]}"
        hasil = await ai_bot_alert_owner(AiBotAlertIn(pesan=pesan), "dummy-property-id")
        if counter.calls != 1:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.calls}x, harus 1x")
        if hasil.get("deduped"):
            return (nama, "FAIL - panggilan pertama salah ditandai deduped")
        return (nama, "PASS")
    finally:
        _lepas_mock(telegram_bot_mod, asli)
        _bersihkan_dedup_state()


async def skenario_retry_teks_sama_tidak_dobel_kirim() -> tuple:
    """Reproduksi PERSIS pola bug: 2 POST identik (teks alert SAMA PERSIS, simulasi retry
    _pms_http_retry setelah httpx ReadTimeout) - HARUS cuma 1x kirim Telegram ke owner
    (bukan 2 pesan identik dobel)."""
    nama = "retry_teks_sama_tidak_dobel_kirim_ke_owner"
    from routes.integrasi_ai_bot import ai_bot_alert_owner, AiBotAlertIn

    _bersihkan_dedup_state()
    counter = _TelegramCounter()
    telegram_bot_mod, asli = _pasang_mock(counter)
    try:
        pesan = f"[TES] koneksi WhatsApp terputus {uuid.uuid4().hex[:8]}"
        hasil_1 = await ai_bot_alert_owner(AiBotAlertIn(pesan=pesan), "dummy-property-id")
        hasil_2 = await ai_bot_alert_owner(AiBotAlertIn(pesan=pesan), "dummy-property-id")  # payload identik, simulasi retry

        if counter.calls != 1:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.calls}x total, harus 1x (retry kirim dobel ke owner)")
        if not hasil_2.get("deduped"):
            return (nama, "FAIL - percobaan ke-2 (retry, teks sama) harus ditandai deduped=True")
        return (nama, "PASS")
    finally:
        _lepas_mock(telegram_bot_mod, asli)
        _bersihkan_dedup_state()


async def skenario_teks_berbeda_tetap_2_kali_kirim() -> tuple:
    """Pastikan ini dedup SUNGGUHAN by teks-persis-sama, BUKAN heuristik jendela waktu buta
    - 2 alert BEDA (teks beda, kejadian nyata yang beda) yang kebetulan dikirim nyaris
    bersamaan tetap harus terkirim 2x ke owner, tidak boleh false-positive di-skip."""
    nama = "teks_berbeda_tetap_2_kali_kirim_tidak_false_positive"
    from routes.integrasi_ai_bot import ai_bot_alert_owner, AiBotAlertIn

    _bersihkan_dedup_state()
    counter = _TelegramCounter()
    telegram_bot_mod, asli = _pasang_mock(counter)
    try:
        suffix = uuid.uuid4().hex[:8]
        hasil_1 = await ai_bot_alert_owner(AiBotAlertIn(pesan=f"[TES] kejadian A {suffix}"), "dummy-property-id")
        hasil_2 = await ai_bot_alert_owner(AiBotAlertIn(pesan=f"[TES] kejadian B {suffix}"), "dummy-property-id")

        if counter.calls != 2:
            return (nama, f"FAIL - kirim_alert_owner terpanggil {counter.calls}x, harus 2x (2 alert nyata beda salah dianggap duplikat)")
        if hasil_1.get("deduped") or hasil_2.get("deduped"):
            return (nama, "FAIL - 2 alert beda teks salah ditandai deduped")
        return (nama, "PASS")
    finally:
        _lepas_mock(telegram_bot_mod, asli)
        _bersihkan_dedup_state()


async def main():
    skenario_list = [
        skenario_normal_single_call_terkirim,
        skenario_retry_teks_sama_tidak_dobel_kirim,
        skenario_teks_berbeda_tetap_2_kali_kirim,
    ]

    print("--- Skenario dedup in-memory alert-owner (in-process, tanpa DB) ---")
    hasil_skenario = []
    for s in skenario_list:
        try:
            nama, status = await s()
        except Exception as e:
            nama, status = (s.__name__, f"FAIL - exception: {e!r}")
        hasil_skenario.append((nama, status))
        print(f"[{'PASS' if status == 'PASS' else 'FAIL'}] {nama}: {status}")

    gagal = [h for h in hasil_skenario if h[1] != "PASS"]
    print(f"\n=== RINGKASAN: {len(hasil_skenario) - len(gagal)}/{len(hasil_skenario)} PASS ===")
    if gagal:
        print("ADA REGRESI:")
        for nama, status in gagal:
            print(f"  - {nama}: {status}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
