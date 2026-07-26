import { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";
import { Plus, Pencil, Building2 } from "lucide-react";

const emptyForm = { nama: "", slug: "", alamat: "", aktif: true, butuh_sinkron_reddoorz: true };

export default function Properti() {
  const { activePropertyId, setActivePropertyId } = useAuth();
  const [items, setItems] = useState([]);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState(emptyForm);

  const load = async () => { const { data } = await api.get("/properties"); setItems(data); };
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(emptyForm); setEdit("new"); };
  const openEdit = (p) => { setForm({ nama: p.nama, slug: p.slug, alamat: p.alamat || "", aktif: p.aktif, butuh_sinkron_reddoorz: p.butuh_sinkron_reddoorz !== false }); setEdit(p); };

  const save = async () => {
    try {
      if (edit === "new") {
        await api.post("/properties", { nama: form.nama, slug: form.slug || form.nama, alamat: form.alamat, butuh_sinkron_reddoorz: form.butuh_sinkron_reddoorz });
      } else {
        await api.put(`/properties/${edit.id}`, { nama: form.nama, slug: form.slug, alamat: form.alamat, aktif: form.aktif, butuh_sinkron_reddoorz: form.butuh_sinkron_reddoorz });
      }
      toast.success("Tersimpan");
      setEdit(null);
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Properti</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Kelola Properti</h1>
          <p className="text-sm text-slate-500 mt-1">Tiap properti punya kamar, staf, keuangan, dan laporan sendiri-sendiri — terpisah total dari properti lain.</p>
        </div>
        <Button data-testid="add-properti" onClick={openNew} className="bg-blue-700 hover:bg-blue-800"><Plus className="w-4 h-4 mr-2" /> Tambah Properti</Button>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider"><tr>
              <th className="text-left p-3">Nama</th>
              <th className="text-left p-3">Slug</th>
              <th className="text-left p-3">Alamat</th>
              <th className="text-left p-3">Status</th>
              <th className="text-left p-3">Menginap</th>
              <th className="text-right p-3">Aksi</th>
            </tr></thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className={`border-t border-slate-100 ${p.id === activePropertyId ? "bg-blue-50/50" : ""}`}>
                  <td className="p-3 font-semibold flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-slate-400" />
                    {p.nama}
                    {p.id === activePropertyId && <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-bold uppercase tracking-wide">Aktif</span>}
                  </td>
                  <td className="p-3 font-mono text-xs text-slate-500">{p.slug}</td>
                  <td className="p-3 text-slate-600">{p.alamat || "-"}</td>
                  <td className="p-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${p.aktif ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                      {p.aktif ? "Aktif" : "Nonaktif"}
                    </span>
                  </td>
                  <td className="p-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${p.butuh_sinkron_reddoorz === false ? "bg-blue-100 text-blue-700" : "bg-amber-100 text-amber-800"}`}>
                      {p.butuh_sinkron_reddoorz === false ? "Auto-konfirmasi" : "Perlu review staf"}
                    </span>
                  </td>
                  <td className="p-3 text-right space-x-1">
                    {p.id !== activePropertyId && (
                      <Button size="sm" variant="outline" onClick={() => setActivePropertyId(p.id)}>Pindah ke sini</Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => openEdit(p)}><Pencil className="w-4 h-4" /></Button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-slate-400">Belum ada properti.</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{edit === "new" ? "Properti Baru" : `Edit ${edit?.nama}`}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nama</Label><Input data-testid="properti-nama" value={form.nama} onChange={(e) => setForm(f => ({ ...f, nama: e.target.value }))} /></div>
            <div>
              <Label>Slug {edit === "new" && <span className="text-slate-400 font-normal">(opsional, otomatis dari nama)</span>}</Label>
              <Input data-testid="properti-slug" value={form.slug} onChange={(e) => setForm(f => ({ ...f, slug: e.target.value }))} placeholder={form.nama ? form.nama.toLowerCase().replace(/[^a-z0-9]+/g, "-") : ""} />
            </div>
            <div><Label>Alamat</Label><Input data-testid="properti-alamat" value={form.alamat} onChange={(e) => setForm(f => ({ ...f, alamat: e.target.value }))} /></div>
            <label className="flex items-start gap-2 p-2.5 rounded-lg border border-slate-200 bg-slate-50 text-xs cursor-pointer">
              <input
                type="checkbox" data-testid="properti-butuh-reddoorz"
                checked={form.butuh_sinkron_reddoorz}
                onChange={(e) => setForm(f => ({ ...f, butuh_sinkron_reddoorz: e.target.checked }))}
                className="mt-0.5"
              />
              <span>
                Properti ini listing di RedDoorz (butuh sinkron manual RedDoorz untuk booking Menginap).
                <span className="block text-slate-500 mt-0.5">
                  Kalau dimatikan: booking Menginap di properti ini langsung diproses otomatis begitu tamu
                  sebutkan preferensi bayar (DP/Lunas) via AI WhatsApp - persis seperti Day Use, tidak perlu
                  ditinjau/disetujui staf.
                </span>
              </span>
            </label>
            {edit !== "new" && (
              <div>
                <Label>Status</Label>
                <select value={form.aktif ? "aktif" : "nonaktif"} onChange={(e) => setForm(f => ({ ...f, aktif: e.target.value === "aktif" }))} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white">
                  <option value="aktif">Aktif</option>
                  <option value="nonaktif">Nonaktif</option>
                </select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdit(null)}>Batal</Button>
            <Button data-testid="save-properti" onClick={save} className="bg-blue-700 hover:bg-blue-800">Simpan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
