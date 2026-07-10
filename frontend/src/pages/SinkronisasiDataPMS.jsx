import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { BedDouble, Tag, ClipboardList, Bot, CheckCircle2, Clock, AlertTriangle, CheckCircle, XCircle, ExternalLink } from "lucide-react";
import { fmtDateTime } from "@/lib/apiClient";

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

// Dasbor monitoring aliran data dari Pelangi PMS ke bot WhatsApp (feature "Sinkronisasi
// Data PMS" di PRD, bagian dari "Pesan WhatsApp Otomatis"). Beda dengan halaman
// "Sinkronisasi Ketersediaan" (SinkronisasiKetersediaan.jsx) yang memantau semua saluran
// penjualan (Website/OTA/WhatsApp) terhadap Availability Engine — halaman ini fokus pada
// data spesifik apa saja yang mengalir ke bot WhatsApp dan kapan terakhir disinkron.
// Pengaturan (apa yang disinkron + frekuensi) ada di tab "Pengaturan" halaman Pesan
// WhatsApp Otomatis (PesanWhatsAppOtomatis.jsx) — halaman ini murni status/monitoring.
const MOCK_DATA_FLOWS = [
  { key: "ketersediaan", label: "Ketersediaan Kamar", icon: BedDouble, last_sync: "2026-07-11T10:14:00", jumlah_record: 18, status: "synced" },
  { key: "harga", label: "Harga & Tarif", icon: Tag, last_sync: "2026-07-11T10:14:00", jumlah_record: 2, status: "synced" },
  { key: "status_booking", label: "Status Booking", icon: ClipboardList, last_sync: "2026-07-11T10:12:00", jumlah_record: 6, status: "synced" },
  { key: "reservasi_baru", label: "Reservasi Baru (Email OTA)", icon: Bot, last_sync: "2026-07-11T09:03:00", jumlah_record: 0, status: "pending" },
];

const STATUS_META = {
  synced: { label: "Tersinkron", cls: "bg-emerald-100 text-emerald-800" },
  pending: { label: "Menunggu Perubahan", cls: "bg-slate-200 text-slate-600" },
  error: { label: "Gagal Sinkron", cls: "bg-red-100 text-red-800" },
};

// Data tiruan (stub) — perbandingan jumlah kamar tersedia yang "dilihat" bot WhatsApp
// (dari sinkronisasi terakhir) vs jumlah tersedia sungguhan di Pelangi PMS saat ini.
// Kalau beda, artinya bot belum menerima update terbaru (drift) — inilah yang dicek
// dashboard ini secara visual, bukan cuma percaya status "Tersinkron" begitu saja.
const MOCK_AVAILABILITY_COMPARISON = [
  { tipe: "Standard", bot: 7, pms: 7 },
  { tipe: "Cottage", bot: 2, pms: 3 },
];

// Data tiruan (stub) — reservasi Pelangi PMS yang jadi rujukan/sumber data yang barusan
// disinkron ke bot WhatsApp bot (mis. reservasi baru hasil AI Email Parser yang bot pakai
// untuk menjawab "sudah dikonfirmasi ya?" dari tamu).
const MOCK_PMS_REFERENCES = [
  { id: "1", kode: "RSV-1043", nama_tamu: "Ahmad Fauzi", room_tipe: "Standard", status: "Confirmed" },
  { id: "2", kode: "RSV-1042", nama_tamu: "Dewi Anggraini", room_tipe: "Cottage", status: "Confirmed" },
  { id: "3", kode: "RSV-1041", nama_tamu: "Budi Santoso", room_tipe: "Standard", status: "Pending" },
];

// Data tiruan (stub) — riwayat gangguan sinkronisasi data ke bot WhatsApp.
const MOCK_ALERT_LOGS = [
  { id: "1", data_type: "Reservasi Baru (Email OTA)", pesan: "Timeout menghubungi Availability Engine setelah 3 percobaan", waktu: "2026-07-11T09:03:00", resolved: false },
  { id: "2", data_type: "Ketersediaan Kamar", pesan: "Webhook WhatsApp Bot merespons 502 — sinkron ditunda otomatis", waktu: "2026-07-10T22:14:00", resolved: true },
  { id: "3", data_type: "Status Booking", pesan: "Kredensial webhook kedaluwarsa saat sinkron terjadwal", waktu: "2026-07-10T14:00:00", resolved: true },
];

export default function SinkronisasiDataPMS() {
  const lastSyncAll = MOCK_DATA_FLOWS.reduce((max, f) => (f.last_sync > max ? f.last_sync : max), MOCK_DATA_FLOWS[0].last_sync);
  const [lastChecked, setLastChecked] = useState(() => new Date().toISOString());

  useEffect(() => {
    const t = setInterval(() => setLastChecked(new Date().toISOString()), CHECK_INTERVAL_MS);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-6" data-testid="sinkronisasi-data-pms-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Sinkronisasi Data PMS</h1>
        <p className="text-slate-500 mt-1">
          Status aliran data dari Pelangi PMS ke bot WhatsApp secara otomatis.
        </p>
      </div>

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
        {MOCK_DATA_FLOWS.map((f) => {
          const meta = STATUS_META[f.status];
          return (
            <Card key={f.key} className="border-slate-200" data-testid={`data-flow-card-${f.key}`}>
              <CardContent className="p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 grid place-items-center shrink-0">
                    <f.icon className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="font-semibold text-sm">{f.label}</div>
                    <div className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                      <Clock className="w-3 h-3" /> {fmtDateTime(f.last_sync)} &bull; {f.jumlah_record} data
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
            {MOCK_AVAILABILITY_COMPARISON.map((c) => {
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
            {MOCK_PMS_REFERENCES.map((r) => (
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
                {MOCK_ALERT_LOGS.map((a) => (
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
                {MOCK_ALERT_LOGS.length === 0 && (
                  <tr><td colSpan={4} className="p-6 text-center text-slate-500">Tidak ada gangguan tercatat</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <p className="text-[11px] text-slate-400">Data tiruan — belum tersambung ke Availability Engine/bot sungguhan.</p>
    </div>
  );
}
