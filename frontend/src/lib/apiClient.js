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

export default api;
