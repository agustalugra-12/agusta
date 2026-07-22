"""Cash & Account Intelligence (2026-07-22, PRD "AI Grow" - modul di dalam Pelangi PMS,
BUKAN produk terpisah, disepakati bareng user).

V1 (ledger manual, TIDAK auto-sync dari db.bookings/db.expenses yang sudah ada - keputusan
sadar supaya cepat kepakai & tidak menyentuh alur uang production yang sudah ada):
- CRUD rekening (operasional/tabungan/pinjaman), saldo tersimpan di field `saldo` & selalu
  diubah via $inc atomik (bukan dihitung ulang dari riwayat tiap request).
- Transaksi manual (pemasukan/pengeluaran) & transfer antar rekening (transfer TIDAK pernah
  masuk laba-rugi/pengeluaran - 2 entri ledger jenis transfer_keluar/transfer_masuk, saling
  berpasangan via `transfer_id`, terpisah total dari db.expenses/db.bookings yang sudah ada).
- Dashboard ringkasan (Total Cash, per jenis, Net Cash) & progress goal tabungan.

V2 (2026-07-22):
- Rekonsiliasi CSV mutasi bank - COCOKKAN terhadap ledger manual, TIDAK PERNAH auto-create
  entri dari baris CSV yang tidak cocok (owner yang putuskan, sama seperti pola review PDF
  OTA yang sudah ada di routes/otomasi_email.py).
- Smart Allocation (transfer otomatis) - trigger saldo_diatas (dicek tiap kali saldo rekening
  asal berubah, TIDAK direkursi ke transfer yang dihasilkannya sendiri - cegah infinite loop)
  & trigger tanggal_bulanan (dicek oleh background loop harian).
- Forecast tabungan (dari rata-rata pemasukan bersih historis) & forecast/risiko kas
  operasional (dari rata-rata burn rate harian historis).

Semua endpoint owner-only (require_owner) - data posisi kas & saldo antar rekening sensitif,
sama seperti Payroll."""
from core import *
import csv
import io as _io
import asyncio

REKENING_TRANSAKSI_JENIS = ["pemasukan", "pengeluaran", "transfer_keluar", "transfer_masuk"]


# ---- Helpers ----

def _rekening_out(r: dict) -> dict:
    r = dict(r)
    r.pop("_id", None)
    if r.get("jenis") == "tabungan" and r.get("target"):
        r["progress_persen"] = round(min(100, max(0, int(r.get("saldo") or 0) / r["target"] * 100)), 1)
    return r


async def _catat_transaksi(rekening_id: str, jenis: str, nominal: int, kategori: str, deskripsi: str,
                            tanggal: Optional[str], user: dict, source: str = "manual",
                            rekening_pasangan_id: Optional[str] = None, transfer_id: Optional[str] = None,
                            cek_smart_rule: bool = True) -> dict:
    """Satu fungsi terpusat utk semua penulisan ledger + update saldo atomik ($inc) - dipakai
    oleh transaksi manual, transfer (2x, sisi keluar & masuk), dan rekonsiliasi CSV (nanti)."""
    delta = nominal if jenis in ("pemasukan", "transfer_masuk") else -nominal
    doc = {
        "id": str(uuid.uuid4()), "rekening_id": rekening_id, "jenis": jenis,
        "nominal": int(nominal), "kategori": kategori or "", "deskripsi": deskripsi or "",
        "tanggal": tanggal or now_iso(), "rekening_pasangan_id": rekening_pasangan_id,
        "transfer_id": transfer_id, "direkonsiliasi": False, "source": source,
        "created_by": user["nama"], "created_by_id": user["id"], "created_at": now_iso(),
    }
    await db.rekening_transaksi.insert_one(doc)
    await db.rekening.update_one({"id": rekening_id}, {"$set": {"updated_at": now_iso()}, "$inc": {"saldo": delta}})
    doc.pop("_id", None)
    if cek_smart_rule:
        await _cek_smart_rules_saldo(rekening_id, user)
    return doc


