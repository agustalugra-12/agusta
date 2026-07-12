# TODO — HotelSync AI (plan `f62b871a-6ff7-47a6-8030-6b82817d22b8`)

Dikelola otomatis (Autonomous Development Mode). Sumber kebenaran urutan kerja tetap
`npx ngodingpakeai task next --plan f62b871a-6ff7-47a6-8030-6b82817d22b8 --json`;
daftar ini ringkasan untuk manusia, bisa sedikit basi — cek CLI kalau ragu.

## Fase 1 — Visibilitas & Pengelolaan Dasar
- [x] Dasbor Ketersediaan — sempat lama tercatat "done" padahal `Ketersediaan.jsx` masih 100% data tiruan sejak commit awal (backend `ketersediaan.py` sudah ada tapi tidak pernah dipanggil). Disambungkan ke data nyata 2026-07-12: ringkasan/status-tipe/notifikasi dari `/ketersediaan/live` (polling 10 detik), Kalender Ketersediaan diubah dari tampilan 30 hari jadi 7 hari (navigasi per minggu) dari `/ketersediaan/kalender-bulanan`, dialog detail hari dari endpoint baru `/ketersediaan/hari` (breakdown per tipe kamar).
- [x] Daftar Reservasi — sama seperti Ketersediaan, lama tercatat "done" padahal `DaftarReservasi.jsx` masih 100% data tiruan (`MOCK_RESERVATIONS`) sejak awal, walau backend `GET /bookings` sudah mendukung `search`/`status`/`date` query param lengkap. Disambungkan ke data nyata 2026-07-12. **Sekaligus digabung dengan halaman "Tamu"** (permintaan user, biar ringkas & saling melengkapi — reservasi + riwayat kunjungan/WA tamu dalam satu tempat): `Tamu.jsx` dihapus, isinya jadi tab "Tamu" di `DaftarReservasi.jsx` (`/reservasi`), tab lain "Reservasi" pakai data `/bookings` nyata (ganti label status tiruan Confirmed/Pending/Cancelled dengan status asli aktif/booking_pending/booking_paid/checked_in/cancelled/no_show). Aksi Ubah Pesanan disederhanakan jadi ubah jadwal saja (ganti tipe kamar butuh pindah `room_id`, di luar cakupan quick-edit ini). Sidebar item "Tamu" dihapus, route `/tamu` dihapus.

