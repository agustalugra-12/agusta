"""Incident Engine (2026-08-12, PRD "Owner Control Center" Fase 1, permintaan Agus langsung
"ok kerjakan" setelah review PRD 47-bagian) - koleksi + helper generik utk event yang butuh
perhatian owner, ditampilkan lewat Action Center bot Telegram owner (lihat telegram_bot.py).

Skema SENGAJA ramping (13 field) utk 2 sumber event pertama (ai_claim_mismatch dari
ai-chat-bot, collection_required dari loop di bawah) - field `meta` bebas isi per
event_type, jadi sumber event baru nanti TIDAK butuh migrasi skema, cukup isi meta beda.

TIDAK dibangun sbg event-bus generik utk SEMUA jenis event masa depan (itu scope Fase 2+
PRD) - collection ini murni backing-store utk Action Center v1."""
from core import *

SEVERITY_EMOJI = {"urgent": "🔴", "warning": "🟠", "info": "🟡"}

BURST_WINDOW_MIN = 15  # (2026-08-13) jendela deteksi burst utk Root Cause Correlation
BURST_THRESHOLD = 3    # >= N incident event_type+source+property_id sama dlm jendela ini
                        # dianggap kemungkinan 1 akar masalah, bukan N insiden independen


async def _correlate_incident(doc: dict) -> None:
    """Root Cause Correlation v1 (2026-08-13, PRD "Owner Control Center" Fase 5 §46) -
    mengisi doc["correlation_id"] kalau incident baru ini kemungkinan besar berbagi akar
    masalah dgn incident lain yang masih open. Dipanggil dari create_incident() SEBELUM
    insert. SENGAJA cuma 2 sinyal yang buktinya jelas dari data yang sudah ada (bukan
    ML/statistik spekulatif - Incident Engine sendiri baru berjalan sejak 2026-08-12,
    belum ada histori cukup utk "belajar" pola apa pun - lihat diskusi Fase 5 dgn Agus:
    predictive anomaly detection & auto-remediation SENGAJA ditunda krn alasan yang sama):

    1. Entity correlation - incident lain (event_type APA PUN) yg meta.booking_id-nya
       SAMA PERSIS. Contoh nyata: collection_required (tamu checked-in belum lunas) &
       checkout_blocked (staf coba checkout, ditolak) utk booking yang sama = SATU akar
       masalah (tamu belum bayar), bukan 2 masalah terpisah - sebelum ini keduanya tampil
       sbg 2 baris tak terhubung di Action Center.
    2. Burst correlation - >= BURST_THRESHOLD incident dgn event_type+source+property_id
       SAMA dlm BURST_WINDOW_MIN menit terakhir. Contoh nyata: ai_claim_mismatch bisa
       meletup berkali-kali dlm hitungan menit kalau 1 KB entry rusak/1 tool salah schema
       - tanpa ini, tiap kejadian severity="urgent" push Telegram terpisah (lihat
       _push_incident_urgent di telegram_bot.py), jadi 5 kejadian dari 1 akar masalah =
       5 notifikasi URGENT terpisah yg membanjiri owner.

    TIDAK mencoba korelasi meta.booking_kode (tripay_settlement_not_posted/
    payment_log_orphan) ke meta.booking_id - butuh resolusi kode->id yg belum pasti
    presisi utk semua kasus, sama alasan hati-hati yg sudah dipakai di
    background_business_truth_scan_loop (lihat komentar di situ) - jangan gabungkan yg
    buktinya belum jelas."""
    booking_id = (doc.get("meta") or {}).get("booking_id")
    if booking_id:
        sibling = await db.incidents.find_one(
            {"status": "open", "meta.booking_id": booking_id, "id": {"$ne": doc["id"]}},
            {"_id": 0, "id": 1, "correlation_id": 1},
        )
        if sibling:
            cid = sibling.get("correlation_id") or str(uuid.uuid4())
            if not sibling.get("correlation_id"):
                await db.incidents.update_one({"id": sibling["id"]}, {"$set": {"correlation_id": cid}})
                await db.incident_correlation_groups.insert_one({
                    "id": cid, "kind": "entity", "key": f"booking_id:{booking_id}",
                    "property_id": doc.get("property_id"), "created_at": now_iso(),
                    "telegram_messages": [],
                })
            doc["correlation_id"] = cid
            return

    batas = (datetime.now(timezone.utc) - timedelta(minutes=BURST_WINDOW_MIN)).isoformat()
    recent = await db.incidents.find(
        {"status": "open", "event_type": doc["event_type"], "source": doc["source"],
         "property_id": doc.get("property_id"), "created_at": {"$gte": batas}},
        {"_id": 0, "id": 1, "correlation_id": 1},
    ).to_list(50)
    if len(recent) + 1 >= BURST_THRESHOLD:
        existing_cid = next((r["correlation_id"] for r in recent if r.get("correlation_id")), None)
        cid = existing_cid or str(uuid.uuid4())
        if not existing_cid:
            ids = [r["id"] for r in recent]
            await db.incidents.update_many({"id": {"$in": ids}}, {"$set": {"correlation_id": cid}})
            await db.incident_correlation_groups.insert_one({
                "id": cid, "kind": "burst", "key": f"{doc['event_type']}:{doc['source']}",
                "property_id": doc.get("property_id"), "created_at": now_iso(),
                "telegram_messages": [],
            })
        doc["correlation_id"] = cid


