import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtDateTime, fmtRp } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Copy, ExternalLink, Check, X, AlertOctagon } from "lucide-react";

const STATUS_LABEL = {
  waiting_approval: "Menunggu Persetujuan",
  waiting_payment: "Menunggu Pembayaran",
  lunas: "Lunas",
  rejected: "Ditolak",
};
const STATUS_CLS = {
  waiting_approval: "bg-amber-100 text-amber-800",
  waiting_payment: "bg-blue-100 text-blue-800",
  lunas: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
};
const BOOKING_STATUS_LABEL = {
  booking_pending: "Menunggu Bayar", booking_paid: "Lunas", checked_in: "Sudah Check-in",
  cancelled: "Dibatalkan", no_show: "No-Show",
};
const SYNC_STATUS_LABEL = {
  waiting_reddoorz_input: "Menunggu Input RedDoorz", waiting_reddoorz_sync: "Menunggu Sinkron RedDoorz",
  synced: "Confirmed (RedDoorz)", not_required: null,
};
const SYNC_STATUS_CLS = {
  waiting_reddoorz_input: "bg-amber-100 text-amber-800",
  waiting_reddoorz_sync: "bg-blue-100 text-blue-800",
  synced: "bg-emerald-100 text-emerald-700",
};

// Untuk booking Menginap yang lunas, badge utama menampilkan progres RedDoorz (bukan cuma
// "Lunas" generik) — supaya di tab Riwayat langsung kelihatan mana yang SUDAH diklik "Sudah
// Input ke RedDoorz" (bukan seperti hilang begitu saja dari Action Required) vs yang masih
// menunggu vs yang sudah benar-benar Confirmed. Data booking_request-nya sendiri TIDAK
// PERNAH dihapus oleh aksi itu — ini murni supaya statusnya lebih jelas di Riwayat.
function badgeInfo(it) {
  if (it.status_efektif === "lunas" && it.booking_ringkasan?.length) {
    const sync = it.booking_ringkasan[0].sync_status;
    if (sync && sync !== "not_required" && SYNC_STATUS_LABEL[sync]) {
      return { label: SYNC_STATUS_LABEL[sync], cls: SYNC_STATUS_CLS[sync] };
    }
  }
  const key = it.status_efektif || it.status;
  return { label: STATUS_LABEL[key] || it.status, cls: STATUS_CLS[key] || "bg-slate-100 text-slate-600" };
}

