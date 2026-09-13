# PRD Teknis — Update Booking Engine Pelangi (Traveloka-style)

> **Sifat dokumen:** PRD TEKNIS IMPLEMENTASI. Ini **UPDATE** sistem existing, **BUKAN rebuild**.
> **PMS = single source of truth inventory.** Booking Engine = channel dengan alur
> **Read → Hold → Book → Pay → Sync**.
>
> **UI/DESAIN TIDAK DIUBAH.** `PublicBook.jsx` existing dipakai apa adanya. Dokumen ini fokus
> **backend / logic / data**. Field/flow frontend hanya dirujuk, tidak di-redesign.
>
> **Prinsip:** reuse endpoint existing; kalau kurang → **extend**, jangan bikin inventory/sistem kedua.
> Semua temuan di bawah berbasis kode nyata (path + baris disebut). Yang tidak terverifikasi ditandai
> **"perlu dikonfirmasi"**.
>
> Basis kode: `/root/agusta/backend` (FastAPI + motor/MongoDB), frontend `frontend/src/pages/PublicBook.jsx`.
> Tanggal audit: 2026-09-13.

---

## 0. Ringkasan Eksekutif

Booking engine Pelangi **sudah ~80% Traveloka-style**. Yang benar-benar kurang cuma **1 hal besar**
(inventory HOLD ber-TTL) + 3 penyesuaian kecil (availability murni date-based, aturan Day Use vs
night-inventory, hardening reliability). Tidak ada yang perlu di-rebuild.

**Model inventory PMS (terverifikasi):** PMS **TIDAK** memakai grid inventory night-based (tidak ada
collection `inventory`/`stock` per-tanggal). Inventory = **fisik kamar** (`db.rooms`, 1 dokumen per
kamar) + **timestamp-based bookings** (`db.bookings.jam_mulai`/`jam_selesai` UTC). Ketersediaan
dihitung **on-the-fly** dari overlap timestamp (`check_room_available`). Ini bagus: Day Use (jam) dan
Menginap (malam) hidup di model yang SAMA tanpa konflik struktural — tidak perlu 2 inventory.

**Temuan paling kritis:** `booking_pending` adalah status **blocking** di `check_room_available`
(reservation_service.py:96) dan `public_availability` (public.py:256), TAPI **tidak ada satupun
background loop yang membatalkan `booking_pending` yang ditinggalkan tamu** (abandoned sebelum bayar).
Satu-satunya jalur expiry = callback Tripay `EXPIRED` yang baru datang **setelah `expired_time` 24 jam**
(tripay.py:96) — dan itu HANYA kalau tamu benar-benar sudah membuat transaksi Tripay. Kalau tamu bikin
booking lalu tutup tab di layar pilih metode bayar → **kamar terkunci s/d 24 jam** (best case) atau
**selamanya** (kalau transaksi Tripay tak pernah dibuat, callback expire tak pernah datang). Inilah yang
harus diperbaiki oleh HOLD + TTL.

---

## 1. Tabel Endpoint / Fungsi Existing yang Dipakai

