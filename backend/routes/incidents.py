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
        "notified_at": None, "resolved_at": None, "resolved_by": None,
    }
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

    SENGAJA cuma 2 cek yang buktinya jelas (bukan spekulatif) - lihat plan lengkap utk
    cek yang SENGAJA belum dibangun (booking_paid_no_settlement, Day Use reconciliation)
    krn butuh filter payment_option yang belum pasti presisi/sumber kebenaran terpisah.

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
        except Exception as e:
            logging.getLogger("incidents").warning(f"Gagal scan Business Truth Reconciliation: {e}")
        await asyncio.sleep(INTERVAL_SEC)


@api.get("/incidents")
async def list_incidents_endpoint(user: dict = Depends(require_owner)):
    """Verifikasi/debug tanpa Telegram (2026-08-12) - list incident open, sumber kebenaran
    yang sama dgn Action Center bot."""
    return await list_open_incidents()
