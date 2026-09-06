"""Laporan Keuangan PDF Profesional (2026-09-06, permintaan Agus - "laporan profesional
yang biasa dibuat untuk perusahaan besar", dgn grafik pendapatan per tanggal + saran
peningkatan pendapatan berbasis data).

SENGAJA murni deterministik (bukan panggilan LLM) - konsisten dgn filosofi seluruh
routes/reports.py (data akuntansi harus reproducible/auditable, bukan hasil model yang
bisa beda tiap generate). "Saran" di bagian akhir dihitung dari pola data ASLI periode
ini (hari terlemah, komposisi saluran, cancel/no-show, rasio pengeluaran) - bukan teks
generik template.

Pakai reportlab (SUDAH terinstal, dipakai email_service.py utk voucher PDF) - platypus
utk layout dokumen multi-halaman, graphics.charts utk grafik batang tersemat, tidak
nambah dependency baru."""
from datetime import datetime
from typing import Any, Dict, List, Optional
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend

NAMA_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

_BIRU = colors.HexColor("#1E40AF")
_ABU = colors.HexColor("#64748B")
_HIJAU = colors.HexColor("#10B981")
_MERAH = colors.HexColor("#EF4444")


def _rp(n: Any) -> str:
    try:
        n = int(round(float(n or 0)))
    except (TypeError, ValueError):
        n = 0
    return "Rp" + f"{n:,}".replace(",", ".")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("H1Custom", parent=ss["Heading1"], textColor=_BIRU, spaceAfter=4))
    ss.add(ParagraphStyle("SubTitle", parent=ss["Normal"], textColor=_ABU, fontSize=10, spaceAfter=14))
    ss.add(ParagraphStyle("SectionHeader", parent=ss["Heading2"], textColor=_BIRU, spaceBefore=16, spaceAfter=8))
    ss.add(ParagraphStyle("Insight", parent=ss["Normal"], fontSize=10, leading=14, spaceAfter=6, leftIndent=8))
    ss.add(ParagraphStyle("Cell", parent=ss["Normal"], fontSize=8, leading=10))
    return ss


def _tabel_style(header_bg=_BIRU) -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