async def _cek_smart_rules_saldo(rekening_id: str, user: dict):
    """Trigger saldo_diatas - dipanggil tiap kali saldo `rekening_id` berubah. SENGAJA tidak
    dipanggil ulang utk rekening_tujuan_id di dalam transfer yang dihasilkan fungsi ini sendiri
    (cek_smart_rule=False di pemanggilan _catat_transaksi di bawah) - cegah rantai/infinite
    loop kalau saldo tujuan kebetulan juga di atas ambang rule lain."""
    rules = await db.rekening_smart_rule.find({
        "rekening_asal_id": rekening_id, "trigger_tipe": "saldo_diatas", "aktif": True,
    }).to_list(50)
    if not rules:
        return
    r = await db.rekening.find_one({"id": rekening_id})
    if not r:
        return
    saldo = int(r.get("saldo") or 0)
    for rule in rules:
        ambang = int(rule.get("ambang_saldo") or 0)
        nominal = int(rule.get("nominal_transfer") or 0)
        if saldo > ambang and nominal > 0 and saldo - nominal >= 0:
            await _catat_transaksi(rekening_id, "transfer_keluar", nominal, "Smart Allocation",
                                    f"Otomatis (aturan: {rule.get('nama')})", None, user,
                                    source="smart_rule", rekening_pasangan_id=rule["rekening_tujuan_id"],
                                    cek_smart_rule=False)
            await _catat_transaksi(rule["rekening_tujuan_id"], "transfer_masuk", nominal, "Smart Allocation",
                                    f"Otomatis (aturan: {rule.get('nama')})", None, user,
                                    source="smart_rule", rekening_pasangan_id=rekening_id,
                                    cek_smart_rule=False)
            await log_activity(user, "smart_allocation",
                                f"Smart Allocation '{rule.get('nama')}' jalan: Rp{nominal:,} dari saldo di atas Rp{ambang:,}".replace(",", "."))
            saldo -= nominal


# ---- CRUD Rekening ----

@api.post("/rekening")
async def buat_rekening(body: RekeningCreate, user: dict = Depends(require_owner)):
    if body.jenis not in REKENING_JENIS:
        raise HTTPException(400, f"Jenis harus salah satu dari: {', '.join(REKENING_JENIS)}")
    if body.target is not None and body.jenis != "tabungan":
        raise HTTPException(400, "Target cuma berlaku untuk rekening jenis tabungan")
    doc = {
        "id": str(uuid.uuid4()), "nama": body.nama, "bank": body.bank,
        "no_rekening": body.no_rekening, "pemilik": body.pemilik, "jenis": body.jenis,
        "saldo": int(body.saldo_awal or 0), "target": body.target,
        "warna": body.warna, "icon": body.icon, "status": "aktif",
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.rekening.insert_one(doc)
    if body.saldo_awal:
        await db.rekening_transaksi.insert_one({
            "id": str(uuid.uuid4()), "rekening_id": doc["id"], "jenis": "pemasukan",
            "nominal": int(body.saldo_awal), "kategori": "Saldo Awal",
            "deskripsi": "Saldo awal saat rekening dibuat", "tanggal": now_iso(),
            "rekening_pasangan_id": None, "transfer_id": None, "direkonsiliasi": False,
            "source": "manual", "created_by": user["nama"], "created_by_id": user["id"],
            "created_at": now_iso(),
        })
    await log_activity(user, "buat_rekening", f"Tambah rekening {body.nama} ({body.jenis}), saldo awal Rp{body.saldo_awal:,}".replace(",", "."))
    return _rekening_out(doc)


@api.get("/rekening")
async def list_rekening(jenis: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_owner)):
    q: Dict[str, Any] = {}
    if jenis:
        q["jenis"] = jenis
    if status:
        q["status"] = status
    items = await db.rekening.find(q, {"_id": 0}).sort("created_at", 1).to_list(200)
    return [_rekening_out(r) for r in items]


@api.put("/rekening/{rid}")
async def update_rekening(rid: str, body: RekeningUpdate, user: dict = Depends(require_owner)):
    r = await db.rekening.find_one({"id": rid})
    if not r:
        raise HTTPException(404, "Rekening tidak ditemukan")
    if body.target is not None and r["jenis"] != "tabungan":
        raise HTTPException(400, "Target cuma berlaku untuk rekening jenis tabungan")
    if body.status is not None and body.status not in ("aktif", "nonaktif"):
        raise HTTPException(400, "Status harus 'aktif' atau 'nonaktif'")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        return _rekening_out(r)
    updates["updated_at"] = now_iso()
    await db.rekening.update_one({"id": rid}, {"$set": updates})
    await log_activity(user, "update_rekening", f"Ubah rekening {r['nama']}")
    return _rekening_out(await db.rekening.find_one({"id": rid}, {"_id": 0}))


