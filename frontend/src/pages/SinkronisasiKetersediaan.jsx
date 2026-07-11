import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { RefreshCw, Wifi, WifiOff, AlertTriangle, CheckCircle2, History, Settings2, X, ArrowUp, ArrowDown, Save } from "lucide-react";
import api, { fmtDateTime } from "@/lib/apiClient";

const ROOM_TYPE_FILTER_OPTIONS = ["Semua", "Standard", "Cottage"];
const FREKUENSI_OPTIONS = [
  { value: 1, label: "Setiap 1 menit (paling akurat, beban server lebih tinggi)" },
  { value: 5, label: "Setiap 5 menit (disarankan)" },
  { value: 15, label: "Setiap 15 menit" },
  { value: 30, label: "Setiap 30 menit" },
];

const TABS = [
  { value: "status", label: "Status Sinkronisasi", icon: Wifi },
  { value: "riwayat", label: "Riwayat Perubahan Stok", icon: History },
  { value: "pengaturan", label: "Pengaturan", icon: Settings2 },
];

const STATUS_META = {
  connected: { label: "Tersambung", cls: "bg-emerald-100 text-emerald-800", icon: CheckCircle2, dot: "bg-emerald-500" },
  error: { label: "Gangguan Sinkron", cls: "bg-red-100 text-red-800", icon: AlertTriangle, dot: "bg-red-500" },
  disconnected: { label: "Terputus", cls: "bg-slate-200 text-slate-600", icon: WifiOff, dot: "bg-slate-400" },
};

const SUMBER_BADGE = {
  "Pelangi PMS": "bg-blue-100 text-blue-800",
  "Website": "bg-violet-100 text-violet-800",
  "Email OTA": "bg-amber-100 text-amber-800",
  "WhatsApp Bot": "bg-emerald-100 text-emerald-800",
};

