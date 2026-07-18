import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Ban, Check, X, Send } from "lucide-react";

const STATUS_LABEL = { requested: "Menunggu Persetujuan", pending: "Disetujui — Menunggu Refund", refund_sent: "Refund Terkirim" };
const STATUS_CLS = {
  requested: "bg-blue-100 text-blue-700",
  pending: "bg-amber-100 text-amber-700",
  refund_sent: "bg-emerald-100 text-emerald-700",
};

function PembatalanCard({ b, onChanged, compact }) {
  const [busy, setBusy] = useState(false);

  const approve = async () => {
    setBusy(true);
    try {
      await api.post(`/cancellation-requests/${b.id}/approve`);
      toast.success(`Pembatalan ${b.kode} disetujui`);
      onChanged();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setBusy(false); }
  };

  const reject = async () => {
    if (!window.confirm(`Tolak permintaan pembatalan ${b.kode}?`)) return;
    setBusy(true);
    try {
      await api.post(`/cancellation-requests/${b.id}/reject`, {});
      toast.success(`Permintaan pembatalan ${b.kode} ditolak`);
      onChanged();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setBusy(false); }
  };

  const refundSent = async () => {
    if (!window.confirm(`Konfirmasi refund ${b.kode} (${fmtRp(b.refund_amount)}) sudah ditransfer manual ke tamu? Tamu akan otomatis dikirim WA konfirmasi.`)) return;
    setBusy(true);
    try {
      await api.post(`/cancellation-requests/${b.id}/refund-sent`);
      toast.success(`Refund ${b.kode} ditandai terkirim & konfirmasi WA dikirim`);
      onChanged();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setBusy(false); }
  };

  return (
    <Card className="border-slate-200" data-testid={`pembatalan-card-${b.id}`}>
      <CardContent className={compact ? "p-3" : "p-4"}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold">{b.nama_tamu}</span>
              <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${STATUS_CLS[b.cancel_request_status]}`}>{STATUS_LABEL[b.cancel_request_status] || b.cancel_request_status}</span>
            </div>
            <div className="text-xs text-slate-500 mt-0.5">{b.kode} · Kamar {b.room_nomor} ({b.room_tipe}) · HP {b.no_hp}</div>
            <div className="text-xs text-slate-500">{b.cancel_policy_label}</div>
            <div className="text-sm mt-1">
              Estimasi refund: <b>{fmtRp(b.refund_amount)}</b>
              {b.cancel_requested_reason && <span className="text-slate-500"> · Alasan: {b.cancel_requested_reason}</span>}
            </div>
            {b.cancel_requested_at && <div className="text-[11px] text-slate-400 mt-1">Diajukan {fmtDateTime(b.cancel_requested_at)}</div>}
          </div>
          <div className="flex gap-2 shrink-0">
            {b.cancel_request_status === "requested" && (
              <>
                <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" disabled={busy} onClick={approve}>
                  <Check className="w-3.5 h-3.5 mr-1" /> Setujui
                </Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={reject}>
                  <X className="w-3.5 h-3.5 mr-1" /> Tolak
                </Button>
              </>
            )}
            {b.cancel_request_status === "pending" && (
              <Button size="sm" className="bg-amber-600 hover:bg-amber-700" disabled={busy} onClick={refundSent}>
                <Send className="w-3.5 h-3.5 mr-1" /> Sudah Dikirim
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function PembatalanAlert() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/cancellation-requests");
      setItems(data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal memuat permintaan pembatalan"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  if (!loading && items.length === 0) return null;

  return (
    <div className="rounded-xl bg-rose-50 border border-rose-200 p-4" data-testid="pembatalan-alert">
      <div className="flex items-start gap-3 mb-3">
        <Ban className="w-5 h-5 text-rose-600 mt-0.5 shrink-0" />
        <div className="text-sm">
          <div className="font-semibold text-rose-900">{items.length} Permintaan Pembatalan</div>
          <div className="text-rose-700">Dari AI WhatsApp — tinjau kebijakan refund, setujui/tolak, atau tandai refund sudah dikirim.</div>
        </div>
      </div>
      {loading ? <p className="text-xs text-rose-700">Memuat…</p> : (
        <div className="space-y-2">
          {items.map((b) => <PembatalanCard key={b.id} b={b} onChanged={load} compact />)}
        </div>
      )}
    </div>
  );
}

export default function Pembatalan() {
  const [items, setItems] = useState([]);
  const [tab, setTab] = useState("aktif");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/cancellation-requests", { params: tab === "riwayat" ? { status: "riwayat" } : {} });
      setItems(tab === "riwayat" ? data.filter((b) => b.cancel_request_status === "refund_sent") : data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal memuat"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Business Platform</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Pembatalan Booking</h1>
        <p className="text-slate-500 mt-1">Permintaan pembatalan dari AI WhatsApp (non-binding) — tinjau, setujui/tolak, lalu tandai refund terkirim setelah transfer manual.</p>
      </div>

      <div className="flex gap-2 flex-wrap">
        <Button size="sm" variant={tab === "aktif" ? "default" : "outline"} className={tab === "aktif" ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setTab("aktif")}>Aktif</Button>
        <Button size="sm" variant={tab === "riwayat" ? "default" : "outline"} className={tab === "riwayat" ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setTab("riwayat")}>Riwayat</Button>
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="text-center text-slate-500 py-10">Memuat…</div>
        ) : items.length === 0 ? (
          <Card className="border-slate-200"><CardContent className="p-6 text-center text-slate-500 text-sm">Tidak ada data</CardContent></Card>
        ) : (
          items.map((b) => <PembatalanCard key={b.id} b={b} onChanged={load} />)
        )}
      </div>
    </div>
  );
}