@api.delete("/rekening/{rid}")
async def hapus_rekening(rid: str, user: dict = Depends(require_owner)):
    r = await db.rekening.find_one({"id": rid})
    if not r:
        raise HTTPException(404, "Rekening tidak ditemukan")
    if int(r.get("saldo") or 0) != 0:
        raise HTTPException(400, "Rekening masih punya saldo - pindahkan/nolkan dulu saldonya sebelum dihapus")
    n_rule = await db.rekening_smart_rule.count_documents({"$or": [{"rekening_asal_id": rid}, {"rekening_tujuan_id": rid}]})
    if n_rule:
        raise HTTPException(400, "Rekening masih dipakai di Smart Allocation Rule - hapus/ubah aturannya dulu")
    await db.rekening.delete_one({"id": rid})
    await db.rekening_transaksi.delete_many({"rekening_id": rid})
    await log_activity(user, "hapus_rekening", f"Hapus rekening {r['nama']}")
    return {"ok": True}


# ---- Transaksi manual (pemasukan/pengeluaran) ----

@api.post("/rekening/transaksi")
async def buat_transaksi(body: RekeningTransaksiCreate, user: dict = Depends(require_owner)):
    if body.jenis not in ("pemasukan", "pengeluaran"):
        raise HTTPException(400, "jenis harus 'pemasukan' atau 'pengeluaran'")
    if body.nominal <= 0:
        raise HTTPException(400, "Nominal harus lebih dari 0")
    r = await db.rekening.find_one({"id": body.rekening_id})
    if not r:
        raise HTTPException(404, "Rekening tidak ditemukan")
    if body.jenis == "pengeluaran" and int(r.get("saldo") or 0) < body.nominal and r["jenis"] != "pinjaman":
        raise HTTPException(400, f"Saldo {r['nama']} tidak cukup (saldo Rp{int(r.get('saldo') or 0):,})".replace(",", "."))
    doc = await _catat_transaksi(body.rekening_id, body.jenis, body.nominal, body.kategori,
                                  body.deskripsi, body.tanggal, user)
    await log_activity(user, "transaksi_rekening",
                        f"{body.jenis.capitalize()} Rp{body.nominal:,} di {r['nama']}".replace(",", ""))
    return doc


@api.get("/rekening/transaksi")
async def list_transaksi(rekening_id: Optional[str] = None, jenis: Optional[str] = None,
                          from_date: Optional[str] = None, to_date: Optional[str] = None,
                          user: dict = Depends(require_owner)):
    q: Dict[str, Any] = {}
    if rekening_id:
        q["rekening_id"] = rekening_id
    if jenis:
        q["jenis"] = jenis
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date: rng["$gte"] = from_date
        if to_date: rng["$lte"] = to_date
        q["tanggal"] = rng
    items = await db.rekening_transaksi.find(q, {"_id": 0}).sort("tanggal", -1).to_list(500)
    return items


@api.delete("/rekening/transaksi/{tid}")
async def hapus_transaksi(tid: str, user: dict = Depends(require_owner)):
    """Hanya untuk transaksi manual (pemasukan/pengeluaran) - transfer & smart_rule dihapus
    lewat pembatalan transfer (belum ada endpoint-nya di V1, sengaja - transfer sebaiknya
    dikoreksi lewat transaksi balik, bukan dihapus, supaya jejak audit tetap utuh)."""
    t = await db.rekening_transaksi.find_one({"id": tid})
    if not t:
        raise HTTPException(404, "Transaksi tidak ditemukan")
    if t["jenis"] not in ("pemasukan", "pengeluaran") or t.get("transfer_id"):
        raise HTTPException(400, "Cuma transaksi pemasukan/pengeluaran manual yang bisa dihapus langsung")
    delta = -t["nominal"] if t["jenis"] == "pemasukan" else t["nominal"]
    await db.rekening.update_one({"id": t["rekening_id"]}, {"$inc": {"saldo": delta}, "$set": {"updated_at": now_iso()}})
    await db.rekening_transaksi.delete_one({"id": tid})
    await log_activity(user, "hapus_transaksi_rekening", f"Hapus transaksi {t['jenis']} Rp{t['nominal']:,}".replace(",", "."))
    return {"ok": True}


# ---- Transfer antar rekening ----

