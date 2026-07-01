import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import { Trash2, Sparkles, Plus } from "lucide-react";

const KATEGORI = [
  "Layanan Tambahan",
  "Transportasi",
  "Antar-Jemput",
  "Cuci Kendaraan",
  "Extra Bed",
  "Extra Handuk",
  "Sewa Alat",
  "Late Check-out",
  "Early Check-in",
  "Lainnya",
];
const METODE = ["tunai", "qris", "transfer"];

const emptyForm = {
  kategori: "Layanan Tambahan",
  deskripsi: "",
  nominal: "",
  tamu: "",
  no_hp: "",
  room_nomor: "",
  metode_pembayaran: "tunai",
};

export default function Service() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(emptyForm);

  const load = async () => {
    try {
      setLoading(true);
      const { data } = await api.get("/services");
      setItems(data || []);
    } catch (e) {
      toast.error("Gagal memuat data layanan");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const totals = useMemo(() => {
    const total = items.reduce((s, x) => s + (x.nominal || 0), 0);
    const today = new Date().toISOString().slice(0, 10);
    const totalToday = items.filter(x => (x.tanggal || "").slice(0, 10) === today)
      .reduce((s, x) => s + (x.nominal || 0), 0);
    const byKat = {};
    items.forEach(x => { byKat[x.kategori] = (byKat[x.kategori] || 0) + (x.nominal || 0); });
    return { total, totalToday, byKat, count: items.length };
  }, [items]);

  const submit = async (e) => {
    e.preventDefault();
    const nominal = Number(form.nominal);
    if (!form.deskripsi.trim()) return toast.error("Deskripsi wajib diisi");
    if (!Number.isFinite(nominal) || nominal <= 0) return toast.error("Nominal harus lebih dari 0");
    try {
      await api.post("/services", { ...form, nominal });
      toast.success("Layanan tercatat & masuk laporan pendapatan");
      setForm(emptyForm);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Gagal menyimpan");
    }
  };

  const del = async (id, kode) => {
    if (!window.confirm(`Hapus layanan ${kode}?`)) return;
    try {
      await api.delete(`/services/${id}`);
      toast.success("Layanan dihapus");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Gagal menghapus");
    }
  };

  return (
    <div className="space-y-6" data-testid="service-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Service</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold flex items-center gap-3">
          <Sparkles className="w-8 h-8 text-emerald-600" />
          Layanan Tambahan
        </h1>
        <p className="text-sm text-slate-500 mt-1">Catat layanan di luar kamar & POS (nominal fleksibel). Otomatis masuk ke Laporan Service & Pendapatan.</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Card className="border-slate-200"><CardContent className="p-4">
          <div className="text-xs uppercase tracking-wider text-slate-500">Total Hari Ini</div>
          <div className="text-2xl font-extrabold mt-1 text-emerald-600" data-testid="svc-total-today">{fmtRp(totals.totalToday)}</div>
        </CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4">
          <div className="text-xs uppercase tracking-wider text-slate-500">Total Keseluruhan</div>
          <div className="text-2xl font-extrabold mt-1 text-blue-700" data-testid="svc-total-all">{fmtRp(totals.total)}</div>
        </CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4">
          <div className="text-xs uppercase tracking-wider text-slate-500">Jumlah Transaksi</div>
          <div className="text-2xl font-extrabold mt-1 text-slate-700">{totals.count}</div>
        </CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4">
          <div className="text-xs uppercase tracking-wider text-slate-500">Top Kategori</div>
          <div className="text-lg font-bold mt-1 text-orange-600 truncate">
            {Object.entries(totals.byKat).sort((a, b) => b[1] - a[1])[0]?.[0] || "-"}
          </div>
        </CardContent></Card>
      </div>

      <div className="grid lg:grid-cols-[420px_1fr] gap-6">
        {/* Form */}
        <Card className="border-slate-200">
          <CardContent className="p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Plus className="w-5 h-5 text-emerald-600" />
              <h2 className="font-bold">Catat Layanan Baru</h2>
            </div>
            <form onSubmit={submit} className="space-y-3">
              <div>
                <Label>Kategori</Label>
                <select
                  data-testid="svc-kategori"
                  value={form.kategori}
                  onChange={(e) => setForm(f => ({ ...f, kategori: e.target.value }))}
                  className="w-full h-11 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
                >
                  {KATEGORI.map(k => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
              <div>
                <Label>Deskripsi Layanan <span className="text-red-500">*</span></Label>
                <Textarea
                  data-testid="svc-deskripsi"
                  value={form.deskripsi}
                  onChange={(e) => setForm(f => ({ ...f, deskripsi: e.target.value }))}
                  placeholder="Cth: Antar tamu ke bandara pukul 15.00"
                  className="mt-1.5"
                  rows={2}
                />
              </div>
              <div>
                <Label>Nominal (Rp) <span className="text-red-500">*</span></Label>
                <Input
                  data-testid="svc-nominal"
                  type="number"
                  min="0"
                  step="1000"
                  value={form.nominal}
                  onChange={(e) => setForm(f => ({ ...f, nominal: e.target.value }))}
                  placeholder="Nominal fleksibel, cth: 75000"
                  className="h-11 mt-1.5"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Nama Tamu (opsional)</Label>
                  <Input
                    data-testid="svc-tamu"
                    value={form.tamu}
                    onChange={(e) => setForm(f => ({ ...f, tamu: e.target.value }))}
                    className="h-11 mt-1.5"
                  />
                </div>
                <div>
                  <Label>Kamar (opsional)</Label>
                  <Input
                    data-testid="svc-kamar"
                    value={form.room_nomor}
                    onChange={(e) => setForm(f => ({ ...f, room_nomor: e.target.value }))}
                    placeholder="Cth: 5"
                    className="h-11 mt-1.5"
                  />
                </div>
              </div>
              <div>
                <Label>No HP (opsional)</Label>
                <Input
                  data-testid="svc-hp"
                  value={form.no_hp}
                  onChange={(e) => setForm(f => ({ ...f, no_hp: e.target.value }))}
                  className="h-11 mt-1.5"
                />
              </div>
              <div>
                <Label>Metode Pembayaran</Label>
                <select
                  data-testid="svc-metode"
                  value={form.metode_pembayaran}
                  onChange={(e) => setForm(f => ({ ...f, metode_pembayaran: e.target.value }))}
                  className="w-full h-11 rounded-md border border-slate-300 px-3 bg-white mt-1.5 capitalize"
                >
                  {METODE.map(m => <option key={m} value={m} className="capitalize">{m}</option>)}
                </select>
              </div>
              <Button
                data-testid="svc-submit"
                type="submit"
                className="w-full h-11 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
              >
                Simpan Layanan
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Riwayat */}
        <Card className="border-slate-200">
          <CardContent className="p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-bold">Riwayat Layanan</h2>
              <span className="text-sm text-slate-500">Total: <span className="font-bold text-emerald-700" data-testid="svc-riwayat-total">{fmtRp(totals.total)}</span></span>
            </div>
            <div className="divide-y divide-slate-100" data-testid="svc-list">
              {items.map(x => (
                <div key={x.id} className="py-3 flex items-start gap-3" data-testid={`svc-row-${x.id}`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-600">{x.kode}</span>
                      <span className="text-xs uppercase font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-700">{x.kategori}</span>
                      <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-blue-50 text-blue-700">{x.metode_pembayaran}</span>
                    </div>
                    <div className="font-semibold mt-1">{x.deskripsi}</div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      {fmtDateTime(x.tanggal)}
                      {x.tamu && ` • ${x.tamu}`}
                      {x.room_nomor && ` • Kamar ${x.room_nomor}`}
                      {` • oleh ${x.user}`}
                    </div>
                  </div>
                  <div className="font-bold text-emerald-700 whitespace-nowrap">+{fmtRp(x.nominal)}</div>
                  {isOwner && (
                    <Button
                      data-testid={`svc-delete-${x.id}`}
                      size="icon"
                      variant="ghost"
                      onClick={() => del(x.id, x.kode)}
                    >
                      <Trash2 className="w-4 h-4 text-red-500" />
                    </Button>
                  )}
                </div>
              ))}
              {items.length === 0 && (
                <div className="text-slate-500 text-center py-10">
                  {loading ? "Memuat..." : "Belum ada layanan tercatat"}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
