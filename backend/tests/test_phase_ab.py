"""Phase A & B Tests: Service fee 3%, /api/bookings/availability, /api/public/*"""
import os
import pytest
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pwa-kasir-hotel.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def owner_token():
    r = requests.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def owner_h(owner_token):
    return {"Authorization": f"Bearer {owner_token}"}


@pytest.fixture(scope="session")
def rooms(owner_h):
    r = requests.get(f"{API}/rooms", headers=owner_h)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="session")
def kosong_standard(rooms, owner_h):
    """Find a Standard room currently 'kosong'."""
    for room in rooms:
        if room["tipe"] == "Standard" and room["status"] == "kosong":
            return room
    pytest.skip("No kosong Standard room available")


# ---------- Service Fee in calc_tagihan ----------
class TestServiceFeeCheckout:
    def test_checkin_checkout_includes_service_fee(self, owner_h, kosong_standard):
        # Create check-in
        ci_payload = {
            "nama_tamu": "TEST_ServiceFee",
            "no_hp": "08123TEST",
            "no_identitas": "TEST_FEE_001",
            "kendaraan": "",
            "jumlah_tamu": 1,
            "room_id": kosong_standard["id"],
            "catatan": "service fee test",
        }
        cr = requests.post(f"{API}/checkins", headers=owner_h, json=ci_payload)
        assert cr.status_code == 200, cr.text
        ci = cr.json()
        cid = ci["id"]
        try:
            # Check-out within 6 hours (no overtime) -> subtotal=120000, fee=3600, total=123600
            jam_out = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            payload = {"pembayaran": [{"metode": "tunai", "jumlah": 123600}], "jam_checkout": jam_out, "catatan": "TEST"}
            r = requests.post(f"{API}/checkins/{cid}/checkout", headers=owner_h, json=payload)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["subtotal"] == 120000, f"subtotal={data['subtotal']}"
            assert data["service_fee"] == 3600, f"service_fee={data['service_fee']}"
            assert data["total"] == 123600, f"total={data['total']}"

            # Verify persisted via GET
            g = requests.get(f"{API}/checkins/{cid}", headers=owner_h)
            assert g.status_code == 200
            saved = g.json()
            assert saved["subtotal"] == 120000
            assert saved["service_fee"] == 3600
            assert saved["total"] == 123600
        finally:
            # cleanup -> set room to kosong
            requests.put(f"{API}/rooms/{kosong_standard['id']}/status", headers=owner_h,
                         json={"status": "kosong"})

    def test_checkout_insufficient_payment_400(self, owner_h, rooms):
        # find another kosong Standard
        room = next((r for r in requests.get(f"{API}/rooms", headers=owner_h).json()
                     if r["tipe"] == "Standard" and r["status"] == "kosong"), None)
        if not room:
            pytest.skip("no kosong room")
        cr = requests.post(f"{API}/checkins", headers=owner_h, json={
            "nama_tamu": "TEST_InsufFee", "no_hp": "08", "no_identitas": "TEST_INSUF",
            "jumlah_tamu": 1, "room_id": room["id"],
        })
        assert cr.status_code == 200
        cid = cr.json()["id"]
        try:
            jam_out = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            # Pay only 120000 — service fee makes total 123600 → should 400
            r = requests.post(f"{API}/checkins/{cid}/checkout", headers=owner_h, json={
                "pembayaran": [{"metode": "tunai", "jumlah": 120000}],
                "jam_checkout": jam_out,
            })
            assert r.status_code == 400
            assert "kurang" in r.text.lower()
        finally:
            # complete properly to free room
            requests.post(f"{API}/checkins/{cid}/checkout", headers=owner_h, json={
                "pembayaran": [{"metode": "tunai", "jumlah": 123600}],
                "jam_checkout": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            })
            requests.put(f"{API}/rooms/{room['id']}/status", headers=owner_h, json={"status": "kosong"})


