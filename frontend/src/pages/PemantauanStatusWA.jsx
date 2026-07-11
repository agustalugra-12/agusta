import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Send, CheckCircle2, XCircle, Timer, AlertTriangle, MessageSquare, RefreshCw, BarChart3, History, Wifi, WifiOff } from "lucide-react";
import api, { fmtDateTime } from "@/lib/apiClient";

// Dasbor kesehatan pengiriman pesan bot WhatsApp (fokus status/infrastruktur), beda
// dengan tab "Log Percakapan" di PesanWhatsAppOtomatis.jsx yang menampilkan ISI percakapan
// (pesan masuk + balasan AI). Halaman ini fokus deteksi kegagalan integrasi.

const STATUS_META = {
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
              <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${STATUS_META[pesan.status] || "bg-slate-100 text-slate-600"}`}>{pesan.status}</span>
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

export default function PemantauanStatusWA() {
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
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Pemantauan Status</h1>
        <p className="text-slate-500 mt-1">
          Status pengiriman/penerimaan pesan bot WhatsApp &amp; deteksi kegagalan integrasi.
        </p>
      </div>

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
                      <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${STATUS_META[d.status] || "bg-slate-100 text-slate-600"}`}>{d.status}</span>
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