| Endpoint / Fungsi | File | Fungsi | Dipakai untuk | Rencana |
|---|---|---|---|---|
| `GET /public/pricing-config` | public.py:53 | `public_pricing_config` | konstanta harga display (fee/extra bed/sarapan) | **REUSE** |
| `GET /public/rooms-catalog` | public.py:68 | `public_rooms_catalog` | katalog per-tipe + tarif | **REUSE** |
| `GET /public/availability` | public.py:137 | `public_availability` | kamar tersedia per tanggal/jam | **EXTEND** (§2, §7) |
| `GET /public/scheduling/rekomendasi-dayuse` | public.py:312 | `public_rekomendasi_dayuse` | hint bentrok Day Use (info) | **REUSE** |
| `POST /public/bookings` | public.py:328 | `public_create_booking` | buat booking (1/grup kamar) | **EXTEND** (§5 hold) |
| `POST /public/bookings/{id}/retry-bayar` | public.py:483 | `public_retry_bayar` | buka ulang booking gagal bayar | **REUSE** (§8) |
| `GET /public/bookings/{id}` | public.py:542 | `public_get_booking` | polling status booking | **EXTEND** (expose `hold_expires_at`) |
| `GET /public/bookings/{id}/voucher.pdf` | public.py:597 | `public_download_voucher_pdf` | voucher PDF | **REUSE** |
| `check_room_available()` | reservation_service.py:62 | hard validator overlap + walk-in + tumpuk | anti-double-book (semua channel) | **REUSE** (inti kebenaran) |
| `create_reservation()` | reservation_service.py:168 | buat dokumen booking + lock + harga | pembuatan booking terpusat | **EXTEND** (set `hold_expires_at`) |
| `room_locks()` | reservation_service.py:37 | asyncio.Lock per-kamar (anti-TOCTOU) | bungkus check→write | **REUSE** |
| `GET /payments/tripay/channels` | tripay.py:17 | `tripay_channels` | daftar metode bayar | **REUSE** |
| `POST /payments/tripay/create-transaction` | tripay.py:38 | `tripay_create_transaction` | buat transaksi + checkout_url | **EXTEND** (perpanjang/clear hold, idempotency) |
| `POST /payments/tripay/callback` | tripay.py:150 | `tripay_callback` | webhook status bayar | **EXTEND** (idempotency eksplisit, §8) |
| `POST /bookings/{id}/ganti-metode-pembayaran` | payments.py:233 | `ganti_metode_pembayaran` | ganti channel (staf/AI) | **REUSE** |
| `background_auto_close_ota_stays_loop()` | bookings.py:901 | tutup booking OTA basi tiap 1 jam | pola loop existing | **REUSE pola** (§5 loop TTL baru) |
| `status_bayar_booking()` | core.py:763 | derive belum_bayar/dp/lunas/refund | konsistensi status bayar | **REUSE** |
| `PublicBookingCreate` | core.py:1106 | model input booking publik | kontrak body | **REUSE** (tak berubah) |

**Konstanta harga (single source, core.py):** `SERVICE_FEE_PCT=0.03` (:83), `EXTRA_BED_PRICE=50000`
(:95), `EXTRA_BED_MAX=2` (:96), `BREAKFAST_PRICE=25000` (:97). Backend **selalu hitung ulang** total
resmi saat create (create_reservation / public_create_booking) — frontend cuma display.

**Background loops existing (server.py:216-261):** sync, gmail-fetch, telegram-report, smart-rule,
ai-grow-cache, collection-required, business-truth, pending-booking-**approval** (booking_requests,
BUKAN payment), stuck-housekeeping, auto-close-ota. → **Tidak ada loop expiry booking_pending payment.**

---

## 2. Model Data Booking Existing (acuan semua perubahan DB)

Dokumen `db.bookings` (dibuat `create_reservation`, reservation_service.py:259-278) — field relevan:

```
id, kode, room_id, room_nomor, room_tipe,
tipe                 # "day_use" | "menginap"
jam_mulai, jam_selesai   # ISO UTC string — INI sumber overlap (timestamp-based, bukan night-grid)
status               # booking_pending | booking_paid | aktif | checked_in | checked_out | cancelled
payment_status       # pending | paid | expired | failed | refunded
subtotal, service_fee, total, dp_min
source               # online | walk_in | ota
invoice_id, payment_id, payment_option, amount_due, amount_paid_min
group_id             # untuk multi-kamar 1 transaksi
property_id
created_at, created_by, updated_at, paid_at, cancelled_at, cancelled_by
sync_status          # RedDoorz: waiting_reddoorz_input | waiting_reddoorz_sync (OTA only)
```

**Status yang BLOCKING ketersediaan** (dipakai konsisten di 2 tempat — reservation_service.py:96 &
public.py:256): `["aktif", "booking_pending", "booking_paid", "checked_in"]`. Plus walk-in via
`db.checkins` status `aktif` (reservation_service.py:127). Ini allow-list, bukan exclude-list.

---

# FASE 1 — Inventory (model, single source of truth)

**Existing:** `db.rooms` (fisik kamar per properti, `scoped(query, property_id)`, core.py:287) +
`db.bookings` timestamp-based. **Tidak ada** collection inventory/stock nightly. `check_room_available`
(reservation_service.py:62) satu-satunya penentu "kamar bebas atau tidak" untuk rentang `[mulai,
selesai)`, dipakai SEMUA channel (publik, staf Quick Book, AI bot, OTA import, retry). Anti-double-book
= `room_locks` (asyncio.Lock per-kamar, reservation_service.py:37) membungkus setiap celah check→write.

**Perubahan DB:** tidak ada di fase ini (model inventory sudah benar dan cukup).

**API:** tidak ada.