async def create_incident(event_type: str, severity: str, title: str, detail: str = "",
                           source: str = "pms", property_id: Optional[str] = None,
                           dedup_key: Optional[str] = None, meta: Optional[dict] = None) -> Optional[dict]:
    """Buat incident baru. `dedup_key` (2026-08-12) - kalau diisi & sudah ada incident
    BERSTATUS OPEN dgn key sama, SKIP (return None) - mencegah kondisi persisten (mis.
    tamu belum lunas) bikin incident baru tiap siklus scan selama masih belum diselesaikan.
    Event one-off (mis. AI ketahuan mengarang sekali) TIDAK diberi dedup_key - tiap
    kejadian layak jadi incident sendiri."""
    if dedup_key:
        existing = await db.incidents.find_one({"dedup_key": dedup_key, "status": "open"})
        if existing:
            return None
    doc = {
        "id": str(uuid.uuid4()), "event_type": event_type, "severity": severity, "status": "open",
        "source": source, "property_id": property_id, "title": title, "detail": detail,
        "dedup_key": dedup_key, "meta": meta or {}, "created_at": now_iso(),
        "notified_at": None, "resolved_at": None, "resolved_by": None, "correlation_id": None,
    }
    await _correlate_incident(doc)
    await db.incidents.insert_one(doc)
    if severity == "urgent":
        # Import DI DALAM fungsi (bukan top-level) - hindari circular import, sama trik
        # yang sudah dipakai integrasi_ai_bot.py utk kirim_alert_owner.
        from routes.telegram_bot import _push_incident_urgent
        try:
            await _push_incident_urgent(doc)
        except Exception as e:
            logging.getLogger("incidents").warning(f"Gagal push incident urgent {doc['id']}: {e}")
    doc.pop("_id", None)
    return doc


async def list_open_incidents(property_id: Optional[str] = None, limit: int = 20) -> list:
    q: Dict[str, Any] = {"status": "open"}
    if property_id:
        q["property_id"] = property_id
    return await db.incidents.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)


async def get_incident(incident_id: str) -> Optional[dict]:
    return await db.incidents.find_one({"id": incident_id}, {"_id": 0})


async def resolve_incident(incident_id: str, resolved_by: str = "") -> Optional[dict]:
    """Atomic - kalau sudah "resolved" sebelumnya (mis. 2 tap "Tandai Selesai" nyaris
    bersamaan, atau auto-resolve loop barengan tap manual), return None ke pemanggil
    KEDUA, bukan menimpa resolved_by/resolved_at yang sudah tercatat."""
    doc = await db.incidents.find_one_and_update(
        {"id": incident_id, "status": "open"},
        {"$set": {"status": "resolved", "resolved_at": now_iso(), "resolved_by": resolved_by}},
        return_document=True,
    )
    if doc:
        doc.pop("_id", None)
    return doc


