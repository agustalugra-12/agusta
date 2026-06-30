"""
Iter20 backend tests:
- GET /api/reports/cancellation-revenue (auth, date range, structure)
- POST /api/bookings/{id}/mark-paid-manual (auth, state machine, payment_log, audit)
- GET /api/public/bank-accounts (no auth, default BCA + Mandiri)
"""
import os
import datetime as dt
import pytest
import requests

def _load_frontend_env():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        return None
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _load_frontend_env()).rstrip("/")
API = f"{BASE_URL}/api"


# ------------------------- fixtures -------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def auth_token(session):
    r = session.post(f"{API}/auth/login", json={"username": "owner", "password": "owner123"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth_session(session, auth_token):
    session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return session


@pytest.fixture(scope="module")
def a_room(auth_session):
    r = auth_session.get(f"{API}/rooms")
    assert r.status_code == 200
    rooms = r.json()
    assert len(rooms) > 0, "no rooms in DB"
    return rooms[0]


# ------------------------- public bank-accounts -------------------------
class TestPublicBankAccounts:
    def test_no_auth_required(self):
        # explicit fresh session without auth header
        r = requests.get(f"{API}/public/bank-accounts")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "accounts" in data
        assert "instruksi" in data
        assert isinstance(data["accounts"], list)

    def test_default_two_banks(self):
        r = requests.get(f"{API}/public/bank-accounts")
        data = r.json()
        banks = {a["bank"]: a for a in data["accounts"]}
        assert "BCA" in banks, f"BCA missing: {banks}"
        assert "Mandiri" in banks, f"Mandiri missing: {banks}"
        for bk in ["BCA", "Mandiri"]:
            acc = banks[bk]
            assert "nomor" in acc and acc["nomor"]
            assert "atas_nama" in acc and acc["atas_nama"]


# ------------------------- cancellation-revenue -------------------------
class TestCancellationRevenue:
    def test_requires_auth(self):
        r = requests.get(f"{API}/reports/cancellation-revenue",
                         params={"from_date": "2026-01-01", "to_date": "2026-01-31"})
        assert r.status_code in (401, 403), r.text

    def test_invalid_date_format(self, auth_session):
        r = auth_session.get(f"{API}/reports/cancellation-revenue",
                             params={"from_date": "31-01-2026", "to_date": "2026-01-31"})
        assert r.status_code == 400, r.text

    def test_structure_and_30day_window(self, auth_session):
        today = dt.date.today()
        f = (today - dt.timedelta(days=30)).isoformat()
        t = today.isoformat()
        r = auth_session.get(f"{API}/reports/cancellation-revenue",
                             params={"from_date": f, "to_date": t})
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["cancel_fees_total", "no_show_total", "grand_total",
                  "cancel_count", "no_show_count", "by_day", "items",
                  "from_date", "to_date"]:
            assert k in d, f"missing key: {k}"
        assert isinstance(d["by_day"], list)
        assert isinstance(d["items"], list)
        # arithmetic consistency
        assert d["grand_total"] == d["cancel_fees_total"] + d["no_show_total"]
        # item shape sanity (if any)
        for it in d["items"]:
            for k in ["tipe", "kode", "room_nomor", "nama_tamu",
                      "tanggal", "nominal", "alasan", "petugas", "source"]:
                assert k in it, f"item missing {k}: {it}"
            assert it["tipe"] in ("cancel", "no_show")

    def test_empty_window_future_returns_zero(self, auth_session):
        # window far in the future should be empty
        r = auth_session.get(f"{API}/reports/cancellation-revenue",
                             params={"from_date": "2099-01-01", "to_date": "2099-01-31"})
        assert r.status_code == 200
        d = r.json()
        assert d["cancel_fees_total"] == 0
        assert d["no_show_total"] == 0
        assert d["grand_total"] == 0
        assert d["items"] == []


# ------------------------- mark-paid-manual -------------------------
class TestMarkPaidManual:
    @pytest.fixture
    def pending_booking(self, auth_session, a_room):
        """Create a public booking which lands as booking_pending."""
        future = (dt.date.today() + dt.timedelta(days=120)).isoformat()
        payload = {
            "room_id": a_room["id"],
            "tanggal": future,
            "jam_checkin": "14:00",
            "nama_tamu": "TEST_ITER20 Manual Pay",
            "no_hp": "081200000020",
            "jumlah_tamu": 1,
            "durasi_jam": 3,
            "source": "online",
        }
        # Public booking endpoint (no auth)
        r = requests.post(f"{API}/public/bookings", json=payload)
        assert r.status_code in (200, 201), r.text
        booking = r.json()
        # booking may be wrapped (e.g. {"booking": {...}})
        if "id" not in booking and "booking" in booking:
            booking = booking["booking"]
        assert booking.get("status") == "booking_pending", booking
        yield booking
        # cleanup: best-effort delete
        try:
            auth_session.delete(f"{API}/bookings/{booking['id']}")
        except Exception:
            pass

    def test_404_not_found(self, auth_session):
        r = auth_session.post(f"{API}/bookings/nope-not-exist/mark-paid-manual", json={})
        assert r.status_code == 404, r.text

    def test_requires_auth(self, pending_booking):
        r = requests.post(f"{API}/bookings/{pending_booking['id']}/mark-paid-manual",
                          json={"nominal": 50000})
        assert r.status_code in (401, 403), r.text

    def test_mark_paid_manual_success_and_persistence(self, auth_session, pending_booking):
        bid = pending_booking["id"]
        kode = pending_booking["kode"]
        total = int(pending_booking.get("total", 0))
        nominal = total if total > 0 else 50000

        r = auth_session.post(f"{API}/bookings/{bid}/mark-paid-manual",
                              json={"nominal": nominal, "alasan": "TEST_ITER20 transfer ok"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("status") == "booking_paid"
        assert d.get("amount") == nominal
        assert d.get("booking_kode") == kode

        # GET booking via list to confirm persistence (no single GET endpoint)
        r2 = auth_session.get(f"{API}/bookings")
        assert r2.status_code == 200, r2.text
        all_b = r2.json()
        if isinstance(all_b, dict):
            all_b = all_b.get("items") or all_b.get("bookings") or []
        b = next((x for x in all_b if x.get("id") == bid), None)
        assert b is not None, f"booking {bid} not found in list"
        assert b["status"] == "booking_paid"
        assert b.get("payment_status") == "paid"
        assert b.get("payment_type") == "transfer_manual"
        assert b.get("amount_due") == nominal
        assert b.get("paid_at"), "paid_at not set"

        # payment_log + audit verified via mongo directly
        import subprocess, json as _json
        cmd = (
            'mongosh pelangi_homestay --quiet --eval '
            f'"JSON.stringify(db.payment_log.findOne({{booking_kode:\'{kode}\'}}, {{_id:0}}))"'
        )
        out = subprocess.check_output(cmd, shell=True, text=True).strip()
        assert out and out != "null", f"payment_log row missing for {kode}"
        row = _json.loads(out)
        assert row.get("order_id") == f"MANUAL-{kode}", row
        assert row.get("transaction_status") == "settlement", row

        # audit log entry "manual_paid"
        r4 = auth_session.get(f"{API}/audit-log")
        if r4.status_code == 200:
            audits = r4.json()
            audits = audits if isinstance(audits, list) else audits.get("items", audits.get("logs", []))
            found = any((a.get("action") == "manual_paid"
                         and kode in (a.get("detail") or a.get("description") or ""))
                        for a in audits)
            assert found, f"manual_paid audit not found for {kode}"

    def test_400_on_non_pending(self, auth_session, pending_booking):
        bid = pending_booking["id"]
        # first call → pending → paid
        r1 = auth_session.post(f"{API}/bookings/{bid}/mark-paid-manual", json={"nominal": 50000})
        assert r1.status_code == 200, r1.text
        # second call → already booking_paid → must reject
        r2 = auth_session.post(f"{API}/bookings/{bid}/mark-paid-manual", json={"nominal": 50000})
        assert r2.status_code == 400, r2.text
