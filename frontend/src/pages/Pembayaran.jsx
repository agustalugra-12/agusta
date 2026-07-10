import { useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Search, X, CreditCard } from "lucide-react";
import { fmtDateTime, fmtRp } from "@/lib/apiClient";

// Data tiruan (stub) — daftar transaksi Midtrans, bentuknya mengikuti koleksi `payment_log`
// yang sudah nyata di backend (backend/routes/payments.py). Alur checkout tamu (Snap.js)
// SUDAH berfungsi sungguhan di PublicBook.jsx; halaman ini baru untuk staf memantau semua
// transaksi — endpoint list-nya menyusul (backend baru punya lookup per order_id).
const MOCK_TRANSACTIONS = [
  { id: "1", order_id: "RSV-1042-143022ABC", booking_kode: "RSV-1042", nama_tamu: "Dewi Anggraini", gross_amount: 130000, payment_option: "dp50", payment_type: "qris", transaction_status: "settlement", created_at: "2026-07-11T09:30:22" },
  { id: "2", order_id: "RSV-1041-101503XYZ", booking_kode: "RSV-1041", nama_tamu: "Budi Santoso", gross_amount: 123600, payment_option: "full", payment_type: "bca_va", transaction_status: "pending", created_at: "2026-07-11T10:15:03" },
  { id: "3", order_id: "RSV-1040-081145DEF", booking_kode: "RSV-1040", nama_tamu: "Ahmad Fauzi", gross_amount: 240000, payment_option: "full", payment_type: "bni_va", transaction_status: "settlement", created_at: "2026-07-10T08:11:45" },
  { id: "4", order_id: "RSV-1039-070230GHI", booking_kode: "RSV-1039", nama_tamu: "Sri Wahyuni", gross_amount: 65000, payment_option: "dp50", payment_type: "bank_transfer", transaction_status: "expire", created_at: "2026-07-09T07:02:30" },
  { id: "5", order_id: "RSV-1037-063312JKL", booking_kode: "RSV-1037", nama_tamu: "Hendra Wijaya", gross_amount: 123600, payment_option: "full", payment_type: "qris", transaction_status: "deny", created_at: "2026-07-10T06:33:12" },
];

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

export default function Pembayaran() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Semua");
  const [selected, setSelected] = useState(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return MOCK_TRANSACTIONS.filter((t) => {
      if (q && !t.booking_kode.toLowerCase().includes(q) && !t.nama_tamu.toLowerCase().includes(q) && !t.order_id.toLowerCase().includes(q)) return false;
      if (status !== "Semua" && t.transaction_status !== status) return false;
      return true;
    });
  }, [search, status]);

  const resetFilters = () => { setSearch(""); setStatus("Semua"); };
  const hasActiveFilter = search || status !== "Semua";

  return (
    <div className="space-y-6" data-testid="pembayaran-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Pembayaran</h1>
        <p className="text-slate-500 mt-1">Daftar transaksi Midtrans dari semua reservasi (checkout tamu &amp; DP).</p>
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
                    onClick={() => setSelected(t)}
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
              {filtered.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-slate-500">Tidak ada transaksi yang cocok</td></tr>
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
              <p className="text-[11px] text-slate-400 pt-1">Data tiruan — belum tersambung ke daftar transaksi Midtrans sungguhan.</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
