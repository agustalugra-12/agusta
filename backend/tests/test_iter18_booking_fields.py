"""Iter18: Verify POST /api/bookings persists subtotal/service_fee/total/source='walk_in',
and that cancel-with-fee computes fee from the real (non-zero) total.

Scenario from problem statement:
- Internal walk-in booking with room tarif → total includes 3% service_fee, source='walk_in'.
- Pending with total=123600 → fee=12360, refund=0, prev_status='booking_pending'.
- Paid simulation (amount_due=61800, total=123600) → fee=12360, refund=49440, payment_status='refunded'.
- Audit log entry 'cancel_with_fee' recorded.
"""
import os
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

# --- Resolve env ---
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    for line in Path('/app/frontend/.env').read_text().splitlines():
        if line.startswith('REACT_APP_BACKEND_URL='):
            BASE_URL = line.split('=', 1)[1].strip().rstrip('/')

MONGO_URL = ''
DB_NAME = ''
for line in Path('/app/backend/.env').read_text().splitlines():
    if line.startswith('MONGO_URL='):
        MONGO_URL = line.split('=', 1)[1].strip().strip('"').strip("'")
    if line.startswith('DB_NAME='):
        DB_NAME = line.split('=', 1)[1].strip().strip('"').strip("'")
assert BASE_URL and MONGO_URL and DB_NAME


# --- Fixtures ---
@pytest.fixture(scope="module")
def headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "owner", "password": "owner123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def room(headers):
    r = requests.get(f"{BASE_URL}/api/rooms", headers=headers)
    assert r.status_code == 200
    rooms = [x for x in r.json() if x["status"] == "kosong"]
    assert rooms, "Need at least one kosong room"
    return rooms[0]


