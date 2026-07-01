"""Iteration 25 — Refactor smoke test.

Verifies all endpoint groups still respond correctly after the server.py -> core.py +
routes/* refactor. No behavioral change expected. Focus: endpoint registration,
response schemas, and cross-domain interactions (login -> checkin -> checkout -> kasir).
"""
import os
import uuid
import pytest
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pwa-kasir-hotel.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="module")
def owner_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "owner", "password": "owner123"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "token" in data and "user" in data
    assert data["user"]["role"] == "owner"
    return data["token"]


@pytest.fixture(scope="module")
def resep_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "resepsionis", "password": "resep123"}, timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---- SMOKE ----
class TestSmoke:
    def test_root_ok(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=10)
        assert r.status_code == 200
        j = r.json()
        assert j.get("status") == "ok"
        assert "app" in j

    def test_auth_me(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(owner_token))
        assert r.status_code == 200
        assert r.json()["username"] == "owner"


# ---- ROOMS ----
class TestRooms:
    def test_rooms_count_18(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/rooms", headers=_h(owner_token))
        assert r.status_code == 200
        rooms = r.json()
        assert len(rooms) == 18


# ---- PRODUCTS / KASIR ----
class TestProducts:
    def test_products_count(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/products", headers=_h(owner_token))
        assert r.status_code == 200
        prods = r.json()
        assert len(prods) >= 11  # seed has 11 items


# ---- PUBLIC ----
class TestPublic:
    def test_rooms_catalog(self):
        r = requests.get(f"{BASE_URL}/api/public/rooms-catalog")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_bank_accounts(self):
        r = requests.get(f"{BASE_URL}/api/public/bank-accounts")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_availability(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        r = requests.get(f"{BASE_URL}/api/public/availability",
                         params={"tanggal": tomorrow, "jam_checkin": "14:00"})
        assert r.status_code == 200


# ---- MIDTRANS ----
class TestMidtrans:
    def test_config_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/payments/midtrans/config")
        assert r.status_code == 200
        j = r.json()
        assert "client_key" in j
        assert j["client_key"]  # non-empty


# ---- REPORTS ----
class TestReports:
    def _range(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {"from_date": today, "to_date": today}

    def test_summary(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/summary", headers=_h(owner_token))
        assert r.status_code == 200

    def test_daily(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/daily", headers=_h(owner_token), params=self._range())
        assert r.status_code == 200

    def test_rooms(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/rooms", headers=_h(owner_token), params=self._range())
        assert r.status_code == 200

    def test_kasir_detail(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/kasir-detail", headers=_h(owner_token), params=self._range())
        assert r.status_code == 200

    def test_items_sold(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/items-sold", headers=_h(owner_token), params=self._range())
        assert r.status_code == 200

    def test_top_products(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/top-products", headers=_h(owner_token))
        assert r.status_code == 200

    def test_cancellation_revenue(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/cancellation-revenue",
                         headers=_h(owner_token), params=self._range())
        assert r.status_code == 200

    def test_booking_widgets(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/booking-widgets", headers=_h(owner_token))
        assert r.status_code == 200

    def test_service_revenue(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/reports/service-revenue",
                         headers=_h(owner_token), params=self._range())
        assert r.status_code == 200


# ---- MISC ----
class TestMisc:
    def test_audit_log(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/audit-log", headers=_h(owner_token))
        assert r.status_code == 200

    def test_housekeeping(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/housekeeping", headers=_h(owner_token))
        assert r.status_code == 200


# ---- END-TO-END: Checkin -> Kasir -> Checkout ----
class TestEndToEnd:
    def test_checkin_kasir_checkout_flow(self, owner_token):
        # 1. Find a 'kosong' room
        rooms = requests.get(f"{BASE_URL}/api/rooms", headers=_h(owner_token)).json()
        kosong = next((r for r in rooms if r["status"] == "kosong"), None)
        if kosong is None:
            pytest.skip("No available room for e2e flow")
        room_id = kosong["id"]

        # 2. Checkin
        ck = requests.post(f"{BASE_URL}/api/checkins", headers=_h(owner_token), json={
            "nama_tamu": f"TEST_iter25_{uuid.uuid4().hex[:6]}",
            "no_hp": "0812345",
            "jumlah_tamu": 1,
            "room_id": room_id,
            "catatan": "iter25 smoke",
        })
        assert ck.status_code == 200, ck.text
        checkin_id = ck.json()["id"]

        # 3. Verify room -> day_use
        room_after = next(x for x in requests.get(f"{BASE_URL}/api/rooms", headers=_h(owner_token)).json()
                          if x["id"] == room_id)
        assert room_after["status"] == "day_use"

        # 4. Checkout with sufficient payment
        co = requests.post(f"{BASE_URL}/api/checkins/{checkin_id}/checkout",
                           headers=_h(owner_token),
                           json={"pembayaran": [{"metode": "tunai", "jumlah": 200000}],
                                 "catatan": "iter25 co"})
        assert co.status_code == 200, co.text
        body = co.json()
        # tarif 120000 standard + 3% service fee = 123600; cottage 140000 + 3% = 144200
        assert body["total"] in (123600, 144200)
        assert "service_fee" in body
        # tarif 120000 -> service_fee 3600 ; tarif 140000 -> service_fee 4200
        assert body["service_fee"] in (3600, 4200)

        # 5. Verify room -> perlu_dibersihkan
        room_final = next(x for x in requests.get(f"{BASE_URL}/api/rooms", headers=_h(owner_token)).json()
                          if x["id"] == room_id)
        assert room_final["status"] == "perlu_dibersihkan"


# ---- BOOKING SMOKE ----
class TestBookingsSmoke:
    def test_list_bookings(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/bookings", headers=_h(owner_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---- SERVICES / EXPENSES CRUD MICRO ----
class TestServicesExpenses:
    def test_expense_crud(self, owner_token):
        payload = {"tanggal": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                   "kategori": "TEST_iter25", "deskripsi": "smoke", "nominal": 5000}
        r = requests.post(f"{BASE_URL}/api/expenses", headers=_h(owner_token), json=payload)
        assert r.status_code == 200, r.text
        eid = r.json()["id"]

        # verify list
        rl = requests.get(f"{BASE_URL}/api/expenses", headers=_h(owner_token))
        assert rl.status_code == 200
        assert any(e["id"] == eid for e in rl.json())

        # delete (owner-only)
        rd = requests.delete(f"{BASE_URL}/api/expenses/{eid}", headers=_h(owner_token))
        assert rd.status_code == 200

    def test_service_crud(self, owner_token):
        payload = {"deskripsi": "TEST_iter25 svc", "nominal": 50000,
                   "kategori": "Layanan Tambahan", "metode_pembayaran": "tunai"}
        r = requests.post(f"{BASE_URL}/api/services", headers=_h(owner_token), json=payload)
        assert r.status_code == 200
        sid = r.json()["id"]

        rl = requests.get(f"{BASE_URL}/api/services", headers=_h(owner_token))
        assert rl.status_code == 200
        assert any(s["id"] == sid for s in rl.json())

        rd = requests.delete(f"{BASE_URL}/api/services/{sid}", headers=_h(owner_token))
        assert rd.status_code == 200
