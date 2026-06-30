"""Regression tests for Move Room + BookingDetail flows on Pelangi Homestay.

Covers:
- POST /api/rooms/{room_id}/move validations (same-room, source must be day_use/menginap, target must be kosong)
- Move success when source=day_use → target=kosong (kamar lama jadi perlu_dibersihkan, kamar baru day_use, checkin updated)
- Move success when source=menginap → target=kosong (kamar lama jadi perlu_dibersihkan, kamar baru menginap, info dipindah)
- Booking lifecycle: create → reschedule (PUT) → cancel (DELETE)
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


# ---- Fixtures ----
@pytest.fixture(scope="module")
def headers():
    r = requests.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


def _get_rooms(headers):
    r = requests.get(f"{API}/rooms", headers=headers, timeout=15)
    assert r.status_code == 200
    return r.json()


def _empty_rooms(headers, n=2):
    rooms = [r for r in _get_rooms(headers) if r["status"] == "kosong"]
    if len(rooms) < n:
        pytest.skip(f"Need {n} kosong rooms, found {len(rooms)}")
    return rooms[:n]


def _set_room_status(headers, room_id, status, nama_tamu="", catatan=""):
    r = requests.put(
        f"{API}/rooms/{room_id}/status",
        headers=headers,
        json={"status": status, "nama_tamu": nama_tamu, "catatan": catatan},
        timeout=10,
    )
    assert r.status_code == 200, f"Failed to set status: {r.text}"


def _reset_room(headers, room_id):
    """Best-effort reset to kosong."""
    try:
        _set_room_status(headers, room_id, "kosong")
    except Exception:
        pass


# ---- Tests ----
class TestMoveRoomValidations:
    def test_same_room_400(self, headers):
        rooms = _empty_rooms(headers, 1)
        src = rooms[0]
        # set day_use via manual status (no checkin row needed for validation test)
        _set_room_status(headers, src["id"], "menginap", nama_tamu="TEST_Val_Same", catatan="")
        try:
            r = requests.post(
                f"{API}/rooms/{src['id']}/move",
                headers=headers,
                json={"new_room_id": src["id"], "alasan": "test"},
                timeout=10,
            )
            assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        finally:
            _reset_room(headers, src["id"])

    def test_source_kosong_rejected_400(self, headers):
        src, _ = _empty_rooms(headers, 2)
        r = requests.post(
            f"{API}/rooms/{src['id']}/move",
            headers=headers,
            json={"new_room_id": _empty_rooms(headers, 2)[1]["id"], "alasan": "test"},
            timeout=10,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}"

    def test_target_not_kosong_rejected_400(self, headers):
        rooms = _empty_rooms(headers, 2)
        src, dst = rooms[0], rooms[1]
        _set_room_status(headers, src["id"], "menginap", nama_tamu="TEST_Val_T1")
        _set_room_status(headers, dst["id"], "maintenance", nama_tamu="", catatan="")
        try:
            r = requests.post(
                f"{API}/rooms/{src['id']}/move",
                headers=headers,
                json={"new_room_id": dst["id"], "alasan": "test"},
                timeout=10,
            )
            assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        finally:
            _reset_room(headers, src["id"])
            _reset_room(headers, dst["id"])


class TestMoveRoomMenginap:
    def test_menginap_move_success(self, headers):
        rooms = _empty_rooms(headers, 2)
        src, dst = rooms[0], rooms[1]
        _set_room_status(headers, src["id"], "menginap", nama_tamu="TEST_Menginap_Tamu", catatan="Lantai berisik")
        try:
            r = requests.post(
                f"{API}/rooms/{src['id']}/move",
                headers=headers,
                json={"new_room_id": dst["id"], "alasan": "AC rusak"},
                timeout=15,
            )
            assert r.status_code == 200, f"Move failed: {r.text}"
            body = r.json()
            assert body.get("ok") is True
            assert body.get("status") == "menginap"

            # verify rooms updated
            all_rooms = {x["id"]: x for x in _get_rooms(headers)}
            assert all_rooms[src["id"]]["status"] == "perlu_dibersihkan", "Source should be perlu_dibersihkan"
            assert all_rooms[dst["id"]]["status"] == "menginap", "Target should be menginap"
            assert all_rooms[dst["id"]].get("info", {}).get("nama_tamu") == "TEST_Menginap_Tamu", \
                f"Tamu info should be moved: {all_rooms[dst['id']].get('info')}"
        finally:
            _reset_room(headers, src["id"])
            _reset_room(headers, dst["id"])


class TestMoveRoomDayUse:
    def test_day_use_move_updates_checkin(self, headers):
        """Create a real checkin (day_use), then move it. Checkin row should reflect new room_id/nomor."""
        rooms = _empty_rooms(headers, 2)
        src, dst = rooms[0], rooms[1]
        # Create checkin (day_use)
        payload = {
            "tipe": "day_use",
            "room_id": src["id"],
            "nama_tamu": f"TEST_DayUse_{uuid.uuid4().hex[:6]}",
            "no_hp": "081200000000",
            "no_identitas": "",
            "kendaraan": "",
            "jumlah_tamu": 1,
            "tarif_dasar": src.get("tarif", 100000),
            "catatan": "TEST",
        }
        r = requests.post(f"{API}/checkins", headers=headers, json=payload, timeout=15)
        assert r.status_code == 200, f"Failed to create checkin: {r.text}"
        ci = r.json()
        ci_id = ci["id"]
        tamu_nama = payload["nama_tamu"]
        try:
            # Now move
            r2 = requests.post(
                f"{API}/rooms/{src['id']}/move",
                headers=headers,
                json={"new_room_id": dst["id"], "alasan": "test day_use"},
                timeout=15,
            )
            assert r2.status_code == 200, f"Move failed: {r2.text}"

            # rooms reflect status
            all_rooms = {x["id"]: x for x in _get_rooms(headers)}
            assert all_rooms[src["id"]]["status"] == "perlu_dibersihkan"
            assert all_rooms[dst["id"]]["status"] == "day_use"
            assert all_rooms[dst["id"]].get("info", {}).get("nama_tamu") == tamu_nama

            # active checkin updated
            ra = requests.get(f"{API}/checkins", headers=headers, params={"status": "aktif"}, timeout=10)
            assert ra.status_code == 200
            ci_updated = next((x for x in ra.json() if x["id"] == ci_id), None)
            assert ci_updated is not None, "Active checkin not found after move"
            assert ci_updated["room_id"] == dst["id"], f"checkin.room_id not updated: {ci_updated.get('room_id')}"
            assert ci_updated["room_nomor"] == dst["nomor"], "checkin.room_nomor not updated"
            assert ci_updated.get("moved_from_room_id") == src["id"]
        finally:
            # cleanup: checkout to remove checkin row
            try:
                requests.post(
                    f"{API}/checkins/{ci_id}/checkout",
                    headers=headers,
                    json={"metode_bayar": "tunai", "diskon": 0, "biaya_tambahan_manual": 0, "overtime_jam_manual": None},
                    timeout=15,
                )
            except Exception:
                pass
            _reset_room(headers, src["id"])
            _reset_room(headers, dst["id"])


class TestBookingRescheduleAndCancel:
    def test_create_then_reschedule_then_cancel(self, headers):
        rooms = _empty_rooms(headers, 1)
        src = rooms[0]
        start = datetime.now(timezone.utc) + timedelta(days=15)
        payload = {
            "tipe": "day_use",
            "room_id": src["id"],
            "nama_tamu": f"TEST_BookFlow_{uuid.uuid4().hex[:6]}",
            "no_hp": "08120000",
            "no_identitas": "",
            "kendaraan": "",
            "jumlah_tamu": 1,
            "jam_mulai": start.isoformat(),
            "jam_selesai": (start + timedelta(hours=6)).isoformat(),
            "catatan": "TEST",
        }
        r = requests.post(f"{API}/bookings", headers=headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        bk = r.json()
        bid = bk["id"]
        try:
            # Reschedule via PUT
            new_start = start + timedelta(days=2)
            updated = dict(payload)
            updated["jam_mulai"] = new_start.isoformat()
            updated["jam_selesai"] = (new_start + timedelta(hours=6)).isoformat()
            r2 = requests.put(f"{API}/bookings/{bid}", headers=headers, json=updated, timeout=15)
            assert r2.status_code == 200, f"PUT failed: {r2.text}"

            # Verify persisted
            r3 = requests.get(f"{API}/bookings", headers=headers, params={"status": "aktif"}, timeout=10)
            persisted = next((b for b in r3.json() if b["id"] == bid), None)
            assert persisted is not None
            # jam_mulai should match new_start (allow string compare on first 19 chars)
            assert persisted["jam_mulai"].startswith(new_start.isoformat()[:16].replace("+00:00", "")) or \
                   new_start.date().isoformat() in persisted["jam_mulai"], \
                f"jam_mulai not rescheduled: {persisted['jam_mulai']}"
        finally:
            # Cancel
            rd = requests.delete(f"{API}/bookings/{bid}", headers=headers, timeout=10)
            assert rd.status_code == 200, f"DELETE failed: {rd.text}"
            # verify in dibatalkan
            r4 = requests.get(f"{API}/bookings", headers=headers, params={"status": "dibatalkan"}, timeout=10)
            assert any(b["id"] == bid for b in r4.json())
