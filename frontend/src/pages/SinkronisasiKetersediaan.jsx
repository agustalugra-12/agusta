import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { RefreshCw, Wifi, WifiOff, AlertTriangle, CheckCircle2, History, Settings2 } from "lucide-react";
import { fmtDateTime } from "@/lib/apiClient";

const TABS = [
  { value: "status", label: "Status Sinkronisasi", icon: Wifi },
  { value: "riwayat", label: "Riwayat Perubahan Stok", icon: History },
  { value: "pengaturan", label: "Pengaturan", icon: Settings2 },
];

// Data tiruan (stub) — status koneksi tiap saluran penjualan ke Availability Engine.
// Pelangi PMS adalah Single Source of Truth (lihat PRD); saluran lain "menarik" data
// darinya, bukan sebaliknya.
const MOCK_CHANNELS = [
  { id: "pms", nama: "Pelangi PMS", peran: "Sumber Kebenaran Tunggal", status: "connected", last_sync: "2026-07-11T09:58:00" },
  { id: "website", nama: "Website Booking Engine", peran: "Saluran Penjualan", status: "connected", last_sync: "2026-07-11T09:58:00" },
  { id: "gmail", nama: "Email OTA (Gmail)", peran: "Sumber Reservasi OTA", status: "connected", last_sync: "2026-07-11T09:55:00" },
  { id: "whatsapp", nama: "WhatsApp Bot", peran: "Saluran Penjualan", status: "error", last_sync: "2026-07-11T08:10:00" },
];

const STATUS_META = {
  connected: { label: "Tersambung", cls: "bg-emerald-100 text-emerald-800", icon: CheckCircle2, dot: "bg-emerald-500" },
  error: { label: "Gangguan Sinkron", cls: "bg-red-100 text-red-800", icon: AlertTriangle, dot: "bg-red-500" },
  disconnected: { label: "Terputus", cls: "bg-slate-200 text-slate-600", icon: WifiOff, dot: "bg-slate-400" },
};

// Data tiruan (stub) — mengikuti entitas AVAILABILITY_LOGS di PRD (id, pms_room_id,
// stock_change, reason, changed_at), ditambah `sumber` untuk menandai saluran pemicu
// perubahan (relevan di Fase 2 karena banyak saluran menulis ke Availability Engine yang sama).
const MOCK_STOCK_HISTORY = [
  { id: "1", room_nomor: "5", room_tipe: "Standard", stock_change: -1, reason: "Booking baru dari Traveloka", sumber: "Email OTA", changed_at: "2026-07-11T09:55:00" },
  { id: "2", room_nomor: "14", room_tipe: "Cottage", stock_change: -1, reason: "Booking baru dari Website", sumber: "Website", changed_at: "2026-07-11T09:40:00" },
  { id: "3", room_nomor: "5", room_tipe: "Standard", stock_change: 1, reason: "Reservasi dibatalkan tamu", sumber: "WhatsApp Bot", changed_at: "2026-07-11T08:20:00" },
  { id: "4", room_nomor: "2", room_tipe: "Standard", stock_change: -1, reason: "Check-in langsung", sumber: "Pelangi PMS", changed_at: "2026-07-11T07:05:00" },
  { id: "5", room_nomor: "16", room_tipe: "Cottage", stock_change: 1, reason: "Check-out", sumber: "Pelangi PMS", changed_at: "2026-07-10T12:00:00" },
  { id: "6", room_nomor: "9", room_tipe: "Standard", stock_change: -1, reason: "Booking baru dari Agoda", sumber: "Email OTA", changed_at: "2026-07-10T10:30:00" },
];

const SUMBER_BADGE = {
  "Pelangi PMS": "bg-blue-100 text-blue-800",
  "Website": "bg-violet-100 text-violet-800",
  "Email OTA": "bg-amber-100 text-amber-800",
  "WhatsApp Bot": "bg-emerald-100 text-emerald-800",
};

function RiwayatPerubahanStok({ history }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm" data-testid="stock-history-table">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left p-3">Waktu</th>
              <th className="text-left p-3">Kamar</th>
              <th className="text-left p-3">Perubahan</th>
              <th className="text-left p-3">Alasan</th>
              <th className="text-left p-3">Sumber</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.id} data-testid={`stock-history-row-${h.id}`} className="border-t border-slate-100">
                <td className="p-3 text-slate-500">{fmtDateTime(h.changed_at)}</td>
                <td className="p-3 font-medium">{h.room_nomor} <span className="text-slate-400 font-normal">({h.room_tipe})</span></td>
                <td className="p-3">
                  <span className={`inline-flex px-2 py-1 rounded-md text-xs font-bold ${h.stock_change > 0 ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
                    {h.stock_change > 0 ? `+${h.stock_change}` : h.stock_change}
                  </span>
                </td>
                <td className="p-3 text-slate-600">{h.reason}</td>
                <td className="p-3">
                  <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${SUMBER_BADGE[h.sumber] || "bg-slate-100 text-slate-600"}`}>{h.sumber}</span>
                </td>
              </tr>
            ))}
            {history.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-slate-500">Belum ada riwayat perubahan stok</td></tr>
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function TabPlaceholder({ label }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-8 text-center text-slate-500">
        <p className="text-sm">Bagian &ldquo;{label}&rdquo; akan dibangun di task berikutnya.</p>
      </CardContent>
    </Card>
  );
}

