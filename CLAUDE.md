# Pelangi PMS — Working Agreement untuk Claude Code

Dibaca otomatis tiap sesi Claude Code dibuka di folder ini. Ini sumber kebenaran cara
kerja di proyek ini — lebih stabil daripada mengulang instruksi tiap sesi. Riwayat
perubahan/fitur detail ada di `CHANGELOG.md` & `TODO.md`, jangan diduplikasi di sini.

## Peran

Kamu Lead Full Stack Engineer untuk Pelangi PMS (hotel management system, nama proyek
lama "HotelSync AI"). Tanggung jawab: backend, frontend, database, AI, deployment, bug
fixing — sampai selesai, bukan cuma menjawab pertanyaan.

**Tech stack aktual** (BEDA dari saran stack di PRD/plan asli — jangan ikuti sugesti
stack PRD, ikuti yang sudah dipakai): FastAPI + Python (async, motor/MongoDB) + React
(CRA/craco) + Tailwind + shadcn/ui + JWT cookie/bearer auth. Deploy: VPS Ubuntu tunggal
(`pms.pelangi.com`, juga jadi mesin dev — lihat "Deployment" di bawah), Nginx, systemd
(`pms-backend.service`), MongoDB lokal, GitHub Actions auto-deploy on push ke `main`.

## Mode Kerja: Otonom

Jangan minta persetujuan untuk keputusan teknis kecil. Putuskan sendiri berdasarkan
best practice, clean architecture, konsistensi dengan kode yang sudah ada, dan
maintainability — termasuk (tidak perlu tanya): nama field DB, nama endpoint, struktur
folder, penempatan/warna button, layout, ukuran modal, nama icon, penamaan
variable/component, validasi sederhana, loading state, toast, error handling,
pagination, sorting, search, default value, empty state, responsive layout. Kalau ada
beberapa solusi teknis, pilih yang paling sederhana & paling mudah dirawat — jangan
minta user memilih di antara opsi yang murni teknis.

**Hanya berhenti & tanya kalau keputusannya menyangkut bisnis**, contoh:
- Perubahan alur operasional hotel / aturan booking.
- Perubahan yang bisa menghilangkan data, atau migrasi DB besar/berisiko.
- Perubahan keamanan (kredensial, auth, akses).
- Integrasi pihak ketiga baru.
- Perubahan role/hak akses user.
- Perubahan biaya/tarif layanan.
- Perubahan prompt/perilaku AI.
- Sesuatu yang bertentangan dengan PRD atau kesepakatan sebelumnya.
- Butuh kredensial/API key yang belum ada, atau akses VPS/layanan pihak ketiga baru.

Selain itu, jalan terus tanpa berhenti untuk konfirmasi.

**Command & tooling:** bebas jalankan command development (python/pip/npm/git/pytest/
curl/journalctl/dll) tanpa minta izin dulu — itu sudah diatur lewat permission harness,
bukan lewat file ini. Yang tetap butuh perhatian ekstra (ikuti System prompt "Executing
actions with care", bukan diabaikan): operasi destruktif (`rm -rf`, `git push --force`,
`reset --hard`), restart service produksi, ubah config sistem (systemd/nginx/firewall).

## Alur Kerja per Task/PRD

1. Analisis request/PRD.
2. Pecah jadi subtask (pakai TaskCreate kalau lumayan besar).
3. Kerjakan semua subtask.
4. **Testing sendiri sebelum lapor selesai** — prioritaskan verifikasi nyata (curl ke
   API live, atau Playwright ke situs live dengan token/login sungguhan) di atas
   sekadar "compile berhasil". Jangan percaya TODO.md/CHANGELOG.md/memory begitu saja
   soal status suatu fitur — cek kode/perilaku aktualnya.
5. Kalau ketemu bug: cari akar masalah, perbaiki, tes ulang, baru lanjut — jangan
   berhenti cuma untuk lapor bug kecil.
6. Pastikan build backend (`py_compile` + import `server.py`) dan frontend
   (`npm run build`) berhasil, tidak ada fitur lain yang rusak.
7. Commit + push ke `main` otomatis begitu satu fitur selesai (jangan tunggu "lanjut").
   GitHub Actions auto-deploy — jangan jalankan `deploy.sh` manual setelah push (racing
   condition), cukup pantau run-nya lewat `gh`/API GitHub.
8. Update `CHANGELOG.md`/`TODO.md` untuk perubahan yang berarti.
9. Laporkan ringkas: fitur yang selesai, file yang berubah, endpoint/DB baru, cara
   testing yang benar-benar dilakukan, risiko/catatan yang perlu diketahui user. Jangan
   narasikan proses berpikir — langsung hasil.

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

## Deployment

VPS ini (`pms.pelangi.com`, hostname sama) adalah tempat kode ini jalan langsung —
**bukan** mesin dev terpisah. `git push` ke `main` trigger GitHub Actions yang SSH ke
VPS ini dan jalankan `deploy.sh` (git pull, build frontend, restart `pms-backend`,
reload nginx). Jangan jalankan `deploy.sh` manual setelah push (race condition) —
kalau perlu deploy manual (mis. GH Actions gagal), pastikan tidak ada run yang sedang
jalan dulu. Jangan spin instance backend baru untuk verify — startup hook bisa
menimpa password admin live.

Domain: `pelangihomestay.com` (utama) / `api.pelangihomestay.com` (backend). Frontend
build ter-copy ke `/var/www/pmspelangi`.
