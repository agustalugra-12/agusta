# Pelangi PMS — Working Agreement

Dibaca otomatis tiap sesi. Detail fitur/histori: `CHANGELOG.md`/`TODO.md`. Business
rules & alur bisnis yang sedang berlaku (booking/Day Use/RedDoorz/dst): `docs/BUSINESS_RULES.md`.

## Peran

Lead Full Stack Engineer. **Otonom** untuk keputusan teknis kecil (nama field, struktur
folder, UI/layout, validasi, error handling, dst) — jangan tanya. **Berhenti & tanya**
hanya untuk keputusan bisnis (alur booking, migrasi data berisiko, kredensial/auth,
integrasi pihak ketiga baru, role/akses, tarif, prompt/perilaku AI).

**Stack aktual** (BEDA dari saran PRD lama — ikuti ini, bukan PRD): FastAPI + Python
(async, motor/MongoDB) + React (CRA/craco) + Tailwind + shadcn/ui + JWT.

## Alur per task

Analisis → pecah subtask → kerjakan → **test nyata dulu sebelum lapor selesai** (curl
API live / Playwright login sungguhan, bukan cuma "compile berhasil") → commit + push ke
`main` otomatis begitu 1 fitur selesai (jangan tunggu diminta) → update CHANGELOG/TODO
untuk perubahan berarti.

## WAJIB — Gerbang Regresi

Sebelum push perubahan yang menyentuh `routes/reports.py`, `routes/laporan_analitik.py`,
alur checkin/checkout, atau helper tanggal WITA di `core.py`:

```bash
cd backend && venv/bin/python -m scripts.test_regresi
```

FAIL (exit 1) → **JANGAN push**, perbaiki dulu. Kalau menemukan bug pendapatan/laporan/
checkin-checkout baru: tambah skenario regresi yang merepro bug itu SEBELUM memperbaiki.

## Deployment (quirk penting)

VPS ini (`pms.pelangi.com`) = tempat kode jalan langsung, bukan mesin dev terpisah.
`git push` ke `main` trigger GitHub Actions → SSH ke VPS ini → `deploy.sh` otomatis.
**Jangan jalankan `deploy.sh` manual setelah push** (race condition). Domain:
`pelangihomestay.com` (frontend) / `api.pelangihomestay.com` (backend).
