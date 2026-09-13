# Pelangi Booking Engine — Brief untuk Google Stitch

> Dokumen ini merangkum FITUR & ALUR booking engine online Pelangi SAAT INI, berbasis kode
> nyata (`frontend/src/pages/PublicBook.jsx` + `backend/routes/public.py` + `backend/routes/tripay.py`).
> Tujuannya: memberi Stitch pemahaman lengkap fungsi yang ada SEBELUM mendesain ulang tampilan.
> Semua fungsi di bawah WAJIB dipertahankan saat redesign — ini bukan wishlist, ini yang sudah live.

---

## Ringkasan (1 paragraf)

Pelangi Booking adalah booking engine online **untuk tamu publik** (tanpa login), berupa SPA React
satu halaman yang di-serve PMS di path `/book/`. Tamu memilih **jenis kunjungan** (Day Use per 6 jam
atau Menginap per malam), tanggal, dan satu atau beberapa kamar dari katalog (Standard / Cottage),
melihat ringkasan harga otomatis (tarif kamar + opsi sarapan + extra bed + service fee 3%), lalu
membayar online lewat **Tripay** (QRIS / Virtual Account / e-wallet / retail) dengan opsi **DP 50%**
atau **bayar penuh**. Setelah bayar, tamu diarahkan ke halaman sukses yang auto-refresh status
pembayaran, menyediakan voucher PDF, konfirmasi WhatsApp, dan pembatalan. Jalur **Menginap** berbeda:
tidak bayar langsung online — tamu diarahkan chat admin via WhatsApp untuk konfirmasi + link bayar.
Engine mendukung **multi-properti** (Pelangi Homestay & Harmoni Hills) via slug URL `/book/<slug>`.

---

## Daftar Screen / Step

Alur inti hanya **2 step dalam 1 halaman** (`BookingForm`) + **1 halaman sukses terpisah** (`SuccessView`),
plus 2 dialog (Batalkan, Coba Bayar Lagi). Ada indikator step 2-titik di atas: "Pilih Kamar" → "Isi Data & Bayar".

### 1. Landing / Step 1 — Pilih Kamar & Tanggal
- **Tujuan**: tamu tentukan jenis kunjungan, tanggal, dan pilih 1+ kamar.
- **Elemen UI**:
  - Header sticky: logo Pelangi + link kecil "Staff Login".
  - Hero: logo besar, judul "Istirahat Sejenak di Sejuknya Bedugul", subjudul.
  - Kartu picker tanggal:
    - Toggle **Jenis Kunjungan**: 2 tombol pill — **Day Use** | **Menginap** (default Day Use).
    - **Tanggal** (`<input type=date>`, min = hari ini): label berubah "Tanggal Kunjungan" (Day Use) / "Tanggal Check-In" (Menginap).
    - **Tanggal Check-Out** (`<input type=date>`) — MUNCUL hanya saat Menginap; min = check-in + 1 hari; auto-geser kalau check-in melewati check-out.
    - Filter tipe kamar: 3 tombol pill — **Semua** | **Standard** | **Cottage**.
    - Baris info "{n} malam · Check-out jam 12:00 siang" (hanya Menginap).
  - **Katalog kamar** (grid kartu per TIPE, bukan per kamar):
    - Foto tipe (aspect 4:3), overlay "Sold Out" bila habis.
    - Badge harga: Day Use → "Rp X / 6 jam" (di atas foto). Menginap → dua tombol harga **Tanpa Sarapan** / **Dengan Sarapan** (per malam) bila properti menyediakan sarapan; kalau tidak (Harmoni) → satu harga /malam tanpa toggle.
    - Nama tipe, ukuran (📐), kapasitas (👥), deskripsi.
    - Chip fasilitas dengan ikon (AC, Wi-Fi, TV LED, Kamar mandi dalam, Air panas, Handuk & toiletries; Cottage +Cottage Style +Area Outdoor).
    - Daftar kamar tersedia sbg tombol pill "Kamar {nomor}" (multi-select, tercentang ✓ bila dipilih); teks "✨ {n} kamar tersedia" atau "Kamar habis di tanggal ini / Coba pilih tanggal lain".
  - **Bar sticky bawah** (muncul saat ≥1 kamar dipilih): "{n} kamar dipilih: 1, 2…" + tombol **Batal** + **Lanjutkan ({n} Kamar)**.
