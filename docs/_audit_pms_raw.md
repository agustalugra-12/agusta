# Pelangi PMS — Raw Architecture & Risk Audit (read-only)

Date: 2026-08-14. Scope: `/root/agusta` only (backend FastAPI/motor/MongoDB + React frontend).
Companion audits: ai-chat-bot, kontenpilot-ai (separate reports). This is a working input
for the controller's cross-system synthesis — not a polished deliverable. All guest
examples below are anonymized per instructions even where the source code comments name
real guests.

CLAUDE.md was read first and is treated as ground truth for business rules already in
force (multi-property model, RedDoorz two-stage sync, booking-request-not-booking AI
boundary, regression gate for reports/checkin). This report does not re-derive those.

---

## 1. Architecture

### Backend (`backend/`, FastAPI + motor/MongoDB async)
Thin `server.py` orchestrator (startup/shutdown hooks, CORS, mounts `routes` package).
Business logic lives in `core.py` (models/helpers/security/DB client) + `routes/*.py`
(37 files, 13,739 lines). Largest/most critical by LOC and by business risk:

| File | LOC | Owns |
|---|---|---|
| `routes/otomasi_email.py` | 1485 | RedDoorz/OTA email parsing (AI), auto-reservation, booking matching/dedup |
| `routes/telegram_bot.py` | 1152 | Owner/staff Telegram bot, daily report, expense capture, Action Center push |
| `routes/booking_requests.py` | 1128 | AI WhatsApp booking-request lifecycle, auto-approve, staff approve/reject |
| `routes/reports.py` | 890 | Revenue/analytics — covered by regression gate |
| `routes/checkins.py` | 853 | Check-in/out (walk-in + Day Use), housekeeping — covered by regression gate |
| `routes/bookings.py` | 764 | CRUD booking, `checkin_from_booking`, cancel |
| `routes/claude_fix.py` | 668 | **AI-driven auto-fix-and-deploy pipeline** (Telegram-triggered, see §6) |
| `routes/integrasi_ai_bot.py` | 667 | **Entire ai-chat-bot-facing API surface** (see §4/§5/§7) |
| `routes/rekening.py` | 614 | Cash/account ledger, smart allocation |
| `routes/pembatalan.py` | 252 | AI + staff cancellation-request workflow |
| `routes/tripay.py` | 339 | Tripay transaction create + webhook callback |
| `routes/payments.py` | 263 | Payment log, manual status override, `_lakukan_ganti_metode_pembayaran` |
| `routes/incidents.py` | 359 | Incident Engine / Action Center, dedup, correlation, 2 background scan loops |

Shared modules: `core.py` (scoped(), auth, locks, pricing/discount rules),
`reservation_service.py` (`check_room_available`, `create_reservation`, room-level
`asyncio.Lock`), `scheduling_engine.py` (advisory Day Use/Menginap scheduling math),
`email_service.py` (voucher PDF/email/WA).

### Frontend (`frontend/src`, brief)
CRA/craco + Tailwind + shadcn/ui. `pages/` (37 page files), `components/`, `context/`,
`hooks/`, `lib/`. Not this audit's focus; no data-safety issues investigated here beyond
noting it consumes the same API surface as staff/owner (JWT cookie/bearer).

### Database (MongoDB, ~50 collections)
Notable collections and index posture (from `server.py` startup + grep):

- **Indexed/unique-guarded**: `users` (username unique, email unique sparse),
  `properties` (slug unique), `rooms`/`products`/`rates`/`jadwal_kerja` (compound unique
  incl. `property_id`, migrated 2026-07-24 for multi-property), `bookings` (room_id,
  jam_mulai, compound room/status/jam_mulai "hot path", payment_status+paid_at, source,
  ota_reservation_no sparse, modifikasi_status sparse, sync_status sparse — **no unique
  constraint on `kode` itself**, dedup relies entirely on app-level idempotency),
  `booking_requests` (status, created_at, **`idempotency_key` unique+sparse — added
  2026-08-14 tonight**), `issues` (`idempotency_key` unique+sparse, added tonight),
  `ganti_metode_pembayaran_idempotency` (new small collection, added tonight, purely a
  dedup/result cache), `push_subscriptions` (endpoint unique), `integrations` (provider
  unique), `payroll` (staff_id+periode unique), `jadwal_shifts` (jadwal_id+staff_id+
  tanggal unique), `incidents` (status+created_at, dedup_key sparse).
