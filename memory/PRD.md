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
- **(Feb 2026)** Dashboard filter tanggal booking: date picker di section "Daftar Kamar" — ribbon "Booked" + warna coklat hanya muncul untuk kamar yang punya booking aktif overlap dengan tanggal filter (default hari ini). Booking masa depan tidak mengganggu transaksi hari ini. Tombol "Hari ini" + banner kuning saat filter ≠ hari ini.
- **(Feb 2026)** Override status realtime saat filter ≠ hari ini: kamar `day_use/menginap/perlu_dibersihkan/maintenance` ditampilkan "Kosong" untuk tanggal selain hari ini (status realtime hanya berlaku untuk hari ini).
- **(Feb 2026)** Booking Detail Dialog di Dashboard: klik kartu kamar yang punya booking pada tanggal filter → modal detail tamu + tombol Reschedule (PUT /api/bookings/{id}) & Batalkan (DELETE).
- **(Feb 2026)** Move Room: pindahkan tamu day_use/menginap ke kamar kosong lain via endpoint `POST /api/rooms/{room_id}/move` (kamar lama → `perlu_dibersihkan`; kamar baru ambil alih status + info; untuk day_use, checkin aktif diupdate ke room_id baru). UI di action dialog Dashboard.
- **(Feb 2026)** **Service Fee 3%**: ditambahkan otomatis ke semua check-in/check-out (calc_tagihan menghasilkan subtotal+service_fee+total) dan booking publik. Tampil di CheckOut.jsx + struk + summary Bookings.jsx.
- **(Feb 2026)** **Saran tanggal alternatif**: endpoint `GET /api/bookings/availability` mengembalikan 14 hari slot ketersediaan. UI di Bookings.jsx menampilkan tombol tanggal kosong otomatis saat user dapat error overlap.
- **(Feb 2026)** **Public Booking Page** (`/book`, no login): 2-step flow (pilih kamar → form), katalog Standard & Cottage dengan foto + fasilitas, summary tarif + service fee + DP 50%, mobile-friendly. Endpoint baru tanpa auth: `/api/public/rooms-catalog`, `/api/public/availability`, `/api/public/bookings`, `/api/public/bookings/{bid}`. Status booking baru: `booking_pending`, `booking_paid`, `cancelled`. Source: `online` vs `walk_in`. *(Fase B selesai; Fase C — integrasi Xendit untuk auto-paid — pending API key user.)*
- **(Feb 2026)** **Fase C — Midtrans Snap Integration (Sandbox)**: pembayaran online via QRIS + Bank Transfer/VA. Endpoints: `GET /api/payments/midtrans/config`, `POST /api/payments/midtrans/create-snap-token` (DP 50% atau Full), `POST /api/payments/midtrans/notification` (webhook dengan SHA512 signature verification), `GET /api/payments/midtrans/status/{order_id}`. Collection baru `payment_log` (order_id, transaction_token, gross_amount, transaction_status, payment_type, raw payloads). Status mapping: settlement/capture(accept) → `booking_paid`, expire/cancel/deny → `cancelled`, refund → `payment_status=refunded`. UI di PublicBook.jsx: button DP 50% vs Bayar Penuh, lazy-load Snap.js dari sandbox CDN, popup Midtrans dengan callback onSuccess/onPending/onError/onClose.
- **(Feb 2026)** **Fase D — WA Notifications + Dashboard Widgets + Refund**: (1) Tombol "Kirim Konfirmasi WA" (wa.me click) di Booking Detail Dialog dengan template lengkap (kode/kamar/jam/H-1 policy); tombol "Konfirmasi via WhatsApp" di Public Booking SuccessView. (2) Dashboard widgets baru (7 mini-card): Booking Hari Ini, Pending, Paid, Pendapatan Online Bulan, Total Midtrans trx+sum, Online vs Walk-In Bulan ini — endpoint `GET /api/reports/booking-widgets`. (3) Endpoint `POST /api/bookings/{id}/cancel-with-fee` (H-1 lock + 10% fee otomatis) untuk refund booking_paid.
- **(Feb 2026)** **Tab Pengeluaran di Laporan**: Tab baru `data-testid="tab-expenses"` di `/laporan` menampilkan detail pengeluaran dengan kolom Tanggal, Kategori, Deskripsi, Nominal, Petugas + statistik card (Total Pengeluaran, Jumlah Transaksi, breakdown per kategori) + Grand Total di footer tabel + Export CSV. Menggunakan endpoint `GET /api/expenses?from_date&to_date` yang sudah ada. Filter Date Range mengalir dari state parent. Backend tests 10/10 PASS (iter23), UI verified via screenshot.

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
