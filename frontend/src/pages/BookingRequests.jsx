import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtDateTime, fmtRp } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Copy, ExternalLink, Check, X } from "lucide-react";

const STATUS_LABEL = {
  waiting_approval: "Menunggu Persetujuan",
  waiting_payment: "Menunggu Pembayaran",
  rejected: "Ditolak",
};
const STATUS_CLS = {
  waiting_approval: "bg-amber-100 text-amber-800",
  waiting_payment: "bg-blue-100 text-blue-800",
  rejected: "bg-red-100 text-red-700",
};

// Dialog Setujui — staf memilih kamar spesifik SETELAH cek ketersediaan (termasuk cek
// silang manual ke PMS RedDoorz, sesuatu yang tidak bisa dicek otomatis oleh sistem ini),
// lalu sistem langsung membuat booking sungguhan + link bayar Tripay & mengirimkannya ke
// tamu via WhatsApp (lihat POST /booking-requests/{id}/approve di backend).
function SetujuiDialog({ req, onOpenChange, onDone }) {
  const [rooms, setRooms] = useState([]);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState([]);
  const [method, setMethod] = useState("");
  const [opsi, setOpsi] = useState("dp50");
  const [hasil, setHasil] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!req) return;
    setLoading(true);
    setError(""); setSelected([]); setHasil(null);
    const params = { tanggal: req.tanggal_checkin, tipe: req.room_tipe || undefined };
    if (req.tipe === "menginap" && req.tanggal_checkout) params.checkout = req.tanggal_checkout;
    Promise.all([
      api.get("/public/availability", { params }),
      api.get("/payments/tripay/channels"),
    ])
      .then(([rRes, cRes]) => {
        setRooms(rRes.data.rooms || []);
        setChannels(cRes.data);
        setMethod(cRes.data[0]?.code || "");
      })
      .catch((e) => setError(e?.response?.data?.detail || "Gagal memuat ketersediaan kamar/channel Tripay"))
      .finally(() => setLoading(false));
  }, [req]);

  if (!req) return null;
  const butuh = req.jumlah_kamar || 1;

  const toggleRoom = (id) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= butuh) return prev; // sudah cukup, jangan tambah lagi
      return [...prev, id];
    });
  };

  const setujui = async () => {
    if (selected.length !== butuh || !method) return;
    setSubmitting(true);
    setError("");
    try {
      const { data } = await api.post(`/booking-requests/${req.id}/approve`, {
        room_ids: selected, payment_option: opsi, method,
      });
      setHasil(data);
      onDone();
    } catch (e) {
      setError(e?.response?.data?.detail || "Gagal menyetujui permintaan");
    } finally {
      setSubmitting(false);
    }
  };

  const salinLink = () => {
    navigator.clipboard?.writeText(hasil.checkout_url);
    toast.success("Link pembayaran disalin");
  };

  return (
    <Dialog open={!!req} onOpenChange={(o) => { if (!o) onOpenChange(false); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Setujui Permintaan {req.kode}</DialogTitle>
        </DialogHeader>
        {!hasil ? (
          <div className="space-y-3 text-sm">
            <div className="bg-slate-50 border border-slate-200 rounded p-2 text-xs space-y-0.5">
              <div><b>{req.nama_tamu}</b> — {req.no_hp}</div>
              <div>{req.tipe === "menginap" ? "Menginap" : "Day Use"} · {req.room_tipe || "(tipe bebas)"} · {butuh} kamar · {req.jumlah_tamu} tamu</div>
              <div>Check-in {req.tanggal_checkin}{req.jam_checkin ? ` ${req.jam_checkin}` : ""}{req.tanggal_checkout ? ` — Check-out ${req.tanggal_checkout}` : ""}</div>
              {req.catatan && <div className="italic text-slate-500">"{req.catatan}"</div>}
            </div>

            {loading ? (
              <p className="text-slate-400 text-xs">Memuat ketersediaan kamar…</p>
            ) : (
              <div>
                <Label>Pilih {butuh} kamar ({selected.length}/{butuh} dipilih)</Label>
                <p className="text-[11px] text-slate-400 mb-1.5">Pastikan juga sudah dicek tidak bentrok di PMS RedDoorz — sistem ini hanya tahu data PMS Pelangi sendiri.</p>
                {rooms.length === 0 ? (
                  <p className="text-red-600 text-xs">Tidak ada kamar {req.room_tipe || ""} tersedia pada tanggal ini di PMS Pelangi.</p>
                ) : (
                  <div className="grid grid-cols-4 gap-1.5">
                    {rooms.map((r) => (
                      <button
                        key={r.id} type="button" onClick={() => toggleRoom(r.id)}
                        className={`p-2 rounded-lg border-2 text-xs font-semibold ${selected.includes(r.id) ? "border-blue-600 bg-blue-50" : "border-slate-200"}`}
                      >
                        {r.nomor}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {!loading && channels.length > 0 && (
              <>
                <div>
                  <Label>Channel Pembayaran</Label>
                  <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5">
                    {channels.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                  </select>
                </div>
                <div>
                  <Label>Opsi Bayar</Label>
                  <div className="grid grid-cols-2 gap-2 mt-1.5">
                    <button type="button" onClick={() => setOpsi("dp50")} className={`p-2.5 rounded-lg border-2 text-left text-xs ${opsi === "dp50" ? "border-blue-600 bg-blue-50" : "border-slate-200"}`}>
                      <div className="font-semibold">DP 50%</div>
                    </button>
                    <button type="button" onClick={() => setOpsi("full")} className={`p-2.5 rounded-lg border-2 text-left text-xs ${opsi === "full" ? "border-blue-600 bg-blue-50" : "border-slate-200"}`}>
                      <div className="font-semibold">Lunas</div>
                    </button>
                  </div>
                </div>
              </>
            )}
            {error && <p className="text-red-600 text-xs">{error}</p>}
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <p className="text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-2">Disetujui — link pembayaran sudah dikirim ke tamu via WhatsApp.</p>
            <div className="flex items-center gap-2">
              <input readOnly value={hasil.checkout_url || ""} className="flex-1 h-10 rounded-md border border-slate-300 px-3 font-mono text-xs" />
              <Button variant="outline" size="icon" onClick={salinLink}><Copy className="w-3.5 h-3.5" /></Button>
              <Button variant="outline" size="icon" asChild>
                <a href={hasil.checkout_url} target="_blank" rel="noreferrer"><ExternalLink className="w-3.5 h-3.5" /></a>
              </Button>
            </div>
          </div>
        )}
        <DialogFooter>
          {!hasil ? (
            <Button onClick={setujui} disabled={selected.length !== butuh || !method || submitting} className="bg-blue-700 hover:bg-blue-800">
              {submitting ? "Menyetujui…" : "Setujui & Kirim Link Bayar"}
            </Button>
          ) : (
            <Button onClick={() => onOpenChange(false)} className="bg-blue-700 hover:bg-blue-800">Selesai</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TolakDialog({ req, onOpenChange, onDone }) {
  const [alasan, setAlasan] = useState("");
  const [submitting, setSubmitting] = useState(false);
  if (!req) return null;

  const tolak = async () => {
    setSubmitting(true);
    try {
      await api.post(`/booking-requests/${req.id}/reject`, { alasan });
      toast.success("Permintaan ditolak, tamu sudah diberi tahu");
      setAlasan("");
      onDone();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menolak permintaan");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={!!req} onOpenChange={(o) => { if (!o) onOpenChange(false); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>Tolak Permintaan {req.kode}</DialogTitle></DialogHeader>
        <div className="space-y-2 text-sm">
          <Label>Alasan (dikirim ke tamu, opsional)</Label>
          <Textarea value={alasan} onChange={(e) => setAlasan(e.target.value)} placeholder="Mis: Kamar penuh di tanggal tersebut" rows={3} />
        </div>
        <DialogFooter>
          <Button onClick={tolak} disabled={submitting} variant="destructive">{submitting ? "Menolak…" : "Tolak Permintaan"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function BookingRequests() {
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("waiting_approval");
  const [loading, setLoading] = useState(true);
  const [approveTarget, setApproveTarget] = useState(null);
  const [rejectTarget, setRejectTarget] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/booking-requests", { params: { status: statusFilter || undefined } });
      setItems(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal memuat permintaan booking");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Reservasi</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Booking Request</h1>
        <p className="text-slate-500 text-sm mt-1">Permintaan booking dari AI WhatsApp — tinjau ketersediaan lalu setujui/tolak sebelum tamu diberi link pembayaran.</p>
      </div>

      <div className="flex gap-2 flex-wrap">
        {[["waiting_approval", "Menunggu Persetujuan"], ["waiting_payment", "Menunggu Pembayaran"], ["rejected", "Ditolak"], ["", "Semua"]].map(([k, lbl]) => (
          <Button key={k} size="sm" variant={statusFilter === k ? "default" : "outline"} className={statusFilter === k ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setStatusFilter(k)}>{lbl}</Button>
        ))}
      </div>

      {loading ? (
        <p className="text-slate-400 text-sm">Memuat…</p>
      ) : items.length === 0 ? (
        <div className="text-center text-slate-500 py-10">Tidak ada permintaan booking</div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {items.map((it) => (
            <Card key={it.id} className="border-slate-200">
              <CardContent className="p-4 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="font-bold">{it.nama_tamu}</div>
                  <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full shrink-0 ${STATUS_CLS[it.status] || "bg-slate-100 text-slate-600"}`}>
                    {STATUS_LABEL[it.status] || it.status}
                  </span>
                </div>
                <div className="text-xs text-slate-500">{it.no_hp}</div>
                <div className="text-sm">
                  {it.tipe === "menginap" ? "Menginap" : "Day Use"} · {it.room_tipe || "(tipe bebas)"} · {it.jumlah_kamar}x kamar · {it.jumlah_tamu} tamu
                </div>
                <div className="text-xs text-slate-500">
                  Check-in {it.tanggal_checkin}{it.jam_checkin ? ` ${it.jam_checkin}` : ""}
                  {it.tanggal_checkout ? ` — Check-out ${it.tanggal_checkout}` : ""}
                </div>
                {it.catatan && <p className="text-xs italic text-slate-500">"{it.catatan}"</p>}
                {it.status === "waiting_payment" && it.checkout_url && (
                  <a href={it.checkout_url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 underline break-all">Link pembayaran</a>
                )}
                {it.status === "rejected" && it.rejected_reason && (
                  <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded p-2">Alasan: {it.rejected_reason}</p>
                )}
                <div className="text-[11px] text-slate-400">{it.kode} · {fmtDateTime(it.created_at)}</div>
                {it.status === "waiting_approval" && (
                  <div className="flex gap-2 pt-1">
                    <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => setApproveTarget(it)}>
                      <Check className="w-3.5 h-3.5 mr-1" /> Setujui
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setRejectTarget(it)}>
                      <X className="w-3.5 h-3.5 mr-1" /> Tolak
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <SetujuiDialog req={approveTarget} onOpenChange={(o) => { if (!o) setApproveTarget(null); }} onDone={() => { setApproveTarget(null); load(); }} />
      <TolakDialog req={rejectTarget} onOpenChange={(o) => { if (!o) setRejectTarget(null); }} onDone={() => { setRejectTarget(null); load(); }} />
    </div>
  );
}
