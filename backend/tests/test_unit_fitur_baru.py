"""Unit test murni (2026-07-24, ditambahkan saat audit kesiapan produksi) untuk logika
paling kritis dari fitur-fitur yang dibangun sesi ini (Payroll->Expense, Cash & Rekening,
AI Grow, perbaikan data member) yang SEBELUMNYA sama sekali tidak punya test otomatis.

Sengaja BEDA dari test lain di folder ini: TIDAK butuh server HTTP terpisah, TIDAK
menyentuh data produksi - murni memanggil fungsi Python langsung & mengecek hasilnya.
Aman dijalankan kapan saja termasuk langsung di server produksi (tidak pernah menulis
data), cukup:

    cd /root/agusta/backend
    MONGO_URL=mongodb://localhost:27017 DB_NAME=pms_test ./venv/bin/python -m pytest \
        tests/test_unit_fitur_baru.py -p no:cacheprovider

(MONGO_URL/DB_NAME cuma dibutuhkan supaya modul core.py bisa di-import - koneksi
Mongo-nya sendiri tidak pernah benar-benar dipakai oleh test-test di file ini)."""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "pms_test")
for _k in ("JWT_SECRET", "TRIPAY_MERCHANT_CODE", "TRIPAY_API_KEY", "TRIPAY_PRIVATE_KEY",
           "OPENAI_API_KEY", "BREVO_API_KEY", "BREVO_FROM_EMAIL", "TELEGRAM_OWNER_BOT_TOKEN",
           "TELEGRAM_STAFF_BOT_TOKEN", "TELEGRAM_OWNER_WEBHOOK_SECRET", "TELEGRAM_STAFF_WEBHOOK_SECRET",
           "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CLAIM_EMAIL", "GOOGLE_CLIENT_ID",
           "GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI", "FRONTEND_URL"):
    os.environ.setdefault(_k, "x")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa: E402
from routes.payroll import _tanggal_expense_payroll  # noqa: E402


# ---- phone_variants / cari_guest matching (bug nyata 2026-07-24: data member terpecah) ----

def test_phone_variants_0_dan_62_dianggap_sama():
    v = core.phone_variants("087761611631")
    assert "087761611631" in v
    assert "6287761611631" in v


def test_phone_variants_dari_format_62():
    v = core.phone_variants("6287761611631")
    assert "087761611631" in v
    assert "6287761611631" in v


def test_phone_variants_no_hp_kosong_tidak_error():
    assert core.phone_variants("") == {""}
    assert core.phone_variants(None) == {""}


# ---- Diskon diskresi AI (tier lama menginap / jumlah kamar, maks 10%) ----

def test_diskon_diskresi_tier_malam():
    assert core.hitung_diskon_ai_diskresi(malam=1, jumlah_kamar=1) == 0
    assert core.hitung_diskon_ai_diskresi(malam=2, jumlah_kamar=1) == 5
    assert core.hitung_diskon_ai_diskresi(malam=3, jumlah_kamar=1) == 8
    assert core.hitung_diskon_ai_diskresi(malam=4, jumlah_kamar=1) == 8
    assert core.hitung_diskon_ai_diskresi(malam=5, jumlah_kamar=1) == 10
    assert core.hitung_diskon_ai_diskresi(malam=100, jumlah_kamar=1) == 10  # tidak pernah lebih dari maks


def test_diskon_diskresi_tier_kamar():
    assert core.hitung_diskon_ai_diskresi(malam=1, jumlah_kamar=2) == 5
    assert core.hitung_diskon_ai_diskresi(malam=1, jumlah_kamar=4) == 8
    assert core.hitung_diskon_ai_diskresi(malam=1, jumlah_kamar=6) == 10


def test_diskon_diskresi_ambil_terbesar_bukan_dijumlah():
    # 4 malam (8%) + 4 kamar (8%) -> WAJIB tetap 8%, bukan 16% (aturan bisnis eksplisit)
    assert core.hitung_diskon_ai_diskresi(malam=4, jumlah_kamar=4) == 8
    # 5 malam (10%) + 2 kamar (5%) -> ambil yang terbesar (10%)
    assert core.hitung_diskon_ai_diskresi(malam=5, jumlah_kamar=2) == 10


# ---- Tanggal expense payroll (bug nyata 2026-07-22: sempat proyeksi ke masa depan) ----

def test_tanggal_expense_payroll_bulan_sudah_lewat():
    # Periode Januari 2020 (pasti sudah lewat) -> tanggal expense = akhir bulan itu persis
    assert _tanggal_expense_payroll("2020-01") == "2020-01-31"


def test_tanggal_expense_payroll_tidak_pernah_masa_depan():
    # Periode bulan BERJALAN saat ini -> tanggal expense TIDAK BOLEH lebih besar dari hari ini
    periode_bulan_ini = datetime.now(timezone.utc).strftime("%Y-%m")
    hasil = _tanggal_expense_payroll(periode_bulan_ini)
    hari_ini = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert hasil <= hari_ini, f"Tanggal expense {hasil} tidak boleh melebihi hari ini {hari_ini}"


def test_tanggal_expense_payroll_desember():
    assert _tanggal_expense_payroll("2020-12") == "2020-12-31"


# ---- Business Health Score (kunci angka yang sudah diverifikasi manual cocok, 2026-07-22) ----

def test_health_score_kasus_nyata_terverifikasi():
    from routes.ai_grow import _hitung_health_score
    # Data PERSIS sama dengan kondisi produksi nyata saat fitur ini pertama diverifikasi
    # manual (lihat CHANGELOG) - skor 86 sudah dicek cocok dengan hitungan tangan waktu itu,
    # test ini mengunci angka itu supaya perubahan formula di masa depan tidak diam-diam
    # menggeser hasilnya tanpa disadari.
    data = {
        "summary": {"okupansi_persen": 33.3, "pendapatan_bulan_ini": 12728017, "laba_bersih_bulan_ini": 6461017},
        "hk_pending": 0, "issues_terbuka": 0,
        "guest": {"total_tamu": 71, "tamu_berulang": 1, "persen_berulang": 1.4},
        "hari_berjalan": 22, "cash": None,
    }
    hasil = _hitung_health_score(data, risiko=[])
    assert hasil["skor"] == 86
    assert hasil["breakdown"]["finansial"]["skor"] == 100  # margin >40%
    assert hasil["breakdown"]["kas"]["skor"] == 100  # tidak pakai modul kas = netral penuh


def test_health_score_risiko_kas_tinggi_menurunkan_skor_kas():
    from routes.ai_grow import _hitung_health_score
    data = {
        "summary": {"okupansi_persen": 50, "pendapatan_bulan_ini": 10000000, "laba_bersih_bulan_ini": 1000000},
        "hk_pending": 0, "issues_terbuka": 0,
        "guest": {"total_tamu": 10, "tamu_berulang": 3, "persen_berulang": 30},
        "hari_berjalan": 15, "cash": {"total_cash": 1000000},
    }
    risiko = [{"level": "tinggi", "area": "kas", "detail": "Rekening X hampir habis"}]
    hasil = _hitung_health_score(data, risiko)
    assert hasil["breakdown"]["kas"]["skor"] == 40  # risiko tinggi -> skor kas jatuh jauh di bawah 100
