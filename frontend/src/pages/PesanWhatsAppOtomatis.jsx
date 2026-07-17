import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import {
  MessageSquare, Send, CheckCircle2, Bot, Inbox, Activity, Settings2, ExternalLink, Save, Search, XCircle,
  Timer, AlertTriangle, History, Wifi, WifiOff, BarChart3, BedDouble, Tag, ClipboardList, Clock, CheckCircle,
  MessageCircle, Eye, EyeOff, Zap, Loader2, Undo2, AlertCircle, Copy, Check, RefreshCw,
} from "lucide-react";
import api, { fmtDateTime, API_BASE } from "@/lib/apiClient";

const TABS = [
  { value: "ringkasan", label: "Ringkasan", icon: Activity },
  { value: "log", label: "Log Percakapan", icon: Inbox },
  { value: "pemantauan", label: "Pemantauan Status", icon: Send },
  { value: "sinkronisasi", label: "Sinkronisasi Data", icon: BarChart3 },
  { value: "pengaturan", label: "Pengaturan", icon: Settings2 },
  { value: "kredensial", label: "Kredensial", icon: MessageCircle },
];

function Ringkasan({ onGotoTab }) {
  const [stats, setStats] = useState({ pesan_masuk_hari_ini: 0, pesan_terkirim_hari_ini: 0, tingkat_sukses_kirim: 100, reservasi_via_wa_hari_ini: 0 });
  const [aktivitas, setAktivitas] = useState([]);

  useEffect(() => {
    api.get("/pesan-whatsapp/stats").then((r) => setStats(r.data)).catch(() => {});
    api.get("/pesan-whatsapp/percakapan").then((r) => setAktivitas(r.data.slice(0, 5))).catch(() => {});
  }, []);

  const cards = [
    { label: "Pesan Masuk Hari Ini", value: stats.pesan_masuk_hari_ini, icon: Inbox, cls: "bg-blue-50 text-blue-600" },
    { label: "Pesan Terkirim Hari Ini", value: stats.pesan_terkirim_hari_ini, icon: Send, cls: "bg-violet-50 text-violet-600" },
    { label: "Tingkat Sukses Kirim", value: `${stats.tingkat_sukses_kirim}%`, icon: CheckCircle2, cls: "bg-emerald-50 text-emerald-600" },
    { label: "Reservasi via WhatsApp", value: stats.reservasi_via_wa_hari_ini, icon: Bot, cls: "bg-amber-50 text-amber-600" },
  ];
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3" data-testid="whatsapp-stats-grid">
        {cards.map((c) => (
          <Card key={c.label} className="border-slate-200">
            <CardContent className="p-4 flex items-center gap-3">
              <div className={`w-10 h-10 rounded-xl grid place-items-center shrink-0 ${c.cls}`}>
                <c.icon className="w-5 h-5" />
              </div>
              <div>
                <div className="text-xl font-extrabold">{c.value}</div>
                <div className="text-xs text-slate-500">{c.label}</div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-0 divide-y divide-slate-100">
          <div className="p-4 border-b border-slate-100">
            <h3 className="text-sm font-semibold text-slate-700">Aktivitas Terbaru</h3>
          </div>
          {aktivitas.map((a) => (
            <div key={a.id} className="p-3.5 flex items-start gap-3" data-testid={`whatsapp-aktivitas-${a.id}`}>
              <div className="w-8 h-8 rounded-full bg-emerald-50 text-emerald-600 grid place-items-center shrink-0">
                <MessageSquare className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{a.nama}</div>
                <div className="text-xs text-slate-500 truncate">{a.pesan_masuk}</div>
              </div>
              <div className="text-xs text-slate-400 shrink-0">{fmtDateTime(a.waktu)}</div>
            </div>
          ))}
          {aktivitas.length === 0 && (
            <div className="p-8 text-center text-slate-500 text-sm">
              Belum ada aktivitas — hubungkan webhook di tab{" "}
              <button type="button" className="text-blue-700 hover:underline" onClick={() => onGotoTab("kredensial")}>Kredensial</button>.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}


const FREKUENSI_WA_OPTIONS = [
  { value: "realtime", label: "Real-time (setiap ada perubahan)" },
  { value: 5, label: "Setiap 5 menit" },
  { value: 15, label: "Setiap 15 menit" },
];

const DATA_SYNC_OPTIONS = [
  { key: "ketersediaan", label: "Ketersediaan Kamar", desc: "Stok kamar tersedia per tipe, dari Availability Engine." },
  { key: "harga", label: "Harga & Tarif", desc: "Tarif kamar terkini dari Pelangi PMS." },
  { key: "status_booking", label: "Status Booking", desc: "Update status reservasi (confirmed/cancelled) ke bot." },
  { key: "reservasi_baru", label: "Reservasi Baru dari Email OTA", desc: "Reservasi hasil parsing AI Email Parser." },
];

// Tab "Pengaturan" fokus pada data apa saja yang disinkronkan dari Pelangi PMS ke bot
// WhatsApp + frekuensinya. Kredensial/endpoint provider WA sekarang ada di tab
// "Kredensial" (dulu halaman terpisah "Konfigurasi Webhook") — digabung ke sini
// supaya tidak ada lagi menu sidebar terpisah untuk topik yang sama.
function PengaturanWhatsApp({ onGotoTab }) {
  const [dataSync, setDataSync] = useState({ ketersediaan: true, harga: true, status_booking: true, reservasi_baru: false });
  const [frekuensi, setFrekuensi] = useState("realtime");
  const [webhookAktif, setWebhookAktif] = useState(false);

  useEffect(() => {
    api.get("/pesan-whatsapp/pengaturan").then((r) => {
      setDataSync(r.data.data_sync);
      setFrekuensi(r.data.frekuensi);
    }).catch(() => {});
    api.get("/konfigurasi-webhook").then((r) => setWebhookAktif(!!r.data.aktif)).catch(() => {});
  }, []);

  const toggleSync = (key) => setDataSync((d) => ({ ...d, [key]: !d[key] }));
  const simpan = async () => {
    try {
      await api.put("/pesan-whatsapp/pengaturan", { data_sync: dataSync, frekuensi });
      toast.success("Pengaturan sinkronisasi WhatsApp Bot disimpan");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan pengaturan");
    }
  };

  return (
    <div className="space-y-4">
      <Card className={webhookAktif ? "border-emerald-200" : "border-slate-200"}>
        <CardContent className="p-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl grid place-items-center shrink-0 ${webhookAktif ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
              <CheckCircle2 className="w-5 h-5" />
            </div>
            <div>
              <div className="font-semibold text-sm">{webhookAktif ? "Webhook Terhubung" : "Webhook Belum Dikonfigurasi"}</div>
              <div className="text-xs text-slate-500">Kredensial &amp; endpoint diatur di tab Kredensial.</div>
            </div>
          </div>
          <Button variant="outline" size="sm" className="gap-1.5 shrink-0" data-testid="wa-buka-konfigurasi-webhook" onClick={() => onGotoTab("kredensial")}>
            Kelola Webhook <ExternalLink className="w-3.5 h-3.5" />
          </Button>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Data yang Disinkronkan ke Bot</h3>
          <div className="space-y-2.5">
            {DATA_SYNC_OPTIONS.map((o) => (
              <label key={o.key} className="flex items-start gap-2.5 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  data-testid={`wa-sync-${o.key}`}
                  checked={dataSync[o.key]}
                  onChange={() => toggleSync(o.key)}
                  className="mt-0.5 accent-blue-700"
                />
                <span>
                  <span className="font-medium">{o.label}</span>
                  <span className="block text-xs text-slate-500">{o.desc}</span>
                </span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Frekuensi Sinkronisasi ke Bot</h3>
          <div className="space-y-2">
            {FREKUENSI_WA_OPTIONS.map((f) => (
              <label key={f.value} className="flex items-center gap-2.5 text-sm cursor-pointer">
                <input
                  type="radio"
                  name="wa-frekuensi"
                  data-testid={`wa-frekuensi-${f.value}`}
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

      <Button data-testid="wa-simpan-pengaturan" onClick={simpan} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
        <Save className="w-3.5 h-3.5" /> Simpan Pengaturan
      </Button>
    </div>
  );
}

function LogPercakapan({ onGotoTab }) {
  const [search, setSearch] = useState("");
  const [conversations, setConversations] = useState([]);

  useEffect(() => {
    api.get("/pesan-whatsapp/percakapan").then((r) => setConversations(r.data)).catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => c.nama.toLowerCase().includes(q) || c.no_hp.includes(q));
  }, [conversations, search]);

  return (
    <div className="space-y-3">
      <div className="max-w-sm">
        <Label htmlFor="wa-log-search">Cari nama / nomor HP</Label>
        <div className="relative mt-1.5">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <Input id="wa-log-search" data-testid="wa-log-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Mis: Rina, 6281234…" className="pl-9" />
        </div>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-0 divide-y divide-slate-100" data-testid="wa-log-list">
          {filtered.map((c) => (
            <div key={c.id} className="p-4" data-testid={`wa-log-row-${c.id}`}>
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="text-sm font-semibold">{c.nama} <span className="text-xs font-normal text-slate-400">({c.no_hp})</span></div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${
                    c.status_kirim === "Terkirim" ? "bg-emerald-100 text-emerald-800"
                    : c.status_kirim === "Ditangani Provider" ? "bg-slate-100 text-slate-600"
                    : "bg-red-100 text-red-800"
                  }`}>
                    {c.status_kirim === "Terkirim" ? <CheckCircle2 className="w-3 h-3" />
                      : c.status_kirim === "Ditangani Provider" ? <Bot className="w-3 h-3" />
                      : <XCircle className="w-3 h-3" />} {c.status_kirim}
                  </span>
                  <span className="text-xs text-slate-400">{fmtDateTime(c.waktu)}</span>
                </div>
              </div>
              <div className="flex items-start gap-2 mb-1.5">
                <span className="text-xs font-bold text-slate-500 w-16 shrink-0">Tamu</span>
                <p className="text-sm bg-slate-50 rounded-lg px-3 py-1.5 flex-1">{c.pesan_masuk}</p>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-xs font-bold text-blue-600 w-16 shrink-0">Bot AI</span>
                {c.balasan_ai ? (
                  <p className="text-sm bg-blue-50 rounded-lg px-3 py-1.5 flex-1">{c.balasan_ai}</p>
                ) : c.status_kirim === "Ditangani Provider" ? (
                  <p className="text-sm bg-slate-50 text-slate-500 rounded-lg px-3 py-1.5 flex-1 italic">Dibalas otomatis oleh AI bawaan provider WhatsApp (bukan PMS) — tidak tercatat di sini.</p>
                ) : (
                  <p className="text-sm bg-red-50 text-red-700 rounded-lg px-3 py-1.5 flex-1 italic">
                    Gagal membalas — lihat tab{" "}
                    <button type="button" className="underline" onClick={() => onGotoTab("pemantauan")}>Pemantauan Status</button>.
                  </p>
                )}
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="p-8 text-center text-slate-500 text-sm">Tidak ada percakapan yang cocok</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// Dasbor kesehatan pengiriman pesan bot WhatsApp (fokus status/infrastruktur), beda
// dengan tab "Log Percakapan" yang menampilkan ISI percakapan (pesan masuk + balasan AI).
// Tab ini fokus deteksi kegagalan integrasi.
const DELIVERY_STATUS_META = {
  Terkirim: "bg-emerald-100 text-emerald-800",
  Diterima: "bg-blue-100 text-blue-800",
  Gagal: "bg-red-100 text-red-800",
};

function DetailPesanDialog({ pesan, onClose, onKirimUlang }) {
  const [resending, setResending] = useState(false);

  const kirimUlang = async () => {
    setResending(true);
    try {
      const { data } = await api.post(`/pemantauan-status-wa/log-pengiriman/${pesan.conv_id}/kirim-ulang`);
      if (data.ok) {
        toast.success(`Pesan ke ${pesan.no_hp} berhasil dikirim ulang`);
      } else {
        toast.error(data.error || "Gagal mengirim ulang");
      }
      onKirimUlang();
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal mengirim ulang");
    } finally {
      setResending(false);
    }
  };

  return (
    <Dialog open={!!pesan} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="delivery-detail-title">Detail Pesan</DialogTitle>
        </DialogHeader>
        {pesan && (
          <div className="space-y-2 text-sm" data-testid="delivery-detail-body">
            <div className="flex items-center gap-2">
              <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${DELIVERY_STATUS_META[pesan.status] || "bg-slate-100 text-slate-600"}`}>{pesan.status}</span>
              <span className="text-[10px] uppercase font-bold px-2 py-1 rounded bg-slate-100 text-slate-600 capitalize">{pesan.arah}</span>
            </div>
            <div><span className="text-slate-500">Nomor:</span> <span className="font-mono">{pesan.no_hp}</span></div>
            <div><span className="text-slate-500">Waktu:</span> {fmtDateTime(pesan.waktu)}</div>
            {pesan.error && (
              <div className="bg-red-50 border border-red-200 rounded p-2 text-red-800">
                <span className="font-semibold">Error:</span> {pesan.error}
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Tutup</Button>
          {pesan?.status === "Gagal" && pesan?.arah === "keluar" && (
            <Button data-testid="delivery-kirim-ulang" onClick={kirimUlang} disabled={resending} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
              <RefreshCw className={`w-3.5 h-3.5 ${resending ? "animate-spin" : ""}`} /> {resending ? "Mengirim…" : "Kirim Ulang"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PemantauanStatus() {
  const [stats, setStats] = useState({ terkirim_hari_ini: 0, gagal_hari_ini: 0, tingkat_sukses: 100, rata_respons_detik: 0 });
  const [alerts, setAlerts] = useState([]);
  const [deliveryLog, setDeliveryLog] = useState([]);
  const [failureSummary, setFailureSummary] = useState([]);
  const [connectionLog, setConnectionLog] = useState([]);
  const [selected, setSelected] = useState(null);

  const load = () => {
    api.get("/pemantauan-status-wa/stats").then((r) => setStats(r.data)).catch(() => {});
    api.get("/pemantauan-status-wa/alerts").then((r) => setAlerts(r.data)).catch(() => {});
    api.get("/pemantauan-status-wa/log-pengiriman").then((r) => setDeliveryLog(r.data)).catch(() => {});
    api.get("/pemantauan-status-wa/ringkasan-kegagalan").then((r) => setFailureSummary(r.data)).catch(() => {});
    api.get("/pemantauan-status-wa/connection-log").then((r) => setConnectionLog(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const cards = [
    { label: "Terkirim Hari Ini", value: stats.terkirim_hari_ini, icon: Send, cls: "bg-blue-50 text-blue-600" },
    { label: "Gagal Hari Ini", value: stats.gagal_hari_ini, icon: XCircle, cls: "bg-red-50 text-red-600" },
    { label: "Tingkat Keberhasilan", value: `${stats.tingkat_sukses}%`, icon: CheckCircle2, cls: "bg-emerald-50 text-emerald-600" },
    { label: "Rata-rata Waktu Respons", value: `${stats.rata_respons_detik}s`, icon: Timer, cls: "bg-amber-50 text-amber-600" },
  ];

  return (
    <div className="space-y-6" data-testid="pemantauan-status-wa-page">
      {alerts.length > 0 && (
        <div className="space-y-2" data-testid="pemantauan-alerts">
          {alerts.map((a) => (
            <Card key={a.id} className="border-red-300 bg-red-50">
              <CardContent className="p-3 flex items-start gap-2 text-sm">
                <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                <div>
                  <p className="text-red-800">{a.pesan}</p>
                  <p className="text-[11px] text-red-500 mt-0.5">{fmtDateTime(a.waktu)}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3" data-testid="pemantauan-stats-grid">
        {cards.map((c) => (
          <Card key={c.label} className="border-slate-200">
            <CardContent className="p-4 flex items-center gap-3">
              <div className={`w-10 h-10 rounded-xl grid place-items-center shrink-0 ${c.cls}`}>
                <c.icon className="w-5 h-5" />
              </div>
              <div>
                <div className="text-xl font-extrabold">{c.value}</div>
                <div className="text-xs text-slate-500">{c.label}</div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        <Card className="border-slate-200">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-slate-700">Ringkasan Kegagalan</h3>
            </div>
            <div className="space-y-2" data-testid="failure-summary-list">
              {failureSummary.map((f, i) => (
                <div key={i} className="flex items-center justify-between text-sm" data-testid={`failure-summary-${i}`}>
                  <span className="text-slate-600">{f.alasan}</span>
                  <span className="font-bold text-red-600">{f.jumlah}x</span>
                </div>
              ))}
              {failureSummary.length === 0 && <p className="text-sm text-slate-500">Tidak ada kegagalan tercatat</p>}
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-slate-700">Log Perubahan Status Koneksi</h3>
            </div>
            <div className="space-y-2" data-testid="connection-log-list">
              {connectionLog.map((c) => (
                <div key={c.id} className="flex items-start gap-2 text-sm" data-testid={`connection-log-${c.id}`}>
                  {c.status === "connected" ? <Wifi className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-0.5" /> : <WifiOff className="w-3.5 h-3.5 text-red-600 shrink-0 mt-0.5" />}
                  <div className="min-w-0">
                    <p className="text-slate-600">{c.keterangan}</p>
                    <p className="text-[11px] text-slate-400">{fmtDateTime(c.waktu)}</p>
                  </div>
                </div>
              ))}
              {connectionLog.length === 0 && <p className="text-sm text-slate-500">Belum ada riwayat koneksi</p>}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-0">
          <div className="p-4 border-b border-slate-100 flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-700">Log Pengiriman Pesan</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="delivery-log-table">
              <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
                <tr>
                  <th className="text-left p-3">Waktu</th>
                  <th className="text-left p-3">Nomor</th>
                  <th className="text-left p-3">Arah</th>
                  <th className="text-left p-3">Status</th>
                  <th className="text-left p-3">Keterangan</th>
                </tr>
              </thead>
              <tbody>
                {deliveryLog.map((d) => (
                  <tr
                    key={d.id}
                    data-testid={`delivery-log-row-${d.id}`}
                    onClick={() => setSelected(d)}
                    className="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                  >
                    <td className="p-3 text-slate-500">{fmtDateTime(d.waktu)}</td>
                    <td className="p-3 font-mono text-xs">{d.no_hp}</td>
                    <td className="p-3 capitalize">{d.arah}</td>
                    <td className="p-3">
                      <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${DELIVERY_STATUS_META[d.status] || "bg-slate-100 text-slate-600"}`}>{d.status}</span>
                    </td>
                    <td className="p-3 text-slate-600">{d.error || "-"}</td>
                  </tr>
                ))}
                {deliveryLog.length === 0 && (
                  <tr><td colSpan={5} className="p-6 text-center text-slate-500">Belum ada log pengiriman</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <DetailPesanDialog pesan={selected} onClose={() => setSelected(null)} onKirimUlang={load} />
    </div>
  );
}

const FLOW_ICON = { ketersediaan: BedDouble, harga: Tag, status_booking: ClipboardList, reservasi_baru: Bot };
const CHECK_INTERVAL_MS = 10000;

// Indikator "live" (sama pola dengan SinkronisasiKetersediaan.jsx): titik berdenyut +
// jam berjalan sejak pengecekan terakhir, supaya dasbor terasa real-time.
function LiveIndicator({ lastChecked }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const detik = Math.max(0, Math.round((Date.now() - new Date(lastChecked).getTime()) / 1000));
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700" data-testid="data-flow-live-indicator">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
      Live &bull; dicek {detik}d lalu
    </span>
  );
}

// Dasbor monitoring aliran data dari Pelangi PMS ke bot WhatsApp. Beda dengan halaman
// "Sinkronisasi Ketersediaan" (SinkronisasiKetersediaan.jsx, tetap terpisah) yang memantau
// SEMUA saluran penjualan (Website/OTA/WhatsApp) terhadap Availability Engine — tab ini
// fokus pada data spesifik apa saja yang mengalir ke bot WhatsApp dan kapan terakhir
// disinkron. Bot di sistem ini membaca `rooms`/`bookings` langsung secara live (bukan
// salinan terpisah), jadi ketersediaan & harga selalu tersinkron sempurna by design.
const FLOW_STATUS_META = {
  synced: { label: "Tersinkron", cls: "bg-emerald-100 text-emerald-800" },
  pending: { label: "Menunggu Perubahan", cls: "bg-slate-200 text-slate-600" },
  error: { label: "Gagal Sinkron", cls: "bg-red-100 text-red-800" },
};

function SinkronisasiData() {
  const [flows, setFlows] = useState([]);
  const [comparison, setComparison] = useState([]);
  const [referensi, setReferensi] = useState([]);
  const [alertLogs, setAlertLogs] = useState([]);
  const [lastChecked, setLastChecked] = useState(() => new Date().toISOString());

  const load = () => {
    api.get("/sinkronisasi-data-pms/dashboard").then((r) => setFlows(r.data.flows)).catch(() => {});
    api.get("/sinkronisasi-data-pms/perbandingan-ketersediaan").then((r) => setComparison(r.data)).catch(() => {});
    api.get("/sinkronisasi-data-pms/referensi").then((r) => setReferensi(r.data)).catch(() => {});
    api.get("/sinkronisasi-data-pms/alerts").then((r) => setAlertLogs(r.data)).catch(() => {});
    setLastChecked(new Date().toISOString());
  };

  useEffect(() => {
    load();
    const t = setInterval(load, CHECK_INTERVAL_MS);
    return () => clearInterval(t);
  }, []);

  const lastSyncAll = flows.reduce((max, f) => (f.last_sync && f.last_sync > max ? f.last_sync : max), flows[0]?.last_sync || null);

  return (
    <div className="space-y-6" data-testid="sinkronisasi-data-pms-page">
      <Card className="border-emerald-300 bg-emerald-50">
        <CardContent className="p-4 flex flex-wrap items-center gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
          <p className="text-sm font-medium text-emerald-800">
            Semua data terbaru sudah mengalir ke bot &bull; sinkron terakhir {fmtDateTime(lastSyncAll)}
          </p>
          <LiveIndicator lastChecked={lastChecked} />
        </CardContent>
      </Card>

      <div className="grid sm:grid-cols-2 gap-3" data-testid="data-flow-grid">
        {flows.map((f) => {
          const meta = FLOW_STATUS_META[f.status];
          const Icon = FLOW_ICON[f.key] || Bot;
          return (
            <Card key={f.key} className="border-slate-200" data-testid={`data-flow-card-${f.key}`}>
              <CardContent className="p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 grid place-items-center shrink-0">
                    <Icon className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="font-semibold text-sm">{f.label}</div>
                    <div className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                      <Clock className="w-3 h-3" /> {f.last_sync ? fmtDateTime(f.last_sync) : "Belum pernah"} &bull; {f.jumlah_record} data
                    </div>
                  </div>
                </div>
                <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium shrink-0 ${meta.cls}`}>{meta.label}</span>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Ketersediaan Kamar: Bot vs PMS</h3>
          <div className="grid sm:grid-cols-2 gap-3" data-testid="availability-comparison-grid">
            {comparison.map((c) => {
              const cocok = c.bot === c.pms;
              return (
                <div key={c.tipe} className={`rounded-lg border p-3 ${cocok ? "border-slate-200" : "border-red-300 bg-red-50"}`} data-testid={`availability-comparison-${c.tipe}`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-sm">{c.tipe}</span>
                    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded ${cocok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
                      {cocok ? <CheckCircle className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                      {cocok ? "Cocok" : "Tidak Cocok"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-1.5 text-slate-600"><Bot className="w-3.5 h-3.5" /> Dilihat Bot: <b>{c.bot}</b></div>
                    <div className="flex items-center gap-1.5 text-slate-600"><BedDouble className="w-3.5 h-3.5" /> Di PMS: <b>{c.pms}</b></div>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">Referensi Reservasi PMS</h3>
            <Link to="/reservasi" data-testid="referensi-lihat-semua" className="text-xs text-blue-700 hover:underline flex items-center gap-1">
              Lihat Daftar Reservasi <ExternalLink className="w-3 h-3" />
            </Link>
          </div>
          <div className="divide-y divide-slate-100" data-testid="pms-reference-list">
            {referensi.map((r) => (
              <div key={r.id} className="p-3 flex items-center justify-between gap-3" data-testid={`pms-reference-${r.id}`}>
                <div>
                  <span className="font-semibold text-sm">{r.kode}</span>
                  <span className="text-sm text-slate-500"> — {r.nama_tamu} ({r.room_tipe})</span>
                </div>
                <span className={`text-xs font-medium px-2 py-1 rounded-md ${r.status === "Confirmed" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{r.status}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0">
          <div className="p-4 border-b border-slate-100">
            <h3 className="text-sm font-semibold text-slate-700">Log Peringatan Gangguan</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="alert-log-table">
              <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
                <tr>
                  <th className="text-left p-3">Waktu</th>
                  <th className="text-left p-3">Data Terdampak</th>
                  <th className="text-left p-3">Pesan</th>
                  <th className="text-left p-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {alertLogs.map((a) => (
                  <tr key={a.id} data-testid={`alert-log-row-${a.id}`} className="border-t border-slate-100">
                    <td className="p-3 text-slate-500">{fmtDateTime(a.waktu)}</td>
                    <td className="p-3 font-medium">{a.data_type}</td>
                    <td className="p-3 text-slate-600">{a.pesan}</td>
                    <td className="p-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium ${a.resolved ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
                        {a.resolved ? <CheckCircle className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                        {a.resolved ? "Sudah Teratasi" : "Perlu Perhatian"}
                      </span>
                    </td>
                  </tr>
                ))}
                {alertLogs.length === 0 && (
                  <tr><td colSpan={4} className="p-6 text-center text-slate-500">Tidak ada gangguan tercatat</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// Provider webhook WhatsApp pihak ketiga yang umum dipakai bisnis di Indonesia.
// BalesOtomatis: sudah punya AI auto-reply bawaan sendiri & ARAH PANGGILANNYA TERBALIK
// dari Fonnte/Wablas/Qontak — dia yang memanggil URL Webhook Masuk PMS (bukan PMS yang
// memanggil dia untuk mengirim pesan), makanya field & validasinya beda, lihat di bawah.
const PROVIDER_OPTIONS = ["BalesOtomatis", "Fonnte", "Wablas", "Qontak", "Lainnya (Custom API)"];

const EMPTY_WEBHOOK_CONFIG = {
  aktif: false, provider: "Fonnte", webhook_url: "", api_key: "", nomor_whatsapp: "", webhook_token: null, updated_at: null,
};

function Kredensial() {
  const [saved, setSaved] = useState(EMPTY_WEBHOOK_CONFIG);
  const [form, setForm] = useState(EMPTY_WEBHOOK_CONFIG);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // { ok, message, tested_at }
  const [attemptedSave, setAttemptedSave] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copiedPengetahuan, setCopiedPengetahuan] = useState(false);

  useEffect(() => {
    api.get("/konfigurasi-webhook").then((r) => { setSaved(r.data); setForm(r.data); }).catch(() => {});
  }, []);

  const isBales = form.provider === "BalesOtomatis";
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const errors = {
    webhook_url: !isBales && !form.webhook_url.trim() && "Wajib diisi",
    api_key: !form.api_key.trim() && "Wajib diisi",
    nomor_whatsapp: !form.nomor_whatsapp.trim() && "Wajib diisi",
  };
  const valid = !errors.webhook_url && !errors.api_key && !errors.nomor_whatsapp;

  const inboundUrl = saved.webhook_token
    ? saved.provider === "BalesOtomatis"
      ? `${API_BASE}/webhook/whatsapp/balesotomatis/${saved.webhook_token}`
      : `${API_BASE}/webhook/whatsapp/incoming`
    : null;
  const pengetahuanUrl = saved.provider === "BalesOtomatis" && saved.webhook_token
    ? `${API_BASE}/webhook/whatsapp/balesotomatis/${saved.webhook_token}/pengetahuan`
    : null;

  const salinUrl = async () => {
    if (!inboundUrl) return;
    await navigator.clipboard.writeText(inboundUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  const salinPengetahuanUrl = async () => {
    if (!pengetahuanUrl) return;
    await navigator.clipboard.writeText(pengetahuanUrl);
    setCopiedPengetahuan(true);
    setTimeout(() => setCopiedPengetahuan(false), 2000);
  };

  const maskedKey = (key) => (key.length <= 8 ? "••••••••" : `${key.slice(0, 6)}${"•".repeat(Math.min(16, key.length - 10))}${key.slice(-4)}`);

  const simpan = async () => {
    setAttemptedSave(true);
    if (!valid) { toast.error("Lengkapi dulu field yang wajib diisi"); return; }
    try {
      const { data } = await api.put("/konfigurasi-webhook", { ...form, aktif: true });
      setSaved(data);
      setForm(data);
      setTestResult(null);
      setAttemptedSave(false);
      toast.success("Konfigurasi webhook WhatsApp disimpan");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan konfigurasi");
    }
  };

  const batalkanPerubahan = () => {
    setForm(saved);
    setAttemptedSave(false);
  };

  const ujiKoneksi = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data } = await api.post("/konfigurasi-webhook/test");
      setTestResult(data);
      if (data.ok) toast.success("Uji koneksi berhasil"); else toast.error("Uji koneksi gagal");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menguji koneksi");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="konfigurasi-webhook-page">
      <p className="text-sm text-slate-500">
        Hubungkan sistem dengan penyedia layanan WhatsApp agar bot bisa membaca ketersediaan &amp; membuat reservasi otomatis.
      </p>

      <Card className={saved.aktif ? "border-emerald-300 bg-emerald-50" : "border-slate-200"}>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className={`w-11 h-11 rounded-xl grid place-items-center shrink-0 ${saved.aktif ? "bg-emerald-100 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
                <MessageCircle className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <div className="font-semibold flex items-center gap-1.5" data-testid="webhook-status-label">
                  {saved.aktif ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : <XCircle className="w-4 h-4 text-slate-400" />}
                  {saved.aktif ? `Aktif — ${saved.provider}` : "Belum Dikonfigurasi"}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  Nomor bot: {saved.nomor_whatsapp} &bull; Terakhir diperbarui: {fmtDateTime(saved.updated_at)}
                </div>
              </div>
            </div>
            <Button data-testid="webhook-uji-koneksi" variant="outline" size="sm" onClick={ujiKoneksi} disabled={testing} className="gap-1.5 shrink-0">
              {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />} {testing ? "Menguji…" : "Uji Koneksi"}
            </Button>
          </div>
          {testResult && (
            <div
              data-testid="webhook-test-result"
              className={`text-xs rounded-lg p-2.5 flex items-start gap-2 ${testResult.ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}
            >
              {testResult.ok ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" /> : <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
              <span>{testResult.message} <span className="opacity-70">({fmtDateTime(testResult.tested_at)})</span></span>
            </div>
          )}
        </CardContent>
      </Card>

      {inboundUrl && (
        <Card className="border-blue-200 bg-blue-50/50">
          <CardContent className="p-4 space-y-2">
            <h3 className="text-sm font-semibold text-slate-700">URL Webhook Masuk</h3>
            <p className="text-xs text-slate-500">
              {saved.provider === "BalesOtomatis"
                ? "Tempel URL ini di dashboard BalesOtomatis (Pengaturan Device → Webhook / AI Trigger) supaya pesan WhatsApp masuk tercatat di tab Log Percakapan. Balasan otomatis tetap ditangani AI bawaan BalesOtomatis sendiri."
                : "URL generik untuk provider yang memanggil PMS saat ada pesan masuk (kontrak {sender/from, message/text, name})."}
            </p>
            <div className="flex items-center gap-2">
              <Input readOnly value={inboundUrl} data-testid="webhook-inbound-url" className="font-mono text-xs bg-white" onFocus={(e) => e.target.select()} />
              <Button type="button" variant="outline" size="sm" onClick={salinUrl} className="gap-1.5 shrink-0" data-testid="webhook-inbound-copy">
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />} {copied ? "Tersalin" : "Salin"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {pengetahuanUrl && (
        <Card className="border-amber-200 bg-amber-50/50">
          <CardContent className="p-4 space-y-2">
            <h3 className="text-sm font-semibold text-slate-700">URL Ketersediaan Kamar (untuk Knowledge Base AI)</h3>
            <p className="text-xs text-slate-500">
              AI bawaan BalesOtomatis yang menjawab pertanyaan tamu, bukan PMS ini — supaya jawabannya pakai data kamar
              yang sebenarnya (bukan jawaban generik), cari fitur "Knowledge Base" / "FAQ" / "Info AI dari URL" di
              dashboard BalesOtomatis lalu tempel URL ini di sana. Kalau BalesOtomatis belum punya fitur ambil-otomatis
              dari URL, buka URL ini dan salin isinya manual ke pengaturan AI mereka secara berkala.
            </p>
            <div className="flex items-center gap-2">
              <Input readOnly value={pengetahuanUrl} data-testid="webhook-pengetahuan-url" className="font-mono text-xs bg-white" onFocus={(e) => e.target.select()} />
              <Button type="button" variant="outline" size="sm" onClick={salinPengetahuanUrl} className="gap-1.5 shrink-0" data-testid="webhook-pengetahuan-copy">
                {copiedPengetahuan ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />} {copiedPengetahuan ? "Tersalin" : "Salin"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">Endpoint &amp; Kredensial</h3>
            {dirty && (
              <span data-testid="webhook-dirty-badge" className="text-[10px] uppercase font-bold text-amber-700 bg-amber-100 px-2 py-1 rounded">
                Perubahan belum disimpan
              </span>
            )}
          </div>
          <div>
            <Label htmlFor="webhook-provider">Penyedia Layanan WhatsApp</Label>
            <select
              id="webhook-provider"
              data-testid="webhook-provider"
              value={form.provider}
              onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {PROVIDER_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          {!isBales && (
            <div>
              <Label htmlFor="webhook-url">Webhook / Endpoint URL</Label>
              <Input
                id="webhook-url"
                data-testid="webhook-url"
                value={form.webhook_url}
                onChange={(e) => setForm((f) => ({ ...f, webhook_url: e.target.value }))}
                placeholder="https://api.penyedia.com/send"
                className={`mt-1.5 font-mono text-sm ${attemptedSave && errors.webhook_url ? "border-red-400 focus-visible:ring-red-400" : ""}`}
              />
              {attemptedSave && errors.webhook_url && (
                <p className="text-xs text-red-600 mt-1 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> {errors.webhook_url}</p>
              )}
            </div>
          )}
          {isBales && (
            <p className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2">
              BalesOtomatis tidak butuh Webhook/Endpoint URL di sini — arahnya terbalik, dia yang memanggil PMS lewat "URL Webhook Masuk" di atas.
            </p>
          )}
          <div>
            <Label htmlFor="webhook-api-key">API Key / Token</Label>
            <div className="relative mt-1.5">
              <Input
                id="webhook-api-key"
                data-testid="webhook-api-key"
                type={showKey ? "text" : "password"}
                value={form.api_key}
                onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                className={`font-mono text-sm pr-10 ${attemptedSave && errors.api_key ? "border-red-400 focus-visible:ring-red-400" : ""}`}
              />
              <button
                type="button"
                data-testid="webhook-toggle-key"
                onClick={() => setShowKey((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {attemptedSave && errors.api_key ? (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> {errors.api_key}</p>
            ) : !showKey && form.api_key === saved.api_key && (
              <p className="text-xs text-slate-400 mt-1 font-mono">Tersimpan: {maskedKey(saved.api_key)}</p>
            )}
          </div>
          <div>
            <Label htmlFor="webhook-nomor">{isBales ? "Nomor WhatsApp / Device ID" : "Nomor WhatsApp Bot"}</Label>
            <Input
              id="webhook-nomor"
              data-testid="webhook-nomor"
              value={form.nomor_whatsapp}
              onChange={(e) => setForm((f) => ({ ...f, nomor_whatsapp: e.target.value }))}
              placeholder={isBales ? "628123456789 atau Device ID dari dashboard BalesOtomatis" : "628123456789"}
              className={`mt-1.5 ${attemptedSave && errors.nomor_whatsapp ? "border-red-400 focus-visible:ring-red-400" : ""}`}
            />
            {attemptedSave && errors.nomor_whatsapp && (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> {errors.nomor_whatsapp}</p>
            )}
          </div>
          <div className="flex gap-2">
            <Button data-testid="webhook-simpan" onClick={simpan} disabled={!dirty} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
              <Save className="w-3.5 h-3.5" /> Simpan Konfigurasi
            </Button>
            {dirty && (
              <Button data-testid="webhook-batal" variant="ghost" onClick={batalkanPerubahan} className="gap-1.5">
                <Undo2 className="w-3.5 h-3.5" /> Batalkan Perubahan
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="pt-4 border-t border-slate-200 space-y-4">
        <div>
          <h2 className="text-lg font-bold">Integrasi AI Chat Bot Eksternal</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Kanal terpisah untuk sistem AI eksternal (mis. AI Chat Bot lintas-produk milik sendiri, dirancang reusable
            di luar Pelangi PMS) yang membaca ketersediaan kamar &amp; menulis tiket/booking request ke PMS ini —
            bukan bagian dari kredensial provider WhatsApp di atas. PMS ini tidak pernah memanggil sistem AI tersebut;
            arahnya selalu sistem itu yang memanggil endpoint di bawah, diautentikasi API key sendiri.
          </p>
        </div>
        <IntegrasiAiBot />
      </div>
    </div>
  );
}

function IntegrasiAiBot() {
  const [cfg, setCfg] = useState({ aktif: false, api_key: "", updated_at: null });
  const [showKey, setShowKey] = useState(false);
  const [copied, setCopied] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/konfigurasi-integrasi-ai-bot").then((r) => setCfg(r.data)).catch(() => {});
  }, []);

  const toggleAktif = async () => {
    setBusy(true);
    try {
      const { data } = await api.put("/konfigurasi-integrasi-ai-bot", { aktif: !cfg.aktif });
      setCfg((c) => ({ ...c, ...data }));
      toast.success(data.aktif ? "Integrasi AI Chat Bot diaktifkan" : "Integrasi AI Chat Bot dinonaktifkan");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal mengubah status");
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    if (!window.confirm("API key lama akan langsung tidak berlaku lagi. Lanjutkan?")) return;
    setBusy(true);
    try {
      const { data } = await api.post("/konfigurasi-integrasi-ai-bot/regenerate-key");
      setCfg((c) => ({ ...c, ...data }));
      toast.success("API key baru dibuat");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal generate ulang API key");
    } finally {
      setBusy(false);
    }
  };

  const salin = async (label, value) => {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  };

  const endpoints = [
    { label: "Ketersediaan Kamar (GET)", value: `${API_BASE}/integrasi-ai-bot/ketersediaan` },
    { label: "Buat Tiket Komplain/Maintenance (POST)", value: `${API_BASE}/integrasi-ai-bot/tiket` },
    { label: "Buat Booking Request (POST)", value: `${API_BASE}/integrasi-ai-bot/booking-request` },
  ];

  return (
    <div className="space-y-4" data-testid="integrasi-ai-bot-section">
      <Card className={cfg.aktif ? "border-emerald-300 bg-emerald-50" : "border-slate-200"}>
        <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className={`w-11 h-11 rounded-xl grid place-items-center shrink-0 ${cfg.aktif ? "bg-emerald-100 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <div className="font-semibold flex items-center gap-1.5" data-testid="ai-bot-status-label">
                {cfg.aktif ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : <XCircle className="w-4 h-4 text-slate-400" />}
                {cfg.aktif ? "Integrasi Aktif" : "Integrasi Nonaktif"}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">Terakhir diperbarui: {fmtDateTime(cfg.updated_at)}</div>
            </div>
          </div>
          <Button data-testid="ai-bot-toggle-aktif" variant="outline" size="sm" onClick={toggleAktif} disabled={busy} className="gap-1.5 shrink-0">
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null} {cfg.aktif ? "Nonaktifkan" : "Aktifkan"}
          </Button>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-4">
          <div>
            <Label>API Key</Label>
            <div className="relative mt-1.5">
              <Input readOnly type={showKey ? "text" : "password"} value={cfg.api_key || ""} className="font-mono text-xs pr-10" data-testid="ai-bot-api-key" onFocus={(e) => e.target.select()} />
              <button type="button" onClick={() => setShowKey((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <div className="flex gap-2 mt-2">
              <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={() => salin("key", cfg.api_key)}>
                {copied === "key" ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />} {copied === "key" ? "Tersalin" : "Salin"}
              </Button>
              <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={regenerate} disabled={busy} data-testid="ai-bot-regenerate-key">
                <RefreshCw className="w-3.5 h-3.5" /> Generate Ulang
              </Button>
            </div>
          </div>

          <div>
            <Label>Endpoint</Label>
            <div className="space-y-2 mt-1.5">
              {endpoints.map((ep) => (
                <div key={ep.label}>
                  <p className="text-xs text-slate-500 mb-1">{ep.label}</p>
                  <div className="flex items-center gap-2">
                    <Input readOnly value={ep.value} className="font-mono text-xs bg-white" onFocus={(e) => e.target.select()} />
                    <Button type="button" variant="outline" size="sm" className="gap-1.5 shrink-0" onClick={() => salin(ep.label, ep.value)}>
                      {copied === ep.label ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default function PesanWhatsAppOtomatis() {
  const [tab, setTab] = useState("ringkasan");

  return (
    <div className="space-y-6" data-testid="pesan-whatsapp-otomatis-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Pesan WhatsApp Otomatis</h1>
        <p className="text-slate-500 mt-1">
          Bot WhatsApp yang membaca ketersediaan dari Pelangi PMS secara real-time dan mencatat interaksi tamu.
        </p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="whatsapp-tabs" className="flex-wrap h-auto">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} data-testid={`tab-${t.value}`} className="gap-1.5">
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="ringkasan" className="mt-4">
          <Ringkasan onGotoTab={setTab} />
        </TabsContent>
        <TabsContent value="log" className="mt-4">
          <LogPercakapan onGotoTab={setTab} />
        </TabsContent>
        <TabsContent value="pemantauan" className="mt-4">
          <PemantauanStatus />
        </TabsContent>
        <TabsContent value="sinkronisasi" className="mt-4">
          <SinkronisasiData />
        </TabsContent>
        <TabsContent value="pengaturan" className="mt-4">
          <PengaturanWhatsApp onGotoTab={setTab} />
        </TabsContent>
        <TabsContent value="kredensial" className="mt-4">
          <Kredensial />
        </TabsContent>
      </Tabs>
    </div>
  );
}