- **Data ditampilkan**: katalog dari `/public/rooms-catalog`, ketersediaan dari `/public/availability` (re-fetch tiap ubah tanggal/tipe/jenis/checkout).
- **Aksi/transisi**: pilih kamar → "Lanjutkan" → Step 2 (scroll ke atas).

### 2. Step 2 — Isi Data Tamu & Bayar (layout 2 kolom: form + ringkasan sticky)
- **Tujuan**: isi identitas tamu, pilih opsi & metode bayar, buat booking + transaksi.
- **Kolom kiri — Form Data Tamu**:
  - Link "← Pilih kamar lain" (balik ke Step 1).
  - **Nama Lengkap** (wajib), **Nomor WhatsApp** (wajib), **Email** (wajib + validasi format regex; catatan "bukti pembayaran & konfirmasi dikirim ke email ini"), **Nomor Identitas KTP/Paspor** (wajib).
  - Grid: **Jumlah Tamu** (number, min 1) + **Kendaraan** (opsional, plat).
  - **Jam Check-In** (`<input type=time>`, default 13:00). Untuk Day Use menampilkan *hint* Scheduling Engine (dari `/public/scheduling/rekomendasi-dayuse`) bila jam mepet booking menginap yang sudah ada di kamar itu — sifatnya INFO, tidak memblok.
  - **Paket Kamar → Sarapan Pagi** toggle (hanya Menginap & properti punya sarapan; "Rp X / malam per kamar").
  - **Permintaan Khusus → Extra Bed** (hanya bila SEMUA kamar terpilih bertipe Cottage; qty 0–max via `ExtraBedSelector`; catatan kapasitas 2 dewasa+1 anak, +extra bed → 3 dewasa+1 anak).
  - **Catatan** (Textarea, opsional).
- **Kolom kanan — Ringkasan (sticky)**:
  - Judul booking (1 kamar "Tipe • Kamar N", atau "{n} Kamar: …").
  - Baris: Check-In (+ Check-Out & Lama Menginap bila Menginap; atau "Jam Check-In (6 jam)" bila Day Use), Tipe.
  - Rincian harga: Tarif Kamar (×malam ×kamar bila relevan), Sarapan (bila ada), Extra Bed (bila ada), **Service Fee (3%)**, **Total**.
  - **Cabang Day Use**: blok Opsi Pembayaran (**DP 50%** "Sisa di lokasi" | **Bayar Penuh** "Tanpa sisa") + blok **Metode Pembayaran** (channel Tripay dikelompokkan per `group`, tiap channel tombol dengan ikon + nama) + tombol **Bayar Sekarang** (disabled sampai metode dipilih).
  - **Cabang Menginap**: TIDAK ada pilih metode/bayar. Blok kuning "chat admin dulu via WhatsApp, kami cek ketersediaan lalu kirim link pembayaran. Perkiraan total: Rp X" + tombol **Chat Admin via WhatsApp** (deep-link wa.me dengan detail booking terisi).
  - Footnote kebijakan pembatalan (refund 100% s/d H-3; H-2 s/d hari-H kena 50%).
- **Footer**: alamat homestay, jam operasional (07.00–22.00 WITA), email CS, link WhatsApp CS (nomor per-properti).
- **Aksi/transisi**:
  - Day Use "Bayar Sekarang" → POST `/public/bookings` → POST `/payments/tripay/create-transaction` → **redirect ke `checkout_url` Tripay** (halaman instruksi bayar ter-hosted, bukan popup).
  - Setelah bayar, Tripay `return_url` mengarahkan balik ke `/book/sukses/{bookingId}`.

