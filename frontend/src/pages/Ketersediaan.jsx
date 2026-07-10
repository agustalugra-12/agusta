import { useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  BedDouble, DoorOpen, PieChart, AlertTriangle, RefreshCw,
  ChevronLeft, ChevronRight,
} from "lucide-react";

// Data tiruan (stub) — Fase 1 dikerjakan di atas mock data, backend/sinkronisasi PMS menyusul.
const MOCK_ROOM_TYPES = [
  { tipe: "Standard", total: 12, tersedia: 5 },
  { tipe: "Cottage", total: 8, tersedia: 2 },
];

const MOCK_NOTIFICATIONS = [
  { id: 1, level: "warning", text: "Stok kamar Cottage menipis — hanya 2 kamar tersisa akhir pekan ini." },
  { id: 2, level: "error", text: "Sinkronisasi dengan Pelangi PMS gagal 08:42 — mencoba ulang otomatis." },
];

const monthLabel = (d) => d.toLocaleDateString("id-ID", { month: "long", year: "numeric" });

// Bangkitkan okupansi % tiruan per hari dalam bulan (deterministik dari tanggal, bukan random murni).
function mockOccupancyForMonth(viewDate) {
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const days = [];
  for (let day = 1; day <= daysInMonth; day++) {
    const seed = (day * 37 + month * 11) % 100;
    const occupancy = 30 + (seed % 65); // 30% - 94%
    days.push({ date: new Date(year, month, day), occupancy });
  }
  return days;
}

// Rincian tiruan per tipe kamar untuk satu tanggal, konsisten dengan persentase okupansi hari itu.
function dayDetailFor(date, occupancy) {
  return MOCK_ROOM_TYPES.map((rt) => {
    const terisi = Math.min(rt.total, Math.round((occupancy / 100) * rt.total));
    return { tipe: rt.tipe, total: rt.total, terisi, tersedia: rt.total - terisi };
  });
}

function occupancyColor(pct) {
  if (pct >= 85) return { bg: "#FEE2E2", text: "#B91C1C", ring: "#FCA5A5" };
  if (pct >= 60) return { bg: "#FEF3C7", text: "#B45309", ring: "#FCD34D" };
  return { bg: "#D1FAE5", text: "#047857", ring: "#6EE7B7" };
}

export default function Ketersediaan() {
  const totalKamar = useMemo(() => MOCK_ROOM_TYPES.reduce((s, r) => s + r.total, 0), []);
  const tersedia = useMemo(() => MOCK_ROOM_TYPES.reduce((s, r) => s + r.tersedia, 0), []);
  const terisi = totalKamar - tersedia;
  const okupansiPct = totalKamar ? Math.round((terisi / totalKamar) * 100) : 0;

  return (
    <div className="space-y-6" data-testid="ketersediaan-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Dasbor Ketersediaan</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Ketersediaan Kamar</h1>
        <p className="text-slate-500 mt-1">
          Ringkasan ketersediaan lintas saluran (PMS, OTA, WhatsApp). Data di bawah masih data tiruan sebelum sinkronisasi PMS aktif.
        </p>
      </div>

      {/* Notifikasi Penting */}
      <NotifikasiPenting notifications={MOCK_NOTIFICATIONS} />

      {/* Ringkasan Hari Ini */}
      <RingkasanHariIni tersedia={tersedia} terisi={terisi} okupansiPct={okupansiPct} />

      {/* Status Tipe Kamar */}
      <StatusTipeKamar roomTypes={MOCK_ROOM_TYPES} />

      {/* Kalender Ketersediaan */}
      <KalenderKetersediaan />

      <div className="flex items-center gap-2 text-xs text-slate-400">
        <RefreshCw className="w-3.5 h-3.5" />
        Data tiruan — akan tersinkron otomatis dari Pelangi PMS pada fase Otomasi Email & Sinkronisasi Ketersediaan.
      </div>
    </div>
  );
}

