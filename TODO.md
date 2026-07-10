# TODO — HotelSync AI (plan `f62b871a-6ff7-47a6-8030-6b82817d22b8`)

Dikelola otomatis (Autonomous Development Mode). Sumber kebenaran urutan kerja tetap
`npx ngodingpakeai task next --plan f62b871a-6ff7-47a6-8030-6b82817d22b8 --json`;
daftar ini ringkasan untuk manusia, bisa sedikit basi — cek CLI kalau ragu.

## Fase 1 — Visibilitas & Pengelolaan Dasar
- [x] Dasbor Ketersediaan
- [x] Daftar Reservasi

## Fase 2 — AI Reservation Automation & Booking Engine
### Otomasi Email & Pemesanan
- [x] Shell halaman + tab navigasi (mock)
- [x] Detail log email (mock)
- [ ] Sisa tab "Log Email Masuk" (jika ada task lanjutan dari `task next`)
- [x] Aturan Pemetaan AI (mock)
- [x] Form uji aturan pemetaan (mock, regex fungsional)
- [x] Proses Manual Email (mock)
- [x] Backend: koneksi Gmail OAuth (endpoint jadi)
- [ ] Aktivasi: kredensial Google OAuth **sudah diterima dari user (2026-07-11)** tapi belum dipasang — user minta tunda restart service. Saat siap: edit unit `pms-backend.service` (tambah GOOGLE_CLIENT_ID/SECRET, GOOGLE_OAUTH_REDIRECT_URI, FRONTEND_URL), `daemon-reload`, restart. Minta user kirim ulang kredensial saat itu (tidak disimpan di repo).
- [ ] Backend: baca email Gmail asli + AI parser (perlu API key AI — cek kredensial sebelum mulai)
- [ ] Backend: sambungkan frontend (Koneksi Gmail, Log Email) ke endpoint asli

### Sinkronisasi Ketersediaan
- [x] Halaman utama + tab Status Sinkronisasi (mock)
- [x] Indikator status koneksi real-time (live, polling 10s)
- [x] Riwayat Perubahan Stok (mock, + filter tanggal/tipe kamar)
- [x] Pengaturan Sinkronisasi (frekuensi + prioritas saluran, mock)

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

### Kebijakan Pembatalan Mandiri
- [x] Tombol "Batalkan Pesanan" di PublicBook.jsx (nyata, bukan mock) — hitung kebijakan/biaya real, aksi = ajukan permintaan (bukan instan)
- [x] Timer mundur H-1 (real, ticking) di dialog batalkan
- [ ] Sisa task fitur ini (cek `task next`)
- [ ] **Backend (perlu keputusan bisnis kalau mau full self-service):** endpoint pembatalan mandiri sungguhan (bukan cuma "ajukan permintaan") — perlu tentukan siapa yang approve, apakah otomatis refund, dst.

## Fase 3
- [ ] Belum dibaca detail PRD-nya — cek `plan get` saat fase 2 selesai.