- **No index at all found for**: `guests`, `payment_log`, `email_logs`, `room_mappings`,
  `staff_profil`, `kasbon`, `rekening_transaksi`, `wa_conversations` (this last one is
  confirmed dead — see `pesan_whatsapp.py` docstring, 0 documents ever, feature removed
  2026-07-22). `payment_log` in particular is queried by `order_id` (Tripay
  merchant_ref) on every webhook callback (`routes/tripay.py:192`) with no index —
  currently fine at low volume, will degrade as `payment_log` grows.
- `bookings.kode` (human-facing booking code, `BKO-YYYYMMDDHHMMSS-XXXX`) has no unique
  index — collision protection relies purely on the timestamp+random-hex generation
  scheme in `reservation_service.py:210`, not the database.

### Background workers (all `asyncio.create_task(...)` at startup, `server.py`)
1. `background_sync_loop` (`sinkronisasi_ketersediaan.py`) — availability sync, interval
   from `sync_settings.frekuensi_menit`.
2. `background_gmail_fetch_loop` (`otomasi_email.py`) — polls Gmail for OTA emails,
   auto-creates/matches reservations.
3. `background_telegram_daily_report_loop` (`telegram_bot.py`) — daily report 23:00 WIB,
   also triggers AI Grow's 3rd cache slot.
4. `background_smart_rule_loop` (`rekening.py`) — cash allocation rule check, ~6h.
5. `background_ai_grow_cache_loop` (`ai_grow.py`) — Daily Brief cache refresh, 10:00/18:00 WIB.
6. `background_collection_required_scan_loop` (`incidents.py`) — scans checked-in
   Menginap bookings with outstanding balance, every 15 min.
7. `background_business_truth_scan_loop` (`incidents.py`) — cross-checks Tripay
   settlement (`payment_log`) vs cash ledger (`rekening_transaksi`), hourly.
8. `reconcile_stale_claude_runs()` (`claude_fix.py`) — awaited (not task) at startup,
   marks any Claude Code Control run left "in progress" across a restart as errored.

All run in-process in the single uvicorn worker — no external scheduler/cron, no
supervision if a loop's top-level `while True` body raises unexpectedly outside its own
try/except (not verified per-loop in this pass; flag for follow-up).

### External APIs / integration points
See full table in §7. Summary: Tripay (payment gateway, in+out), Gmail API (RedDoorz/OTA
email, in), Telegram Bot API (owner/staff, in+out, 2 bots), WhatsApp relay (out, via
staff-configured generic webhook → in practice always ai-chat-bot's `/api/send-message`
and `/api/send-document`), ai-chat-bot's own inbound API (`integrasi_ai_bot.py`, in —
this PMS never calls ai-chat-bot or WAHA directly), VAPID Web Push (out, browser),
OpenAI (email parsing in `otomasi_email.py`, jadwal_kerja AI generation), `claude` CLI
subprocess (self-modifying code pipeline, `claude_fix.py`).

---

## 2. Deployment

Confirmed exactly as CLAUDE.md states, with detail from `.github/workflows/deploy.yml`
and `deploy.sh`:

- Trigger: `git push` to `main` → GitHub Actions (`deploy.yml`, SSH via
  `appleboy/ssh-action`) → runs `deploy.sh` **on the same VPS that serves production**
  (`pms.pelangi.com` doubles as dev box).
- `deploy.sh`: `git pull` → `npm install --legacy-peer-deps` + `npm run build` (frontend)
  → wipe+copy `build/*` to `/var/www/pmspelangi` → `systemctl restart pms-backend` →
  `systemctl reload nginx`. **No test run, no build-failure short-circuit before
  restart** — if `npm run build` fails, the script has no explicit `set -e` visible at
  the top and no check between build and restart; a failed frontend build could still
  proceed to restart the (unrelated) backend and reload nginx with a stale/partial
  `/var/www/pmspelangi`. Backend has no equivalent explicit smoke-test step either
  (`py_compile`/import check is a *pre-push* discipline in CLAUDE.md's workflow, not
  something `deploy.sh` itself enforces).
- Regression gate is a **process discipline, not a CI gate**: `scripts/test_regresi.py`
  is a manual pre-push step for changes to `reports.py`/`laporan_analitik.py`/checkin-
  checkout/WITA date helpers — nothing in `deploy.yml` runs it. A push that skips the
  discipline (human or agent forgetting) still deploys.
