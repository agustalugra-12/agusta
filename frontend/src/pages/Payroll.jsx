import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDate } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Plus, Trash2, PencilLine, CheckCircle2, MessageCircle } from "lucide-react";

const todayPeriode = () => new Date().toISOString().slice(0, 7);

export default function Payroll() {
  const [tab, setTab] = useState("staf");
  return (
    <div className="space-y-6" data-testid="payroll-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Payroll</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Penggajian Staf</h1>
        <p className="text-slate-500 mt-1">Data staf, kasbon, dan proses payroll bulanan — semua nominal bisa diisi/diedit manual.</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="staf" data-testid="tab-staf">Data Staf</TabsTrigger>
          <TabsTrigger value="kasbon" data-testid="tab-kasbon">Kasbon</TabsTrigger>
          <TabsTrigger value="payroll" data-testid="tab-payroll">Payroll</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === "staf" && <StafTab />}
      {tab === "kasbon" && <KasbonTab />}
      {tab === "payroll" && <PayrollTab />}
    </div>
  );
}

// ---------------- Data Staf ----------------

const emptyStaf = { nama: "", posisi: "", no_hp: "", gaji_pokok: "", aktif: true, catatan: "" };

function StafTab() {
  const [staff, setStaff] = useState([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyStaf);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const { data } = await api.get("/staff-profil");
    setStaff(data);
  };
  useEffect(() => { load(); }, []);

  const openAdd = () => { setEditing(null); setForm(emptyStaf); setFormOpen(true); };
  const openEdit = (s) => {
    setEditing(s);
    setForm({ nama: s.nama, posisi: s.posisi || "", no_hp: s.no_hp || "", gaji_pokok: String(s.gaji_pokok || 0), aktif: s.aktif, catatan: s.catatan || "" });
    setFormOpen(true);
  };

  const save = async () => {
    if (!form.nama.trim()) { toast.error("Nama wajib diisi"); return; }
    setSaving(true);
    try {
      const payload = { ...form, gaji_pokok: parseInt(form.gaji_pokok, 10) || 0 };
      if (editing) {
        await api.put(`/staff-profil/${editing.id}`, payload);
        toast.success(`Data ${form.nama} diperbarui`);
      } else {
        await api.post("/staff-profil", payload);
        toast.success(`Staf ${form.nama} ditambahkan`);
      }
      setFormOpen(false);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan"); }
    finally { setSaving(false); }
  };

  const hapus = async (s) => {
    if (!window.confirm(`Hapus staf ${s.nama}? Tindakan ini tidak dapat diurungkan.`)) return;
    try {
      await api.delete(`/staff-profil/${s.id}`);
      toast.success(`${s.nama} dihapus`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button data-testid="btn-tambah-staf" onClick={openAdd} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
          <Plus className="w-4 h-4" /> Tambah Staf
        </Button>
      </div>
      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="text-left p-3">Nama</th>
                <th className="text-left p-3">Posisi</th>
                <th className="text-left p-3">Gaji Pokok</th>
                <th className="text-left p-3">Kasbon Aktif</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {staff.map((s) => (
                <tr key={s.id} data-testid={`staf-row-${s.nama}`} className="border-t border-slate-100">
                  <td className="p-3 font-bold">{s.nama}</td>
                  <td className="p-3">{s.posisi || "-"}</td>
                  <td className="p-3">{fmtRp(s.gaji_pokok)}</td>
                  <td className="p-3">{s.kasbon_aktif > 0 ? <span className="text-amber-700 font-semibold">{fmtRp(s.kasbon_aktif)}</span> : "-"}</td>
                  <td className="p-3">
                    <span className={`px-2 py-1 rounded-md text-xs font-medium ${s.aktif ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-600"}`}>
                      {s.aktif ? "Aktif" : "Nonaktif"}
                    </span>
                  </td>
                  <td className="p-3">
                    <Button size="sm" variant="outline" onClick={() => openEdit(s)} className="gap-1"><PencilLine className="w-3.5 h-3.5" /> Ubah</Button>
                    <Button size="sm" variant="ghost" onClick={() => hapus(s)} className="gap-1 text-red-600 ml-1"><Trash2 className="w-3.5 h-3.5" /></Button>
                  </td>
                </tr>
              ))}
              {staff.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-slate-500">Belum ada data staf - klik "Tambah Staf" untuk mulai</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? `Ubah ${editing.nama}` : "Tambah Staf"}</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <div><Label>Nama</Label><Input data-testid="input-staf-nama" value={form.nama} onChange={(e) => setForm((f) => ({ ...f, nama: e.target.value }))} /></div>
            <div><Label>Posisi</Label><Input data-testid="input-staf-posisi" value={form.posisi} onChange={(e) => setForm((f) => ({ ...f, posisi: e.target.value }))} placeholder="mis. Resepsionis, Housekeeping" /></div>
            <div><Label>Nomor WhatsApp</Label><Input data-testid="input-staf-nohp" value={form.no_hp} onChange={(e) => setForm((f) => ({ ...f, no_hp: e.target.value }))} placeholder="untuk kirim slip gaji, mis. 08123456789" /></div>
            <div><Label>Gaji Pokok / Bulan (Rp)</Label><Input data-testid="input-staf-gaji" type="number" value={form.gaji_pokok} onChange={(e) => setForm((f) => ({ ...f, gaji_pokok: e.target.value }))} /></div>
            <div className="flex items-center gap-2"><Switch checked={form.aktif} onCheckedChange={(v) => setForm((f) => ({ ...f, aktif: v }))} /><Label>Aktif</Label></div>
            <div><Label>Catatan (opsional)</Label><Input value={form.catatan} onChange={(e) => setForm((f) => ({ ...f, catatan: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setFormOpen(false)}>Batal</Button>
            <Button data-testid="btn-simpan-staf" onClick={save} disabled={saving} className="bg-blue-700 hover:bg-blue-800">Simpan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------- Kasbon ----------------

const emptyKasbon = { staff_id: "", nominal: "", tanggal: new Date().toISOString().slice(0, 10), alasan: "" };

function KasbonTab() {
  const [kasbon, setKasbon] = useState([]);
  const [staff, setStaff] = useState([]);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(emptyKasbon);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [{ data: k }, { data: s }] = await Promise.all([api.get("/kasbon"), api.get("/staff-profil")]);
    setKasbon(k);
    setStaff(s);
  };
  useEffect(() => { load(); }, []);

  const openAdd = () => { setForm({ ...emptyKasbon, staff_id: staff[0]?.id || "" }); setFormOpen(true); };

  const save = async () => {
    if (!form.staff_id) { toast.error("Pilih staf dulu"); return; }
    const nominal = parseInt(form.nominal, 10) || 0;
    if (nominal <= 0) { toast.error("Nominal kasbon harus lebih dari 0"); return; }
    setSaving(true);
    try {
      await api.post("/kasbon", { ...form, nominal });
      toast.success("Kasbon dicatat");
      setFormOpen(false);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan"); }
    finally { setSaving(false); }
  };

  const hapus = async (k) => {
    if (!window.confirm(`Hapus catatan kasbon ${k.staff_nama} (${fmtRp(k.nominal)})?`)) return;
    try {
      await api.delete(`/kasbon/${k.id}`);
      toast.success("Kasbon dihapus");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  const tandaiLunas = async (k) => {
    try {
      await api.put(`/kasbon/${k.id}`, { sisa: 0 });
      toast.success(`Kasbon ${k.staff_nama} ditandai lunas`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button data-testid="btn-tambah-kasbon" onClick={openAdd} disabled={staff.length === 0} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
          <Plus className="w-4 h-4" /> Catat Kasbon
        </Button>
      </div>
      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="text-left p-3">Tanggal</th>
                <th className="text-left p-3">Staf</th>
                <th className="text-left p-3">Nominal</th>
                <th className="text-left p-3">Sisa</th>
                <th className="text-left p-3">Alasan</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {kasbon.map((k) => (
                <tr key={k.id} className="border-t border-slate-100">
                  <td className="p-3">{fmtDate(k.tanggal)}</td>
                  <td className="p-3 font-semibold">{k.staff_nama}</td>
                  <td className="p-3">{fmtRp(k.nominal)}</td>
                  <td className="p-3">{fmtRp(k.sisa)}</td>
                  <td className="p-3 text-slate-500">{k.alasan || "-"}</td>
                  <td className="p-3">
                    <span className={`px-2 py-1 rounded-md text-xs font-medium ${k.lunas ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                      {k.lunas ? "Lunas" : "Belum Lunas"}
                    </span>
                  </td>
                  <td className="p-3 flex gap-1">
                    {!k.lunas && <Button size="sm" variant="outline" onClick={() => tandaiLunas(k)} className="gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> Lunas</Button>}
                    <Button size="sm" variant="ghost" onClick={() => hapus(k)} className="gap-1 text-red-600"><Trash2 className="w-3.5 h-3.5" /></Button>
                  </td>
                </tr>
              ))}
              {kasbon.length === 0 && (
                <tr><td colSpan={7} className="p-6 text-center text-slate-500">Belum ada catatan kasbon</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Catat Kasbon</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <div>
              <Label>Staf</Label>
              <select data-testid="select-kasbon-staf" className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
                value={form.staff_id} onChange={(e) => setForm((f) => ({ ...f, staff_id: e.target.value }))}>
                {staff.map((s) => <option key={s.id} value={s.id}>{s.nama}</option>)}
              </select>
            </div>
            <div><Label>Nominal (Rp)</Label><Input data-testid="input-kasbon-nominal" type="number" value={form.nominal} onChange={(e) => setForm((f) => ({ ...f, nominal: e.target.value }))} /></div>
            <div><Label>Tanggal</Label><Input type="date" value={form.tanggal} onChange={(e) => setForm((f) => ({ ...f, tanggal: e.target.value }))} /></div>
            <div><Label>Alasan (opsional)</Label><Input value={form.alasan} onChange={(e) => setForm((f) => ({ ...f, alasan: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setFormOpen(false)}>Batal</Button>
            <Button data-testid="btn-simpan-kasbon" onClick={save} disabled={saving} className="bg-blue-700 hover:bg-blue-800">Simpan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------- Payroll ----------------

function PayrollTab() {
  const [periode, setPeriode] = useState(todayPeriode());
  const [payroll, setPayroll] = useState([]);
  const [staff, setStaff] = useState([]);
  const [formOpen, setFormOpen] = useState(false);
  const [newStaffId, setNewStaffId] = useState("");
  const [selected, setSelected] = useState(null);
  const [editForm, setEditForm] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [{ data: p }, { data: s }] = await Promise.all([
      api.get("/payroll", { params: { periode } }),
      api.get("/staff-profil", { params: { aktif: true } }),
    ]);
    setPayroll(p);
    setStaff(s);
  };
  useEffect(() => { load(); }, [periode]);

  const staffTanpaPayroll = staff.filter((s) => !payroll.some((p) => p.staff_id === s.id));

  const buatPayroll = async () => {
    if (!newStaffId) { toast.error("Pilih staf dulu"); return; }
    try {
      const { data } = await api.post("/payroll", { staff_id: newStaffId, periode });
      toast.success(`Payroll ${data.staff_nama} dibuat (draft) - silakan cek & sesuaikan nominalnya`);
      setFormOpen(false);
      setNewStaffId("");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal membuat payroll"); }
  };

  const openDetail = (p) => {
    setSelected(p);
    setEditForm({
      gaji_pokok: String(p.gaji_pokok), service_charge: String(p.service_charge),
      tunjangan_lain: String(p.tunjangan_lain), potongan_kasbon: String(p.potongan_kasbon),
      potongan_lain: String(p.potongan_lain), catatan: p.catatan || "",
    });
  };

  const totalPreview = editForm
    ? (parseInt(editForm.gaji_pokok || 0, 10) + parseInt(editForm.service_charge || 0, 10) + parseInt(editForm.tunjangan_lain || 0, 10))
      - (parseInt(editForm.potongan_kasbon || 0, 10) + parseInt(editForm.potongan_lain || 0, 10))
    : 0;

  const simpanEdit = async () => {
    setSaving(true);
    try {
      await api.put(`/payroll/${selected.id}`, {
        gaji_pokok: parseInt(editForm.gaji_pokok, 10) || 0,
        service_charge: parseInt(editForm.service_charge, 10) || 0,
        tunjangan_lain: parseInt(editForm.tunjangan_lain, 10) || 0,
        potongan_kasbon: parseInt(editForm.potongan_kasbon, 10) || 0,
        potongan_lain: parseInt(editForm.potongan_lain, 10) || 0,
        catatan: editForm.catatan,
      });
      toast.success("Payroll diperbarui");
      setSelected(null);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan"); }
    finally { setSaving(false); }
  };

  const tandaiDibayar = async () => {
    if (!window.confirm(`Tandai payroll ${selected.staff_nama} sebagai DIBAYAR? Kasbon akan terpotong permanen dan data tidak bisa diedit lagi setelah ini.`)) return;
    try {
      await api.post(`/payroll/${selected.id}/tandai-dibayar`);
      toast.success(`Payroll ${selected.staff_nama} ditandai dibayar`);
      setSelected(null);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const hapusDraft = async (p) => {
    if (!window.confirm(`Hapus draft payroll ${p.staff_nama} periode ${p.periode}?`)) return;
    try {
      await api.delete(`/payroll/${p.id}`);
      toast.success("Draft dihapus");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  const [sendingWa, setSendingWa] = useState(false);
  const kirimWa = async () => {
    setSendingWa(true);
    try {
      await api.post(`/payroll/${selected.id}/kirim-wa`);
      toast.success(`Slip gaji ${selected.staff_nama} terkirim ke WhatsApp`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal mengirim ke WhatsApp"); }
    finally { setSendingWa(false); }
  };

  return (
    <div className="space-y-4">
      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div>
            <Label htmlFor="payroll-periode">Periode</Label>
            <Input id="payroll-periode" data-testid="input-periode" type="month" value={periode} onChange={(e) => setPeriode(e.target.value)} className="mt-1.5" />
          </div>
          <div className="flex-1" />
          <Button data-testid="btn-buat-payroll" onClick={() => setFormOpen(true)} disabled={staffTanpaPayroll.length === 0} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
            <Plus className="w-4 h-4" /> Buat Payroll
          </Button>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="text-left p-3">Staf</th>
                <th className="text-left p-3">Gaji Pokok</th>
                <th className="text-left p-3">Service</th>
                <th className="text-left p-3">Potongan Kasbon</th>
                <th className="text-left p-3">Total Diterima</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {payroll.map((p) => (
                <tr key={p.id} data-testid={`payroll-row-${p.staff_nama}`} className="border-t border-slate-100 cursor-pointer hover:bg-slate-50" onClick={() => openDetail(p)}>
                  <td className="p-3 font-bold">{p.staff_nama}</td>
                  <td className="p-3">{fmtRp(p.gaji_pokok)}</td>
                  <td className="p-3">{fmtRp(p.service_charge)}</td>
                  <td className="p-3">{p.potongan_kasbon > 0 ? <span className="text-amber-700">-{fmtRp(p.potongan_kasbon)}</span> : "-"}</td>
                  <td className="p-3 font-bold text-blue-700">{fmtRp(p.total_diterima)}</td>
                  <td className="p-3">
                    <span className={`px-2 py-1 rounded-md text-xs font-medium ${p.status === "dibayar" ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-600"}`}>
                      {p.status === "dibayar" ? "Dibayar" : "Draft"}
                    </span>
                  </td>
                  <td className="p-3">
                    {p.status === "draft" && (
                      <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); hapusDraft(p); }} className="gap-1 text-red-600"><Trash2 className="w-3.5 h-3.5" /></Button>
                    )}
                  </td>
                </tr>
              ))}
              {payroll.length === 0 && (
                <tr><td colSpan={7} className="p-6 text-center text-slate-500">Belum ada payroll untuk periode ini</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Buat Payroll — {periode}</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <div>
              <Label>Staf</Label>
              <select data-testid="select-payroll-staf" className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
                value={newStaffId} onChange={(e) => setNewStaffId(e.target.value)}>
                <option value="">Pilih staf...</option>
                {staffTanpaPayroll.map((s) => <option key={s.id} value={s.id}>{s.nama}</option>)}
              </select>
            </div>
            <p className="text-xs text-slate-500">Gaji pokok & potongan kasbon otomatis terisi dari data staf, bisa diubah lagi sebelum ditandai dibayar.</p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setFormOpen(false)}>Batal</Button>
            <Button data-testid="btn-simpan-buat-payroll" onClick={buatPayroll} className="bg-blue-700 hover:bg-blue-800">Buat Draft</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) setSelected(null); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Payroll {selected?.staff_nama} — {selected?.periode}</DialogTitle></DialogHeader>
          {selected && editForm && (
            <div className="space-y-3 text-sm" data-testid="payroll-detail-form">
              {selected.status === "dibayar" && (
                <p className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded p-2">
                  Sudah dibayar {fmtDate(selected.dibayar_at)} oleh {selected.dibayar_by} - tidak bisa diedit lagi.
                </p>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Gaji Pokok</Label><Input type="number" disabled={selected.status === "dibayar"} value={editForm.gaji_pokok} onChange={(e) => setEditForm((f) => ({ ...f, gaji_pokok: e.target.value }))} /></div>
                <div><Label>Service Charge</Label><Input type="number" disabled={selected.status === "dibayar"} value={editForm.service_charge} onChange={(e) => setEditForm((f) => ({ ...f, service_charge: e.target.value }))} /></div>
                <div><Label>Tunjangan Lain</Label><Input type="number" disabled={selected.status === "dibayar"} value={editForm.tunjangan_lain} onChange={(e) => setEditForm((f) => ({ ...f, tunjangan_lain: e.target.value }))} /></div>
                <div><Label>Potongan Kasbon</Label><Input type="number" disabled={selected.status === "dibayar"} value={editForm.potongan_kasbon} onChange={(e) => setEditForm((f) => ({ ...f, potongan_kasbon: e.target.value }))} /></div>
                <div><Label>Potongan Lain</Label><Input type="number" disabled={selected.status === "dibayar"} value={editForm.potongan_lain} onChange={(e) => setEditForm((f) => ({ ...f, potongan_lain: e.target.value }))} /></div>
              </div>
              <div><Label>Catatan</Label><Input disabled={selected.status === "dibayar"} value={editForm.catatan} onChange={(e) => setEditForm((f) => ({ ...f, catatan: e.target.value }))} /></div>
              <div className="bg-slate-50 border border-slate-200 rounded p-3 flex justify-between items-center">
                <span className="font-semibold text-slate-600">Total Diterima</span>
                <span className="font-bold text-lg text-blue-700" data-testid="payroll-total-preview">{fmtRp(selected.status === "dibayar" ? selected.total_diterima : totalPreview)}</span>
              </div>
            </div>
          )}
          <DialogFooter className="flex-wrap gap-2">
            <Button data-testid="btn-kirim-wa-payroll" variant="outline" onClick={kirimWa} disabled={sendingWa} className="gap-1.5 text-emerald-700 border-emerald-300 hover:bg-emerald-50">
              <MessageCircle className="w-4 h-4" /> {sendingWa ? "Mengirim..." : "Kirim WA"}
            </Button>
            {selected?.status === "draft" && (
              <>
                <Button variant="ghost" onClick={() => setSelected(null)}>Tutup</Button>
                <Button data-testid="btn-simpan-payroll" variant="outline" onClick={simpanEdit} disabled={saving}>Simpan Perubahan</Button>
                <Button data-testid="btn-tandai-dibayar" onClick={tandaiDibayar} className="bg-emerald-600 hover:bg-emerald-700 gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> Tandai Dibayar
                </Button>
              </>
            )}
            {selected?.status === "dibayar" && <Button variant="ghost" onClick={() => setSelected(null)}>Tutup</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