@api.post("/rekening/transfer")
async def transfer_rekening(body: TransferIn, user: dict = Depends(require_owner)):
    if body.rekening_asal_id == body.rekening_tujuan_id:
        raise HTTPException(400, "Rekening asal & tujuan tidak boleh sama")
    if body.nominal <= 0:
        raise HTTPException(400, "Nominal harus lebih dari 0")
    asal = await db.rekening.find_one({"id": body.rekening_asal_id})
    tujuan = await db.rekening.find_one({"id": body.rekening_tujuan_id})
    if not asal or not tujuan:
        raise HTTPException(404, "Rekening asal/tujuan tidak ditemukan")
    if int(asal.get("saldo") or 0) < body.nominal:
        raise HTTPException(400, f"Saldo {asal['nama']} tidak cukup (saldo Rp{int(asal.get('saldo') or 0):,})".replace(",", "."))
    transfer_id = str(uuid.uuid4())
    keluar = await _catat_transaksi(body.rekening_asal_id, "transfer_keluar", body.nominal, "Transfer Internal",
                                     body.deskripsi, body.tanggal, user,
                                     rekening_pasangan_id=body.rekening_tujuan_id, transfer_id=transfer_id)
    masuk = await _catat_transaksi(body.rekening_tujuan_id, "transfer_masuk", body.nominal, "Transfer Internal",
                                    body.deskripsi, body.tanggal, user,
                                    rekening_pasangan_id=body.rekening_asal_id, transfer_id=transfer_id)
    await log_activity(user, "transfer_rekening",
                        f"Transfer Rp{body.nominal:,} dari {asal['nama']} ke {tujuan['nama']}".replace(",", "."))
    return {"transfer_id": transfer_id, "keluar": keluar, "masuk": masuk}


@api.get("/rekening/transfer")
async def list_transfer(user: dict = Depends(require_owner)):
    items = await db.rekening_transaksi.find(
        {"jenis": "transfer_keluar"}, {"_id": 0}
    ).sort("tanggal", -1).to_list(200)
    nama_map = {r["id"]: r["nama"] for r in await db.rekening.find({}, {"_id": 0, "id": 1, "nama": 1}).to_list(200)}
    out = []
    for t in items:
        out.append({
            "transfer_id": t["transfer_id"], "nominal": t["nominal"], "deskripsi": t["deskripsi"],
            "tanggal": t["tanggal"], "dari": nama_map.get(t["rekening_id"], "?"),
            "ke": nama_map.get(t["rekening_pasangan_id"], "?"), "source": t["source"],
        })
    return out


# ---- Dashboard ----

@api.get("/rekening/dashboard")
async def dashboard_rekening(user: dict = Depends(require_owner)):
    items = await db.rekening.find({"status": "aktif"}, {"_id": 0}).to_list(200)
    per_jenis: Dict[str, int] = {"operasional": 0, "tabungan": 0, "pinjaman": 0}
    for r in items:
        per_jenis[r["jenis"]] = per_jenis.get(r["jenis"], 0) + int(r.get("saldo") or 0)
    total_cash = per_jenis["operasional"] + per_jenis["tabungan"]
    net_cash = total_cash - per_jenis["pinjaman"]
    goals = [_rekening_out(r) for r in items if r["jenis"] == "tabungan" and r.get("target")]
    transfer_terakhir = await list_transfer(user)
    return {
        "total_cash": total_cash, "operasional": per_jenis["operasional"],
        "tabungan": per_jenis["tabungan"], "pinjaman": per_jenis["pinjaman"],
        "net_cash": net_cash, "rekening": [_rekening_out(r) for r in items],
        "goals": goals, "transfer_terakhir": transfer_terakhir[:5],
    }


# ---- Forecast & Cash Risk (V2) ----

async def _rata_rata_harian_bersih(rekening_id: str, hari: int = 30) -> float:
    """Rata-rata perubahan saldo bersih per hari, `hari` terakhir - dari histori transaksi
    sungguhan (pemasukan/transfer_masuk positif, pengeluaran/transfer_keluar negatif)."""
    batas = (datetime.now(timezone.utc) - timedelta(days=hari)).isoformat()
    items = await db.rekening_transaksi.find({
        "rekening_id": rekening_id, "tanggal": {"$gte": batas}, "kategori": {"$ne": "Saldo Awal"},
    }, {"_id": 0, "jenis": 1, "nominal": 1}).to_list(2000)
    if not items:
        return 0.0
    bersih = sum(t["nominal"] if t["jenis"] in ("pemasukan", "transfer_masuk") else -t["nominal"] for t in items)
    return bersih / hari