**Flow teknis:** dipertahankan. Semua fase lain hanya menambah lapisan di atas model ini, TIDAK
mengganti model.

**Backward-compat:** aman — tidak ada perubahan.

**Catatan arsitektur (penting untuk Agus):** karena inventory = timestamp overlap (bukan grid nightly),
**Day Use dan Menginap tidak pernah butuh 2 inventory terpisah.** Sebuah Day Use 12:00–18:00 dan
Menginap yang check-in 14:00 di kamar sama akan bentrok secara timestamp secara otomatis. Ini yang
membuat `izinkan_tumpuk` (Harmoni, reservation_service.py:60,106) harus jadi override eksplisit — default
selalu tolak overlap.

---

# FASE 2 — Search / Availability (Read)

**Existing:** `GET /public/availability` (public.py:137). Sudah **date-based & terbukti beda per
tanggal**: hitung overlap `[d_start, d_end)` via `_booking_date_range` (public.py:25, hari check-out
tidak dihitung menempati) + filter presisi jam opsional via `check_room_available` kalau `jam_checkin`
diisi (public.py:288-307). Multi-malam pakai param `checkout`. Multi-properti via `properti` slug
(`_resolve_property`, public.py:11). "Hari ini" dihitung dari **WITA UTC+8** (public.py:194), bukan jam
server (server = WIB).

**Masalah yang harus di-fix (GAP #2 — availability belum MURNI date-based):**
public.py:210-213:
```python
if is_today and not jam_checkin:
    q["status"] = "kosong"          # ← gate STATUS FISIK kamar untuk hari ini
else:
    q["status"] = {"$ne": "maintenance"}
```
Untuk **hari ini tanpa jam_checkin**, endpoint masih menyembunyikan kamar yang `status != "kosong"`
(mis. kamar masih `menginap`/`perlu_dibersihkan` karena staf belum proses checkout, padahal secara
booking sudah bebas). Ini **status fisik real-time**, bukan status booking → melanggar prinsip "murni
date-based / booking-based" (§7 PRD produk). Gate ini sengaja konservatif dulu (lihat komentar
public.py:199-209), tapi konsekuensinya: **kamar yang sebenarnya bisa dibooking untuk hari ini bisa
hilang** hanya karena status fisik basi.

**Perubahan DB:** tidak ada.

**API — EXTEND `public_availability`:**
- Hapus cabang `q["status"]="kosong"`; selalu pakai `q["status"]={"$ne":"maintenance"}` (buang gate
  status-fisik, sisakan hanya exclude `maintenance`).
- Kebenaran "kamar bebas hari ini" tetap dijaga oleh: (a) filter overlap booking date-based yang sudah
  ada (public.py:244-274), dan (b) untuk hari ini, `create_reservation` **tetap** menolak booking yang
  `mulai <= now` bila `room.status != "kosong"` (reservation_service.py:217-219) + cek `db.checkins`
  aktif di `check_room_available` (reservation_service.py:127) → jadi walk-in yang belum tercatat di
  bookings TETAP menghalangi saat submit. **Konsekuensi yang harus disadari Agus:** untuk *hari ini*,
  availability bisa **menampilkan** kamar yang status fisiknya basi (mis. belum dibersihkan) sebagai
  "tersedia", tapi submit-nya bisa ditolak oleh guard fisik di atas kalau check-in-nya untuk *jam
  sekarang*. Untuk booking hari ini dengan `jam_checkin` di masa depan (mis. jam 14:00), submit akan
  lolos — dan itu memang perilaku yang diinginkan. → **butuh keputusan Agus** (lihat §9): apakah gate
  fisik hari-ini dibuang sepenuhnya, atau diganti jadi "tampilkan tapi beri badge 'perlu dibersihkan'"
  (data ada: `room.status`).

**Flow teknis:** tidak berubah selain menghapus 1 cabang gate. Filter presisi jam & multi-malam tetap.

**Test case (scripts/test_regresi):**
- `test_availability_today_hides_only_maintenance`: buat 1 kamar `perlu_dibersihkan` tanpa booking
  overlap hari ini → harus **muncul** di availability hari ini (setelah fix); kamar `maintenance` →
  tetap **tidak** muncul.
- `test_availability_future_date_ignores_physical_status`: kamar `menginap` sekarang, booking bebas 3
  hari lagi → muncul (sudah lolos hari ini, jaga regresi).