# ---------- /api/bookings/availability ----------
class TestBookingAvailability:
    def test_availability_returns_slots(self, owner_h, rooms):
        room = next((r for r in rooms if r["status"] == "kosong"), rooms[0])
        from_date = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(f"{API}/bookings/availability",
                         headers=owner_h, params={"room_id": room["id"], "from_date": from_date, "days": 14})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["room_id"] == room["id"]
        assert len(data["slots"]) == 14
        for s in data["slots"]:
            assert "date" in s and "available" in s and "reason" in s

    def test_availability_marks_booked_date(self, owner_h, kosong_standard):
        # Create booking 5 days from now
        start = (datetime.now(timezone.utc) + timedelta(days=5)).replace(hour=10, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=4)
        b = requests.post(f"{API}/bookings", headers=owner_h, json={
            "room_id": kosong_standard["id"], "tipe": "day_use",
            "nama_tamu": "TEST_Avail", "no_hp": "08", "jumlah_tamu": 1,
            "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        })
        assert b.status_code == 200, b.text
        bid = b.json()["id"]
        try:
            from_date = datetime.now(timezone.utc).date().isoformat()
            r = requests.get(f"{API}/bookings/availability", headers=owner_h,
                             params={"room_id": kosong_standard["id"], "from_date": from_date, "days": 14})
            data = r.json()
            target_date = start.strftime("%Y-%m-%d")
            slot = next((s for s in data["slots"] if s["date"] == target_date), None)
            assert slot is not None
            assert slot["available"] is False
            assert b.json()["kode"] in slot["reason"]
        finally:
            requests.delete(f"{API}/bookings/{bid}", headers=owner_h)


# ---------- Public Booking ----------
class TestPublicEndpoints:
    def test_catalog_no_auth(self):
        r = requests.get(f"{API}/public/rooms-catalog")
        assert r.status_code == 200
        cat = r.json()
        types = [c["tipe"] for c in cat]
        assert "Standard" in types and "Cottage" in types

    def test_availability_no_auth(self):
        d = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(f"{API}/public/availability", params={"tanggal": d})
        assert r.status_code == 200
        assert "rooms" in r.json()

    def test_availability_bad_date(self):
        r = requests.get(f"{API}/public/availability", params={"tanggal": "invalid"})
        assert r.status_code == 400

    def test_public_booking_standard_calc(self, owner_h):
        d = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
        avail = requests.get(f"{API}/public/availability", params={"tanggal": d, "tipe": "Standard"}).json()
        if not avail["rooms"]:
            pytest.skip("no available standard")
        room = avail["rooms"][0]
        r = requests.post(f"{API}/public/bookings", json={
            "nama_tamu": "TEST_Public_Std", "no_hp": "081234567890",
            "no_identitas": "TEST_PUB_STD", "jumlah_tamu": 1,
            "room_id": room["id"], "tanggal": d, "jam_checkin": "13:00",
        })
        assert r.status_code == 200, r.text
        bk = r.json()
        try:
            assert bk["status"] == "booking_pending"
            assert bk["payment_status"] == "pending"
            assert bk["source"] == "online"
            assert bk["subtotal"] == 120000
            assert bk["service_fee"] == 3600
            assert bk["total"] == 123600
            assert bk["dp_min"] == 61800
            assert bk["kode"].startswith("BKO-")

            # Public GET
            g = requests.get(f"{API}/public/bookings/{bk['id']}")
            assert g.status_code == 200
            assert g.json()["kode"] == bk["kode"]

            # Overlap should be rejected
            r2 = requests.post(f"{API}/public/bookings", json={
                "nama_tamu": "TEST_Overlap", "no_hp": "08", "no_identitas": "X",
                "jumlah_tamu": 1, "room_id": room["id"], "tanggal": d, "jam_checkin": "14:00",
            })
            assert r2.status_code == 400
            assert "dibooking" in r2.text.lower() or "tersedia" in r2.text.lower()
        finally:
            requests.delete(f"{API}/bookings/{bk['id']}", headers=owner_h)

    def test_public_booking_cottage_calc(self, owner_h):
        d = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        avail = requests.get(f"{API}/public/availability", params={"tanggal": d, "tipe": "Cottage"}).json()
        if not avail["rooms"]:
            pytest.skip("no available cottage")
        room = avail["rooms"][0]
        r = requests.post(f"{API}/public/bookings", json={
            "nama_tamu": "TEST_Public_Cot", "no_hp": "081", "no_identitas": "TEST_PUB_COT",
            "jumlah_tamu": 2, "room_id": room["id"], "tanggal": d, "jam_checkin": "14:00",
        })
        assert r.status_code == 200, r.text
        bk = r.json()
        try:
            assert bk["subtotal"] == 140000
            assert bk["service_fee"] == 4200
            assert bk["total"] == 144200
            assert bk["dp_min"] == 72100
        finally:
            requests.delete(f"{API}/bookings/{bk['id']}", headers=owner_h)

    def test_public_booking_invalid_date(self):
        r = requests.post(f"{API}/public/bookings", json={
            "nama_tamu": "TEST_Bad", "no_hp": "08", "no_identitas": "X",
            "jumlah_tamu": 1, "room_id": "any", "tanggal": "bad-date", "jam_checkin": "13:00",
        })
        # could be 404 room or 400 date — accept both as validation failure
        assert r.status_code in (400, 404)

    def test_public_booking_room_not_kosong(self, owner_h, rooms):
        # find a room currently NOT kosong (day_use/menginap)
        busy = next((r for r in rooms if r["status"] != "kosong"), None)
        if not busy:
            pytest.skip("no busy room")
        d = (datetime.now(timezone.utc) + timedelta(days=4)).date().isoformat()
        r = requests.post(f"{API}/public/bookings", json={
            "nama_tamu": "TEST_Busy", "no_hp": "08", "no_identitas": "X",
            "jumlah_tamu": 1, "room_id": busy["id"], "tanggal": d, "jam_checkin": "13:00",
        })
        assert r.status_code == 400
        assert "tersedia" in r.text.lower()