@api.get("/rekening/{rid}/forecast")
async def forecast_rekening(rid: str, user: dict = Depends(require_owner)):
    r = await db.rekening.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rekening tidak ditemukan")
    rata_bulanan = await _rata_rata_harian_bersih(rid, 90) * 30
    saldo = int(r.get("saldo") or 0)
    out = {"rekening_id": rid, "nama": r["nama"], "saldo": saldo, "rata_rata_bersih_per_bulan": round(rata_bulanan)}
    if r.get("jenis") == "tabungan" and r.get("target"):
        sisa = r["target"] - saldo
        if sisa <= 0:
            out.update({"status": "tercapai", "estimasi_bulan": 0, "estimasi_tanggal": None})
        elif rata_bulanan <= 0:
            out.update({"status": "tidak_bisa_diperkirakan", "estimasi_bulan": None, "estimasi_tanggal": None})
        else:
            bulan = sisa / rata_bulanan
            tanggal = datetime.now(timezone.utc) + timedelta(days=bulan * 30)
            out.update({"status": "berjalan", "estimasi_bulan": round(bulan, 1), "estimasi_tanggal": tanggal.strftime("%Y-%m-%d")})
    return out


@api.get("/rekening/cash-risk")
async def cash_risk(user: dict = Depends(require_owner)):
    """Deteksi risiko kehabisan kas untuk tiap rekening operasional aktif, dari tren burn
    rate harian 30 hari terakhir. Ambang: <14 hari = Risiko Tinggi, <30 hari = Perlu
    Diperhatikan, selain itu = Aman. (Ambang angka bulat wajar, bisa disesuaikan nanti kalau
    user mau lebih ketat/longgar - belum ada permintaan spesifik soal ini.)"""
    items = await db.rekening.find({"jenis": "operasional", "status": "aktif"}, {"_id": 0}).to_list(100)
    out = []
    for r in items:
        rata_harian = await _rata_rata_harian_bersih(r["id"], 30)
        saldo = int(r.get("saldo") or 0)
        if rata_harian >= 0:
            out.append({"rekening_id": r["id"], "nama": r["nama"], "saldo": saldo, "status": "aman",
                        "hari_tersisa": None, "keterangan": "Tren kas stabil/positif 30 hari terakhir."})
            continue
        hari_tersisa = saldo / abs(rata_harian) if rata_harian != 0 else None
        if hari_tersisa is None:
            status, ket = "aman", "Belum cukup data histori transaksi."
        elif hari_tersisa < 14:
            status, ket = "risiko_tinggi", f"Diperkirakan habis dalam {round(hari_tersisa)} hari pada tren saat ini."
        elif hari_tersisa < 30:
            status, ket = "perlu_diperhatikan", f"Diperkirakan cukup untuk {round(hari_tersisa)} hari pada tren saat ini."
        else:
            status, ket = "aman", f"Diperkirakan cukup untuk {round(hari_tersisa)}+ hari."
        out.append({"rekening_id": r["id"], "nama": r["nama"], "saldo": saldo, "status": status,
                    "hari_tersisa": round(hari_tersisa) if hari_tersisa else None, "keterangan": ket})
    return out


# ---- AI Insight (reuse pola OpenAI yang sama dengan Telegram bot owner) ----

INSIGHT_SYSTEM_PROMPT = """Kamu adalah asisten kas eksekutif untuk owner Pelangi Homestay.
Tulis ringkasan kondisi kas singkat (maksimal 5-6 kalimat pendek, gaya seperti briefing
eksekutif - lihat contoh), Bahasa Indonesia, berdasarkan data yang diberikan.
ATURAN KERAS: PAKAI PERSIS angka yang diberikan di data, JANGAN PERNAH mengarang/menaksir
angka yang tidak ada di data. Kalau suatu data tidak tersedia (mis. forecast tidak bisa
dihitung), jangan sebut-sebut itu sama sekali - jangan mengarang alasan.
Contoh gaya (bukan template wajib, cuma referensi nada):
"Cash perusahaan saat ini Rp135.000.000. Sebesar Rp82.000.000 sudah dialokasikan menjadi
dana tabungan. Dana operasional aman untuk 24 hari. Dana Renovasi diperkirakan mencapai
target dalam 5 bulan. Tidak ada risiko likuiditas.\""""


