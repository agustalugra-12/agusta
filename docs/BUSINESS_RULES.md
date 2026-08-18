# Business Rules & Fitur — Pelangi PMS

Dipindahkan dari CLAUDE.md (2026-08-18, audit token-optimization) supaya CLAUDE.md
sendiri tetap ringkas (cuma command/quirk yang tidak bisa ditebak dari kode) —
isi di sini TIDAK hilang, cuma tidak lagi otomatis ke-load ke tiap context window.
Baca file ini kalau butuh detail alur bisnis/fitur; detail histori perubahan tetap
di CHANGELOG.md/TODO.md, jangan diduplikasi ke sini juga.

## Business Rules — SUDAH BERLAKU sekarang

- Tidak boleh ada 2 booking Menginap overlap di kamar yang sama (`check_room_available`,
  `backend/reservation_service.py`) — validasi datetime penuh, bukan cuma tanggal.
- Tidak boleh ada 2 booking Day Use overlap di kamar yang sama (validator sama).
- Day Use boleh pakai kamar yang sama dengan Menginap selama tidak overlap waktu; buffer
  housekeeping (default 30 menit) & durasi Day Use (default 6 jam) dihitung terpusat di
  `backend/scheduling_engine.py` — **semua modul yang butuh info ini WAJIB pakai fungsi
  di situ, jangan hitung ulang sendiri di tempat lain** (Dashboard staf/Quick Book, AI
  WhatsApp, dan Booking Engine publik `/book` sudah pakai ini per 2026-07-17).
- Booking Menginap tidak pernah otomatis dibatalkan/digeser gara-gara Day Use — sistem
  hanya boleh memberi rekomendasi/peringatan, keputusan akhir di resepsionis/owner.
- Day Use tidak pernah masuk ke PMS RedDoorz (RedDoorz cuma dipakai untuk baca email
  konfirmasi OTA booking Menginap, lihat `backend/routes/otomasi_email.py`).
- AI WhatsApp (`backend/routes/pesan_whatsapp.py`) TIDAK PERNAH langsung membuat booking.
  Sejak 2026-07-17 AI bisa mengumpulkan data booking lewat percakapan multi-turn dan
  membuat **Booking Request** non-binding (`backend/routes/booking_requests.py`,
  `db.booking_requests`) — booking sungguhan baru dibuat staf lewat Terima manual di
  halaman `/booking-requests` (juga tampil sebagai alert di Dashboard utama). Selain itu
  (pertanyaan umum, ekstraksi pengeluaran) AI tetap hanya menjawab/merekomendasikan/
  mengekstrak data terstruktur untuk insert deterministik lewat kode, sama seperti
  sebelumnya.
- **Booking Menginap publik instan DIMATIKAN sejak 2026-07-17** (keputusan bisnis user):
  `/book` publik cuma melayani Day Use instan seperti biasa. Tab Menginap di `/book`
  tetap bisa dilihat (preview kamar/harga) tapi diarahkan chat WhatsApp (CTA), backend
  `public_create_booking` menolak `tipe=menginap`. Satu-satunya jalur booking Menginap
  sekarang: AI WhatsApp → Booking Request → staf Terima → link Tripay. Quick Book staf
  (walk-in, Dashboard) untuk Menginap TIDAK terpengaruh — tetap instan seperti biasa
  (tamu sudah fisik di lokasi, tidak masuk akal digating lewat approval/RedDoorz).
