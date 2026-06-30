"""Phase C - Midtrans Snap integration tests (sandbox).

Covers:
- GET /api/payments/midtrans/config
- POST /api/payments/midtrans/create-snap-token (dp50 + full + validation)
- POST /api/payments/midtrans/notification (signature, status mapping, idempotent)
- GET /api/payments/midtrans/status/{order_id}
"""
import os
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pwa-kasir-hotel.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
SERVER_KEY = "Mid-server-q5-wHV0Ie4QwLnV7zu8e7enJ"
CLIENT_KEY = "Mid-client-96SeuHeUoYtpLMHG"


# ---- fixtures ----

@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def owner_token(session):
    r = session.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def std_room(session, owner_token):
    """Find an available Standard room."""
    r = session.get(f"{API}/public/rooms-catalog")
    assert r.status_code == 200
    rooms = r.json()
    # rooms is list of types; pick first room of Standard type
    std = next((t for t in rooms if "tandar" in (t.get("tipe") or "")), rooms[0])
    # we need an actual room doc. Use admin endpoint
    s2 = requests.Session()
    s2.headers.update({"Authorization": f"Bearer {owner_token}"})
    r2 = s2.get(f"{API}/rooms")
    assert r2.status_code == 200
    avail = [x for x in r2.json() if x["status"] == "kosong" and x["tipe"] == std["tipe"]]
    assert avail, f"No available {std['tipe']} room"
    return avail[0]


def _make_public_booking(session, room, day_offset=30):
    """Helper - create a fresh booking_pending booking on a far future date to avoid overlaps."""
    tanggal = (datetime.now(timezone.utc) + timedelta(days=day_offset)).strftime("%Y-%m-%d")
    jam = f"{(uuid.uuid4().int % 8) + 8:02d}:00"  # rand 08..15
    body = {
        "nama_tamu": f"TEST_MTR_{uuid.uuid4().hex[:6]}",
        "no_hp": "081234567890",
        "no_identitas": "3201" + uuid.uuid4().hex[:12].upper(),
        "jumlah_tamu": 1,
        "kendaraan": "",
        "room_id": room["id"],
        "tanggal": tanggal,
        "jam_checkin": jam,
        "catatan": "phase-c-midtrans-test",
    }
    # retry with different offset on overlap
    for off in range(day_offset, day_offset + 30):
        body["tanggal"] = (datetime.now(timezone.utc) + timedelta(days=off)).strftime("%Y-%m-%d")
        r = session.post(f"{API}/public/bookings", json=body)
        if r.status_code == 200:
            return r.json()
        if r.status_code != 400:
            r.raise_for_status()
    pytest.skip("Cannot create public booking — all far-future dates overlap")


def _sign(order_id, status_code, gross_amount):
    raw = f"{order_id}{status_code}{gross_amount}{SERVER_KEY}".encode()
    return hashlib.sha512(raw).hexdigest()


# ---- 1. Config endpoint ----

def test_midtrans_config(session):
    r = session.get(f"{API}/payments/midtrans/config")
    assert r.status_code == 200
    data = r.json()
    assert data["client_key"] == CLIENT_KEY
    assert data["is_production"] is False
    assert data["snap_url"] == "https://app.sandbox.midtrans.com/snap/snap.js"


# ---- 2. create-snap-token: success scenarios ----

