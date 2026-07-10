# Changelog

Semua perubahan penting pada proyek Pelangi PMS (HotelSync AI) dicatat di sini.
Format longgar mengikuti [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Backend: endpoint koneksi Gmail OAuth (`/api/otomasi-email/gmail/connect`, `/callback`, `/status`, `/disconnect`) — `backend/routes/otomasi_email.py`, koleksi Mongo baru `integrations`.
- Frontend: dialog detail log email (data hasil ekstraksi AI / alasan gagal parsing) di tab "Log Email Masuk" halaman Otomasi Email & Pemesanan — `frontend/src/pages/OtomasiEmail.jsx`.
- Frontend: halaman "Otomasi Email & Pemesanan" (shell + tab navigasi, koneksi Gmail mock, log email mock) — `frontend/src/pages/OtomasiEmail.jsx`, route `/otomasi-email`.

### Notes
- Integrasi Gmail OAuth backend belum bisa dipakai nyata sampai `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` dikonfigurasi di environment `pms-backend.service` (perlu dibuat dulu di Google Cloud Console) — lihat rincian di laporan task terkait.
- Frontend halaman Otomasi Email masih memakai data tiruan (mock) untuk tab Koneksi Gmail & Log Email; belum disambungkan ke endpoint backend di atas.