const CHECK_INTERVAL_MS = 10000;

// Indikator "live": titik berdenyut + jam berjalan sejak pengecekan terakhir. Jam benar-benar
// berjalan (setInterval per detik) supaya terasa real-time meski siklus cek di baliknya (dari
// StatusSinkronisasi) masih data tiruan.
function LiveIndicator({ lastChecked }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const detik = Math.max(0, Math.round((Date.now() - new Date(lastChecked).getTime()) / 1000));
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-500" data-testid="live-indicator">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
      Live &bull; dicek {detik}d lalu
    </span>
  );
}

function StatusSinkronisasi() {
  const [channels, setChannels] = useState(MOCK_CHANNELS);
  const [syncing, setSyncing] = useState(false);
  const [lastChecked, setLastChecked] = useState(() => new Date().toISOString());

  // Simulasi pemantauan berkala (polling) — mengikuti pola setInterval sederhana yang
  // sudah dipakai Dashboard.jsx, belum WebSocket karena tidak ada infrastrukturnya di backend.
  useEffect(() => {
    const t = setInterval(() => setLastChecked(new Date().toISOString()), CHECK_INTERVAL_MS);
    return () => clearInterval(t);
  }, []);

  const bermasalah = channels.filter((c) => c.status !== "connected");

  const paksaSinkron = () => {
    setSyncing(true);
    // Mock: nanti diganti panggilan nyata ke Availability Engine backend.
    setTimeout(() => {
      const now = new Date().toISOString();
      setChannels((cs) => cs.map((c) => ({ ...c, status: "connected", last_sync: now })));
      setLastChecked(now);
      setSyncing(false);
      toast.success("Sinkronisasi manual selesai — semua saluran tersambung");
    }, 900);
  };

  return (
    <div className="space-y-4">
      <Card className={bermasalah.length ? "border-amber-300 bg-amber-50" : "border-emerald-300 bg-emerald-50"}>
        <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            {bermasalah.length ? <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" /> : <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />}
            <p className={`text-sm font-medium ${bermasalah.length ? "text-amber-800" : "text-emerald-800"}`}>
              {bermasalah.length
                ? `${bermasalah.length} saluran bermasalah — stok bisa tidak akurat sampai disinkron ulang.`
                : "Semua saluran tersinkron dengan Pelangi PMS."}
            </p>
            <LiveIndicator lastChecked={lastChecked} />
          </div>
          <Button data-testid="paksa-sinkron" size="sm" onClick={paksaSinkron} disabled={syncing} className="gap-1.5 bg-blue-700 hover:bg-blue-800 shrink-0">
            <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} /> {syncing ? "Menyinkronkan…" : "Paksa Sinkronisasi"}
          </Button>
        </CardContent>
      </Card>

      <div className="grid sm:grid-cols-2 gap-3" data-testid="channel-status-grid">
        {channels.map((c) => {
          const meta = STATUS_META[c.status];
          const Icon = meta.icon;
          return (
            <Card key={c.id} className="border-slate-200" data-testid={`channel-card-${c.id}`}>
              <CardContent className="p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className={`w-2 h-2 rounded-full ${meta.dot} ${c.status === "connected" ? "animate-pulse" : ""}`} />
                  <div>
                    <div className="font-semibold">{c.nama}</div>
                    <div className="text-xs text-slate-500">{c.peran}</div>
                    <div className="text-xs text-slate-400 mt-0.5">Terakhir sinkron: {fmtDateTime(c.last_sync)}</div>
                  </div>
                </div>
                <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium shrink-0 ${meta.cls}`}>
                  <Icon className="w-3 h-3" /> {meta.label}
                </span>
              </CardContent>
            </Card>
          );
        })}
      </div>
      <p className="text-[11px] text-slate-400">Data tiruan — belum tersambung ke Availability Engine sungguhan.</p>
    </div>
  );
}

export default function SinkronisasiKetersediaan() {
  return (
    <div className="space-y-6" data-testid="sinkronisasi-ketersediaan-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Sinkronisasi Ketersediaan</h1>
        <p className="text-slate-500 mt-1">
          Pusat sinkronisasi stok kamar antara Pelangi PMS dan semua saluran penjualan.
        </p>
      </div>

      <Tabs defaultValue="status">
        <TabsList data-testid="sinkronisasi-tabs">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} data-testid={`tab-${t.value}`} className="gap-1.5">
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="status" className="mt-4">
          <StatusSinkronisasi />
        </TabsContent>
        <TabsContent value="riwayat" className="mt-4">
          <RiwayatPerubahanStok history={MOCK_STOCK_HISTORY} />
        </TabsContent>
        {TABS.filter((t) => !["status", "riwayat"].includes(t.value)).map((t) => (
          <TabsContent key={t.value} value={t.value} className="mt-4">
            <TabPlaceholder label={t.label} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
