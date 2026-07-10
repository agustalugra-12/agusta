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
- Frontend: tab "Pengaturan" — pilih frekuensi sinkronisasi + atur prioritas saluran saat data bentrok (Pelangi PMS terkunci di posisi 1), data tiruan — `frontend/src/pages/SinkronisasiKetersediaan.jsx`.
- Frontend: halaman baru "Konfigurasi Webhook" — form endpoint & kredensial penyedia WhatsApp (Fonnte/Wablas/Qontak/custom), API key tersamar dengan toggle lihat, data tiruan — `frontend/src/pages/KonfigurasiWebhook.jsx`, route `/konfigurasi-webhook`.
- Frontend: halaman baru "Pembayaran" — daftar transaksi Midtrans (cari/filter status, detail dialog), bentuk data mengikuti koleksi `payment_log` yang sudah nyata di backend, data tiruan — `frontend/src/pages/Pembayaran.jsx`, route `/pembayaran`. Tidak mengubah alur checkout tamu (`PublicBook.jsx`) yang sudah berfungsi sungguhan.
- Frontend: halaman baru "Pesan WhatsApp Otomatis" — tab Ringkasan (statistik pesan/reservasi via WA hari ini + aktivitas terbaru), data tiruan — `frontend/src/pages/PesanWhatsAppOtomatis.jsx`, route `/whatsapp-otomatis`. Tab Log Percakapan & Pemantauan Status masih placeholder.
- Frontend: fitur "Buat Tagihan Baru" di halaman Pembayaran — staf pilih booking belum lunas + metode bayar (DP50/Lunas), simulasi Snap menghasilkan link pembayaran tiruan (copy/buka link) — `frontend/src/pages/Pembayaran.jsx`. Melengkapi (bukan menggantikan) alur checkout tamu asli di `PublicBook.jsx`.
- Frontend: tab "Pengaturan" di halaman Pesan WhatsApp Otomatis — toggle data yang disinkron ke bot (ketersediaan/harga/status booking/reservasi baru) + frekuensi, plus tautan ke halaman Konfigurasi Webhook (tidak menduplikasi form kredensialnya) — `frontend/src/pages/PesanWhatsAppOtomatis.jsx`.
- Frontend: tab "Log Percakapan" di halaman Pesan WhatsApp Otomatis — riwayat pesan masuk & balasan AI per tamu, cari nama/nomor, status kirim, data tiruan — `frontend/src/pages/PesanWhatsAppOtomatis.jsx`.

- Frontend: tombol "Uji Koneksi" di halaman Konfigurasi Webhook — simulasi ping ke penyedia WhatsApp, tampilkan hasil (berhasil/gagal + waktu uji) — `frontend/src/pages/KonfigurasiWebhook.jsx`.
- Frontend: tombol "Lihat Pembayaran" di detail Daftar Reservasi — buka halaman Pembayaran dengan filter kode booking otomatis terisi (`?kode=...`) — `frontend/src/pages/DaftarReservasi.jsx`, `frontend/src/pages/Pembayaran.jsx`.
- Frontend: perhalus feedback form Konfigurasi Webhook — badge "perubahan belum disimpan", validasi inline per field saat gagal simpan, tombol "Batalkan Perubahan" — `frontend/src/pages/KonfigurasiWebhook.jsx`.
- Frontend: halaman baru "Pemetaan Tipe Kamar" — tabel korelasi nama tipe kamar OTA (Agoda/Traveloka/Booking.com) dengan tipe kamar Pelangi PMS, data tiruan — `frontend/src/pages/PemetaanTipeKamar.jsx`, route `/pemetaan-tipe-kamar`.
- Frontend: halaman baru "Sinkronisasi Data PMS" — dasbor status aliran data (ketersediaan/harga/status booking/reservasi baru) dari Pelangi PMS ke bot WhatsApp, data tiruan — `frontend/src/pages/SinkronisasiDataPMS.jsx`, route `/sinkronisasi-data-pms`. Beda dari halaman "Sinkronisasi Ketersediaan" (lintas saluran penjualan) dan tab Pengaturan di Pesan WhatsApp Otomatis (pengaturan, bukan monitoring).
- Frontend: tombol "Batalkan Pesanan" (self-service) di halaman detail reservasi tamu (`PublicBook.jsx`, live/nyata) — dialog menampilkan kebijakan & biaya pembatalan yang dihitung sungguhan (H-1, 10%, kebijakan sama seperti pesan konfirmasi WA), aksinya mengajukan permintaan (bukan pembatalan instan palsu) karena backend belum punya endpoint pembatalan mandiri.
- Frontend: filter cari/tipe kamar PMS/sumber OTA di halaman Pemetaan Tipe Kamar — `frontend/src/pages/PemetaanTipeKamar.jsx`.
- Frontend: indikator "Live" di halaman Sinkronisasi Data PMS — `frontend/src/pages/SinkronisasiDataPMS.jsx`.
- Frontend: timer mundur (real, benar-benar berjalan) sampai batas bebas biaya di dialog Batalkan Pesanan tamu — `frontend/src/pages/PublicBook.jsx`.
- Frontend: tabel "Log Peringatan Gangguan" di halaman Sinkronisasi Data PMS — `frontend/src/pages/SinkronisasiDataPMS.jsx`.

### Fixed
- **Kebijakan pembatalan H-3/H-1 (nyata, bukan mock)** — sebelumnya pesan konfirmasi WA & dialog batalkan pesanan selalu bilang H-1 untuk semua booking. Sesuai klarifikasi bisnis: menginap = bebas biaya sampai H-3, day use = H-1. Diperbaiki di `apiClient.js` (buildBookingConfirmationMessage, dipakai Dashboard/Bookings/PublicBook) dan `PublicBook.jsx` (dialog Batalkan Pesanan + timer mundur, dibuat tipe-aware).

### Fixed
- **PublicBook.jsx (halaman checkout tamu, live/nyata)** — sebelumnya booking yang pembayarannya expired/gagal (status `cancelled`) tidak menampilkan penjelasan apa pun ke tamu di halaman hasil. Sekarang ditampilkan status "Booking Dibatalkan" + info bahwa kamar sudah dilepas kembali, tanpa tombol "bayar ulang" palsu (backend belum mendukung retry — lihat catatan di TODO.md). Polling status juga dihentikan begitu status final (paid/cancelled) supaya tidak polling selamanya.

### Notes
- Integrasi Gmail OAuth backend belum bisa dipakai nyata sampai `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` dikonfigurasi di environment `pms-backend.service` (perlu dibuat dulu di Google Cloud Console) — lihat rincian di laporan task terkait.
- Frontend halaman Otomasi Email masih memakai data tiruan (mock) untuk semua tab yang sudah dibangun; belum disambungkan ke endpoint backend di atas.
