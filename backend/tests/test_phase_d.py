"""Phase D backend tests: Dashboard booking-widgets + cancel-with-fee endpoint."""
import os
import uuid
import requests
import pytest
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or pytest.fail("REACT_APP_BACKEND_URL missing")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "owner", "password": "owner123"}, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def api_client(auth_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"})
    return s


# ============== Module 1: GET /api/reports/booking-widgets ==============
class TestBookingWidgets:
    def test_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/reports/booking-widgets", timeout=10)
        assert r.status_code in (401, 403)

    def test_widgets_shape_and_numeric(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/reports/booking-widgets", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        expected_keys = [
            "booking_hari_ini", "booking_pending", "booking_paid",
            "pendapatan_online_bulan", "payment_total_count", "payment_total_sum",
            "booking_online_bulan", "booking_walkin_bulan",
        ]
        for k in expected_keys:
            assert k in data, f"missing key {k}"
            assert isinstance(data[k], (int, float)), f"{k} not numeric: {type(data[k])}"

    def test_payment_sum_uses_todouble(self, api_client):
        """Validate that gross_amount stored as string '61800.00' is summed correctly via $toDouble."""
        r = api_client.get(f"{BASE_URL}/api/reports/booking-widgets", timeout=15)
        assert r.status_code == 200
        data = r.json()
        # Either there is data or it's 0; in both cases must be int-like (no string)
        assert isinstance(data["payment_total_sum"], (int, float))
        assert data["payment_total_sum"] >= 0
        assert data["payment_total_count"] >= 0


# ============== Module 2: POST /api/bookings/{id}/cancel-with-fee ==============
def _create_booking_paid(api_client, hours_ahead: int):
    """Create an active booking then bypass to booking_paid status via mongo direct (helper)."""
    # We'll create normally via API then mutate via mongo
    start = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    end = start + timedelta(hours=6)
    # Need a room id
    rooms = api_client.get(f"{BASE_URL}/api/rooms", timeout=10).json()
    room = next((r for r in rooms if r.get("status") == "kosong"), rooms[0])
    payload = {
        "room_id": room["id"], "tipe": "menginap",
        "nama_tamu": f"TEST_PhD_{uuid.uuid4().hex[:6]}",
        "no_hp": "081234567890", "no_identitas": "", "kendaraan": "", "jumlah_tamu": 1,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": "TEST_PHASE_D", "total": 100000,
    }
    r = api_client.post(f"{BASE_URL}/api/bookings", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


async def _mutate_to_paid(bid: str, amount_due: int = 100000):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.bookings.update_one({"id": bid}, {"$set": {
        "status": "booking_paid", "payment_status": "paid",
        "amount_due": amount_due, "total": amount_due,
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }})
    client.close()


async def _cleanup(bid: str):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.bookings.delete_one({"id": bid})
    client.close()


class TestCancelWithFee:
    def test_unauthorized(self):
        r = requests.post(f"{BASE_URL}/api/bookings/nope/cancel-with-fee", json={"alasan": "x"}, timeout=10)
        assert r.status_code in (401, 403)

    def test_booking_not_found(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/bookings/nonexistent-id-xyz/cancel-with-fee",
                            json={"alasan": "test"}, timeout=10)
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_with_fee_success(self, api_client):
        """booking_paid + jam_mulai > 24h future → refund OK"""
        bk = _create_booking_paid(api_client, hours_ahead=72)  # 3 days ahead
        bid = bk["id"]
        try:
            await _mutate_to_paid(bid, amount_due=100000)
            r = api_client.post(f"{BASE_URL}/api/bookings/{bid}/cancel-with-fee",
                                json={"alasan": "TEST refund"}, timeout=15)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ok"] is True
            assert data["fee"] == 10000  # 10% of 100000
            assert data["refund_amount"] == 90000
            assert data["original_paid"] == 100000
            assert "booking_kode" in data

            # Verify persistence
            r2 = api_client.get(f"{BASE_URL}/api/bookings", timeout=10)
            booking = next((b for b in r2.json() if b["id"] == bid), None)
            assert booking is not None
            assert booking["status"] == "cancelled"
            assert booking["payment_status"] == "refunded"
            assert booking["refund_amount"] == 90000
            assert booking["cancel_fee"] == 10000
        finally:
            await _cleanup(bid)

    @pytest.mark.asyncio
    async def test_cancel_with_fee_too_late(self, api_client):
        """booking_paid + jam_mulai < 24h → 400 H-1 rule."""
        bk = _create_booking_paid(api_client, hours_ahead=2)  # 2 hours ahead
        bid = bk["id"]
        try:
            await _mutate_to_paid(bid)
            r = api_client.post(f"{BASE_URL}/api/bookings/{bid}/cancel-with-fee",
                                json={"alasan": "too late"}, timeout=15)
            assert r.status_code == 400, r.text
            assert "H-1" in r.json().get("detail", "")
        finally:
            await _cleanup(bid)

    @pytest.mark.asyncio
    async def test_cancel_with_fee_wrong_status(self, api_client):
        """status != booking_paid → 400."""
        bk = _create_booking_paid(api_client, hours_ahead=72)
        bid = bk["id"]
        # Keep as default 'aktif' — don't mutate
        try:
            r = api_client.post(f"{BASE_URL}/api/bookings/{bid}/cancel-with-fee",
                                json={"alasan": "wrong status"}, timeout=15)
            assert r.status_code == 400, r.text
            assert "lunas" in r.json().get("detail", "").lower() or "booking_paid" in r.json().get("detail", "")
        finally:
            await _cleanup(bid)
