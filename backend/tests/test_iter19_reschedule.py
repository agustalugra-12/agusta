"""
Iter19 backend tests:
- Reschedule (PUT /api/bookings/{id}) accepts status in {aktif, booking_pending, booking_paid}
- Reschedule rejects status cancelled / no_show / cancel_with_fee
- Overlap check works when rescheduling a booking_paid into a taken slot
- Smoke regression: cancel_with_fee (3 statuses), no_show, create_booking total/source
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

def _load_env(path):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass

_load_env("/app/frontend/.env")
_load_env("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

API = f"{BASE_URL}/api"


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def first_room(session):
    r = session.get(f"{API}/rooms", timeout=15)
    assert r.status_code == 200
    rooms = r.json()
    assert len(rooms) >= 2, "need at least 2 rooms for overlap test"
    return rooms


def _future_iso(days_from_now: int, hour: int = 14):
    base = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    base = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    return base.isoformat()


def _create_walkin(session, room, days_from_now, hours=4, name="TEST_ITER19"):
    start = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    start = start.replace(hour=10, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=hours)
    payload = {
        "room_id": room["id"],
        "tipe": "day_use",
        "nama_tamu": name,
        "no_hp": "081200000000",
        "no_identitas": "",
        "kendaraan": "",
        "jumlah_tamu": 1,
        "jam_mulai": start.isoformat(),
        "jam_selesai": end.isoformat(),
        "catatan": "iter19 test",
    }
    r = session.post(f"{API}/bookings", json=payload, timeout=15)
    assert r.status_code == 200, f"create_booking failed: {r.status_code} {r.text}"
    return r.json(), start, end


async def _set_status(bid: str, status: str, extras: dict | None = None):
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    upd = {"status": status}
    if extras:
        upd.update(extras)
    await db.bookings.update_one({"id": bid}, {"$set": upd})
    cli.close()


def set_status(bid: str, status: str, extras: dict | None = None):
    asyncio.run(_set_status(bid, status, extras))


async def _cleanup():
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    await db.bookings.delete_many({"nama_tamu": {"$regex": "^TEST_ITER19"}})
    cli.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup_module():
    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


# ---------------- reschedule tests ----------------
class TestRescheduleStatusGuard:
    def test_reschedule_aktif_ok(self, session, first_room):
        booking, s, e = _create_walkin(session, first_room[0], 30)
        new_start = (s + timedelta(hours=2)).isoformat()
        new_end = (e + timedelta(hours=2)).isoformat()
        payload = {**{k: booking[k] for k in (
            "room_id", "tipe", "nama_tamu", "no_hp", "no_identitas",
            "kendaraan", "jumlah_tamu", "catatan")},
            "jam_mulai": new_start, "jam_selesai": new_end}
        r = session.put(f"{API}/bookings/{booking['id']}", json=payload, timeout=15)
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        # GET back to verify persisted
        g = session.get(f"{API}/bookings", timeout=15)
        assert g.status_code == 200
        match = [x for x in g.json() if x["id"] == booking["id"]]
        assert match and match[0]["jam_mulai"] == new_start

    def test_reschedule_booking_pending_ok(self, session, first_room):
        booking, s, e = _create_walkin(session, first_room[0], 31, name="TEST_ITER19_PEND")
        set_status(booking["id"], "booking_pending")
        new_start = (s + timedelta(hours=3)).isoformat()
        new_end = (e + timedelta(hours=3)).isoformat()
        payload = {**{k: booking[k] for k in (
            "room_id", "tipe", "nama_tamu", "no_hp", "no_identitas",
            "kendaraan", "jumlah_tamu", "catatan")},
            "jam_mulai": new_start, "jam_selesai": new_end}
        r = session.put(f"{API}/bookings/{booking['id']}", json=payload, timeout=15)
        assert r.status_code == 200, r.text

    def test_reschedule_booking_paid_ok(self, session, first_room):
        booking, s, e = _create_walkin(session, first_room[0], 32, name="TEST_ITER19_PAID")
        set_status(booking["id"], "booking_paid", {"amount_due": booking.get("total", 100000)})
        new_start = (s + timedelta(hours=5)).isoformat()
        new_end = (e + timedelta(hours=5)).isoformat()
        payload = {**{k: booking[k] for k in (
            "room_id", "tipe", "nama_tamu", "no_hp", "no_identitas",
            "kendaraan", "jumlah_tamu", "catatan")},
            "jam_mulai": new_start, "jam_selesai": new_end}
        r = session.put(f"{API}/bookings/{booking['id']}", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["jam_mulai"] == new_start

    def test_reschedule_cancelled_rejected(self, session, first_room):
        booking, s, e = _create_walkin(session, first_room[0], 33, name="TEST_ITER19_CANC")
        set_status(booking["id"], "cancelled")
        payload = {**{k: booking[k] for k in (
            "room_id", "tipe", "nama_tamu", "no_hp", "no_identitas",
            "kendaraan", "jumlah_tamu", "catatan")},
            "jam_mulai": booking["jam_mulai"], "jam_selesai": booking["jam_selesai"]}
        r = session.put(f"{API}/bookings/{booking['id']}", json=payload, timeout=15)
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"

    def test_reschedule_no_show_rejected(self, session, first_room):
        booking, s, e = _create_walkin(session, first_room[0], 34, name="TEST_ITER19_NS")
        set_status(booking["id"], "no_show")
        payload = {**{k: booking[k] for k in (
            "room_id", "tipe", "nama_tamu", "no_hp", "no_identitas",
            "kendaraan", "jumlah_tamu", "catatan")},
            "jam_mulai": booking["jam_mulai"], "jam_selesai": booking["jam_selesai"]}
        r = session.put(f"{API}/bookings/{booking['id']}", json=payload, timeout=15)
        assert r.status_code == 400


class TestRescheduleOverlap:
    def test_paid_reschedule_into_taken_slot_rejected(self, session, first_room):
        # Booking A in room0 days+40
        a, sa, ea = _create_walkin(session, first_room[0], 40, name="TEST_ITER19_A")
        # Booking B in room0 days+41
        b, sb, eb = _create_walkin(session, first_room[0], 41, name="TEST_ITER19_B")
        # Promote B to booking_paid
        set_status(b["id"], "booking_paid")
        # Try to reschedule B into A's slot
        payload = {**{k: b[k] for k in (
            "room_id", "tipe", "nama_tamu", "no_hp", "no_identitas",
            "kendaraan", "jumlah_tamu", "catatan")},
            "jam_mulai": a["jam_mulai"], "jam_selesai": a["jam_selesai"]}
        r = session.put(f"{API}/bookings/{b['id']}", json=payload, timeout=15)
        assert r.status_code == 400
        assert "dibooking" in r.text.lower() or "overlap" in r.text.lower()

    def test_paid_reschedule_into_free_slot_ok(self, session, first_room):
        b, sb, eb = _create_walkin(session, first_room[0], 45, name="TEST_ITER19_FREE")
        set_status(b["id"], "booking_paid")
        new_start = (sb + timedelta(days=2)).isoformat()
        new_end = (eb + timedelta(days=2)).isoformat()
        payload = {**{k: b[k] for k in (
            "room_id", "tipe", "nama_tamu", "no_hp", "no_identitas",
            "kendaraan", "jumlah_tamu", "catatan")},
            "jam_mulai": new_start, "jam_selesai": new_end}
        r = session.put(f"{API}/bookings/{b['id']}", json=payload, timeout=15)
        assert r.status_code == 200, r.text


# ---------------- smoke regression ----------------
class TestSmokeRegression:
    def test_create_booking_persists_total_source(self, session, first_room):
        booking, s, e = _create_walkin(session, first_room[1], 50, name="TEST_ITER19_SMK")
        assert booking.get("source") == "walk_in"
        assert booking.get("total", 0) > 0
        assert booking.get("subtotal", 0) > 0
        assert booking.get("service_fee", 0) >= 0

    def test_cancel_with_fee_aktif(self, session, first_room):
        booking, _, _ = _create_walkin(session, first_room[1], 51, name="TEST_ITER19_CWF_A")
        r = session.post(f"{API}/bookings/{booking['id']}/cancel-with-fee", json={"alasan": "test"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("fee", 0) > 0

    def test_cancel_with_fee_pending(self, session, first_room):
        booking, _, _ = _create_walkin(session, first_room[1], 52, name="TEST_ITER19_CWF_P")
        set_status(booking["id"], "booking_pending")
        r = session.post(f"{API}/bookings/{booking['id']}/cancel-with-fee", json={"alasan": "test"}, timeout=15)
        assert r.status_code == 200, r.text

    def test_cancel_with_fee_paid(self, session, first_room):
        booking, _, _ = _create_walkin(session, first_room[1], 53, name="TEST_ITER19_CWF_PD")
        set_status(booking["id"], "booking_paid", {"amount_due": booking.get("total", 100000)})
        r = session.post(f"{API}/bookings/{booking['id']}/cancel-with-fee", json={"alasan": "test"}, timeout=15)
        assert r.status_code == 200, r.text

    def test_no_show(self, session, first_room):
        booking, _, _ = _create_walkin(session, first_room[1], 54, name="TEST_ITER19_NS2")
        set_status(booking["id"], "booking_paid", {"amount_due": booking.get("total", 100000)})
        r = session.post(f"{API}/bookings/{booking['id']}/no-show", json={"alasan": "tidak datang"}, timeout=15)
        assert r.status_code == 200, r.text

    def test_audit_log_has_cancel_with_fee_entries(self, session):
        r = session.get(f"{API}/audit-log", timeout=15)
        assert r.status_code == 200
        entries = r.json()
        actions = {e.get("action") for e in entries}
        assert "cancel_with_fee" in actions
