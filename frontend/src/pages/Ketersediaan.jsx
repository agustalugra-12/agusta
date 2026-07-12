import { useEffect, useMemo, useState } from "react";
import api from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  BedDouble, DoorOpen, PieChart, AlertTriangle, RefreshCw,
  ChevronLeft, ChevronRight,
} from "lucide-react";

const LIVE_POLL_MS = 10000;

const dayLabel = (d) => d.toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "short" });
const rangeLabel = (start, end) => `${start.toLocaleDateString("id-ID", { day: "2-digit", month: "long" })} – ${end.toLocaleDateString("id-ID", { day: "2-digit", month: "long", year: "numeric" })}`;
const toDateKey = (d) => d.toISOString().slice(0, 10);

function occupancyColor(pct) {
  if (pct >= 85) return { bg: "#FEE2E2", text: "#B91C1C", ring: "#FCA5A5" };
  if (pct >= 60) return { bg: "#FEF3C7", text: "#B45309", ring: "#FCD34D" };
  return { bg: "#D1FAE5", text: "#047857", ring: "#6EE7B7" };
}

export default function Ketersediaan() {
  const [live, setLive] = useState(null);

  useEffect(() => {
    let stop = false;
    const load = () => api.get("/ketersediaan/live").then((r) => { if (!stop) setLive(r.data); }).catch(() => {});
    load();
    const t = setInterval(load, LIVE_POLL_MS);
    return () => { stop = true; clearInterval(t); };
  }, []);

  const ringkasan = live?.ringkasan ?? { tersedia: 0, terisi: 0, okupansi_pct: 0 };
  const statusTipe = live?.status_tipe_kamar ?? [];
  const notifikasi = live?.notifikasi ?? [];

  return (
    <div className="space-y-6" data-testid="ketersediaan-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Dasbor Ketersediaan</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Ketersediaan Kamar</h1>
        <p className="text-slate-500 mt-1">
          Ringkasan ketersediaan kamar Pelangi PMS, diperbarui otomatis tiap {LIVE_POLL_MS / 1000} detik.
        </p>
      </div>

      <NotifikasiPenting notifications={notifikasi} />

      <RingkasanHariIni tersedia={ringkasan.tersedia} terisi={ringkasan.terisi} okupansiPct={ringkasan.okupansi_pct} />

      <StatusTipeKamar roomTypes={statusTipe} />

      <KalenderKetersediaan />

      <div className="flex items-center gap-2 text-xs text-slate-400">
        <RefreshCw className="w-3.5 h-3.5" />
        Data langsung dari Pelangi PMS.
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
      {notifications.map((n, i) => (
        <div
          key={i}
          data-testid={`notifikasi-${i}`}
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

// Cache sederhana per bulan supaya geser minggu yang masih dalam bulan sama tidak fetch ulang.
function KalenderKetersediaan() {
  const [weekStart, setWeekStart] = useState(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    const dow = (d.getDay() + 6) % 7; // Senin=0
    d.setDate(d.getDate() - dow);
    return d;
  });
  const [monthCache, setMonthCache] = useState({}); // key "YYYY-M" -> { tanggal: {terisi,tersedia,okupansi_pct} }
  const [selectedDay, setSelectedDay] = useState(null); // { date, occupancy }
  const [dayDetail, setDayDetail] = useState(null);

  const weekDays = useMemo(() => Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + i);
    return d;
  }), [weekStart]);

  const neededMonths = useMemo(() => {
    const set = new Set();
    weekDays.forEach((d) => set.add(`${d.getFullYear()}-${d.getMonth() + 1}`));
    return Array.from(set);
  }, [weekDays]);

  useEffect(() => {
    neededMonths.forEach((key) => {
      if (monthCache[key]) return;
      const [year, month] = key.split("-").map(Number);
      api.get("/ketersediaan/kalender-bulanan", { params: { year, month } }).then((r) => {
        const byDate = {};
        r.data.days.forEach((d) => { byDate[d.tanggal] = d; });
        setMonthCache((prev) => ({ ...prev, [key]: byDate }));
      }).catch(() => {});
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [neededMonths]);

  const goWeek = (delta) => {
    setWeekStart((d) => {
      const n = new Date(d);
      n.setDate(n.getDate() + delta * 7);
      return n;
    });
  };

  const occupancyFor = (date) => {
    const key = `${date.getFullYear()}-${date.getMonth() + 1}`;
    const entry = monthCache[key]?.[toDateKey(date)];
    return entry?.okupansi_pct ?? null;
  };

  const openDay = (date) => {
    const occupancy = occupancyFor(date);
    setSelectedDay({ date, occupancy });
    setDayDetail(null);
    api.get("/ketersediaan/hari", { params: { tanggal: toDateKey(date) } }).then((r) => setDayDetail(r.data)).catch(() => {});
  };

  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold">Kalender Ketersediaan</h2>
          <div className="flex items-center gap-2">
            <Button data-testid="kalender-prev" size="icon" variant="outline" className="h-8 w-8" onClick={() => goWeek(-1)}>
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="text-sm font-medium text-center" data-testid="kalender-label">{rangeLabel(weekDays[0], weekDays[6])}</span>
            <Button data-testid="kalender-next" size="icon" variant="outline" className="h-8 w-8" onClick={() => goWeek(1)}>
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-7 gap-1.5" data-testid="kalender-ketersediaan">
          {weekDays.map((date) => {
            const occupancy = occupancyFor(date);
            const loaded = occupancy !== null;
            const c = loaded ? occupancyColor(occupancy) : { bg: "#F1F5F9", text: "#94A3B8", ring: "#CBD5E1" };
            const isToday = toDateKey(date) === toDateKey(new Date());
            return (
              <button
                type="button"
                key={toDateKey(date)}
                data-testid={`kalender-hari-${date.getDate()}`}
                onClick={() => openDay(date)}
                disabled={!loaded}
                className="aspect-square rounded-lg flex flex-col items-center justify-center gap-0.5 cursor-pointer hover:opacity-80 transition-opacity disabled:cursor-wait"
                style={{ background: c.bg, color: c.text, boxShadow: isToday ? `0 0 0 2px ${c.ring}` : undefined }}
              >
                <span className="text-[10px] font-medium opacity-80 capitalize">{dayLabel(date).split(" ")[0]}</span>
                <span className="text-sm font-bold">{date.getDate()}</span>
                <span className="text-[9px] font-medium opacity-80">{loaded ? `${occupancy}%` : "…"}</span>
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

      <Dialog open={!!selectedDay} onOpenChange={(o) => { if (!o) { setSelectedDay(null); setDayDetail(null); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle data-testid="detail-hari-title">
              Ketersediaan {selectedDay?.date.toLocaleDateString("id-ID", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm" data-testid="detail-hari-body">
            <div className="flex items-center justify-between rounded-lg bg-slate-50 border border-slate-200 px-3 py-2">
              <span className="text-slate-500">Okupansi hari ini</span>
              <span className="font-bold">{dayDetail ? `${dayDetail.okupansi_pct}%` : "Memuat…"}</span>
            </div>
            {dayDetail?.by_tipe.map((r) => (
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
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