async def background_collection_required_scan_loop():
    """Scan berkala booking Menginap checked_in dgn sisa_tagihan > 0 (2026-08-12) - data
    sumbernya (status_bayar_booking, bookings.status=="checked_in") SUDAH ADA & benar,
    cuma belum pernah disilangkan jadi 1 alert sebelum ini. dedup_key per booking
    mencegah re-alert tiap siklus selama masih open; auto-resolve kalau sisa_tagihan
    sudah 0 di siklus berikutnya.

    SENGAJA dibatasi tipe=="menginap" saja - tamu Day Use checked_in punya sumber
    kebenaran saldo TERPISAH (db.checkins.pembayaran, bukan bookings.amount_due yang
    pernah terbukti bisa basi utk kasus itu, cuma disinkron di titik checkout 2026-08-09).
    Day Use Collection Required = follow-up terpisah nanti, BUKAN bagian pass ini.

    TIDAK disambungkan langsung ke collect_balance() (routes/bookings.py) - hindari
    coupling baru di titik itu. Begitu staf collect bayaran, incident tetap "open" sampai
    siklus scan berikutnya (maks INTERVAL_SEC) baru auto-resolve - cukup utk v1, bukan bug."""
    INTERVAL_SEC = 900  # 15 menit
    while True:
        try:
            properti_aktif = await db.properties.find({"aktif": True}, {"_id": 0, "id": 1}).to_list(50)
            for p in properti_aktif:
                pid = p["id"]
                bookings = await db.bookings.find(
                    scoped({"status": "checked_in", "tipe": "menginap"}, pid),
                    {"_id": 0, "id": 1, "kode": 1, "total": 1, "payment_status": 1,
                     "amount_due": 1, "room_nomor": 1, "nama_tamu": 1},
                ).to_list(500)
                for b in bookings:
                    sb = status_bayar_booking(b)
                    dedup_key = f"collection_required:{b['id']}"
                    if sb["sisa_tagihan"] > 0:
                        sisa_str = f"{sb['sisa_tagihan']:,}".replace(",", ".")
                        await create_incident(
                            event_type="collection_required", severity="warning", source="pms",
                            property_id=pid, dedup_key=dedup_key,
                            title=f"Sisa tagihan {b.get('kode')} - Rp{sisa_str}",
                            detail=f"Kamar {b.get('room_nomor') or '-'} · {b.get('nama_tamu') or '-'} · "
                                   f"sudah check-in, sisa tagihan Rp{sisa_str}",
                            meta={"booking_id": b["id"], "booking_kode": b.get("kode"), "sisa_tagihan": sb["sisa_tagihan"]},
                        )
                    else:
                        existing = await db.incidents.find_one({"dedup_key": dedup_key, "status": "open"})
                        if existing:
                            await resolve_incident(existing["id"], resolved_by="system:auto-lunas")
        except Exception as e:
            logging.getLogger("incidents").warning(f"Gagal scan Collection Required: {e}")
        await asyncio.sleep(INTERVAL_SEC)