- `test_availability_dayuse_precise_hour_today`: kamar habis-menginap checkout 12:00, query Day Use
  hari ini jam_checkin=13:00 → muncul (regresi bug Vina, public.py:199).

**Backward-compat:** endpoint internal (`property_id_override`, ai_bot) tak berubah signature. Perilaku
"hari ini" jadi lebih permisif — pastikan guard fisik di `create_reservation` tetap jadi jaring akhir
(sudah ada). Jalankan gerbang regresi (CLAUDE.md) karena menyentuh alur checkin.

---

# FASE 3 — Room Select (katalog + pilih kamar)

**Existing:** `GET /public/rooms-catalog` (public.py:68) grup per tipe (Standard/Cottage), tarif Day
Use + Menginap + Menginap-dengan-sarapan (dihitung dari `BREAKFAST_PRICE`, single source), fasilitas
per-properti (Harmoni tanpa AC/sarapan), foto statis per tipe. Frontend multi-select kamar (`room_ids`).

**Perubahan DB:** tidak ada.

**API:** **REUSE** apa adanya. Tidak ada perubahan diperlukan untuk Traveloka-style (katalog sudah
lengkap). Foto 1/tipe (hardcode META public.py:85) — **perlu dikonfirmasi** apakah Agus mau galeri
multi-foto (di luar scope teknis ini; kalau ya → field `images[]` di `db.rooms`, bukan sekarang).

**Test case:** existing catalog test cukup; tak ada logika baru.

**Backward-compat:** aman.

---

# FASE 4 — Booking Form (isi data tamu)

**Existing:** `PublicBookingCreate` (core.py:1106): nama/no_hp/email(wajib+regex)/no_identitas/
jumlah_tamu/kendaraan/room_id|room_ids/tanggal/jam_checkin/catatan/extra_bed_qty/tipe/tanggal_checkout/
dengan_sarapan. Validasi email + extra-bed-only-Cottage + Harmoni-no-sarapan sudah di
`public_create_booking` (public.py:355-406) dan sebagian diulang di `create_reservation` (defensif).
Menginap publik instan **dimatikan by design** (public.py:348-354) → diarahkan WhatsApp (booking_requests).

**Perubahan DB:** tidak ada.

**API:** **REUSE**. Model & validasi cukup. (Traveloka-style tidak menuntut field tamu tambahan.)

**Test case:** existing.

**Backward-compat:** aman.

---

# FASE 5 — Hold + Payment (INTI PERUBAHAN — GAP #1)

## 5.1 Masalah (terverifikasi)

`public_create_booking` (public.py:328) langsung membuat `booking_pending` **tanpa hold ber-expiry**.
`booking_pending` = **blocking** (reservation_service.py:96, public.py:256). **Tidak ada loop yang
membatalkan pending yang ditinggalkan.** Satu-satunya expiry = Tripay callback `EXPIRED` setelah
`expired_time = now + 24*3600` (tripay.py:96) — **dan hanya jika transaksi Tripay sudah dibuat**. Skenario
bocor nyata:
1. Tamu POST `/public/bookings` → `booking_pending` (kamar terkunci).
2. Tamu **tutup tab** di layar pilih metode (belum POST create-transaction).
3. Tidak ada transaksi Tripay → callback expire **tak pernah datang** → **kamar terkunci selamanya**
   (sampai staf sadar & cancel manual).

Bahkan bila transaksi dibuat, kamar terkunci **24 jam** — terlalu lama untuk booking engine (Traveloka
hold 10–15 menit).

## 5.2 Perubahan DB

Collection **`db.bookings`**, field baru:
- **`hold_expires_at`** : ISO string UTC. Diisi saat booking dibuat via channel online (`source in
  ("online",)`) dengan status `booking_pending` & `payment_status="pending"`. `None`/absent artinya
  "tidak ada hold" (booking staf/OTA/sudah paid — tak pernah di-expire loop).

Tidak ada collection baru. Tidak ada inventory kedua.

## 5.3 API — EXTEND (bukan baru)

**a. `create_reservation()` (reservation_service.py:168) — EXTEND:**
Tambah param `hold_menit: Optional[int] = None`. Kalau diisi & status awal `booking_pending`, set
`doc["hold_expires_at"] = (now_utc + timedelta(minutes=hold_menit)).isoformat()`. Default `None` →
perilaku lama (backward-compat penuh; staf Quick Book / OTA tidak pernah dapat hold).

