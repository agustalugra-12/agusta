import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDate } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import { Trash2 } from "lucide-react";

const CATS = ["Belanja Operasional", "Laundry", "Perawatan Kamar", "Gaji", "Perlengkapan", "Listrik", "Air", "Internet", "Lainnya"];

export default function Pengeluaran() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ kategori: "Belanja Operasional", deskripsi: "", nominal: 0 });

  const load = async () => { const { data } = await api.get("/expenses"); setItems(data); };
  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.post("/expenses", { ...form, nominal: Number(form.nominal) });
      toast.success("Tersimpan");
      setForm({ kategori: "Belanja Operasional", deskripsi: "", nominal: 0 });
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const del = async (id) => {
    if (!window.confirm("Hapus?")) return;
    await api.delete(`/expenses/${id}`); load();
  };

  const total = items.reduce((a, x) => a + (x.nominal || 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Pengeluaran</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Catatan Pengeluaran</h1>
      </div>

      <div className="grid lg:grid-cols-[400px_1fr] gap-6">
        <Card className="border-slate-200">
          <CardContent className="p-5 space-y-4">
            <h2 className="font-bold">Pengeluaran Baru</h2>
            <form onSubmit={submit} className="space-y-3">
              <div>
                <Label>Kategori</Label>
                <select data-testid="exp-kat" value={form.kategori} onChange={(e) => setForm(f => ({ ...f, kategori: e.target.value }))} className="w-full h-12 rounded-md border border-slate-300 px-3 bg-white mt-1.5">
                  {CATS.map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
              <div><Label>Deskripsi</Label><Textarea data-testid="exp-desc" value={form.deskripsi} onChange={(e) => setForm(f => ({ ...f, deskripsi: e.target.value }))} className="mt-1.5" rows={2} /></div>
              <div><Label>Nominal (Rp)</Label><Input data-testid="exp-nominal" type="number" value={form.nominal} onChange={(e) => setForm(f => ({ ...f, nominal: e.target.value }))} className="h-12 mt-1.5" /></div>
              <Button data-testid="exp-submit" type="submit" className="w-full h-12 bg-blue-700 hover:bg-blue-800">Simpan</Button>
            </form>
          </CardContent>
        </Card>

        <Card className="border-slate-200">
          <CardContent className="p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-bold">Riwayat</h2>
              <span className="text-sm">Total: <span className="font-bold text-blue-700">{fmtRp(total)}</span></span>
            </div>
            <div className="divide-y divide-slate-100">
              {items.map(x => (
                <div key={x.id} className="py-3 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold">{x.kategori}</div>
                    <div className="text-xs text-slate-500">{fmtDate(x.tanggal)} • {x.user} • {x.deskripsi}</div>
                  </div>
                  <div className="font-bold text-red-600">-{fmtRp(x.nominal)}</div>
                  {isOwner && <Button size="icon" variant="ghost" onClick={() => del(x.id)}><Trash2 className="w-4 h-4 text-red-500" /></Button>}
                </div>
              ))}
              {items.length === 0 && <div className="text-slate-500 text-center py-10">Belum ada pengeluaran</div>}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
