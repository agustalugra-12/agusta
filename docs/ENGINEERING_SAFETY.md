# Engineering Safety — Anti-Bug Development System

**Cakupan**: 3 sistem terhubung milik Agus — Pelangi PMS (`/root/agusta`, hub/sumber
kebenaran booking+tamu+uang), AI Chat/WhatsApp Bot (`/root/ai-chat-bot`, satu-satunya
jalur tamu masuk ke PMS), AI Content/KontenPilot (`/root/kontenpilot-ai`, sistem terpisah,
tidak terhubung ke 2 sistem lain — konfirmasi: zero referensi Tripay, tidak ada jalur data
tamu masuk ke sini).

**Kenapa dokumen ini ada**: pola kerja lama — bug ditemukan → diperbaiki → bug lain
muncul — sudah cukup sering terjadi (lihat riwayat commit). Dokumen ini bukan proses
birokrasi baru, tapi kodifikasi dari pola yang SUDAH terbukti berhasil malam ini
(2026-08-14): 3 bug idempotency nyata ditemukan+diperbaiki di PMS/AI Chat dengan pola yang
identik, lalu audit lanjutan (dokumen ini sendiri) menemukan versi "belum diperbaiki" dari
pola yang sama di 12 titik lain lintas 3 sistem — SEBELUM jadi insiden nyata. Itulah yang
dokumen ini coba jaga supaya rutin terjadi, bukan sekali saja.

**Sumber**: disintesis dari 3 audit menyeluruh (arsitektur, database, deployment, test
coverage, critical flows, regression-prone points, integrasi eksternal) per sistem,
2026-08-14. Raw audit tersimpan di `docs/_audit_<sistem>_raw.md` masing-masing repo
(working artifact, bukan bagian resmi dokumen ini — evidence lengkap file:line ada di
sana kalau butuh detail lebih dalam dari ringkasan di bawah).

---

## Alur Wajib untuk Setiap Perubahan

```
CHANGE → IMPACT ANALYSIS → BUG HUNT (cari pola sama) → IMPLEMENTATION
       → UNIT TEST → INTEGRATION TEST → REGRESSION TEST → SECURITY REVIEW
       → CODE REVIEW → DEPLOY → POST-DEPLOY HEALTH CHECK
```

Poin paling penting dari malam ini: **BUG HUNT bukan langkah opsional**. Bug idempotency
booking-request ditemukan lewat 1 laporan tamu nyata — tapi begitu polanya dikenali (retry
pada timeout + endpoint tanpa dedup), audit lanjutan ke fungsi-fungsi SEJENIS di file yang
SAMA menemukan 3 lagi (`ganti-metode-pembayaran`, `tiket`, `emit-incident`), lalu audit
cross-system menemukan 2 lagi di sistem tetangga (`_pms_ajukan_pembatalan` di ai-chat-bot,
dan pola berbeda tapi bentuk sama di `/send-document`). **1 bug yang dilaporkan jadi 6+
titik yang diperbaiki** — itu bedanya "tambal 1 lubang" vs "cari semua lubang berbentuk
sama".

---

## Aturan

### Perubahan & Produksi
1. **Jangan mengubah production secara langsung tanpa memahami impact.** Baca dulu
   critical flow yang tersentuh (lihat peta di bawah) sebelum edit — bukan sekadar baca
   fungsi yang error, tapi baca ALUR yang memanggilnya dan yang dipanggilnya.
2. **Jangan menghapus behavior existing tanpa alasan.** Kalau perilaku lama sengaja
   (ada komentar "kenapa"), itu biasanya hasil insiden nyata sebelumnya — cari komentarnya
   dulu sebelum asumsi itu bug.
3. **Setiap bug yang ditemukan dari laporan/insiden nyata harus menghasilkan regression
   test** yang merepro kondisi nyatanya (bukan skenario karangan) — pola yang sudah
   dipakai konsisten malam ini (`test_booking_request_idempotency.py`,
   `test_ganti_metode_pembayaran_idempotency.py`, dst, dan
   `skenario_loop_fallback_terkirim_sekali_saja` di ai-chat-bot).

