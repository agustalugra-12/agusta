# Regression Checklist — Lintas 3 Sistem

Dipakai sebelum menganggap perubahan apa pun "selesai". Tidak semua baris relevan untuk
tiap perubahan — pilih yang relevan dengan area yang disentuh, tapi WAJIB baca semua baris
dulu untuk mutuskan relevan/tidak (bukan skip diam-diam). Detail evidence tiap baris ada di
`ENGINEERING_SAFETY.md` dan `docs/_audit_<sistem>_raw.md`.

## Checklist Inti

- [ ] **API regression** — kalau ubah endpoint PMS yang dipanggil ai-chat-bot
      (`integrasi_ai_bot.py`), cek `pms_connector.py` sisi lain sudah sesuai. Kalau ubah
      response shape apa pun, cari SEMUA caller (grep, bukan asumsi 1 tempat).
- [ ] **Database regression** — index/constraint baru tidak konflik dgn data lama (PMS:
      unique+sparse index harus toleran dokumen lama tanpa field itu). Drizzle migration
      (KontenPilot) sudah dijalankan di **kedua** server, bukan cuma satu.
- [ ] **Authentication** — JWT/API-key/session tetap valid untuk semua role yang
      seharusnya bisa akses, DAN tetap ditolak untuk yang seharusnya tidak.
- [ ] **Authorization** — `require_owner` vs `get_current_user` (PMS), scope
      per-properti (`scoped()`), scope per-bot/per-properti (ai-chat-bot) tidak
      ke-bypass oleh perubahan.
- [ ] **Duplicate request / idempotency** — endpoint tulis apa pun yang lewat retry
      wrapper (`_pms_http_retry`) atau bisa dipanggil ulang (klik dobel, race manual-vs-
      cron) sudah pakai pola Lampiran A `ENGINEERING_SAFETY.md`. Cek SEMUA endpoint
      SEJENIS di file yang sama, bukan cuma yang dilaporkan.
- [ ] **Webhook retry** — Tripay callback, Gmail poll, Fonnte/WA Cloud webhook — pastikan
      pemrosesan ulang event yang sama tidak menghasilkan efek ganda (notif dobel,
      booking dobel, dst).
- [ ] **Payment flow** — kalau tersentuh: create-transaction → callback → booking update
      → voucher → posting kas, ditelusuri end-to-end, bukan cuma titik yang diubah.
- [ ] **Booking flow** — `check_room_available`/room lock tetap dihormati; multi-kamar
      (group) tetap konsisten (voucher/posting sekali per grup, bukan per kamar).
- [ ] **AI Chat flow** — turn processing tetap lewat `_run_chat_turn` (lock per-session);
      state `waiting_admin`/`resolution` apa pun yang baru punya jalur keluar yang jelas
      (bukan "diam selamanya" seperti bug loop-detector sebelum diperbaiki).
- [ ] **AI Content generation** — cron/manual-trigger tidak bisa race untuk brand/project
      yang sama (⚠️ saat ini BELUM ada proteksi — lihat Lampiran D #3, jangan anggap aman
      by default sampai ini benar-benar diperbaiki).
- [ ] **Queue/worker** — KontenPilot tidak punya queue sungguhan (systemd timer only) —
      pastikan tidak ada asumsi keliru bahwa ada antrian yang mencegah overlap.
- [ ] **File processing** — render ffmpeg: tetap 2-input-per-panggilan (bukan N-input),
      cek tidak ada jalur BARU yang scaling memori dengan jumlah klip/overlay/input.
- [ ] **Frontend/backend compatibility** — PMS frontend (CRA) vs backend API; KontenPilot
      Next.js API routes vs client — perubahan response shape dicek di kedua sisi.
- [ ] **External API failure** — OpenAI/fal.ai/Tripay/Buffer/YouTube/Telegram/Fonnte:
      panggilan gagal tidak membuat state PMS/DB jadi tidak konsisten (write-before-call
      vs call-before-write — cek urutan mana yang lebih aman utk kasus spesifik).
- [ ] **Timeout/retry** — timeout yang di-hardcode masuk akal utk kerja NYATA (bukan
      asumsi optimis) — 2 insiden nyata di KontenPilot sendiri (curl 1700s, ffmpeg 20menit)
      keduanya gara-gara timeout tidak mengikuti kerja sungguhan.
- [ ] **Logging** — biaya API (KontenPilot `llm_usage_log`), aktivitas sensitif (PMS
      `audit_log`) tetap tercatat untuk perubahan yang menyentuh jalur itu.
- [ ] **Monitoring** — kalau menambah kegagalan-diam-diam yang mungkin (try/except tanpa
      alert), pastikan itu keputusan sadar (seperti `alert-owner` yang boleh gagal diam2)
      bukan kelalaian (seperti webhook WA Cloud yang TIDAK alert, Lampiran D #7).
- [ ] **Security** — tidak ada nama tamu/kredensial asli masuk ke commit message/comment
      (insiden nyata malam ini). Kredensial baru (API key, token) tidak ter-log/ter-print
      ke output yang bisa terekspos.
- [ ] **Performance** — render/generate baru tidak menambah pola "1 proses pegang N input
      sekaligus" tanpa batas (Lampiran D #14) — kalau N bisa tumbuh tanpa batas
      (jumlah klip, jumlah overlay, jumlah item apa pun dari sumber eksternal/AI), WAJIB
      ada strategi (batching, cap, atau desain yg terbukti O(1) per panggilan seperti
      tree-merge).

## Sebelum Deploy (per sistem)

- [ ] **PMS**: `test_regresi.py` PASS **kalau** perubahan menyentuh
      reports/laporan_analitik/checkin-checkout/WITA helpers (scope gate, lihat Lampiran
      B) — kalau di luar scope itu, review manual menggantikan gate otomatis, lakukan
      lebih hati-hati.
- [ ] **ai-chat-bot**: `test_hallucination_guards.py` PASS. Kegagalan skenario LIVE →
      re-run 1x sebelum dianggap regresi nyata. Kegagalan unit test → selalu nyata,
      jangan re-run-lalu-abaikan.
- [ ] **KontenPilot**: tidak ada test runner — minimal jalankan `npx tsc --noEmit` (type
      check) dan, kalau ada, script `tsx` verifikasi yang relevan
      (`scripts/verify-tree-merge-plan.ts` utk perubahan render). Untuk perubahan
      berdampak besar, pertimbangkan 1x uji nyata berbayar skala kecil sebelum full
      deploy (pola yang dipakai malam ini utk validasi tree-merge).

## Setelah Deploy

- [ ] Commit SHA di server match dgn yang di-push (`git log -1` di server vs origin).
- [ ] Service `is-active`/health endpoint OK, log start bersih.
- [ ] **KontenPilot khusus**: cek KEDUA server, bukan cuma satu — drift adalah risiko
      struktural di sistem ini (Lampiran C).
- [ ] Untuk perubahan booking/payment/AI-behavior: 1x uji nyata (Chat Simulator utk
      ai-chat-bot, atau baca log produksi beberapa menit pertama) sebelum dianggap selesai
      — jangan cuma percaya "test lolos = aman di produksi".