**b. `public_create_booking()` (public.py:328) — EXTEND:**
Panggil `create_reservation(..., hold_menit=HOLD_TTL_MENIT)`. `HOLD_TTL_MENIT` konstanta baru di
`core.py` (default 15 — **perlu keputusan Agus**, §9). Grup: semua kamar dapat `hold_expires_at` sama.

**c. `tripay_create_transaction()` (tripay.py:38) — EXTEND:**
Saat transaksi berhasil dibuat, **perpanjang** `hold_expires_at` semua booking dalam grup agar
sinkron dengan `expired_time` Tripay (mis. `now + PAY_WINDOW_MENIT`, default samakan dgn expired_time
transaksi atau 60 menit — **perlu keputusan Agus**). Alasan: begitu tamu committed ke pembayaran, hold
15 menit terlalu pendek (tamu perlu waktu transfer VA). Tulis bersama update `invoice_id` yang sudah ada
(tripay.py:114-118).

**d. `tripay_callback()` — saat settlement (tripay.py:279):**
Saat `new_payment=="paid"`, **`$unset hold_expires_at`** (booking sudah paid, tidak boleh kena loop).
Saat expire/deny: booking sudah di-set `cancelled` oleh callback (tripay.py:237-239) — loop tak akan
menyentuhnya (bukan `booking_pending` lagi). Aman.

**e. `public_get_booking()` (public.py:542) — EXTEND:**
Tambahkan `hold_expires_at` ke `_PUBLIC_BOOKING_FIELDS` (public.py:535) agar SuccessView bisa
menampilkan countdown (opsional UI — tidak wajib, frontend existing tetap jalan tanpa ini).

## 5.4 Background loop baru (pola auto_close_ota_stays)

Fungsi `background_expire_holds_loop()` di `routes/bookings.py` (samakan pola dengan
`background_auto_close_ota_stays_loop`, bookings.py:901; register di server.py bersama loop lain
~baris 261). Interval **60 detik** (hold perlu presisi menit, beda dari loop OTA 1 jam).

Logika (per properti aktif):
```
batas = now_utc.isoformat()
stale = db.bookings.find({status:"booking_pending", payment_status:"pending",
                          hold_expires_at:{"$exists":True,"$lt":batas}})
for b in stale:
    async with room_locks(b["room_id"]):
        # re-cek status di dalam lock (hindari balapan dgn callback settlement yg baru masuk)
        cur = db.bookings.find_one({id:b.id})
        if cur.status=="booking_pending" and cur.payment_status=="pending":
            db.bookings.update_one({id:b.id}, {"$set":{status:"cancelled",
                payment_status:"expired", cancelled_at:now, cancelled_by:"system:hold_expired"},
                "$unset":{hold_expires_at:""}})
            log_availability_change(..., "booking_dibatalkan_hold_expired", ...)
```

**Penting — reuse retry:** `cancelled_by="system:hold_expired"` sengaja **berbeda** dari
`system_rollback_group_booking_gagal` tetapi mirip pola auto-cancel gateway. **Namun** `retry-bayar`
(public.py:483) syaratnya `cancelled_by` **kosong** (public.py:502) supaya hanya auto-cancel *gateway*
yang bisa retry. → **Keputusan Agus (§9):** apakah hold-expired boleh di-retry? Jika ya, jangan isi
`cancelled_by` (biar seperti auto-cancel gateway) ATAU longgarkan syarat retry untuk mengizinkan
`system:hold_expired`. Rekomendasi: **izinkan retry** (UX identik dengan "coba bayar lagi" yang sudah
ada) → set `cancelled_by=None` saat hold expired, cukup `payment_status="expired"` sebagai penanda.

## 5.5 Flow teknis end-to-end (Hold→Pay)

1. `POST /public/bookings` → `create_reservation(hold_menit=15)` → `booking_pending` +
   `hold_expires_at=now+15m`. Kamar ter-hold (blocking).
2. Tamu pilih metode → `POST /payments/tripay/create-transaction` → hold diperpanjang ke jendela bayar
   (mis. 60m) + `invoice_id` di-set + `checkout_url`.
3a. Tamu bayar → callback `settlement` → `booking_paid`/`paid` + `$unset hold_expires_at`. Voucher
    terkirim (idempotent via `was_paid`, tripay.py:273,291).
3b. Tamu tak bayar → callback `expire` (≤ expired_time) → `cancelled`/`expired`. Kamar lepas.
3c. Tamu abandon sebelum step 2 → **loop TTL** cancel setelah 15m. Kamar lepas. (Ini yang sekarang bocor.)

