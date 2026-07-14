"""Iter17: cancel-with-fee (3 statuses) + no-show endpoint tests."""
import os
import uuid
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    # fallback to frontend .env directly
    from pathlib import Path
    for line in Path('/app/frontend/.env').read_text().splitlines():
        if line.startswith('REACT_APP_BACKEND_URL='):
            BASE_URL = line.split('=', 1)[1].strip().rstrip('/')

# Always read from backend/.env (env not propagated to pytest worker)
from pathlib import Path
MONGO_URL = ''
DB_NAME = ''
for line in Path('/app/backend/.env').read_text().splitlines():
    if line.startswith('MONGO_URL='):
        MONGO_URL = line.split('=', 1)[1].strip().strip('"').strip("'")
    if line.startswith('DB_NAME='):
        DB_NAME = line.split('=', 1)[1].strip().strip('"').strip("'")
assert MONGO_URL.startswith("mongodb"), f"Bad MONGO_URL: {MONGO_URL!r}"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "owner", "password": "owner123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def room(headers):
    r = requests.get(f"{BASE_URL}/api/rooms", headers=headers)
    assert r.status_code == 200
    rooms = [x for x in r.json() if x["status"] == "kosong"]
    assert rooms, "Need at least one kosong room"
    return rooms[0]


def _make_booking(headers, room, days_offset=2):
    """Create an 'aktif' walk-in booking far in future to avoid overlap."""
    from datetime import datetime, timezone, timedelta
    start = (datetime.now(timezone.utc) + timedelta(days=days_offset)).replace(microsecond=0)
    end = start + timedelta(hours=6)
    payload = {
        "room_id": room["id"], "tipe": "day_use",
        "nama_tamu": f"TEST_{uuid.uuid4().hex[:6]}",
        "no_hp": "08123", "no_identitas": "", "kendaraan": "",
        "jumlah_tamu": 1,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": "iter17 test",
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _mongo_set(bid, fields):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.bookings.update_one({"id": bid}, {"$set": fields})
    client.close()


def mongo_set(bid, fields):
    asyncio.run(_mongo_set(bid, fields))


async def _mongo_cleanup():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.bookings.delete_many({"nama_tamu": {"$regex": "^TEST_"}})
    client.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    # Pre-cleanup: remove any leftover TEST_ bookings from prior failed runs
    asyncio.run(_mongo_cleanup())
    yield
    asyncio.run(_mongo_cleanup())


# ---------------- cancel-with-fee ----------------
class TestCancelWithFee:
    def test_cancel_aktif_no_refund(self, headers, room):
        bk = _make_booking(headers, room, days_offset=2)
        # Inject total to verify fee calculation
        mongo_set(bk["id"], {"total": 100000})
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={"alasan": "test"}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["fee"] == 10000
        assert data["refund_amount"] == 0
        assert data["previous_status"] == "aktif"
        # Verify persistence via list
        lst = requests.get(f"{BASE_URL}/api/bookings", headers=headers, params={"status": "cancelled"}).json()
        assert any(b["id"] == bk["id"] for b in lst)

    def test_cancel_booking_pending_no_refund(self, headers, room):
        bk = _make_booking(headers, room, days_offset=3)
        mongo_set(bk["id"], {"status": "booking_pending", "total": 50000, "payment_status": "pending"})
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={"alasan": ""}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["fee"] == 5000
        assert d["refund_amount"] == 0
        assert d["previous_status"] == "booking_pending"

    def test_cancel_booking_paid_refund(self, headers, room):
        bk = _make_booking(headers, room, days_offset=4)
        # simulate Midtrans paid DP
        mongo_set(bk["id"], {
            "status": "booking_paid", "payment_status": "paid",
            "total": 100000, "amount_due": 61800,
        })
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={"alasan": ""}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["fee"] == 10000
        # refund = paid(61800) - fee(10000) = 51800
        assert d["refund_amount"] == 51800
        assert d["original_paid"] == 61800
        assert d["previous_status"] == "booking_paid"

    def test_cancel_total_zero_no_crash(self, headers, room):
        bk = _make_booking(headers, room, days_offset=5)
        mongo_set(bk["id"], {"total": 0})
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["fee"] == 0
        assert d["refund_amount"] == 0

    def test_cancel_not_found(self, headers):
        r = requests.post(f"{BASE_URL}/api/bookings/nonexistent-{uuid.uuid4().hex}/cancel-with-fee",
                          json={}, headers=headers)
        assert r.status_code == 404

    def test_cancel_already_cancelled_400(self, headers, room):
        bk = _make_booking(headers, room, days_offset=6)
        mongo_set(bk["id"], {"status": "cancelled"})
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={}, headers=headers)
        assert r.status_code == 400


# ---------------- no-show ----------------
class TestNoShow:
    def test_noshow_booking_paid(self, headers, room):
        bk = _make_booking(headers, room, days_offset=7)
        mongo_set(bk["id"], {
            "status": "booking_paid", "payment_status": "paid",
            "total": 100000, "amount_due": 61800,
        })
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/no-show",
                          json={"alasan": "tamu tidak datang"}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["amount_retained"] == 61800
        # Verify status via list endpoint
        lst = requests.get(f"{BASE_URL}/api/bookings", headers=headers, params={"status": "no_show"}).json()
        match = [b for b in lst if b["id"] == bk["id"]]
        assert match, "Booking should now have status=no_show"
        assert match[0]["payment_status"] == "kept"

    def test_noshow_booking_pending_400(self, headers, room):
        bk = _make_booking(headers, room, days_offset=8)
        mongo_set(bk["id"], {"status": "booking_pending"})
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/no-show",
                          json={}, headers=headers)
        assert r.status_code == 400
        assert "lunas" in r.text.lower() or "booking_pending" in r.text

    def test_noshow_aktif_400(self, headers, room):
        bk = _make_booking(headers, room, days_offset=9)
        # aktif by default
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/no-show",
                          json={}, headers=headers)
        assert r.status_code == 400

    def test_noshow_not_found_404(self, headers):
        r = requests.post(f"{BASE_URL}/api/bookings/nope-{uuid.uuid4().hex}/no-show",
                          json={}, headers=headers)
        assert r.status_code == 404


# ---------------- smoke regression ----------------
class TestSmoke:
    def test_booking_widgets(self, headers):
        r = requests.get(f"{BASE_URL}/api/reports/booking-widgets", headers=headers)
        assert r.status_code == 200
        d = r.json()
        for k in ("booking_hari_ini", "booking_pending", "booking_paid",
                  "payment_total_count", "booking_online_bulan", "booking_walkin_bulan"):
            assert k in d

    def test_rooms_list(self, headers):
        r = requests.get(f"{BASE_URL}/api/rooms", headers=headers)
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_summary(self, headers):
        r = requests.get(f"{BASE_URL}/api/reports/summary", headers=headers)
        assert r.status_code == 200
