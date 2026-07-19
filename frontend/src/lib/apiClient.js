import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export { BACKEND_URL };
export const API_BASE = `${BACKEND_URL}/api`;

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("ph_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && !window.location.pathname.includes("/login")) {
      localStorage.removeItem("ph_token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export const fmtRp = (n) => "Rp " + (Number(n) || 0).toLocaleString("id-ID");
export const fmtDateTime = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("id-ID", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
};
export const fmtDate = (iso) => {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" }); }
  catch { return iso; }
};
export const fmtTime = (iso) => {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }); }
  catch { return iso; }
};

export function statusLabel(s) {
  return ({
    kosong: "Kosong",
    day_use: "Day Use",
    menginap: "Menginap",
    perlu_dibersihkan: "Perlu Dibersihkan",
    maintenance: "Maintenance",
  })[s] || s;
}

export function statusColor(s) {
  return ({
    kosong: "#10B981",
    day_use: "#EF4444",
    menginap: "#3B82F6",
    perlu_dibersihkan: "#F97316",
    maintenance: "#EAB308",
  })[s] || "#94A3B8";
}

// Label & warna status bayar (belum_bayar/dp/lunas) — satu sumber dipakai bersama oleh
// Dashboard, Reservasi, dan halaman booking publik, supaya labelnya selalu identik di
// semua permukaan (Booking Success, PDF, Dashboard, Reservasi) sesuai field status_bayar
// yang di-derive backend (status_bayar_booking(), backend/core.py) — bukan payment_status
// mentah yang tidak bedakan DP dari lunas.
export const STATUS_BAYAR_LABEL = { belum_bayar: "BELUM BAYAR", dp: "DP — BELUM LUNAS", lunas: "LUNAS" };
export const STATUS_BAYAR_BADGE_CLASS = {
  belum_bayar: "bg-slate-100 text-slate-700",
  dp: "bg-amber-100 text-amber-800",
  lunas: "bg-emerald-100 text-emerald-800",
};

/**
 * Ambil {status_bayar, jumlah_dibayar, sisa_tagihan} dari booking. Utamakan field yang
 * sudah di-derive backend (GET /bookings, GET /bookings/{id}, GET /public/bookings/{id}
 * semua sudah menyertakan ini) — fallback hitung sendiri di client HANYA untuk booking
 * object lama yang belum melewati endpoint yang sudah diperbarui (jaga-jaga, bukan jalur utama).
 */
export function statusBayarOf(b) {
  if (!b) return { status_bayar: "belum_bayar", jumlah_dibayar: 0, sisa_tagihan: 0 };
  if (b.status_bayar) {
    return { status_bayar: b.status_bayar, jumlah_dibayar: Number(b.jumlah_dibayar || 0), sisa_tagihan: Number(b.sisa_tagihan || 0) };
  }
  const total = Number(b.total || 0);
  const terkumpul = b.payment_status === "paid" ? Number(b.amount_due || 0) : 0;
  const status_bayar = b.payment_status !== "paid" ? "belum_bayar" : (total > 0 && terkumpul >= total ? "lunas" : "dp");
  return { status_bayar, jumlah_dibayar: terkumpul, sisa_tagihan: Math.max(0, total - terkumpul) };
}

export function waLink(phone, message = "") {
  if (!phone) return "#";
  let n = phone.replace(/\D/g, "");
  if (n.startsWith("0")) n = "62" + n.slice(1);
  else if (!n.startsWith("62")) n = "62" + n;
  return `https://wa.me/${n}${message ? "?text=" + encodeURIComponent(message) : ""}`;
}

/**
 * Build the standard WhatsApp booking confirmation message used across
 * Dashboard, Bookings, Public Booking, and any future OTA integrations.
 *
 * @param {Object} b - Booking object with keys:
 *   nama_tamu, kode, room_tipe, room_nomor, jam_mulai, jumlah_tamu,
 *   total, amount_due, dp_min, payment_status, source
 * @returns {string} Formatted WhatsApp message text
 */
