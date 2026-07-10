import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import {
  LayoutDashboard, BedDouble, ShoppingCart, Users, Boxes,
  Wallet, Sparkles, BarChart3, UserCog, ShieldCheck, LogOut, Hotel, Menu, CalendarCheck, HandCoins, DoorOpen, ListChecks, Mail, RefreshCw, MessageCircle, CreditCard, MessageSquare, Shuffle,
} from "lucide-react";
import { useState } from "react";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/ketersediaan", label: "Ketersediaan", icon: DoorOpen },
  { to: "/reservasi", label: "Reservasi", icon: ListChecks },
  { to: "/otomasi-email", label: "Otomasi Email", icon: Mail },
  { to: "/sinkronisasi-ketersediaan", label: "Sinkronisasi", icon: RefreshCw },
  { to: "/konfigurasi-webhook", label: "Webhook WA", icon: MessageCircle },
  { to: "/pembayaran", label: "Pembayaran", icon: CreditCard },
  { to: "/whatsapp-otomatis", label: "WhatsApp Bot", icon: MessageSquare },
  { to: "/pemetaan-tipe-kamar", label: "Pemetaan Kamar", icon: Shuffle },
  { to: "/rooms", label: "Kamar", icon: BedDouble },
  { to: "/bookings", label: "Booking", icon: CalendarCheck },
  { to: "/kasir", label: "Kasir", icon: ShoppingCart },
  { to: "/service", label: "Service", icon: HandCoins },
  { to: "/tamu", label: "Tamu", icon: Users },
  { to: "/inventory", label: "Inventory", icon: Boxes },
  { to: "/pengeluaran", label: "Pengeluaran", icon: Wallet },
  { to: "/housekeeping", label: "Housekeeping", icon: Sparkles },
  { to: "/laporan", label: "Laporan", icon: BarChart3 },
  { to: "/pengguna", label: "Pengguna", icon: UserCog, ownerOnly: true },
  { to: "/audit", label: "Audit Log", icon: ShieldCheck },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);

  const items = navItems.filter((it) => !it.ownerOnly || user?.role === "owner");

  const doLogout = async () => {
    await logout();
    nav("/login", { replace: true });
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Sidebar (desktop) */}
      <aside className="hidden lg:flex fixed inset-y-0 left-0 w-64 bg-white border-r border-slate-200 flex-col z-30">
        <div className="px-6 py-6 flex items-center gap-3 border-b border-slate-100">
          <div className="w-10 h-10 rounded-xl bg-blue-700 grid place-items-center text-white">
            <Hotel className="w-5 h-5" />
          </div>
          <div>
            <p className="text-[10px] tracking-[0.3em] uppercase text-slate-500">Pelangi</p>
            <h2 className="text-base font-bold leading-tight">Homestay</h2>
          </div>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.exact}
              data-testid={`nav-${it.label.toLowerCase().replace(/ /g, "-")}`}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-3 rounded-xl text-sm font-medium transition-colors ${
                  isActive ? "bg-blue-700 text-white" : "text-slate-600 hover:bg-slate-100"
                }`
              }
            >
              <it.icon className="w-5 h-5" />
              {it.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-full bg-slate-100 grid place-items-center font-bold text-slate-700">
              {(user?.nama || "U")[0]}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold truncate">{user?.nama}</div>
              <div className="text-xs text-slate-500 capitalize">{user?.role}</div>
            </div>
          </div>
          <Button data-testid="logout-btn" onClick={doLogout} variant="outline" className="w-full justify-start gap-2">
            <LogOut className="w-4 h-4" /> Keluar
          </Button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <header className="lg:hidden sticky top-0 z-30 bg-white/90 backdrop-blur border-b border-slate-200">
        <div className="flex items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-lg bg-blue-700 grid place-items-center text-white">
              <Hotel className="w-5 h-5" />
            </div>
            <div>
              <p className="text-[9px] tracking-[0.3em] uppercase text-slate-500 leading-tight">Pelangi</p>
              <h2 className="text-sm font-bold leading-tight">Homestay</h2>
            </div>
          </Link>
          <button data-testid="mobile-menu" onClick={() => setOpen(true)} className="p-2 rounded-lg hover:bg-slate-100">
            <Menu className="w-6 h-6" />
          </button>
        </div>
      </header>

      {/* Mobile drawer */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="relative bg-white w-72 h-full flex flex-col">
            <div className="px-5 py-5 border-b border-slate-100">
              <div className="text-sm font-semibold">{user?.nama}</div>
              <div className="text-xs text-slate-500 capitalize">{user?.role}</div>
            </div>
            <nav className="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
              {items.map((it) => (
                <NavLink
                  key={it.to} to={it.to} end={it.exact} onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-3 rounded-xl text-base font-medium ${
                      isActive ? "bg-blue-700 text-white" : "text-slate-700 hover:bg-slate-100"
                    }`
                  }
                >
                  <it.icon className="w-5 h-5" />
                  {it.label}
                </NavLink>
              ))}
            </nav>
            <div className="p-4 border-t">
              <Button data-testid="logout-btn-mobile" onClick={doLogout} variant="outline" className="w-full justify-start gap-2">
                <LogOut className="w-4 h-4" /> Keluar
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Main */}
      <main className="lg:pl-64 pb-20 lg:pb-0">
        <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
          <Outlet />
        </div>
      </main>

      {/* Bottom nav (mobile) */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-30 bg-white/95 backdrop-blur border-t border-slate-200">
        <div className="grid grid-cols-5">
          {items.slice(0, 5).map((it) => (
            <NavLink
              key={it.to} to={it.to} end={it.exact}
              className={({ isActive }) =>
                `flex flex-col items-center justify-center py-2.5 gap-1 text-[11px] font-medium ${
                  isActive ? "text-blue-700" : "text-slate-500"
                }`
              }
            >
              <it.icon className="w-5 h-5" />
              {it.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
