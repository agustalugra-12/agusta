"""
Iteration 14 — Pelangi Homestay regression tests
Covers:
  Fix 1: GET /api/public/rooms-catalog → Cottage rooms 1-8 @140000, Standard 9-18 @120000 (18 rooms total)
  Fix 4: GET /api/reports/booking-widgets → booking_walkin_bulan reflects db.checkins count
         (insert checkin → walkin_bulan++; insert public booking → online_bulan++ but walkin_bulan unchanged)
Smoke: booking lifecycle, cancel, walk-in via /checkins
"""
import os
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def auth(session):
    r = session.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    session.headers.update({"Authorization": f"Bearer {tok}"})
    return tok


# ---------- Fix 1 ----------
class TestRoomsCatalog:
    def test_catalog_groups_and_prices(self, session):
        r = session.get(f"{API}/public/rooms-catalog")
        assert r.status_code == 200, r.text
        groups = r.json()
        assert isinstance(groups, list)
        by_tipe = {g["tipe"]: g for g in groups}
        assert "Cottage" in by_tipe, f"Cottage missing: {list(by_tipe)}"
        assert "Standard" in by_tipe, f"Standard missing: {list(by_tipe)}"

        cottage = by_tipe["Cottage"]
        standard = by_tipe["Standard"]

        # tarif
        assert int(cottage["tarif"]) == 140000, f"Cottage tarif={cottage['tarif']}"
        assert int(standard["tarif"]) == 120000, f"Standard tarif={standard['tarif']}"

        # room numbers
        cot_nums = sorted(int(x["nomor"]) for x in cottage["rooms"] if x["nomor"].isdigit())
        std_nums = sorted(int(x["nomor"]) for x in standard["rooms"] if x["nomor"].isdigit())
        assert cot_nums == list(range(1, 9)), f"Cottage rooms != 1..8: {cot_nums}"
        assert std_nums == list(range(9, 19)), f"Standard rooms != 9..18: {std_nums}"

        # total
        total = len(cottage["rooms"]) + len(standard["rooms"])
        assert total == 18, f"total rooms = {total}"


# ---------- Fix 4 ----------
class TestWidgetWalkinFromCheckins:
    def _widgets(self, session):
        r = session.get(f"{API}/reports/booking-widgets")
        assert r.status_code == 200, r.text
        return r.json()

    def _get_a_kosong_room(self, session):
        rooms = session.get(f"{API}/rooms").json()
        for r in rooms:
            if r.get("status") == "kosong":
                return r
        pytest.skip("no kosong room available")

    def test_checkin_increments_walkin_only(self, session, auth):
        before = self._widgets(session)
        walk_before = before["booking_walkin_bulan"]
        online_before = before["booking_online_bulan"]

        room = self._get_a_kosong_room(session)
        ci_payload = {
            "room_id": room["id"],
            "guest_id": None,
            "nama_tamu": "TEST_ITER14_CI",
            "no_hp": "0811000999",
            "no_identitas": "TEST",
            "kendaraan": "",
            "jumlah_tamu": 1,
            "metode": "menginap",
            "durasi_jam": 24,
            "catatan": "TEST_ITER14",
        }
        r = session.post(f"{API}/checkins", json=ci_payload)
        assert r.status_code in (200, 201), r.text
        checkin_id = r.json().get("id")
        assert checkin_id

        try:
            after = self._widgets(session)
            assert after["booking_walkin_bulan"] == walk_before + 1, (
                f"walkin_bulan expected +1: before={walk_before}, after={after['booking_walkin_bulan']}"
            )
            assert after["booking_online_bulan"] == online_before, (
                f"online_bulan must not change: before={online_before}, after={after['booking_online_bulan']}"
            )
        finally:
            # cleanup → checkout
            try:
                session.post(f"{API}/checkins/{checkin_id}/checkout", json={"metode_bayar": "cash"})
            except Exception:
                pass

    def test_public_booking_increments_online_not_walkin(self, session, auth):
        before = self._widgets(session)
        walk_before = before["booking_walkin_bulan"]
        online_before = before["booking_online_bulan"]

        d = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        avail = session.get(f"{API}/public/availability", params={"tanggal": d, "tipe": "Standard"}).json()
        rooms = avail.get("rooms", [])
        if not rooms:
            pytest.skip("no public-available rooms 7 days out")
        rid = rooms[0]["id"]

        payload = {
            "tipe": "Standard",
            "room_id": rid,
            "nama_tamu": "TEST_ITER14_PB",
            "no_hp": "081100099988",
            "no_identitas": "TEST",
            "jumlah_tamu": 1,
            "tanggal": d,
            "jam_checkin": "14:00",
            "catatan": "TEST_ITER14",
        }
        r = session.post(f"{API}/public/bookings", json=payload)
        assert r.status_code in (200, 201), r.text
        bid = r.json().get("id")
        assert bid

        try:
            after = self._widgets(session)
            assert after["booking_online_bulan"] == online_before + 1, (
                f"online_bulan expected +1: before={online_before}, after={after['booking_online_bulan']}"
            )
            assert after["booking_walkin_bulan"] == walk_before, (
                f"walkin_bulan must not change: before={walk_before}, after={after['booking_walkin_bulan']}"
            )
        finally:
            try:
                session.delete(f"{API}/bookings/{bid}")
            except Exception:
                pass


# ---------- Fix 2 smoke (cancel) ----------
class TestBookingCancelSmoke:
    def test_public_booking_then_cancel(self, session, auth):
        d = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
        avail = session.get(f"{API}/public/availability", params={"tanggal": d, "tipe": "Cottage"}).json()
        rooms = avail.get("rooms", [])
        if not rooms:
            pytest.skip("no available cottage room 5 days out")
        rid = rooms[0]["id"]
        r = session.post(f"{API}/public/bookings", json={
            "tipe": "Cottage", "room_id": rid, "nama_tamu": "TEST_ITER14_QC",
            "no_hp": "0811000777", "no_identitas": "TEST", "jumlah_tamu": 1,
            "tanggal": d, "jam_checkin": "15:00", "catatan": "TEST_ITER14",
        })
        assert r.status_code in (200, 201), r.text
        bid = r.json()["id"]

        # DELETE → cancel
        rd = session.delete(f"{API}/bookings/{bid}")
        assert rd.status_code in (200, 204), rd.text

        # verify status cancelled
        gb = session.get(f"{API}/bookings/{bid}")
        # endpoint may not exist; fallback to list filter
        if gb.status_code == 404 or gb.status_code == 405:
            lst = session.get(f"{API}/bookings", params={"include_cancelled": "true"}).json()
            items = lst if isinstance(lst, list) else lst.get("items", [])
            found = next((b for b in items if b.get("id") == bid), None)
            if found:
                assert found.get("status") == "cancelled", f"status={found.get('status')}"
        else:
            assert gb.status_code == 200, gb.text
            assert gb.json().get("status") == "cancelled", gb.json()