### API & Kontrak
4. **Setiap perubahan API harus diperiksa terhadap consumer-nya.** PMS's
   `integrasi_ai_bot.py` dikonsumsi SEPENUHNYA oleh ai-chat-bot's `pms_connector.py` —
   ubah satu sisi tanpa cek sisi lain adalah sumber bug lintas-repo yang paling mudah
   lolos (2 repo berbeda, tidak ada compile-time check lintas repo).

### Database
5. **Perubahan database harus diperiksa terhadap compatibility.** Semua 3 sistem TIDAK
   punya migration-CI — PMS pakai Mongo tanpa skema kaku (index ditambah manual),
   ai-chat-bot sama, KontenPilot pakai drizzle migration file tapi **harus dijalankan
   manual di tiap server** (KontenPilot production ada di 2 server terpisah, SQLite lokal,
   TIDAK ADA replikasi — drift skema antar server tidak akan error keras, cuma perilaku
   beda diam-diam).

### Booking & Pembayaran
6. **Perubahan booking/payment harus mendapat integration test.** Ini jalur duit
   sungguhan (Tripay). Pola idempotency yang sudah terbukti (lihat Lampiran A) WAJIB
   dipakai utk endpoint tulis baru apa pun di jalur ini — jangan reinvent per endpoint.

### AI Chat
7. **Perubahan AI Chat harus diuji terhadap duplicate request, retry, timeout, dan
   webhook.** `_pms_http_retry` (ai-chat-bot) retry pada `httpx.ReadTimeout` — SETIAP
   endpoint tulis baru yang lewat wrapper ini WAJIB idempotency key, generated SEKALI
   SEBELUM masuk retry closure (lihat pola di Lampiran A). Loop-detector/handover-state
   juga masuk kategori ini — status apa pun yang bisa bikin tamu "diam tanpa balasan
   apa pun" harus punya jalur keluar yang diuji, bukan cuma alert-ke-owner best-effort.

### AI Content
8. **Perubahan AI Content harus diuji terhadap queue, worker, rendering, dan
   publishing.** Tidak ada queue sungguhan di KontenPilot (systemd timer → HTTP lokal) —
   artinya TIDAK ADA proteksi bawaan terhadap 2 proses jalan bersamaan untuk brand/project
   yang sama. Render/publish itu MAHAL (API berbayar + CPU) — dobel-proses = dobel-biaya,
   bukan cuma bug data.

### Keamanan
9. **Setiap perubahan authentication/authorization harus mendapat security review.**
   3 pola auth berbeda di 3 sistem: PMS pakai JWT (staff/owner) + API key (`integrasi_ai_bot`),
   ai-chat-bot pakai Bearer + `secrets.compare_digest`, KontenPilot pakai single-password
   session JWT. **Jangan pernah commit kredensial/nama tamu asli ke git** — insiden nyata
   malam ini: commit berisi nama tamu asli ter-push ke repo GitHub yang publik, harus
   di-private-kan + history di-rewrite. Pakai frasa generik ("tamu asli", "seorang tamu")
   di comment/commit message, SELALU.

### Deploy
10. **Sebelum deploy harus dilakukan test.** PMS: `test_regresi.py` (gate untuk
    reports/checkin/WITA saja — scope sempit, lihat Lampiran B soal apa yang TIDAK
    tercakup). ai-chat-bot: `test_hallucination_guards.py` (95 test, WAJIB sebelum
    restart). KontenPilot: **tidak ada test runner sama sekali** — verifikasi saat ini =
    baca kode + `npx tsx` script ad hoc + render sungguhan berbayar di produksi. Ini gap
    paling serius dari ketiga sistem, lihat Lampiran C.
11. **Setelah deploy harus dilakukan health check.** Pola yang sudah baik: cek commit SHA
    di server match dengan yang di-push, cek service `is-active`, cek log start bersih
    (tanpa error). Untuk KontenPilot yang 2-server: **WAJIB cek kedua server**, drift
    adalah risiko struktural (lihat Lampiran C).
