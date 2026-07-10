import { useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Mail, Inbox, Wand2, FileWarning, CheckCircle2, Unlink, AlertTriangle } from "lucide-react";
import { fmtDateTime, fmtRp } from "@/lib/apiClient";

// Data tiruan (stub) — log email OTA yang sudah diproses AI Email Parser. `extracted_data`
// mengikuti entitas EMAIL_LOGS di PRD (JSON hasil ekstraksi AI); kosong untuk email yang
// gagal/perlu proses manual, digantikan `alasan`.
const MOCK_EMAIL_LOGS = [
  {
    id: "1", subjek: "Konfirmasi Reservasi #AGD-88213", pengirim: "noreply@agoda.com", sumber: "Agoda",
    status: "Parsed_Success", processed_at: "2026-07-10T08:12:00", gmail_message_id: "18f2a9c7b3e4d501",
    extracted_data: {
      no_reservasi: "AGD-88213", nama_tamu: "Ahmad Fauzi", tipe_kamar: "Standard",
      check_in: "2026-07-12T14:00:00", check_out: "2026-07-14T12:00:00",
      jumlah_tamu: 2, harga: 240000, status_pembayaran: "Lunas",
    },
  },
  {
    id: "2", subjek: "Booking Baru - Traveloka BKN-4471", pengirim: "no-reply@traveloka.com", sumber: "Traveloka",
    status: "Parsed_Success", processed_at: "2026-07-10T09:03:00", gmail_message_id: "18f2a8b1c9d3e402",
    extracted_data: {
      no_reservasi: "BKN-4471", nama_tamu: "Rina Kusuma", tipe_kamar: "Standard",
      check_in: "2026-07-13T14:00:00", check_out: "2026-07-15T12:00:00",
      jumlah_tamu: 2, harga: 240000, status_pembayaran: "Lunas",
    },
  },
  {
    id: "3", subjek: "New reservation confirmed - Booking.com", pengirim: "noreply@booking.com", sumber: "Booking.com",
    status: "Manual_Required", processed_at: "2026-07-10T10:41:00", gmail_message_id: "18f2a6d4a1b2c303",
    extracted_data: null,
    alasan: "Format email Booking.com ini belum dikenali parser AI (template baru) — perlu dipetakan manual di tab \"Proses Manual\".",
  },
  {
    id: "4", subjek: "Pembatalan Pesanan #AGD-88190", pengirim: "noreply@agoda.com", sumber: "Agoda",
    status: "Parsed_Success", processed_at: "2026-07-09T21:15:00", gmail_message_id: "18f29f0e5c6d7204",
    extracted_data: {
      no_reservasi: "AGD-88190", nama_tamu: "Sri Wahyuni", tipe_kamar: "Cottage",
      check_in: "2026-07-10T14:00:00", check_out: "2026-07-11T12:00:00",
      jumlah_tamu: 3, harga: 130000, status_pembayaran: "Dibatalkan",
    },
  },
  {
    id: "5", subjek: "Fwd: Detail Reservasi (format tidak dikenal)", pengirim: "reservasi.staff@gmail.com", sumber: "Lainnya",
    status: "Failed", processed_at: "2026-07-09T18:30:00", gmail_message_id: "18f29c2b4e5f6105",
    extracted_data: null,
    alasan: "Isi email tidak mengandung pola reservasi OTA yang dikenali (kemungkinan email diteruskan manual, bukan notifikasi asli OTA).",
  },
];

const EMAIL_STATUS_BADGE = {
  Parsed_Success: { label: "Berhasil Diproses", cls: "bg-emerald-100 text-emerald-800" },
  Manual_Required: { label: "Perlu Diproses Manual", cls: "bg-amber-100 text-amber-800" },
  Failed: { label: "Gagal", cls: "bg-red-100 text-red-800" },
};

