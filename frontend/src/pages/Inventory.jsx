import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, AlertTriangle, Pencil, Trash2 } from "lucide-react";

export default function Inventory() {
  const [products, setProducts] = useState([]);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({ kode: "", nama: "", kategori: "makanan", harga: 0, stok: 0, stok_minimal: 5, aktif: true });
  const [adj, setAdj] = useState(null);
  const [delta, setDelta] = useState(1);

  const load = async () => { const { data } = await api.get("/products"); setProducts(data); };
  useEffect(() => { load(); }, []);

  const lowStock = products.filter(p => p.kategori !== "laundry" && p.stok <= (p.stok_minimal || 0));

  const openNew = () => { setForm({ kode: "", nama: "", kategori: "makanan", harga: 0, stok: 0, stok_minimal: 5, aktif: true }); setEdit("new"); };
  const openEdit = (p) => { setForm({ ...p }); setEdit(p); };

  const save = async () => {
    try {
      const payload = { ...form, harga: Number(form.harga), stok: Number(form.stok), stok_minimal: Number(form.stok_minimal) };
      if (edit === "new") await api.post("/products", payload);
      else await api.put(`/products/${edit.id}`, payload);
      toast.success("Tersimpan");
      setEdit(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const del = async (p) => {
    if (!window.confirm(`Hapus produk ${p.nama}?`)) return;
    try { await api.delete(`/products/${p.id}`); toast.success("Dihapus"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const submitAdj = async () => {
    try {
      await api.post(`/products/${adj.id}/stock`, { delta: Number(delta), catatan: "Penyesuaian manual" });
      toast.success("Stok diperbarui");
      setAdj(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Inventory</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">{products.length} Produk</h1>
        </div>
        <Button data-testid="add-product" onClick={openNew} className="bg-blue-700 hover:bg-blue-800"><Plus className="w-4 h-4 mr-2" /> Tambah Produk</Button>
      </div>

      {lowStock.length > 0 && (
        <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-amber-800">{lowStock.length} produk hampir/sudah habis</div>
            <div className="text-amber-700">{lowStock.map(p => `${p.nama} (${p.stok})`).join(", ")}</div>
          </div>
        </div>
      )}

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Kode</th>
                <th className="text-left p-3">Nama</th>
                <th className="text-left p-3">Kategori</th>
                <th className="text-right p-3">Harga</th>
                <th className="text-right p-3">Stok</th>
                <th className="text-right p-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {products.map(p => (
                <tr key={p.id} className="border-t border-slate-100">
                  <td className="p-3 font-mono text-xs">{p.kode}</td>
                  <td className="p-3 font-semibold">{p.nama}</td>
                  <td className="p-3 capitalize">{p.kategori}</td>
                  <td className="p-3 text-right">{fmtRp(p.harga)}</td>
                  <td className="p-3 text-right">
                    {p.kategori === "laundry" ? "-" : (
                      <span className={p.stok <= (p.stok_minimal || 0) ? "text-amber-600 font-bold" : ""}>
                        {p.stok} {p.stok_minimal ? <span className="text-xs text-slate-400">/ min {p.stok_minimal}</span> : null}
                      </span>
                    )}
                  </td>
                  <td className="p-3 text-right whitespace-nowrap">
                    {p.kategori !== "laundry" && <Button size="sm" variant="outline" onClick={() => { setAdj(p); setDelta(1); }} data-testid={`adj-${p.kode}`}>+/-</Button>}
                    <Button size="sm" variant="ghost" onClick={() => openEdit(p)}><Pencil className="w-4 h-4" /></Button>
                    <Button size="sm" variant="ghost" onClick={() => del(p)}><Trash2 className="w-4 h-4 text-red-500" /></Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{edit === "new" ? "Produk Baru" : `Edit ${edit?.nama}`}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Kode</Label><Input data-testid="prod-kode" value={form.kode} onChange={(e) => setForm(f => ({ ...f, kode: e.target.value }))} /></div>
            <div><Label>Kategori</Label>
              <select data-testid="prod-kat" value={form.kategori} onChange={(e) => setForm(f => ({ ...f, kategori: e.target.value }))} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white">
                <option value="makanan">Makanan</option><option value="minuman">Minuman</option><option value="laundry">Laundry</option>
              </select>
            </div>
            <div className="col-span-2"><Label>Nama</Label><Input data-testid="prod-nama" value={form.nama} onChange={(e) => setForm(f => ({ ...f, nama: e.target.value }))} /></div>
            <div><Label>Harga</Label><Input data-testid="prod-harga" type="number" value={form.harga} onChange={(e) => setForm(f => ({ ...f, harga: e.target.value }))} /></div>
            <div><Label>Stok</Label><Input data-testid="prod-stok" type="number" value={form.stok} onChange={(e) => setForm(f => ({ ...f, stok: e.target.value }))} disabled={form.kategori === "laundry"} /></div>
            <div className="col-span-2"><Label>Stok Minimal</Label><Input type="number" value={form.stok_minimal} onChange={(e) => setForm(f => ({ ...f, stok_minimal: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdit(null)}>Batal</Button>
            <Button data-testid="save-product" onClick={save} className="bg-blue-700 hover:bg-blue-800">Simpan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!adj} onOpenChange={(o) => !o && setAdj(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Penyesuaian Stok — {adj?.nama}</DialogTitle></DialogHeader>
          <div>
            <Label>Delta (+ untuk masuk, - untuk keluar)</Label>
            <Input data-testid="adj-delta" type="number" value={delta} onChange={(e) => setDelta(e.target.value)} className="h-12 mt-2" />
            <p className="text-xs text-slate-500 mt-1">Stok saat ini: {adj?.stok}</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdj(null)}>Batal</Button>
            <Button data-testid="save-adj" onClick={submitAdj} className="bg-blue-700 hover:bg-blue-800">Simpan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
