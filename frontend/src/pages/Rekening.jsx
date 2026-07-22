import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDate } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Plus, Trash2, PencilLine, ArrowRightLeft, Sparkles, AlertTriangle,
  Upload, Wallet, PiggyBank, Landmark, TrendingDown, Zap,
} from "lucide-react";

const JENIS_LABEL = { operasional: "Operasional", tabungan: "Tabungan", pinjaman: "Pinjaman" };
const JENIS_ICON = { operasional: Wallet, tabungan: PiggyBank, pinjaman: Landmark };

export default function Rekening() {
  const [tab, setTab] = useState("dashboard");
  return (
    <div className="space-y-6" data-testid="rekening-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Cash & Account Intelligence</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Cash & Rekening</h1>
        <p className="text-slate-500 mt-1">Posisi kas per rekening, transfer internal, target tabungan, & insight AI — bukan pengganti Laporan Keuangan, ini lapisan "uang ada di mana" di atasnya.</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="dashboard" data-testid="tab-rekening-dashboard">Dashboard</TabsTrigger>
          <TabsTrigger value="rekening" data-testid="tab-rekening-list">Rekening</TabsTrigger>
          <TabsTrigger value="transaksi" data-testid="tab-rekening-transaksi">Transaksi & Transfer</TabsTrigger>
          <TabsTrigger value="smart" data-testid="tab-rekening-smart">Smart Allocation</TabsTrigger>
          <TabsTrigger value="rekonsiliasi" data-testid="tab-rekening-rekonsiliasi">Rekonsiliasi CSV</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === "dashboard" && <DashboardTab />}
      {tab === "rekening" && <RekeningTab />}
      {tab === "transaksi" && <TransaksiTab />}
      {tab === "smart" && <SmartTab />}
      {tab === "rekonsiliasi" && <RekonsiliasiTab />}
    </div>
  );
}

// ---------------- Dashboard ----------------