## 5.6 Test case (scripts/test_regresi + unit)

- `test_hold_set_on_public_booking`: create booking online → `hold_expires_at` terisi & ~15m ke depan.
- `test_hold_extended_on_tripay_create`: setelah create-transaction, `hold_expires_at` mundur ke jendela bayar.
- `test_hold_cleared_on_paid`: callback settlement → `hold_expires_at` hilang, status `booking_paid`.
- `test_expire_loop_cancels_abandoned`: booking dgn `hold_expires_at` di masa lalu, masih
  `booking_pending` → 1 iterasi loop → `cancelled`/`expired`, kamar bebas lagi (availability
  menampilkannya).
- `test_expire_loop_skips_paid`: booking `booking_paid` (hold sudah unset) → loop tidak menyentuhnya.
- `test_expire_loop_race_settlement`: `hold_expires_at` lewat TAPI status sudah `booking_paid`
  (settlement masuk barusan) → loop tidak cancel (re-cek dalam lock).
- `test_staff_quickbook_no_hold`: `create_reservation` tanpa `hold_menit` → tak ada `hold_expires_at`,
  loop tak pernah cancel.

## 5.7 Backward-compat

- Booking existing (tanpa `hold_expires_at`) → loop query `hold_expires_at:{"$exists":True}` → **tidak
  tersentuh**. Aman total untuk data lama.
- Staf Quick Book / OTA / AI booking_requests → tidak lewat `public_create_booking`, tak dapat hold.
- `check_room_available` tak berubah → anti-double-book tetap.
- Loop dibungkus `room_locks` → tidak balapan dengan create/retry/callback.

---

# FASE 6 — PMS Confirm (Book + Sync ke PMS)

**Existing:** Karena **PMS = booking engine** (satu aplikasi, satu `db.bookings`), tidak ada "sync ke
PMS eksternal" — booking langsung jadi record PMS. Setelah paid, `tripay_callback` (tripay.py:150)
otomatis: set `booking_paid`/`paid`, kirim voucher PDF+email+WA (gabungan per grup, tripay.py:294-318),
`auto_posting` pemasukan ke rekening (sekali per grup, tripay.py:323), push + alert owner Telegram. Staf
lalu `checkin_from_booking` (bookings.py:352) saat tamu datang → `db.checkins` + `room.status="day_use"`.

**Sync OTA (RedDoorz):** **inbound only** — reservasi OTA masuk lewat parsing Gmail
(`otomasi_email.py`, `buat_reservasi_otomatis`), status `sync_status` (`waiting_reddoorz_input` →
`waiting_reddoorz_sync`, bookings.py:687-697). **Tidak ada outbound availability push** ke OTA
(`sinkronisasi_ketersediaan.py` hanya monitor status channel Gmail, bukan push stok). Untuk
Traveloka-style booking engine sendiri, ini **cukup** — engine publik bukan OTA.

**Perubahan DB:** tidak ada.

**API:** **REUSE**. Confirm-after-pay sudah otomatis & lengkap.

**Test case:** existing (webhook settlement → voucher/posting sekali per grup, regresi bug Jadid
tripay.py:243-257).

**Backward-compat:** aman.

**Catatan:** kalau kelak Pelangi mau **push availability ke OTA** (channel manager 2-arah), itu **fitur
baru terpisah**, di luar scope update ini. Jangan bangun sekarang (YAGNI).

---

# FASE 7 — Day Use vs Night-based Inventory

**Existing (terverifikasi):** inventory **timestamp-based**, jadi Day Use (jam) & Menginap (malam)
**sudah satu model**, tidak ada konflik struktural night-grid. Aturan konflik yang sudah dikodekan:

- **Day Use:** `end = start + 6 jam` (public.py:381; `DAYUSE_DURASI_JAM=6`). Checkout Menginap fixed
  12:00 WITA (public.py:373). Presisi jam ditangani `check_room_available`.
- **`_booking_date_range`** (public.py:25): Day Use pagi (mulai < 04:00 UTC / 12:00 WITA) dapat
  memblokir malam sebelumnya kalau `jam_checkin` tak disebut (konservatif) — regresi bug kamar 9
  (public.py:33-41). Kalau `jam_checkin` disebut, serahkan ke presisi jam.
