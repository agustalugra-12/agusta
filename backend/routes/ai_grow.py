"""AI Grow — Executive Business Intelligence (2026-07-22, PRD user, lanjutan dari
GET /reports/ai-insight yang sudah ada, sekarang digantikan modul ini sepenuhnya).

Prinsip desain (SAMA seperti semua fitur AI lain sesi ini - dipertahankan ketat karena
berulang kali terbukti perlu): PMS tetap Single Source of Truth, AI Grow TIDAK menyimpan
salinan data sendiri, murni membaca live tiap kali diminta. SEMUA angka (skor, prediksi,
korelasi, rekomendasi) dihitung DETERMINISTIK di Python - LLM (gpt-4o-mini) HANYA dipakai
untuk menarasikan angka yang sudah dihitung, tidak pernah diberi wewenang menghitung/
mengarang angka sendiri (pola identik dengan reports.py/rekening.py sebelumnya).

4 layer PRD dipetakan ke fungsi berikut:
- Layer 1 Read    -> _baca_semua_data()
- Layer 2 Understand -> _pahami_korelasi() (perbandingan periode, BUKAN machine learning -
  korelasi di sini artinya "dua indikator sama-sama bergerak", bukan pembuktian kausal)
- Layer 3 Predict -> _prediksi_bisnis() (proyeksi run-rate sederhana & transparan, BUKAN
  model statistik rumit - supaya owner bisa pahami & percaya angkanya)
- Layer 4 Recommend -> _rekomendasi() (aturan deterministik dari sinyal Opportunity/Risk)

Business Health Score, Opportunity Engine, Risk Engine, & Daily Executive Brief semua
mengorkestrasi fungsi-fungsi di atas - lihat masing-masing untuk detail formula (SEMUA
sengaja sederhana & bisa dijelaskan ke owner, bukan black-box)."""
from core import *
import asyncio
import json
import logging

logger = logging.getLogger("ai_grow")


# =====================================================================================
# LAYER 1 — READ
# =====================================================================================

