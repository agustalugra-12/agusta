import { useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Search, X, Mail, MessageSquare, CheckCircle2, XCircle } from "lucide-react";
import { fmtDateTime } from "@/lib/apiClient";

// Data tiruan (stub) — log pengiriman voucher/bukti booking otomatis ke tamu (email atau
// WhatsApp) setelah reservasi terkonfirmasi. Belum tersambung ke pengiriman sungguhan.
const MOCK_VOUCHER_LOG = [
  { id: "1", kode_booking: "RSV-1042", nama_tamu: "Dewi Anggraini", metode: "Email", status: "Terkirim", waktu: "2026-07-11T09:31:00" },
  { id: "2", kode_booking: "RSV-1041", nama_tamu: "Budi Santoso", metode: "WhatsApp", status: "Terkirim", waktu: "2026-07-11T10:16:00" },
  { id: "3", kode_booking: "RSV-1040", nama_tamu: "Ahmad Fauzi", metode: "Email", status: "Gagal", waktu: "2026-07-10T08:12:00", error: "Alamat email tidak valid" },
  { id: "4", kode_booking: "RSV-1039", nama_tamu: "Sri Wahyuni", metode: "WhatsApp", status: "Terkirim", waktu: "2026-07-09T07:05:00" },
];

const METODE_ICON = { Email: Mail, WhatsApp: MessageSquare };
const STATUS_META = {
  Terkirim: "bg-emerald-100 text-emerald-800",
  Gagal: "bg-red-100 text-red-800",
};

export default function PengirimanVoucherOtomatis() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Semua");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return MOCK_VOUCHER_LOG.filter((v) => {
      if (q && !v.kode_booking.toLowerCase().includes(q) && !v.nama_tamu.toLowerCase().includes(q)) return false;
      if (status !== "Semua" && v.status !== status) return false;
      return true;
    });
  }, [search, status]);

  const resetFilters = () => { setSearch(""); setStatus("Semua"); };
  const hasActiveFilter = search || status !== "Semua";

  return (
    <div className="space-y-6" data-testid="pengiriman-voucher-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Log Pengiriman Voucher</h1>
        <p className="text-slate-500 mt-1">
          Riwayat pengiriman voucher/bukti booking otomatis ke tamu (email &amp; WhatsApp).
        </p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <Label htmlFor="voucher-search">Cari kode booking / nama tamu</Label>
            <div className="relative mt-1.5">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <Input id="voucher-search" data-testid="voucher-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Mis: RSV-1042, Dewi…" className="pl-9" />
            </div>
          </div>
          <div className="w-full sm:w-48">
            <Label htmlFor="voucher-status">Status</Label>
            <select
              id="voucher-status"
              data-testid="voucher-filter-status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {["Semua", "Terkirim", "Gagal"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {hasActiveFilter && (
            <Button data-testid="voucher-reset-filter" variant="ghost" size="sm" onClick={resetFilters} className="gap-1.5">
              <X className="w-3.5 h-3.5" /> Reset
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm" data-testid="voucher-log-table">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Kode Booking</th>
                <th className="text-left p-3">Tamu</th>
                <th className="text-left p-3">Metode</th>
                <th className="text-left p-3">Waktu</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Keterangan</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((v) => {
                const Icon = METODE_ICON[v.metode];
                return (
                  <tr key={v.id} data-testid={`voucher-log-row-${v.id}`} className="border-t border-slate-100">
                    <td className="p-3 font-semibold">{v.kode_booking}</td>
                    <td className="p-3">{v.nama_tamu}</td>
                    <td className="p-3">
                      <span className="inline-flex items-center gap-1 text-slate-600"><Icon className="w-3.5 h-3.5" /> {v.metode}</span>
                    </td>
                    <td className="p-3 text-slate-500">{fmtDateTime(v.waktu)}</td>
                    <td className="p-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium ${STATUS_META[v.status]}`}>
                        {v.status === "Terkirim" ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />} {v.status}
                      </span>
                    </td>
                    <td className="p-3 text-slate-600">{v.error || "-"}</td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-slate-500">Tidak ada log yang cocok dengan pencarian/filter</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[11px] text-slate-400">Data tiruan — belum tersambung ke pengiriman voucher sungguhan.</p>
    </div>
  );
}