export function buildBookingConfirmationMessage(b) {
  if (!b) return "";
  const nama = b.nama_tamu || "Tamu";
  const kode = b.kode || "-";
  const tipe = b.room_tipe || "-";
  const nomor = b.room_nomor || "-";
  const jumlah = b.jumlah_tamu || 1;
  const dt = b.jam_mulai ? new Date(b.jam_mulai) : null;
  const tanggal = dt
    ? dt.toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    : "-";
  const jam = dt
    ? dt.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) + " WIB"
    : "-";
  const dtOut = b.jam_selesai ? new Date(b.jam_selesai) : null;
  const isMenginap = b.tipe === "menginap";
  const nights = isMenginap && dt && dtOut ? Math.max(1, Math.round((dtOut - dt) / 86400000)) : null;
  const total = Number(b.total || 0);
  const dpMin = Number(b.dp_min || 0);
  const { status_bayar, jumlah_dibayar, sisa_tagihan } = statusBayarOf(b);
  const isLunas = status_bayar === "lunas";
  const isDp = status_bayar === "dp";
  const sisa = isDp ? sisa_tagihan : Math.max(0, total - dpMin);

  const lines = [
    `Halo *${nama}*,`,
    "",
    "Terima kasih telah melakukan reservasi di *Pelangi Homestay*.",
    "",
    isLunas
      ? "\u2705 *Booking Anda telah LUNAS & terkonfirmasi.*"
      : isDp
      ? "\u2705 *Booking Anda DP diterima & terkonfirmasi.*"
      : "\u23F3 *Booking Anda menunggu pembayaran.*",
    "",
    "\uD83D\uDCCC *Detail Reservasi*",
    `\u2022 Nomor Booking: *${kode}*`,
    `\u2022 Tipe Kamar: *${tipe}*`,
    `\u2022 Nomor Kamar: *${nomor}*`,
    `\u2022 Tanggal Check-in: *${tanggal}*`,
    `\u2022 Jam Check-in: *${jam}*`,
    ...(isMenginap && dtOut ? [
      `\u2022 Tanggal Check-out: *${dtOut.toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}*`,
      `\u2022 Lama Menginap: *${nights} malam*`,
    ] : []),
    `\u2022 Jumlah Tamu: *${jumlah}*`,
    "",
  ];

  if (total > 0) {
    lines.push("\uD83D\uDCB3 *Detail Pembayaran*");
    lines.push(`\u2022 Total Tagihan: *${fmtRp(total)}*`);
    if (isLunas) {
      lines.push(`\u2022 \u2705 Status Pembayaran: *LUNAS*`);
    } else if (isDp) {
      lines.push(`\u2022 \u2705 DP Diterima: *${fmtRp(jumlah_dibayar)}*`);
      lines.push(`\u2022 Sisa saat check-in: *${fmtRp(sisa)}*`);
    } else {
      lines.push(`\u2022 DP Minimum yang perlu dibayar: *${fmtRp(dpMin)}*`);
      lines.push(`\u2022 Sisa saat check-in: *${fmtRp(sisa)}*`);
    }
    lines.push("");
    if (!isLunas && sisa > 0) {
      lines.push("\uD83D\uDCCD Sisa pelunasan dapat dilakukan saat check-in di lokasi Pelangi Homestay.");
      lines.push("");
    }
  }

  lines.push(
    "\u2139\uFE0F *Kebijakan Pembatalan*",
    "Pembatalan H-7 s/d H-3 sebelum check-in: refund 100%. Pembatalan H-2 s/d hari check-in: biaya 50% dari total tagihan.",
    "",
    "Tamu yang tidak datang tanpa pembatalan (No Show) tidak mendapatkan refund.",
    "",
    "Mohon tunjukkan *Nomor Booking* saat kedatangan.",
    "",
    "Kami tunggu kedatangannya di *Pelangi Homestay*. \uD83D\uDE0A",
  );

  return lines.join("\n");
}

/** Convenience: build the wa.me URL directly from a booking object. */
export function bookingConfirmationWaLink(b) {
  return waLink(b?.no_hp, buildBookingConfirmationMessage(b));
}

