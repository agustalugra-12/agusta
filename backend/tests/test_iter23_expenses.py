"""Iter23 — Backend regression for /api/expenses (list + create + date range filter).
Feature: Frontend LaporanExpenses tab. Backend unchanged; verify baseline still works."""
import os
import uuid
import pytest
import requests
from datetime import datetime, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def auth_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "owner", "password": "owner123"}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json().get("token")
    assert token
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


class TestExpensesEndpoints:
    def test_list_expenses_returns_list(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/expenses", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_list_expenses_range_filter(self, auth_client):
        today = datetime.now().strftime("%Y-%m-%d")
        r = auth_client.get(f"{BASE_URL}/api/expenses",
                            params={"from_date": today, "to_date": today + "T23:59:59"}, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_and_verify_expense_persistence(self, auth_client):
        marker = f"TEST_ITER23_{uuid.uuid4().hex[:8]}"
        payload = {
            "kategori": "Operasional",
            "deskripsi": f"Test regression E2E iterasi 23 {marker}",
            "nominal": 45000,
        }
        r = auth_client.post(f"{BASE_URL}/api/expenses", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["kategori"] == "Operasional"
        assert created["nominal"] == 45000
        assert created["deskripsi"] == payload["deskripsi"]
        assert "id" in created
        assert "_id" not in created  # ensure ObjectId excluded
        assert created.get("user")  # petugas populated
        eid = created["id"]

        # GET should include this expense
        r2 = auth_client.get(f"{BASE_URL}/api/expenses", timeout=30)
        assert r2.status_code == 200
        items = r2.json()
        found = [x for x in items if x.get("id") == eid]
        assert len(found) == 1, "created expense not returned by GET /api/expenses"
        assert found[0]["deskripsi"] == payload["deskripsi"]
        assert found[0]["nominal"] == 45000

        # Cleanup: owner can delete
        d = auth_client.delete(f"{BASE_URL}/api/expenses/{eid}", timeout=30)
        assert d.status_code in (200, 204)

    def test_list_expenses_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/expenses", timeout=30)
        assert r.status_code in (401, 403)


class TestReportsSmoke:
    """Regression smoke — ensure other Laporan tabs endpoints still return 200."""
    def test_daily(self, auth_client):
        today = datetime.now().strftime("%Y-%m-%d")
        wk = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        r = auth_client.get(f"{BASE_URL}/api/reports/daily",
                            params={"from_date": wk, "to_date": today}, timeout=30)
        assert r.status_code == 200

    def test_rooms(self, auth_client):
        today = datetime.now().strftime("%Y-%m-%d")
        wk = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
        r = auth_client.get(f"{BASE_URL}/api/reports/rooms",
                            params={"from_date": wk, "to_date": today}, timeout=30)
        assert r.status_code == 200

    def test_kasir_detail(self, auth_client):
        today = datetime.now().strftime("%Y-%m-%d")
        wk = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
        r = auth_client.get(f"{BASE_URL}/api/reports/kasir-detail",
                            params={"from_date": wk, "to_date": today}, timeout=30)
        assert r.status_code == 200

    def test_items_sold(self, auth_client):
        today = datetime.now().strftime("%Y-%m-%d")
        wk = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
        r = auth_client.get(f"{BASE_URL}/api/reports/items-sold",
                            params={"from_date": wk, "to_date": today}, timeout=30)
        assert r.status_code == 200

    def test_top_products(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/reports/top-products",
                            params={"period": "month", "limit": 10}, timeout=30)
        assert r.status_code == 200

    def test_cancellation_revenue(self, auth_client):
        today = datetime.now().strftime("%Y-%m-%d")
        wk = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
        r = auth_client.get(f"{BASE_URL}/api/reports/cancellation-revenue",
                            params={"from_date": wk, "to_date": today}, timeout=30)
        assert r.status_code == 200