### 3. Halaman Sukses — `/book/sukses/:bookingId` (`SuccessView`)
- **Tujuan**: tampilkan status booking & pembayaran, voucher, konfirmasi, pembatalan.
- **Perilaku**: poll `GET /public/bookings/{id}` tiap **5 detik** sampai status final (paid, atau cancelled+expired/failed). Fallback ID dari `localStorage` bila URL tanpa id.
- **State tampilan** (warna & judul berubah):
  - **Booking Berhasil Dibuat** (pending) — blok kuning "Pembayaran Belum Selesai", instruksi selesaikan VA/QRIS, catatan simulator Tripay (sandbox).
  - **DP Diterima** — booking terkonfirmasi dengan DP, sisa dibayar saat check-in.
  - **Pembayaran Diterima** (lunas).
  - **Booking Dibatalkan** (expired/failed) — blok merah "Kamar sudah dilepas kembali" + tombol **Coba Bayar Lagi**.
- **Kartu detail**: Nomor Booking (kode), Nama, Kamar (list bila grup >1 kamar), Check-In, Check-Out, Paket Sarapan (bila ada), Extra Bed (bila ada), Total (gabungan grup), DP Minimum, Status Pembayaran, Sisa Dibayar di Lokasi (bila DP).
- **Aksi/tombol**: **Lihat Voucher Booking** (PDF, saat paid) · **Konfirmasi via WhatsApp** · **Batalkan Pesanan** (dialog) · **Coba Bayar Lagi** (dialog, saat failed) · "Buat booking lain". Halaman print-friendly (kelas `print:`).
- **Layar "Tidak Ditemukan"**: bila id tidak valid → arahkan hubungi CS via WA.

### 4. Dialog — Batalkan Pesanan
- Jelaskan kebijakan pembatalan + status waktu saat ini + biaya (Gratis vs 50%) + countdown menuju batas H-3. **Pembatalan HANYA lewat WhatsApp** (tombol Chat Admin dengan kode booking terisi) — TIDAK ada eksekusi pembatalan mandiri dari UI (jalur `/batalkan` dimatikan di backend by design).

### 5. Dialog — Coba Bayar Lagi (untuk booking auto-cancel karena bayar expired/gagal)
- Pilih channel (select) + opsi DP 50% / Lunas + input **Nomor WhatsApp saat booking** (konfirmasi kepemilikan). Submit → `POST /public/bookings/{id}/retry-bayar` (re-cek ketersediaan kamar, buka ulang booking) → `create-transaction` → redirect `checkout_url`.

---

## Fitur & Aturan Bisnis

- **Dua jenis kunjungan**:
  - **Day Use** — flat per **6 jam**, bayar online langsung (DP/lunas via Tripay).
  - **Menginap** — per **malam** (check-out 12:00), TIDAK bayar online otomatis → diarahkan chat admin WhatsApp untuk konfirmasi ketersediaan + link bayar manual.
- **Multi-kamar dalam 1 transaksi**: tamu bisa pilih beberapa kamar; backend membuat grup (`group_id`) dan menagih **total gabungan dalam 1 transaksi Tripay** (extra bed & sarapan berlaku sama tiap kamar).
- **Opsi pembayaran**: **DP 50%** (sisa dilunasi di lokasi saat check-in) atau **Bayar Penuh**.
- **Service Fee 3%** ditambahkan ke subtotal (tarif kamar + sarapan + extra bed). Nilai `service_fee_pct`, `extra_bed_price` (Rp50.000), `extra_bed_max` (2), `breakfast_price` (Rp25.000) diambil dari `/public/pricing-config` (sumber kebenaran = `core.py`). **Backend menghitung ulang total resmi sendiri** saat create booking — angka di frontend murni untuk tampilan pra-submit.
- **Sarapan**: opsional, per malam per kamar, hanya untuk Menginap & properti yang menyediakan (Pelangi ya, Harmoni tidak).
- **Extra bed**: hanya tipe **Cottage** (backend menolak bila ada kamar non-Cottage), maks 2, kapasitas 2 dewasa+1 anak → +extra bed jadi 3 dewasa+1 anak.
- **Metode bayar** (dari Tripay, dinamis — bukan hardcode): semua channel `active` dari `GET /merchant/payment-channel` Tripay, dikelompokkan per `group` (Virtual Account bank, e-wallet, QRIS, retail/convenience store, dll). Bank/kode spesifik ditentukan akun Tripay — **jangan hardcode daftar bank di UI**.
- **Multi-properti**: slug di URL `/book/<slug>` (mis. `harmoni`) diteruskan sbg param `properti` ke SETIAP call `/public/*`. Tanpa slug = properti default (Pelangi). Nomor WhatsApp CS per-properti (Pelangi `0851-1945-9269`, Harmoni `0851-6894-1258`). Fasilitas per-properti (Harmoni tanpa AC & tanpa sarapan).
- **Kebijakan pembatalan (tunggal, semua channel)**: refund 100% bila > 72 jam (H-7 s/d H-3) sebelum check-in; 50% bila < 72 jam (H-2 s/d hari-H); No Show tanpa refund.
- **Validasi**: nama/HP/identitas/email wajib (email regex); tanggal min hari ini; checkout min check-in+1; jumlah tamu min 1; metode bayar wajib sebelum submit (Day Use); "hari ini" dihitung dari **WITA (UTC+8)**, bukan jam server.
- **Auto-cancel & retry**: booking yang tak dibayar tepat waktu otomatis dibatalkan (kamar dilepas), tamu bisa "Coba Bayar Lagi" (re-cek ketersediaan).
- **Konfirmasi**: voucher PDF + bukti dikirim otomatis ke email; tombol konfirmasi WhatsApp; auto-refresh status via polling + webhook Tripay.

