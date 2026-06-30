import requests, json, sys, time

BASE = "https://pwa-kasir-hotel.preview.emergentagent.com/api"
results = {"passed": [], "failed": []}

def ok(name): results["passed"].append(name); print(f"PASS {name}")
def fail(name, ev): results["failed"].append({"area": name, "evidence": str(ev)[:300]}); print(f"FAIL {name}: {str(ev)[:300]}")

# 1. Login owner
try:
    r = requests.post(f"{BASE}/auth/login", json={"username": "owner", "password": "owner123"}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    owner_token = j["token"]
    assert j["user"]["role"] == "owner"
    ok("login owner")
except Exception as e:
    fail("login owner", e); sys.exit(1)

# Login resepsionis
try:
    r = requests.post(f"{BASE}/auth/login", json={"username": "resepsionis", "password": "resep123"}, timeout=15)
    assert r.status_code == 200, r.text
    resep_token = r.json()["token"]
    assert r.json()["user"]["role"] == "resepsionis"
    ok("login resepsionis")
except Exception as e:
    fail("login resepsionis", e); resep_token = None

# Wrong password
try:
    r = requests.post(f"{BASE}/auth/login", json={"username": "owner", "password": "wrong"}, timeout=15)
    assert r.status_code == 401, r.status_code
    ok("login wrong password 401")
except Exception as e:
    fail("login wrong password", e)

H_OWN = {"Authorization": f"Bearer {owner_token}"}
H_RES = {"Authorization": f"Bearer {resep_token}"} if resep_token else {}

# /auth/me
try:
    r = requests.get(f"{BASE}/auth/me", headers=H_OWN, timeout=15)
    assert r.status_code == 200 and r.json().get("username") == "owner", r.text
    ok("auth/me")
except Exception as e:
    fail("auth/me", e)

# Rooms
try:
    r = requests.get(f"{BASE}/rooms", headers=H_OWN, timeout=15)
    rooms = r.json()
    assert r.status_code == 200
    std = [x for x in rooms if x.get("tipe") == "Standard"]
    cot = [x for x in rooms if x.get("tipe") == "Cottage"]
    print(f"  total rooms={len(rooms)} std={len(std)} cot={len(cot)}")
    assert len(rooms) == 18, f"expected 18 got {len(rooms)}"
    assert len(std) == 12 and len(cot) == 6
    assert all(x["tarif"] == 120000 for x in std)
    assert all(x["tarif"] == 140000 for x in cot)
    ok("GET /rooms 18 rooms with correct tarif")
except Exception as e:
    fail("GET /rooms", e); rooms = []

# Pick a kosong room
kosong = [x for x in rooms if x.get("status") == "kosong"]
if not kosong:
    fail("no kosong room available", f"counts: {{r['status'] for r in rooms}}")
    sys.exit(1)
room = kosong[0]
print(f"  using room {room['id']} {room.get('nama','?')}")

# Checkin
checkin_id = None
try:
    payload = {"nama_tamu": "Test Guest", "no_hp": "08123", "no_identitas": "KTP1", "kendaraan": "B1234", "jumlah_tamu": 2, "room_id": room["id"]}
    r = requests.post(f"{BASE}/checkins", json=payload, headers=H_RES or H_OWN, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    checkin_id = j["id"]
    assert j.get("trx_no")
    ok("POST /checkins creates checkin")
    # Verify room status
    r2 = requests.get(f"{BASE}/rooms", headers=H_OWN, timeout=15)
    updated = [x for x in r2.json() if x["id"] == room["id"]][0]
    assert updated["status"] == "day_use", updated["status"]
    ok("room status becomes day_use after checkin")
except Exception as e:
    fail("POST /checkins", e)

# Overbooking
try:
    r = requests.post(f"{BASE}/checkins", json={"nama_tamu": "X", "no_hp": "0", "no_identitas": "0", "kendaraan": "", "jumlah_tamu": 1, "room_id": room["id"]}, headers=H_OWN, timeout=15)
    assert r.status_code == 400, r.status_code
    ok("overbooking returns 400")
except Exception as e:
    fail("overbooking", e)

# Get checkin with preview
preview_total = None
if checkin_id:
    try:
        r = requests.get(f"{BASE}/checkins/{checkin_id}", headers=H_OWN, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        prev = j.get("preview") or {}
        print(f"  preview: {prev}")
        assert "tarif_dasar" in prev and "total" in prev
        assert prev.get("overtime_jam", 0) == 0
        preview_total = prev["total"]
        ok("GET /checkins/{id} preview")
    except Exception as e:
        fail("GET /checkins/{id}", e)

# Insufficient payment
if checkin_id and preview_total:
    try:
        r = requests.post(f"{BASE}/checkins/{checkin_id}/checkout", json={"pembayaran": [{"metode": "tunai", "jumlah": preview_total - 1000}]}, headers=H_OWN, timeout=15)
        assert r.status_code == 400, r.status_code
        ok("insufficient payment 400")
    except Exception as e:
        fail("insufficient payment", e)

# Successful checkout
if checkin_id and preview_total:
    try:
        r = requests.post(f"{BASE}/checkins/{checkin_id}/checkout", json={"pembayaran": [{"metode": "tunai", "jumlah": preview_total}]}, headers=H_OWN, timeout=15)
        assert r.status_code == 200, r.text
        ok("checkout success")
        r2 = requests.get(f"{BASE}/rooms", headers=H_OWN, timeout=15)
        upd = [x for x in r2.json() if x["id"] == room["id"]][0]
        assert upd["status"] == "perlu_dibersihkan", upd["status"]
        ok("room perlu_dibersihkan after checkout")
    except Exception as e:
        fail("checkout", e)

# Housekeeping done
try:
    r = requests.post(f"{BASE}/rooms/{room['id']}/housekeeping-done", headers=H_OWN, timeout=15)
    assert r.status_code == 200, r.text
    r2 = requests.get(f"{BASE}/rooms", headers=H_OWN, timeout=15)
    upd = [x for x in r2.json() if x["id"] == room["id"]][0]
    assert upd["status"] == "kosong"
    ok("housekeeping-done -> kosong")
except Exception as e:
    fail("housekeeping-done", e)

# PUT room status
kosong2 = [x for x in requests.get(f"{BASE}/rooms", headers=H_OWN).json() if x["status"] == "kosong"]
if kosong2:
    rid = kosong2[0]["id"]
    try:
        r = requests.put(f"{BASE}/rooms/{rid}/status", json={"status": "menginap", "nama_tamu": "Tester"}, headers=H_OWN, timeout=15)
        assert r.status_code == 200, r.text
        ok("PUT room status menginap")
        r = requests.put(f"{BASE}/rooms/{rid}/status", json={"status": "day_use"}, headers=H_OWN, timeout=15)
        assert r.status_code == 400, r.status_code
        ok("PUT day_use rejected")
        r = requests.put(f"{BASE}/rooms/{rid}/status", json={"status": "kosong"}, headers=H_OWN, timeout=15)
        assert r.status_code == 200, r.text
        ok("PUT back to kosong")
    except Exception as e:
        fail("PUT room status", e)

# Owner-only endpoints as resepsionis
if resep_token:
    try:
        r = requests.post(f"{BASE}/users", json={"username":"x","password":"x","role":"resepsionis","nama":"x"}, headers=H_RES, timeout=15)
        assert r.status_code == 403, r.status_code
        r = requests.get(f"{BASE}/users", headers=H_RES, timeout=15)
        assert r.status_code == 403, r.status_code
        r = requests.post(f"{BASE}/rooms", json={"nama":"X","tipe":"Standard","tarif":120000}, headers=H_RES, timeout=15)
        assert r.status_code == 403, r.status_code
        ok("owner-only endpoints reject resepsionis (403)")
    except Exception as e:
        fail("owner-only 403", e)

# Products
try:
    r = requests.get(f"{BASE}/products", headers=H_OWN, timeout=15)
    products = r.json()
    print(f"  products count={len(products)}")
    assert len(products) == 11, f"expected 11 got {len(products)}"
    ok("GET /products 11 items")
except Exception as e:
    fail("GET /products", e); products = []

# Kasir
mkn = next((p for p in products if p.get("kategori") == "makanan"), None) or next((p for p in products if (p.get("stok") or 0) > 0), None)
if mkn:
    try:
        item = {"product_id": mkn["id"], "nama": mkn["nama"], "harga": mkn["harga"], "qty": 1, "kategori": mkn.get("kategori","makanan")}
        total = mkn["harga"]
        pay = [{"metode":"tunai","jumlah": total//2 + (total%2)}, {"metode":"qris","jumlah": total//2}]
        # ensure sum equals total
        pay[0]["jumlah"] = total - pay[1]["jumlah"]
        r = requests.post(f"{BASE}/kasir", json={"items":[item], "pembayaran": pay}, headers=H_OWN, timeout=15)
        assert r.status_code == 200, r.text
        ok("POST /kasir split payment")
    except Exception as e:
        fail("POST /kasir", e)

# Kasir insufficient stock
mkn_stok = next((p for p in products if p.get("kategori") in ("makanan","minuman") and (p.get("stok") or 0) >= 0), None)
if mkn_stok:
    try:
        item = {"product_id": mkn_stok["id"], "nama": mkn_stok["nama"], "harga": mkn_stok["harga"], "qty": 99999, "kategori": mkn_stok["kategori"]}
        total = mkn_stok["harga"] * 99999
        r = requests.post(f"{BASE}/kasir", json={"items":[item], "pembayaran":[{"metode":"tunai","jumlah": total}]}, headers=H_OWN, timeout=15)
        assert r.status_code == 400, r.status_code
        ok("kasir insufficient stock 400")
    except Exception as e:
        fail("kasir insufficient stock", e)

# Expense
try:
    r = requests.post(f"{BASE}/expenses", json={"keterangan":"Test exp","kategori":"lain","jumlah":50000}, headers=H_OWN, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE}/expenses", headers=H_OWN, timeout=15)
    assert r.status_code == 200 and len(r.json()) >= 1
    ok("expenses create + list")
except Exception as e:
    fail("expenses", e)

# Reports summary
try:
    r = requests.get(f"{BASE}/reports/summary", headers=H_OWN, timeout=15)
    assert r.status_code == 200, r.text
    print(f"  summary={r.json()}")
    ok("reports/summary")
except Exception as e:
    fail("reports/summary", e)

# Reports daily
try:
    from datetime import date
    today = date.today().isoformat()
    r = requests.get(f"{BASE}/reports/daily", params={"from_date": today, "to_date": today}, headers=H_OWN, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    print(f"  daily rows={len(j) if isinstance(j,list) else 'obj'}")
    ok("reports/daily")
except Exception as e:
    fail("reports/daily", e)

# Audit log
try:
    r = requests.get(f"{BASE}/audit-log", headers=H_OWN, timeout=15)
    assert r.status_code == 200 and len(r.json()) > 0
    ok("audit-log")
except Exception as e:
    fail("audit-log", e)

print("\n=== SUMMARY ===")
print(f"Passed: {len(results['passed'])}")
print(f"Failed: {len(results['failed'])}")
for f in results["failed"]:
    print(" -", f)

with open("/tmp/results.json","w") as f:
    json.dump(results, f, indent=2)
