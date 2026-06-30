"""Iteration 10: Re-test overlap blocking by booking_pending/booking_paid
- Internal POST /api/bookings overlap check now includes 3 statuses
- PUT /api/bookings/{id} overlap check now includes 3 statuses
- Public booking creates booking_pending, blocks internal create on same room+date
"""
import os
import requests
import pytest
from datetime import datetime, timedelta, timezone


def _read_frontend_env():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_env()).rstrip("/")
API = f"{BASE_URL}/api"


def _login():
    r = requests.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def kosong_room(auth):
    r = requests.get(f"{API}/rooms", headers=auth)
    assert r.status_code == 200
    rooms = [x for x in r.json() if x["status"] == "kosong"]
    assert rooms, "Need at least one kosong room"
    return rooms[0]


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def _create_public(room_id, tanggal, jam_checkin="14:00", nama="TEST_ITER10_PUB"):
    """Public booking uses {tanggal:'YYYY-MM-DD', jam_checkin:'HH:MM'}, 6h fixed."""
    body = {
        "room_id": room_id,
        "tanggal": tanggal,
        "jam_checkin": jam_checkin,
        "nama_tamu": nama,
        "no_hp": "0812000999",
        "no_identitas": "3300000000009999",
        "jumlah_tamu": 1,
    }
    return requests.post(f"{API}/public/bookings", json=body)


def _delete_booking(bid, auth):
    return requests.delete(f"{API}/bookings/{bid}", headers=auth)


# ------------- TEST 1: Internal POST overlap blocked by booking_pending -------------
def test_internal_create_overlap_blocked_by_pending(kosong_room, auth):
    tanggal = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    # Public booking: 14:00 WIB → 14:00+07 = 07:00 UTC, +6h = 13:00 UTC
    pub = _create_public(kosong_room["id"], tanggal, "14:00", "TEST_ITER10_PUB1")
    assert pub.status_code == 200, pub.text
    pub_id = pub.json()["id"]
    assert pub.json()["status"] == "booking_pending"

    try:
        # Internal day_use overlap (same window 07:00-13:00 UTC)
        start = datetime.fromisoformat(pub.json()["jam_mulai"])
        end = datetime.fromisoformat(pub.json()["jam_selesai"])
        body = {
            "room_id": kosong_room["id"], "tipe": "day_use",
            "nama_tamu": "TEST_ITER10_INT", "no_hp": "0812000011",
            "no_identitas": "3300000000000011", "jumlah_tamu": 1,
            "jam_mulai": _iso(start + timedelta(hours=1)),
            "jam_selesai": _iso(end - timedelta(hours=1)),
        }
        r = requests.post(f"{API}/bookings", json=body, headers=auth)
        assert r.status_code == 400, f"Expected 400 overlap, got {r.status_code}: {r.text}"
        assert "dibooking" in r.json().get("detail", "").lower()
    finally:
        _delete_booking(pub_id, auth)


# ------------- TEST 2: Delete public booking → internal create succeeds -------------
def test_internal_create_succeeds_after_public_deleted(kosong_room, auth):
    tanggal = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
    pub = _create_public(kosong_room["id"], tanggal, "10:00", "TEST_ITER10_PUB2")
    assert pub.status_code == 200, pub.text
    pub_id = pub.json()["id"]
    start = datetime.fromisoformat(pub.json()["jam_mulai"])
    end = datetime.fromisoformat(pub.json()["jam_selesai"])

    int_body = {
        "room_id": kosong_room["id"], "tipe": "day_use",
        "nama_tamu": "TEST_ITER10_INT2", "no_hp": "0812000021",
        "no_identitas": "3300000000000021", "jumlah_tamu": 1,
        "jam_mulai": _iso(start), "jam_selesai": _iso(end),
    }
    # Should be blocked
    blocked = requests.post(f"{API}/bookings", json=int_body, headers=auth)
    assert blocked.status_code == 400, blocked.text

    # Delete public booking
    d = _delete_booking(pub_id, auth)
    assert d.status_code in (200, 204), d.text

    # Now internal should succeed
    ok = requests.post(f"{API}/bookings", json=int_body, headers=auth)
    assert ok.status_code == 200, ok.text
    new_id = ok.json()["id"]
    _delete_booking(new_id, auth)


