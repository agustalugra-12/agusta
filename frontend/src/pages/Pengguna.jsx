import { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";
import { Plus, Pencil, Trash2 } from "lucide-react";

export default function Pengguna() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({ nama: "", username: "", password: "", role: "resepsionis" });

  const load = async () => { const { data } = await api.get("/users"); setUsers(data); };
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm({ nama: "", username: "", password: "", role: "resepsionis" }); setEdit("new"); };
  const openEdit = (u) => { setForm({ nama: u.nama, username: u.username, password: "", role: u.role, status: u.status }); setEdit(u); };

  const save = async () => {
    try {
      if (edit === "new") await api.post("/users", form);
      else {
        const payload = { nama: form.nama, role: form.role, status: form.status };
        if (form.password) payload.password = form.password;
        await api.put(`/users/${edit.id}`, payload);
      }
      toast.success("Tersimpan");
      setEdit(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const del = async (u) => {
    if (!window.confirm(`Hapus user ${u.username}?`)) return;
    try { await api.delete(`/users/${u.id}`); toast.success("Dihapus"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Pengguna</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Manajemen Pengguna</h1>
        </div>
        <Button data-testid="add-user" onClick={openNew} className="bg-blue-700 hover:bg-blue-800"><Plus className="w-4 h-4 mr-2" /> Tambah</Button>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider"><tr>
              <th className="text-left p-3">Nama</th><th className="text-left p-3">Username</th>
              <th className="text-left p-3">Role</th><th className="text-left p-3">Status</th>
              <th className="text-right p-3">Aksi</th>
            </tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="p-3 font-semibold">{u.nama}</td>
                  <td className="p-3 font-mono text-xs">{u.username}</td>
                  <td className="p-3 capitalize">{u.role}</td>
                  <td className="p-3"><span className={`text-xs px-2 py-0.5 rounded ${u.status === "aktif" ? "bg-emerald-100 text-emerald-700" : u.status === "pending" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>{u.status === "pending" ? "menunggu aktivasi" : u.status}</span></td>
                  <td className="p-3 text-right">
                    <Button size="sm" variant="ghost" onClick={() => openEdit(u)}><Pencil className="w-4 h-4" /></Button>
                    {u.id !== me.id && <Button size="sm" variant="ghost" onClick={() => del(u)}><Trash2 className="w-4 h-4 text-red-500" /></Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{edit === "new" ? "User Baru" : `Edit ${edit?.username}`}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nama</Label><Input data-testid="user-nama" value={form.nama} onChange={(e) => setForm(f => ({ ...f, nama: e.target.value }))} /></div>
            <div><Label>Username</Label><Input data-testid="user-username" value={form.username} onChange={(e) => setForm(f => ({ ...f, username: e.target.value }))} disabled={edit !== "new"} /></div>
            <div><Label>{edit === "new" ? "Password" : "Password baru (kosongkan jika tidak diubah)"}</Label><Input data-testid="user-password" type="password" value={form.password} onChange={(e) => setForm(f => ({ ...f, password: e.target.value }))} /></div>
            <div>
              <Label>Role</Label>
              <select data-testid="user-role" value={form.role} onChange={(e) => setForm(f => ({ ...f, role: e.target.value }))} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white">
                <option value="resepsionis">Resepsionis</option>
                <option value="owner">Owner</option>
              </select>
            </div>
            {edit !== "new" && (
              <div>
                <Label>Status</Label>
                <select value={form.status || "aktif"} onChange={(e) => setForm(f => ({ ...f, status: e.target.value }))} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white">
                  <option value="aktif">Aktif</option>
                  <option value="nonaktif">Nonaktif</option>
                  {form.status === "pending" && <option value="pending">Menunggu Aktivasi</option>}
                </select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdit(null)}>Batal</Button>
            <Button data-testid="save-user" onClick={save} className="bg-blue-700 hover:bg-blue-800">Simpan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