function RiwayatPerubahanStok() {
  const [dari, setDari] = useState("");
  const [sampai, setSampai] = useState("");
  const [tipeKamar, setTipeKamar] = useState("Semua");
  const [filtered, setFiltered] = useState([]);

  useEffect(() => {
    const params = {};
    if (dari) params.dari = dari;
    if (sampai) params.sampai = sampai;
    if (tipeKamar !== "Semua") params.tipe_kamar = tipeKamar;
    api.get("/sinkronisasi-ketersediaan/riwayat-stok", { params })
      .then((r) => setFiltered(r.data))
      .catch(() => setFiltered([]));
  }, [dari, sampai, tipeKamar]);

  const resetFilters = () => { setDari(""); setSampai(""); setTipeKamar("Semua"); };
  const hasActiveFilter = dari || sampai || tipeKamar !== "Semua";

  return (
    <div className="space-y-3">
      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="w-full sm:w-44">
            <Label htmlFor="riwayat-dari">Dari Tanggal</Label>
            <Input id="riwayat-dari" data-testid="riwayat-filter-dari" type="date" value={dari} onChange={(e) => setDari(e.target.value)} className="mt-1.5" />
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="riwayat-sampai">Sampai Tanggal</Label>
            <Input id="riwayat-sampai" data-testid="riwayat-filter-sampai" type="date" value={sampai} onChange={(e) => setSampai(e.target.value)} className="mt-1.5" />
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="riwayat-tipe">Tipe Kamar</Label>
            <select
              id="riwayat-tipe"
              data-testid="riwayat-filter-tipe"
              value={tipeKamar}
              onChange={(e) => setTipeKamar(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {ROOM_TYPE_FILTER_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {hasActiveFilter && (
            <Button data-testid="riwayat-reset-filter" variant="ghost" size="sm" onClick={resetFilters} className="gap-1.5">
              <X className="w-3.5 h-3.5" /> Reset
            </Button>
          )}
        </CardContent>
      </Card>
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
            {filtered.map((h) => (
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
            {filtered.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-slate-500">Tidak ada riwayat yang cocok dengan filter</td></tr>
            )}
          </tbody>
        </table>
      </CardContent>
      </Card>
    </div>
  );
}

function PengaturanSinkronisasi() {
  const [frekuensi, setFrekuensi] = useState(5);
  const [prioritas, setPrioritas] = useState(["Pelangi PMS", "Email OTA", "Website", "WhatsApp Bot"]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/sinkronisasi-ketersediaan/pengaturan").then((r) => {
      setFrekuensi(r.data.frekuensi_menit);
      setPrioritas(r.data.prioritas);
    }).catch(() => {});
  }, []);

  const pindah = (idx, arah) => {
    const target = idx + arah;
    if (target < 1 || target >= prioritas.length) return; // index 0 (Pelangi PMS) terkunci
    setPrioritas((p) => {
      const next = [...p];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  const simpan = async () => {
    setSaving(true);
    try {
      await api.put("/sinkronisasi-ketersediaan/pengaturan", { frekuensi_menit: frekuensi, prioritas });
      toast.success(`Pengaturan disimpan: sinkron tiap ${frekuensi} menit, prioritas ${prioritas.join(" > ")}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan pengaturan");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Frekuensi Sinkronisasi</h3>
          <p className="text-xs text-slate-500 -mt-2">Seberapa sering Availability Engine mengecek ulang stok ke semua saluran.</p>
          <div className="space-y-2">
            {FREKUENSI_OPTIONS.map((f) => (
              <label key={f.value} className="flex items-center gap-2.5 text-sm cursor-pointer">
                <input
                  type="radio"
                  name="frekuensi"
                  data-testid={`frekuensi-${f.value}`}
                  checked={frekuensi === f.value}
                  onChange={() => setFrekuensi(f.value)}
                  className="accent-blue-700"
                />
                {f.label}
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Prioritas Saluran (saat data bentrok)</h3>
          <p className="text-xs text-slate-500 -mt-2">
            Jika dua saluran melaporkan perubahan stok kamar yang sama nyaris bersamaan, saluran berperingkat lebih atas yang dipakai.
          </p>
          <div className="border border-slate-200 rounded-lg divide-y divide-slate-100" data-testid="prioritas-list">
            {prioritas.map((nama, idx) => (
              <div key={nama} className="p-2.5 flex items-center justify-between gap-3" data-testid={`prioritas-item-${idx}`}>
                <div className="flex items-center gap-2.5">
                  <span className="w-6 h-6 rounded-full bg-slate-100 text-slate-600 text-xs font-bold grid place-items-center">{idx + 1}</span>
                  <span className="text-sm font-medium">{nama}</span>
                  {idx === 0 && <span className="text-[10px] uppercase font-bold text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded">Terkunci</span>}
                </div>
                {idx > 0 && (
                  <div className="flex gap-1">
                    <Button data-testid={`prioritas-naik-${idx}`} variant="ghost" size="icon" onClick={() => pindah(idx, -1)} disabled={idx === 1}>
                      <ArrowUp className="w-3.5 h-3.5" />
                    </Button>
                    <Button data-testid={`prioritas-turun-${idx}`} variant="ghost" size="icon" onClick={() => pindah(idx, 1)} disabled={idx === prioritas.length - 1}>
                      <ArrowDown className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Button data-testid="simpan-pengaturan" onClick={simpan} disabled={saving} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
        <Save className="w-3.5 h-3.5" /> {saving ? "Menyimpan…" : "Simpan Pengaturan"}
      </Button>
    </div>
  );
}

const CHECK_INTERVAL_MS = 10000;

// Indikator "live": titik berdenyut + jam berjalan sejak pengecekan terakhir di klien
// (jam ini murni UI, dihitung ulang tiap detik; data statusnya sendiri sungguhan dari server).
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
  const [channels, setChannels] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [lastChecked, setLastChecked] = useState(() => new Date().toISOString());

  const load = () => {
    api.get("/sinkronisasi-ketersediaan/status").then((r) => {
      setChannels(r.data.channels);
      setLastChecked(new Date().toISOString());
    }).catch(() => {});
  };

  useEffect(() => {
    load();
    // Polling berkala — pencerminan status dari server (server sendiri juga auto-refresh
    // di background tiap `frekuensi_menit`, ini cuma supaya UI ikut kebaruan tanpa reload).
    const t = setInterval(load, CHECK_INTERVAL_MS);
    return () => clearInterval(t);
  }, []);

  const bermasalah = channels.filter((c) => c.status !== "connected");

  const paksaSinkron = async () => {
    setSyncing(true);
    try {
      const { data } = await api.post("/sinkronisasi-ketersediaan/paksa-sinkron");
      setChannels(data.channels);
      setLastChecked(new Date().toISOString());
      const masihBermasalah = data.channels.filter((c) => c.status !== "connected");
      if (masihBermasalah.length) {
        toast.warning(`Sinkronisasi selesai — ${masihBermasalah.length} saluran masih belum tersambung`);
      } else {
        toast.success("Sinkronisasi manual selesai — semua saluran tersambung");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal memaksa sinkronisasi");
    } finally {
      setSyncing(false);
    }
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
            <Card key={c.key} className="border-slate-200" data-testid={`channel-card-${c.key}`}>
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
          <RiwayatPerubahanStok />
        </TabsContent>
        <TabsContent value="pengaturan" className="mt-4">
          <PengaturanSinkronisasi />
        </TabsContent>
      </Tabs>
    </div>
  );
}
