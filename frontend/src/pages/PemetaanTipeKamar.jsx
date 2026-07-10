import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { ArrowRight, Search, X, Pencil, Trash2, Plus, Download, Loader2, CheckCircle2, Wand2 } from "lucide-react";
import api, { fmtDateTime } from "@/lib/apiClient";

const SUMBER_BADGE = {
  Agoda: "bg-violet-100 text-violet-800",
  Traveloka: "bg-blue-100 text-blue-800",
  "Booking.com": "bg-amber-100 text-amber-800",
};

const ROOM_TYPE_OPTIONS = ["Standard", "Cottage"];
const SUMBER_FORM_OPTIONS = ["Agoda", "Traveloka", "Booking.com"];
const PMS_TIPE_OPTIONS = ["Semua", ...ROOM_TYPE_OPTIONS];
const SUMBER_OPTIONS = ["Semua", ...SUMBER_FORM_OPTIONS];

const emptyMappingForm = { ota_nama: "", pms_tipe: ROOM_TYPE_OPTIONS[0], sumber: SUMBER_FORM_OPTIONS[0] };

function MappingFormDialog({ open, onOpenChange, prefill, isEdit, onSave }) {
  const [form, setForm] = useState(prefill || emptyMappingForm);

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (o) setForm(prefill || emptyMappingForm); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="pemetaan-form-title">{isEdit ? "Ubah Pemetaan" : "Tambah Pemetaan"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div>
            <Label>Nama di OTA</Label>
            <Input
              data-testid="pemetaan-form-ota-nama"
              value={form.ota_nama}
              onChange={(e) => setForm((f) => ({ ...f, ota_nama: e.target.value }))}
              placeholder="Mis: Deluxe Room"
              className="mt-1.5"
            />
          </div>
          <div>
            <Label>Tipe Kamar PMS</Label>
            <select
              data-testid="pemetaan-form-tipe"
              value={form.pms_tipe}
              onChange={(e) => setForm((f) => ({ ...f, pms_tipe: e.target.value }))}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
            >
              {ROOM_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <Label>Sumber OTA</Label>
            <select
              data-testid="pemetaan-form-sumber"
              value={form.sumber}
              onChange={(e) => setForm((f) => ({ ...f, sumber: e.target.value }))}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
            >
              {SUMBER_FORM_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button
            data-testid="pemetaan-form-save"
            className="bg-blue-700 hover:bg-blue-800"
            disabled={!form.ota_nama.trim()}
            onClick={() => { onSave(form); onOpenChange(false); }}
          >
            Simpan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function PemetaanTipeKamar() {
  const [mappings, setMappings] = useState([]);
  const [search, setSearch] = useState("");
  const [pmsTipe, setPmsTipe] = useState("Semua");
  const [sumber, setSumber] = useState("Semua");
  const [unmapped, setUnmapped] = useState([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState(null); // id mapping yang diubah, null = tambah baru
  const [formPrefill, setFormPrefill] = useState(emptyMappingForm);
  const [resolvingUnmappedId, setResolvingUnmappedId] = useState(null);

  const load = () => {
    api.get("/mappings").then((r) => setMappings(r.data)).catch(() => toast.error("Gagal memuat pemetaan"));
    api.get("/unmapped-ota-rooms").then((r) => setUnmapped(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return mappings.filter((m) => {
      if (q && !m.ota_nama.toLowerCase().includes(q)) return false;
      if (pmsTipe !== "Semua" && m.pms_tipe !== pmsTipe) return false;
      if (sumber !== "Semua" && m.sumber !== sumber) return false;
      return true;
    });
  }, [mappings, search, pmsTipe, sumber]);

  const openAdd = () => { setEditingId(null); setFormPrefill(emptyMappingForm); setResolvingUnmappedId(null); setFormOpen(true); };
  const openEdit = (m) => { setEditingId(m.id); setFormPrefill(m); setResolvingUnmappedId(null); setFormOpen(true); };
  const openPetakan = (u) => {
    setEditingId(null);
    setFormPrefill({ ota_nama: u.ota_nama, sumber: u.sumber, pms_tipe: ROOM_TYPE_OPTIONS[0] });
    setResolvingUnmappedId(u.id);
    setFormOpen(true);
  };

  const saveMapping = async (form) => {
    try {
      if (editingId) {
        await api.put(`/mappings/${editingId}`, form);
        toast.success(`Pemetaan "${form.ota_nama}" diperbarui`);
      } else {
        await api.post("/mappings", form);
        toast.success(`Pemetaan "${form.ota_nama}" ditambahkan`);
      }
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan pemetaan");
    }
  };

  const deleteMapping = async (m) => {
    if (!window.confirm(`Hapus pemetaan "${m.ota_nama}" (${m.sumber}) → ${m.pms_tipe}?`)) return;
    try {
      await api.delete(`/mappings/${m.id}`);
      toast.success("Pemetaan dihapus");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menghapus pemetaan");
    }
  };

  const resetFilters = () => { setSearch(""); setPmsTipe("Semua"); setSumber("Semua"); };
  const hasActiveFilter = search || pmsTipe !== "Semua" || sumber !== "Semua";

  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const imporDariPMS = async () => {
    setImporting(true);
    try {
      const { data } = await api.post("/pms-room-types/sync");
      setImportResult(data);
      toast.success(`${data.tipe.length} tipe kamar berhasil diimpor dari Pelangi PMS`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal impor dari PMS");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="pemetaan-tipe-kamar-page">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Pemetaan Tipe Kamar</h1>
          <p className="text-slate-500 mt-1">
            Samakan nama tipe kamar di tiap OTA dengan tipe kamar yang dipakai Pelangi PMS.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button data-testid="pemetaan-impor-pms" variant="outline" onClick={imporDariPMS} disabled={importing} className="gap-1.5">
            {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} {importing ? "Mengimpor…" : "Impor dari PMS"}
          </Button>
          <Button data-testid="pemetaan-tambah" onClick={openAdd} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
            <Plus className="w-3.5 h-3.5" /> Tambah Pemetaan
          </Button>
        </div>
      </div>

      {importResult && (
        <Card className="border-emerald-300 bg-emerald-50" data-testid="pemetaan-import-result">
          <CardContent className="p-3 flex items-center gap-2 text-sm text-emerald-800">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            Tipe kamar Pelangi PMS saat ini: <b>{importResult.tipe.join(", ")}</b> &bull; diimpor {fmtDateTime(importResult.waktu)}
          </CardContent>
        </Card>
      )}

      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <Label htmlFor="pemetaan-search">Cari nama di OTA</Label>
            <div className="relative mt-1.5">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <Input
                id="pemetaan-search"
                data-testid="pemetaan-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Mis: Deluxe Room…"
                className="pl-9"
              />
            </div>
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="pemetaan-tipe">Tipe Kamar PMS</Label>
            <select
              id="pemetaan-tipe"
              data-testid="pemetaan-filter-tipe"
              value={pmsTipe}
              onChange={(e) => setPmsTipe(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {PMS_TIPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="pemetaan-sumber">Sumber OTA</Label>
            <select
              id="pemetaan-sumber"
              data-testid="pemetaan-filter-sumber"
              value={sumber}
              onChange={(e) => setSumber(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {SUMBER_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {hasActiveFilter && (
            <Button data-testid="pemetaan-reset-filter" variant="ghost" size="sm" onClick={resetFilters} className="gap-1.5">
              <X className="w-3.5 h-3.5" /> Reset
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm" data-testid="pemetaan-table">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Nama di OTA</th>
                <th className="text-left p-3"></th>
                <th className="text-left p-3">Tipe Kamar PMS</th>
                <th className="text-left p-3">Sumber</th>
                <th className="text-right p-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((m) => (
                <tr key={m.id} data-testid={`pemetaan-row-${m.id}`} className="border-t border-slate-100">
                  <td className="p-3 font-medium">{m.ota_nama}</td>
                  <td className="p-3 text-slate-300"><ArrowRight className="w-4 h-4" /></td>
                  <td className="p-3 font-semibold text-blue-700">{m.pms_tipe}</td>
                  <td className="p-3">
                    <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${SUMBER_BADGE[m.sumber] || "bg-slate-100 text-slate-600"}`}>{m.sumber}</span>
                  </td>
                  <td className="p-3">
                    <div className="flex justify-end gap-1">
                      <Button data-testid={`pemetaan-edit-${m.id}`} variant="ghost" size="icon" onClick={() => openEdit(m)}>
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      <Button data-testid={`pemetaan-delete-${m.id}`} variant="ghost" size="icon" onClick={() => deleteMapping(m)} className="text-red-600 hover:bg-red-50">
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={5} className="p-6 text-center text-slate-500">Tidak ada pemetaan yang cocok dengan pencarian/filter</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {unmapped.length > 0 && (
        <Card className="border-amber-300 bg-amber-50">
          <CardContent className="p-4 space-y-3">
            <h3 className="text-sm font-semibold text-amber-900">Tipe Kamar OTA Belum Dipetakan</h3>
            <p className="text-xs text-amber-800 -mt-2">Terdeteksi AI Email Parser dari email OTA masuk, tapi belum ada pemetaannya ke tipe kamar PMS.</p>
            <div className="space-y-2" data-testid="unmapped-list">
              {unmapped.map((u) => (
                <div key={u.id} className="bg-white border border-amber-200 rounded-lg p-3 flex items-center justify-between gap-3" data-testid={`unmapped-item-${u.id}`}>
                  <div>
                    <span className="font-medium text-sm">{u.ota_nama}</span>
                    <span className={`ml-2 inline-flex px-2 py-0.5 rounded-md text-xs font-medium ${SUMBER_BADGE[u.sumber] || "bg-slate-100 text-slate-600"}`}>{u.sumber}</span>
                    <span className="ml-2 text-xs text-slate-400">muncul {u.jumlah_kemunculan}x</span>
                  </div>
                  <Button data-testid={`unmapped-petakan-${u.id}`} size="sm" onClick={() => openPetakan(u)} className="gap-1.5 bg-amber-600 hover:bg-amber-700 shrink-0">
                    <Wand2 className="w-3.5 h-3.5" /> Petakan
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <MappingFormDialog open={formOpen} onOpenChange={setFormOpen} prefill={formPrefill} isEdit={!!editingId} onSave={saveMapping} />
    </div>
  );
}
