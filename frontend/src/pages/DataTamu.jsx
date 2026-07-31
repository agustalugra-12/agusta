import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtDateTime, fmtRp, waLink } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { MessageCircle, Phone, History, Sparkles, Plus, PencilLine, Trash2 } from "lucide-react";

// (2026-07-31, permintaan Agus) - "Data Tamu" dipindah jadi halaman/sidebar sendiri,
// LEPAS dari Reservasi (sebelumnya cuma tab di dalam DaftarReservasi.jsx - riwayat
// bolak-balik: awalnya entri sidebar sendiri -> pernah dilebur jadi tab "biar konsisten
// pola tab halaman lain" -> sekarang dipisah lagi krn Agus mau lebih mudah ditemukan,
// tidak nyempil di dalam Reservasi). Isi komponen SAMA PERSIS dgn TamuTab lama, cuma
// dipindah ke file+route+sidebar sendiri.

// Tabel siklus diskon loyalitas - SAMA PERSIS dgn DISKON_MEMBER_TABLE (core.py), cuma
// dipakai di sini utk render visual siklus 10 kedatangan ("Member Intelligence" fase 1).
// Kalau tabel di backend diubah, WAJIB update di sini juga.
const DISKON_MEMBER_TABLE = { 1: 0, 2: 10, 3: 0, 4: 10, 5: 30, 6: 0, 7: 10, 8: 0, 9: 10, 10: 100 };

function loyaltyStatus(g) {
  const totalKunjungan = g.total_kunjungan || 0;
  const daysSince = g.last_visit ? Math.floor((Date.now() - new Date(g.last_visit).getTime()) / 86400000) : null;
  if (totalKunjungan === 0) return { label: "Tamu Baru", emoji: "🎉", cls: "bg-blue-100 text-blue-700" };
  if (daysSince !== null && daysSince > 90) return { label: "Jarang Datang", emoji: "😴", cls: "bg-slate-200 text-slate-600" };
  if (totalKunjungan >= 9) return { label: "VIP", emoji: "💎", cls: "bg-purple-100 text-purple-700" };
  if (totalKunjungan >= 2) return { label: "Loyal Guest", emoji: "❤️", cls: "bg-rose-100 text-rose-700" };
  return { label: "Active Member", emoji: "🔥", cls: "bg-orange-100 text-orange-700" };
}

// Posisi di siklus 10 kedatangan (sama seperti diskon_member_untuk_total_kunjungan di
// core.py) + reward berikutnya yang belum diraih, buat progress bar "Loyalty Journey".
function loyaltyCycle(kedatanganKe) {
  const posisi = ((kedatanganKe - 1) % 10) + 1;
  let nextPosisi = null, nextReward = 0;
  for (let p = posisi + 1; p <= 10; p++) {
    if (DISKON_MEMBER_TABLE[p] > 0) { nextPosisi = p; nextReward = DISKON_MEMBER_TABLE[p]; break; }
  }
  return { posisi, nextPosisi, nextReward, sisaMenuju: nextPosisi ? nextPosisi - posisi : null };
}

const emptyGuestForm = { nama: "", no_hp: "", no_identitas: "", kendaraan: "" };
const emptyKunjunganManual = { tanggal: new Date().toISOString().slice(0, 10), room_nomor: "", catatan: "" };

