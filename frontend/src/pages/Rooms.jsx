import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, statusLabel, statusColor, BACKEND_URL } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";
import { Plus, Pencil, Trash2, Upload, Star, Loader2, X } from "lucide-react";

export default function Rooms() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [rooms, setRooms] = useState([]);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({ nomor: "", tipe: "Standard", tarif: 120000, tarif_menginap: 150000 });
  const [foto, setFoto] = useState({ foto_urls: [], foto_utama: "" });
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  const load = async () => { const { data } = await api.get("/rooms"); setRooms(data); };
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm({ nomor: "", tipe: "Standard", tarif: 120000, tarif_menginap: 150000 }); setFoto({ foto_urls: [], foto_utama: "" }); setEdit("new"); };
  const openEdit = (r) => { setForm({ nomor: r.nomor, tipe: r.tipe, tarif: r.tarif, tarif_menginap: r.tarif_menginap }); setFoto({ foto_urls: r.foto_urls || [], foto_utama: r.foto_utama || "" }); setEdit(r); };

  const save = async () => {
    try {
      const payload = { ...form, tarif: Number(form.tarif), tarif_menginap: Number(form.tarif_menginap) };
      if (edit === "new") {
        await api.post("/rooms", payload);
      } else {
        await api.put(`/rooms/${edit.id}`, { ...payload, foto_utama: foto.foto_utama });
      }
      toast.success("Tersimpan");
      setEdit(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const uploadFoto = async (e) => {
    const file = e.target.files?.[0];
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (!file || edit === "new" || !edit) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post(`/rooms/${edit.id}/foto`, fd);
      setFoto(data);
      toast.success("Foto ditambahkan");
    } catch (err) { toast.error(err?.response?.data?.detail || "Gagal upload foto"); }
    finally { setUploading(false); }
  };

  const hapusFoto = async (url) => {
    if (!edit || edit === "new") return;
    try {
      const { data } = await api.delete(`/rooms/${edit.id}/foto`, { params: { url } });
      setFoto(data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Gagal hapus foto"); }
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

            {edit !== "new" && (
              <div>
                <Label>Foto Kamar</Label>
                <div className="grid grid-cols-3 gap-2 mt-1.5">
                  {foto.foto_urls.map((url) => (
                    <div key={url} className="relative group aspect-square rounded-lg overflow-hidden border border-slate-200">
                      <img src={`${BACKEND_URL}${url}`} alt="Foto kamar" className="w-full h-full object-cover" />
                      <button
                        type="button" title="Jadikan foto utama"
                        onClick={() => setFoto((f) => ({ ...f, foto_utama: url }))}
                        className={`absolute top-1 left-1 w-6 h-6 rounded-full grid place-items-center ${url === foto.foto_utama ? "bg-amber-400 text-white" : "bg-white/80 text-slate-400 hover:text-amber-500"}`}
                      >
                        <Star className="w-3.5 h-3.5" fill={url === foto.foto_utama ? "currentColor" : "none"} />
                      </button>
                      <button
                        type="button" title="Hapus foto"
                        onClick={() => hapusFoto(url)}
                        className="absolute top-1 right-1 w-6 h-6 rounded-full bg-white/80 text-slate-400 hover:text-red-500 grid place-items-center opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  <button
                    type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading}
                    className="aspect-square rounded-lg border-2 border-dashed border-slate-300 text-slate-400 hover:border-blue-400 hover:text-blue-500 grid place-items-center"
                  >
                    {uploading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Upload className="w-5 h-5" />}
                  </button>
                </div>
                <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={uploadFoto} />
                <p className="text-xs text-slate-500 mt-1.5">Klik ikon bintang untuk jadikan foto utama. JPG/PNG/WEBP, maks 5MB.</p>
              </div>
            )}
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
