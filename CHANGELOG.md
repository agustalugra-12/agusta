# Changelog

Semua perubahan penting pada proyek Pelangi PMS (HotelSync AI) dicatat di sini.
Format longgar mengikuti [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Backend: field `extra_bed_qty` di booking publik (`PublicBookingCreate`, `reservation_service.create_reservation`) — harga +Rp 50.000 flat per bed (maks 2), dihitung server-side. Frontend `/book` sekarang punya selector Extra Bed sungguhan (`ExtraBedSelector` dipakai ulang dari halaman pratinjau) yang mengubah harga & tersimpan ke reservasi nyata — `backend/core.py`, `backend/reservation_service.py`, `backend/routes/public.py`, `frontend/src/pages/PublicBook.jsx`, `frontend/src/pages/PermintaanKhususExtraBed.jsx`.
- Backend: endpoint GET `/api/jenis-reservasi` — daftar jenis layanan (Day Use/Menginap) + aturan bisnisnya — `backend/routes/jenis_layanan.py`.
- Backend: endpoint GET `/api/rekomendasi-checkin` — rekomendasi jam check-in Day Use dari data booking Menginap sungguhan + jeda bersih-bersih, filter anti double-booking — `backend/routes/jenis_layanan.py`. Frontend `RekomendasiCheckinDayUse.jsx` disambungkan (bukan data tiruan lagi).
- Backend: endpoint status/paksa-sinkron/riwayat-stok/pengaturan untuk Sinkronisasi Ketersediaan + service penjadwalan otomatis (background asyncio loop) — `backend/routes/sinkronisasi_ketersediaan.py`, collection baru `sync_channels`/`sync_settings`, dipakai lagi `availability_logs` yang sudah ada.
- Frontend: `SinkronisasiKetersediaan.jsx` disambungkan penuh ke endpoint nyata di atas — tidak ada lagi data tiruan.
- Konfigurasi: aktivasi AI Email Parser — `OPENAI_API_KEY` dipasang di `pms-backend.service`.
- Backend: service pengambilan email Gmail (`POST /api/otomasi-email/gmail/fetch`) dengan refresh token otomatis — `backend/routes/otomasi_email.py`.
- Backend: AI Email Parser sungguhan pakai OpenAI (gpt-4o-mini) untuk ekstrak data reservasi dari isi email OTA — `backend/routes/otomasi_email.py`.
- Backend: Reservation Automation — reservasi otomatis dibuat di Pelangi PMS begitu email berhasil di-parse AI (anti double-booking: fallback ke Manual_Required kalau tipe kamar belum dipetakan atau kamar penuh) — `backend/routes/otomasi_email.py` (`buat_reservasi_otomatis`), pakai `reservation_service.create_reservation` yang sudah ada.
- Backend: endpoint GET `/api/otomasi-email/logs` (+ filter `status`), CRUD `/api/otomasi-email/mapping-rules`, POST `/api/otomasi-email/logs/{id}/proses-manual`.
- Frontend: `OtomasiEmail.jsx` disambungkan penuh ke endpoint nyata (Koneksi Gmail, Log Email Masuk, Aturan Pemetaan AI, Proses Manual) — tidak ada lagi data tiruan.
- Backend: skema `EmailLog`/`EmailExtractedData` (collection `email_logs`) — `backend/core.py`.
- Backend: model `RoomMappingCreate`/`RoomMappingUpdate` + endpoint CRUD `/api/mappings`, GET `/api/pms-room-types`, POST `/api/pms-room-types/sync`, GET `/api/unmapped-ota-rooms` — `backend/routes/pemetaan_tipe_kamar.py`, collection baru `room_mappings`.
- Frontend: `PemetaanTipeKamar.jsx` disambungkan ke endpoint nyata di atas (bukan data tiruan lagi).
- Konfigurasi: aktivasi Gmail OAuth di `pms-backend.service` (GOOGLE_CLIENT_ID/SECRET, GOOGLE_OAUTH_REDIRECT_URI, FRONTEND_URL) — service direstart, siap dipakai tombol "Hubungkan Gmail".
- Frontend: aturan jam check-in Day Use per hari (Minggu mulai 12:00, Senin-Sabtu mulai 10:00), validasi input jam — `frontend/src/pages/JenisReservasi.jsx`.
- Frontend: halaman baru "Paket Kamar" (`/paket-kamar`) — komponen `PaketKamarSelector` (dengan/tanpa breakfast per tipe kamar), data tiruan — `frontend/src/pages/PaketKamar.jsx`.
- Frontend: halaman baru "Rekomendasi Check-in" (`/rekomendasi-checkin`) — logika AI menyarankan jam check-in Day Use dari jam check-out Menginap malam sebelumnya + jeda bersih-bersih, alternatif kamar lain, skenario penuh, data tiruan — `frontend/src/pages/RekomendasiCheckinDayUse.jsx`.
- Frontend: notifikasi status kirim voucher ke email di halaman konfirmasi tamu — `frontend/src/pages/PublicBook.jsx`.
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
- Frontend: tombol ubah/hapus (dengan modal edit & konfirmasi hapus) di tiap baris Pemetaan Tipe Kamar — `frontend/src/pages/PemetaanTipeKamar.jsx`.
- Frontend: tombol "Tambah Pemetaan" di halaman Pemetaan Tipe Kamar (dialog form dipakai bersama untuk tambah & ubah) — `frontend/src/pages/PemetaanTipeKamar.jsx`.
- Frontend: panel "Ketersediaan Kamar: Bot vs PMS" di halaman Sinkronisasi Data PMS — bandingkan jumlah kamar tersedia yang dilihat bot vs data PMS sungguhan per tipe kamar, tandai jika tidak cocok (drift) — `frontend/src/pages/SinkronisasiDataPMS.jsx`.
- Frontend: panel "Referensi Reservasi PMS" di halaman Sinkronisasi Data PMS — daftar reservasi yang jadi rujukan data yang disinkron ke bot + tautan ke Daftar Reservasi — `frontend/src/pages/SinkronisasiDataPMS.jsx`.
- Frontend: tombol "Impor dari PMS" (simulasi loading + notifikasi) di halaman Pemetaan Tipe Kamar — `frontend/src/pages/PemetaanTipeKamar.jsx`.
- Frontend: panel "Tipe Kamar OTA Belum Dipetakan" di halaman Pemetaan Tipe Kamar — tombol "Petakan" per item membuka form tambah pemetaan pre-filled (nama OTA + sumber) — `frontend/src/pages/PemetaanTipeKamar.jsx`.
- Frontend: komponen `ExtraBedSelector` + halaman pratinjau "Permintaan Khusus: Extra Bed", data tiruan — `frontend/src/pages/PermintaanKhususExtraBed.jsx`, route `/extra-bed`. Belum disambungkan ke checkout tamu nyata (backend belum punya field/harga extra bed).
- Frontend: halaman baru "Pemantauan Status" — statistik pengiriman pesan WA, area peringatan gangguan, log pengiriman pesan, data tiruan — `frontend/src/pages/PemantauanStatusWA.jsx`, route `/pemantauan-status-wa`. Tab placeholder "Pemantauan Status" lama di halaman Pesan WhatsApp Otomatis diubah jadi tautan ke halaman baru ini (menghindari duplikasi).
- Frontend: dialog detail pesan + tombol "Kirim Ulang" (mock) untuk pesan berstatus Gagal di halaman Pemantauan Status — `frontend/src/pages/PemantauanStatusWA.jsx`.
- Frontend: form pemesanan demo (tipe kamar + malam + ExtraBedSelector) dengan total harga dinamis di halaman Permintaan Khusus Extra Bed — `frontend/src/pages/PermintaanKhususExtraBed.jsx`. Sengaja tetap demo (bukan form live) karena backend belum punya field/harga extra bed sungguhan.
- Frontend: panel "Ringkasan Kegagalan" (dikelompokkan per alasan) + "Log Perubahan Status Koneksi" (naik-turun webhook) di halaman Pemantauan Status — `frontend/src/pages/PemantauanStatusWA.jsx`.
- Frontend: info "Permintaan Khusus: Extra Bed" di dialog detail Daftar Reservasi (data tiruan, halaman ini memang sudah mock sepenuhnya) — `frontend/src/pages/DaftarReservasi.jsx`.
- Frontend: info extra bed (kondisional, `bk.extra_bed_qty > 0`) di halaman voucher/konfirmasi booking tamu — `frontend/src/pages/PublicBook.jsx`. Live tapi aman: field belum ada di data nyata sehingga tidak pernah tampil sampai backend benar-benar mendukungnya, tidak memengaruhi total harga.

- Frontend: komponen `TipeReservasiSelector` (Day Use/Menginap) + halaman pratinjau "Jenis Reservasi", gaya konsisten dengan form staf Bookings.jsx — `frontend/src/pages/JenisReservasi.jsx`, route `/jenis-reservasi`. Belum diintegrasikan ke form booking tamu (masih selalu day_use).
- Frontend: form demo "Reservasi Menginap" (tanggal check-in, jumlah malam, tipe kamar, jumlah tamu, ringkasan check-in/out + total dinamis) di halaman Jenis Reservasi, muncul saat tipe Menginap dipilih — `frontend/src/pages/JenisReservasi.jsx`.
- Frontend: form demo "Reservasi Day Use" (tanggal/jam check-in, tipe kamar, jumlah tamu, tarif flat + biaya layanan 3% seperti perhitungan nyata) di halaman Jenis Reservasi, muncul saat tipe Day Use dipilih — `frontend/src/pages/JenisReservasi.jsx`.
- Frontend: notifikasi ketentuan Day Use (durasi 6 jam standar + biaya overtime Rp20.000/jam, sama seperti `calc_tagihan` nyata di backend) di form demo Day Use — `frontend/src/pages/JenisReservasi.jsx`.
- Frontend: validasi input (tanggal tidak boleh lampau, jumlah tamu minimal 1) di kedua form demo Jenis Reservasi — `frontend/src/pages/JenisReservasi.jsx`.
- Frontend: halaman admin baru "Log Pengiriman Voucher" — riwayat pengiriman voucher/bukti booking otomatis (email/WhatsApp), cari/filter status, data tiruan — `frontend/src/pages/PengirimanVoucherOtomatis.jsx`, route `/pengiriman-voucher`.

### Fixed
- **Halaman voucher booking (nyata)** — tanggal/jam Check-Out tidak pernah ditampilkan padahal API sudah mengembalikan `jam_selesai`. Ditambahkan baris Check-Out di `PublicBook.jsx`.
- **Kebijakan pembatalan H-3/H-1 (nyata, bukan mock)** — sebelumnya pesan konfirmasi WA & dialog batalkan pesanan selalu bilang H-1 untuk semua booking. Sesuai klarifikasi bisnis: menginap = bebas biaya sampai H-3, day use = H-1. Diperbaiki di `apiClient.js` (buildBookingConfirmationMessage, dipakai Dashboard/Bookings/PublicBook) dan `PublicBook.jsx` (dialog Batalkan Pesanan + timer mundur, dibuat tipe-aware).
- **PublicBook.jsx (halaman checkout tamu, live/nyata)** — sebelumnya booking yang pembayarannya expired/gagal (status `cancelled`) tidak menampilkan penjelasan apa pun ke tamu di halaman hasil. Sekarang ditampilkan status "Booking Dibatalkan" + info bahwa kamar sudah dilepas kembali, tanpa tombol "bayar ulang" palsu (backend belum mendukung retry — lihat catatan di TODO.md). Polling status juga dihentikan begitu status final (paid/cancelled) supaya tidak polling selamanya.

### Notes
- Integrasi Gmail OAuth backend belum bisa dipakai nyata sampai `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` dikonfigurasi di environment `pms-backend.service` (perlu dibuat dulu di Google Cloud Console) — lihat rincian di laporan task terkait.
- Frontend halaman Otomasi Email masih memakai data tiruan (mock) untuk semua tab yang sudah dibangun; belum disambungkan ke endpoint backend di atas.