12. **Jika test gagal, jangan deploy.** Pengecualian yang SUDAH dikonfirmasi: skenario
    LIVE ai-chat-bot (panggil OpenAI asli) punya flakiness non-deterministic yang
    dikonfirmasi 2x malam ini — SATU kegagalan skenario LIVE (bukan unit test) harus
    di-re-run SEKALI sebelum dianggap regresi nyata. Unit test yang gagal SELALU dianggap
    nyata (deterministic by construction), tidak pernah di-re-run-lalu-abaikan.
13. **Jika ada perubahan berisiko tinggi, berhenti dan minta approval Agus.** Definisi
    "berisiko tinggi" untuk 3 sistem ini: mengubah alur booking/pembayaran/pembatalan,
    mengubah perilaku/prompt AI yang besar, aksi yang mengirim pesan nyata ke tamu asli,
    operasi git destruktif (force-push/rewrite history — walau malam ini itu perlu &
    disetujui eksplisit untuk insiden PII), mengubah visibility/akses repo, dan **auto-
    publish/deploy production tanpa approval eksplisit** (dilarang default, lihat aturan
    berikut).

### Deployment Otomatis
14. **Jangan menjalankan deployment production otomatis hanya karena test berhasil.**
    PMS sudah auto-deploy via GitHub Actions (test lolos secara manual sebelum push, bukan
    gate CI) — pola ini DITERIMA karena sudah lama berjalan & konsisten. Untuk workflow
    BARU (termasuk kerja Claude Code via skill/agent apa pun): deployment production tetap
    butuh persetujuan eksplisit Agus, kecuali sudah ada pola established sebelumnya
    (auto-deploy PMS) yang sudah disetujui.

---

## Peta Arsitektur (ringkas)

```
TAMU (WhatsApp)
   │
   ▼
AI CHAT BOT (ai-chat-bot) ──── OpenAI (LiteLLM)
   │  Bearer API key             Fonnte / WhatsApp Cloud (in+out)
   ▼
PMS (agusta) ──── Tripay (bayar), Gmail/RedDoorz (OTA sync),
   │               Telegram (owner+staff bot, 2 bot terpisah),
   │               VAPID Push, Claude CLI (auto-fix pipeline)
   ▼
MongoDB (lokal, 1 instance, ~50 collection, multi-property via property_id)


KONTENPILOT (kontenpilot-ai) — TERPISAH TOTAL, tidak terhubung ke PMS/AI Chat
   │
   ├── systemd timer → cron API routes (X-Cron-Key shared secret)
   ├── OpenAI, fal.ai (gambar), Whisper, TTS — semua berbayar
   ├── Buffer / YouTube API / Meta Graph — publish sosial media
   └── SQLite LOKAL per server (2 server terpisah, TANPA sync/replikasi)
```

**Critical flows** (detail lengkap ada di masing-masing `_audit_*_raw.md` §5):
- Tamu → AI Chat → Booking Request → Staff Approve → Tripay → Callback → Konfirmasi
- Tamu → AI Chat → Cancellation Request → Staff Review → (WA konfirmasi cuma saat approve)
- Gmail RedDoorz Email → AI Parse → Booking Matching (3 fungsi fuzzy, riwayat insiden
  terbanyak di seluruh codebase PMS) → Sync atau Booking Baru
- KontenPilot: Cron Trigger → Idea Selection → Footage Match (GPT) → Render (ffmpeg,
  tree-merge) → Gerbang Durasi+QC → Publish-or-Draft → (kalau auto) Buffer/YouTube

---

## Lampiran A — Pola Idempotency Standar (dipakai konsisten malam ini, jadikan default)

Untuk endpoint tulis apa pun yang bisa dipanggil lewat retry (network timeout, klik
dobel, race manual-vs-cron):

1. **Idempotency key** dibuat SEKALI oleh CALLER, SEBELUM masuk retry wrapper apa pun
   (bukan di dalam closure yang di-retry — itu akan generate key baru tiap percobaan,
   menggagalkan tujuannya).
2. Sisi PENERIMA cek dulu (`find_one` by key) sebelum insert — kalau ketemu, KEMBALIKAN
   hasil yang sudah ada, jangan proses ulang side-effect (jangan kirim notifikasi 2x).
3. Backstop race-safe: unique+sparse index di kolom key, tangkap `DuplicateKeyError`
   sebagai lapis kedua (proteksi kalau 2 request identik benar-benar barengan, bukan
   cuma berurutan).
