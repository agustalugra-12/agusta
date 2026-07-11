import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MessageSquare, Send, CheckCircle2, Bot, Inbox, Activity, Settings2, ExternalLink, Save, Search, XCircle } from "lucide-react";
import api, { fmtDateTime } from "@/lib/apiClient";

const TABS = [
  { value: "ringkasan", label: "Ringkasan", icon: Activity },
  { value: "log", label: "Log Percakapan", icon: Inbox },
  { value: "pemantauan", label: "Pemantauan Status", icon: Send },
  { value: "pengaturan", label: "Pengaturan", icon: Settings2 },
];

function Ringkasan() {
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
            <div className="p-8 text-center text-slate-500 text-sm">Belum ada aktivitas — hubungkan webhook di halaman Konfigurasi Webhook.</div>
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

// Halaman ini TIDAK menduplikasi form kredensial di halaman "Konfigurasi Webhook"
// (KonfigurasiWebhook.jsx) — di sini cuma ringkasan status + tautan ke sana, fokusnya
// pengaturan data apa saja yang disinkronkan dari Pelangi PMS ke bot WhatsApp.
function PengaturanWhatsApp() {
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
              <div className="text-xs text-slate-500">Kredensial &amp; endpoint diatur di halaman Konfigurasi Webhook.</div>
            </div>
          </div>
          <Button asChild variant="outline" size="sm" className="gap-1.5 shrink-0" data-testid="wa-buka-konfigurasi-webhook">
            <Link to="/konfigurasi-webhook">Kelola Webhook <ExternalLink className="w-3.5 h-3.5" /></Link>
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

function LogPercakapan() {
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
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${c.status_kirim === "Terkirim" ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
                    {c.status_kirim === "Terkirim" ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />} {c.status_kirim}
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
                ) : (
                  <p className="text-sm bg-red-50 text-red-700 rounded-lg px-3 py-1.5 flex-1 italic">Gagal membalas — lihat tab Pemantauan Status.</p>
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

export default function PesanWhatsAppOtomatis() {
  return (
    <div className="space-y-6" data-testid="pesan-whatsapp-otomatis-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Pesan WhatsApp Otomatis</h1>
        <p className="text-slate-500 mt-1">
          Bot WhatsApp yang membaca ketersediaan dari Pelangi PMS secara real-time dan mencatat interaksi tamu.
        </p>
      </div>

      <Tabs defaultValue="ringkasan">
        <TabsList data-testid="whatsapp-tabs">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} data-testid={`tab-${t.value}`} className="gap-1.5">
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="ringkasan" className="mt-4">
          <Ringkasan />
        </TabsContent>
        <TabsContent value="pengaturan" className="mt-4">
          <PengaturanWhatsApp />
        </TabsContent>
        <TabsContent value="log" className="mt-4">
          <LogPercakapan />
        </TabsContent>
        <TabsContent value="pemantauan" className="mt-4">
          <Card className="border-slate-200">
            <CardContent className="p-8 text-center space-y-3">
              <p className="text-sm text-slate-500">Pemantauan status pengiriman/penerimaan pesan sekarang punya halaman tersendiri.</p>
              <Button asChild className="gap-1.5 bg-blue-700 hover:bg-blue-800" data-testid="wa-buka-pemantauan-status">
                <Link to="/pemantauan-status-wa">Buka Pemantauan Status <ExternalLink className="w-3.5 h-3.5" /></Link>
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