---

## Kontrak Data / API (endpoint yang dipakai frontend)

Base: `${REACT_APP_BACKEND_URL}/api`. Semua endpoint publik **tanpa auth**. Param `properti` (slug) opsional di endpoint `/public/*`.

| Endpoint | Method | Fungsi | Field penting (respons / body) |
|---|---|---|---|
| `/public/pricing-config` | GET | Konstanta harga tampilan | `service_fee_pct`, `extra_bed_price`, `extra_bed_max`, `breakfast_price` |
| `/public/rooms-catalog` | GET | Katalog per tipe kamar | per tipe: `tipe`, `tarif` (Day Use/6jam), `tarif_menginap`, `tarif_menginap_dengan_sarapan`, `ada_sarapan`, `image`, `size`, `capacity`, `description`, `fasilitas[]`, `rooms[]{id,nomor}` |
| `/public/availability` | GET | Kamar tersedia | params: `tanggal`, `tipe?`, `checkout?`, `properti?`. Resp: `{tanggal, tipe, rooms:[{id,nomor,tipe,tarif,tarif_menginap}]}` |
| `/public/scheduling/rekomendasi-dayuse` | GET | Hint bentrok Day Use (info) | params: `room_id`, `jam_mulai` (ISO), `properti?`. Resp: `{dipersingkat, alasan}` |
| `/public/bookings` | POST | Buat booking (1 / banyak kamar) | body `PublicBookingCreate`: `nama_tamu`, `no_hp`, `email`, `no_identitas`, `jumlah_tamu`, `kendaraan`, `room_ids[]` (atau `room_id`), `tanggal`, `jam_checkin`, `catatan`, `extra_bed_qty`, `tipe` (`day_use`\|`menginap`), `tanggal_checkout?`, `dengan_sarapan?`. Resp: booking datar (1 kamar) atau `{group_id, bookings:[…]}` (>1) |
| `/payments/tripay/channels` | GET | Daftar metode bayar aktif | tiap channel: `code`, `name`, `group`, `icon_url`, `active` (raw Tripay) |
| `/payments/tripay/create-transaction` | POST | Buat transaksi + `checkout_url` | body: `booking_id`, `payment_option` (`dp50`\|`full`), `method` (kode channel). Resp: `{checkout_url, …}`. Grup ditagih total gabungan |
| `/public/bookings/{id}` | GET | Status booking (polling 5s) | `kode`, `nama_tamu`, `room_nomor`, `room_tipe`, `jam_mulai`, `jam_selesai`, `dengan_sarapan`, `extra_bed_qty`, `total`, `dp_min`, `sisa_tagihan`, `amount_due`, `payment_status`, `status`, `status_bayar` (`belum_bayar`/`dp`/`lunas`), `email`, `no_hp`, `property_slug`, `group_bookings[]` |
| `/public/bookings/{id}/retry-bayar` | POST | Buka ulang booking gagal bayar | body: `no_hp_konfirmasi` |
| `/public/bookings/{id}/voucher.pdf` | GET | Unduh voucher PDF | (link langsung, saat paid) |

