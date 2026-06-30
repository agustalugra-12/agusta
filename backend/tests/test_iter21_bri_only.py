"""Iter21 - Verify /api/public/bank-accounts returns BRI only with correct number."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pwa-kasir-hotel.preview.emergentagent.com").rstrip("/")


def test_public_bank_accounts_bri_only():
    r = requests.get(f"{BASE_URL}/api/public/bank-accounts", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "accounts" in data and isinstance(data["accounts"], list)
    assert len(data["accounts"]) == 1, f"Expected 1 account, got {len(data['accounts'])}: {data['accounts']}"
    acc = data["accounts"][0]
    assert acc["bank"] == "BRI"
    assert acc["nomor"] == "464001008162533"
    assert acc["atas_nama"] == "Pelangi Homestay"


def test_no_bca_or_mandiri():
    r = requests.get(f"{BASE_URL}/api/public/bank-accounts", timeout=10)
    assert r.status_code == 200
    banks = [a["bank"] for a in r.json()["accounts"]]
    assert "BCA" not in banks
    assert "Mandiri" not in banks


def test_instruksi_present():
    r = requests.get(f"{BASE_URL}/api/public/bank-accounts", timeout=10)
    assert r.status_code == 200
    assert "instruksi" in r.json()
    assert len(r.json()["instruksi"]) > 0