async def background_business_truth_scan_loop():
    """Business Truth Reconciliation (2026-08-13, PRD "Owner Control Center" §21) - silang
    cek 2 sumber uang yang independen (db.payment_log = log transaksi Tripay, dan
    db.rekening_transaksi = ledger kas via auto_posting()) yang SELAMA INI tidak pernah
    disilangkan sama sekali - keduanya bisa drift diam-diam tanpa ada yang tahu (lihat
    komentar auto_posting() di routes/rekening.py: "kalau belum ada rekening default,
    diam-diam dilewati").

    3 cek yang buktinya jelas (bukan spekulatif) - Cek A/B (2026-08-12) + Cek C
    booking_marked_paid_no_settlement (2026-08-13, sebelumnya sengaja ditunda, lihat
    komentar di Cek C soal validasi thd data produksi asli sblm dibangun). Day Use
    reconciliation TETAP belum dibangun - sumber kebenarannya terpisah
    (db.checkins.pembayaran, bukan db.bookings), perlu perlakuan sendiri spt
    background_collection_required_scan_loop.

    INTERVAL 1 jam (beda dari collection_required 15 menit) - ini isu pembukuan
    back-office, bukan urgensi tamu."""
    INTERVAL_SEC = 3600  # 1 jam
    LOOKBACK_HARI = 7
    while True:
        try:
            batas_lookback = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_HARI)).isoformat()
            properti_aktif = await db.properties.find({"aktif": True}, {"_id": 0, "id": 1}).to_list(50)
            for p in properti_aktif:
                pid = p["id"]

                # Cek A - tripay_settlement_not_posted: settlement Tripay yang TIDAK
                # ketemu baris rekening_transaksi yang cocok (auto_posting kemungkinan
                # ke-skip diam-diam, atau bug serupa 2026-08-09 "ditagih dobel"/"tidak
                # ke-post" yang pernah nyata terjadi).
                #
                # `gateway: "tripay"` WAJIB ada di filter (2026-08-13, bug nyata ditemukan
                # SENDIRI pas cek hasil scan pertama) - draft awal tidak filter `gateway`
                # sama sekali, jadi entri payment_log dari collect_balance()/mark_paid_manual()
                # (transaction_status="settlement" juga, tapi `gateway` TIDAK PERNAH diisi di
                # 2 fungsi itu, beda sumber sama sekali dari webhook Tripay) ikut ke-scan &
                # SEMUA 16 kejadian nyata di scan pertama ternyata FALSE POSITIVE murni -
                # bukan settlement Tripay yang belum ke-posting, tapi memang bukan Tripay
                # sama sekali (auto_posting "Booking Tamu (Tripay)" tidak pernah relevan
                # utknya). Investigasi false positive ini JUSTRU nemu bug NYATA terpisah:
                # collect_balance()/mark_paid_manual() sendiri TIDAK PERNAH panggil
                # auto_posting() sama sekali - lihat fix di routes/bookings.py.
                settlements = await db.payment_log.find(
                    scoped({"gateway": "tripay", "transaction_status": {"$in": ["settlement", "capture"]},
                            "updated_at": {"$gte": batas_lookback}}, pid),
                    {"_id": 0, "id": 1, "booking_kode": 1, "gross_amount": 1, "updated_at": 1},
                ).to_list(500)
                for s in settlements:
                    dedup_key = f"tripay_settlement_not_posted:{s['id']}"
                    try:
                        nominal = int(float(s.get("gross_amount") or 0))
                    except (TypeError, ValueError):
                        continue
                    if nominal <= 0:
                        continue
                    try:
                        t_settle = datetime.fromisoformat(s["updated_at"])
                    except (TypeError, ValueError):
                        continue
                    jendela_awal = (t_settle - timedelta(days=1)).isoformat()
                    jendela_akhir = (t_settle + timedelta(days=1)).isoformat()
                    match = await db.rekening_transaksi.find_one(scoped({
                        "kategori": "Booking Tamu (Tripay)", "nominal": nominal,
                        "tanggal": {"$gte": jendela_awal, "$lte": jendela_akhir},
                    }, pid))
                    if not match:
                        nominal_str = f"{nominal:,}".replace(",", ".")
                        await create_incident(
                            event_type="tripay_settlement_not_posted", severity="warning", source="pms",
                            property_id=pid, dedup_key=dedup_key,
                            title=f"Settlement Tripay belum ke-posting - {s.get('booking_kode') or '-'} Rp{nominal_str}",
                            detail=f"Booking {s.get('booking_kode') or '-'} · settlement Tripay Rp{nominal_str} "
                                   f"tapi tidak ketemu baris ledger kas (rekening_transaksi) yang cocok - "
                                   f"kemungkinan rekening operasional default belum diset, atau ada bug posting.",
                            meta={"payment_log_id": s["id"], "booking_kode": s.get("booking_kode"), "nominal": nominal},
                        )
                    else:
                        existing = await db.incidents.find_one({"dedup_key": dedup_key, "status": "open"})
                        if existing:
                            await resolve_incident(existing["id"], resolved_by="system:auto-match")

                # Cek B - payment_log_orphan: callback Tripay yang gagal ditebak booking-nya
                # sama sekali (routes/tripay.py:206-213, saat ini cuma di-log warning,
                # TIDAK PERNAH sampai ke owner). Tidak ada scoped() property_id di sini
                # krn justru property_id-nya sendiri yang tidak diketahui (booking_id null).
                orphans = await db.payment_log.find(
                    {"booking_id": None, "updated_at": {"$gte": batas_lookback}},
                    {"_id": 0, "id": 1, "order_id": 1, "gross_amount": 1},
                ).to_list(200)
                for o in orphans:
                    try:
                        nominal = int(float(o.get("gross_amount") or 0))
                    except (TypeError, ValueError):
                        nominal = 0
                    nominal_str = f"{nominal:,}".replace(",", ".")
                    await create_incident(
                        event_type="payment_log_orphan", severity="warning", source="pms",
                        property_id=None, dedup_key=f"payment_log_orphan:{o['id']}",
                        title=f"Callback Tripay tanpa booking - order {o.get('order_id')} Rp{nominal_str}",
                        detail=f"Order {o.get('order_id')} · Rp{nominal_str} · sistem gagal mencocokkan "
                               f"callback ini ke booking manapun (order_id tidak match pola kode booking "
                               f"apa pun). Uang mungkin sudah diterima Tripay tapi tidak tertaut ke booking "
                               f"nyata - perlu ditinjau manual, mungkin butuh dicocokkan tangan lewat dashboard Tripay.",
                        meta={"payment_log_id": o["id"], "order_id": o.get("order_id"), "nominal": nominal},
                    )

                # Cek C - booking_marked_paid_no_settlement (2026-08-13, sebelumnya
                # SENGAJA ditunda - lihat catatan lama di docstring - krn butuh filter
                # payment_option yang presisi. Diverifikasi thd data produksi asli
                # sebelum dibangun (bukan tebakan): booking.source == "walk_in" (7/7
                # paid tanpa payment_log - cash dibayar LANGSUNG saat Quick Book dibuat,
                # dicatat di booking.pembayaran, bukan payment_log by design) & "ota"
                # (132/138 paid tanpa payment_log - tamu RedDoorz bayar ke RedDoorz,
                # bukan ke PMS, lihat komentar _cocokkan_booking_pending_reddoorz di
                # routes/otomasi_email.py) DIKECUALIKAN krn memang tidak pernah & tidak
                # perlu punya payment_log - flag di sini utk keduanya SELALU false positive.
                #
                # Ditemukan sendiri lewat investigasi validasi di atas (2026-08-13):
                # booking GRUP (>1 kamar, 1x checkout, lihat komentar group_id di
                # tripay_create_transaction) - transaksi Tripay dibuat SEKALI atas nama
                # booking PERTAMA grup saja, jadi payment_log HANYA tertaut ke kode
                # booking pertama itu - booking lain dlm grup yang sama (payment_status
                # ikut "paid") TIDAK PERNAH punya payment_log dgn kode mereka SENDIRI,
                # walau uangnya sudah benar-benar tercatat (via sibling-nya). Ini pola
                # BY DESIGN, bukan bug - cek group_id dulu sblm menyimpulkan "tidak ada
                # settlement", cegah false-positive utk SETIAP booking grup di masa
                # depan (bukan cuma 3 kejadian yg ditemukan hari ini).
                kandidat = await db.bookings.find(
                    scoped({"payment_status": "paid", "source": {"$nin": ["walk_in", "ota"]},
                            "paid_at": {"$gte": batas_lookback}}, pid),
                    {"_id": 0, "id": 1, "kode": 1, "total": 1, "amount_due": 1, "group_id": 1, "source": 1},
                ).to_list(500)
                for b in kandidat:
                    dedup_key = f"booking_marked_paid_no_settlement:{b['id']}"
                    log_sendiri = await db.payment_log.find_one({"booking_kode": b.get("kode")})
                    ada_settlement = bool(log_sendiri)
                    if not ada_settlement and b.get("group_id"):
                        saudara = await db.bookings.find(
                            {"group_id": b["group_id"], "id": {"$ne": b["id"]}}, {"_id": 0, "kode": 1},
                        ).to_list(20)
                        for s2 in saudara:
                            if await db.payment_log.find_one({"booking_kode": s2.get("kode")}):
                                ada_settlement = True
                                break
                    if not ada_settlement:
                        total_str = f"{int(b.get('total') or 0):,}".replace(",", ".")
                        await create_incident(
                            event_type="booking_marked_paid_no_settlement", severity="warning", source="pms",
                            property_id=pid, dedup_key=dedup_key,
                            title=f"Booking lunas tanpa jejak pembayaran - {b.get('kode')} Rp{total_str}",
                            detail=f"Booking {b.get('kode')} (sumber: {b.get('source')}) berstatus lunas tapi "
                                   f"tidak ketemu baris payment_log yang membuktikannya (bukan walk_in/OTA yang "
                                   f"memang dikecualikan, & bukan bagian booking grup yang settlement-nya ada di "
                                   f"kode saudaranya) - perlu ditinjau, kemungkinan bug di jalur yang menandai "
                                   f"lunas atau data pembayaran yang hilang.",
                            meta={"booking_id": b["id"], "booking_kode": b.get("kode"), "total": b.get("total")},
                        )
                    else:
                        existing = await db.incidents.find_one({"dedup_key": dedup_key, "status": "open"})
                        if existing:
                            await resolve_incident(existing["id"], resolved_by="system:auto-match")
        except Exception as e:
            logging.getLogger("incidents").warning(f"Gagal scan Business Truth Reconciliation: {e}")
        await asyncio.sleep(INTERVAL_SEC)


@api.get("/incidents")
async def list_incidents_endpoint(user: dict = Depends(require_owner)):
    """Verifikasi/debug tanpa Telegram (2026-08-12) - list incident open, sumber kebenaran
    yang sama dgn Action Center bot."""
    return await list_open_incidents()
