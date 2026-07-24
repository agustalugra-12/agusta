import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api from "@/lib/apiClient";

const AuthCtx = createContext(null);

// Multi-properti (2026-07-25, Fase 3): properti aktif disimpan di localStorage (bukan
// cuma state React) supaya apiClient.js (modul biasa, bukan komponen - tidak bisa baca
// context React) bisa menyisipkan header X-Property-Id di setiap request lewat interceptor
// axios yang sudah ada, persis pola yang sama dengan ph_token.
const ACTIVE_PROPERTY_KEY = "ph_active_property_id";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [properties, setProperties] = useState([]);
  const [activePropertyId, setActivePropertyIdState] = useState(() => localStorage.getItem(ACTIVE_PROPERTY_KEY) || null);

  const setActivePropertyId = useCallback((id) => {
    if (id) localStorage.setItem(ACTIVE_PROPERTY_KEY, id);
    else localStorage.removeItem(ACTIVE_PROPERTY_KEY);
    setActivePropertyIdState(id);
    // Reload penuh (bukan sekadar update state) - paling sederhana & aman supaya SEMUA
    // halaman yang sudah terlanjur fetch data properti lama ikut fetch ulang dengan
    // header X-Property-Id yang baru, tanpa perlu audit ulang tiap halaman satu-satu.
    window.location.reload();
  }, []);

  const loadProperties = useCallback(async (currentUser) => {
    if (currentUser?.role !== "owner") {
      // Resepsionis terkunci ke propertinya sendiri (backend juga menegakkan ini,
      // header apa pun dari sini diabaikan) - tetap simpan biar switcher (kalau ada)
      // bisa tampilkan nama propertinya.
      setActivePropertyIdState(currentUser?.property_id || null);
      setProperties([]);
      return;
    }
    try {
      const { data } = await api.get("/properties");
      setProperties(data);
      const saved = localStorage.getItem(ACTIVE_PROPERTY_KEY);
      const stillValid = saved && data.some((p) => p.id === saved);
      if (!stillValid && data.length) {
        localStorage.setItem(ACTIVE_PROPERTY_KEY, data[0].id);
        setActivePropertyIdState(data[0].id);
      } else if (stillValid) {
        setActivePropertyIdState(saved);
      }
    } catch {
      // Diam-diam dilewati - owner lama yang belum pernah buka halaman Properti pun
      // tetap bisa pakai PMS seperti biasa (backend default ke properti pertama kalau
      // header tidak dikirim sama sekali, lihat get_active_property di core.py).
    }
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("ph_token");
    if (!token) { setLoading(false); return; }
    api.get("/auth/me").then(async (r) => {
      setUser(r.data);
      await loadProperties(r.data);
    }).catch(() => {
      localStorage.removeItem("ph_token");
    }).finally(() => setLoading(false));
  }, [loadProperties]);

  const login = async (username, password) => {
    const { data } = await api.post("/auth/login", { username, password });
    localStorage.setItem("ph_token", data.token);
    setUser(data.user);
    await loadProperties(data.user);
    return data.user;
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    localStorage.removeItem("ph_token");
    localStorage.removeItem(ACTIVE_PROPERTY_KEY);
    setUser(null);
    setProperties([]);
    setActivePropertyIdState(null);
  };

  const activeProperty = properties.find((p) => p.id === activePropertyId) || null;

  return (
    <AuthCtx.Provider value={{
      user, loading, login, logout, setUser,
      properties, activeProperty, activePropertyId, setActivePropertyId,
    }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