4. Kalau operasinya tidak menyimpan dokumen sendiri (mis. cuma efek samping/notifikasi),
   pakai key yang DETERMINISTIK dari konteks kejadian (bukan random/timestamp — itu
   menggagalkan dedup-nya sendiri), atau dedup window waktu pendek in-memory untuk kasus
   paling ringan.
5. **Endpoint baca (GET) tidak butuh ini** — aman by construction, retry tidak bisa
   menggandakan efek samping yang tidak ada.

---

## Lampiran B — Regression Gate Existing per Sistem (scope, JANGAN diasumsikan lebih luas)

| Sistem | Gate | Scope SEBENARNYA | Dijalankan otomatis? |
|---|---|---|---|
| PMS | `scripts/test_regresi.py` | `reports.py`/`laporan_analitik.py`/checkin-checkout/WITA date helpers SAJA | Tidak — disiplin manual pre-push |
| PMS | 5 script idempotency baru malam ini | 1 endpoint spesifik per script | Tidak — tidak di-wire ke gate manapun |
| ai-chat-bot | `scripts/test_hallucination_guards.py` | 71 unit test + 20 skenario LIVE, cakupan luas perilaku AI | Tidak — disiplin manual pre-restart (WAJIB per CLAUDE.md) |
| KontenPilot | **Tidak ada** | — | — |

**Bahaya paling nyata dari tabel ini**: perubahan di luar scope PMS's `test_regresi.py`
(mis. `otomasi_email.py`, `booking_requests.py`, `payments.py`) TIDAK punya gate otomatis
sama sekali — cuma review manual. Ini persis kenapa temuan #1 di Lampiran D
(`_cocokkan_booking_pending_reddoorz`) bisa lolos tidak terdeteksi sejak fungsi kembarannya
diperbaiki.

---

## Lampiran C — KontenPilot: Gap Test + Risiko Drift 2-Server (paling serius dari 3 sistem)

- **Nol test runner terinstall.** Verifikasi = baca kode + 1 script `tsx` ad hoc (dibuat
  reaktif malam ini setelah insiden) + render sungguhan berbayar di produksi.
- **2 server, SQLite lokal masing-masing, TANPA replikasi/sync.** Config (`.env`),
  kode (commit), dan migrasi database HARUS disamakan manual — tidak ada yang otomatis
  memberi tahu kalau salah satu ketinggalan. Insiden nyaris terjadi malam ini sendiri
  (setup timezone/cron nyaris divergen antar server sebelum ketahuan).
- **Dashboard biaya (`/usage-summary`) TIDAK gabungan** — cek dari 1 server tidak
  menunjukkan pengeluaran di server lain.

**Rekomendasi konkret** (belum dikerjakan, follow-up): (1) tulis 1 checklist manual
"deploy ke 2 server" yang eksplisit menyebutkan tiap file yang perlu disamakan
(`.env` keys mana yang MEMANG boleh beda vs yang harus sama, migrasi, kode); (2)
pertimbangkan endpoint `/api/version` sederhana di tiap server (commit SHA + waktu start)
supaya drift kelihatan dalam 1x cek, bukan cuma dari ingatan.

---

## Lampiran D — Temuan Konkret dari Audit Malam Ini (belum diperbaiki, urutan prioritas)

Ini BUKAN daftar lengkap semua yang mungkin salah — ini yang benar-benar ditemukan lewat
audit evidence-based malam ini. Detail file:line lengkap ada di `_audit_*_raw.md`
masing-masing repo. **Belum ada satu pun dari daftar ini yang diperbaiki** (audit-only
fase pertama, sesuai instruksi Agus) — ini input untuk fase berikutnya.

### 🔴 Tinggi
1. **PMS** — `_cocokkan_booking_pending_reddoorz` (`otomasi_email.py:304`) TIDAK
   difilter `property_id` sama sekali, beda dari 2 fungsi kembarannya di file yang sama
   yang sudah benar. Begitu properti kedua pakai RedDoorz sync, email konfirmasi properti
   A berpotensi salah tandai booking properti B sebagai `synced` (matching nama+tanggal
   longgar, bukan exact).