# ------------- TEST 3: PUT /bookings/{id} overlap blocked by booking_pending -------------
def test_update_booking_overlap_blocked_by_pending(kosong_room, auth):
    # Create aktif booking at +14 days @ 18:00 UTC for 3h (after public window, fresh date)
    base = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=14)
    start_a, end_a = _iso(base), _iso(base + timedelta(hours=3))
    aktif_body = {
        "room_id": kosong_room["id"], "tipe": "day_use",
        "nama_tamu": "TEST_ITER10_AKT", "no_hp": "0812000030",
        "no_identitas": "3300000000000030", "jumlah_tamu": 1,
        "jam_mulai": start_a, "jam_selesai": end_a,
    }
    a = requests.post(f"{API}/bookings", json=aktif_body, headers=auth)
    assert a.status_code == 200, a.text
    aktif_id = a.json()["id"]

    # Create public booking_pending same day, jam_checkin 14:00 WIB → 07:00 UTC, ends 13:00 UTC
    tanggal = base.strftime("%Y-%m-%d")
    pub = _create_public(kosong_room["id"], tanggal, "14:00", "TEST_ITER10_PUB3")
    assert pub.status_code == 200, pub.text
    pub_id = pub.json()["id"]

    try:
        # Update aktif booking to overlap public_pending window
        upd_body = {**aktif_body,
                    "jam_mulai": pub.json()["jam_mulai"],
                    "jam_selesai": pub.json()["jam_selesai"]}
        u = requests.put(f"{API}/bookings/{aktif_id}", json=upd_body, headers=auth)
        assert u.status_code == 400, f"Expected 400, got {u.status_code}: {u.text}"
        assert "dibooking" in u.json().get("detail", "").lower()
    finally:
        _delete_booking(aktif_id, auth)
        _delete_booking(pub_id, auth)


# ------------- TEST 4: Smoke — public booking service fee 3% -------------
def test_public_booking_service_fee_smoke(kosong_room, auth):
    tanggal = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")
    pub = _create_public(kosong_room["id"], tanggal, "09:00", "TEST_ITER10_FEE")
    assert pub.status_code == 200, pub.text
    d = pub.json()
    assert d.get("service_fee", 0) > 0
    assert d["total"] == d["subtotal"] + d["service_fee"]
    assert d["dp_min"] == round(d["total"] * 0.5)
    _delete_booking(d["id"], auth)


# ------------- TEST 5: Smoke — /bookings/availability slots -------------
def test_availability_smoke(kosong_room, auth):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = requests.get(f"{API}/bookings/availability",
                     params={"room_id": kosong_room["id"], "from_date": today, "days": 7},
                     headers=auth)
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["slots"]) == 7
    assert all("available" in s and "date" in s for s in j["slots"])


# ------------- TEST 6: Smoke — availability marks public booking date as booked -------------
def test_availability_marks_public_booking(kosong_room, auth):
    tanggal = (datetime.now(timezone.utc) + timedelta(days=12)).strftime("%Y-%m-%d")
    pub = _create_public(kosong_room["id"], tanggal, "10:00", "TEST_ITER10_AVAIL")
    assert pub.status_code == 200, pub.text
    pub_id = pub.json()["id"]
    try:
        r = requests.get(f"{API}/bookings/availability",
                         params={"room_id": kosong_room["id"],
                                 "from_date": (datetime.now(timezone.utc) + timedelta(days=11)).strftime("%Y-%m-%d"),
                                 "days": 3},
                         headers=auth)
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        booked = [s for s in slots if s["date"] == tanggal]
        assert booked and booked[0]["available"] is False, f"Expected {tanggal} booked, got {slots}"
        assert "BKO" in booked[0]["reason"] or "Booking" in booked[0]["reason"]
    finally:
        _delete_booking(pub_id, auth)
