"""Pengiriman Voucher Otomatis — generate PDF voucher & kirim ke email tamu via Brevo.

Dipakai oleh routes/public.py (unduh voucher, kirim ulang manual oleh staf)
dan routes/payments.py (kirim otomatis begitu pembayaran booking berhasil).
Setiap percobaan kirim selalu dicatat ke collection `email_send_log`, baik
sukses maupun gagal, supaya halaman staf "Log Pengiriman" akurat.
"""
import io
import base64
import logging

import httpx
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core import db, os, uuid, now_iso, parse_iso, timezone, timedelta, BREVO_API_KEY, BREVO_FROM_EMAIL, BREVO_FROM_NAME

logger = logging.getLogger("email_service")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _fmt_rp(n) -> str:
    return f"Rp {int(n or 0):,}".replace(",", ".")


def _fmt_tanggal(iso: str) -> str:
    try:
        d = parse_iso(iso, "waktu").astimezone(timezone(timedelta(hours=7)))
        return d.strftime("%d %b %Y, %H:%M") + " WIB"
    except Exception:
        return iso


def generate_voucher_pdf(b: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    w, h = A5
    y = h - 20 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(15 * mm, y, "Pelangi Homestay")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    c.drawString(15 * mm, y, "Voucher / Bukti Reservasi")
    y -= 10 * mm

    c.line(15 * mm, y, w - 15 * mm, y)
    y -= 8 * mm

    def baris(label, value, bold=False):
        nonlocal y
        c.setFont("Helvetica", 10)
        c.drawString(15 * mm, y, label)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawRightString(w - 15 * mm, y, str(value))
        y -= 7 * mm

    baris("Kode Booking", b["kode"], bold=True)
    baris("Nama Tamu", b["nama_tamu"])
    baris("Kamar", f"{b['room_nomor']} ({b['room_tipe']})")
    baris("Check-In", _fmt_tanggal(b["jam_mulai"]))
    if b.get("jam_selesai"):
        baris("Check-Out", _fmt_tanggal(b["jam_selesai"]))
    baris("Jumlah Tamu", b.get("jumlah_tamu", 1))
    if b.get("extra_bed_qty"):
        baris("Extra Bed", f"x{b['extra_bed_qty']}")
    if b.get("dengan_sarapan"):
        baris("Sarapan Pagi", "Termasuk")
    y -= 3 * mm
    c.line(15 * mm, y, w - 15 * mm, y)
    y -= 8 * mm

    baris("Subtotal", _fmt_rp(b.get("subtotal")))
    baris("Service Fee", _fmt_rp(b.get("service_fee")))
    baris("Total", _fmt_rp(b.get("total")), bold=True)
    baris("Status Pembayaran", (b.get("payment_status") or "").upper(), bold=True)

    y -= 5 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(15 * mm, y, "Mohon tunjukkan voucher ini saat kedatangan. Terima kasih telah memilih Pelangi Homestay.")

    c.showPage()
    c.save()
    return buf.getvalue()


def _voucher_email_html(b: dict) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;color:#222">
      <h2 style="margin-bottom:4px">Terima kasih, {b.get('nama_tamu', 'Tamu')}!</h2>
      <p>Reservasi Anda di <b>Pelangi Homestay</b> dengan kode <b>{b.get('kode', '')}</b> sudah dikonfirmasi.</p>
      <p>Kamar {b.get('room_nomor', '')} ({b.get('room_tipe', '')}) — Check-in {_fmt_tanggal(b.get('jam_mulai', ''))}.</p>
      <p>Voucher/bukti reservasi terlampir dalam bentuk PDF. Mohon tunjukkan voucher ini saat kedatangan.</p>
      <p style="margin-top:24px">Sampai jumpa!<br/>Pelangi Homestay</p>
    </div>
    """


async def send_voucher_email(b: dict, pdf_bytes: bytes) -> dict:
    """Kirim voucher PDF ke email tamu lewat Brevo transactional email API.

    Selalu menulis satu entri ke `email_send_log` (Terkirim/Gagal), termasuk saat
    BREVO_API_KEY belum diisi atau booking tidak punya email tamu, supaya staf bisa
    melihat kenapa suatu voucher belum terkirim tanpa perlu cek server log.
    """
    log_entry = {
        "id": str(uuid.uuid4()),
        "booking_id": b["id"],
        "kode_booking": b["kode"],
        "nama_tamu": b.get("nama_tamu", ""),
        "tujuan_email": b.get("email", ""),
        "metode": "Email",
        "status": "Gagal",
        "error": None,
        "waktu": now_iso(),
    }
    if not BREVO_API_KEY or not BREVO_FROM_EMAIL:
        log_entry["error"] = "BREVO_API_KEY/BREVO_FROM_EMAIL belum dikonfigurasi di server"
    elif not b.get("email"):
        log_entry["error"] = "Booking tidak punya alamat email tamu"
    else:
        payload = {
            "sender": {"name": BREVO_FROM_NAME, "email": BREVO_FROM_EMAIL},
            "to": [{"email": b["email"], "name": b.get("nama_tamu") or "Tamu"}],
            "subject": f"Voucher Reservasi {b['kode']} - Pelangi Homestay",
            "htmlContent": _voucher_email_html(b),
            "attachment": [{
                "content": base64.b64encode(pdf_bytes).decode(),
                "name": f"voucher-{b['kode']}.pdf",
            }],
        }
        try:
            # local_address="0.0.0.0" memaksa koneksi lewat IPv4: Brevo authorised-IPs
            # di akun ini hanya mengizinkan IPv4 VPS, sementara default egress server ini IPv6.
            transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
            async with httpx.AsyncClient(timeout=15, transport=transport) as http:
                resp = await http.post(
                    BREVO_API_URL, json=payload,
                    headers={
                        "api-key": BREVO_API_KEY,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
            if resp.status_code in (200, 201):
                log_entry["status"] = "Terkirim"
            else:
                log_entry["error"] = f"Brevo {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            log_entry["error"] = str(e)

    if log_entry["status"] != "Terkirim":
        logger.warning("Gagal kirim voucher email booking %s: %s", b.get("kode"), log_entry["error"])
    await db.email_send_log.insert_one(log_entry)
    return log_entry
