# TODO — HotelSync AI (plan `f62b871a-6ff7-47a6-8030-6b82817d22b8`)

Dikelola otomatis (Autonomous Development Mode). Sumber kebenaran urutan kerja tetap
`npx ngodingpakeai task next --plan f62b871a-6ff7-47a6-8030-6b82817d22b8 --json`;
daftar ini ringkasan untuk manusia, bisa sedikit basi — cek CLI kalau ragu.

## Fase 1 — Visibilitas & Pengelolaan Dasar
- [x] Dasbor Ketersediaan
- [x] Daftar Reservasi

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

### Sinkronisasi Ketersediaan
- [x] Halaman utama + tab Status Sinkronisasi — SEKARANG NYATA (2026-07-11): status per saluran dihitung dari data sungguhan (PMS/Website selalu tersambung karena aplikasi ini sendiri, Gmail dari `integrations`, WhatsApp dari `webhook_config` yang belum dibangun jadi default belum tersambung)
- [x] Indikator status koneksi real-time (live, polling 10s ke endpoint nyata)
- [x] Riwayat Perubahan Stok — SEKARANG NYATA, baca `availability_logs` (Fase 1) + filter tanggal/tipe kamar server-side, `sumber` di-derive dari `bookings.source`
- [x] Pengaturan Sinkronisasi (frekuensi + prioritas saluran) — SEKARANG NYATA, tersimpan di `sync_settings`
- [x] Service penjadwalan sinkronisasi otomatis — background asyncio loop di `server.py`, interval baca ulang `sync_settings.frekuensi_menit` tiap siklus

### Konfigurasi Webhook (WhatsApp Bot)
- [x] Halaman utama + form endpoint & kredensial (mock)
- [x] Uji Koneksi (mock)
- [x] Perhalus feedback form (validasi inline, badge dirty, batal perubahan)

### Integrasi Pembayaran Midtrans
- [x] Halaman utama "Pembayaran" (daftar transaksi, mock) — catatan: checkout tamu sudah nyata di PublicBook.jsx, ini cuma monitoring admin
- [x] Buat Tagihan Baru (simulasi Snap + pilihan metode bayar, mock)
- [x] Penanganan status pembayaran gagal/kedaluwarsa di PublicBook.jsx (nyata, bukan mock)
- [x] Navigasi Daftar Reservasi -> Pembayaran (filter kode otomatis)
- [ ] **Backend (perlu keputusan bisnis, ditunda atas persetujuan user 2026-07-11):** izinkan booking `cancelled` (karena expired/gagal bayar) dibuka lagi untuk retry Snap — perlu re-cek ketersediaan kamar saat retry supaya tidak double-booking. Frontend "Coba Bayar Lagi" sengaja belum dibuat sampai ini selesai.

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

### Rekomendasi AI Check-in Day Use
- [x] Halaman "Rekomendasi Check-in" — saran jam check-in Day Use berdasarkan jam check-out Menginap malam sebelumnya + jeda bersih-bersih 1 jam, auto-update saat tanggal/tipe kamar berubah, alternatif kamar lain, skenario "penuh" (mock)

### Kebijakan Pembatalan Mandiri
- [x] Tombol "Batalkan Pesanan" di PublicBook.jsx (nyata, bukan mock) — hitung kebijakan/biaya real, aksi = ajukan permintaan (bukan instan)
- [x] Timer mundur H-1 (real, ticking) di dialog batalkan
- [ ] Sisa task fitur ini (cek `task next`)
- [ ] **Backend (perlu keputusan bisnis kalau mau full self-service):** endpoint pembatalan mandiri sungguhan (bukan cuma "ajukan permintaan") — perlu tentukan siapa yang approve, apakah otomatis refund, dst.

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

### Backend — Sinkronisasi Ketersediaan
- [x] Status saluran, riwayat stok, pengaturan, auto-sync scheduler — lihat `backend/routes/sinkronisasi_ketersediaan.py` (semua nyata, sudah live)

### Backend — Integrasi Pembayaran Midtrans — SUDAH LENGKAP SEBELUMNYA (diverifikasi ulang 2026-07-11)
- [x] SDK/env, tabel `payment_log`, Snap token, webhook handler (verifikasi signature), penanganan expired/gagal — semua sudah ada di `backend/routes/payments.py` sejak batch sebelumnya, tidak ada yang perlu ditambah

### Backend — Booking Engine, Harga & Kalkulasi, Jenis Reservasi/Layanan — SUDAH LENGKAP SEBELUMNYA (diverifikasi ulang 2026-07-11)
- [x] room_types (`rooms`), reservations (`bookings`), ketersediaan (`/api/public/availability`), hitung harga & buat reservasi (`reservation_service.create_reservation`, kalkulasi server-side asli — bukan cuma preview client), pengurangan stok (`log_availability_change`), konfirmasi via antarmuka (`SuccessView` + polling) — semua sudah nyata dari batch Fase 1/2 sebelumnya
- [x] Endpoint baru GET `/api/jenis-reservasi` — daftar jenis layanan (Day Use/Menginap) + aturan bisnisnya (durasi, overtime, kebijakan pembatalan), satu sumber kebenaran dipakai kedua nama fitur mirip di plan — `backend/routes/jenis_layanan.py`

### Backend — Permintaan Khusus Extra Bed — SELESAI, DIINTEGRASIKAN KE FORM BOOKING PUBLIK LIVE (2026-07-11)
- [x] Field `extra_bed_qty` di `PublicBookingCreate` + tersimpan di booking, harga (+Rp 50.000 flat per bed, maks 2) dihitung server-side di `reservation_service.create_reservation`
- [x] Field disertakan di GET booking detail (dipakai halaman konfirmasi/voucher)
- [x] **Perubahan alur booking publik LIVE**: tamu sekarang bisa pilih Extra Bed sendiri di form `/book` (komponen `ExtraBedSelector` yang sama dipakai ulang dari halaman pratinjau, tapi kini benar-benar mengubah harga & tersimpan ke reservasi nyata)

### Backend — Rekomendasi AI Check-in Day Use — SEKARANG NYATA (2026-07-11)
- [x] Endpoint GET `/api/rekomendasi-checkin?tanggal&tipe_kamar` — hitung rekomendasi dari booking Menginap sungguhan yang check-out di tanggal itu + jeda bersih-bersih, filter lewat `check_room_available` asli (anti double-booking), bukan lagi data tiruan
- [x] Frontend `RekomendasiCheckinDayUse.jsx` disambungkan ke endpoint ini

## Fase 3
- [ ] Belum dibaca detail PRD-nya — cek `plan get` saat fase 2 selesai.