- New: `routes/claude_fix.py` is a **second, parallel deploy path** — Telegram-triggered
  AI auto-fix that (after its own regression gate) pushes to `main` and restarts
  `pms-backend` itself, bypassing the human GitHub Actions flow's SSH step (it runs
  locally as the same systemd-adjacent process). See §6.

---

## 3. Existing tests

- **`scripts/test_regresi.py`** (890+ lines-equivalent, 18904 bytes) — the only test
  suite actually wired into a "must-pass-before-push" discipline (documented in
  CLAUDE.md). Runs **in-process against the production DB**, using fake `property_id`
  values (prefixed `test-regresi-pms-jangan-dipakai-asli-<uuid>`) that never appear in
  the property switcher, self-cleaning at the end of `main()`. Covers: WITA date-bucket
  helpers (`tanggal_wita`), and (per CLAUDE.md's own description of why it was created)
  Dashboard-vs-Ringkasan revenue parity, `source="whatsapp_auto"` inclusion in reports,
  double-counting checkins vs bookings, UTC-vs-WITA date bucketing bugs. Scope is
  explicitly `reports.py` / `laporan_analitik.py` / checkin-checkout / WITA helpers —
  **nothing else**.
- **5 new narrow regression scripts, all added today (2026-08-14), all explicitly
  labeled "not part of the mandatory gate"**: `test_booking_request_idempotency.py`,
  `test_ganti_metode_pembayaran_idempotency.py` (labeled HIGH), `test_tiket_idempotency.py`
  (MEDIUM), `test_emit_incident_dedup_key.py` (MEDIUM-LOW), `test_alert_owner_dedup.py`
  (LOW) — each is a single-purpose regression for one of tonight's fixes, same
  fake-property-id/self-cleaning/monkeypatched-side-effects pattern as `test_regresi.py`.
  These prove the specific fix works and stays fixed, but are not run automatically
  anywhere (no CI, no pre-push hook found).
- **`backend/tests/` (pytest, 17 files)** — confirmed exactly as CLAUDE.md says: relies
  on a separate test server + separate DB per `tests/conftest.py`'s own docstring, which
  "was never actually set up on this production server." `test_reports/pytest/` exists
  as a directory but there is no evidence of a working CI wiring it up; treat as
  effectively dormant/unreliable infrastructure, not a safety net.
- **`/root/agusta/tests/`** — `backend_test.py` (10407 bytes) + empty `__init__.py`,
  root-level, separate from both of the above; not referenced by CLAUDE.md at all,
  provenance/currency unclear, not investigated further (out of scope given the other
  two suites are the documented ones).

**Net effect**: exactly one code path family (reports/analytics/checkin-checkout/date
math) has an enforced regression gate. Payment flows, webhook handlers, the entire
ai-chat-bot-facing surface, RedDoorz matching, cancellation, auth/authorization, and
multi-property scoping have **zero enforced automated coverage** — the 5 new scripts are
opt-in regressions for specific already-fixed bugs, not a gate against new ones.

---

## 4. Test gaps (specific, not "everything else")

- **Tripay webhook (`routes/tripay.py:150` `tripay_callback`)**: no automated test at
  all. This is the single highest-value untested code path — it's the only external,
  unauthenticated-until-signature-checked, financially authoritative endpoint in the
  system. No test exercises: signature verification failure, `TRIPAY_PRIVATE_KEY` unset
  (payload silently ignored, `tripay.py:166`), the "guess booking from order_id when
  `payment_log` missing" fallback (`tripay.py:206`), the group-booking fan-out
  (`tripay.py:226`), or the settlement-vs-later-downgrade guard (`tripay.py:273`, itself
  a fix for a real 2026-08-02 incident).
- **RedDoorz email matching (`otomasi_email.py`)**: no automated test for
  `_cocokkan_via_kode_pms`, `_cocokkan_via_kode_pms_masked`, or
  `_cocokkan_booking_pending_reddoorz` — three fuzzy-matching functions that have each
  individually caused real duplicate/mismatched-booking incidents per their own code
  comments (2026-07-27, 2026-08-01/07/12/13). This is the most incident-prone function
  family in the codebase by comment density and is completely untested.
- **`integrasi_ai_bot.py` — the entire ai-chat-bot-facing surface**: no test file
  targets this module directly except the 4 new narrow idempotency scripts (which cover
  only the retry-duplication failure mode for booking-request/tiket/ganti-metode/
  alert-owner/emit-incident). Not covered: `verifikasi_ai_bot_key`'s constant-time
  comparison loop under concurrent load, `ai_bot_ketersediaan`'s WITA "today" anchor
  under DST-adjacent edge cases (none in Indonesia, but worth noting as a pattern), or
  `ai_bot_ajukan_pembatalan` (cancel-request) at all — no idempotency test exists for
  this endpoint despite it being the last of the 6 write endpoints in the file (its
  safety currently comes from an implicit state-check guard, not an explicit key — see
  §6, this is *probably* fine but is unverified by test).
- **Authentication/authorization boundaries**: no test exercises `require_owner` vs
  `get_current_user` role separation, JWT cookie vs bearer parity, or the
  `verifikasi_ai_bot_key` API-key auth path's failure modes (missing header, malformed
  Bearer, revoked/regenerated key mid-flight).
