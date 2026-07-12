import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, statusLabel, statusColor } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";
import { Plus, Pencil, Trash2 } from "lucide-react";

export default function Rooms() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [rooms, setRooms] = useState([]);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({ nomor: "", tipe: "Standard", tarif: 120000, tarif_menginap: 150000 });

  const load = async () => { const { data } = await api.get("/rooms"); setRooms(data); };
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm({ nomor: "", tipe: "Standard", tarif: 120000, tarif_menginap: 150000 }); setEdit("new"); };
  const openEdit = (r) => { setForm({ nomor: r.nomor, tipe: r.tipe, tarif: r.tarif, tarif_menginap: r.tarif_menginap }); setEdit(r); };

  const save = async () => {
    try {
      const payload = { ...form, tarif: Number(form.tarif), tarif_menginap: Number(form.tarif_menginap) };
      if (edit === "new") {
        await api.post("/rooms", payload);
      } else {
        await api.put(`/rooms/${edit.id}`, payload);
      }
      toast.success("Tersimpan");
      setEdit(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const del = async (r) => {
    if (!window.confirm(`Hapus kamar ${r.nomor}?`)) return;
    try { await api.delete(`/rooms/${r.id}`); toast.success("Dihapus"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Manajemen Kamar</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">{rooms.length} Kamar</h1>
        </div>
        {isOwner && <Button data-testid="add-room" onClick={openNew} className="bg-blue-700 hover:bg-blue-800"><Plus className="w-4 h-4 mr-2" /> Tambah Kamar</Button>}
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Nomor</th>
                <th className="text-left p-3">Tipe</th>
                <th className="text-left p-3">Tarif Day Use</th>
                <th className="text-left p-3">Tarif Menginap</th>
                <th className="text-left p-3">Status</th>
                {isOwner && <th className="text-right p-3">Aksi</th>}
              </tr>
            </thead>
            <tbody>
              {rooms.map(r => (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="p-3 font-bold">{r.nomor}</td>
                  <td className="p-3">{r.tipe}</td>
                  <td className="p-3">{fmtRp(r.tarif)}</td>
                  <td className="p-3">{fmtRp(r.tarif_menginap)}</td>
                  <td className="p-3">
                    <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium" style={{ background: statusColor(r.status) + "22", color: statusColor(r.status) }}>
                      <span className="w-2 h-2 rounded-full" style={{ background: statusColor(r.status) }} />
                      {statusLabel(r.status)}
                    </span>
                  </td>
                  {isOwner && (
                    <td className="p-3 text-right">
                      <Button data-testid={`edit-room-${r.nomor}`} size="sm" variant="ghost" onClick={() => openEdit(r)}><Pencil className="w-4 h-4" /></Button>
                      <Button data-testid={`del-room-${r.nomor}`} size="sm" variant="ghost" onClick={() => del(r)}><Trash2 className="w-4 h-4 text-red-500" /></Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{edit === "new" ? "Tambah Kamar" : `Edit Kamar ${edit?.nomor}`}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nomor</Label><Input data-testid="room-nomor" value={form.nomor} onChange={(e) => setForm(f => ({ ...f, nomor: e.target.value }))} /></div>
            <div>
              <Label>Tipe</Label>
              <select data-testid="room-tipe" value={form.tipe} onChange={(e) => setForm(f => ({ ...f, tipe: e.target.value, tarif: e.target.value === "Cottage" ? 140000 : 120000, tarif_menginap: e.target.value === "Cottage" ? 200000 : 150000 }))} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white">
                <option value="Standard">Standard</option>
                <option value="Cottage">Cottage</option>
              </select>
            </div>
            <div><Label>Tarif Day Use (per 6 jam)</Label><Input data-testid="room-tarif" type="number" value={form.tarif} onChange={(e) => setForm(f => ({ ...f, tarif: e.target.value }))} /></div>
            <div><Label>Tarif Menginap (per malam, tanpa sarapan)</Label><Input data-testid="room-tarif-menginap" type="number" value={form.tarif_menginap} onChange={(e) => setForm(f => ({ ...f, tarif_menginap: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdit(null)}>Batal</Button>
            <Button data-testid="save-room" onClick={save} className="bg-blue-700 hover:bg-blue-800">Simpan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
