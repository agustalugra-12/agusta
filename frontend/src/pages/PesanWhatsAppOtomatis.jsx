import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MessageSquare, Send, CheckCircle2, Bot, Inbox, Activity } from "lucide-react";
import { fmtDateTime } from "@/lib/apiClient";

const TABS = [
  { value: "ringkasan", label: "Ringkasan", icon: Activity },
  { value: "log", label: "Log Percakapan", icon: Inbox },
  { value: "pemantauan", label: "Pemantauan Status", icon: Send },
];

function TabPlaceholder({ label }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-8 text-center text-slate-500">
        <p className="text-sm">Bagian &ldquo;{label}&rdquo; akan dibangun di task berikutnya.</p>
      </CardContent>
    </Card>
  );
}

// Data tiruan (stub) — ringkasan aktivitas bot WhatsApp hari ini.
const MOCK_STATS = {
  pesan_masuk_hari_ini: 18,
  pesan_terkirim_hari_ini: 24,
  tingkat_sukses_kirim: 96,
  reservasi_via_wa_hari_ini: 3,
};

const MOCK_AKTIVITAS_TERBARU = [
  { id: "1", nama: "Rina Kusuma", no_hp: "6281234567021", ringkasan: "Menanyakan ketersediaan Cottage 12-14 Juli", waktu: "2026-07-11T10:05:00" },
  { id: "2", nama: "Ahmad Fauzi", no_hp: "6281234567022", ringkasan: "Konfirmasi reservasi RSV-1043 berhasil dibuat", waktu: "2026-07-11T09:48:00" },
  { id: "3", nama: "081234567023", no_hp: "6281234567023", ringkasan: "Bertanya cara pembatalan booking", waktu: "2026-07-11T09:20:00" },
  { id: "4", nama: "Sri Wahyuni", no_hp: "6281234567024", ringkasan: "Minta info harga kamar Standard weekend", waktu: "2026-07-11T08:55:00" },
];

function Ringkasan() {
  const cards = [
    { label: "Pesan Masuk Hari Ini", value: MOCK_STATS.pesan_masuk_hari_ini, icon: Inbox, cls: "bg-blue-50 text-blue-600" },
    { label: "Pesan Terkirim Hari Ini", value: MOCK_STATS.pesan_terkirim_hari_ini, icon: Send, cls: "bg-violet-50 text-violet-600" },
    { label: "Tingkat Sukses Kirim", value: `${MOCK_STATS.tingkat_sukses_kirim}%`, icon: CheckCircle2, cls: "bg-emerald-50 text-emerald-600" },
    { label: "Reservasi via WhatsApp", value: MOCK_STATS.reservasi_via_wa_hari_ini, icon: Bot, cls: "bg-amber-50 text-amber-600" },
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
          {MOCK_AKTIVITAS_TERBARU.map((a) => (
            <div key={a.id} className="p-3.5 flex items-start gap-3" data-testid={`whatsapp-aktivitas-${a.id}`}>
              <div className="w-8 h-8 rounded-full bg-emerald-50 text-emerald-600 grid place-items-center shrink-0">
                <MessageSquare className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{a.nama}</div>
                <div className="text-xs text-slate-500 truncate">{a.ringkasan}</div>
              </div>
              <div className="text-xs text-slate-400 shrink-0">{fmtDateTime(a.waktu)}</div>
            </div>
          ))}
        </CardContent>
      </Card>
      <p className="text-[11px] text-slate-400">Data tiruan — belum tersambung ke bot WhatsApp sungguhan.</p>
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
        {TABS.filter((t) => t.value !== "ringkasan").map((t) => (
          <TabsContent key={t.value} value={t.value} className="mt-4">
            <TabPlaceholder label={t.label} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