function StatCard({ label, value, sub, icon: Icon, tone = "default" }) {
  const toneClass = tone === "danger" ? "text-red-600" : tone === "muted" ? "text-slate-500" : "text-slate-900";
  return (
    <Card className="border-slate-200">
      <CardContent className="p-5">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
          {Icon && <Icon className="w-4 h-4 text-slate-400" />}
        </div>
        <p className={`text-2xl font-extrabold mt-1 ${toneClass}`}>{fmtRp(value)}</p>
        {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function DashboardTab() {
  const [dash, setDash] = useState(null);
  const [insight, setInsight] = useState("");
  const [insightLoading, setInsightLoading] = useState(true);
  const [risk, setRisk] = useState([]);

  const load = async () => {
    const [{ data: d }, { data: r }] = await Promise.all([
      api.get("/rekening/dashboard"), api.get("/rekening/cash-risk"),
    ]);
    setDash(d); setRisk(r);
  };
  const loadInsight = async () => {
    setInsightLoading(true);
    try {
      const { data } = await api.get("/rekening/insight");
      setInsight(data.insight);
    } finally { setInsightLoading(false); }
  };
  useEffect(() => { load(); loadInsight(); }, []);

  if (!dash) return <div className="text-slate-500 text-sm">Memuat…</div>;

  if (dash.rekening.length === 0) {
    return (
      <Card className="border-slate-200 border-dashed">
        <CardContent className="p-10 text-center text-slate-500">
          <Landmark className="w-8 h-8 mx-auto mb-3 opacity-40" />
          Belum ada rekening. Tambahkan dulu di tab "Rekening".
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label="Total Cash" value={dash.total_cash} icon={Wallet} />
        <StatCard label="Operasional" value={dash.operasional} icon={Wallet} />
        <StatCard label="Tabungan" value={dash.tabungan} icon={PiggyBank} />
        <StatCard label="Pinjaman" value={dash.pinjaman} icon={Landmark} tone={dash.pinjaman > 0 ? "danger" : "muted"} />
        <StatCard label="Net Cash" value={dash.net_cash} tone={dash.net_cash < 0 ? "danger" : "default"} />
      </div>

      <Card className="border-slate-200 bg-teal-50/40">
        <CardContent className="p-5">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-4 h-4 text-blue-700" />
            <p className="font-bold text-sm">Executive Insight</p>
          </div>
          <p className="text-sm text-slate-700 whitespace-pre-line">{insightLoading ? "Menyusun ringkasan…" : insight}</p>
        </CardContent>
      </Card>

      {risk.some((r) => r.status !== "aman") && (
        <Card className="border-amber-300 bg-amber-50">
          <CardContent className="p-5 space-y-2">
            <div className="flex items-center gap-2 font-bold text-sm text-amber-800"><AlertTriangle className="w-4 h-4" /> Cash Risk</div>
            {risk.filter((r) => r.status !== "aman").map((r) => (
              <div key={r.rekening_id} className="text-sm flex items-center justify-between">
                <span>{r.nama}</span>
                <Badge className={r.status === "risiko_tinggi" ? "bg-red-600" : "bg-amber-500"}>{r.keterangan}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {dash.goals.length > 0 && (
        <div>
          <h3 className="font-bold mb-3">Progress Target Tabungan</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {dash.goals.map((g) => (
              <Card key={g.id} className="border-slate-200">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between mb-1">
                    <p className="font-semibold">{g.nama}</p>
                    <span className="text-xs text-slate-500">{g.progress_persen}%</span>
                  </div>
                  <Progress value={g.progress_persen} className="mb-2" />
                  <p className="text-xs text-slate-500">{fmtRp(g.saldo)} / {fmtRp(g.target)}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {dash.transfer_terakhir.length > 0 && (
        <div>
          <h3 className="font-bold mb-3">Transfer Internal Terakhir</h3>
          <Card className="border-slate-200">
            <CardContent className="p-4 divide-y divide-slate-100">
              {dash.transfer_terakhir.map((t) => (
                <div key={t.transfer_id} className="py-2.5 flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{t.dari}</span>
                    <ArrowRightLeft className="w-3.5 h-3.5 text-slate-400" />
                    <span className="font-medium">{t.ke}</span>
                  </div>
                  <span className="font-bold">{fmtRp(t.nominal)}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

// ---------------- Rekening (CRUD) ----------------

const emptyRekening = { nama: "", bank: "", no_rekening: "", pemilik: "", jenis: "operasional", saldo_awal: "", target: "", warna: "#0F4C5C" };

function RekeningTab() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyRekening);
  const [saving, setSaving] = useState(false);

  const load = async () => setItems((await api.get("/rekening")).data);
  useEffect(() => { load(); }, []);

  const openAdd = () => { setForm(emptyRekening); setOpen(true); };

  const save = async () => {
    if (!form.nama || !form.jenis) return toast.error("Nama & jenis wajib diisi");
    setSaving(true);
    try {
      await api.post("/rekening", {
        ...form,
        saldo_awal: Number(form.saldo_awal || 0),
        target: form.jenis === "tabungan" && form.target ? Number(form.target) : null,
      });
      toast.success("Rekening ditambahkan"); setOpen(false); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan"); }
    finally { setSaving(false); }
  };

  const toggleStatus = async (r) => {
    await api.put(`/rekening/${r.id}`, { status: r.status === "aktif" ? "nonaktif" : "aktif" });
    load();
  };

  const setDefaultOperasional = async (r) => {
    await api.put(`/rekening/${r.id}`, { default_operasional: true });
    toast.success(`${r.nama} dijadikan tujuan posting otomatis`); load();
  };

  const remove = async (r) => {
    if (!window.confirm(`Hapus rekening ${r.nama}?`)) return;
    try {
      await api.delete(`/rekening/${r.id}`);
      toast.success("Dihapus"); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  const grouped = ["operasional", "tabungan", "pinjaman"].map((j) => ({ jenis: j, items: items.filter((r) => r.jenis === j) }));

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs text-slate-500 max-w-lg">
          Pembayaran booking (Tripay), checkout Day Use, penjualan Kasir, dan pengeluaran/payroll
          sekarang otomatis tercatat ke rekening operasional yang ditandai "Default Posting" —
          set salah satu rekening operasional di bawah kalau belum ada.
        </p>
        <Button onClick={openAdd} className="bg-blue-700 hover:bg-blue-800 shrink-0" data-testid="rekening-add-btn">
          <Plus className="w-4 h-4 mr-1" /> Tambah Rekening
        </Button>
      </div>

      {grouped.map(({ jenis, items: list }) => {
        const Icon = JENIS_ICON[jenis];
        return (
          <div key={jenis}>
            <h3 className="font-bold mb-3 flex items-center gap-2"><Icon className="w-4 h-4" /> {JENIS_LABEL[jenis]}</h3>
            {list.length === 0 ? (
              <p className="text-sm text-slate-400 mb-4">Belum ada rekening {JENIS_LABEL[jenis].toLowerCase()}.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
                {list.map((r) => (
                  <Card key={r.id} className={`border-slate-200 ${r.status === "nonaktif" ? "opacity-50" : ""}`} data-testid={`rekening-card-${r.id}`}>
                    <CardContent className="p-5">
                      <div className="flex items-start justify-between">
                        <div>
                          <p className="font-bold">{r.nama}</p>
                          <p className="text-xs text-slate-500">{r.bank}{r.no_rekening ? ` · ${r.no_rekening}` : ""}</p>
                        </div>
                        <div className="flex flex-col items-end gap-1">
                          <Badge variant={r.status === "aktif" ? "default" : "secondary"}>{r.status}</Badge>
                          {r.default_operasional && <Badge className="bg-blue-700">Default Posting</Badge>}
                        </div>
                      </div>
                      <p className="text-xl font-extrabold mt-3">{fmtRp(r.saldo)}</p>
                      {r.jenis === "tabungan" && r.target && (
                        <div className="mt-2">
                          <Progress value={r.progress_persen} className="mb-1" />
                          <p className="text-[11px] text-slate-500">{r.progress_persen}% dari {fmtRp(r.target)}</p>
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2 mt-3">
                        {r.jenis === "operasional" && !r.default_operasional && (
                          <Button size="sm" variant="outline" onClick={() => setDefaultOperasional(r)} data-testid={`rekening-set-default-${r.id}`}>Jadikan Default Posting Otomatis</Button>
                        )}
                        <Button size="sm" variant="outline" onClick={() => toggleStatus(r)}>{r.status === "aktif" ? "Nonaktifkan" : "Aktifkan"}</Button>
                        <Button size="sm" variant="outline" className="text-red-600 hover:bg-red-50" onClick={() => remove(r)}><Trash2 className="w-3.5 h-3.5" /></Button>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        );
      })}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Tambah Rekening</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nama Rekening</Label><Input value={form.nama} onChange={(e) => setForm((f) => ({ ...f, nama: e.target.value }))} placeholder="BCA Operasional" className="mt-1.5" data-testid="rekening-form-nama" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Bank</Label><Input value={form.bank} onChange={(e) => setForm((f) => ({ ...f, bank: e.target.value }))} className="mt-1.5" /></div>
              <div><Label>No. Rekening</Label><Input value={form.no_rekening} onChange={(e) => setForm((f) => ({ ...f, no_rekening: e.target.value }))} className="mt-1.5" /></div>
            </div>
            <div><Label>Pemilik</Label><Input value={form.pemilik} onChange={(e) => setForm((f) => ({ ...f, pemilik: e.target.value }))} className="mt-1.5" /></div>
            <div>
              <Label>Jenis Rekening</Label>
              <select value={form.jenis} onChange={(e) => setForm((f) => ({ ...f, jenis: e.target.value }))} className="mt-1.5 w-full h-10 px-3 rounded-md border border-slate-200 text-sm" data-testid="rekening-form-jenis">
                <option value="operasional">Operasional</option>
                <option value="tabungan">Tabungan</option>
                <option value="pinjaman">Pinjaman</option>
              </select>
            </div>
            <div><Label>Saldo Awal (Rp)</Label><Input type="number" value={form.saldo_awal} onChange={(e) => setForm((f) => ({ ...f, saldo_awal: e.target.value }))} className="mt-1.5" data-testid="rekening-form-saldo" /></div>
            {form.jenis === "tabungan" && (
              <div><Label>Target Tabungan (Rp, opsional)</Label><Input type="number" value={form.target} onChange={(e) => setForm((f) => ({ ...f, target: e.target.value }))} className="mt-1.5" /></div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Batal</Button>
            <Button onClick={save} disabled={saving} className="bg-blue-700 hover:bg-blue-800" data-testid="rekening-form-save">{saving ? "Menyimpan…" : "Simpan"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------- Transaksi & Transfer ----------------

function RekeningSelect({ items, value, onChange, exclude, testId }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="mt-1.5 w-full h-10 px-3 rounded-md border border-slate-200 text-sm" data-testid={testId}>
      <option value="">Pilih rekening…</option>
      {items.filter((r) => r.status === "aktif" && r.id !== exclude).map((r) => (
        <option key={r.id} value={r.id}>{r.nama} ({fmtRp(r.saldo)})</option>
      ))}
    </select>
  );
}

function TransaksiTab() {
  const [rekening, setRekening] = useState([]);
  const [riwayat, setRiwayat] = useState([]);
  const [txForm, setTxForm] = useState({ rekening_id: "", jenis: "pengeluaran", nominal: "", kategori: "", deskripsi: "" });
  const [trForm, setTrForm] = useState({ rekening_asal_id: "", rekening_tujuan_id: "", nominal: "", deskripsi: "" });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [{ data: r }, { data: t }] = await Promise.all([api.get("/rekening"), api.get("/rekening/transaksi")]);
    setRekening(r); setRiwayat(t);
  };
  useEffect(() => { load(); }, []);

  const submitTx = async () => {
    if (!txForm.rekening_id || !txForm.nominal) return toast.error("Rekening & nominal wajib diisi");
    setSaving(true);
    try {
      await api.post("/rekening/transaksi", { ...txForm, nominal: Number(txForm.nominal) });
      toast.success("Transaksi dicatat"); setTxForm({ rekening_id: "", jenis: "pengeluaran", nominal: "", kategori: "", deskripsi: "" }); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setSaving(false); }
  };

  const submitTransfer = async () => {
    if (!trForm.rekening_asal_id || !trForm.rekening_tujuan_id || !trForm.nominal) return toast.error("Rekening asal, tujuan & nominal wajib diisi");
    setSaving(true);
    try {
      await api.post("/rekening/transfer", { ...trForm, nominal: Number(trForm.nominal) });
      toast.success("Transfer berhasil (tidak masuk laba-rugi/pengeluaran)"); setTrForm({ rekening_asal_id: "", rekening_tujuan_id: "", nominal: "", deskripsi: "" }); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setSaving(false); }
  };

  const nama = (id) => rekening.find((r) => r.id === id)?.nama || "?";

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-6">
        <Card className="border-slate-200">
          <CardContent className="p-5 space-y-3">
            <h3 className="font-bold">Pemasukan / Pengeluaran Manual</h3>
            <RekeningSelect items={rekening} value={txForm.rekening_id} onChange={(v) => setTxForm((f) => ({ ...f, rekening_id: v }))} testId="tx-form-rekening" />
            <select value={txForm.jenis} onChange={(e) => setTxForm((f) => ({ ...f, jenis: e.target.value }))} className="w-full h-10 px-3 rounded-md border border-slate-200 text-sm">
              <option value="pengeluaran">Pengeluaran</option>
              <option value="pemasukan">Pemasukan</option>
            </select>
            <Input type="number" placeholder="Nominal (Rp)" value={txForm.nominal} onChange={(e) => setTxForm((f) => ({ ...f, nominal: e.target.value }))} data-testid="tx-form-nominal" />
            <Input placeholder="Kategori" value={txForm.kategori} onChange={(e) => setTxForm((f) => ({ ...f, kategori: e.target.value }))} />
            <Input placeholder="Deskripsi" value={txForm.deskripsi} onChange={(e) => setTxForm((f) => ({ ...f, deskripsi: e.target.value }))} />
            <Button onClick={submitTx} disabled={saving} className="w-full bg-blue-700 hover:bg-blue-800" data-testid="tx-form-submit">Simpan</Button>
          </CardContent>
        </Card>

        <Card className="border-slate-200">
          <CardContent className="p-5 space-y-3">
            <h3 className="font-bold flex items-center gap-2"><ArrowRightLeft className="w-4 h-4" /> Transfer Antar Rekening</h3>
            <p className="text-xs text-slate-500">Transfer TIDAK dianggap pengeluaran/pemasukan — cuma memindahkan posisi saldo.</p>
            <RekeningSelect items={rekening} value={trForm.rekening_asal_id} onChange={(v) => setTrForm((f) => ({ ...f, rekening_asal_id: v }))} testId="transfer-form-asal" />
            <RekeningSelect items={rekening} value={trForm.rekening_tujuan_id} onChange={(v) => setTrForm((f) => ({ ...f, rekening_tujuan_id: v }))} exclude={trForm.rekening_asal_id} testId="transfer-form-tujuan" />
            <Input type="number" placeholder="Nominal (Rp)" value={trForm.nominal} onChange={(e) => setTrForm((f) => ({ ...f, nominal: e.target.value }))} data-testid="transfer-form-nominal" />
            <Input placeholder="Deskripsi (opsional)" value={trForm.deskripsi} onChange={(e) => setTrForm((f) => ({ ...f, deskripsi: e.target.value }))} />
            <Button onClick={submitTransfer} disabled={saving} className="w-full bg-blue-700 hover:bg-blue-800" data-testid="transfer-form-submit">Transfer</Button>
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-5">
          <h3 className="font-bold mb-3">Riwayat Transaksi</h3>
          <div className="divide-y divide-slate-100 max-h-[600px] overflow-y-auto">
            {riwayat.map((t) => (
              <div key={t.id} className="py-2.5 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{nama(t.rekening_id)}{t.rekening_pasangan_id ? ` → ${nama(t.rekening_pasangan_id)}` : ""}</span>
                  <span className={`font-bold ${t.jenis === "pemasukan" || t.jenis === "transfer_masuk" ? "text-emerald-600" : "text-red-600"}`}>
                    {t.jenis === "pemasukan" || t.jenis === "transfer_masuk" ? "+" : "-"}{fmtRp(t.nominal)}
                  </span>
                </div>
                <p className="text-xs text-slate-500">{fmtDate(t.tanggal)} · {t.kategori}{t.deskripsi ? ` · ${t.deskripsi}` : ""}{t.source === "smart_rule" && " · 🤖 otomatis"}</p>
              </div>
            ))}
            {riwayat.length === 0 && <p className="text-sm text-slate-400 py-6 text-center">Belum ada transaksi</p>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------- Smart Allocation ----------------

const emptyRule = { nama: "", rekening_asal_id: "", rekening_tujuan_id: "", trigger_tipe: "saldo_diatas", ambang_saldo: "", tanggal_hari: "", nominal_transfer: "" };

function SmartTab() {
  const [rules, setRules] = useState([]);
  const [rekening, setRekening] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyRule);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [{ data: r }, { data: rk }] = await Promise.all([api.get("/rekening/smart-rules"), api.get("/rekening")]);
    setRules(r); setRekening(rk);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!form.nama || !form.rekening_asal_id || !form.rekening_tujuan_id || !form.nominal_transfer) return toast.error("Lengkapi data aturan");
    setSaving(true);
    try {
      await api.post("/rekening/smart-rules", {
        ...form, nominal_transfer: Number(form.nominal_transfer),
        ambang_saldo: form.ambang_saldo ? Number(form.ambang_saldo) : null,
        tanggal_hari: form.tanggal_hari ? Number(form.tanggal_hari) : null,
      });
      toast.success("Aturan ditambahkan"); setOpen(false); setForm(emptyRule); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setSaving(false); }
  };

  const toggleAktif = async (r) => { await api.put(`/rekening/smart-rules/${r.id}`, { aktif: !r.aktif }); load(); };
  const remove = async (r) => { if (!window.confirm(`Hapus aturan "${r.nama}"?`)) return; await api.delete(`/rekening/smart-rules/${r.id}`); load(); };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <p className="text-sm text-slate-500 max-w-lg">Transfer otomatis: begitu saldo rekening asal di atas ambang tertentu, atau tiap tanggal tertentu tiap bulan.</p>
        <Button onClick={() => { setForm(emptyRule); setOpen(true); }} className="bg-blue-700 hover:bg-blue-800" data-testid="smart-rule-add-btn"><Plus className="w-4 h-4 mr-1" /> Tambah Aturan</Button>
      </div>

      <div className="space-y-3">
        {rules.map((r) => (
          <Card key={r.id} className={`border-slate-200 ${!r.aktif ? "opacity-50" : ""}`}>
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <p className="font-bold flex items-center gap-2"><Zap className="w-4 h-4 text-amber-500" /> {r.nama}</p>
                <p className="text-sm text-slate-600 mt-1">
                  {r.rekening_asal_nama} → {r.rekening_tujuan_nama} · Rp{Number(r.nominal_transfer).toLocaleString("id-ID")}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">
                  {r.trigger_tipe === "saldo_diatas" ? `Trigger: saldo asal di atas Rp${Number(r.ambang_saldo).toLocaleString("id-ID")}` : `Trigger: tiap tanggal ${r.tanggal_hari} setiap bulan`}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Switch checked={r.aktif} onCheckedChange={() => toggleAktif(r)} />
                <Button size="icon" variant="ghost" onClick={() => remove(r)}><Trash2 className="w-4 h-4 text-red-500" /></Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {rules.length === 0 && <p className="text-sm text-slate-400 text-center py-8">Belum ada Smart Allocation Rule</p>}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Tambah Smart Allocation Rule</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nama Aturan</Label><Input value={form.nama} onChange={(e) => setForm((f) => ({ ...f, nama: e.target.value }))} placeholder="Skim ke Dana Renovasi" className="mt-1.5" /></div>
            <div><Label>Rekening Asal</Label><RekeningSelect items={rekening} value={form.rekening_asal_id} onChange={(v) => setForm((f) => ({ ...f, rekening_asal_id: v }))} /></div>
            <div><Label>Rekening Tujuan</Label><RekeningSelect items={rekening} value={form.rekening_tujuan_id} onChange={(v) => setForm((f) => ({ ...f, rekening_tujuan_id: v }))} exclude={form.rekening_asal_id} /></div>
            <div>
              <Label>Jenis Trigger</Label>
              <select value={form.trigger_tipe} onChange={(e) => setForm((f) => ({ ...f, trigger_tipe: e.target.value }))} className="mt-1.5 w-full h-10 px-3 rounded-md border border-slate-200 text-sm">
                <option value="saldo_diatas">Saldo di atas nominal tertentu</option>
                <option value="tanggal_bulanan">Tanggal tertentu tiap bulan</option>
              </select>
            </div>
            {form.trigger_tipe === "saldo_diatas" ? (
              <div><Label>Ambang Saldo (Rp)</Label><Input type="number" value={form.ambang_saldo} onChange={(e) => setForm((f) => ({ ...f, ambang_saldo: e.target.value }))} className="mt-1.5" /></div>
            ) : (
              <div><Label>Tanggal (1-28)</Label><Input type="number" min={1} max={28} value={form.tanggal_hari} onChange={(e) => setForm((f) => ({ ...f, tanggal_hari: e.target.value }))} className="mt-1.5" /></div>
            )}
            <div><Label>Nominal Transfer (Rp)</Label><Input type="number" value={form.nominal_transfer} onChange={(e) => setForm((f) => ({ ...f, nominal_transfer: e.target.value }))} className="mt-1.5" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Batal</Button>
            <Button onClick={save} disabled={saving} className="bg-blue-700 hover:bg-blue-800">{saving ? "Menyimpan…" : "Simpan"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------- Rekonsiliasi CSV ----------------

function RekonsiliasiTab() {
  const [rekening, setRekening] = useState([]);
  const [rekeningId, setRekeningId] = useState("");
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { api.get("/rekening").then(({ data }) => setRekening(data)); }, []);

  const upload = async () => {
    if (!rekeningId || !file) return toast.error("Pilih rekening & file CSV dulu");
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post(`/rekening/${rekeningId}/rekonsiliasi-csv`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(data);
      toast.success(`Rekonsiliasi selesai: ${data.cocok.length} cocok, ${data.tidak_cocok.length} perlu ditinjau`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal memproses CSV"); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-6">
      <Card className="border-slate-200">
        <CardContent className="p-5 space-y-3">
          <h3 className="font-bold">Upload Mutasi Bank (CSV)</h3>
          <p className="text-xs text-slate-500">
            Format kolom wajib: <code className="bg-slate-100 px-1 rounded">tanggal,keterangan,nominal,tipe</code> — tanggal format YYYY-MM-DD,
            tipe isi <code className="bg-slate-100 px-1 rounded">masuk</code>/<code className="bg-slate-100 px-1 rounded">keluar</code> (atau kredit/debit).
            Baris CSV dicocokkan ke transaksi yang sudah dicatat manual — yang tidak cocok TIDAK otomatis dibuat, cuma ditampilkan untuk ditinjau.
          </p>
          <RekeningSelect items={rekening} value={rekeningId} onChange={setRekeningId} testId="rekonsiliasi-rekening" />
          <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} className="text-sm" data-testid="rekonsiliasi-file" />
          <Button onClick={upload} disabled={loading} className="bg-blue-700 hover:bg-blue-800" data-testid="rekonsiliasi-submit">
            <Upload className="w-4 h-4 mr-1" /> {loading ? "Memproses…" : "Proses Rekonsiliasi"}
          </Button>
        </CardContent>
      </Card>

      {result && (
        <div className="space-y-4">
          <Card className="border-emerald-200 bg-emerald-50">
            <CardContent className="p-5">
              <p className="font-bold text-emerald-800 mb-2">✓ Cocok ({result.cocok.length})</p>
              {result.cocok.map((c, i) => (
                <div key={i} className="text-sm py-1 flex justify-between"><span>{c.tanggal} · {c.keterangan}</span><span className="font-medium">{fmtRp(c.nominal)}</span></div>
              ))}
              {result.cocok.length === 0 && <p className="text-sm text-slate-400">Tidak ada</p>}
            </CardContent>
          </Card>

          <Card className="border-amber-300 bg-amber-50">
            <CardContent className="p-5">
              <p className="font-bold text-amber-800 mb-2 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> Perlu Ditinjau — ada di mutasi bank, belum tercatat di ledger ({result.tidak_cocok.length})</p>
              {result.tidak_cocok.map((c, i) => (
                <div key={i} className="text-sm py-1">
                  <div className="flex justify-between"><span>{c.tanggal} · {c.keterangan}</span><span className="font-medium">{fmtRp(c.nominal)}</span></div>
                  <p className="text-xs text-amber-700">{c.error}</p>
                </div>
              ))}
              {result.tidak_cocok.length === 0 && <p className="text-sm text-slate-400">Tidak ada</p>}
            </CardContent>
          </Card>

          {result.ledger_belum_direkonsiliasi.length > 0 && (
            <Card className="border-slate-200">
              <CardContent className="p-5">
                <p className="font-bold mb-2 flex items-center gap-2"><TrendingDown className="w-4 h-4" /> Tercatat di ledger, belum ketemu di mutasi bank yang diupload ({result.ledger_belum_direkonsiliasi.length})</p>
                {result.ledger_belum_direkonsiliasi.map((t) => (
                  <div key={t.id} className="text-sm py-1 flex justify-between text-slate-600">
                    <span>{fmtDate(t.tanggal)} · {t.kategori}{t.deskripsi ? ` - ${t.deskripsi}` : ""}</span>
                    <span>{fmtRp(t.nominal)}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