- **Walk-in Day Use** (tak nulis `db.bookings`) di-cover via `db.checkins` aktif di
  `check_room_available` (reservation_service.py:127); estimasi selesai = `jam_selesai` booking asal
  kalau `from_booking_id` ada, else +6 jam (reservation_service.py:146-155).
- **Override tumpuk (Harmoni only):** `izinkan_tumpuk` (reservation_service.py:106,
  `HARMONI_PROPERTY_ID`) — owner boleh sengaja tumpuk Day Use+Menginap 1 kamar. Pelangi selalu tolak.

**Perubahan DB:** tidak ada.

**API:** **REUSE**. Model konflik sudah matang (banyak bug lapangan sudah ditambal di sini). **Tidak
perlu** membangun inventory night-based terpisah — justru akan merusak Day Use.

**Yang perlu diputuskan (§9):** apakah Day Use tetap **time-based** (sekarang) atau Agus mau ubah jadi
"Day Use memblokir 1 malam penuh" (night-based)? **Rekomendasi teknis: JANGAN.** Time-based sudah benar,
lebih fleksibel (2 Day Use/hari/kamar mungkin), dan mengubahnya membuang semua fix presisi jam.

**Test case:** existing regresi (kamar 9, Vina, RedDoorz Budiana, Oka Mahendra) — jangan sampai pecah.

**Backward-compat:** aman (tak ada perubahan).

---

# FASE 8 — Reliability (idempotency, retry, race)

**Sudah ada (terverifikasi):**
- **Anti-double-book race:** `room_locks` asyncio.Lock per-kamar bungkus check→write di
  create_reservation, retry-bayar, checkin (find_one_and_update atomik, checkins.py:32). ⚠️ **Hanya
  aman 1-proses uvicorn** (reservation_service.py:11-26) — kalau scale multi-worker, lock in-process
  tidak cukup, butuh lock DB (Mongo replica set / findOneAndUpdate). **Perlu dikonfirmasi** apakah ada
  rencana multi-instance.
- **Grup all-or-nothing:** rollback booking grup kalau salah satu kamar gagal (public.py:435-452).
- **Webhook downgrade guard:** callback expire/deny yang datang setelah booking sudah `paid` (dari
  transaksi lain) **diabaikan** (`was_paid`, tripay.py:273-278) — regresi bug Kadek Ongki.
- **Voucher/posting sekali per grup:** `newly_paid` + `was_paid` mencegah kirim ganda (tripay.py:258,291).
- **Callback tanpa payment_log:** tebak booking dari `guess_booking_kode_from_order_id`
  (tripay.py:206) — tidak jadi entri yatim.
- **Signature verify:** HMAC-SHA256 `X-Callback-Signature` (tripay.py:170-172).

**Gap reliability yang perlu diperbaiki:**

1. **Idempotency callback belum eksplisit** (EXTEND `tripay_callback`, tripay.py:150). Kalau Tripay
   mengirim callback `PAID` **dua kali**, `was_paid` sudah mencegah voucher/posting ganda (baik). TAPI
   `payment_log` di-update apa adanya tiap kali (tripay.py:199) dan `db.bookings` di-update lagi
   (tripay.py:279) — idempoten secara efek, tapi tidak ada catatan "callback ini sudah diproses".
   **Rekomendasi (lazy):** cukup andalkan `was_paid` guard yang sudah ada + tambah short-circuit: kalau
   `status=="settlement"` dan booking sudah `payment_status=="paid"` → update payment_log lalu
   `return {"success":True}` tanpa proses ulang. Tidak perlu tabel idempotency-key baru (YAGNI).

2. **`create-transaction` tidak idempoten** (tripay.py:38): dua klik cepat "Bayar" → 2 transaksi Tripay
   untuk booking sama (kasus Kadek Ongki lahir dari sini). **Rekomendasi:** kalau booking sudah punya
   `invoice_id` + payment_log `transaction_status=="pending"` yang belum expired, kembalikan
   `checkout_url` existing alih-alih buat transaksi baru. Kecil, mencegah kelas bug ini di sumbernya.
   (Atau minimal: bungkus create-transaction dengan `room_locks`/guard per-booking.)

3. **Retry PMS sync:** tidak relevan (PMS = booking engine, tak ada sync eksternal, §6). Voucher
   send-fail sudah best-effort + log (tripay.py:315) + ada resend manual staf
   (`/pengiriman-voucher/kirim-ulang`, public.py:580). Cukup.

