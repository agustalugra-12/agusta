"""Regression tests for Pelangi Homestay booking edit feature.

Covers:
  - Auth login (owner)
  - Create booking
  - PUT /api/bookings/{id}  (THE FEATURE UNDER TEST — currently MISSING on backend)
  - GET /api/bookings to verify persistence
  - Cancel booking
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pwa-kasir-hotel.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def empty_room(headers):
    """Pick first room with status == 'kosong'."""
    r = requests.get(f"{API}/rooms", headers=headers, timeout=15)
    assert r.status_code == 200
    for room in r.json():
        if room["status"] == "kosong":
            return room
    pytest.skip("No empty room available for test")


@pytest.fixture(scope="module")
def created_booking(headers, empty_room):
    """Create a booking we own for edit/cancel testing."""
    now = datetime.now(timezone.utc) + timedelta(days=10)  # future window to avoid overlap
    payload = {
        "tipe": "day_use",
        "room_id": empty_room["id"],
        "nama_tamu": f"TEST_Tamu_{uuid.uuid4().hex[:6]}",
        "no_hp": "081200000000",
        "no_identitas": "",
        "kendaraan": "",
        "jumlah_tamu": 1,
        "jam_mulai": now.isoformat(),
        "jam_selesai": (now + timedelta(hours=6)).isoformat(),
        "catatan": "TEST seed",
    }
    r = requests.post(f"{API}/bookings", headers=headers, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    bk = r.json()
    yield bk
    # cleanup — cancel if still aktif
    try:
        requests.delete(f"{API}/bookings/{bk['id']}", headers=headers, timeout=10)
    except Exception:
        pass


class TestBookingAuth:
    def test_login_owner(self, token):
        assert isinstance(token, str) and len(token) > 20


class TestBookingCreateAndList:
    def test_create_persists(self, created_booking, headers):
        bk_id = created_booking["id"]
        r = requests.get(f"{API}/bookings", headers=headers, params={"status": "aktif"}, timeout=10)
        assert r.status_code == 200
        ids = [b["id"] for b in r.json()]
        assert bk_id in ids


class TestBookingEdit:
    """The critical feature being validated."""

    def test_put_endpoint_exists(self, headers, created_booking):
        """PUT /api/bookings/{id} should accept update payload."""
        bk_id = created_booking["id"]
        payload = {
            "tipe": "day_use",
            "room_id": created_booking["room_id"],
            "nama_tamu": "TEST_Tamu_Updated",
            "no_hp": "081200000099",
            "no_identitas": "",
            "kendaraan": "",
            "jumlah_tamu": 2,
            "jam_mulai": created_booking["jam_mulai"],
            "jam_selesai": created_booking["jam_selesai"],
            "catatan": "TEST updated",
        }
        r = requests.put(f"{API}/bookings/{bk_id}", headers=headers, json=payload, timeout=15)
        # Currently expected to FAIL — backend endpoint not implemented.
        assert r.status_code == 200, (
            f"PUT /api/bookings/{{id}} returned {r.status_code}: {r.text}. "
            "Backend endpoint missing — frontend Edit button fails."
        )

    def test_update_persisted_via_get(self, headers, created_booking):
        """After PUT, GET should reflect new nama_tamu."""
        bk_id = created_booking["id"]
        r = requests.get(f"{API}/bookings", headers=headers, timeout=10)
        bk = next((b for b in r.json() if b["id"] == bk_id), None)
        assert bk is not None
        assert bk["nama_tamu"] == "TEST_Tamu_Updated", f"nama_tamu not persisted: {bk.get('nama_tamu')}"


class TestBookingCancel:
    def test_cancel_booking(self, headers, empty_room):
        # create a throwaway booking
        now = datetime.now(timezone.utc) + timedelta(days=20)
        payload = {
            "tipe": "day_use",
            "room_id": empty_room["id"],
            "nama_tamu": f"TEST_Cancel_{uuid.uuid4().hex[:6]}",
            "no_hp": "", "no_identitas": "", "kendaraan": "", "jumlah_tamu": 1,
            "jam_mulai": now.isoformat(),
            "jam_selesai": (now + timedelta(hours=6)).isoformat(),
            "catatan": "",
        }
        r = requests.post(f"{API}/bookings", headers=headers, json=payload, timeout=15)
        assert r.status_code == 200
        bid = r.json()["id"]

        r2 = requests.delete(f"{API}/bookings/{bid}", headers=headers, timeout=10)
        assert r2.status_code == 200

        r3 = requests.get(f"{API}/bookings", headers=headers, params={"status": "dibatalkan"}, timeout=10)
        assert any(b["id"] == bid for b in r3.json())
