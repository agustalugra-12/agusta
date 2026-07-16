import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Search, X, CreditCard, Plus, Copy, ExternalLink } from "lucide-react";
import api, { fmtDateTime, fmtRp } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";

const STATUS_META = {
  settlement: { label: "Lunas", cls: "bg-emerald-100 text-emerald-800" },
  capture: { label: "Lunas", cls: "bg-emerald-100 text-emerald-800" },
  pending: { label: "Menunggu Pembayaran", cls: "bg-amber-100 text-amber-800" },
  initiated: { label: "Baru Dibuat", cls: "bg-slate-200 text-slate-600" },
  expire: { label: "Kedaluwarsa", cls: "bg-red-100 text-red-800" },
  cancel: { label: "Dibatalkan", cls: "bg-slate-200 text-slate-600" },
  deny: { label: "Ditolak", cls: "bg-red-100 text-red-800" },
  refund: { label: "Refund", cls: "bg-violet-100 text-violet-800" },
};

const STATUS_OPTIONS = ["Semua", "settlement", "pending", "expire", "deny", "cancel", "refund"];
const UBAH_STATUS_OPTIONS = ["settlement", "pending", "expire", "deny", "cancel", "refund"];

// Dialog "Buat Tagihan Baru" — alur bayar dari sisi staf (bukan tamu): pilih booking yang
// belum lunas (mis. reservasi telepon/WA yang dicatat lewat Quick Book, atau booking publik
// yang belum sempat bayar) + channel Tripay + opsi DP50/Lunas, lalu benar-benar memanggil
// POST /payments/tripay/create-transaction — hasilnya link pembayaran Tripay sungguhan
// (checkout_url) yang bisa dikirim ke tamu lewat WA. Kredensial Tripay saat ini masih
// sandbox (lihat GET /payments/tripay/config); begitu Tripay approve kredensial produksi,
// staf ops tinggal ganti env var di server — tidak ada perubahan kode di sini.
function BuatTagihanDialog({ open, onOpenChange, onCreated }) {
  const [bookings, setBookings] = useState([]);
  const [channels, setChannels] = useState([]);
  const [loadingOpts, setLoadingOpts] = useState(false);
  const [bookingId, setBookingId] = useState("");
  const [method, setMethod] = useState("");
  const [opsi, setOpsi] = useState("dp50");
  const [hasil, setHasil] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setLoadingOpts(true);
    setError("");
    Promise.all([
      api.get("/payments/bookings-status", { params: { status_bayar: "belum_bayar" } }),
      api.get("/payments/tripay/channels"),
    ])
      .then(([bRes, cRes]) => {
        setBookings(bRes.data);
        setBookingId(bRes.data[0]?.id || "");
        setChannels(cRes.data);
        setMethod(cRes.data[0]?.code || "");
      })
      .catch((e) => setError(e?.response?.data?.detail || "Gagal memuat daftar booking/channel Tripay"))
      .finally(() => setLoadingOpts(false));
  }, [open]);

  const booking = bookings.find((b) => b.id === bookingId);
  const dpMin = booking ? (booking.dp_min || Math.round(booking.total * 0.5)) : 0;
  const nominal = booking ? (opsi === "dp50" ? dpMin : booking.total) : 0;

  const buatTagihan = async () => {
    if (!booking || !method) return;
    setSubmitting(true);
    setError("");
    try {
      const { data } = await api.post("/payments/tripay/create-transaction", {
        booking_id: booking.id, payment_option: opsi, method,
      });
      setHasil(data);
      onCreated();
    } catch (e) {
      setError(e?.response?.data?.detail || "Gagal membuat tagihan Tripay");
    } finally {
      setSubmitting(false);
    }
  };

  const salinLink = () => {
    navigator.clipboard?.writeText(hasil.checkout_url);
    toast.success("Link pembayaran disalin");
  };

  const tutup = () => { setHasil(null); setError(""); onOpenChange(false); };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) tutup(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="buat-tagihan-title">Buat Tagihan Baru</DialogTitle>
        </DialogHeader>
        {!hasil ? (
          <div className="space-y-3 text-sm">
            {loadingOpts ? (
              <p className="text-slate-400 text-xs">Memuat daftar booking &amp; channel Tripay…</p>
            ) : bookings.length === 0 ? (
              <p className="text-slate-500 text-xs">Tidak ada reservasi yang belum bayar saat ini.</p>
            ) : (
              <>
                <div>
                  <Label>Booking</Label>
                  <select
                    data-testid="tagihan-booking"
                    value={bookingId}
                    onChange={(e) => setBookingId(e.target.value)}
                    className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
                  >
                    {bookings.map((b) => <option key={b.id} value={b.id}>{b.kode} — {b.nama_tamu}</option>)}
                  </select>
                </div>
                <div>
                  <Label>Channel Pembayaran</Label>
                  <select
                    data-testid="tagihan-channel"
                    value={method}
                    onChange={(e) => setMethod(e.target.value)}
                    className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
                  >
                    {channels.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                  </select>
                </div>
                <div>
                  <Label>Metode Bayar</Label>
                  <div className="grid grid-cols-2 gap-2 mt-1.5">
                    <button
                      type="button"
                      data-testid="tagihan-opsi-dp50"
                      onClick={() => setOpsi("dp50")}
                      className={`p-2.5 rounded-lg border-2 text-left text-xs ${opsi === "dp50" ? "border-blue-600 bg-blue-50" : "border-slate-200"}`}
                    >
                      <div className="font-semibold">DP 50%</div>
                      <div className="text-slate-500">{booking && fmtRp(dpMin)}</div>
                    </button>
                    <button
                      type="button"
                      data-testid="tagihan-opsi-full"
                      onClick={() => setOpsi("full")}
                      className={`p-2.5 rounded-lg border-2 text-left text-xs ${opsi === "full" ? "border-blue-600 bg-blue-50" : "border-slate-200"}`}
                    >
                      <div className="font-semibold">Lunas</div>
                      <div className="text-slate-500">{booking && fmtRp(booking.total)}</div>
                    </button>
                  </div>
                </div>
                <div className="bg-slate-50 border border-slate-200 rounded p-2 flex justify-between">
                  <span className="font-bold">Total Ditagih</span><b className="text-blue-700">{fmtRp(nominal)}</b>
                </div>
              </>
            )}
            {error && <p className="text-red-600 text-xs">{error}</p>}
          </div>
        ) : (
          <div className="space-y-3 text-sm" data-testid="tagihan-hasil">
            <p className="text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-2">Tagihan Tripay dibuat — kirim tautan ini ke tamu untuk membayar.</p>
            <div className="flex items-center gap-2">
              <Input readOnly value={hasil.checkout_url} className="font-mono text-xs" data-testid="tagihan-link" />
              <Button variant="outline" size="icon" onClick={salinLink} data-testid="tagihan-salin-link"><Copy className="w-3.5 h-3.5" /></Button>
              <Button variant="outline" size="icon" asChild data-testid="tagihan-buka-link">
                <a href={hasil.checkout_url} target="_blank" rel="noreferrer"><ExternalLink className="w-3.5 h-3.5" /></a>
              </Button>
            </div>
            <p className="text-[11px] text-slate-400">Order ID: <span className="font-mono">{hasil.order_id}</span></p>
          </div>
        )}
        <DialogFooter>
          {!hasil ? (
            <Button data-testid="tagihan-buat" onClick={buatTagihan} disabled={!booking || !method || submitting} className="bg-blue-700 hover:bg-blue-800">
              {submitting ? "Membuat…" : "Buat Tagihan"}
            </Button>
          ) : (
            <Button data-testid="tagihan-selesai" onClick={tutup} className="bg-blue-700 hover:bg-blue-800">Selesai</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function Pembayaran() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [searchParams] = useSearchParams();
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  // Terima navigasi dari Daftar Reservasi (?kode=RSV-1042) — langsung filter ke booking itu.
  const [search, setSearch] = useState(searchParams.get("kode") || "");
  const [status, setStatus] = useState("Semua");
  const [selected, setSelected] = useState(null);
  const [tagihanOpen, setTagihanOpen] = useState(false);
  const [ubahStatus, setUbahStatus] = useState("");
  const [savingStatus, setSavingStatus] = useState(false);
  const [riwayat, setRiwayat] = useState([]);
  const [riwayatLoading, setRiwayatLoading] = useState(false);

  const muatTransaksi = () => {
    setLoading(true);
    api.get("/payments/log")
      .then(({ data }) => setTransactions(data))
      .catch(() => toast.error("Gagal memuat daftar transaksi pembayaran"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { muatTransaksi(); }, []);

  useEffect(() => {
    if (!selected?.booking_kode) { setRiwayat([]); return; }
    let cancelled = false;
    setRiwayatLoading(true);
    api.get(`/payments/log/by-booking/${selected.booking_kode}`)
      .then(({ data }) => { if (!cancelled) setRiwayat(data); })
      .catch(() => { if (!cancelled) setRiwayat([]); })
      .finally(() => { if (!cancelled) setRiwayatLoading(false); });
    return () => { cancelled = true; };
  }, [selected?.booking_kode]);

  const simpanUbahStatus = async () => {
    if (!selected || !ubahStatus || ubahStatus === selected.transaction_status) return;
    setSavingStatus(true);
    try {
      await api.put(`/payments/log/${selected.id}/status`, { status: ubahStatus });
      setTransactions((ts) => ts.map((t) => (t.id === selected.id ? { ...t, transaction_status: ubahStatus } : t)));
      setSelected((s) => ({ ...s, transaction_status: ubahStatus }));
      toast.success(`Status ${selected.order_id} diubah ke "${STATUS_META[ubahStatus]?.label || ubahStatus}"`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal mengubah status transaksi");
    } finally {
      setSavingStatus(false);
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return transactions.filter((t) => {
      if (q) {
        const hay = `${t.booking_kode || ""} ${t.nama_tamu || ""} ${t.order_id || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (status !== "Semua" && t.transaction_status !== status) return false;
      return true;
    });
  }, [transactions, search, status]);

  const resetFilters = () => { setSearch(""); setStatus("Semua"); };
  const hasActiveFilter = search || status !== "Semua";

  return (
    <div className="space-y-6" data-testid="pembayaran-page">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Pembayaran</h1>
          <p className="text-slate-500 mt-1">Daftar transaksi Tripay &amp; Midtrans dari semua reservasi (checkout tamu &amp; DP).</p>
        </div>
        <Button data-testid="buat-tagihan-buka" onClick={() => setTagihanOpen(true)} className="gap-1.5 bg-blue-700 hover:bg-blue-800 shrink-0">
          <Plus className="w-3.5 h-3.5" /> Buat Tagihan Baru
        </Button>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <Label htmlFor="pembayaran-search">Cari kode booking / tamu / order ID</Label>
            <div className="relative mt-1.5">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <Input
                id="pembayaran-search"
                data-testid="pembayaran-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Mis: RSV-1042, Dewi…"
                className="pl-9"
              />
            </div>
          </div>
          <div className="w-full sm:w-52">
            <Label htmlFor="pembayaran-status">Status</Label>
            <select
              id="pembayaran-status"
              data-testid="pembayaran-filter-status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s === "Semua" ? s : STATUS_META[s]?.label || s}</option>)}
            </select>
          </div>
          {hasActiveFilter && (
            <Button data-testid="pembayaran-reset-filter" variant="ghost" size="sm" onClick={resetFilters} className="gap-1.5">
              <X className="w-3.5 h-3.5" /> Reset
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm" data-testid="pembayaran-table">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Order ID</th>
                <th className="text-left p-3">Booking</th>
                <th className="text-left p-3">Nominal</th>
                <th className="text-left p-3">Metode</th>
                <th className="text-left p-3">Waktu</th>
                <th className="text-left p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => {
                const meta = STATUS_META[t.transaction_status] || { label: t.transaction_status, cls: "bg-slate-100 text-slate-600" };
                return (
                  <tr
                    key={t.id}
                    data-testid={`pembayaran-row-${t.id}`}
                    onClick={() => { setSelected(t); setUbahStatus(t.transaction_status); }}
                    className="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                  >
                    <td className="p-3 font-mono text-xs">{t.order_id}</td>
                    <td className="p-3 font-medium">{t.booking_kode} <span className="text-slate-400 font-normal">— {t.nama_tamu}</span></td>
                    <td className="p-3">{fmtRp(t.gross_amount)}</td>
                    <td className="p-3 uppercase text-xs text-slate-500">{t.payment_type}</td>
                    <td className="p-3">{fmtDateTime(t.created_at)}</td>
                    <td className="p-3">
                      <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${meta.cls}`}>{meta.label}</span>
                    </td>
                  </tr>
                );
              })}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-slate-500">Tidak ada transaksi yang cocok</td></tr>
              )}
              {loading && (
                <tr><td colSpan={6} className="p-6 text-center text-slate-400">Memuat transaksi…</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) setSelected(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle data-testid="pembayaran-detail-title" className="flex items-center gap-2">
              <CreditCard className="w-4 h-4" /> Detail Transaksi
            </DialogTitle>
          </DialogHeader>
          {selected && (
            <div className="space-y-2 text-sm" data-testid="pembayaran-detail-body">
              <div className="flex items-center gap-2">
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${(STATUS_META[selected.transaction_status] || {}).cls}`}>
                  {(STATUS_META[selected.transaction_status] || {}).label || selected.transaction_status}
                </span>
              </div>
              <div><span className="text-slate-500">Order ID:</span> <span className="font-mono text-xs">{selected.order_id}</span></div>
              <div><span className="text-slate-500">Booking:</span> <b>{selected.booking_kode}</b> — {selected.nama_tamu}</div>
              <div><span className="text-slate-500">Opsi Bayar:</span> {selected.payment_option === "dp50" ? "DP 50%" : "Lunas"}</div>
              <div><span className="text-slate-500">Metode:</span> <span className="uppercase">{selected.payment_type}</span></div>
              <div><span className="text-slate-500">Waktu:</span> {fmtDateTime(selected.created_at)}</div>
              <div className="bg-slate-50 border border-slate-200 rounded p-2 mt-2">
                <div className="flex justify-between"><span className="font-bold">Nominal</span><b className="text-blue-700">{fmtRp(selected.gross_amount)}</b></div>
              </div>

              {isOwner && (
                <div className="border-t border-slate-100 pt-3 mt-1">
                  <Label htmlFor="ubah-status">Ubah Status (manual, owner)</Label>
                  <div className="flex gap-2 mt-1.5">
                    <select
                      id="ubah-status"
                      data-testid="pembayaran-ubah-status"
                      value={ubahStatus}
                      onChange={(e) => setUbahStatus(e.target.value)}
                      className="flex-1 h-10 rounded-md border border-slate-300 px-3 bg-white text-sm"
                    >
                      {UBAH_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_META[s]?.label || s}</option>)}
                    </select>
                    <Button
                      data-testid="pembayaran-simpan-status"
                      size="sm"
                      disabled={ubahStatus === selected.transaction_status || savingStatus}
                      onClick={simpanUbahStatus}
                      className="bg-blue-700 hover:bg-blue-800 shrink-0"
                    >
                      {savingStatus ? "Menyimpan…" : "Simpan"}
                    </Button>
                  </div>
                </div>
              )}

              <div className="border-t border-slate-100 pt-3">
                <p className="text-sm font-semibold text-slate-600 mb-2">Riwayat Pembayaran</p>
                {riwayatLoading ? (
                  <p className="text-xs text-slate-400">Memuat riwayat…</p>
                ) : (
                  <ul className="space-y-2" data-testid="pembayaran-riwayat">
                    {(riwayat.length ? riwayat : [selected]).map((h, i) => (
                      <li key={h.id || i} className="flex items-start gap-2 text-xs">
                        <span className={`shrink-0 mt-0.5 inline-flex px-1.5 py-0.5 rounded font-medium ${(STATUS_META[h.transaction_status] || {}).cls || "bg-slate-100 text-slate-600"}`}>
                          {(STATUS_META[h.transaction_status] || {}).label || h.transaction_status}
                        </span>
                        <div className="min-w-0">
                          <div className="text-slate-700 font-mono">{h.order_id}{h.payment_type ? <> — <span className="uppercase">{h.payment_type}</span></> : null} · {fmtRp(h.gross_amount)}</div>
                          {h.manual_status_by && (
                            <div className="text-slate-500">Diubah manual oleh {h.manual_status_by}{h.manual_status_reason ? `: ${h.manual_status_reason}` : ""}</div>
                          )}
                          <div className="text-slate-400">{fmtDateTime(h.created_at)}</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

            </div>
          )}
        </DialogContent>
      </Dialog>

      <BuatTagihanDialog
        open={tagihanOpen}
        onOpenChange={setTagihanOpen}
        onCreated={() => {
          muatTransaksi();
          toast.success("Tagihan Tripay dibuat");
        }}
      />
    </div>
  );
}