## Fase 3 — Manajemen Sistem Internal
### Autentikasi & Pengelolaan Akun — backend LENGKAP (2026-07-11)
- [x] Halaman login — SUDAH NYATA sejak awal (bukan mock), tersambung `/api/auth/login`
- [x] Halaman pendaftaran (sign-up publik) — **SEKARANG DIKERJAKAN** (keputusan sebelumnya untuk menunda dibatalkan atas instruksi user 2026-07-11): `POST /api/auth/register`, akun baru role resepsionis + status `pending`, Owner aktifkan lewat `/pengguna`. Frontend `Register.jsx` di `/register`, tautan dari Login.
- [x] Halaman dasbor utama — SUDAH NYATA sejak Fase 1 (`Dashboard.jsx` di `/`). **Konsolidasi 2026-07-12 (v1, dikoreksi user):** sempat dipindah "Daftar Booking" (list+form) dari halaman "Booking" ke Dashboard, TAPI user koreksi maksudnya beda — lihat v2 di bawah.
- [x] **Konsolidasi 2026-07-12 (v2, final):** klik kamar berstatus kosong di grid Dashboard sekarang membuka dialog "Quick Book" — pilih tipe (Day Use/Menginap) + **harga custom** (bisa beda dari tarif dasar kamar), langsung tercatat: Day Use → `POST /checkins` (tarif_override), Menginap → `POST /bookings` (tipe menginap, tarif_override) + `PUT /rooms/{id}/status` (tandai kamar terisi seketika, walk-in). Halaman `Bookings.jsx`/`CheckIn.jsx` (route `/bookings`, `/checkin/:roomId`) DIHAPUS total — sudah tidak dipakai. Melihat daftar tamu yang sudah booking sekarang cukup lewat sidebar "Reservasi".
- [x] Fix warna overlay booking di grid kamar: booking tipe **menginap** sekarang biru (#3B82F6, sama seperti status "Menginap"), booking **day_use** tetap coklat (#92400E) — sebelumnya semua booking (apapun tipenya) selalu coklat.
- [x] Fix urutan kamar: `GET /api/rooms` sekarang urut murni numerik 1→18 (`backend/routes/rooms.py`) — sebelumnya dikelompokkan per tipe dulu (Standard lalu Cottage) sehingga urutan tampil jadi 9,10,...18,1,2,...8 karena nomor kamar tidak berurutan per tipe. Nama/nomor kamar tidak diubah, cuma urutan tampil.
- [x] Backend: field `tarif_override` opsional di `CheckinCreate`/`BookingCreate` (`backend/core.py`), dipakai `create_checkin`/`create_booking` untuk terima harga custom dari staf (validasi harus > 0) — `backend/routes/checkins.py`, `backend/routes/bookings.py`.
- [x] Halaman kelola pengguna admin — SUDAH NYATA sejak awal (`Pengguna.jsx` di `/pengguna`, owner-only, CRUD staf sungguhan)
- [x] Halaman profil pengguna + form ubah profil/password — BARU (`frontend/src/pages/Profil.jsx`, route `/profil`, diakses dari klik nama di sidebar). Backend `PUT /api/auth/me` (beda dari `PUT /users/{id}` yang owner-only): user ubah nama/password sendiri, wajib verifikasi password lama — `backend/routes/auth.py`, `backend/core.py` (`MeUpdate`).
- [x] Backend — login/logout/middleware/lihat profil/ubah profil/ubah kata sandi/hapus akun (admin)/daftar pengguna (admin): semua SUDAH NYATA dari batch sebelumnya, diverifikasi ulang end-to-end (curl) 2026-07-11, tidak ada kode baru selain register di atas.

### Laporan & Analitik — backend LENGKAP (2026-07-11)
- [x] Endpoint pendapatan harian, performa saluran (OTA/Website/WhatsApp), tren okupansi — data nyata dari `bookings`/`checkins`, beda dari `/reports/*` (P&L walk-in Fase 1) — `backend/routes/laporan_analitik.py`. Index `bookings.(payment_status,paid_at)` + `bookings.source`.
- [x] Frontend `LaporanAnalitik.jsx` disambungkan penuh (bukan mock lagi). Kosong/nol sampai ada booking online/OTA/WhatsApp yang lunas — ini benar, bukan bug.

### Manajemen Harga (Rates) — backend LENGKAP (2026-07-11)
- [x] Collection `rates` (override harga per tanggal per tipe kamar, index unik `room_type+tanggal`), tarif dasar tetap satu sumber kebenaran di `rooms.tarif`.
- [x] `GET /api/rates/kalender`, `GET /api/rates/tipe-kamar`, `POST /api/rates/update-massal` — `backend/routes/rates.py`.
- [x] Sinkronisasi harga ke saluran — pakai ulang `push_sync_event` (webhook bot WhatsApp) yang sama dengan sinkronisasi ketersediaan, dipanggil tiap update harga massal.
- [x] Frontend `KalenderHarga.jsx` disambungkan penuh (bukan mock lagi).

### Integrasi Pembayaran — backend LENGKAP (2026-07-11)
- [x] `GET /api/payments/log/by-booking/{booking_kode}` — riwayat semua percobaan pembayaran (payment_log) per reservasi, dipakai panel "Riwayat Pembayaran" di `Pembayaran.jsx` (sudah disambungkan, bukan mock lagi untuk panel ini).
- [x] `PUT /api/payments/log/{log_id}/status` — koreksi status transaksi manual oleh staf (mis. cek bukti transfer manual), ikut update `status`/`payment_status` booking terkait dengan pemetaan sama seperti webhook Midtrans, kirim voucher otomatis kalau jadi lunas — disambungkan ke tombol "Ubah Status" di `Pembayaran.jsx`.
- [x] `GET /api/payments/bookings-status` — daftar reservasi dengan status bayar terderivasi (`belum_bayar`/`dp`/`lunas` dari `payment_status`+`amount_due` vs `total`), filter `status_bayar`/`search` — `backend/routes/payments.py`. Belum disambungkan ke UI (tabel utama `Pembayaran.jsx` masih data tiruan, endpoint list payment_log belum ada — tugas menyusul kalau muncul di plan).
- [x] Fix bug: field `metode` sempat "kecuri" dari `CollectBalanceBody` gara-gara class baru ke-insert di tengah — dibetulkan di `backend/core.py`.

### Log Aktivitas (Audit Trail) — SUDAH LENGKAP (diverifikasi 2026-07-11, hampir tanpa kode baru)
- [x] Skema `AuditLog` didokumentasikan di `backend/core.py` (Mongo schemaless, tidak ada migrasi terpisah) — koleksi `audit_log` sudah dipakai luas sejak awal proyek.
- [x] Service AuditLogger — `log_activity()` di `backend/core.py`, dipanggil 50+ tempat lintas modul.
- [x] Integrasi ke modul stok kamar — `backend/routes/rooms.py` (create/update/delete/ubah status/housekeeping/pindah kamar) sudah lengkap.
- [x] Integrasi ke modul reservasi — `backend/routes/bookings.py`, `backend/routes/checkins.py`, `backend/reservation_service.py` (termasuk booking publik & pembatalan mandiri tamu) sudah lengkap.
- [x] `GET /api/audit-log` (`backend/routes/misc.py`) — sudah nyata & sudah disambungkan penuh ke frontend `Audit.jsx` (`/audit`, filter aksi + cari client-side) sejak batch sebelumnya.

**Fase 3 selesai 100% (7/7 task NgodingPakeAI tersisa) — `task next` mengembalikan `done: true`.**

## Fase 2 — AI Reservation Automation & Booking Engine
### Otomasi Email & Pemesanan — SELESAI (backend + frontend nyata, 2026-07-11)
- [x] Shell halaman + tab navigasi
- [x] Backend: koneksi Gmail OAuth (endpoint) + aktivasi kredensial (GOOGLE_CLIENT_ID/SECRET terpasang, service direstart)
- [x] Skema `EmailLog`/`EmailExtractedData` (collection `email_logs`)
- [x] Service pengambilan email Gmail (`gmail/fetch`, refresh token otomatis, deteksi sumber OTA dari domain pengirim)
- [x] Service AI Email Parser sungguhan pakai OpenAI (`OPENAI_API_KEY` diterima & dipasang dari user 2026-07-11) — ekstrak data reservasi dari isi email, model gpt-4o-mini
- [x] Reservation Automation: begitu AI berhasil parse, reservasi OTOMATIS dibuat di Pelangi PMS (source="ota", tipe="menginap") — dikonfirmasi ke user: mode **otomatis penuh**, bukan approval manual. Anti double-booking: kalau tipe kamar OTA belum dipetakan atau tidak ada kamar kosong di rentang tanggalnya, log tetap `Manual_Required` dengan alasan jelas (tidak memaksakan buat reservasi)
- [x] Endpoint GET `/logs` (+ filter status), CRUD `/mapping-rules`, POST `/logs/{id}/proses-manual` (proses manual staf juga lanjut ke Reservation Automation yang sama)
- [x] Frontend disambungkan penuh ke endpoint nyata: Koneksi Gmail (status/connect/disconnect/fetch, redirect OAuth), Log Email Masuk, Aturan Pemetaan AI, Proses Manual — tidak ada lagi data tiruan di halaman ini
- [x] "Uji Aturan Pemetaan" sengaja TETAP client-side (regex jalan di browser) — endpoint backend terpisah tidak perlu, tidak ada state yang disimpan, cuma nambah round-trip percuma
- [x] **Auto-fetch tanpa staf klik + tangani modifikasi/pembatalan (2026-07-12, keputusan bisnis user)**: background loop `background_gmail_fetch_loop` cek Gmail tiap 1 menit selama terhubung (bukan lagi cuma manual lewat tombol "Cek Email Baru"). AI Email Parser sekarang klasifikasi `jenis`: **baru** → alur lama (buat reservasi otomatis); **modifikasi/pembatalan** → **dibatalkan otomatis** (disamakan, sesuai instruksi user), dicocokkan lewat field baru `ota_reservation_no` di booking. Reservasi lama tidak ketemu → `Manual_Required`, tidak menebak. Diverifikasi lewat skrip standalone (bukan instance backend baru), data uji dibersihkan.

### Sinkronisasi Ketersediaan
- [x] Halaman utama + tab Status Sinkronisasi — SEKARANG NYATA (2026-07-11): status per saluran dihitung dari data sungguhan (PMS/Website selalu tersambung karena aplikasi ini sendiri, Gmail dari `integrations`, WhatsApp dari `webhook_config` yang belum dibangun jadi default belum tersambung)
- [x] Indikator status koneksi real-time (live, polling 10s ke endpoint nyata)
- [x] Riwayat Perubahan Stok — SEKARANG NYATA, baca `availability_logs` (Fase 1) + filter tanggal/tipe kamar server-side, `sumber` di-derive dari `bookings.source`
- [x] Pengaturan Sinkronisasi (frekuensi + prioritas saluran) — SEKARANG NYATA, tersimpan di `sync_settings`
- [x] Service penjadwalan sinkronisasi otomatis — background asyncio loop di `server.py`, interval baca ulang `sync_settings.frekuensi_menit` tiap siklus

### Konfigurasi Webhook (WhatsApp Bot) — SEKARANG NYATA (2026-07-11)
- [x] Halaman utama + form endpoint & kredensial — tersimpan di collection `webhook_config` (kredensial milik staf sendiri, provider apa pun: Fonnte/Wablas/Qontak/custom)
- [x] Uji Koneksi — panggilan HTTP sungguhan ke `webhook_url` tersimpan (bukan simulasi), dicatat ke `wa_connection_log`
- [x] Perhalus feedback form (validasi inline, badge dirty, batal perubahan)

### Pesan WhatsApp Otomatis & Pemantauan Status — SEKARANG NYATA (2026-07-11)
- [x] Webhook receiver publik `/api/webhook/whatsapp/incoming` — pesan masuk dijawab AI (OpenAI, konteks ketersediaan kamar real-time dari `rooms`), balasan dikirim via webhook provider yang staf konfigurasi
- [x] Collection `wa_conversations` — satu sumber kebenaran untuk Log Percakapan, Ringkasan, dan Log Pengiriman (Pemantauan Status), sesuai entitas WHATSAPP_LOGS di PRD
- [x] Endpoint stats, log percakapan, log pengiriman (per-arah), ringkasan kegagalan 24 jam, log koneksi, alert kegagalan beruntun, kirim ulang pesan gagal — semua dari data sungguhan (kosong/nol sampai ada trafik WhatsApp nyata, ini benar bukan bug)
- [x] Pengaturan sinkronisasi data ke bot (toggle + frekuensi) tersimpan di `wa_sync_settings`
- [x] Ketiga halaman (`KonfigurasiWebhook.jsx`, `PesanWhatsAppOtomatis.jsx`, `PemantauanStatusWA.jsx`) disambungkan penuh, tidak ada lagi data tiruan

### Integrasi Pembayaran Midtrans
- [x] Halaman utama "Pembayaran" (daftar transaksi, mock) — catatan: checkout tamu sudah nyata di PublicBook.jsx, ini cuma monitoring admin
- [x] Buat Tagihan Baru (simulasi Snap + pilihan metode bayar, mock)
- [x] Penanganan status pembayaran gagal/kedaluwarsa di PublicBook.jsx (nyata, bukan mock)
- [x] Navigasi Daftar Reservasi -> Pembayaran (filter kode otomatis)
- [ ] **Backend (perlu keputusan bisnis, ditunda atas persetujuan user 2026-07-11):** izinkan booking `cancelled` (karena expired/gagal bayar) dibuka lagi untuk retry Snap — perlu re-cek ketersediaan kamar saat retry supaya tidak double-booking. Frontend "Coba Bayar Lagi" sengaja belum dibuat sampai ini selesai. **Dinilai ulang 2026-07-12** (atas permintaan user, "kerjakan jika memang penting"): dicek kodenya, dampaknya cuma UX (tamu isi form ulang) — kamar otomatis lepas lagi & tamu diberi tahu jelas, tidak ada kerugian bisnis/data. Tetap ditunda, prioritas rendah.

### Pesan WhatsApp Otomatis
- [x] Halaman dasbor + tab Ringkasan (mock)
- [x] Tab Pengaturan (sinkronisasi data ke bot + tautan Konfigurasi Webhook)
- [x] Log Percakapan (mock)
- [x] Tab Pemantauan Status diubah jadi tautan ke halaman "Pemantauan Status" tersendiri (lihat bawah)

### Pemetaan Tipe Kamar
- [x] Halaman daftar pemetaan (mock)
- [x] Filter cari/tipe kamar PMS/sumber OTA
- [x] Tombol ubah/hapus + modal konfirmasi
- [x] Form tambah pemetaan baru (dialog dipakai bersama tambah/ubah)
- [x] Tombol Impor dari PMS (simulasi loading + notifikasi)
- [x] Panel Tipe Kamar OTA Belum Dipetakan + tombol Petakan (pre-fill form)

### Permintaan Khusus Extra Bed
- [x] Komponen ExtraBedSelector + halaman pratinjau (mock, belum disambungkan ke checkout nyata)
- [x] Form pemesanan demo dengan total dinamis (tetap demo, bukan form live)
- [x] Info extra bed di detail Daftar Reservasi (mock)
- [x] Info extra bed di halaman voucher/konfirmasi tamu (kondisional, aman)

### Pemantauan Status (WhatsApp)
- [x] Halaman utama (statistik, peringatan, log pengiriman, mock) — gantikan tab placeholder lama di Pesan WhatsApp Otomatis
- [x] Dialog detail pesan + tombol Kirim Ulang (mock)
- [x] Ringkasan Kegagalan + Log Perubahan Status Koneksi (mock)

### Sinkronisasi Data PMS -> WhatsApp Bot
- [x] Halaman Dashboard Sinkronisasi (mock)
- [x] Indikator status sinkronisasi (live)
- [x] Tabel Log Peringatan Gangguan (mock)
- [x] Panel Ketersediaan Kamar Bot vs PMS (mock)
- [x] Panel Referensi Reservasi PMS (mock)

### Detail Voucher Booking
- [x] Info Check-In/Check-Out di halaman voucher tamu (nyata — field sudah ada di API, cuma belum ditampilkan)
- [ ] Sisa task fitur ini (cek `task next`)

### Jenis Reservasi
- [x] Komponen TipeReservasiSelector + halaman pratinjau (mock, belum diintegrasikan ke form tamu)
- [x] Form demo Reservasi Menginap (tanggal/malam/tipe kamar/tamu + total dinamis, mock)
- [x] Form demo Reservasi Day Use (tanggal/jam/tipe kamar/tamu + tarif flat & biaya layanan 3%, mock)
- [x] Notifikasi ketentuan Day Use (durasi 6 jam + overtime, sesuai calc_tagihan nyata)
- [x] Validasi input (tanggal tidak lampau, jumlah tamu minimal 1)
- [x] Aturan jam check-in Day Use per hari (Minggu mulai 12:00, Senin-Sabtu mulai 10:00), mock

### Paket Kamar
- [x] Komponen PaketKamarSelector (dengan/tanpa breakfast per tipe kamar) + halaman pratinjau (mock, belum ada field paket di backend)
- [x] **Opsi sarapan SEKARANG NYATA di booking engine (2026-07-12)**, terpisah dari komponen pratinjau mock di atas. Field `dengan_sarapan` di `PublicBookingCreate`/`BookingCreate` (`backend/core.py`) + `BREAKFAST_PRICE=25000`/malam — dihitung server-side (`backend/routes/public.py`, `backend/routes/bookings.py`). Toggle "Sarapan Pagi" di `PublicBook.jsx` khusus alur Menginap, tampil di breakdown harga, halaman sukses, dan PDF voucher (`email_service.py`).
- [x] **Koreksi 2026-07-12 (sama hari, revisi kedua)**: percobaan pertama di atas salah — sempat menyamakan tarif dasar Day Use dan Menginap lewat satu field `rooms.tarif`, padahal harusnya terpisah. Diperbaiki: `rooms.tarif` = Day Use (Standard Rp120rb/Cottage Rp140rb, dikembalikan ke nilai asli), field baru `rooms.tarif_menginap` = Menginap tanpa sarapan (Standard Rp150rb/Cottage Rp200rb; +sarapan tetap Rp175rb/Rp225rb, tidak berubah). Model `RoomCreate`/`RoomUpdate` (`backend/core.py`), form Kelola Kamar (`frontend/src/pages/Rooms.jsx`, 2 kolom tarif terpisah), seed `server.py`, DB live dimigrasi. Semua titik perhitungan/tampilan harga menginap (`public.py`, `bookings.py`, `otomasi_email.py` fallback OTA, `PublicBook.jsx`, `Dashboard.jsx` Quick Book) disambungkan ke field baru ini. Diverifikasi ulang end-to-end, data uji dihapus.

### Rekomendasi AI Check-in Day Use
- [x] Halaman "Rekomendasi Check-in" — saran jam check-in Day Use berdasarkan jam check-out Menginap malam sebelumnya + jeda bersih-bersih 1 jam, auto-update saat tanggal/tipe kamar berubah, alternatif kamar lain, skenario "penuh" (mock)

### Kebijakan Pembatalan Mandiri — SELESAI, SEKARANG SELF-SERVICE PENUH (2026-07-11)
- [x] Tombol "Batalkan Pesanan" di PublicBook.jsx (nyata) — hitung kebijakan/biaya real
- [x] Timer mundur H-1 (real, ticking) di dialog batalkan
- [x] **Keputusan bisnis dikonfirmasi user (2026-07-11): pembatalan mandiri OTOMATIS PENUH, tanpa approval staf.** Endpoint `POST /api/public/bookings/{id}/batalkan` langsung update status jadi `cancelled` + lepas kamar (log_availability_change) + hitung biaya (sama persis dengan formula H-3/H-1 di frontend). Refund uang (kalau ada) TETAP manual oleh staf — sistem cuma menghitung & mencatat `refund_amount`, tidak transfer sungguhan.
- [x] Notifikasi konfirmasi pembatalan ke tamu via WhatsApp (best-effort, pakai webhook yang sama dengan bot — kalau staf belum konfigurasi webhook, dilewati saja tanpa mengganggu pembatalan)

### Pengiriman Voucher Otomatis
- [x] Halaman admin log pengiriman voucher (mock)
- [x] Notifikasi status kirim voucher ke email di halaman konfirmasi tamu (PublicBook.jsx) — bahasa "akan terkirim" (bukan "sudah terkirim") karena backend pengiriman email sungguhan belum ada

Layer **frontend** Fase 2 selesai 100% (30/30 task NgodingPakeAI, 2026-07-11). Lanjut ke layer **backend** Fase 2 (99 task, dimulai dari Otomasi Email & Pemesanan).

### Backend — Otomasi Email & Pemesanan
- [x] Skema `EmailLog`/`EmailExtractedData` di `core.py` (collection `email_logs`)

### Backend — Pemetaan Tipe Kamar
- [x] Model `RoomMappingCreate`/`RoomMappingUpdate`, collection `room_mappings`
- [x] Endpoint GET `/api/pms-room-types` + POST `/api/pms-room-types/sync` — diambil langsung dari `rooms` (bukan tabel terpisah; Pelangi PMS = aplikasi ini sendiri, jadi selalu live, tidak ada yang bisa basi)
- [x] Endpoint CRUD `/api/mappings` (+ validasi duplikasi sumber+nama OTA)
- [x] Endpoint GET `/api/unmapped-ota-rooms` (dari `email_logs.extracted_data.tipe_kamar` yang belum dipetakan — kosong sampai email parsing sungguhan aktif)
- [x] Frontend `PemetaanTipeKamar.jsx` disambungkan ke endpoint nyata (bukan mock lagi)

### Backend — Sinkronisasi Data PMS -> WhatsApp Bot
- [x] Dashboard status aliran data (ketersediaan/harga selalu "synced" by design — bot baca live, bukan salinan), perbandingan bot vs PMS (selalu cocok, bukti zero-drift), referensi reservasi, log alert — `backend/routes/sinkronisasi_data_pms.py`
- [x] `push_sync_event` di `core.py` — dorong notifikasi ke webhook bot tiap ada perubahan stok (dipanggil dari `log_availability_change`), dengan 1x retry otomatis + log kegagalan
- [x] Endpoint manual resync `POST /sinkronisasi-data-pms/webhook` (retry manual oleh staf)
- [x] Frontend `SinkronisasiDataPMS.jsx` disambungkan penuh

### Backend — Voucher PDF & Log Pengiriman (2026-07-11)
- [x] Generator PDF voucher SUNGGUHAN (reportlab, ditambahkan ke requirements.txt) — `GET /api/public/bookings/{id}/voucher.pdf`, dipakai tombol "Unduh Voucher" di `/book` (ganti dari `window.print()`)
- [x] Skema `EmailSendLog` (collection `email_send_log`) + endpoint `GET /api/pengiriman-voucher/logs` — frontend `PengirimanVoucherOtomatis.jsx` disambungkan

### Backend — Pengiriman Voucher Email SUNGGUHAN via Brevo (2026-07-11)
- [x] Service kirim email (`backend/email_service.py`, `send_voucher_email` + `generate_voucher_pdf` dipindah kesini dari `public.py` supaya dipakai lintas route) — Brevo transactional API, kredensial `BREVO_API_KEY`/`BREVO_FROM_EMAIL`/`BREVO_FROM_NAME` user 2026-07-11, dipasang di `pms-backend.service`. Setiap percobaan (sukses/gagal) selalu dicatat ke `email_send_log`.
- [x] Catatan infra: VPS ini default keluar lewat IPv6 tapi Brevo authorised-IP baru mengizinkan IPv4 — dipaksa `local_address="0.0.0.0"` di httpx supaya tidak tergantung whitelist IPv6.
- [x] Trigger otomatis kirim voucher saat booking jadi lunas — webhook Midtrans (`payments.py`, sekali saja per booking, bukan tiap retry webhook) DAN konfirmasi transfer manual oleh staf (`bookings.py` `mark-paid-manual`)
- [x] Endpoint kirim ulang manual staf — `POST /api/pengiriman-voucher/kirim-ulang/{booking_id}`
- [x] Tes end-to-end: email sungguhan terkirim & diterima (verifikasi manual oleh user), log tes dibersihkan dari DB setelahnya

### Backend — Manajemen Stok Terpusat, Booking Engine, Harga & Kalkulasi, Integrasi Midtrans, Jenis Reservasi/Layanan — SUDAH LENGKAP (diverifikasi 2026-07-11, tanpa kode baru)
- [x] Semua sudah nyata dari batch Fase 1/2 sebelumnya (`availability_logs`, `reservation_service.py`, `payments.py`) — 24 task NgodingPakeAI ditandai selesai setelah verifikasi kode, bukan dikerjakan ulang

**Fase 2 backend selesai 92/97 task** (5 sisanya diblokir kredensial email, lihat di atas).

### Backend — Sinkronisasi Ketersediaan
- [x] Status saluran, riwayat stok, pengaturan, auto-sync scheduler — lihat `backend/routes/sinkronisasi_ketersediaan.py` (semua nyata, sudah live)

### Backend — Integrasi Pembayaran Midtrans — SUDAH LENGKAP SEBELUMNYA (diverifikasi ulang 2026-07-11)
- [x] SDK/env, tabel `payment_log`, Snap token, webhook handler (verifikasi signature), penanganan expired/gagal — semua sudah ada di `backend/routes/payments.py` sejak batch sebelumnya, tidak ada yang perlu ditambah

### Backend — Booking Engine, Harga & Kalkulasi, Jenis Reservasi/Layanan — SUDAH LENGKAP SEBELUMNYA (diverifikasi ulang 2026-07-11)
- [x] room_types (`rooms`), reservations (`bookings`), ketersediaan (`/api/public/availability`), hitung harga & buat reservasi (`reservation_service.create_reservation`, kalkulasi server-side asli — bukan cuma preview client), pengurangan stok (`log_availability_change`), konfirmasi via antarmuka (`SuccessView` + polling) — semua sudah nyata dari batch Fase 1/2 sebelumnya
- [x] Endpoint baru GET `/api/jenis-reservasi` — daftar jenis layanan (Day Use/Menginap) + aturan bisnisnya (durasi, overtime, kebijakan pembatalan), satu sumber kebenaran dipakai kedua nama fitur mirip di plan — `backend/routes/jenis_layanan.py`
- [x] **Koreksi 2026-07-12**: klaim "SUDAH LENGKAP" di atas ternyata cuma benar untuk sisi internal/staf — booking publik (`/book`, `PublicBookingCreate` → `public_create_booking`) sebenarnya **hardcode selalu Day Use** (selalu +6 jam dari check-in, tidak ada field tipe sama sekali), meski `GET /api/jenis-reservasi` sudah lama menyebut Menginap sebagai pilihan. Tamu publik sampai hari ini tidak pernah bisa benar-benar booking menginap sendiri — cuma staf (Dashboard Quick Book) yang bisa. Diperbaiki: `PublicBookingCreate` (`backend/core.py`) tambah `tipe`/`tanggal_checkout`; `public_create_booking` & `public_availability` (`backend/routes/public.py`) sekarang tipe-aware (harga per malam, extra bed per malam untuk menginap — beda dari day use yang flat; anti-overbooking dicek untuk seluruh rentang malam). Frontend `PublicBook.jsx`: toggle Day Use/Menginap + date picker check-out, alamat & kontak WA CS di footer, copy hero/footer ditulis ulang (nuansa Bedugul).

### Backend — Permintaan Khusus Extra Bed — SELESAI, DIINTEGRASIKAN KE FORM BOOKING PUBLIK LIVE (2026-07-11)
- [x] Field `extra_bed_qty` di `PublicBookingCreate` + tersimpan di booking, harga (+Rp 50.000 flat per bed, maks 2) dihitung server-side di `reservation_service.create_reservation`
- [x] Field disertakan di GET booking detail (dipakai halaman konfirmasi/voucher)
- [x] **Perubahan alur booking publik LIVE**: tamu sekarang bisa pilih Extra Bed sendiri di form `/book` (komponen `ExtraBedSelector` yang sama dipakai ulang dari halaman pratinjau, tapi kini benar-benar mengubah harga & tersimpan ke reservasi nyata)

### Backend — Rekomendasi AI Check-in Day Use — SEKARANG NYATA (2026-07-11)
- [x] Endpoint GET `/api/rekomendasi-checkin?tanggal&tipe_kamar` — hitung rekomendasi dari booking Menginap sungguhan yang check-out di tanggal itu + jeda bersih-bersih, filter lewat `check_room_available` asli (anti double-booking), bukan lagi data tiruan
- [x] Frontend `RekomendasiCheckinDayUse.jsx` disambungkan ke endpoint ini

Fase 3 detail: lihat section "Fase 3 — Manajemen Sistem Internal" di atas — sudah selesai 100%.