// Layout utama halaman Otomasi Email & Pemesanan (Fase 2). Isi tiap tab (koneksi Gmail,
// log email, aturan pemetaan AI, proses manual) dibangun di task terpisah berikutnya —
// task ini hanya menyusun struktur navigasi & shell halamannya.
const TABS = [
  { value: "koneksi", label: "Hubungkan Gmail", icon: Mail },
  { value: "log", label: "Log Email Masuk", icon: Inbox },
  { value: "aturan", label: "Aturan Pemetaan AI", icon: Wand2 },
  { value: "manual", label: "Proses Manual", icon: FileWarning },
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

// Status koneksi Gmail — data tiruan. OAuth (Client ID/Secret) menyusul di task backend terpisah.
function KoneksiGmail() {
  const [connected, setConnected] = useState(false);
  const [email, setEmail] = useState("");

  const connect = () => {
    // Mock: nanti diganti alur OAuth Google (redirect ke consent screen).
    setConnected(true);
    setEmail("reservasi@pelangihomestay.com");
    toast.success("Gmail terhubung (mock) — reservasi@pelangihomestay.com");
  };

  const disconnect = () => {
    if (!window.confirm("Putuskan koneksi Gmail? Otomasi email OTA akan berhenti sampai dihubungkan lagi.")) return;
    setConnected(false);
    setEmail("");
    toast.success("Koneksi Gmail diputuskan");
  };

  return (
    <Card className="border-slate-200">
      <CardContent className="p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className={`w-11 h-11 rounded-xl grid place-items-center ${connected ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
            <Mail className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold" data-testid="gmail-status-label">
              {connected ? "Gmail Terhubung" : "Belum Terhubung"}
            </div>
            <div className="text-sm text-slate-500" data-testid="gmail-status-detail">
              {connected ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-700">
                  <CheckCircle2 className="w-3.5 h-3.5" /> {email}
                </span>
              ) : (
                "Hubungkan akun Gmail untuk membaca email reservasi OTA secara otomatis."
              )}
            </div>
          </div>
        </div>
        {connected ? (
          <Button data-testid="gmail-disconnect" variant="outline" onClick={disconnect} className="gap-1.5 text-red-600 border-red-300 hover:bg-red-50">
            <Unlink className="w-3.5 h-3.5" /> Putuskan
          </Button>
        ) : (
          <Button data-testid="gmail-connect" onClick={connect} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
            <Mail className="w-3.5 h-3.5" /> Hubungkan Gmail
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function LogEmailDetailDialog({ log, onClose }) {
  return (
    <Dialog open={!!log} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="email-log-detail-title">Detail Email</DialogTitle>
        </DialogHeader>
        {log && (
          <div className="space-y-3 text-sm" data-testid="email-log-detail-body">
            <div className="flex items-center gap-2">
              <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${EMAIL_STATUS_BADGE[log.status].cls}`}>
                {EMAIL_STATUS_BADGE[log.status].label}
              </span>
              <span className="text-[10px] uppercase font-bold px-2 py-1 rounded bg-slate-100 text-slate-600">{log.sumber}</span>
            </div>
            <div><span className="text-slate-500">Subjek:</span> <b>{log.subjek}</b></div>
            <div><span className="text-slate-500">Pengirim:</span> {log.pengirim}</div>
            <div><span className="text-slate-500">Diproses Pada:</span> {fmtDateTime(log.processed_at)}</div>
            {log.gmail_message_id && (
              <div><span className="text-slate-500">Gmail Message ID:</span> <span className="font-mono text-xs">{log.gmail_message_id}</span></div>
            )}

            {log.extracted_data ? (
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 mt-2 space-y-1.5">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Data Hasil Ekstraksi AI</p>
                <div><span className="text-slate-500">No. Reservasi:</span> <b>{log.extracted_data.no_reservasi}</b></div>
                <div><span className="text-slate-500">Nama Tamu:</span> {log.extracted_data.nama_tamu}</div>
                <div><span className="text-slate-500">Tipe Kamar:</span> {log.extracted_data.tipe_kamar}</div>
                <div><span className="text-slate-500">Check-in:</span> {fmtDateTime(log.extracted_data.check_in)}</div>
                <div><span className="text-slate-500">Check-out:</span> {fmtDateTime(log.extracted_data.check_out)}</div>
                <div><span className="text-slate-500">Jumlah Tamu:</span> {log.extracted_data.jumlah_tamu}</div>
                <div className="flex justify-between pt-1 border-t border-slate-200 mt-1">
                  <span className="font-bold">Harga</span><b className="text-blue-700">{fmtRp(log.extracted_data.harga)}</b>
                </div>
                <div><span className="text-slate-500">Status Pembayaran:</span> {log.extracted_data.status_pembayaran}</div>
              </div>
            ) : (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mt-2 flex gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                <p className="text-amber-800">{log.alasan || "AI tidak berhasil mengekstrak data reservasi dari email ini."}</p>
              </div>
            )}
            <p className="text-[11px] text-slate-400 pt-1">Data tiruan — belum tersambung ke Gmail sungguhan.</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function LogEmail() {
  const [selected, setSelected] = useState(null);
  return (
    <Card className="border-slate-200">
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm" data-testid="email-log-table">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left p-3">Subjek</th>
              <th className="text-left p-3">Pengirim</th>
              <th className="text-left p-3">Sumber</th>
              <th className="text-left p-3">Diproses Pada</th>
              <th className="text-left p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {MOCK_EMAIL_LOGS.map((e) => {
              const badge = EMAIL_STATUS_BADGE[e.status];
              return (
                <tr
                  key={e.id}
                  data-testid={`email-log-row-${e.id}`}
                  onClick={() => setSelected(e)}
                  className="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                >
                  <td className="p-3 font-medium">{e.subjek}</td>
                  <td className="p-3 text-slate-500">{e.pengirim}</td>
                  <td className="p-3">{e.sumber}</td>
                  <td className="p-3">{fmtDateTime(e.processed_at)}</td>
                  <td className="p-3">
                    <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${badge.cls}`}>{badge.label}</span>
                  </td>
                </tr>
              );
            })}
            {MOCK_EMAIL_LOGS.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-slate-500">Belum ada email yang diproses</td></tr>
            )}
          </tbody>
        </table>
      </CardContent>
      <LogEmailDetailDialog log={selected} onClose={() => setSelected(null)} />
    </Card>
  );
}

export default function OtomasiEmail() {
  return (
    <div className="space-y-6" data-testid="otomasi-email-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Otomasi Email &amp; Pemesanan</h1>
        <p className="text-slate-500 mt-1">
          Baca email konfirmasi OTA secara otomatis dan buat reservasi tanpa input manual.
        </p>
      </div>

      <Tabs defaultValue="koneksi">
        <TabsList data-testid="otomasi-email-tabs">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} data-testid={`tab-${t.value}`} className="gap-1.5">
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="koneksi" className="mt-4">
          <KoneksiGmail />
        </TabsContent>
        <TabsContent value="log" className="mt-4">
          <LogEmail />
        </TabsContent>
        {TABS.filter((t) => !["koneksi", "log"].includes(t.value)).map((t) => (
          <TabsContent key={t.value} value={t.value} className="mt-4">
            <TabPlaceholder label={t.label} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