def test_create_snap_token_dp50(session, std_room):
    bk = _make_public_booking(session, std_room)
    r = session.post(f"{API}/payments/midtrans/create-snap-token",
                     json={"booking_id": bk["id"], "payment_option": "dp50"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "transaction_token" in data and data["transaction_token"]
    assert "order_id" in data and data["order_id"].startswith(bk["kode"])
    assert data["client_key"] == CLIENT_KEY
    assert data["gross_amount"] == bk["dp_min"]
    # Verify booking updated with invoice_id & amount_due
    b2 = session.get(f"{API}/public/bookings/{bk['id']}").json()
    assert b2["invoice_id"] == data["order_id"]
    # status endpoint
    s = session.get(f"{API}/payments/midtrans/status/{data['order_id']}")
    assert s.status_code == 200
    sl = s.json()
    assert sl["transaction_status"] == "initiated"
    assert sl["payment_option"] == "dp50"
    assert sl["booking_id"] == bk["id"]


def test_create_snap_token_full(session, std_room):
    bk = _make_public_booking(session, std_room)
    r = session.post(f"{API}/payments/midtrans/create-snap-token",
                     json={"booking_id": bk["id"], "payment_option": "full"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["gross_amount"] == bk["total"]
    assert data["transaction_token"]


# ---- 3. validation ----

def test_create_snap_token_booking_not_found(session):
    r = session.post(f"{API}/payments/midtrans/create-snap-token",
                     json={"booking_id": "non-existent-id", "payment_option": "dp50"})
    assert r.status_code == 404


def test_create_snap_token_invalid_option(session, std_room):
    bk = _make_public_booking(session, std_room)
    r = session.post(f"{API}/payments/midtrans/create-snap-token",
                     json={"booking_id": bk["id"], "payment_option": "half"})
    assert r.status_code == 400


def test_create_snap_token_wrong_status(session, std_room, owner_token):
    """booking with non-booking_pending status → 400."""
    bk = _make_public_booking(session, std_room)
    # cancel it via admin
    s2 = requests.Session()
    s2.headers.update({"Authorization": f"Bearer {owner_token}", "Content-Type": "application/json"})
    # quickest is to fire a webhook to cancel it
    order_id = f"{bk['kode']}-CANCEL01"
    sc = "202"
    ga = "1000.00"
    # First create a snap token so payment_log exists for this booking
    session.post(f"{API}/payments/midtrans/create-snap-token",
                 json={"booking_id": bk["id"], "payment_option": "dp50"})
    # Fetch latest order_id
    b2 = session.get(f"{API}/public/bookings/{bk['id']}").json()
    real_oid = b2["invoice_id"]
    log = session.get(f"{API}/payments/midtrans/status/{real_oid}").json()
    ga = log["gross_amount"]
    sig = _sign(real_oid, sc, ga)
    payload = {"order_id": real_oid, "status_code": sc, "gross_amount": ga,
               "signature_key": sig, "transaction_status": "deny",
               "payment_type": "credit_card", "fraud_status": "deny"}
    nr = session.post(f"{API}/payments/midtrans/notification", json=payload)
    assert nr.status_code == 200
    # Now booking should be cancelled
    r = session.post(f"{API}/payments/midtrans/create-snap-token",
                     json={"booking_id": bk["id"], "payment_option": "dp50"})
    assert r.status_code == 400


# ---- 4. webhook signature ----

def test_webhook_invalid_signature(session):
    payload = {"order_id": "FAKE-XYZ", "status_code": "200", "gross_amount": "10000.00",
               "signature_key": "deadbeef", "transaction_status": "settlement"}
    r = session.post(f"{API}/payments/midtrans/notification", json=payload)
    assert r.status_code == 403
    assert "Signature" in r.text


def test_webhook_missing_fields(session):
    r = session.post(f"{API}/payments/midtrans/notification",
                     json={"order_id": "X", "status_code": "200"})
    assert r.status_code == 400


# ---- 5. webhook status mapping ----

def _create_token_and_get_log(session, std_room, option="dp50"):
    bk = _make_public_booking(session, std_room)
    r = session.post(f"{API}/payments/midtrans/create-snap-token",
                     json={"booking_id": bk["id"], "payment_option": option})
    assert r.status_code == 200
    data = r.json()
    return bk, data["order_id"], data["gross_amount"]


def _send_notification(session, order_id, gross_amount, transaction_status,
                       status_code="200", payment_type="qris", fraud_status=None):
    ga = f"{gross_amount}.00" if isinstance(gross_amount, int) else str(gross_amount)
    sig = _sign(order_id, status_code, ga)
    payload = {"order_id": order_id, "status_code": status_code, "gross_amount": ga,
               "signature_key": sig, "transaction_status": transaction_status,
               "payment_type": payment_type, "fraud_status": fraud_status}
    return session.post(f"{API}/payments/midtrans/notification", json=payload)


def test_webhook_settlement(session, std_room):
    bk, oid, ga = _create_token_and_get_log(session, std_room)
    r = _send_notification(session, oid, ga, "settlement")
    assert r.status_code == 200
    b2 = session.get(f"{API}/public/bookings/{bk['id']}").json()
    assert b2["status"] == "booking_paid"
    assert b2["payment_status"] == "paid"


def test_webhook_pending(session, std_room):
    bk, oid, ga = _create_token_and_get_log(session, std_room)
    r = _send_notification(session, oid, ga, "pending", status_code="201")
    assert r.status_code == 200
    b2 = session.get(f"{API}/public/bookings/{bk['id']}").json()
    assert b2["status"] == "booking_pending"  # unchanged
    assert b2["payment_status"] == "pending"


def test_webhook_expire(session, std_room):
    bk, oid, ga = _create_token_and_get_log(session, std_room)
    r = _send_notification(session, oid, ga, "expire", status_code="202")
    assert r.status_code == 200
    b2 = session.get(f"{API}/public/bookings/{bk['id']}").json()
    assert b2["status"] == "cancelled"
    assert b2["payment_status"] == "expired"


def test_webhook_deny(session, std_room):
    bk, oid, ga = _create_token_and_get_log(session, std_room)
    r = _send_notification(session, oid, ga, "deny", status_code="202", payment_type="credit_card")
    assert r.status_code == 200
    b2 = session.get(f"{API}/public/bookings/{bk['id']}").json()
    assert b2["status"] == "cancelled"
    assert b2["payment_status"] == "failed"


# ---- 6. idempotent webhook ----

def test_webhook_idempotent(session, std_room):
    bk, oid, ga = _create_token_and_get_log(session, std_room)
    r1 = _send_notification(session, oid, ga, "settlement")
    r2 = _send_notification(session, oid, ga, "settlement")
    assert r1.status_code == 200 and r2.status_code == 200
    # status endpoint should still return single record
    s = session.get(f"{API}/payments/midtrans/status/{oid}")
    assert s.status_code == 200
    assert s.json()["transaction_status"] == "settlement"
    b2 = session.get(f"{API}/public/bookings/{bk['id']}").json()
    assert b2["status"] == "booking_paid"


# ---- 7. status polling endpoint ----

def test_get_status_not_found(session):
    r = session.get(f"{API}/payments/midtrans/status/DOES-NOT-EXIST-XYZ")
    assert r.status_code == 404
