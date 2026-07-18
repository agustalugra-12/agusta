import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Ketersediaan from "@/pages/Ketersediaan";
import Rooms from "@/pages/Rooms";
import CheckOut from "@/pages/CheckOut";
import Kasir from "@/pages/Kasir";
import Inventory from "@/pages/Inventory";
import Pengeluaran from "@/pages/Pengeluaran";
import Housekeeping from "@/pages/Housekeeping";
import Laporan from "@/pages/Laporan";
import Service from "@/pages/Service";
import Pengguna from "@/pages/Pengguna";
import Profil from "@/pages/Profil";
import KalenderHarga from "@/pages/KalenderHarga";
import Audit from "@/pages/Audit";
import DaftarReservasi from "@/pages/DaftarReservasi";
import OtomasiEmail from "@/pages/OtomasiEmail";
import SinkronisasiKetersediaan from "@/pages/SinkronisasiKetersediaan";
import Pembayaran from "@/pages/Pembayaran";
import PesanWhatsAppOtomatis from "@/pages/PesanWhatsAppOtomatis";
import PemetaanTipeKamar from "@/pages/PemetaanTipeKamar";
import PermintaanKhususExtraBed from "@/pages/PermintaanKhususExtraBed";
import PengirimanVoucherOtomatis from "@/pages/PengirimanVoucherOtomatis";
import RekomendasiCheckinDayUse from "@/pages/RekomendasiCheckinDayUse";
import Komplain from "@/pages/Komplain";
import Maintenance from "@/pages/Maintenance";
import ServiceRequests from "@/pages/ServiceRequests";
import BookingRequests from "@/pages/BookingRequests";
import JadwalKerja from "@/pages/JadwalKerja";
import BusinessRules from "@/pages/BusinessRules";
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
      <Route path="/register" element={<Register />} />
      <Route path="/book" element={<PublicBook />} />
      <Route path="/book/sukses" element={<PublicBook successView />} />
      <Route path="/book/sukses/:bookingId" element={<PublicBook successView />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/ketersediaan" element={<Ketersediaan />} />
        <Route path="/rooms" element={<Rooms />} />
        <Route path="/checkout/:checkinId" element={<CheckOut />} />
        <Route path="/kasir" element={<Kasir />} />
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/pengeluaran" element={<Pengeluaran />} />
        <Route path="/service" element={<Service />} />
        <Route path="/housekeeping" element={<Housekeeping />} />
        <Route path="/laporan" element={<Laporan />} />
        <Route path="/pengguna" element={<Protected ownerOnly><Pengguna /></Protected>} />
        <Route path="/profil" element={<Profil />} />
        <Route path="/kalender-harga" element={<KalenderHarga />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/reservasi" element={<DaftarReservasi />} />
        <Route path="/booking-requests" element={<BookingRequests />} />
        <Route path="/otomasi-email" element={<OtomasiEmail />} />
        <Route path="/sinkronisasi-ketersediaan" element={<SinkronisasiKetersediaan />} />
        <Route path="/pembayaran" element={<Pembayaran />} />
        <Route path="/whatsapp-otomatis" element={<PesanWhatsAppOtomatis />} />
        <Route path="/pemetaan-tipe-kamar" element={<PemetaanTipeKamar />} />
        <Route path="/extra-bed" element={<PermintaanKhususExtraBed />} />
        <Route path="/pengiriman-voucher" element={<PengirimanVoucherOtomatis />} />
        <Route path="/rekomendasi-checkin" element={<RekomendasiCheckinDayUse />} />
        <Route path="/komplain" element={<Komplain />} />
        <Route path="/maintenance" element={<Maintenance />} />
        <Route path="/service-requests" element={<ServiceRequests />} />
        <Route path="/jadwal-kerja" element={<JadwalKerja />} />
        <Route path="/business-rules" element={<Protected ownerOnly><BusinessRules /></Protected>} />
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
