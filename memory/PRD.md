# PRD — Pelangi Homestay Management System

## Original Problem Statement
Aplikasi web + Android PWA "Pelangi Homestay Management System" untuk operasional penginapan day use & kasir. 18 kamar (Standard & Cottage). Tarif dasar 6 jam + overtime Rp 20.000/jam. Role Owner & Resepsionis. Offline-first. (User memilih MongoDB sbg DB utama, custom JWT, object storage Emergent untuk foto identitas, print + PDF untuk struk; Google Sheets sync diundur ke fase 2.)

## User Personas
- **Owner**: akses penuh — kelola pengguna, kamar, produk, lihat semua laporan, hapus data.
- **Resepsionis**: check-in/out, kasir, lihat dashboard, tidak boleh hapus data penting.

## Architecture
- Backend: FastAPI + MongoDB (Motor). Endpoints under `/api`. JWT (PyJWT) + bcrypt.
- Frontend: React 19 + React Router + Shadcn UI + Recharts. PWA manifest.
- Status kamar: kosong, day_use, menginap, perlu_dibersihkan, maintenance. Validasi anti-overbooking di backend.

## Implemented (Feb 2026)
- Auth: login owner/resepsionis (JWT bearer), /me, logout, audit log otomatis.
- Seed: owner/owner123, resepsionis/resep123, 18 kamar (12 Standard 120k + 6 Cottage 140k), 11 produk starter.
- Rooms: list, CRUD owner-only, ubah status (menginap/maintenance/perlu_dibersihkan/kosong), housekeeping-done.
- Check-in: validasi kamar kosong, auto guest upsert, trx_no otomatis, ubah status ke day_use.
- Check-out: kalkulasi overtime otomatis (>6 jam = ceil × 20k), override manual, split payment, validasi pembayaran. Setelah selesai → kamar perlu_dibersihkan, log housekeeping.
- Kasir: produk per kategori (makanan/minuman/laundry), keranjang, diskon, split payment, stok auto-decrement (kecuali laundry), validasi stok.
- Inventory: CRUD produk, alert stok minimal, penyesuaian stok manual + stock_log.
- Pengeluaran: input + kategori, list, hapus (owner only).
- Housekeeping: antrian kamar, log waktu mulai/selesai, riwayat.
- Laporan: summary harian/bulanan, breakdown per kategori, grafik bar (per hari per kategori) + line (laba/pengeluaran), filter rentang tanggal, export CSV.
- Riwayat tamu: search, tombol WhatsApp (wa.me) + telepon, history per tamu.
- Audit log lengkap untuk semua aksi penting.
- Notifikasi dashboard: tamu mendekati 5 jam & overtime.
- PWA: manifest.json, offline banner.
- Booking kamar: CRUD (POST/GET/PUT/DELETE /api/bookings), aktivasi → checkin, anti-overlap.
- **(Feb 2026)** Indikator booking di Dashboard: kartu kamar berwarna coklat (#92400E) dengan ribbon tanggal & badge "Booked" untuk kamar yang punya booking aktif walau status kosong; legend kamar diperbarui.
- **(Feb 2026)** Edit Booking dari halaman /bookings: tombol Pencil pada card booking aktif → modal dengan prefill data → PUT /api/bookings/{id} (overlap-exclude-self, status guard, audit fields).

## Backlog / Next Phase
**P0**
- Upload foto KTP/SIM/Paspor (kamera + galeri) ke Emergent object storage, link tersimpan di checkin.
- Service worker offline-first lengkap (cache shell + IndexedDB queue untuk transaksi offline).
- Cetak PDF struk (saat ini hanya browser print).

**P1**
- Sinkronisasi otomatis ke Google Sheets (USERS, KAMAR, TAMU, CHECKIN, TRANSAKSI, PEMBAYARAN, LAPORAN_HARIAN, LOG_AKTIVITAS, INVENTORY, PENGELUARAN, SHIFT, BACKUP_LOG, HOUSEKEEPING).
- Auto backup harian ke Google Drive (sheets + foto + struk PDF).
- Restore data dari backup.
- Laporan shift (per petugas) — backend log sudah ada, perlu UI.

**P2**
- Kirim bukti transaksi via WhatsApp dengan PDF attachment.
- Cetak struk thermal Bluetooth (perlu native wrapper, contoh Capacitor + plugin).
- Notifikasi push (PWA notification API).

## Test Credentials
Lihat `/app/memory/test_credentials.md`.
