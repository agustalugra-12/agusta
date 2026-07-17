import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Pencil, Trash2, Plus, CheckCircle2, XCircle } from "lucide-react";
import api from "@/lib/apiClient";

const CATEGORY_LABEL = {
  dp: "DP / Uang Muka", cancellation: "Pembatalan / Refund", checkin: "Check-in",
  checkout: "Check-out", promo: "Promo", smoking: "Merokok", pet: "Hewan Peliharaan", other: "Lainnya",
};
const CATEGORY_OPTIONS = Object.keys(CATEGORY_LABEL);

const emptyForm = { category: "dp", title: "", description: "", is_active: true };

function RuleFormDialog({ open, onOpenChange, prefill, isEdit, onSave }) {
  const [form, setForm] = useState(prefill || emptyForm);

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (o) setForm(prefill || emptyForm); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="rule-form-title">{isEdit ? "Ubah Business Rule" : "Tambah Business Rule"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div>
            <Label>Kategori</Label>
            <select
              data-testid="rule-form-category"
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
            >
              {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
            </select>
          </div>
          <div>
            <Label>Judul</Label>
            <Input data-testid="rule-form-title-input" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              placeholder="Mis: DP Minimal Booking Menginap" className="mt-1.5" />
          </div>
          <div>
            <Label>Deskripsi (ini yang dibaca AI untuk menjawab tamu — tulis jelas & lengkap)</Label>
            <Textarea data-testid="rule-form-description" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="Mis: DP minimal 50% dari total tagihan, dibayar saat konfirmasi booking. Sisa dibayar saat check-in."
              rows={4} className="mt-1.5" />
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" data-testid="rule-form-active" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
            <span className="text-sm">Aktif (dipakai AI untuk menjawab tamu)</span>
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button
            data-testid="rule-form-save"
            className="bg-blue-700 hover:bg-blue-800"
            disabled={!form.title.trim() || !form.description.trim()}
            onClick={() => { onSave(form); onOpenChange(false); }}
          >
            Simpan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function BusinessRules() {
  const [rules, setRules] = useState([]);
  const [category, setCategory] = useState("Semua");
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formPrefill, setFormPrefill] = useState(emptyForm);

  const load = () => {
    api.get("/business-rules").then((r) => setRules(r.data)).catch(() => toast.error("Gagal memuat business rules"));
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    if (category === "Semua") return rules;
    return rules.filter((r) => r.category === category);
  }, [rules, category]);

  const openAdd = () => { setEditingId(null); setFormPrefill(emptyForm); setFormOpen(true); };
  const openEdit = (r) => { setEditingId(r.id); setFormPrefill(r); setFormOpen(true); };

  const saveRule = async (form) => {
    try {
      if (editingId) {
        await api.put(`/business-rules/${editingId}`, form);
        toast.success(`Rule "${form.title}" diperbarui`);
      } else {
        await api.post("/business-rules", form);
        toast.success(`Rule "${form.title}" ditambahkan`);
      }
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan rule");
    }
  };

  const deleteRule = async (r) => {
    if (!window.confirm(`Hapus rule "${r.title}"?`)) return;
    try {
      await api.delete(`/business-rules/${r.id}`);
      toast.success("Rule dihapus");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menghapus rule");
    }
  };

  return (
    <div className="space-y-6" data-testid="business-rules-page">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Business Platform</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Business Rules</h1>
          <p className="text-slate-500 mt-1">
            Kebijakan operasional (DP, pembatalan, check-in/out, promo, dst) — PMS adalah satu-satunya
            sumber kebenaran, ditarik AI Chat Bot untuk menjawab tamu secara akurat.
          </p>
        </div>
        <Button data-testid="rule-tambah" onClick={openAdd} className="gap-1.5 bg-blue-700 hover:bg-blue-800 shrink-0">
          <Plus className="w-3.5 h-3.5" /> Tambah Rule
        </Button>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="w-full sm:w-56">
            <Label htmlFor="rule-filter-category">Kategori</Label>
            <select
              id="rule-filter-category" data-testid="rule-filter-category"
              value={category} onChange={(e) => setCategory(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              <option value="Semua">Semua</option>
              {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
            </select>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {filtered.map((r) => (
          <Card key={r.id} data-testid={`rule-row-${r.id}`} className="border-slate-200">
            <CardContent className="p-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="inline-flex px-2 py-0.5 rounded-md text-xs font-medium bg-blue-100 text-blue-800">{CATEGORY_LABEL[r.category] || r.category}</span>
                  {r.is_active
                    ? <span className="inline-flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="w-3 h-3" /> Aktif</span>
                    : <span className="inline-flex items-center gap-1 text-xs text-slate-400"><XCircle className="w-3 h-3" /> Nonaktif</span>}
                </div>
                <div className="font-semibold mt-1.5">{r.title}</div>
                <div className="text-sm text-slate-600 mt-0.5 whitespace-pre-wrap">{r.description}</div>
              </div>
              <div className="flex gap-1 shrink-0">
                <Button data-testid={`rule-edit-${r.id}`} variant="ghost" size="icon" onClick={() => openEdit(r)}>
                  <Pencil className="w-3.5 h-3.5" />
                </Button>
                <Button data-testid={`rule-delete-${r.id}`} variant="ghost" size="icon" onClick={() => deleteRule(r)} className="text-red-600 hover:bg-red-50">
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {filtered.length === 0 && (
          <Card className="border-slate-200"><CardContent className="p-6 text-center text-slate-500 text-sm">Belum ada business rule. Klik "Tambah Rule" untuk mulai.</CardContent></Card>
        )}
      </div>

      <RuleFormDialog open={formOpen} onOpenChange={setFormOpen} prefill={formPrefill} isEdit={!!editingId} onSave={saveRule} />
    </div>
  );
}
