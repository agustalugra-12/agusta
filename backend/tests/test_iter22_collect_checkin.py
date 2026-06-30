"""Iter22 — collect-balance + checkin_from_booking tests."""
import os
import uuid
from datetime import datetime, timedelta
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pwa-kasir-hotel.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

_date_counter = 0


def _next_tanggal():
    global _date_counter
    _date_counter += 1
    base = datetime(2030, 1, 1) + timedelta(days=_date_counter)
    return base.strftime("%Y-%m-%d")


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _pick_kosong_room():
    return db.rooms.find_one({"status": "kosong"})


def _make_booking_paid_dp50(total=123600, paid=61800):
    room = _pick_kosong_room()
    assert room, "No kosong room available for test"
    payload = {
        "room_id": room["id"],
        "nama_tamu": f"TEST_ITER22_{uuid.uuid4().hex[:6]}",
        "no_hp": "081234567890",
        "no_identitas": "1234567890",
        "kendaraan": "B 1234 XYZ",
        "jumlah_tamu": 1,
        "tanggal": _next_tanggal(),
        "jam_checkin": "10:00",
        "catatan": "iter22 test",
    }
    r = requests.post(f"{API}/public/bookings", json=payload, timeout=10)
    assert r.status_code in (200, 201), r.text
    bid = r.json()["id"]
    db.bookings.update_one({"id": bid}, {"$set": {
        "status": "booking_paid", "total": total, "amount_due": paid,
        "subtotal": total, "service_fee": 0,
    }})
    return db.bookings.find_one({"id": bid})


def _cleanup_booking(bid):
    b = db.bookings.find_one({"id": bid})
    if not b:
        return
    ci = db.checkins.find_one({"from_booking_id": bid})
    if ci:
        db.checkins.delete_one({"id": ci["id"]})
        db.rooms.update_one({"id": b["room_id"]}, {"$set": {"status": "kosong", "info": None}})
    db.bookings.update_one({"id": bid}, {"$set": {"status": "cancelled", "cancelled_at": "TEST_CLEANUP"}})


# ============== collect-balance ==============

class TestCollectBalance:
    def test_happy_path_full_collect(self, headers):
        b = _make_booking_paid_dp50(total=123600, paid=61800)
        try:
            r = requests.post(f"{API}/bookings/{b['id']}/collect-balance",
                              json={"nominal": 61800, "metode": "cash"}, headers=headers, timeout=10)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ok"] is True
            assert data["amount_collected"] == 61800
            assert data["total_paid"] == 123600
            assert data["remaining"] == 0
            b2 = db.bookings.find_one({"id": b["id"]})
            assert int(b2["amount_due"]) == 123600
            log = db.payment_log.find_one({"booking_id": b["id"], "payment_option": "collect_balance"})
            assert log is not None
            assert log["order_id"].startswith("COLLECT-")
            assert log["payment_type"] == "cash"
            assert log["transaction_status"] == "settlement"
            audit = db.audit_log.find_one({"action": "collect_balance", "detail": {"$regex": b["kode"]}})
            assert audit is not None
        finally:
            db.payment_log.delete_many({"booking_id": b["id"]})
            _cleanup_booking(b["id"])

    def test_partial_collect_qris(self, headers):
        b = _make_booking_paid_dp50()
        try:
            r = requests.post(f"{API}/bookings/{b['id']}/collect-balance",
                              json={"nominal": 30000, "metode": "qris"}, headers=headers, timeout=10)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["amount_collected"] == 30000
            assert d["total_paid"] == 91800
            assert d["remaining"] == 31800
        finally:
            db.payment_log.delete_many({"booking_id": b["id"]})
            _cleanup_booking(b["id"])

    def test_nominal_too_big_400(self, headers):
        b = _make_booking_paid_dp50()
        try:
            r = requests.post(f"{API}/bookings/{b['id']}/collect-balance",
                              json={"nominal": 999999, "metode": "cash"}, headers=headers, timeout=10)
            assert r.status_code == 400
            assert "terlalu besar" in r.json()["detail"].lower()
        finally:
            _cleanup_booking(b["id"])

    def test_invalid_metode_400(self, headers):
        b = _make_booking_paid_dp50()
        try:
            r = requests.post(f"{API}/bookings/{b['id']}/collect-balance",
                              json={"nominal": 1000, "metode": "transfer"}, headers=headers, timeout=10)
            assert r.status_code == 400
            assert "cash" in r.json()["detail"].lower() or "qris" in r.json()["detail"].lower()
        finally:
            _cleanup_booking(b["id"])

    def test_already_lunas_400(self, headers):
        b = _make_booking_paid_dp50(total=100000, paid=100000)
        try:
            r = requests.post(f"{API}/bookings/{b['id']}/collect-balance",
                              json={"nominal": 1, "metode": "cash"}, headers=headers, timeout=10)
            assert r.status_code == 400
            assert "lunas" in r.json()["detail"].lower()
        finally:
            _cleanup_booking(b["id"])

    def test_booking_pending_400(self, headers):
        b = _make_booking_paid_dp50()
        try:
            db.bookings.update_one({"id": b["id"]}, {"$set": {"status": "booking_pending"}})
            r = requests.post(f"{API}/bookings/{b['id']}/collect-balance",
                              json={"nominal": 1000, "metode": "cash"}, headers=headers, timeout=10)
            assert r.status_code == 400
            txt = r.json()["detail"].lower()
            assert "booking_paid" in txt or "checked_in" in txt
        finally:
            _cleanup_booking(b["id"])

    def test_no_auth_401(self):
        b = _make_booking_paid_dp50()
        try:
            r = requests.post(f"{API}/bookings/{b['id']}/collect-balance",
                              json={"nominal": 1000, "metode": "cash"}, timeout=10)
            assert r.status_code in (401, 403)
        finally:
            _cleanup_booking(b["id"])