def _bar_chart_pendapatan_harian(daily_rows: List[Dict[str, Any]]) -> Drawing:
    """Grafik pendapatan per tanggal (kamar/kasir/service ditumpuk) - subset tanggal
    diambil merata (maks ~20 label) supaya sumbu-X tidak numpuk kalau rentang panjang."""
    drawing = Drawing(480, 220)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 50, 30, 400, 170
    step = max(1, len(daily_rows) // 20)
    subset = daily_rows[::step]
    kamar = [r.get("kamar", 0) for r in subset]
    kasir = [(r.get("makanan", 0) + r.get("minuman", 0) + r.get("laundry", 0) + r.get("lainnya", 0)) for r in subset]
    service = [r.get("service", 0) for r in subset]
    chart.data = [kamar, kasir, service]
    chart.categoryAxis.categoryNames = [r["tanggal"][5:] for r in subset]
    chart.categoryAxis.labels.angle = 45
    chart.categoryAxis.labels.dx = -6
    chart.categoryAxis.labels.fontSize = 6.5
    chart.valueAxis.labelTextFormat = lambda v: f"{v/1000:.0f}k"
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = _BIRU
    chart.bars[1].fillColor = _HIJAU
    chart.bars[2].fillColor = colors.HexColor("#F97316")
    chart.barWidth = 6
    drawing.add(chart)
    legend = Legend()
    legend.x, legend.y = 460, 190
    legend.alignment = "right"
    legend.fontSize = 7
    legend.colorNamePairs = [(_BIRU, "Kamar"), (_HIJAU, "Kasir"), (colors.HexColor("#F97316"), "Service")]
    drawing.add(legend)
    return drawing


def _hitung_saran(
    daily_rows: List[Dict[str, Any]],
    saluran_rows: List[Dict[str, Any]],
    cancel_data: Dict[str, Any],
    okupansi_avg: Optional[float],
) -> List[str]:
    """Saran peningkatan pendapatan - MURNI dari pola data periode ini, bukan template
    generik. Tiap saran cuma muncul kalau pola datanya benar-benar mengindikasikan itu
    (mis. rasio pengeluaran tinggi HANYA disebut kalau > 30%) - laporan yang jujur
    "tidak ada temuan mencolok" lebih baik drpd saran generik yang selalu sama."""
    saran: List[str] = []

    # 1. Hari terlemah vs terkuat (pola hari dalam seminggu)
    dow_totals: Dict[int, List[int]] = {}
    for r in daily_rows:
        try:
            d = datetime.fromisoformat(r["tanggal"]).weekday()
        except ValueError:
            continue
        dow_totals.setdefault(d, []).append(r.get("pendapatan", 0))
    if len(dow_totals) >= 5:
        dow_avg = {d: sum(v) / len(v) for d, v in dow_totals.items() if v}
        if dow_avg:
            terlemah = min(dow_avg, key=lambda d: dow_avg[d])
            terkuat = max(dow_avg, key=lambda d: dow_avg[d])
            if dow_avg[terkuat] > 0 and dow_avg[terlemah] < dow_avg[terkuat] * 0.6:
                saran.append(
                    f"Hari {NAMA_HARI[terlemah]} rata-rata pendapatan {_rp(dow_avg[terlemah])}, jauh di bawah "
                    f"hari {NAMA_HARI[terkuat]} ({_rp(dow_avg[terkuat])}). Pertimbangkan promo/diskon khusus "
                    f"hari {NAMA_HARI[terlemah]} untuk meratakan okupansi sepanjang minggu."
                )

    # 2. Komposisi saluran - saluran dgn kontribusi sangat kecil (<10%) tapi jumlah booking
    #    tidak nol, artinya ADA permintaan tapi belum digarap maksimal.
    total_saluran_rev = sum(r.get("pendapatan", 0) for r in saluran_rows)
    if total_saluran_rev > 0:
        for r in saluran_rows:
            pct = r.get("pendapatan", 0) / total_saluran_rev * 100
            if 0 < pct < 10 and r.get("booking", 0) > 0:
                saran.append(
                    f"Saluran '{r.get('key')}' baru menyumbang {pct:.1f}% dari pendapatan online "
                    f"({r.get('booking')} booking) - ada permintaan tapi porsinya kecil, pertimbangkan "
                    f"tingkatkan promosi/listing di saluran ini."
                )

    # 3. Cancel & no-show - kehilangan pendapatan nyata
    grand_cancel = cancel_data.get("grand_total", 0) if cancel_data else 0
    total_pendapatan = sum(r.get("pendapatan", 0) for r in daily_rows)
    if grand_cancel > 0 and total_pendapatan > 0 and grand_cancel / total_pendapatan > 0.03:
        saran.append(
            f"Cancel fee & no-show retention periode ini {_rp(grand_cancel)} "
            f"({grand_cancel / total_pendapatan * 100:.1f}% dari pendapatan) - cukup signifikan, "
            f"pertimbangkan kebijakan DP lebih tinggi atau konfirmasi H-1 utk kurangi no-show."
        )

    # 4. Rasio pengeluaran terhadap pendapatan
    total_pengeluaran = sum(r.get("pengeluaran", 0) for r in daily_rows)
    if total_pendapatan > 0:
        rasio = total_pengeluaran / total_pendapatan * 100
        if rasio > 30:
            saran.append(
                f"Rasio pengeluaran terhadap pendapatan {rasio:.1f}% - lebih tinggi dari acuan sehat "
                f"industri hospitality (~20-30%), pertimbangkan tinjau ulang pos pengeluaran terbesar "
                f"periode ini."
            )

    # 5. Okupansi rendah - peluang isi kamar kosong
    if okupansi_avg is not None and okupansi_avg < 60:
        saran.append(
            f"Rata-rata okupansi periode ini {okupansi_avg:.0f}% - masih ada ruang isi kamar kosong, "
            f"pertimbangkan paket long-stay/promo hari kerja utk naikkan okupansi."
        )

    if not saran:
        saran.append("Tidak ada pola menonjol yang butuh perhatian khusus periode ini - performa relatif stabil.")
    return saran


def _pie_chart_jenis_kamar(day_use_n: int, menginap_n: int) -> Optional[Drawing]:
    if day_use_n + menginap_n <= 0:
        return None
    drawing = Drawing(300, 150)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 75, 10, 130, 130
    pie.data = [day_use_n, menginap_n]
    pie.labels = [f"Day Use ({day_use_n})", f"Menginap ({menginap_n})"]
    pie.slices[0].fillColor = colors.HexColor("#F97316")
    pie.slices[1].fillColor = _BIRU
    drawing.add(pie)
    legend = Legend()
    legend.x, legend.y = 220, 100
    legend.fontSize = 8
    legend.colorNamePairs = [(colors.HexColor("#F97316"), "Day Use"), (_BIRU, "Menginap")]
    drawing.add(legend)
    return drawing


def _metode_bayar_ringkas(detail_pembayaran: List[Dict[str, Any]]) -> str:
    """Ringkas daftar detail_pembayaran (dari report_rooms - lihat _ambil_detail_pembayaran_
    booking/_detail_pembayaran_checkin) jadi 1 string singkat, mis. "Tunai" atau
    "QRIS + Transfer" kalau DP & pelunasan pakai metode beda."""
    metodes = [p.get("metode") for p in (detail_pembayaran or []) if p.get("metode") and p["metode"] != "-"]
    seen = []
    for m in metodes:
        if m not in seen:
            seen.append(m)
    return " + ".join(seen) if seen else "-"


def build_financial_report_pdf(
    property_name: str,
    from_date: str,
    to_date: str,
    daily_rows: List[Dict[str, Any]],
    arus_kas_rows: List[Dict[str, Any]],
    service_data: Dict[str, Any],
    saluran_rows: List[Dict[str, Any]],
    cancel_data: Dict[str, Any],
    okupansi_avg: Optional[float] = None,
    rooms_items: Optional[List[Dict[str, Any]]] = None,
    expenses_rows: Optional[List[Dict[str, Any]]] = None,
    selisih_detail: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=15 * mm, leftMargin=15 * mm, rightMargin=15 * mm,
    )
    ss = _styles()
    story: List[Any] = []

    story.append(Paragraph(f"Laporan Keuangan &ndash; {property_name}", ss["H1Custom"]))
    story.append(Paragraph(
        f"Periode {from_date} s.d. {to_date} &middot; Dibuat {datetime.now().strftime('%d %B %Y, %H:%M')} WITA",
        ss["SubTitle"],
    ))

    total_pendapatan = sum(r.get("pendapatan", 0) for r in daily_rows)
    total_pengeluaran = sum(r.get("pengeluaran", 0) for r in daily_rows)
    laba = total_pendapatan - total_pengeluaran
    total_online = sum(r.get("online", 0) for r in arus_kas_rows)
    total_masuk = sum(r.get("total_uang_masuk", 0) for r in arus_kas_rows)
    margin = (laba / total_pendapatan * 100) if total_pendapatan else 0

    ringkasan_tbl = Table([
        ["Pendapatan", "Pengeluaran", "Laba Bersih", "Margin"],
        [_rp(total_pendapatan), _rp(total_pengeluaran), _rp(laba), f"{margin:.1f}%"],
    ], colWidths=[115 * mm / 1, None, None, None], hAlign="LEFT")
    ringkasan_tbl.setStyle(_tabel_style())
    story.append(ringkasan_tbl)
    story.append(Spacer(1, 6))
    cash_tbl = Table([
        ["Online (Tripay)", "Total Uang Masuk (Cash Basis)"],
        [_rp(total_online), _rp(total_masuk)],
    ], hAlign="LEFT")
    cash_tbl.setStyle(_tabel_style(header_bg=_ABU))
    story.append(cash_tbl)

    # Penjelasan selisih Pendapatan vs Total Uang Masuk (2026-09-06, permintaan Agus -
    # "jelaskan di laporan PDF kenapa bisa ada selisih") - dihitung DINAMIS dari angka
    # periode ini sendiri (bukan teks statis) - Pendapatan = akrual (diakui saat malam
    # kamar TERPAKAI), Total Uang Masuk = cash basis (uang diterima kapan pun, tidak
    # peduli kapan tamu menginap) - DP diterima periode ini utk stay BULAN LAIN muncul
    # di Total Uang Masuk tapi belum di Pendapatan (begitu jg sebaliknya: DP bulan lalu
    # utk stay periode ini muncul di Pendapatan tapi TIDAK di Total Uang Masuk periode
    # ini) - selisih ini WAJAR/BUKAN kesalahan, sama seperti PMS profesional lain
    # (Cloudbeds/Mews/Majoo) yg selalu punya 2 laporan beda utk 2 pertanyaan beda.
    selisih = total_masuk - total_pendapatan
    if selisih != 0:
        arah = (
            "lebih banyak uang diterima periode ini dibanding pendapatan yang diakui"
            if selisih > 0 else
            "lebih banyak pendapatan diakui periode ini dibanding uang yang benar-benar diterima"
        )
        sebab = (
            "kemungkinan ada DP/pelunasan yang diterima periode ini untuk booking yang "
            "menginapnya di bulan lain (uang sudah masuk, tapi jasanya belum/sudah "
            "dikonsumsi di luar periode ini)"
            if selisih > 0 else
            "kemungkinan ada booking yang menginap periode ini tapi DP-nya sudah diterima "
            "di bulan sebelumnya (jasa sudah diakui, tapi uangnya masuk di luar periode ini)"
        )
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"<b>Kenapa Total Uang Masuk ({_rp(total_masuk)}) berbeda dari Pendapatan ({_rp(total_pendapatan)})?</b> "
            f"Selisih {_rp(abs(selisih))} ini normal, BUKAN kesalahan pencatatan - Pendapatan dihitung "
            f"saat jasa (malam kamar) benar-benar terpakai (akrual), sedangkan Total Uang Masuk dihitung "
            f"saat uang benar-benar diterima (cash basis), tidak peduli kapan tamu menginap. Periode ini "
            f"{arah} - {sebab}.",
            ss["Insight"],
        ))
        if selisih_detail:
            sel_rows = [["Tanggal", "Kode", "Nama Tamu", "Nominal", "Arah", "Keterangan"]]
            for d in selisih_detail:
                sel_rows.append([
                    d.get("tanggal", "-"),
                    Paragraph(d.get("kode") or "-", ss["Cell"]),
                    Paragraph(d.get("nama_tamu") or "-", ss["Cell"]),
                    _rp(d.get("nominal", 0)),
                    "Masuk" if d.get("arah") == "masuk" else "Keluar",
                    Paragraph(d.get("keterangan") or "-", ss["Cell"]),
                ])
            sel_tbl = Table(sel_rows, repeatRows=1, hAlign="LEFT",
                             colWidths=[18 * mm, 30 * mm, 32 * mm, 25 * mm, 15 * mm, 55 * mm])
            sel_tbl.setStyle(_tabel_style(header_bg=_ABU))
            story.append(Spacer(1, 4))
            story.append(sel_tbl)

    if rooms_items:
        day_use_n = sum(1 for it in rooms_items if it.get("tipe") == "day_use")
        menginap_n = sum(1 for it in rooms_items if it.get("tipe") == "menginap")
        rev_day_use = sum(r.get("kamar_day_use", 0) for r in daily_rows)
        rev_menginap = sum(r.get("kamar_menginap", 0) for r in daily_rows)
        story.append(Paragraph("Jenis Kamar Terjual", ss["SectionHeader"]))
        jk_tbl = Table([
            ["Jenis", "Jumlah Transaksi", "Pendapatan"],
            ["Day Use", str(day_use_n), _rp(rev_day_use)],
            ["Menginap", str(menginap_n), _rp(rev_menginap)],
        ], hAlign="LEFT")
        jk_tbl.setStyle(_tabel_style())
        story.append(jk_tbl)
        pie = _pie_chart_jenis_kamar(day_use_n, menginap_n)
        if pie:
            story.append(Spacer(1, 4))
            story.append(pie)

    if expenses_rows:
        story.append(Paragraph("Detail Pengeluaran", ss["SectionHeader"]))
        exp_rows = [["Tanggal", "Kategori", "Deskripsi", "Nominal"]]
        for e in expenses_rows:
            exp_rows.append([
                (e.get("tanggal") or "")[:10], e.get("kategori") or "-",
                Paragraph(e.get("deskripsi") or "-", ss["Cell"]), _rp(e.get("nominal", 0)),
            ])
        exp_tbl = Table(exp_rows, repeatRows=1, hAlign="LEFT", colWidths=[22 * mm, 30 * mm, 78 * mm, 30 * mm])
        exp_tbl.setStyle(_tabel_style())
        story.append(exp_tbl)

        top5 = sorted(expenses_rows, key=lambda e: e.get("nominal", 0), reverse=True)[:5]
        story.append(Paragraph("Top 5 Pengeluaran Terbesar", ss["SectionHeader"]))
        top5_rows = [["Tanggal", "Kategori", "Deskripsi", "Nominal"]]
        for e in top5:
            top5_rows.append([
                (e.get("tanggal") or "")[:10], e.get("kategori") or "-",
                Paragraph(e.get("deskripsi") or "-", ss["Cell"]), _rp(e.get("nominal", 0)),
            ])
        top5_tbl = Table(top5_rows, repeatRows=1, hAlign="LEFT", colWidths=[22 * mm, 30 * mm, 78 * mm, 30 * mm])
        top5_tbl.setStyle(_tabel_style(header_bg=_MERAH))
        story.append(top5_tbl)

    story.append(Paragraph("Grafik Pendapatan per Tanggal", ss["SectionHeader"]))
    if daily_rows:
        story.append(_bar_chart_pendapatan_harian(daily_rows))
    else:
        story.append(Paragraph("Tidak ada transaksi pada periode ini.", ss["Normal"]))

    story.append(Paragraph("Detail Pendapatan Harian", ss["SectionHeader"]))
    detail_header = ["Tanggal", "Kamar", "Kasir", "Service", "Pendapatan", "Pengeluaran", "Laba"]
    detail_rows = [detail_header]
    for r in daily_rows:
        kasir = r.get("makanan", 0) + r.get("minuman", 0) + r.get("laundry", 0) + r.get("lainnya", 0)
        detail_rows.append([
            r["tanggal"], _rp(r.get("kamar", 0)), _rp(kasir), _rp(r.get("service", 0)),
            _rp(r.get("pendapatan", 0)), _rp(r.get("pengeluaran", 0)), _rp(r.get("laba", 0)),
        ])
    detail_tbl = Table(detail_rows, repeatRows=1, hAlign="LEFT")
    detail_tbl.setStyle(_tabel_style())
    story.append(detail_tbl)

    story.append(Paragraph("Service Fee", ss["SectionHeader"]))
    svc_tbl = Table([
        ["Sumber", "Nominal", "Transaksi"],
        ["Check-in (walk-in)", _rp(service_data.get("checkin_service_fee_total", 0)), str(service_data.get("checkin_count", 0))],
        ["Booking (online/OTA/WA)", _rp(service_data.get("booking_service_fee_total", 0)), str(service_data.get("booking_count", 0))],
        ["Layanan Manual", _rp(service_data.get("manual_service_total", 0)), str(service_data.get("manual_service_count", 0))],
        ["Grand Total", _rp(service_data.get("grand_total", 0)), ""],
    ], hAlign="LEFT")
    svc_tbl.setStyle(_tabel_style())
    story.append(svc_tbl)

    if saluran_rows:
        story.append(Paragraph("Analitik Saluran", ss["SectionHeader"]))
        sal_rows = [["Saluran", "Booking", "Pendapatan"]] + [
            [r.get("key", "-"), str(r.get("booking", 0)), _rp(r.get("pendapatan", 0))] for r in saluran_rows
        ]
        sal_tbl = Table(sal_rows, hAlign="LEFT")
        sal_tbl.setStyle(_tabel_style())
        story.append(sal_tbl)

    if cancel_data and (cancel_data.get("cancel_count") or cancel_data.get("no_show_count")):
        story.append(Paragraph("Cancel & No-Show", ss["SectionHeader"]))
        cancel_tbl = Table([
            ["Jenis", "Nominal", "Jumlah"],
            ["Cancel Fee", _rp(cancel_data.get("cancel_fees_total", 0)), str(cancel_data.get("cancel_count", 0))],
            ["No-Show Retention", _rp(cancel_data.get("no_show_total", 0)), str(cancel_data.get("no_show_count", 0))],
        ], hAlign="LEFT")
        cancel_tbl.setStyle(_tabel_style())
        story.append(cancel_tbl)

    if rooms_items:
        story.append(PageBreak())
        story.append(Paragraph("Lampiran: Detail Transaksi Tamu", ss["SectionHeader"]))
        story.append(Paragraph(
            f"{len(rooms_items)} transaksi (walk-in check-in & booking online/OTA/WA), diurutkan tanggal kedatangan.",
            ss["SubTitle"],
        ))
        tamu_rows = [["Tanggal", "Nama Tamu", "Kamar", "Tipe", "Total", "Metode Bayar"]]
        for it in sorted(rooms_items, key=lambda x: x.get("jam_checkin") or ""):
            tamu_rows.append([
                (it.get("jam_checkin") or "")[:10],
                Paragraph(it.get("nama_tamu") or "-", ss["Cell"]),
                it.get("room_nomor") or "-",
                it.get("room_tipe") or "-",
                _rp(it.get("total", 0)),
                _metode_bayar_ringkas(it.get("detail_pembayaran")),
            ])
        tamu_tbl = Table(tamu_rows, repeatRows=1, hAlign="LEFT", colWidths=[20 * mm, 45 * mm, 22 * mm, 22 * mm, 28 * mm, 33 * mm])
        tamu_tbl.setStyle(_tabel_style())
        story.append(tamu_tbl)

    story.append(PageBreak())
    story.append(Paragraph("Saran Peningkatan Pendapatan", ss["SectionHeader"]))
    story.append(Paragraph(
        "Berdasarkan analisis data periode ini (bukan saran generik) - dihitung otomatis dari "
        "pola hari, komposisi saluran, cancel/no-show, dan rasio biaya periode yang sama.",
        ss["SubTitle"],
    ))
    for i, s in enumerate(_hitung_saran(daily_rows, saluran_rows, cancel_data, okupansi_avg), 1):
        story.append(Paragraph(f"{i}. {s}", ss["Insight"]))

    doc.build(story)
    return buf.getvalue()