- **Multi-property data isolation**: `test_regresi.py` uses per-scenario fake
  `property_id`s but does not specifically assert that two *real* properties'
  data can never cross — i.e., there's no regression test of the `scoped()` discipline
  itself. Given §6 found one real scoping gap (`_cocokkan_booking_pending_reddoorz`),
  this is a concrete, not hypothetical, gap.
- **Payment/booking flows end-to-end**: no test drives create_reservation →
  tripay_create_transaction → tripay_callback → checkin_from_booking as one flow;
  each piece is at best indirectly touched.
- **Background loops**: none of the 7 `asyncio.create_task` loops (§1) have any test
  coverage of their scan/matching logic (`background_collection_required_scan_loop`,
  `background_business_truth_scan_loop` in particular, since they're the newest and
  encode real financial reconciliation logic).
- **`claude_fix.py`** (AI auto-deploy pipeline): no automated test of the gate-run-then-
  deploy state machine, the worktree isolation, or the restart-safety reconciliation
  (`reconcile_stale_claude_runs`) — high blast-radius code with zero test coverage.

---

## 5. Critical business flows (traced in code)

### A. Guest → AI chat → booking request → staff approval → payment → callback → confirmation
1. Guest messages ai-chat-bot (separate repo/process); PMS is never called until
   ai-chat-bot decides to act.
2. ai-chat-bot calls `POST /integrasi-ai-bot/booking-request`
   (`integrasi_ai_bot.py:511`) → `buat_booking_request` (`booking_requests.py:568`).
   Idempotency: `idempotency_key` checked via `find_one` first, then a `DuplicateKeyError`
   catch around `insert_one` as a race-safe second layer (`booking_requests.py:596-747`)
   — this is the pattern added tonight and is the most robust idempotency
   implementation in the codebase (find-then-insert + unique-index-as-backstop).
3. Validation gauntlet inside `buat_booking_request`: guest name/phone sanity, past-date
   guard, Day Use `jam_checkin` required + ≥11:00 WITA business rule, Menginap
   `tanggal_checkout` required — all added after real incidents (comments cite specific
   past bugs for each guard).
4. For Day Use with a known payment option: **auto-approve path**
   (`_coba_auto_approve_day_use`, referenced but not fully re-read this pass) creates a
   real Tripay transaction and sends the checkout link **without staff involvement** —
   this is a pre-existing trust boundary (per `integrasi_ai_bot.py:542` comment) that
   `ai_bot_ganti_metode_pembayaran` deliberately reuses rather than expanding.
5. Otherwise: staff reviews at `/booking-requests`, clicks Terima →
   `approve_booking_request` (not re-read line-by-line this pass, but calls into
   `create_reservation` per CLAUDE.md) → real `db.bookings` row created, `room_locks`
   held across check-then-insert (`reservation_service.py:234`) → Tripay transaction
   created (`tripay.py:38`) → checkout_url sent to guest.
6. Guest pays → Tripay calls `POST /payments/tripay/callback` (`tripay.py:150`) →
   HMAC-SHA256 signature check → `payment_log` upserted (idempotent by `order_id`) →
   booking(s) updated to `booking_paid`/`paid` → voucher (PDF+email+WA) generated once
   per group → `rekening` auto-posting once per group → push+Telegram alert. Two
   real-incident-driven guards live here: (a) already-paid bookings never get downgraded
   by a later stale `expire`/`deny`/`refund` callback from an abandoned parallel
   transaction (`tripay.py:273`, fixed 2026-08-02 incident), (b) group-level actions
   (voucher/posting) collected during the loop and executed once after, not per-room
   (`tripay.py:243`, fixed 2026-08-09 incident — previously a 4-room group posted the
   same income 4×).