async def _baca_semua_data() -> Dict[str, Any]:
    """Satu titik baca untuk seluruh data yang dibutuhkan layer di atasnya - dipanggil
    SEKALI per generate brief/score, hasilnya dipakai bersama supaya tidak query berulang."""
    from routes.reports import report_summary
    summary = await report_summary({"id": "ai-grow", "nama": "AI Grow", "role": "owner"})

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    hari_berjalan = max(1, (now - month_start).days + 1)
    hari_dalam_bulan = (month_start.replace(month=month_start.month % 12 + 1, day=1) - timedelta(days=1)).day \
        if month_start.month < 12 else 31

    # Periode sama panjang bulan lalu, supaya perbandingan month-to-date adil (bukan
    # bulan penuh vs bulan berjalan yang pasti lebih kecil).
    bulan_lalu_start = (month_start - timedelta(days=1)).replace(day=1)
    bulan_lalu_end = bulan_lalu_start + timedelta(days=hari_berjalan)

    exp_bulan_ini = await db.expenses.find({"tanggal": {"$gte": month_start.isoformat()}}, {"_id": 0, "kategori": 1, "nominal": 1}).to_list(2000)
    exp_bulan_lalu = await db.expenses.find({"tanggal": {"$gte": bulan_lalu_start.isoformat(), "$lt": bulan_lalu_end.isoformat()}}, {"_id": 0, "kategori": 1, "nominal": 1}).to_list(2000)

    def _per_kategori(items):
        out: Dict[str, int] = {}
        for e in items:
            k = e.get("kategori") or "Lainnya"
            out[k] = out.get(k, 0) + int(e.get("nominal") or 0)
        return out

    # Okupansi harian 14 hari terakhir (dari db.rooms.status TIDAK bisa historis - dipakai
    # proksi jumlah booking yang menempati tiap tanggal, sama logika dengan
    # /reports/kedatangan-harian yang sudah ada, supaya konsisten).
    batas_14 = (now - timedelta(days=14)).date().isoformat()
    bookings_14hari = await db.bookings.find({
        "jam_mulai": {"$gte": batas_14}, "status": {"$in": ["aktif", "booking_paid", "checked_in", "selesai"]},
    }, {"_id": 0, "jam_mulai": 1, "tipe": 1}).to_list(2000)

    # Komplain & maintenance
    batas_30 = (now - timedelta(days=30)).isoformat()
    batas_60 = (now - timedelta(days=60)).isoformat()
    issues_30 = await db.issues.find({"created_at": {"$gte": batas_30}}, {"_id": 0, "tipe": 1, "created_at": 1, "status": 1}).to_list(500)
    issues_prev30 = await db.issues.find({"created_at": {"$gte": batas_60, "$lt": batas_30}}, {"_id": 0, "tipe": 1}).to_list(500)
    issues_terbuka = await db.issues.count_documents({"status": {"$in": ["open", "in_progress"]}})
    hk_pending = await db.housekeeping_log.count_documents({"status": {"$in": ["pending", "cleaning"]}})

    # Housekeeping delay rata-rata (created "tanggal" -> selesai "jam_selesai"), trailing 30 hari
    hk_selesai = await db.housekeeping_log.find(
        {"status": "clean", "tanggal": {"$gte": batas_30}, "jam_selesai": {"$ne": None}},
        {"_id": 0, "tanggal": 1, "jam_selesai": 1},
    ).to_list(500)
    delay_menit = []
    for h in hk_selesai:
        try:
            mulai = datetime.fromisoformat(h["tanggal"])
            selesai = datetime.fromisoformat(h["jam_selesai"])
            delay_menit.append((selesai - mulai).total_seconds() / 60)
        except Exception:
            continue

    cash = None
    try:
        from routes.rekening import dashboard_rekening, cash_risk
        owner_ctx = {"id": "ai-grow", "nama": "AI Grow", "role": "owner"}
        dash = await dashboard_rekening(owner_ctx)
        if dash["rekening"]:
            risk = await cash_risk(owner_ctx)
            cash = {"total_cash": dash["total_cash"], "net_cash": dash["net_cash"],
                    "goals": dash["goals"], "risk": risk}
    except Exception as e:
        logger.info(f"cash data dilewati: {e}")

    # Aktivitas tamu / loyalitas (2026-07-22, gap ditemukan saat audit "Product Hardening" -
    # AI Grow sebelumnya tidak baca ini sama sekali padahal PRD eksplisit minta "aktivitas
    # pelanggan"). total_kunjungan>=2 = tamu yang pernah kembali (Program Loyalitas
    # Kedatangan, lihat diskon_member_untuk_total_kunjungan di core.py).
    total_tamu = await db.guests.count_documents({})
    tamu_berulang = await db.guests.count_documents({"total_kunjungan": {"$gte": 2}})
    tamu_baru_bulan_ini = await db.guests.count_documents({"created_at": {"$gte": month_start.isoformat()}})

    return {
        "summary": summary, "now": now, "hari_berjalan": hari_berjalan, "hari_dalam_bulan": hari_dalam_bulan,
        "guest": {"total_tamu": total_tamu, "tamu_berulang": tamu_berulang,
                  "persen_berulang": round(tamu_berulang / total_tamu * 100, 1) if total_tamu else 0,
                  "tamu_baru_bulan_ini": tamu_baru_bulan_ini},
        "exp_per_kategori_bulan_ini": _per_kategori(exp_bulan_ini),
        "exp_per_kategori_bulan_lalu": _per_kategori(exp_bulan_lalu),
        "bookings_14hari": bookings_14hari,
        "issues_30": issues_30, "n_issues_prev30": len(issues_prev30), "issues_terbuka": issues_terbuka,
        "hk_pending": hk_pending, "hk_delay_rata_menit": (sum(delay_menit) / len(delay_menit)) if delay_menit else None,
        "cash": cash,
    }


