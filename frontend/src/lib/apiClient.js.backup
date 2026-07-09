import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
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
  const total = Number(b.total || 0);
  const dp = Number(b.amount_due || 0);
  const sisa = Math.max(0, total - dp);
  const isLunas = total > 0 && dp >= total;

  const lines = [
    `Halo *${nama}*,`,
    "",
    "Terima kasih telah melakukan reservasi di *Pelangi Homestay*.",
    "",
    "✅ *Booking Anda telah dikonfirmasi.*",
    "",
    "📌 *Detail Reservasi*",
    `• Nomor Booking: *${kode}*`,
    `• Tipe Kamar: *${tipe}*`,
    `• Nomor Kamar: *${nomor}*`,
    `• Tanggal Check-in: *${tanggal}*`,
    `• Jam Check-in: *${jam}*`,
    `• Jumlah Tamu: *${jumlah}*`,
    "",
  ];

  if (total > 0) {
    lines.push("💳 *Detail Pembayaran*");
    lines.push(`• Total Tagihan: *${fmtRp(total)}*`);
    if (isLunas) {
      lines.push(`• ✅ Status Pembayaran: *LUNAS*`);
    } else {
      lines.push(`• DP Dibayarkan: *${fmtRp(dp)}*`);
      lines.push(`• Sisa Pelunasan: *${fmtRp(sisa)}*`);
    }
    lines.push("");
    if (!isLunas && sisa > 0) {
      lines.push("📍 Sisa pelunasan dapat dilakukan saat check-in di lokasi Pelangi Homestay.");
      lines.push("");
    }
  }

  lines.push(
    "ℹ️ *Kebijakan Pembatalan*",
    "Pembatalan dapat dilakukan maksimal H-1 sebelum tanggal check-in dengan biaya pembatalan sebesar 10% dari total tagihan.",
    "",
    "Pembatalan pada hari check-in atau tamu tidak datang (No Show) tidak mendapatkan refund.",
    "",
    "Mohon tunjukkan *Nomor Booking* saat kedatangan.",
    "",
    "Kami tunggu kedatangannya di *Pelangi Homestay*. 😊",
  );

  return lines.join("\n");
}

/** Convenience: build the wa.me URL directly from a booking object. */
export function bookingConfirmationWaLink(b) {
  return waLink(b?.no_hp, buildBookingConfirmationMessage(b));
}

export default api;