# ============== checkin_from_booking ==============

class TestCheckinFromBooking:
    def test_happy_checkin(self, headers):
        b = _make_booking_paid_dp50(total=123600, paid=61800)
        try:
            r = requests.post(f"{API}/bookings/{b['id']}/checkin", json={}, headers=headers, timeout=10)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["ok"] is True
            assert d["trx_no"].startswith("CI-")
            assert d["remaining"] == 61800
            ci_id = d["checkin_id"]
            ci = db.checkins.find_one({"id": ci_id})
            assert ci is not None
            assert ci["status"] == "aktif"
            assert ci["from_booking_id"] == b["id"]
            assert ci["from_booking_kode"] == b["kode"]
            assert int(ci["booking_paid"]) == 61800
            assert int(ci["booking_remaining"]) == 61800
            b2 = db.bookings.find_one({"id": b["id"]})
            assert b2["status"] == "checked_in"
            assert b2["checkin_id"] == ci_id
            r2 = db.rooms.find_one({"id": b["room_id"]})
            assert r2["status"] == "day_use"
            audit = db.audit_log.find_one({"action": "checkin_from_booking", "detail": {"$regex": b["kode"]}})
            assert audit is not None
        finally:
            _cleanup_booking(b["id"])

    def test_not_booking_paid_400(self, headers):
        b = _make_booking_paid_dp50()
        try:
            db.bookings.update_one({"id": b["id"]}, {"$set": {"status": "booking_pending"}})
            r = requests.post(f"{API}/bookings/{b['id']}/checkin", json={}, headers=headers, timeout=10)
            assert r.status_code == 400
            assert "lunas" in r.json()["detail"].lower()
        finally:
            _cleanup_booking(b["id"])

    def test_room_not_kosong_400(self, headers):
        b = _make_booking_paid_dp50()
        try:
            original_status = db.rooms.find_one({"id": b["room_id"]})["status"]
            db.rooms.update_one({"id": b["room_id"]}, {"$set": {"status": "menginap"}})
            r = requests.post(f"{API}/bookings/{b['id']}/checkin", json={}, headers=headers, timeout=10)
            assert r.status_code == 400
            assert "dipakai" in r.json()["detail"].lower() or "kosong" in r.json()["detail"].lower()
        finally:
            db.rooms.update_one({"id": b["room_id"]}, {"$set": {"status": "kosong"}})
            _cleanup_booking(b["id"])


# ============== regression smoke ==============

class TestSmokeRegression:
    def test_mark_paid_manual_still_works(self, headers):
        room = _pick_kosong_room()
        payload = {
            "room_id": room["id"], "nama_tamu": f"TEST_ITER22_SMK_{uuid.uuid4().hex[:4]}",
            "no_hp": "081234567890", "no_identitas": "1", "kendaraan": "",
            "jumlah_tamu": 1,
            "tanggal": _next_tanggal(), "jam_checkin": "10:00",
            "catatan": "smoke",
        }
        r = requests.post(f"{API}/public/bookings", json=payload, timeout=10)
        assert r.status_code in (200, 201), r.text
        bid = r.json()["id"]
        try:
            r2 = requests.post(f"{API}/bookings/{bid}/mark-paid-manual",
                               json={"nominal": 50000, "metode": "transfer_manual"},
                               headers=headers, timeout=10)
            assert r2.status_code == 200, r2.text
            b = db.bookings.find_one({"id": bid})
            assert b["status"] == "booking_paid"
            assert b.get("payment_type") == "transfer_manual"
        finally:
            db.payment_log.delete_many({"booking_id": bid})
            _cleanup_booking(bid)

    def test_cancellation_revenue_endpoint(self, headers):
        r = requests.get(f"{API}/reports/cancellation-revenue?from_date=2024-01-01&to_date=2031-12-31",
                         headers=headers, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "cancel_fees_total" in d
        assert "no_show_total" in d
        assert "grand_total" in d
        assert d["grand_total"] == d["cancel_fees_total"] + d["no_show_total"]

    def test_public_bank_accounts(self):
        r = requests.get(f"{API}/public/bank-accounts", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "accounts" in d
        assert len(d["accounts"]) >= 1