@api.get("/rekening/insight")
async def ai_insight(user: dict = Depends(require_owner)):
    dash = await dashboard_rekening(user)
    risk = await cash_risk(user)
    forecasts = []
    for g in dash["goals"]:
        f = await forecast_rekening(g["id"], user)
        if f.get("status") == "berjalan":
            forecasts.append(f)
    konteks = (
        f"Total Cash: Rp{dash['total_cash']:,}\n"
        f"Operasional: Rp{dash['operasional']:,}\n"
        f"Tabungan: Rp{dash['tabungan']:,}\n"
        f"Pinjaman: Rp{dash['pinjaman']:,}\n"
        f"Net Cash: Rp{dash['net_cash']:,}\n"
        f"Risiko kas operasional: {[(r['nama'], r['status'], r.get('hari_tersisa')) for r in risk]}\n"
        f"Forecast goal tabungan: {[(f['nama'], f.get('estimasi_bulan'), f.get('estimasi_tanggal')) for f in forecasts]}\n"
    ).replace(",", ".")
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    if not client:
        return {"insight": "AI belum aktif (OPENAI_API_KEY belum diisi) - lihat angka di dashboard langsung."}
    try:
        resp = await asyncio.to_thread(
            client.chat.completions.create, model="gpt-4o-mini", temperature=0.4,
            messages=[{"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
                     {"role": "user", "content": konteks}],
        )
        return {"insight": resp.choices[0].message.content}
    except Exception as e:
        logging.getLogger("rekening").warning(f"Gagal generate AI insight kas: {e}")
        return {"insight": "Gagal membuat ringkasan AI saat ini - lihat angka di dashboard langsung."}


# ---- Smart Allocation Rules (V2) ----

@api.post("/rekening/smart-rules")
async def buat_smart_rule(body: SmartAllocationRuleCreate, user: dict = Depends(require_owner)):
    if body.trigger_tipe not in ("saldo_diatas", "tanggal_bulanan"):
        raise HTTPException(400, "trigger_tipe harus 'saldo_diatas' atau 'tanggal_bulanan'")
    if body.trigger_tipe == "saldo_diatas" and not body.ambang_saldo:
        raise HTTPException(400, "ambang_saldo wajib diisi untuk trigger saldo_diatas")
    if body.trigger_tipe == "tanggal_bulanan" and not (body.tanggal_hari and 1 <= body.tanggal_hari <= 28):
        raise HTTPException(400, "tanggal_hari wajib diisi (1-28) untuk trigger tanggal_bulanan")
    if body.rekening_asal_id == body.rekening_tujuan_id:
        raise HTTPException(400, "Rekening asal & tujuan tidak boleh sama")
    for rid in (body.rekening_asal_id, body.rekening_tujuan_id):
        if not await db.rekening.find_one({"id": rid}):
            raise HTTPException(404, f"Rekening {rid} tidak ditemukan")
    doc = {
        "id": str(uuid.uuid4()), "nama": body.nama, "rekening_asal_id": body.rekening_asal_id,
        "rekening_tujuan_id": body.rekening_tujuan_id, "trigger_tipe": body.trigger_tipe,
        "ambang_saldo": body.ambang_saldo, "tanggal_hari": body.tanggal_hari,
        "nominal_transfer": body.nominal_transfer, "aktif": body.aktif,
        "last_triggered_period": None, "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.rekening_smart_rule.insert_one(doc)
    await log_activity(user, "buat_smart_rule", f"Tambah Smart Allocation Rule '{body.nama}'")
    doc.pop("_id", None)
    return doc


@api.get("/rekening/smart-rules")
async def list_smart_rules(user: dict = Depends(require_owner)):
    items = await db.rekening_smart_rule.find({}, {"_id": 0}).sort("created_at", 1).to_list(100)
    nama_map = {r["id"]: r["nama"] for r in await db.rekening.find({}, {"_id": 0, "id": 1, "nama": 1}).to_list(200)}
    for it in items:
        it["rekening_asal_nama"] = nama_map.get(it["rekening_asal_id"], "?")
        it["rekening_tujuan_nama"] = nama_map.get(it["rekening_tujuan_id"], "?")
    return items


@api.put("/rekening/smart-rules/{ruleid}")
async def update_smart_rule(ruleid: str, body: SmartAllocationRuleUpdate, user: dict = Depends(require_owner)):
    rule = await db.rekening_smart_rule.find_one({"id": ruleid})
    if not rule:
        raise HTTPException(404, "Rule tidak ditemukan")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        rule.pop("_id", None)
        return rule
    updates["updated_at"] = now_iso()
    await db.rekening_smart_rule.update_one({"id": ruleid}, {"$set": updates})
    await log_activity(user, "update_smart_rule", f"Ubah Smart Allocation Rule '{rule['nama']}'")
    out = await db.rekening_smart_rule.find_one({"id": ruleid}, {"_id": 0})
    return out


@api.delete("/rekening/smart-rules/{ruleid}")
async def hapus_smart_rule(ruleid: str, user: dict = Depends(require_owner)):
    rule = await db.rekening_smart_rule.find_one({"id": ruleid})
    if not rule:
        raise HTTPException(404, "Rule tidak ditemukan")
    await db.rekening_smart_rule.delete_one({"id": ruleid})
    await log_activity(user, "hapus_smart_rule", f"Hapus Smart Allocation Rule '{rule['nama']}'")
    return {"ok": True}


async def jalankan_smart_rules_tanggal_bulanan():
    """Dipanggil oleh background loop harian (server.py) - cek rule trigger_tipe=tanggal_bulanan
    yang jatuh hari ini & belum pernah jalan bulan ini (last_triggered_period != YYYY-MM
    sekarang), transfer otomatis kalau saldo asal cukup (kalau tidak cukup, dilewati - dicoba
    lagi otomatis besok kalau masih hari yang sama... tidak, cukup dilewati bulan ini, owner
    akan lihat saldo tidak berubah & bisa transfer manual - tidak perlu retry kompleks utk V2)."""
    now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
    period = now_wib.strftime("%Y-%m")
    rules = await db.rekening_smart_rule.find({
        "trigger_tipe": "tanggal_bulanan", "aktif": True, "tanggal_hari": now_wib.day,
        "last_triggered_period": {"$ne": period},
    }).to_list(50)
    if not rules:
        return
    system_user = {"nama": "Smart Allocation (otomatis)", "id": "system"}
    for rule in rules:
        asal = await db.rekening.find_one({"id": rule["rekening_asal_id"]})
        nominal = int(rule.get("nominal_transfer") or 0)
        if not asal or int(asal.get("saldo") or 0) < nominal:
            logging.getLogger("rekening").info(f"Smart rule tanggal_bulanan '{rule['nama']}' dilewati - saldo tidak cukup")
            continue
        try:
            await _catat_transaksi(rule["rekening_asal_id"], "transfer_keluar", nominal, "Smart Allocation",
                                    f"Otomatis (aturan: {rule['nama']})", None, system_user,
                                    source="smart_rule", rekening_pasangan_id=rule["rekening_tujuan_id"], cek_smart_rule=False)
            await _catat_transaksi(rule["rekening_tujuan_id"], "transfer_masuk", nominal, "Smart Allocation",
                                    f"Otomatis (aturan: {rule['nama']})", None, system_user,
                                    source="smart_rule", rekening_pasangan_id=rule["rekening_asal_id"], cek_smart_rule=False)
            await db.rekening_smart_rule.update_one({"id": rule["id"]}, {"$set": {"last_triggered_period": period, "updated_at": now_iso()}})
        except Exception as e:
            logging.getLogger("rekening").warning(f"Smart rule tanggal_bulanan '{rule['nama']}' gagal: {e}")


async def background_smart_rule_loop():
    """Cek 1x/hari (bukan 1x/jam - trigger tanggal_bulanan tidak butuh presisi jam) apakah
    ada Smart Allocation Rule tanggal_bulanan yang jatuh hari ini. Loop pertama langsung jalan
    saat startup (jaga-jaga kalau server baru nyala persis di tanggal yang jadi trigger)."""
    while True:
        try:
            await jalankan_smart_rules_tanggal_bulanan()
        except Exception as e:
            logging.getLogger("rekening").warning(f"background_smart_rule_loop error: {e}")
        await asyncio.sleep(6 * 3600)


# ---- Rekonsiliasi CSV mutasi bank (V2) ----

def _parse_nominal_csv(raw: str) -> int:
    bersih = re.sub(r"[^0-9-]", "", raw or "")
    return int(bersih) if bersih not in ("", "-") else 0


def _tebak_tipe_csv(raw: str) -> Optional[str]:
    v = (raw or "").strip().lower()
    if v in ("masuk", "kredit", "credit", "cr", "+", "in"):
        return "pemasukan"
    if v in ("keluar", "debit", "debet", "dr", "-", "out"):
        return "pengeluaran"
    return None


@api.post("/rekening/{rid}/rekonsiliasi-csv")
async def rekonsiliasi_csv(rid: str, file: UploadFile = File(...), user: dict = Depends(require_owner)):
    """Format CSV yang didukung: kolom header `tanggal,keterangan,nominal,tipe` (tipe =
    masuk/keluar atau kredit/debit atau +/-). Setiap baris dicocokkan terhadap
    db.rekening_transaksi milik rekening ini yang BELUM `direkonsiliasi`, nominal PERSIS
    sama & tanggal dalam +-3 hari - kalau ketemu, ditandai direkonsiliasi=true. TIDAK PERNAH
    auto-membuat transaksi baru dari baris yang tidak cocok - cuma dilaporkan ke owner untuk
    ditinjau manual (sama seperti pola review PDF settlement OTA yang sudah ada)."""
    r = await db.rekening.find_one({"id": rid})
    if not r:
        raise HTTPException(404, "Rekening tidak ditemukan")
    raw = (await file.read()).decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(_io.StringIO(raw))
    if reader.fieldnames is None:
        raise HTTPException(400, "CSV kosong/tidak terbaca")
    kolom = {k.strip().lower(): k for k in reader.fieldnames}
    wajib = ["tanggal", "keterangan", "nominal", "tipe"]
    if not all(k in kolom for k in wajib):
        raise HTTPException(400, f"CSV wajib punya kolom: {', '.join(wajib)} (ditemukan: {', '.join(reader.fieldnames)})")

    cocok, tidak_cocok = [], []
    for row in reader:
        tanggal_raw = (row.get(kolom["tanggal"]) or "").strip()
        keterangan = (row.get(kolom["keterangan"]) or "").strip()
        nominal = _parse_nominal_csv(row.get(kolom["nominal"]) or "")
        tipe = _tebak_tipe_csv(row.get(kolom["tipe"]) or "")
        if not tanggal_raw or nominal <= 0 or not tipe:
            tidak_cocok.append({"tanggal": tanggal_raw, "keterangan": keterangan, "nominal": nominal, "error": "baris tidak valid (tanggal/nominal/tipe kosong atau tidak dikenali)"})
            continue
        try:
            tgl = datetime.fromisoformat(tanggal_raw[:10])
        except Exception:
            tidak_cocok.append({"tanggal": tanggal_raw, "keterangan": keterangan, "nominal": nominal, "error": "format tanggal tidak dikenali (pakai YYYY-MM-DD)"})
            continue
        jenis_cocok = ["pemasukan", "transfer_masuk"] if tipe == "pemasukan" else ["pengeluaran", "transfer_keluar"]
        rentang_awal = (tgl - timedelta(days=3)).isoformat()
        rentang_akhir = (tgl + timedelta(days=3)).isoformat()
        kandidat = await db.rekening_transaksi.find_one({
            "rekening_id": rid, "jenis": {"$in": jenis_cocok}, "nominal": nominal,
            "direkonsiliasi": False, "tanggal": {"$gte": rentang_awal, "$lte": rentang_akhir},
        })
        if kandidat:
            await db.rekening_transaksi.update_one({"id": kandidat["id"]}, {"$set": {"direkonsiliasi": True, "direkonsiliasi_at": now_iso()}})
            cocok.append({"tanggal": tanggal_raw, "keterangan": keterangan, "nominal": nominal, "tipe": tipe, "cocok_dengan": kandidat["id"]})
        else:
            tidak_cocok.append({"tanggal": tanggal_raw, "keterangan": keterangan, "nominal": nominal, "tipe": tipe, "error": "tidak ada transaksi ledger yang cocok - kemungkinan belum dicatat manual"})

    ledger_belum_cocok = await db.rekening_transaksi.find({
        "rekening_id": rid, "direkonsiliasi": False, "jenis": {"$in": ["pemasukan", "pengeluaran", "transfer_keluar", "transfer_masuk"]},
    }, {"_id": 0}).sort("tanggal", -1).to_list(100)

    await log_activity(user, "rekonsiliasi_csv", f"Rekonsiliasi CSV {r['nama']}: {len(cocok)} cocok, {len(tidak_cocok)} tidak cocok")
    return {"rekening": r["nama"], "total_baris": len(cocok) + len(tidak_cocok), "cocok": cocok,
            "tidak_cocok": tidak_cocok, "ledger_belum_direkonsiliasi": ledger_belum_cocok}


# Endpoint detail 1 rekening (path parameterized "/rekening/{rid}") SENGAJA didaftarkan PALING
# AKHIR di antara semua GET "/rekening/..." lain - FastAPI/Starlette mencocokkan rute
# berdasarkan URUTAN DIDAFTARKAN, bukan spesifisitas; kalau ini didaftarkan lebih dulu, request
# ke path literal seperti "/rekening/dashboard" akan salah kena sini duluan (rid="dashboard")
# dan gagal 404 "Rekening tidak ditemukan" - insiden nyata ditemukan saat testing 2026-07-22.
@api.get("/rekening/{rid}")
async def get_rekening(rid: str, user: dict = Depends(require_owner)):
    r = await db.rekening.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rekening tidak ditemukan")
    riwayat = await db.rekening_transaksi.find({"rekening_id": rid}, {"_id": 0}).sort("tanggal", -1).to_list(100)
    out = _rekening_out(r)
    out["riwayat"] = riwayat
    return out