7. Menginap bookings then enter the RedDoorz two-stage sync (`sync_status`) described in
   CLAUDE.md — orthogonal to `check_room_available`, purely a display/reconciliation
   concern, confirmed by re-reading `otomasi_email.py`.

### B. Guest cancellation request → staff review
1. ai-chat-bot calls `POST /integrasi-ai-bot/cancel-request` → `ajukan_pembatalan_ai`
   (`pembatalan.py:22`). No explicit `idempotency_key` (unlike the 3 fixed endpoints) —
   but it is **naturally idempotent by state check**: a second call for a booking
   already `cancel_request_status in (requested, pending)` is rejected outright
   (`pembatalan.py:65-66`) before any write happens. This means a `_pms_http_retry`
   duplicate here degrades gracefully to a harmless "already requested" response rather
   than a duplicate side effect — worth explicitly confirming/documenting as *safe by
   design*, not an oversight, in the synthesis doc (contrast with §6's genuine gaps).
2. Sets `cancel_request_status="requested"` + push + Telegram alert to owner — **no
   guest-facing message sent yet** (business rule confirmed: confirmation only on staff
   approval).
3. Staff approves (`pembatalan.py:109`) → policy fee recalculated at approval time (not
   trusted from request time) → `status="cancelled"`, `payment_status` set to
   `refunded`/`forfeited` → WA template sent to guest (only now). Reject/refund-sent are
   separate staff actions, each idempotent via explicit status-transition guards
   (`cancel_request_status` must be exactly `requested`/`pending` respectively).

### C. RedDoorz email sync → booking matching
1. `background_gmail_fetch_loop` polls Gmail → AI (`gpt-4o-mini`) parses email into
   structured reservation/modification/cancellation data (`otomasi_email.py:288`).
2. `buat_reservasi_otomatis` (`otomasi_email.py:512`) resolves target property from the
   email subject text (`_resolve_property_dari_subjek:366`, falls back to
   `get_default_property_id()` if ambiguous/not found — a **best-effort, not guaranteed,
   property resolution** for a downstream matching function that then doesn't even use
   it consistently, see §6 finding #1).
3. Tries, in order: exact PMS-code match in "Permintaan Khusus"
   (`_cocokkan_via_kode_pms`), then masked/wildcarded-code match
   (`_cocokkan_via_kode_pms_masked:395`, both properly `scoped()` by `property_id`),
   then fuzzy name+date+room-type match against pending-RedDoorz-sync bookings
   (`_cocokkan_booking_pending_reddoorz:304`, **not** scoped by `property_id` — see §6).
   If a unique match is found, the existing booking is marked `synced` instead of
   creating a duplicate.
4. If no match, and room-type mapping + real availability both check out, a brand-new
   `db.bookings` row is created directly (`source="ota"` path, not re-read line-by-line
   this pass) — protected by the same `check_room_available`/`room_locks` machinery as
   any other reservation.
5. Every one of the 4 matching functions above has comment-documented real-incident
   history (2026-07-27, 2026-08-01, -02, -07, -12, -13) — this is empirically the most
   bug-prone flow in the entire codebase, and per §4 it remains fully untested.

---

## 6. Regression-prone points (concrete evidence)

**1. HIGH — Multi-property data leak in RedDoorz booking matching.**
`_cocokkan_booking_pending_reddoorz` (`otomasi_email.py:304-363`) queries
`db.bookings.find({...})` with **no `property_id` in the filter at all** — its
signature doesn't even accept `property_id` (`nama_tamu, room_tipe, check_in,
jumlah_kamar`). It's called from `buat_reservasi_otomatis` (`otomasi_email.py:568`)
*after* `property_id` has already been resolved and correctly threaded into the two
sibling matchers on lines 534/539 (`_cocokkan_via_kode_pms`/`_masked`, both properly
`scoped()`). Practical exposure: once a second property with RedDoorz enabled exists
(today only Pelangi uses `sync_status`/RedDoorz per CLAUDE.md, but Harmoni or any future
property could be onboarded — see the `_resolve_property_dari_subjek` docstring, which
was itself written specifically to stop a "works today, silently wrong once a second
tenant needs it" bug of this exact shape), an OTA confirmation email for Property A could
match and silently mark a pending booking belonging to Property B as `synced` if
name+room-type+date happen to be close (name matching is deliberately loose substring
matching, not exact). This is precisely the class of bug the `scoped()` discipline in
`core.py:250` exists to prevent, and precisely the class the multi-property migration
audit (per memory) was built to catch — this one slipped through because the function
predates that audit and was never revisited when `property_id` threading was added to
its two siblings.

**2. MEDIUM — Same TOCTOU/atomicity bug class fixed in one check-in path, not its sibling.**
`routes/checkins.py`'s walk-in check-in path uses `db.rooms.find_one_and_update` with
`status: "kosong"` in the filter itself (`checkins.py:82`, comment explicitly frames
this as the atomic fix for a **real double-click duplicate-checkin race** — matches
memory of "PMS Check-in Race Condition," fixed 2026-08-05). `checkin_from_booking`
(`routes/bookings.py:323-361`), the *other* check-in entry point (booking → checked-in,
used for OTA/Quick-Book/online bookings), still does a plain `find_one` read
(`bookings.py:347,352`) followed by separate `update_one` calls with no lock and no
atomic filter — the same TOCTOU gap the sibling function was fixed for. Two staff
double-clicking "Check-in" on the same booking, or a slow request retried, could still
race here.

**3. MEDIUM — `deploy.sh` has no build/test gate before restart.** No `set -e` visible,
no check between `npm run build` and the subsequent wipe of `/var/www/pmspelangi` +
`systemctl restart pms-backend`. A failing frontend build could leave the site broken
while still restarting a possibly-unrelated backend and reloading nginx, masking the
real failure signal. The regression gate (`test_regresi.py`) is not invoked anywhere in
this pipeline — it is purely a documented human/agent pre-push habit.

**4. MEDIUM — `payment_log` queried by `order_id` on every Tripay webhook with no
index** (`tripay.py:192`, confirmed absent from the `server.py` index list in §1).
Low risk today at current volume; will degrade linearly and eventually threaten webhook
response latency (Tripay retries on slow responses, same failure family as the bug
class this whole audit is about).

**5. LOW-MEDIUM — `bookings.kode` has no unique DB index.** Collision-avoidance is
purely probabilistic (timestamp-to-the-second + 4 random hex chars,
`reservation_service.py:210`). Two bookings created in the same second for the same
room would need the same 4 random hex chars to actually collide (1/65536 conditional on
same-second), so practical risk is low, but it means the RedDoorz masked-suffix matching
in §5C (which matches on exactly those 4 trailing hex chars) has a small but nonzero
false-positive surface that a DB constraint doesn't backstop.

**6. Confirmed-good pattern, worth naming explicitly for the synthesis doc**: every one
of tonight's 5 idempotency fixes uses (or, for cancel-request, doesn't need) a
consistent, race-safe two-layer pattern — in-app `find_one` check first (fast path) +
either a unique-sparse DB index with `DuplicateKeyError` catch (`booking_requests`,
`issues`) or a dedicated small idempotency-result-cache collection
(`ganti_metode_pembayaran_idempotency`, used because that function returns a computed
result rather than owning a document) or a bounded in-memory time-window dedup for the
one case with no persistable "result" at all (`alert-owner`, explicitly scoped to that
endpoint only, not the shared `kirim_alert_owner` helper, to avoid over-deduping
unrelated alerts that happen to have identical text). This is a genuinely solid template
— the synthesis doc should probably recommend it as the standard idempotency pattern for
any *future* AI-facing write endpoint, rather than reinventing per-endpoint.

**7. Retry/timeout logic besides the one already fixed tonight**: no other in-house
retry loop was found in `backend/` (grepped for `retry`/`timeout=`/`max_retries` across
all of `routes/` and `core.py` — see §1 methodology). The `_pms_http_retry` mechanism
itself lives in ai-chat-bot, not here; PMS's own outbound HTTP calls (Tripay, Gmail via
`email_service.py`, the generic WA webhook relay, Telegram) all use a single
`httpx.AsyncClient(timeout=N)` call with **no retry wrapper at all** on the PMS side —
meaning PMS-initiated calls fail once and give up (logged/best-effort), rather than risk
duplicate side effects. This is actually a reasonable current equilibrium (no PMS-side
retry = no PMS-side retry-duplication risk of this specific bug class) but is worth
flagging explicitly: if someone adds retry logic to any of these outbound calls in the
future (e.g., to make Tripay creation more resilient to transient network blips), it
would need the same idempotency-key discipline as tonight's fixes, since none of these
call sites currently have any dedup guard against being invoked twice.

---

## 7. External API / webhook integration points

| Integration | Direction | Trigger | If slow | If called twice | If fails mid-flow |
|---|---|---|---|---|---|
| **Tripay** (payment gateway) | Out: create-transaction (`tripay.py:38`); In: callback webhook (`tripay.py:150`) | Out: staff/AI/auto-approve requests a checkout link. In: Tripay pushes on every status change. | Out: `timeout=15`, no retry — guest/staff sees an error, must retry manually (creates a *new* Tripay transaction, not a duplicate of the failed one, so no dedup issue). In: Tripay itself retries callbacks per their own policy (not controlled by PMS) — PMS callback handler is idempotent by `order_id` upsert into `payment_log` + a guard against downgrading already-paid bookings (`tripay.py:273`), so Tripay-side retries are safe. | Create: two calls = two real Tripay transactions + two checkout links (this is the exact bug class `_lakukan_ganti_metode_pembayaran`'s idempotency fix targets when reached via AI retry — direct staff-UI clicks still have no guard, "intentional" per code comment at `payments.py:143`). Callback: safe (idempotent, see above). | Create: `payment_log` row is written *after* the HTTP call succeeds (`tripay.py:119`) — if PMS crashes between Tripay accepting the transaction and this insert, the transaction exists at Tripay but PMS has no record until the callback arrives and falls back to the `guess_booking_kode_from_order_id` heuristic (`tripay.py:206`), which is a real but unindexed and best-effort recovery path. |
| **Gmail API / RedDoorz email** | In (poll) | `background_gmail_fetch_loop`, interval-based | N/A (poll loop, not a webhook) | N/A — same email re-fetched would re-trigger `buat_reservasi_otomatis`; protected only by the (partially scoped, see §6 #1) matching functions, not by an explicit "already processed this email" idempotency key on `email_logs` — not verified this pass whether `email_logs` itself has a dedup-by-message-id guard. **Flag for follow-up.** | Manual_Required fallback with a specific reason string — designed to degrade to staff review rather than fail silently, per multiple docstrings in `otomasi_email.py`. |
| **Telegram Bot API** (2 bots: owner+staff) | Out: alerts/reports (`kirim_alert_owner`, daily report); In: staff/owner commands incl. `claude_fix.py` triggers | Out: any payment/booking/incident event; In: Telegram polling/webhook (not confirmed which this pass) | `timeout=15-20` on outbound calls, no retry — alert simply doesn't arrive, best-effort (explicitly accepted risk per `alert-owner` dedup comment, `integrasi_ai_bot.py:601-618`) | Handled per-call-site: `alert-owner` relay has a 30s in-memory text-dedup window (added tonight); most other `kirim_alert_owner` call sites (payment received, booking approved, etc.) have no dedup because they're only ever called once per real event from PMS's own code, not via a retried HTTP path. | No transactional guarantee — a crash after DB write but before the Telegram call simply means the alert never fires; owner relies on the PMS UI (Dashboard/Action Center) as the source of truth, Telegram as a convenience notification layer. |
| **WhatsApp relay** (generic `webhook_config` → in practice always ai-chat-bot's `/api/send-message` / `/api/send-document`) | Out only (PMS never receives WA in) | Every guest-facing notification (voucher, approval, cancellation, refund, payment link) | `timeout=10` (`send-message`) / `timeout=30` (`send-document`), no retry on PMS side | N/A — PMS never calls this twice for the same event (no retry wrapper); a duplicate would only happen if the *caller* of `_kirim_dengan_alert` were itself re-invoked, which is exactly what tonight's idempotency fixes prevent for the AI-facing paths that funnel through it (`ganti-metode-pembayaran`) | `_kirim_dengan_alert` failures are caught and logged (`logging.getLogger(...).warning`), never raised — by design, a WA send failure never blocks or rolls back the underlying business action (booking approved, cancellation approved, etc. all complete regardless). This is a reasonable design choice but means **silent guest-communication failures are possible** with no automated retry or alerting distinct from a log line — worth a monitoring recommendation in the synthesis doc. |
| **ai-chat-bot inbound API** (`integrasi_ai_bot.py`, 12 endpoints) | In only — PMS never calls ai-chat-bot | Every guest WhatsApp interaction that needs live PMS data or wants to write a booking-request/ticket/cancel-request | PMS is the callee here — "if slow" is PMS's own response latency, which is exactly what caused tonight's 5 bugs upstream in ai-chat-bot's retry wrapper. Slowest known culprits: `kirim_alert_owner`'s serial per-owner Telegram loop (comment at `integrasi_ai_bot.py:604`), and any endpoint that waits on Tripay (`ganti-metode-pembayaran`). | 6 write endpoints total: `booking-request` (idempotency_key, fixed), `tiket` (idempotency_key, fixed), `ganti-metode-pembayaran` (idempotency_key, fixed), `alert-owner` (in-memory text dedup, fixed), `emit-incident` (dedup_key, fixed — pre-existing `create_incident` guard, ai-chat-bot just wasn't populating it before tonight), `cancel-request` (no explicit key, but naturally idempotent via state-check, see §5B). All 6 covered. The 6 read-only GETs (`ketersediaan`, `timeline-kamar`, `menu`, `rules`, `status-member`, `booking-status`, `link-pembayaran-aktif`, `preview-harga`) have no side effects and don't need dedup. | Each write endpoint either fully commits or raises an exception the caller sees (no partial-write states observed in the code read this pass, other than the general Tripay create-then-log-write gap noted above, which is shared with the staff-facing path). |
| **VAPID Web Push** | Out only | Booking/payment/complaint/housekeeping/cancellation events | Push API failure modes not investigated this pass (`routes/push.py`, 103 lines, not read in full) | Not investigated this pass — flag for follow-up if push duplication is ever reported | Not investigated this pass |
| **OpenAI** | Out (server-to-server) | Email parsing (`otomasi_email.py:288`, `gpt-4o-mini`), Jadwal Kerja AI generation | No timeout/retry visible on the `parse_email_with_ai` call itself (`asyncio.to_thread` wrapping the sync SDK call) — an OpenAI outage would raise and the email stays `Manual_Required`-eligible on next poll, not stuck. | N/A, read-generate-only, not a write-retry path | Exception bubbles to the poll loop's per-email try/except (not fully re-verified this pass) |
| **`claude` CLI subprocess** (Claude Code Control, `claude_fix.py`) | Out (controller shells out) + writes to `main` + restarts `pms-backend` | Owner Telegram command | `timeout=900s` on the Claude run itself, various shorter timeouts (15-300s) on individual git/systemctl subprocess calls | Guarded by `_claude_run_lock` (single in-process `asyncio.Lock`) — a second trigger while one run is active is rejected, not queued/duplicated (`claude_fix.py:241,425,468`) | `reconcile_stale_claude_runs()` at startup specifically handles the "backend restarted mid-run" case by marking the run errored rather than leaving it stuck (`server.py`, `claude_fix.py` docstring line 612) — this is itself evidence the authors are already applying the audit's core lesson (retry/crash-mid-flow leaves state, must be reconciled) to their newest, highest-blast-radius feature. |

---

## Appendix: methodology notes for the synthesis controller

- Searches used: `grep -rn` for `httpx\.\|requests\.` (outbound HTTP inventory),
  `retry\|timeout=\|max_retries` (retry logic inventory), `asyncio.Lock\|find_one_and_update`
  (concurrency-safety inventory), `db.<collection>.(find|find_one|update_one|...)` per
  major collection cross-referenced against `scoped(` on the same line (property-leak
  candidates — note this method has false positives where `property_id` was already
  validated by an earlier `scoped()` read in the same function; each flagged line in §6
  was individually read in context before being reported as a real finding, not just
  grep output).
- Not fully investigated this pass (explicitly flagged inline above, repeated here for
  visibility): `routes/push.py` internals, whether `email_logs` has message-ID-level
  dedup against reprocessing the same Gmail message, per-background-loop crash/
  supervision behavior beyond confirming they're bare `asyncio.create_task` with no
  visible top-level supervisor, `approve_booking_request`'s full body (only its role in
  the flow was confirmed via CLAUDE.md + call-graph, not re-read line by line).
- No code was modified. No destructive commands run. No messages sent to guests/staff/
  Telegram/WhatsApp/email. No git operations performed beyond none (this is not a git
  repo per the environment note, and none of the tooling used touches git regardless).