def _make_booking(headers, room, days_offset=20):
    start = (datetime.now(timezone.utc) + timedelta(days=days_offset)).replace(microsecond=0)
    end = start + timedelta(hours=6)
    payload = {
        "room_id": room["id"], "tipe": "day_use",
        "nama_tamu": f"TEST_{uuid.uuid4().hex[:6]}",
        "no_hp": "08123", "no_identitas": "", "kendaraan": "",
        "jumlah_tamu": 1,
        "jam_mulai": start.isoformat(), "jam_selesai": end.isoformat(),
        "catatan": "iter18",
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _mongo_set(bid, fields):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.bookings.update_one({"id": bid}, {"$set": fields})
    client.close()


async def _mongo_cleanup():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.bookings.delete_many({"nama_tamu": {"$regex": "^TEST_"}})
    client.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    asyncio.run(_mongo_cleanup())
    yield
    asyncio.run(_mongo_cleanup())


# === Tests ===

class TestCreateBookingFields:
    """Verify create_booking persists subtotal/service_fee/total/source for internal bookings."""

    def test_create_returns_subtotal_service_fee_total_source(self, headers, room):
        bk = _make_booking(headers, room, days_offset=20)
        assert "subtotal" in bk and isinstance(bk["subtotal"], int) and bk["subtotal"] > 0
        assert "service_fee" in bk and isinstance(bk["service_fee"], int)
        assert "total" in bk and bk["total"] == bk["subtotal"] + bk["service_fee"]
        assert bk["source"] == "walk_in"
        # service_fee ≈ 3% of subtotal
        assert bk["service_fee"] == round(bk["subtotal"] * 0.03)

    def test_get_booking_persists_fields(self, headers, room):
        bk = _make_booking(headers, room, days_offset=21)
        # Verify via GET /api/bookings (list)
        lst = requests.get(f"{BASE_URL}/api/bookings", headers=headers).json()
        match = next((x for x in lst if x["id"] == bk["id"]), None)
        assert match is not None
        for k in ("subtotal", "service_fee", "total", "source"):
            assert k in match, f"Missing {k} in persisted booking"
        assert match["source"] == "walk_in"
        assert match["total"] > 0  # critical: NOT zero (this was the root cause)


class TestCancelUsesRealTotal:
    """Cancel-with-fee must compute fee from persisted total (not 0)."""

    def test_pending_fee_nonzero_no_refund(self, headers, room):
        bk = _make_booking(headers, room, days_offset=22)
        # Inject scenario from PRD: total=123600, pending
        asyncio.run(_mongo_set(bk["id"], {
            "status": "booking_pending", "payment_status": "pending",
            "total": 123600,
        }))
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={"alasan": "uji pending"}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["fee"] == 12360, d
        assert d["refund_amount"] == 0
        assert d["previous_status"] == "booking_pending"
        # Persistence check
        lst = requests.get(f"{BASE_URL}/api/bookings", headers=headers, params={"status": "cancelled"}).json()
        match = next((x for x in lst if x["id"] == bk["id"]), None)
        assert match is not None
        assert match["status"] == "cancelled"
        assert match["cancel_fee"] == 12360

    def test_paid_fee_and_refund(self, headers, room):
        bk = _make_booking(headers, room, days_offset=23)
        asyncio.run(_mongo_set(bk["id"], {
            "status": "booking_paid", "payment_status": "paid",
            "total": 123600, "amount_due": 61800,
        }))
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={"alasan": "uji paid"}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["fee"] == 12360
        assert d["refund_amount"] == 49440  # 61800 - 12360
        assert d["original_paid"] == 61800
        assert d["previous_status"] == "booking_paid"
        # Persist
        lst = requests.get(f"{BASE_URL}/api/bookings", headers=headers, params={"status": "cancelled"}).json()
        match = next((x for x in lst if x["id"] == bk["id"]), None)
        assert match and match["payment_status"] == "refunded"

    def test_aktif_fresh_booking_uses_total(self, headers, room):
        """Fresh aktif booking (no mongo override) should produce fee>0 from create_booking total."""
        bk = _make_booking(headers, room, days_offset=24)
        expected_total = bk["total"]
        expected_fee = round(expected_total * 0.10)
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                          json={}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["fee"] == expected_fee
        assert d["fee"] > 0, "Fee should be >0 since fresh booking has non-zero total (this was the bug)"
        assert d["previous_status"] == "aktif"


class TestAuditLog:
    def test_cancel_logs_activity(self, headers, room):
        bk = _make_booking(headers, room, days_offset=25)
        asyncio.run(_mongo_set(bk["id"], {"total": 100000}))
        requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel-with-fee",
                      json={"alasan": "audit-check"}, headers=headers)
        r = requests.get(f"{BASE_URL}/api/audit-log", headers=headers)
        assert r.status_code == 200
        acts = r.json()
        # Find cancel_with_fee entry referencing booking kode
        matched = [a for a in acts if a.get("action") == "cancel_with_fee" and bk["kode"] in (a.get("detail") or "")]
        assert matched, "Audit log should contain cancel_with_fee for this booking"


class TestNoShowSmoke:
    def test_no_show_still_works(self, headers, room):
        bk = _make_booking(headers, room, days_offset=26)
        asyncio.run(_mongo_set(bk["id"], {
            "status": "booking_paid", "payment_status": "paid",
            "total": 123600, "amount_due": 61800,
        }))
        r = requests.post(f"{BASE_URL}/api/bookings/{bk['id']}/no-show",
                          json={"alasan": "tamu tidak datang"}, headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["amount_retained"] == 61800
        lst = requests.get(f"{BASE_URL}/api/bookings", headers=headers, params={"status": "no_show"}).json()
        assert any(b["id"] == bk["id"] for b in lst)


class TestReportsCancelledQueryable:
    def test_cancelled_bookings_queryable(self, headers):
        r = requests.get(f"{BASE_URL}/api/bookings", headers=headers, params={"status": "cancelled"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_booking_widgets_smoke(self, headers):
        r = requests.get(f"{BASE_URL}/api/reports/booking-widgets", headers=headers)
        assert r.status_code == 200
