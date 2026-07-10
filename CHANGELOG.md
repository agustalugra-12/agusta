# Changelog

Semua perubahan penting pada proyek Pelangi PMS (HotelSync AI) dicatat di sini.
Format longgar mengikuti [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Backend: endpoint koneksi Gmail OAuth (`/api/otomasi-email/gmail/connect`, `/callback`, `/status`, `/disconnect`) — `backend/routes/otomasi_email.py`, koleksi Mongo baru `integrations`.
- Frontend: dialog detail log email (data hasil ekstraksi AI / alasan gagal parsing) di tab "Log Email Masuk" halaman Otomasi Email & Pemesanan — `frontend/src/pages/OtomasiEmail.jsx`.
- Frontend: halaman "Otomasi Email & Pemesanan" (shell + tab navigasi, koneksi Gmail mock, log email mock) — `frontend/src/pages/OtomasiEmail.jsx`, route `/otomasi-email`.
- Frontend: tab "Aturan Pemetaan AI" — tabel aturan ekstraksi (sumber OTA, field, pola/kata kunci) + tambah/ubah/hapus/toggle aktif, data tiruan — `frontend/src/pages/OtomasiEmail.jsx`.
- Frontend: panel "Uji Aturan dengan Contoh Email" — jalankan regex aturan aktif terhadap contoh isi email yang ditempel staff (fungsional, bukan hasil acak) — `frontend/src/pages/OtomasiEmail.jsx`.
- Frontend: tab "Proses Manual" — daftar email berstatus Manual_Required/Failed + form isi data reservasi manual yang mengubah status email jadi Parsed_Success, data bersama (shared state) dengan tab Log Email Masuk — `frontend/src/pages/OtomasiEmail.jsx`.
- Frontend: halaman baru "Sinkronisasi Ketersediaan" — tab Status Sinkronisasi (status per saluran: Pelangi PMS, Website, Email OTA, WhatsApp Bot + tombol Paksa Sinkronisasi), data tiruan — `frontend/src/pages/SinkronisasiKetersediaan.jsx`, route `/sinkronisasi-ketersediaan`.
- Frontend: indikator "Live" (titik berdenyut + jam berjalan sejak cek terakhir, polling berkala 10 detik) di tab Status Sinkronisasi — `frontend/src/pages/SinkronisasiKetersediaan.jsx`.
- Frontend: tab "Riwayat Perubahan Stok" — tabel log pergerakan stok per kamar (waktu, perubahan +/-, alasan, sumber saluran), data tiruan — `frontend/src/pages/SinkronisasiKetersediaan.jsx`.
- Frontend: filter rentang tanggal + tipe kamar untuk tabel Riwayat Perubahan Stok — `frontend/src/pages/SinkronisasiKetersediaan.jsx`.

### Notes
- Integrasi Gmail OAuth backend belum bisa dipakai nyata sampai `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` dikonfigurasi di environment `pms-backend.service` (perlu dibuat dulu di Google Cloud Console) — lihat rincian di laporan task terkait.
- Frontend halaman Otomasi Email masih memakai data tiruan (mock) untuk semua tab yang sudah dibangun; belum disambungkan ke endpoint backend di atas.