function RingkasanHariIni({ tersedia, terisi, okupansiPct }) {
  const items = [
    { label: "Kamar Tersedia", value: tersedia, icon: DoorOpen, valueClass: "text-emerald-600", iconClass: "bg-emerald-50 text-emerald-600", testid: "ringkasan-tersedia" },
    { label: "Kamar Terisi", value: terisi, icon: BedDouble, valueClass: "text-blue-600", iconClass: "bg-blue-50 text-blue-600", testid: "ringkasan-terisi" },
    { label: "Okupansi Hari Ini", value: `${okupansiPct}%`, icon: PieChart, valueClass: "text-violet-600", iconClass: "bg-violet-50 text-violet-600", testid: "ringkasan-okupansi" },
  ];
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4" data-testid="ringkasan-hari-ini">
      {items.map((it) => (
        <Card key={it.label} className="border-slate-200">
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500">{it.label}</div>
                <div className={`text-3xl font-extrabold mt-1 ${it.valueClass}`} data-testid={it.testid}>{it.value}</div>
              </div>
              <div className={`w-9 h-9 rounded-lg grid place-items-center ${it.iconClass}`}>
                <it.icon className="w-5 h-5" />
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function NotifikasiPenting({ notifications }) {
  if (!notifications.length) return null;
  return (
    <div className="space-y-2" data-testid="ketersediaan-notifikasi">
      {notifications.map((n) => (
        <div
          key={n.id}
          data-testid={`notifikasi-${n.id}`}
          className={`rounded-xl border p-4 flex items-start gap-3 ${
            n.level === "error" ? "bg-red-50 border-red-200" : "bg-amber-50 border-amber-200"
          }`}
        >
          <AlertTriangle className={`w-5 h-5 mt-0.5 ${n.level === "error" ? "text-red-600" : "text-amber-600"}`} />
          <div className={`text-sm font-medium ${n.level === "error" ? "text-red-800" : "text-amber-800"}`}>
            {n.text}
          </div>
        </div>
      ))}
    </div>
  );
}

function StatusTipeKamar({ roomTypes }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-6">
        <h2 className="text-xl font-bold mb-4">Status Tipe Kamar</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" data-testid="status-tipe-kamar">
          {roomTypes.map((rt) => {
            const pct = rt.total ? Math.round((rt.tersedia / rt.total) * 100) : 0;
            return (
              <div key={rt.tipe} className="rounded-xl border border-slate-200 p-4" data-testid={`status-tipe-${rt.tipe.toLowerCase()}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold">{rt.tipe}</span>
                  <span className="text-xs text-slate-500">{rt.tersedia} / {rt.total} tersedia</span>
                </div>
                <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function KalenderKetersediaan() {
  const [viewDate, setViewDate] = useState(() => {
    const d = new Date();
    d.setDate(1);
    return d;
  });
  const [selectedDay, setSelectedDay] = useState(null); // { date, occupancy }

  const days = useMemo(() => mockOccupancyForMonth(viewDate), [viewDate]);
  const leadingBlanks = (new Date(viewDate.getFullYear(), viewDate.getMonth(), 1).getDay() + 6) % 7; // Senin=0
  const todayStr = new Date().toDateString();

  const goMonth = (delta) => {
    setViewDate((d) => new Date(d.getFullYear(), d.getMonth() + delta, 1));
  };

  const detailRows = selectedDay ? dayDetailFor(selectedDay.date, selectedDay.occupancy) : [];

  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold">Kalender Ketersediaan</h2>
          <div className="flex items-center gap-2">
            <Button data-testid="kalender-prev" size="icon" variant="outline" className="h-8 w-8" onClick={() => goMonth(-1)}>
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="text-sm font-medium w-36 text-center capitalize" data-testid="kalender-label">{monthLabel(viewDate)}</span>
            <Button data-testid="kalender-next" size="icon" variant="outline" className="h-8 w-8" onClick={() => goMonth(1)}>
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-7 gap-1.5 text-center text-[11px] font-semibold text-slate-500 mb-1.5">
          {["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"].map((d) => <div key={d}>{d}</div>)}
        </div>
        <div className="grid grid-cols-7 gap-1.5" data-testid="kalender-ketersediaan">
          {Array.from({ length: leadingBlanks }).map((_, i) => <div key={`b${i}`} />)}
          {days.map(({ date, occupancy }) => {
            const c = occupancyColor(occupancy);
            const isToday = date.toDateString() === todayStr;
            return (
              <button
                type="button"
                key={date.toISOString()}
                data-testid={`kalender-hari-${date.getDate()}`}
                onClick={() => setSelectedDay({ date, occupancy })}
                className="aspect-square rounded-lg flex flex-col items-center justify-center gap-0.5 cursor-pointer hover:opacity-80 transition-opacity"
                style={{ background: c.bg, color: c.text, boxShadow: isToday ? `0 0 0 2px ${c.ring}` : undefined }}
              >
                <span className="text-xs font-bold">{date.getDate()}</span>
                <span className="text-[9px] font-medium opacity-80">{occupancy}%</span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-4 mt-4 text-xs text-slate-500">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm" style={{ background: "#D1FAE5" }} /> Rendah (&lt;60%)</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm" style={{ background: "#FEF3C7" }} /> Sedang (60–84%)</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm" style={{ background: "#FEE2E2" }} /> Tinggi (&ge;85%)</span>
        </div>
      </CardContent>

      <Dialog open={!!selectedDay} onOpenChange={(o) => !o && setSelectedDay(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle data-testid="detail-hari-title">
              Ketersediaan {selectedDay?.date.toLocaleDateString("id-ID", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm" data-testid="detail-hari-body">
            <div className="flex items-center justify-between rounded-lg bg-slate-50 border border-slate-200 px-3 py-2">
              <span className="text-slate-500">Okupansi hari ini</span>
              <span className="font-bold">{selectedDay?.occupancy}%</span>
            </div>
            {detailRows.map((r) => (
              <div key={r.tipe} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold">{r.tipe}</span>
                  <span className="text-xs text-slate-500">{r.tersedia} / {r.total} tersedia</span>
                </div>
                <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full bg-emerald-500" style={{ width: `${r.total ? (r.tersedia / r.total) * 100 : 0}%` }} />
                </div>
              </div>
            ))}
            <p className="text-[11px] text-slate-400">Data tiruan — rincian per kamar akan tersedia setelah sinkronisasi Pelangi PMS aktif.</p>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