**Perubahan DB:** tidak ada (kecuali opsi payment_log flag kalau Agus mau audit — tidak wajib).

**Test case:**
- `test_callback_paid_twice_idempotent`: 2x callback settlement → voucher/posting sekali, status stabil.
- `test_create_transaction_twice_reuses_pending`: 2x create-transaction booking sama & belum bayar →
  transaksi kedua kembalikan checkout_url existing (setelah fix) atau minimal tak korupsi state.
- `test_expire_after_paid_ignored`: regresi Kadek Ongki (sudah ada, pastikan tetap).

**Backward-compat:** guard bersifat additive; alur sukses existing tak berubah.

---

## 9. Daftar Keputusan yang Perlu Agus Putuskan

| # | Keputusan | Opsi | Rekomendasi teknis |
|---|---|---|---|
| 1 | **TTL hold** berapa menit (sebelum bayar) | 10 / 15 / 20 menit | **15 menit** (standar OTA; cukup isi form+pilih metode) |
| 2 | **Jendela bayar** setelah create-transaction (perpanjangan hold) | samakan expired_time Tripay (24 jam) / 60 menit / 2 jam | **60 menit** untuk hold PMS (kamar cepat lepas kalau VA tak dibayar), TAPI `expired_time` Tripay boleh tetap lebih panjang — atau selaraskan keduanya. Perlu dipilih. |
| 3 | **Hold-expired boleh retry-bayar?** | ya / tidak | **Ya** — set `cancelled_by=None` + `payment_status="expired"` agar masuk jalur `retry-bayar` existing (UX sama dgn gagal-bayar) |
| 4 | **Availability hari-ini: buang gate status-fisik sepenuhnya?** | (a) buang total (murni date-based) / (b) tampilkan + badge "perlu dibersihkan" | **(b)** kalau mau UX aman; **(a)** kalau mau murni Traveloka-style. Guard fisik di create_reservation tetap jadi jaring akhir either way |
| 5 | **Day Use tetap time-based?** | time-based (sekarang) / night-based | **Time-based** — jangan ubah (§7) |
| 6 | **create-transaction dibuat idempoten?** | ya (reuse checkout_url pending) / biarkan | **Ya** — cegah kelas bug Kadek Ongki di sumbernya |
| 7 | **Rencana multi-worker/instance?** | ya / tidak | Kalau **ya**, `room_locks` in-process TIDAK cukup → butuh lock DB (Mongo replica set/findOneAndUpdate) sebelum scale. Perlu dikonfirmasi |

---

## 10. Ringkasan Perubahan (checklist implementasi)

**Wajib (GAP #1 — Hold+TTL):**
- [ ] `core.py`: konstanta `HOLD_TTL_MENIT` (default 15), `PAY_WINDOW_MENIT` (default 60).
- [ ] `reservation_service.py:create_reservation`: param `hold_menit`, set `hold_expires_at`.
- [ ] `public.py:public_create_booking`: passing `hold_menit=HOLD_TTL_MENIT`.
- [ ] `tripay.py:create_transaction`: perpanjang `hold_expires_at`; (opsi) idempotency.
- [ ] `tripay.py:callback`: `$unset hold_expires_at` saat paid; (opsi) short-circuit idempoten.
- [ ] `bookings.py`: `background_expire_holds_loop()` + register di `server.py`.
- [ ] `public.py:public_get_booking` + `_PUBLIC_BOOKING_FIELDS`: expose `hold_expires_at`.

**GAP #2 — Availability murni date-based:**
- [ ] `public.py:public_availability`: hapus cabang `q["status"]="kosong"` (per keputusan #4).

**GAP #3 — Day Use vs night inventory:** tidak ada perubahan kode (model sudah benar; keputusan #5).

**GAP #4 — Reliability:** (opsional per keputusan #6) idempotency create-transaction + short-circuit callback.

**Regresi:** semua di atas menyentuh alur booking/availability → jalankan
`cd backend && venv/bin/python -m scripts.test_regresi` sebelum push (CLAUDE.md gate), tambah skenario
hold/expire di atas SEBELUM implementasi.

---

*Catatan verifikasi audit: dokumen ini READ-ONLY — tidak ada kode/DB yang diubah. Semua path & nomor
baris dari pembacaan file 2026-09-13. Item "perlu dikonfirmasi": galeri multi-foto kamar, rencana
multi-instance, selaras/tidaknya expired_time Tripay dengan hold PMS.*