- **Tahap 2 (Action Required RedDoorz + sinkron email) SUDAH LIVE sejak 2026-07-17**:
  booking Menginap dari Booking Request membawa `sync_status` — `waiting_reddoorz_input`
  begitu dibuat → `waiting_reddoorz_sync` setelah staf klik "Sudah Input ke RedDoorz"
  (`POST /bookings/{id}/reddoorz-input-selesai`, section "Action Required" di halaman
  Booking Request & Dashboard) → `synced` otomatis begitu AI Email Parser menerima &
  mencocokkan email konfirmasi RedDoorz (`_cocokkan_booking_pending_reddoorz`,
  `backend/routes/otomasi_email.py` — cegah booking duplikat). `check_room_available`
  TIDAK terpengaruh sama sekali (slot tetap terkunci penuh selama proses ini) — yang
  berubah cuma TAMPILAN: Kalender Ketersediaan & grid Dashboard mengecualikan booking
  `sync_status` `waiting_reddoorz_*` dari hitungan "terisi"/badge Booked (supaya tidak
  dianggap tamu terkonfirmasi sebelum RedDoorz benar-benar konfirmasi) — **kamar jadi
  terlihat "tersedia" di kalender padahal sudah terpakai**, staf yang coba booking ulang
  tetap ditolak `check_room_available` (tidak ada risiko double-booking, cuma tampilan
  sementara belum penuh). **Laporan keuangan SENGAJA TIDAK ikut disaring** — uang sudah
  diterima nyata lewat Tripay, tetap tercatat sebagai pemasukan berapa pun status
  sync-nya.

## Fitur yang Sudah Ada (ringkas — detail lengkap di CHANGELOG.md)

- **Jadwal Kerja Staf (2026-07-17, owner-only, `/jadwal-kerja`):** 7 staf diseed
  (`backend/server.py`, aturan larangan shift per orang disimpan sebagai data
  `shift_terlarang` di `db.staff_kerja`, bukan hardcode). AI Generate (OpenAI) + perbaikan
  deterministik menjamin tiap staf PERSIS 4 hari off/bulan & tidak pernah shift terlarang,
  apapun hasil AI-nya. Edit manual/tukar shift/publish/export PDF/riwayat — semua di
  `backend/routes/jadwal_kerja.py`. Integrasi absensi belum dikerjakan (bukan Phase 1).
- **Modul Reservasi & Priority Booking (Tahap 1+2, 2026-07-17, PRD lengkap sudah live):**
  AI WhatsApp kumpulkan data booking multi-turn → `db.booking_requests` (non-binding) →
  staf Terima/Tolak di `/booking-requests` (juga tampil sebagai alert di Dashboard) →
  Terima = booking sungguhan dibuat + link Tripay otomatis terkirim ke tamu. Booking
  Menginap dari jalur ini menunggu Action Required (input manual RedDoorz) sebelum
  dianggap "Confirmed" (lihat Business Rules di atas untuk detail `sync_status`). `/book`
  publik Menginap dimatikan (diarahkan WhatsApp), Day Use tetap instan. Reuse penuh
  `create_reservation`/`tripay_create_transaction`, tidak ada jalur pembayaran paralel.
- **Payment Alert & Action Center:** Web Push (VAPID, `backend/routes/push.py`, opt-in
  per user di halaman Profil) broadcast ke resepsionis+owner sekaligus untuk booking
  baru/pembayaran/komplain/housekeeping, plus suara alert kustom (Web Audio API,
  `frontend/src/lib/alertSound.js`) yang otomatis berbunyi di tiap tab PMS yang terbuka,
  dan alert tambahan ke Telegram owner (`kirim_alert_owner`,
  `backend/routes/telegram_bot.py`) tiap pembayaran Tripay masuk & Booking Request baru.
- **Telegram Bot** (owner + staff, bot terpisah): owner tanya kondisi bisnis (AI, konteks
  dari data PMS asli), staff (dan owner) catat pengeluaran via teks/foto, laporan harian
  otomatis jam 22:00 WIB. Linking pakai kode 6 digit dari halaman Profil.
- **Scheduling Engine** (`backend/scheduling_engine.py`): fungsi murni advisory, tidak
  pernah mengubah `check_room_available`/validasi inti yang sudah ada.
- **Modul Komplain & Maintenance** (`/komplain`, `/maintenance`): auto-tiket dari
  klasifikasi AI pesan WhatsApp tamu (`backend/routes/issues.py`, fungsi `buat_issue`
  reusable dari endpoint manual maupun otomatis).