/**
 * Build a plain-text WhatsApp receipt for a day-use check-out transaction
 * (from CheckOut.jsx `done` state — POST /checkins/{id}/checkout response).
 */
export function buildCheckoutReceiptMessage(ci) {
  if (!ci) return "";
  const lines = [
    `Halo *${ci.nama_tamu || "Tamu"}*,`,
    "",
    "Berikut bukti transaksi Anda di *Pelangi Homestay*.",
    "",
    "🧾 *Struk Check-Out*",
    `• No. Transaksi: *${ci.trx_no}*`,
    `• Kamar: *${ci.room_nomor}${ci.room_tipe ? ` (${ci.room_tipe})` : ""}*`,
    `• Check-In: *${fmtDateTime(ci.jam_checkin)}*`,
    `• Check-Out: *${fmtDateTime(ci.jam_checkout)}*`,
    `• Durasi: *${ci.durasi_jam} jam*`,
    "",
    "💳 *Rincian Biaya*",
    `• Tarif Dasar: ${fmtRp(ci.tarif_dasar)}`,
  ];
  if (ci.biaya_tambahan) lines.push(`• Overtime (${ci.overtime_jam} jam): ${fmtRp(ci.biaya_tambahan)}`);
  lines.push(`• Subtotal: ${fmtRp(ci.subtotal ?? (ci.tarif_dasar + (ci.biaya_tambahan || 0)))}`);
  if (ci.service_fee) lines.push(`• Service Fee (3%): ${fmtRp(ci.service_fee)}`);
  lines.push(`• *TOTAL: ${fmtRp(ci.total)}*`, "");
  if ((ci.pembayaran || []).length) {
    lines.push("💰 *Pembayaran*");
    for (const p of ci.pembayaran) lines.push(`• ${p.metode}: ${fmtRp(p.jumlah)}`);
    lines.push("");
  }
  lines.push("Terima kasih atas kunjungan Anda. Sampai jumpa lagi! 😊");
  return lines.join("\n");
}

/** Convenience: build the wa.me URL directly from a checkout result. */
export function checkoutReceiptWaLink(ci) {
  return waLink(ci?.no_hp, buildCheckoutReceiptMessage(ci));
}

/**
 * Build a plain-text WhatsApp receipt for a POS/kasir transaction
 * (from Kasir.jsx `last` state — POST /kasir response). Kasir sales have no
 * guest identity by default, so the phone number is passed in separately
 * (captured optionally in the UI at send time).
 */
export function buildKasirReceiptMessage(trx, namaPembeli = "") {
  if (!trx) return "";
  const lines = [
    `Halo${namaPembeli ? ` *${namaPembeli}*` : ""},`,
    "",
    "Berikut bukti transaksi Anda di *Pelangi Homestay*.",
    "",
    "🧾 *Struk Transaksi*",
    `• No. Transaksi: *${trx.trx_no}*`,
    `• Waktu: *${fmtDateTime(trx.timestamp)}*`,
    "",
    "🛒 *Item*",
    ...(trx.items || []).map((it) => `• ${it.nama} x${it.qty}: ${fmtRp(it.subtotal)}`),
    "",
    `• Subtotal: ${fmtRp(trx.subtotal)}`,
  ];
  if (trx.diskon) lines.push(`• Diskon: -${fmtRp(trx.diskon)}`);
  lines.push(`• *TOTAL: ${fmtRp(trx.total)}*`, "");
  if ((trx.pembayaran || []).length) {
    lines.push("💰 *Pembayaran*");
    for (const p of trx.pembayaran) lines.push(`• ${p.metode}: ${fmtRp(p.jumlah)}`);
    lines.push("");
  }
  lines.push("Terima kasih atas kunjungan Anda. Sampai jumpa lagi! 😊");
  return lines.join("\n");
}

/** Convenience: build the wa.me URL for a kasir transaction, given a phone number. */
export function kasirReceiptWaLink(trx, phone, namaPembeli = "") {
  return waLink(phone, buildKasirReceiptMessage(trx, namaPembeli));
}

export default api;