export default function DataTamu() {
  const [q, setQ] = useState("");
  const [guests, setGuests] = useState([]);
  const [history, setHistory] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingGuest, setEditingGuest] = useState(null);
  const [guestForm, setGuestForm] = useState(emptyGuestForm);
  const [saving, setSaving] = useState(false);
  const [kunjunganManualOpen, setKunjunganManualOpen] = useState(false);
  const [kunjunganManualForm, setKunjunganManualForm] = useState(emptyKunjunganManual);
  const [savingKunjungan, setSavingKunjungan] = useState(false);

  const load = async () => {
    const { data } = await api.get("/guests", { params: q ? { q } : {} });
    setGuests(data);
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [q]);

  const showHistory = async (g) => {
    const { data } = await api.get(`/guests/${g.id}/history`);
    setHistory({ guest: g, items: data });
    setKunjunganManualOpen(false);
    setKunjunganManualForm(emptyKunjunganManual);
  };

  const tambahKunjunganManual = async () => {
    if (!kunjunganManualForm.tanggal) { toast.error("Tanggal wajib diisi"); return; }
    setSavingKunjungan(true);
    try {
      const { data: updatedGuest } = await api.post(`/guests/${history.guest.id}/kunjungan-manual`, kunjunganManualForm);
      setHistory((h) => ({ ...h, guest: updatedGuest }));
      setKunjunganManualOpen(false);
      setKunjunganManualForm(emptyKunjunganManual);
      toast.success("Kunjungan manual ditambahkan");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menambahkan"); }
    finally { setSavingKunjungan(false); }
  };

  const hapusKunjunganManual = async (entryId) => {
    if (!window.confirm("Hapus catatan kunjungan manual ini?")) return;
    try {
      const { data: updatedGuest } = await api.delete(`/guests/${history.guest.id}/kunjungan-manual/${entryId}`);
      setHistory((h) => ({ ...h, guest: updatedGuest }));
      toast.success("Dihapus");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  const openAddGuest = () => { setEditingGuest(null); setGuestForm(emptyGuestForm); setFormOpen(true); };
  const openEditGuest = (g) => { setEditingGuest(g); setGuestForm({ nama: g.nama, no_hp: g.no_hp || "", no_identitas: g.no_identitas || "", kendaraan: g.kendaraan || "" }); setFormOpen(true); };

  const saveGuest = async () => {
    if (!guestForm.nama.trim()) { toast.error("Nama wajib diisi"); return; }
    if (!editingGuest && !guestForm.no_hp.trim() && !guestForm.no_identitas.trim()) {
      toast.error("Isi minimal salah satu: No HP atau No KTP"); return;
    }
    setSaving(true);
    try {
      if (editingGuest) {
        await api.put(`/guests/${editingGuest.id}`, guestForm);
        toast.success("Data tamu diperbarui");
      } else {
        await api.post("/guests", guestForm);
        toast.success("Tamu ditambahkan");
      }
      setFormOpen(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="data-tamu-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Data Tamu</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Tamu &amp; Member.</h1>
        <p className="text-slate-500 mt-1">Riwayat kedatangan, loyalitas, dan data kontak semua tamu.</p>
      </div>
      <div className="flex flex-col sm:flex-row gap-3">
        <Input data-testid="search-guest" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama, HP, atau No KTP..." className="h-12 flex-1" />
        <Button data-testid="guest-add-btn" onClick={openAddGuest} className="h-12 gap-1.5 bg-blue-700 hover:bg-blue-800 shrink-0">
          <Plus className="w-4 h-4" /> Tambah Tamu
        </Button>
      </div>
      <div className="space-y-2">
        {guests.map(g => {
          const status = loyaltyStatus(g);
          const cycle = loyaltyCycle(g.kedatangan_ke);
          return (
          <Card key={g.id} className="border-slate-200" data-testid={`guest-row-${g.id}`}>
            <CardContent className="p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-4">
                <div className="flex items-center gap-3 min-w-[220px]">
                  <div className="w-11 h-11 rounded-full bg-blue-700 text-white grid place-items-center font-bold text-base shrink-0">
                    {(g.nama || "?").trim().charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-base">{g.nama}</span>
                      <span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide rounded-full px-2 py-0.5 ${status.cls}`} data-testid={`guest-status-${g.id}`}>
                        {status.emoji} {status.label}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500">{g.no_hp || "-"} • {g.no_identitas || "-"}</div>
                    {(() => {
                      const varianLain = Object.keys(g.nama_varian || {}).filter((n) => n !== g.nama);
                      return varianLain.length > 0 ? (
                        <div className="text-[11px] text-slate-400 mt-0.5" title="Nama lain yang pernah dipakai tamu ini saat booking (nomor HP sama)">
                          juga tercatat sebagai: {varianLain.join(", ")}
                        </div>
                      ) : null;
                    })()}
                  </div>
                </div>
                <div className="flex items-center gap-2 text-xs shrink-0">
                  <div className="bg-slate-50 rounded-lg px-2.5 py-1.5"><span className="text-slate-500">Kunjungan </span><span className="font-bold">{g.total_kunjungan || 0}×</span></div>
                  <div className="bg-slate-50 rounded-lg px-2.5 py-1.5"><span className="text-slate-500">Total Belanja </span><span className="font-bold">{fmtRp(g.total_transaksi || 0)}</span></div>
                  {g.diskon_persen > 0 ? (
                    <div className="inline-flex items-center gap-1 bg-amber-100 text-amber-800 rounded-lg px-2.5 py-1.5 font-semibold" data-testid={`guest-member-badge-${g.id}`}>
                      <Sparkles className="w-3.5 h-3.5" /> Kedatangan ke-{g.kedatangan_ke}: diskon {g.diskon_persen}%
                    </div>
                  ) : (
                    <div className="text-slate-400 px-2.5 py-1.5">Kedatangan ke-{g.kedatangan_ke}: belum ada diskon</div>
                  )}
                </div>
                <div className="text-xs text-slate-500 shrink-0">Terakhir: {fmtDateTime(g.last_visit)}</div>
                <div className="flex gap-2 ml-auto shrink-0">
                  {g.no_hp && <a href={waLink(g.no_hp)} target="_blank" rel="noreferrer"><Button size="sm" variant="outline"><MessageCircle className="w-3.5 h-3.5 mr-1" /> WA</Button></a>}
                  {g.no_hp && <a href={`tel:${g.no_hp}`}><Button size="sm" variant="outline"><Phone className="w-3.5 h-3.5 mr-1" /> Telepon</Button></a>}
                  <Button size="sm" variant="outline" onClick={() => showHistory(g)} data-testid={`hist-${g.id}`}><History className="w-3.5 h-3.5" /></Button>
                  <Button size="sm" variant="outline" onClick={() => openEditGuest(g)} data-testid={`guest-edit-${g.id}`}><PencilLine className="w-3.5 h-3.5" /></Button>
                </div>
              </div>
              {/* Loyalty Journey - siklus 10 kedatangan (2026-07-31, "Member Intelligence" fase 1) */}
              <div className="flex items-center gap-2" data-testid={`guest-loyalty-cycle-${g.id}`}>
                <div className="flex gap-1">
                  {Array.from({ length: 10 }, (_, i) => i + 1).map((p) => (
                    <div
                      key={p}
                      title={`Kedatangan ke-${p}${DISKON_MEMBER_TABLE[p] > 0 ? ` — diskon ${DISKON_MEMBER_TABLE[p]}%` : ""}`}
                      className={`w-4 h-4 rounded-sm shrink-0 ${
                        p < cycle.posisi ? "bg-blue-300"
                          : p === cycle.posisi ? "bg-blue-700 ring-2 ring-blue-300"
                          : DISKON_MEMBER_TABLE[p] > 0 ? "bg-amber-200" : "bg-slate-150 bg-slate-200"
                      }`}
                    />
                  ))}
                </div>
                <span className="text-[11px] text-slate-500">
                  {cycle.nextPosisi
                    ? `${cycle.sisaMenuju}x lagi menuju diskon ${cycle.nextReward}% (kedatangan ke-${cycle.nextPosisi})`
                    : "Siklus 10 kedatangan selesai — mulai lagi dari awal"}
                </span>
              </div>
            </CardContent>
          </Card>
          );
        })}
        {guests.length === 0 && <div className="text-slate-500 text-center py-10">Belum ada data tamu</div>}
      </div>

      <Dialog open={!!history} onOpenChange={(o) => !o && setHistory(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Riwayat {history?.guest?.nama}</DialogTitle></DialogHeader>
          <div className="max-h-[28rem] overflow-y-auto space-y-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                  Riwayat Kedatangan ({history?.guest?.total_kunjungan || 0}×)
                </p>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setKunjunganManualOpen((v) => !v)} data-testid="kunjungan-manual-toggle">
                  <Plus className="w-3 h-3 mr-1" /> Kunjungan Manual
                </Button>
              </div>

              {kunjunganManualOpen && (
                <div className="border border-slate-200 rounded-lg p-3 mb-3 bg-slate-50 space-y-2" data-testid="kunjungan-manual-form">
                  <p className="text-xs text-slate-500">Untuk migrasi riwayat dari kartu member kertas lama, atau koreksi data.</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <Label className="text-xs">Tanggal Kedatangan</Label>
                      <Input type="date" className="h-9 mt-1 text-sm" value={kunjunganManualForm.tanggal}
                        onChange={(e) => setKunjunganManualForm((f) => ({ ...f, tanggal: e.target.value }))} data-testid="kunjungan-manual-tanggal" />
                    </div>
                    <div>
                      <Label className="text-xs">Kamar (opsional)</Label>
                      <Input className="h-9 mt-1 text-sm" placeholder="mis. 5" value={kunjunganManualForm.room_nomor}
                        onChange={(e) => setKunjunganManualForm((f) => ({ ...f, room_nomor: e.target.value }))} data-testid="kunjungan-manual-kamar" />
                    </div>
                  </div>
                  <div>
                    <Label className="text-xs">Catatan (opsional)</Label>
                    <Input className="h-9 mt-1 text-sm" placeholder="mis. dari kartu member kertas" value={kunjunganManualForm.catatan}
                      onChange={(e) => setKunjunganManualForm((f) => ({ ...f, catatan: e.target.value }))} data-testid="kunjungan-manual-catatan" />
                  </div>
                  <Button size="sm" className="w-full bg-blue-700 hover:bg-blue-800" disabled={savingKunjungan} onClick={tambahKunjunganManual} data-testid="kunjungan-manual-simpan">
                    {savingKunjungan ? "Menyimpan…" : "Simpan Kunjungan"}
                  </Button>
                </div>
              )}

              <div className="space-y-1.5">
                {[...(history?.guest?.riwayat_kunjungan || [])].reverse().map((k, i) => (
                  <div key={k.id || i} className="flex items-center justify-between text-sm border border-slate-200 rounded-lg px-3 py-2" data-testid={`riwayat-kunjungan-${i}`}>
                    <div className="flex items-center gap-2">
                      <span>{fmtDateTime(k.tanggal)}</span>
                      {k.room_nomor && <span className="text-slate-500">Kamar {k.room_nomor}</span>}
                      {k.source === "manual" && <span className="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">Manual</span>}
                      {k.catatan && <span className="text-slate-400 text-xs">· {k.catatan}</span>}
                    </div>
                    {k.source === "manual" && k.id && (
                      <button onClick={() => hapusKunjunganManual(k.id)} className="text-red-500 hover:text-red-700 shrink-0" data-testid={`kunjungan-manual-hapus-${i}`}>
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                ))}
                {(history?.guest?.riwayat_kunjungan || []).length === 0 && (
                  <div className="text-slate-400 text-center py-3 text-sm">Belum pernah check-in sungguhan</div>
                )}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Detail Transaksi (Day Use)</p>
              <div className="space-y-2">
                {(history?.items || []).map(it => (
                  <div key={it.id} className="border border-slate-200 rounded-lg p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold">Kamar {it.room_nomor} ({it.room_tipe})</span>
                      <span className={`text-xs px-2 py-0.5 rounded ${it.status === "selesai" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{it.status}</span>
                    </div>
                    <div className="text-xs text-slate-500 mt-1">{fmtDateTime(it.jam_checkin)} → {fmtDateTime(it.jam_checkout)}</div>
                    {it.status === "selesai" && <div className="text-sm font-semibold mt-1">{fmtRp(it.total)}</div>}
                  </div>
                ))}
                {(history?.items || []).length === 0 && <div className="text-slate-400 text-center py-3 text-sm">Tidak ada transaksi Day Use tercatat</div>}
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editingGuest ? `Edit Tamu — ${editingGuest.nama}` : "Tambah Tamu"}</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <div>
              <Label>Nama</Label>
              <Input data-testid="guest-form-nama" value={guestForm.nama} onChange={(e) => setGuestForm((f) => ({ ...f, nama: e.target.value }))} className="mt-1.5" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>No HP</Label>
                <Input data-testid="guest-form-hp" value={guestForm.no_hp} onChange={(e) => setGuestForm((f) => ({ ...f, no_hp: e.target.value }))} placeholder="628xxxxxxxxxx" className="mt-1.5" />
              </div>
              <div>
                <Label>No KTP</Label>
                <Input data-testid="guest-form-ktp" value={guestForm.no_identitas} onChange={(e) => setGuestForm((f) => ({ ...f, no_identitas: e.target.value }))} className="mt-1.5" />
              </div>
            </div>
            <div>
              <Label>Kendaraan</Label>
              <Input data-testid="guest-form-kendaraan" value={guestForm.kendaraan} onChange={(e) => setGuestForm((f) => ({ ...f, kendaraan: e.target.value }))} placeholder="Plat nomor (opsional)" className="mt-1.5" />
            </div>
            {!editingGuest && <p className="text-xs text-slate-500">Isi minimal salah satu: No HP atau No KTP.</p>}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setFormOpen(false)}>Batal</Button>
            <Button data-testid="guest-form-save" className="bg-blue-700 hover:bg-blue-800" disabled={saving} onClick={saveGuest}>
              {saving ? "Menyimpan..." : "Simpan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