// Dialog Setujui — staf memilih kamar spesifik SETELAH cek ketersediaan (termasuk cek
// silang manual ke PMS RedDoorz, sesuatu yang tidak bisa dicek otomatis oleh sistem ini),
// lalu sistem langsung membuat booking sungguhan + link bayar Tripay & mengirimkannya ke
// tamu via WhatsApp (lihat POST /booking-requests/{id}/approve di backend).
export function SetujuiDialog({ req, onOpenChange, onApproved }) {
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
    // Default ke preferensi yang tamu SENDIRI sebutkan di WhatsApp (kalau ada) — staf tetap
    // bisa ubah manual, ini cuma default supaya tidak ketinggalan/salah pilih dari yang diminta.
    setOpsi(req.payment_option_diminta || "dp50");
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
      onApproved(); // refresh daftar di belakang layar — dialog tetap terbuka menampilkan link bayar
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
          <DialogTitle>Terima Permintaan {req.kode}</DialogTitle>
        </DialogHeader>
        {!hasil ? (
          <div className="space-y-3 text-sm">
            <div className="bg-slate-50 border border-slate-200 rounded p-2 text-xs space-y-0.5">
              <div><b>{req.nama_tamu}</b> — {req.no_hp}</div>
              <div>{req.tipe === "menginap" ? "Menginap" : "Day Use"} · {req.room_tipe || "(tipe bebas)"} · {butuh} kamar · {req.jumlah_tamu} tamu</div>
              <div>Check-in {req.tanggal_checkin}{req.jam_checkin ? ` ${req.jam_checkin}` : ""}{req.tanggal_checkout ? ` — Check-out ${req.tanggal_checkout}` : ""}</div>
              {req.payment_option_diminta && (
                <div className="text-blue-700 font-semibold">Tamu minta: {req.payment_option_diminta === "dp50" ? "DP 50%" : "Bayar Penuh"}</div>
              )}
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
              {submitting ? "Menerima…" : "Terima & Kirim Link Bayar"}
            </Button>
          ) : (
            <Button onClick={() => onOpenChange(false)} className="bg-blue-700 hover:bg-blue-800">Selesai</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function TolakDialog({ req, onOpenChange, onDone }) {
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

export function ActionRequiredRedDoorz() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/bookings", { params: { sync_status: "waiting_reddoorz_input" } });
      setItems(data.filter((b) => b.payment_status === "paid"));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal memuat daftar Action Required");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const tandaiSelesai = async (b) => {
    setBusyId(b.id);
    try {
      await api.post(`/bookings/${b.id}/reddoorz-input-selesai`);
      toast.success(`Booking ${b.kode} ditandai sudah diinput ke RedDoorz`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal");
    } finally {
      setBusyId(null);
    }
  };

  if (!loading && items.length === 0) return null;

  return (
    <div className="rounded-xl bg-amber-50 border border-amber-200 p-4">
      <div className="flex items-start gap-3 mb-3">
        <AlertOctagon className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
        <div className="text-sm">
          <div className="font-semibold text-amber-900">Action Required — Perlu Input ke PMS RedDoorz</div>
          <div className="text-amber-700">Booking Menginap ini sudah lunas — input manual ke PMS RedDoorz, lalu tandai selesai di sini. Baru dianggap "Confirmed" setelah email konfirmasi RedDoorz diterima.</div>
        </div>
      </div>
      {loading ? (
        <p className="text-xs text-amber-700">Memuat…</p>
      ) : (
        <div className="space-y-2">
          {items.map((b) => (
            <div key={b.id} className="flex items-center justify-between gap-3 bg-white border border-amber-100 rounded-lg p-2.5 text-sm">
              <div>
                <div className="font-semibold">{b.nama_tamu} — Kamar {b.room_nomor} ({b.room_tipe})</div>
                <div className="text-xs text-slate-500">{b.kode} · check-in {fmtDateTime(b.jam_mulai)}</div>
              </div>
              <Button size="sm" className="bg-amber-600 hover:bg-amber-700 shrink-0" disabled={busyId === b.id} onClick={() => tandaiSelesai(b)}>
                {busyId === b.id ? "Menyimpan…" : "Sudah Input ke RedDoorz"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
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
      // "riwayat" bukan status asli — gabungan permintaan yang SUDAH selesai diproses
      // (lunas + ditolak), diambil semua lalu disaring di sini pakai status_efektif
      // (backend menghitungnya dari status booking sungguhan yang terkait, karena
      // booking_requests.status sendiri berhenti di "waiting_payment" walau tamu sudah bayar).
      const params = statusFilter === "riwayat" ? {} : { status: statusFilter || undefined };
      const { data } = await api.get("/booking-requests", { params });
      setItems(statusFilter === "riwayat" ? data.filter((it) => ["lunas", "rejected"].includes(it.status_efektif)) : data);
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

      <ActionRequiredRedDoorz />

      <div className="flex gap-2 flex-wrap">
        {[["waiting_approval", "Menunggu Persetujuan"], ["waiting_payment", "Menunggu Pembayaran"], ["riwayat", "Riwayat"], ["", "Semua"]].map(([k, lbl]) => (
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
                  <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full shrink-0 ${badgeInfo(it).cls}`}>
                    {badgeInfo(it).label}
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
                {it.payment_option_diminta && (
                  <p className="text-xs text-blue-700 font-semibold">Tamu minta: {it.payment_option_diminta === "dp50" ? "DP 50%" : "Bayar Penuh"}</p>
                )}
                {it.catatan && <p className="text-xs italic text-slate-500">"{it.catatan}"</p>}
                {it.status === "waiting_payment" && it.status_efektif !== "lunas" && it.checkout_url && (
                  <a href={it.checkout_url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 underline break-all">Link pembayaran</a>
                )}
                {it.status === "rejected" && it.rejected_reason && (
                  <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded p-2">Alasan ditolak: {it.rejected_reason}</p>
                )}
                {it.booking_ringkasan && (
                  <div className="text-xs bg-slate-50 border border-slate-200 rounded p-2 space-y-1.5">
                    {it.booking_ringkasan.map((b) => (
                      <div key={b.kode}>
                        <div className="flex flex-wrap items-center gap-x-2">
                          <span className="font-semibold">Kamar {b.room_nomor}</span>
                          <span className="text-slate-400">({b.room_tipe})</span>
                          <span>{BOOKING_STATUS_LABEL[b.status] || b.status}</span>
                          {SYNC_STATUS_LABEL[b.sync_status] && (
                            <span className="text-amber-700">· {SYNC_STATUS_LABEL[b.sync_status]}</span>
                          )}
                        </div>
                        {b.total != null && (
                          <div className="text-slate-600 mt-0.5">
                            Total {fmtRp(b.total)}
                            {b.payment_option && <span className="text-slate-400"> ({b.payment_option === "dp50" ? "DP 50%" : "Lunas"})</span>}
                            {" · "}Sudah dibayar <b className="text-emerald-700">{fmtRp(b.jumlah_dibayar)}</b>
                            {b.sisa_tagihan > 0 ? (
                              <> · Sisa <b className="text-red-600">{fmtRp(b.sisa_tagihan)}</b> (dibayar di lokasi)</>
                            ) : (
                              <> · <b className="text-emerald-700">Lunas</b></>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {it.approved_by && <div className="text-[11px] text-slate-400">Diterima oleh {it.approved_by} · {fmtDateTime(it.approved_at)}</div>}
                {it.rejected_by && <div className="text-[11px] text-slate-400">Ditolak oleh {it.rejected_by} · {fmtDateTime(it.rejected_at)}</div>}
                <div className="text-[11px] text-slate-400">{it.kode} · diajukan {fmtDateTime(it.created_at)}</div>
                {it.status === "waiting_approval" && (
                  <div className="flex gap-2 pt-1">
                    <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => setApproveTarget(it)}>
                      <Check className="w-3.5 h-3.5 mr-1" /> Terima
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

      <SetujuiDialog req={approveTarget} onOpenChange={(o) => { if (!o) setApproveTarget(null); }} onApproved={load} />
      <TolakDialog req={rejectTarget} onOpenChange={(o) => { if (!o) setRejectTarget(null); }} onDone={() => { setRejectTarget(null); load(); }} />
    </div>
  );
}