# =====================================================================================
# LAYER 2 — UNDERSTAND (perbandingan periode, deterministik)
# =====================================================================================

def _pahami_korelasi(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    temuan = []
    s = data["summary"]

    # 1) Penggerak utama biaya bulan ini vs bulan lalu (periode sepanjang sama)
    ini, lalu = data["exp_per_kategori_bulan_ini"], data["exp_per_kategori_bulan_lalu"]
    total_ini, total_lalu = sum(ini.values()), sum(lalu.values())
    if total_lalu > 0:
        delta_persen = round((total_ini - total_lalu) / total_lalu * 100, 1)
        if abs(delta_persen) >= 15:
            # kategori penyumbang delta terbesar
            semua_kat = set(ini) | set(lalu)
            penggerak = max(semua_kat, key=lambda k: ini.get(k, 0) - lalu.get(k, 0))
            temuan.append({
                "jenis": "biaya_operasional",
                "arah": "naik" if delta_persen > 0 else "turun",
                "detail": f"Pengeluaran bulan ini (s/d hari ke-{data['hari_berjalan']}) {'naik' if delta_persen > 0 else 'turun'} {abs(delta_persen)}% dibanding periode sama bulan lalu, terutama dari kategori '{penggerak}' (Rp{ini.get(penggerak,0):,} vs Rp{lalu.get(penggerak,0):,}).".replace(",", "."),
            })

    # 2) Komplain vs housekeeping delay (dua-duanya naik trailing 30 hari = sinyal terkait,
    # BUKAN pembuktian sebab-akibat - dilaporkan sebagai korelasi, bukan klaim pasti)
    n_komplain = sum(1 for i in data["issues_30"] if i["tipe"] == "complaint")
    n_komplain_prev = data["n_issues_prev30"]
    delay = data["hk_delay_rata_menit"]
    if n_komplain_prev > 0 and n_komplain > n_komplain_prev * 1.3 and delay and delay > 60:
        temuan.append({
            "jenis": "komplain_housekeeping",
            "arah": "naik",
            "detail": f"Komplain 30 hari terakhir naik dari {n_komplain_prev} ke {n_komplain} tiket, bersamaan dengan rata-rata waktu housekeeping menyelesaikan kamar {round(delay)} menit - kemungkinan terkait, perlu dicek langsung.",
        })

    # 3) Okupansi vs ADR (harga rata-rata per kamar) - kalau okupansi turun TAPI pendapatan
    # kamar per malam relatif stabil, bukan sinyal harga; kalau dua-duanya turun bareng,
    # itu penurunan permintaan murni.
    if s["okupansi_persen"] < 40 and s["pendapatan_bulan_ini"] > 0:
        temuan.append({
            "jenis": "okupansi_rendah",
            "arah": "turun",
            "detail": f"Okupansi hari ini {s['okupansi_persen']}% - di bawah 40%, cek apakah ini pola musiman atau ada masalah di kanal pemasaran/OTA.",
        })

    return temuan


# =====================================================================================
# LAYER 3 — PREDICT (proyeksi run-rate sederhana & transparan)
# =====================================================================================

def _prediksi_bisnis(data: Dict[str, Any]) -> Dict[str, Any]:
    s = data["summary"]
    hari_berjalan, hari_total = data["hari_berjalan"], data["hari_dalam_bulan"]
    faktor = hari_total / hari_berjalan

    omzet_proyeksi = round(s["pendapatan_bulan_ini"] * faktor)
    pengeluaran_proyeksi = round(s["pengeluaran_bulan_ini"] * faktor)
    laba_proyeksi = omzet_proyeksi - pengeluaran_proyeksi

    # Okupansi 7 hari ke depan - dari booking yang SUDAH ADA (fakta, bukan statistik),
    # jauh lebih bisa dipercaya daripada model prediktif untuk horizon sedekat ini.
    now = data["now"]
    okupansi_7hari = []
    total_kamar = s["total_rooms"] or 1
    for i in range(7):
        tgl = (now + timedelta(days=i)).date()
        n = 0
        for b in data["bookings_14hari"]:
            try:
                b_tgl = datetime.fromisoformat(b["jam_mulai"]).date()
            except Exception:
                continue
            if b_tgl == tgl:
                n += 1
        okupansi_7hari.append({"tanggal": tgl.isoformat(), "booking_terjadwal": n, "okupansi_persen": round(min(100, n / total_kamar * 100))})

    out = {
        "omzet_proyeksi_akhir_bulan": omzet_proyeksi, "pengeluaran_proyeksi_akhir_bulan": pengeluaran_proyeksi,
        "laba_proyeksi_akhir_bulan": laba_proyeksi, "hari_berjalan": hari_berjalan, "hari_dalam_bulan": hari_total,
        "okupansi_7hari_kedepan": okupansi_7hari,
    }
    if data["cash"]:
        goals_forecast = []
        for g in data["cash"]["goals"]:
            goals_forecast.append({"nama": g["nama"], "progress_persen": g.get("progress_persen")})
        out["goal_tabungan"] = goals_forecast
    return out


# =====================================================================================
# OPPORTUNITY ENGINE (pola weekend/weekday, deterministik dari histori booking nyata)
# =====================================================================================

async def _deteksi_opportunity() -> List[Dict[str, Any]]:
    peluang = []
    batas = (datetime.now(timezone.utc) - timedelta(days=56)).date().isoformat()  # 8 minggu
    bookings = await db.bookings.find({
        "jam_mulai": {"$gte": batas}, "status": {"$in": ["aktif", "booking_paid", "checked_in", "selesai"]},
    }, {"_id": 0, "jam_mulai": 1, "room_id": 1}).to_list(3000)
    rooms = await db.rooms.find({}, {"_id": 0, "id": 1}).to_list(200)
    total_kamar = len(rooms) or 1

    per_hari_minggu: Dict[int, List[int]] = {i: [] for i in range(7)}  # 0=Senin
    per_tanggal: Dict[str, int] = {}
    for b in bookings:
        try:
            tgl = datetime.fromisoformat(b["jam_mulai"]).date()
        except Exception:
            continue
        key = tgl.isoformat()
        per_tanggal[key] = per_tanggal.get(key, 0) + 1
    for key, n in per_tanggal.items():
        hari = datetime.fromisoformat(key).weekday()
        per_hari_minggu[hari].append(round(n / total_kamar * 100))

    rata_weekend = [v for d in (4, 5) for v in per_hari_minggu[d]]  # Jumat, Sabtu
    rata_weekday = [v for d in (0, 1, 2, 3) for v in per_hari_minggu[d]]  # Senin-Kamis
    if rata_weekend and rata_weekday:
        avg_weekend = sum(rata_weekend) / len(rata_weekend)
        avg_weekday = sum(rata_weekday) / len(rata_weekday)
        if avg_weekend >= 80 and avg_weekend - avg_weekday >= 25:
            peluang.append({
                "jenis": "harga_weekend",
                "judul": "Okupansi weekend jauh lebih tinggi dari weekday",
                "detail": f"Rata-rata okupansi Jumat-Sabtu {round(avg_weekend)}% (8 minggu terakhir), dibanding Senin-Kamis {round(avg_weekday)}%. Selisih {round(avg_weekend - avg_weekday)} poin - permintaan weekend jauh lebih tinggi dari kapasitas yang perlu diberi harga premium.",
                "rekomendasi": "Pertimbangkan menaikkan tarif kamar 10-20% khusus Jumat & Sabtu lewat Kalender Harga.",
            })

    return peluang


# =====================================================================================
# RISK ENGINE (perluasan dari cash-risk yang sudah ada, tambah okupansi/komplain/biaya)
# =====================================================================================

async def _deteksi_risk(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    risiko = []
    s = data["summary"]

    if s["okupansi_persen"] < 30:
        risiko.append({"level": "tinggi", "area": "okupansi", "detail": f"Okupansi hari ini cuma {s['okupansi_persen']}% - jauh di bawah titik aman."})
    elif s["okupansi_persen"] < 45:
        risiko.append({"level": "sedang", "area": "okupansi", "detail": f"Okupansi hari ini {s['okupansi_persen']}% - perlu dipantau."})

    n_komplain = sum(1 for i in data["issues_30"] if i["tipe"] == "complaint")
    if data["n_issues_prev30"] > 0 and n_komplain > data["n_issues_prev30"] * 1.5:
        risiko.append({"level": "sedang", "area": "komplain", "detail": f"Komplain 30 hari terakhir naik {round((n_komplain/data['n_issues_prev30']-1)*100)}% dibanding periode sebelumnya ({data['n_issues_prev30']} -> {n_komplain})."})

    if data["issues_terbuka"] >= 5:
        risiko.append({"level": "sedang", "area": "tiket_terbuka", "detail": f"{data['issues_terbuka']} tiket komplain/maintenance masih terbuka."})

    ini, lalu = data["exp_per_kategori_bulan_ini"], data["exp_per_kategori_bulan_lalu"]
    for kat, nom_ini in ini.items():
        nom_lalu = lalu.get(kat, 0)
        if nom_lalu > 0 and nom_ini > nom_lalu * 1.5 and nom_ini > 500000:
            risiko.append({"level": "sedang", "area": "biaya", "detail": f"Kategori pengeluaran '{kat}' naik {round((nom_ini/nom_lalu-1)*100)}% dibanding periode sama bulan lalu (Rp{nom_lalu:,} -> Rp{nom_ini:,}).".replace(",", ".")})

    if data["cash"]:
        for r in data["cash"]["risk"]:
            if r["status"] != "aman":
                risiko.append({"level": "tinggi" if r["status"] == "risiko_tinggi" else "sedang", "area": "kas", "detail": f"{r['nama']}: {r['keterangan']}"})

    urutan = {"tinggi": 0, "sedang": 1}
    risiko.sort(key=lambda r: urutan.get(r["level"], 2))
    return risiko


# =====================================================================================
# BUSINESS HEALTH SCORE (0-100, komposit dari 5 aspek - formula transparan & bisa
# dijelaskan penuh ke owner, bukan black-box)
# =====================================================================================

def _hitung_health_score(data: Dict[str, Any], risiko: List[Dict[str, Any]]) -> Dict[str, Any]:
    s = data["summary"]

    # Finansial (30%): margin laba bulan ini
    margin = (s["laba_bersih_bulan_ini"] / s["pendapatan_bulan_ini"] * 100) if s["pendapatan_bulan_ini"] else 0
    skor_finansial = max(0, min(100, round(margin / 40 * 100)))  # margin 40%+ = skor penuh

    # Operasional (25%): okupansi + housekeeping backlog
    skor_okupansi = max(0, min(100, round(s["okupansi_persen"] / 70 * 100)))  # 70%+ okupansi = skor penuh
    skor_hk = 100 if data["hk_pending"] <= 2 else max(0, 100 - (data["hk_pending"] - 2) * 15)
    skor_operasional = round((skor_okupansi + skor_hk) / 2)

    # Pelanggan (20%): tiket terbuka & tren komplain (70%) + tingkat tamu berulang - proksi
    # kepuasan pelanggan sungguhan, bukan cuma "tidak ada komplain" (30%)
    skor_tiket = 100 if data["issues_terbuka"] == 0 else max(0, 100 - data["issues_terbuka"] * 10)
    skor_loyalitas = min(100, round(data["guest"]["persen_berulang"] / 30 * 100)) if data["guest"]["total_tamu"] >= 5 else 70  # 30%+ berulang = skor penuh; data tamu terlalu sedikit = netral
    skor_pelanggan = round(skor_tiket * 0.7 + skor_loyalitas * 0.3)

    # Kas (15%): dari risk engine kas, 100 kalau tidak ada rekening/risiko sama sekali
    risiko_kas = [r for r in risiko if r["area"] == "kas"]
    skor_kas = 100 if not risiko_kas else (40 if any(r["level"] == "tinggi" for r in risiko_kas) else 70)

    # Pertumbuhan (10%): tren pendapatan bulan ini vs bulan lalu (proksi dari total_ini/total_lalu biaya
    # tidak representatif utk pendapatan - dihitung ulang dari margin proyeksi run-rate)
    skor_pertumbuhan = 60  # netral default kalau tidak ada data pembanding memadai
    if s["pendapatan_bulan_ini"] > 0 and data["hari_berjalan"] >= 5:
        # bandingkan run-rate harian ke rata2 3 bulan (proksi sederhana pakai laba_bersih_bulan_ini saja
        # kalau positif & margin sehat, anggap tumbuh wajar)
        skor_pertumbuhan = 80 if margin > 15 else (50 if margin > 0 else 20)

    breakdown = {
        "finansial": {"skor": skor_finansial, "bobot": 30, "keterangan": f"Margin laba bulan ini {round(margin,1)}%"},
        "operasional": {"skor": skor_operasional, "bobot": 25, "keterangan": f"Okupansi {s['okupansi_persen']}%, {data['hk_pending']} kamar antre dibersihkan"},
        "pelanggan": {"skor": skor_pelanggan, "bobot": 20, "keterangan": f"{data['issues_terbuka']} tiket terbuka, {data['guest']['persen_berulang']}% tamu berulang"},
        "kas": {"skor": skor_kas, "bobot": 15, "keterangan": "Tidak ada modul Cash & Rekening dipakai" if not data["cash"] else f"{len(risiko_kas)} rekening berisiko" if risiko_kas else "Semua rekening aman"},
        "pertumbuhan": {"skor": skor_pertumbuhan, "bobot": 10, "keterangan": "Berdasar margin laba berjalan"},
    }
    total = round(sum(b["skor"] * b["bobot"] / 100 for b in breakdown.values()))
    return {"skor": total, "breakdown": breakdown}


# =====================================================================================
# LAYER 4 — RECOMMEND (diturunkan dari sinyal Opportunity + Risk, bukan LLM bebas)
# =====================================================================================

def _rekomendasi(risiko: List[Dict[str, Any]], peluang: List[Dict[str, Any]], data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in peluang:
        out.append({"tipe": "peluang", "judul": p["judul"], "alasan": p["detail"], "aksi": p["rekomendasi"]})
    for r in risiko:
        if r["level"] == "tinggi":
            aksi = {
                "kas": "Buka Cash & Rekening, cek rekening yang berisiko, pertimbangkan transfer dari tabungan.",
                "okupansi": "Cek kanal pemasaran/OTA, pertimbangkan promo jangka pendek.",
            }.get(r["area"], "Perlu ditinjau langsung.")
            out.append({"tipe": "risiko", "judul": f"Risiko tinggi: {r['area']}", "alasan": r["detail"], "aksi": aksi})
    if data["hk_pending"] >= 5:
        out.append({
            "tipe": "operasional", "judul": "Antrean housekeeping menumpuk",
            "alasan": f"{data['hk_pending']} kamar menunggu dibersihkan saat ini.",
            "aksi": "Pertimbangkan tambahan tenaga housekeeping untuk hari-hari sibuk.",
        })
    return out[:5]


# =====================================================================================
# ORKESTRASI: Daily Executive Brief
# =====================================================================================

BRIEF_SYSTEM_PROMPT = """Kamu adalah AI Grow, Executive Business Intelligence untuk owner
Pelangi Homestay. Tulis Daily Executive Brief singkat (maksimal 8-10 kalimat pendek,
Bahasa Indonesia, gaya briefing eksekutif - to the point, bukan bertele-tele) dari data
terstruktur yang diberikan. Susun begini: (1) 1-2 kalimat kondisi hari ini (okupansi,
kas kalau ada), (2) 1-2 kalimat proyeksi akhir bulan, (3) korelasi/insight paling penting
kalau ada, (4) 2-3 rekomendasi paling prioritas dengan alasannya singkat.
ATURAN KERAS: PAKAI PERSIS angka yang diberikan, JANGAN PERNAH mengarang angka yang tidak
ada di data. Kalau suatu bagian data kosong/tidak ada, lewati saja, jangan mengarang."""


async def _generate_daily_brief() -> Dict[str, Any]:
    data = await _baca_semua_data()
    understand = _pahami_korelasi(data)
    predict = _prediksi_bisnis(data)
    opportunity = await _deteksi_opportunity()
    risk = await _deteksi_risk(data)
    health = _hitung_health_score(data, risk)
    recommend = _rekomendasi(risk, opportunity, data)

    konteks = {
        "okupansi_hari_ini_persen": data["summary"]["okupansi_persen"],
        "pendapatan_bulan_ini": data["summary"]["pendapatan_bulan_ini"],
        "pengeluaran_bulan_ini": data["summary"]["pengeluaran_bulan_ini"],
        "laba_bersih_bulan_ini": data["summary"]["laba_bersih_bulan_ini"],
        "business_health_score": health["skor"],
        "aktivitas_tamu": data["guest"],
        "proyeksi_akhir_bulan": predict,
        "korelasi_understand": understand,
        "peluang": opportunity,
        "risiko": risk,
        "rekomendasi_prioritas": recommend,
    }

    narasi = "AI belum aktif (OPENAI_API_KEY belum diisi)."
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            resp = await asyncio.to_thread(
                client.chat.completions.create, model="gpt-4o-mini", temperature=0.4,
                messages=[{"role": "system", "content": BRIEF_SYSTEM_PROMPT},
                         {"role": "user", "content": json.dumps(konteks, ensure_ascii=False, default=str)}],
            )
            narasi = resp.choices[0].message.content
        except Exception as e:
            logger.warning(f"Gagal generate narasi Daily Brief: {e}")
            narasi = "Gagal membuat ringkasan AI saat ini - lihat data di bawah langsung."

    return {
        "narasi": narasi, "health_score": health, "prediksi": predict,
        "understand": understand, "peluang": opportunity, "risiko": risk,
        "rekomendasi": recommend, "generated_at": now_iso(),
    }


@api.get("/ai-grow/daily-brief")
async def get_daily_brief(user: dict = Depends(require_owner)):
    return await _generate_daily_brief()


@api.get("/ai-grow/health-score")
async def get_health_score(user: dict = Depends(require_owner)):
    data = await _baca_semua_data()
    risk = await _deteksi_risk(data)
    return _hitung_health_score(data, risk)


async def _kirim_brief_telegram():
    from routes.telegram_bot import kirim_alert_owner
    brief = await _generate_daily_brief()
    skor = brief["health_score"]["skor"]
    pesan = (
        f"\U0001F4CA *AI Grow — Daily Executive Brief*\n"
        f"Business Health Score: *{skor}/100*\n\n"
        f"{brief['narasi']}"
    )
    await kirim_alert_owner(pesan)


async def background_daily_brief_loop():
    """Kirim Daily Executive Brief ke Telegram owner tiap hari jam 07:30 WIB (beda dari
    laporan akhir hari yang sudah ada jam 22:00 - brief ini untuk MEMULAI hari, bukan
    menutup). Cek per menit supaya presisi jamnya, kirim sekali per tanggal (dilacak
    in-memory - cukup untuk 1 proses uvicorn, sama pola dengan loop lain di server ini)."""
    terkirim_tanggal = None
    while True:
        try:
            now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
            if now_wib.hour == 7 and now_wib.minute >= 30 and terkirim_tanggal != now_wib.date():
                await _kirim_brief_telegram()
                terkirim_tanggal = now_wib.date()
        except Exception as e:
            logger.warning(f"background_daily_brief_loop error: {e}")
        await asyncio.sleep(120)
