import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { ChevronLeft, ChevronRight, Sparkles, Send, Users, Plus, Pencil, Repeat2, AlertTriangle, History } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const SHIFT_LABEL = { morning: "Morning", middle: "Middle", night: "Night", off: "Off" };
const SHIFT_CLS = {
  morning: "bg-amber-100 text-amber-800 border-amber-300",
  middle: "bg-blue-100 text-blue-800 border-blue-300",
  night: "bg-indigo-100 text-indigo-800 border-indigo-300",
  off: "bg-slate-100 text-slate-500 border-slate-300",
};
const SHIFT_OPTIONS = ["morning", "middle", "night", "off"];
const BULAN_LABEL = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
const WAJIB_OFF = 4;

function StaffDialog({ staf, onOpenChange, onSaved }) {
  const [nama, setNama] = useState("");
  const [terlarang, setTerlarang] = useState([]);
  const [aktif, setAktif] = useState(true);
  const [saving, setSaving] = useState(false);
  const isNew = staf === "new";

  useEffect(() => {
    if (staf && staf !== "new") {
      setNama(staf.nama); setTerlarang(staf.shift_terlarang || []); setAktif(staf.aktif);
    } else if (isNew) {
      setNama(""); setTerlarang([]); setAktif(true);
    }
  }, [staf]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!staf) return null;

  const toggleTerlarang = (sh) => {
    setTerlarang((prev) => prev.includes(sh) ? prev.filter((x) => x !== sh) : [...prev, sh]);
  };

  const simpan = async () => {
    if (!nama.trim()) { toast.error("Nama wajib diisi"); return; }
    setSaving(true);
    try {
      if (isNew) await api.post("/staff-kerja", { nama: nama.trim(), shift_terlarang: terlarang, aktif });
      else await api.put(`/staff-kerja/${staf.id}`, { nama: nama.trim(), shift_terlarang: terlarang, aktif });
      toast.success("Tersimpan");
      onSaved();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={!!staf} onOpenChange={(o) => { if (!o) onOpenChange(false); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{isNew ? "Tambah Staf" : "Edit Staf"}</DialogTitle></DialogHeader>
        <div className="space-y-3 text-sm">
          <div>
            <Label>Nama</Label>
            <Input value={nama} onChange={(e) => setNama(e.target.value)} className="mt-1.5" />
          </div>
          <div>
            <Label>Shift Terlarang</Label>
            <p className="text-[11px] text-slate-400 mb-1.5">Staf ini TIDAK PERNAH akan dijadwalkan shift yang dicentang, baik oleh Generate Jadwal maupun edit manual/tukar shift.</p>
            <div className="flex gap-2">
              {["morning", "middle", "night"].map((sh) => (
                <button key={sh} type="button" onClick={() => toggleTerlarang(sh)}
                  className={`px-3 py-1.5 rounded-lg border-2 text-xs font-semibold ${terlarang.includes(sh) ? "border-red-500 bg-red-50 text-red-700" : "border-slate-200"}`}>
                  {SHIFT_LABEL[sh]}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="staf-aktif" checked={aktif} onChange={(e) => setAktif(e.target.checked)} />
            <Label htmlFor="staf-aktif">Aktif (ikut dijadwalkan)</Label>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={simpan} disabled={saving} className="bg-blue-700 hover:bg-blue-800">{saving ? "Menyimpan…" : "Simpan"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TukarShiftDialog({ open, onOpenChange, jadwal, staffList, onDone }) {
  const [staffA, setStaffA] = useState("");
  const [tglA, setTglA] = useState("");
  const [staffB, setStaffB] = useState("");
  const [tglB, setTglB] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open && jadwal) {
      setStaffA(staffList[0]?.id || ""); setTglA(jadwal.tanggal[0] || "");
      setStaffB(staffList[1]?.id || staffList[0]?.id || ""); setTglB(jadwal.tanggal[0] || "");
    }
  }, [open, jadwal, staffList]);

  if (!jadwal) return null;

  const submit = async () => {
    setSubmitting(true);
    try {
      await api.post(`/jadwal-kerja/${jadwal.id}/swap`, { staff_id_a: staffA, tanggal_a: tglA, staff_id_b: staffB, tanggal_b: tglB });
      toast.success("Shift berhasil ditukar");
      onDone();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menukar shift"); }
    finally { setSubmitting(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Tukar Shift</DialogTitle></DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-2 items-end">
            <div>
              <Label>Staf A</Label>
              <select value={staffA} onChange={(e) => setStaffA(e.target.value)} className="w-full h-10 rounded-md border border-slate-300 px-2 mt-1.5">
                {staffList.map((s) => <option key={s.id} value={s.id}>{s.nama}</option>)}
              </select>
            </div>
            <div>
              <Label>Tanggal A</Label>
              <select value={tglA} onChange={(e) => setTglA(e.target.value)} className="w-full h-10 rounded-md border border-slate-300 px-2 mt-1.5">
                {jadwal.tanggal.map((t) => <option key={t} value={t}>{t.slice(-2)}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 items-end">
            <div>
              <Label>Staf B</Label>
              <select value={staffB} onChange={(e) => setStaffB(e.target.value)} className="w-full h-10 rounded-md border border-slate-300 px-2 mt-1.5">
                {staffList.map((s) => <option key={s.id} value={s.id}>{s.nama}</option>)}
              </select>
            </div>
            <div>
              <Label>Tanggal B</Label>
              <select value={tglB} onChange={(e) => setTglB(e.target.value)} className="w-full h-10 rounded-md border border-slate-300 px-2 mt-1.5">
                {jadwal.tanggal.map((t) => <option key={t} value={t}>{t.slice(-2)}</option>)}
              </select>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={submitting} className="bg-blue-700 hover:bg-blue-800">{submitting ? "Menukar…" : "Tukar"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function JadwalKerja() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [viewDate, setViewDate] = useState(() => { const d = new Date(); d.setDate(1); return d; });
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth() + 1;

  const [staffList, setStaffList] = useState([]);
  const [jadwal, setJadwal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [staffDialog, setStaffDialog] = useState(null); // "new" | staf object | null
  const [swapOpen, setSwapOpen] = useState(false);
  const [riwayat, setRiwayat] = useState([]);
  const [showRiwayat, setShowRiwayat] = useState(false);
  const [editCell, setEditCell] = useState(null); // {staff, tanggal}

  const loadStaff = async () => { const { data } = await api.get("/staff-kerja"); setStaffList(data); };
  const loadJadwal = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/jadwal-kerja", { params: { year, month } });
      setJadwal(data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal memuat jadwal"); }
    finally { setLoading(false); }
  };
  const loadRiwayat = async () => { const { data } = await api.get("/jadwal-kerja/riwayat"); setRiwayat(data); };

  useEffect(() => { loadStaff(); }, []);
  useEffect(() => { loadJadwal(); }, [year, month]); // eslint-disable-line react-hooks/exhaustive-deps

  const goMonth = (delta) => setViewDate((d) => { const nd = new Date(d); nd.setMonth(nd.getMonth() + delta); return nd; });

  const generate = async () => {
    setGenerating(true);
    try {
      const { data } = await api.post("/jadwal-kerja/generate", { year, month });
      setJadwal(data);
      toast.success("Jadwal draft berhasil dibuat");
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal generate jadwal"); }
    finally { setGenerating(false); }
  };

  const ubahShift = async (staffId, tanggal, shift) => {
    try {
      const { data } = await api.put(`/jadwal-kerja/${jadwal.id}/shift`, { staff_id: staffId, tanggal, shift });
      setJadwal(data);
      setEditCell(null);
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal ubah shift"); }
  };

  const publish = async () => {
    setPublishing(true);
    try {
      const { data } = await api.post(`/jadwal-kerja/${jadwal.id}/publish`);
      setJadwal(data);
      toast.success("Jadwal dipublish");
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal publish"); }
    finally { setPublishing(false); }
  };

  const bukaBulanRiwayat = (r) => {
    setViewDate(new Date(r.year, r.month - 1, 1));
    setShowRiwayat(false);
  };

  const totalPelanggaran = useMemo(() => {
    const perStaf = (jadwal?.staf || []).reduce((n, s) => n + s.pelanggaran.length, 0);
    return perStaf + (jadwal?.pelanggaran_hari?.length || 0);
  }, [jadwal]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Staf</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Jadwal Kerja</h1>
          <p className="text-slate-500 text-sm mt-1">Buat draft jadwal shift bulanan otomatis, tinjau &amp; publish setelah sesuai.</p>
        </div>
        <Button variant="outline" onClick={() => { setShowRiwayat(true); loadRiwayat(); }}><History className="w-4 h-4 mr-2" /> Riwayat</Button>
      </div>

      {/* Kelola Staf */}
      <Card className="border-slate-200">
        <CardContent className="p-4 sm:p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold flex items-center gap-2"><Users className="w-4 h-4" /> Staf ({staffList.length})</h2>
            {isOwner && <Button size="sm" onClick={() => setStaffDialog("new")}><Plus className="w-3.5 h-3.5 mr-1" /> Tambah Staf</Button>}
          </div>
          <div className="flex flex-wrap gap-2">
            {staffList.map((s) => (
              <div key={s.id} className={`flex items-center gap-2 border rounded-full pl-3 pr-1.5 py-1 text-xs ${s.aktif ? "border-slate-200" : "border-slate-200 opacity-50"}`}>
                <span className="font-semibold">{s.nama}</span>
                {(s.shift_terlarang || []).length > 0 && (
                  <span className="text-red-600">(no {s.shift_terlarang.map((sh) => SHIFT_LABEL[sh]).join("/")})</span>
                )}
                {isOwner && <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => setStaffDialog(s)}><Pencil className="w-3 h-3" /></Button>}
              </div>
            ))}
            {staffList.length === 0 && <p className="text-xs text-slate-400">Belum ada staf</p>}
          </div>
        </CardContent>
      </Card>

      {/* Navigasi bulan */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => goMonth(-1)}><ChevronLeft className="w-4 h-4" /></Button>
          <span className="text-base font-bold w-44 text-center">{BULAN_LABEL[month]} {year}</span>
          <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => goMonth(1)}><ChevronRight className="w-4 h-4" /></Button>
        </div>
        {jadwal && (
          <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${jadwal.status === "published" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>
            {jadwal.status === "published" ? "Published" : "Draft"}
          </span>
        )}
      </div>

      {loading ? (
        <p className="text-slate-400 text-sm">Memuat…</p>
      ) : !jadwal ? (
        <Card className="border-slate-200">
          <CardContent className="p-10 text-center space-y-3">
            <p className="text-slate-500">Belum ada jadwal untuk {BULAN_LABEL[month]} {year}.</p>
            {isOwner ? (
              <>
                <Button onClick={generate} disabled={generating || staffList.length === 0} className="bg-blue-700 hover:bg-blue-800">
                  <Sparkles className="w-4 h-4 mr-2" /> {generating ? "Membuat jadwal…" : "Generate Jadwal"}
                </Button>
                {staffList.length === 0 && <p className="text-xs text-red-500">Tambah staf dulu sebelum generate.</p>}
              </>
            ) : (
              <p className="text-xs text-slate-400">Hubungi owner untuk membuat jadwal bulan ini.</p>
            )}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {isOwner && jadwal.status === "draft" && (
              <>
                <Button size="sm" variant="outline" onClick={generate} disabled={generating}>
                  <Sparkles className="w-3.5 h-3.5 mr-1" /> {generating ? "Membuat ulang…" : "Generate Ulang"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setSwapOpen(true)}><Repeat2 className="w-3.5 h-3.5 mr-1" /> Tukar Shift</Button>
                <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={publish} disabled={publishing || totalPelanggaran > 0}>
                  <Send className="w-3.5 h-3.5 mr-1" /> {publishing ? "Mempublish…" : "Publish Jadwal"}
                </Button>
              </>
            )}
          </div>

          {isOwner && jadwal.status === "draft" && totalPelanggaran > 0 && (
            <div className="rounded-xl bg-red-50 border border-red-200 p-3 flex items-start gap-2 text-sm text-red-700">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{totalPelanggaran} pelanggaran aturan ditemukan — perbaiki dulu (klik sel untuk ubah) sebelum bisa publish.</span>
            </div>
          )}

          <Card className="border-slate-200">
            <CardContent className="p-3 overflow-x-auto">
              <table className="border-collapse text-xs">
                <thead>
                  <tr>
                    <th className="sticky left-0 bg-white p-2 text-left border-b-2 border-slate-200 min-w-[110px]">Staf</th>
                    {jadwal.tanggal.map((t) => (
                      <th key={t} className="p-1 text-center border-b-2 border-slate-200 min-w-[38px] font-semibold text-slate-500">{t.slice(-2)}</th>
                    ))}
                    <th className="p-2 text-center border-b-2 border-slate-200 min-w-[60px]">Off</th>
                  </tr>
                </thead>
                <tbody>
                  {jadwal.staf.map((s) => (
                    <tr key={s.id}>
                      <td className="sticky left-0 bg-white p-2 font-semibold border-b border-slate-100">{s.nama}</td>
                      {jadwal.tanggal.map((t) => {
                        const sh = s.shift[t];
                        return (
                          <td key={t} className="p-0.5 text-center border-b border-slate-100">
                            <button
                              disabled={!isOwner || jadwal.status === "published"}
                              onClick={() => setEditCell({ staff: s, tanggal: t })}
                              className={`w-9 h-7 rounded text-[9px] font-bold border ${SHIFT_CLS[sh] || "bg-white border-slate-200"} ${isOwner && jadwal.status !== "published" ? "cursor-pointer hover:opacity-70" : "cursor-default"}`}
                              title={SHIFT_LABEL[sh] || "-"}
                            >
                              {sh ? SHIFT_LABEL[sh].slice(0, 3).toUpperCase() : "-"}
                            </button>
                          </td>
                        );
                      })}
                      <td className={`p-2 text-center font-bold border-b border-slate-100 ${s.statistik.off === WAJIB_OFF ? "text-emerald-600" : "text-red-600"}`}>
                        {s.statistik.off}/{WAJIB_OFF}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}

      {/* Popover edit sel sederhana via dialog */}
      <Dialog open={!!editCell} onOpenChange={(o) => { if (!o) setEditCell(null); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editCell?.staff.nama} — {editCell?.tanggal}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-2">
            {SHIFT_OPTIONS.map((sh) => {
              const terlarang = (editCell?.staff.shift_terlarang || []).includes(sh);
              return (
                <button
                  key={sh}
                  disabled={terlarang}
                  onClick={() => ubahShift(editCell.staff.id, editCell.tanggal, sh)}
                  className={`p-3 rounded-lg border-2 text-sm font-semibold ${terlarang ? "opacity-30 cursor-not-allowed border-slate-200" : SHIFT_CLS[sh]}`}
                >
                  {SHIFT_LABEL[sh]}{terlarang ? " (terlarang)" : ""}
                </button>
              );
            })}
          </div>
        </DialogContent>
      </Dialog>

      <StaffDialog staf={staffDialog} onOpenChange={(o) => { if (!o) setStaffDialog(null); }} onSaved={() => { setStaffDialog(null); loadStaff(); }} />
      <TukarShiftDialog open={swapOpen} onOpenChange={setSwapOpen} jadwal={jadwal} staffList={jadwal?.staf || []} onDone={() => { setSwapOpen(false); loadJadwal(); }} />

      <Dialog open={showRiwayat} onOpenChange={setShowRiwayat}>
        <DialogContent>
          <DialogHeader><DialogTitle>Riwayat Jadwal</DialogTitle></DialogHeader>
          <div className="space-y-1.5 max-h-96 overflow-y-auto">
            {riwayat.length === 0 && <p className="text-sm text-slate-400">Belum ada riwayat</p>}
            {riwayat.map((r) => (
              <button key={r.id} onClick={() => bukaBulanRiwayat(r)} className="w-full flex items-center justify-between p-2.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-sm text-left">
                <span>{BULAN_LABEL[r.month]} {r.year}</span>
                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${r.status === "published" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>{r.status}</span>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