Catatan: `/payments/tripay/callback` (webhook Tripay) & `/public/bookings/{id}/batalkan` ADA di backend
tapi tidak dipanggil dari UI publik (webhook server-to-server; batalkan dimatikan by design → lewat WhatsApp).

---

## Catatan untuk Desainer Stitch

**WAJIB dipertahankan fungsinya (jangan hilang saat redesign):**
1. **Toggle Day Use vs Menginap** dengan alur berbeda: Day Use = bayar online; Menginap = CTA "Chat Admin WhatsApp" (BUKAN tombol bayar). Ini beda mendasar, jangan diseragamkan.
2. **Multi-select kamar** (bisa pilih >1 kamar per tipe) + bar sticky ringkasan pilihan.
3. **Katalog per-tipe** dengan foto, fasilitas berikon, harga kontekstual (Day Use /6jam vs Menginap /malam, dengan/tanpa sarapan).
4. **Ringkasan harga live**: tarif + sarapan + extra bed + **Service Fee 3%** + Total; DP 50% vs Bayar Penuh.
5. **Pemilih metode Tripay dinamis dikelompokkan per group** dengan ikon channel — jangan hardcode daftar bank.
6. **Halaman sukses stateful** (pending / DP / lunas / dibatalkan) dengan **polling 5 detik**, voucher PDF, konfirmasi WA, batalkan, coba-bayar-lagi, dan **layout print-friendly**.
7. **Kebijakan pembatalan** & dialog batal (info + countdown H-3 + arahkan WhatsApp).
8. **Validasi form**: email wajib+valid, nama/HP/identitas wajib, tanggal & jumlah tamu.
9. **Extra bed hanya Cottage**; **sarapan hanya Menginap** & tergantung properti.
10. Elemen `data-testid` di banyak komponen dipakai test Playwright — **pertahankan atribut `data-testid`** agar test tidak pecah (mis. `pb-tanggal`, `pb-submit`, `pb-total`, `pb-method-{code}`, `pb-success-kode`, dll).

**Constraint teknis:**
- **SPA React** (CRA/craco) + **Tailwind** + **shadcn/ui**, ikon **lucide-react**, toast **sonner**. Di-serve PMS di path `/book/`.
- **Multi-properti via slug URL** `/book/:propertySlug` — semua call publik meneruskan param `properti`. Route: `/book`, `/book/:slug`, `/book/sukses/:bookingId`, `/book/:slug/sukses/:bookingId`.
- **Pembayaran = Tripay hosted checkout** (redirect ke `checkout_url`, BUKAN popup/widget inline). Setelah bayar, `return_url` balik ke `/book/sukses/{id}`.
- **Sumber harga tunggal = backend** (`core.py`); frontend hanya menampilkan estimasi, total final dihitung ulang server saat create booking. Jangan duplikasi konstanta harga di desain.
- Zona waktu **WITA (UTC+8)** untuk "hari ini".
- Palet warna eksisting: teal-deep, cream/paper, mustard, ink (Tailwind custom) — Stitch boleh redesign, tapi ini identitas visual saat ini.

**Perlu dikonfirmasi (tidak jelas / tidak tampak dari kode frontend):**
- **Daftar bank/e-wallet/retail spesifik** yang aktif: ditentukan konfigurasi akun Tripay (live vs sandbox), tidak hardcode di kode — perlu cek dashboard Tripay untuk daftar riil yang dilihat tamu.
- **Foto & aset kamar** (`/assets/std-5.webp`, `/assets/cot-2.webp`) di-hardcode per tipe di backend — jumlah/variasi foto sebenarnya per properti perlu dikonfirmasi (saat ini 1 foto per tipe).
- Apakah **Harmoni** benar-benar sudah go-live di booking engine publik atau baru disiapkan (data properti ada, tapi status operasional perlu konfirmasi Agus).
- Isi persis **voucher PDF** & template email konfirmasi (di-render backend) — di luar cakupan file frontend ini.
