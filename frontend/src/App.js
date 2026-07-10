import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Login from "@/pages/Login";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Ketersediaan from "@/pages/Ketersediaan";
import Rooms from "@/pages/Rooms";
import CheckIn from "@/pages/CheckIn";
import CheckOut from "@/pages/CheckOut";
import Kasir from "@/pages/Kasir";
import Tamu from "@/pages/Tamu";
import Inventory from "@/pages/Inventory";
import Pengeluaran from "@/pages/Pengeluaran";
import Housekeeping from "@/pages/Housekeeping";
import Laporan from "@/pages/Laporan";
import Service from "@/pages/Service";
import Pengguna from "@/pages/Pengguna";
import Audit from "@/pages/Audit";
import Bookings from "@/pages/Bookings";
import DaftarReservasi from "@/pages/DaftarReservasi";
import OtomasiEmail from "@/pages/OtomasiEmail";
import SinkronisasiKetersediaan from "@/pages/SinkronisasiKetersediaan";
import KonfigurasiWebhook from "@/pages/KonfigurasiWebhook";
import PublicBook from "@/pages/PublicBook";
import "@/App.css";

function Protected({ children, ownerOnly = false }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="min-h-screen grid place-items-center text-slate-500">Memuat…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  if (ownerOnly && user.role !== "owner") return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/book" element={<PublicBook />} />
      <Route path="/book/sukses/:bookingId" element={<PublicBook successView />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/ketersediaan" element={<Ketersediaan />} />
        <Route path="/rooms" element={<Rooms />} />
        <Route path="/checkin/:roomId" element={<CheckIn />} />
        <Route path="/checkout/:checkinId" element={<CheckOut />} />
        <Route path="/kasir" element={<Kasir />} />
        <Route path="/tamu" element={<Tamu />} />
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/pengeluaran" element={<Pengeluaran />} />
        <Route path="/service" element={<Service />} />
        <Route path="/housekeeping" element={<Housekeeping />} />
        <Route path="/laporan" element={<Laporan />} />
        <Route path="/pengguna" element={<Protected ownerOnly><Pengguna /></Protected>} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/bookings" element={<Bookings />} />
        <Route path="/reservasi" element={<DaftarReservasi />} />
        <Route path="/otomasi-email" element={<OtomasiEmail />} />
        <Route path="/sinkronisasi-ketersediaan" element={<SinkronisasiKetersediaan />} />
        <Route path="/konfigurasi-webhook" element={<KonfigurasiWebhook />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function NetworkBanner() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);
  if (online) return null;
  return (
    <div data-testid="offline-banner" className="fixed top-0 inset-x-0 z-[60] bg-amber-500 text-white text-center text-sm py-2 font-medium">
      Mode Offline — perubahan akan disinkron ketika koneksi kembali.
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <NetworkBanner />
        <AppRoutes />
        <Toaster position="top-right" richColors />
      </BrowserRouter>
    </AuthProvider>
  );
}