2. **AI Chat** — `/send-document` (`server.py:4715`) masih pakai lookup percakapan TANPA
   scoping properti — bug yang SAMA PERSIS sudah diperbaiki utk `/send-message` tanggal
   2026-08-01, tapi kembarannya ini terlewat. Dokumen (voucher/slip gaji) bisa terkirim
   lewat channel WA properti yang salah.
3. **KontenPilot** — TIDAK ADA lock (DB maupun aplikasi) yang cegah `cron/auto-generate`,
   `/process`, `/retry`, atau tombol manual "⚡" jalan BARENGAN untuk brand/project yang
   sama. Kalau race terjadi, seluruh pipeline berbayar (OpenAI+fal.ai+TTS+render ffmpeg)
   bisa jalan 2x untuk ide yang sama — dobel biaya nyata. Riwayat sistem ini SENDIRI sudah
   pernah membuktikan skenario pemicunya (`curl` timeout sementara kerja server tetap
   jalan, mendorong percobaan re-trigger manual).

### 🟡 Menengah
4. **PMS** — `checkin_from_booking` (`bookings.py:323`) belum pakai atomic
   `find_one_and_update` yang sudah jadi fix di jalur check-in walk-in kembarannya
   (`checkins.py:82`, fix insiden race-condition 2026-08-05) — celah dobel-checkin TOCTOU
   yang sama berpotensi masih ada di jalur booking→checkin.
5. **PMS** — `deploy.sh` tidak ada gate build/test sebelum restart — build frontend gagal
   tetap bisa lanjut restart backend & reload nginx dengan state parsial.
6. **AI Chat** — `_pms_ajukan_pembatalan` (cancel-request) belum dapat idempotency key
   seperti 3 saudaranya malam ini — dampaknya lebih kecil (non-binding, staf tetap review
   manual) tapi pola risikonya identik.
7. **AI Chat** — webhook WhatsApp Cloud (`server.py:4783-4869`) punya 1 exception handler
   luar yang menelan error TANPA alert ke owner (beda dari jalur Fonnte yang selalu
   alert) — tamu di channel Cloud API bisa diam tanpa balasan DAN tanpa staf tahu.
8. **KontenPilot** — `publishProject()` tidak ada lock per-project — race manual-publish
   vs auto-publish cron bisa memicu publish dobel ke akun sosial media asli.
9. **KontenPilot** — Quality Checker (silence/volume/black-frame thresholds) sudah
   pernah dilonggarkan sekali (2026-08-12) tapi TIDAK ikut divalidasi ulang seperti
   gerbang durasi malam ini — pola risiko sama ("gerbang ketat menolak kerja mahal yang
   sudah selesai"), belum dicek apakah masih relevan.

### 🟢 Rendah (dicatat, bukan urgent)
10. PMS: `payment_log` tanpa index di `order_id` (degradasi bertahap, bukan langsung).
11. PMS: `bookings.kode` tanpa unique DB constraint (proteksi cuma probabilistik).
12. AI Chat: `conversations` collection nol index sama sekali (`session_id`/`whatsapp`).
13. AI Chat: kirim dokumen/template WhatsApp Cloud gagal tanpa alert owner (mirip #7,
    dampak lebih kecil).
14. KontenPilot: fan-in tak terbatas ke 1 panggilan ffmpeg overlay final (dibatasi jumlah
    stat-overlay dari GPT, bukan jumlah klip — bentuk risiko sama dgn bug malam ini,
    variabel beda, belum terbukti jadi masalah nyata).
15. KontenPilot & PMS: pola "timeout keras vs kerja nyata yang lebih lama" sudah terbukti
    2x independen di KontenPilot sendiri (curl 1700s→10700s, ffmpeg 20menit→40menit) —
    worth dicek sistematis, bukan tunggu insiden ke-3.

---

*Dokumen ini hidup — update begitu ada temuan/insiden baru, jangan biarkan basi seperti
`daily_qa_audit.py`'s jadwal di CLAUDE.md ai-chat-bot yang sempat 6x meleset dari kode
sungguhan tanpa ada yang sadar (ditemukan audit ini sendiri).*
