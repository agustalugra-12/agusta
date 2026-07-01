"""Iteration 24 - Services & Service Revenue Report tests."""
import os
import pytest
import requests
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pwa-kasir-hotel.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(username, password):
    r = requests.post(f"{API}/auth/login", json={"username": username, "password": password}, timeout=30)
    assert r.status_code == 200, f"Login {username} failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def owner_headers():
    tok = _login("owner", "owner123")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def resep_headers():
    tok = _login("resepsionis", "resep123")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def created_service_ids():
    # collect ids for cleanup
    return []


# ---- POST /api/services ----
class TestServiceCRUD:
    def test_create_service_success(self, owner_headers, created_service_ids):
        payload = {
            "kategori": "Transportasi",
            "deskripsi": "TEST_iter24 antar-jemput",
            "nominal": 75000,
            "tamu": "TEST_User",
            "no_hp": "081234567890",
            "metode_pembayaran": "qris",
        }
        r = requests.post(f"{API}/services", json=payload, headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data
        assert data["kode"].startswith("SVC-")
        # Format check SVC-YYYYMMDDHHMMSS-XXXX
        parts = data["kode"].split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 14
        assert len(parts[2]) == 4
        assert data["nominal"] == 75000
        assert data["deskripsi"] == "TEST_iter24 antar-jemput"
        assert data["kategori"] == "Transportasi"
        assert data["user"]  # user name
        assert data["tanggal"]
        created_service_ids.append(data["id"])

    def test_create_service_invalid_nominal(self, owner_headers):
        r = requests.post(f"{API}/services",
                          json={"deskripsi": "x", "nominal": 0},
                          headers=owner_headers, timeout=30)
        assert r.status_code == 400

        r2 = requests.post(f"{API}/services",
                           json={"deskripsi": "x", "nominal": -100},
                           headers=owner_headers, timeout=30)
        assert r2.status_code == 400

    def test_create_service_empty_description(self, owner_headers):
        r = requests.post(f"{API}/services",
                          json={"deskripsi": "  ", "nominal": 5000},
                          headers=owner_headers, timeout=30)
        assert r.status_code == 400

    def test_create_service_no_auth(self):
        r = requests.post(f"{API}/services",
                          json={"deskripsi": "no auth", "nominal": 5000}, timeout=30)
        assert r.status_code in (401, 403)

    def test_list_services(self, owner_headers, created_service_ids):
        r = requests.get(f"{API}/services", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        ids = [d["id"] for d in data]
        for sid in created_service_ids:
            assert sid in ids

    def test_list_services_date_filter(self, owner_headers):
        today = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(f"{API}/services",
                         params={"from_date": today, "to_date": today},
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # all items should be within today
        for it in data:
            assert (it.get("tanggal") or "")[:10] == today

    def test_list_services_date_filter_past(self, owner_headers):
        # empty result for far-past date
        r = requests.get(f"{API}/services",
                         params={"from_date": "2000-01-01", "to_date": "2000-01-02"},
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert r.json() == []

    def test_delete_service_forbidden_for_resep(self, resep_headers, owner_headers):
        # create with owner
        payload = {"deskripsi": "TEST_iter24 delete-attempt", "nominal": 1000, "kategori": "Lain"}
        r = requests.post(f"{API}/services", json=payload, headers=owner_headers, timeout=30)
        assert r.status_code == 200
        sid = r.json()["id"]
        # attempt delete with resep
        r2 = requests.delete(f"{API}/services/{sid}", headers=resep_headers, timeout=30)
        assert r2.status_code == 403
        # confirm still exists
        r3 = requests.get(f"{API}/services", headers=owner_headers, timeout=30)
        assert sid in [x["id"] for x in r3.json()]
        # cleanup
        requests.delete(f"{API}/services/{sid}", headers=owner_headers, timeout=30)

    def test_delete_service_owner_ok(self, owner_headers):
        payload = {"deskripsi": "TEST_iter24 to-be-deleted", "nominal": 2500}
        r = requests.post(f"{API}/services", json=payload, headers=owner_headers, timeout=30)
        sid = r.json()["id"]
        r2 = requests.delete(f"{API}/services/{sid}", headers=owner_headers, timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("ok") is True
        # verify gone
        r3 = requests.get(f"{API}/services", headers=owner_headers, timeout=30)
        assert sid not in [x["id"] for x in r3.json()]

    def test_delete_service_not_found(self, owner_headers):
        r = requests.delete(f"{API}/services/nonexistent-id-xyz", headers=owner_headers, timeout=30)
        assert r.status_code == 404


# ---- GET /api/reports/service-revenue ----
class TestServiceRevenueReport:
    def test_service_revenue_shape(self, owner_headers):
        today = datetime.now(timezone.utc).date().isoformat()
        # far past to today to include all data
        r = requests.get(f"{API}/reports/service-revenue",
                         params={"from_date": "2020-01-01", "to_date": today},
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        required = ["service_fee_pct", "checkin_service_fee_total", "checkin_count",
                    "booking_service_fee_total", "booking_count",
                    "service_fee_grand_total", "manual_service_total",
                    "manual_service_count", "grand_total",
                    "by_day", "checkin_items", "booking_items", "manual_services"]
        for k in required:
            assert k in d, f"missing key {k}"
        assert d["service_fee_pct"] == 0.03
        # numeric checks
        assert d["service_fee_grand_total"] == d["checkin_service_fee_total"] + d["booking_service_fee_total"]
        assert d["grand_total"] == d["service_fee_grand_total"] + d["manual_service_total"]
        # verify sums equal item aggregations
        ci_sum = sum(int(x.get("service_fee") or 0) for x in d["checkin_items"])
        bk_sum = sum(int(x.get("service_fee") or 0) for x in d["booking_items"])
        ms_sum = sum(int(x.get("nominal") or 0) for x in d["manual_services"])
        assert d["checkin_service_fee_total"] == ci_sum
        assert d["booking_service_fee_total"] == bk_sum
        assert d["manual_service_total"] == ms_sum
        assert d["checkin_count"] == len(d["checkin_items"])
        assert d["booking_count"] == len(d["booking_items"])
        assert d["manual_service_count"] == len(d["manual_services"])

    def test_service_revenue_includes_created(self, owner_headers):
        # ensure at least one manual service is included today
        payload = {"deskripsi": "TEST_iter24 report-check", "nominal": 12345,
                   "kategori": "Lain-lain"}
        cr = requests.post(f"{API}/services", json=payload, headers=owner_headers, timeout=30)
        assert cr.status_code == 200
        sid = cr.json()["id"]
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            r = requests.get(f"{API}/reports/service-revenue",
                             params={"from_date": today, "to_date": today},
                             headers=owner_headers, timeout=30)
            assert r.status_code == 200
            d = r.json()
            ids = [m["id"] for m in d["manual_services"]]
            assert sid in ids
        finally:
            requests.delete(f"{API}/services/{sid}", headers=owner_headers, timeout=30)


# ---- Regression: /reports/daily and /reports/summary ----
class TestReportsRegression:
    def test_daily_has_service_column(self, owner_headers):
        today = datetime.now(timezone.utc).date().isoformat()
        payload = {"deskripsi": "TEST_iter24 daily-check", "nominal": 50000}
        cr = requests.post(f"{API}/services", json=payload, headers=owner_headers, timeout=30)
        sid = cr.json()["id"]
        try:
            r = requests.get(f"{API}/reports/daily",
                             params={"from_date": today, "to_date": today},
                             headers=owner_headers, timeout=30)
            assert r.status_code == 200
            rows = r.json()
            assert isinstance(rows, list) and len(rows) >= 1
            row = next((x for x in rows if x["tanggal"] == today), None)
            assert row is not None
            assert "service" in row
            assert row["service"] >= 50000
            # pendapatan should include service
            assert row["pendapatan"] >= row["kamar"] + row["makanan"] + row["minuman"] + row["laundry"] + row["service"] - 1
        finally:
            requests.delete(f"{API}/services/{sid}", headers=owner_headers, timeout=30)

    def test_summary_has_service_fields(self, owner_headers):
        payload = {"deskripsi": "TEST_iter24 summary-check", "nominal": 33333}
        cr = requests.post(f"{API}/services", json=payload, headers=owner_headers, timeout=30)
        sid = cr.json()["id"]
        try:
            r = requests.get(f"{API}/reports/summary", headers=owner_headers, timeout=30)
            assert r.status_code == 200
            d = r.json()
            for k in ["pendapatan_service_hari_ini", "pendapatan_service_bulan_ini",
                      "pendapatan_bulan_ini", "pendapatan_hari_ini"]:
                assert k in d
            assert d["pendapatan_service_hari_ini"] >= 33333
            assert d["pendapatan_service_bulan_ini"] >= 33333
        finally:
            requests.delete(f"{API}/services/{sid}", headers=owner_headers, timeout=30)

    def test_expenses_regression(self, owner_headers):
        r = requests.get(f"{API}/expenses", headers=owner_headers, timeout=30)
        assert r.status_code == 200

    def test_login_owner_resep_regression(self):
        r1 = _login("owner", "owner123")
        r2 = _login("resepsionis", "resep123")
        assert r1 and r2
