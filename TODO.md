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
- [x] Backend: koneksi Gmail OAuth (endpoint jadi, **butuh kredensial Google Cloud** dari user sebelum bisa dipakai nyata)
- [ ] Backend: baca email Gmail asli + AI parser (perlu API key AI — cek kredensial sebelum mulai)
- [ ] Backend: sambungkan frontend (Koneksi Gmail, Log Email) ke endpoint asli

### Sinkronisasi Ketersediaan
- [x] Halaman utama + tab Status Sinkronisasi (mock)
- [x] Indikator status koneksi real-time (live, polling 10s)
- [x] Riwayat Perubahan Stok (mock)
- [ ] Pengaturan Sinkronisasi

### Belum dimulai
- [ ] Pesan WhatsApp Otomatis (konfigurasi webhook, sinkronisasi data PMS, log percakapan, pemantauan status)
- [ ] Pemetaan Tipe Kamar (daftar pemetaan, tambah pemetaan, impor tipe kamar PMS)

## Fase 3
- [ ] Belum dibaca detail PRD-nya — cek `plan get` saat fase 2 selesai.
