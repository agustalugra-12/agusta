import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import api, { fmtDateTime, fmtRp, waLink, bookingConfirmationWaLink, statusBayarOf, STATUS_BAYAR_LABEL, STATUS_BAYAR_BADGE_CLASS } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Search, X, Ban, CreditCard, MessageCircle, Phone, History, Sparkles, Plus, PencilLine } from "lucide-react";

const toLocalInput = (iso) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

const STATUS_OPTIONS = ["Semua", "aktif", "booking_pending", "booking_paid", "checked_in", "cancelled", "no_show"];
// Label status LIFECYCLE booking (aktif/pending/dst) — beda dari status BAYAR (Belum
// Bayar/DP/Lunas, lihat STATUS_BAYAR_LABEL di apiClient.js). "booking_paid" cuma berarti
// "sudah ada pembayaran masuk & terkonfirmasi", BUKAN otomatis lunas (bisa DP) — makanya
// labelnya "Terkonfirmasi", bukan "Lunas", supaya tidak tumpang tindih dengan badge bayar.
const STATUS_LABEL = {
  aktif: "Aktif", booking_pending: "Menunggu Bayar", booking_paid: "Terkonfirmasi",
  checked_in: "Sudah Check-In", cancelled: "Dibatalkan", no_show: "No-Show",
};
const STATUS_BADGE = {
  aktif: "bg-blue-100 text-blue-800", booking_pending: "bg-amber-100 text-amber-800",
  booking_paid: "bg-emerald-100 text-emerald-800", checked_in: "bg-violet-100 text-violet-800",
  cancelled: "bg-slate-200 text-slate-600", no_show: "bg-red-100 text-red-700",
};
const SOURCE_BADGE = {
  walk_in: "bg-slate-100 text-slate-700", online: "bg-blue-100 text-blue-800",
  ota: "bg-purple-100 text-purple-800", whatsapp_request: "bg-emerald-100 text-emerald-800",
};
const SOURCE_LABEL = { online: "Online", ota: "OTA", whatsapp_request: "WhatsApp AI" };
const CANCELLABLE = ["aktif", "booking_pending", "booking_paid"];

export default function DaftarReservasi() {
  // Tab awal bisa didorong lewat URL (?tab=tamu) — dipakai sidebar "Data Tamu" supaya
  // langsung buka tab Tamu, bukan cuma tab Reservasi default (permintaan user 2026-07-19:
  // Data Tamu sebelumnya cuma tab tersembunyi di dalam halaman Reservasi, kurang mudah
  // ditemukan lewat sidebar).
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState(searchParams.get("tab") === "tamu" ? "tamu" : "reservasi");
  const gantiTab = (t) => { setTab(t); setSearchParams(t === "tamu" ? { tab: "tamu" } : {}, { replace: true }); };
  return (
    <div className="space-y-6" data-testid="daftar-reservasi-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Reservasi</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Reservasi &amp; Tamu</h1>
        <p className="text-slate-500 mt-1">Semua pemesanan (walk-in &amp; online) dan riwayat tamu dalam satu halaman.</p>
      </div>

      <Tabs value={tab} onValueChange={gantiTab}>
        <TabsList>
          <TabsTrigger value="reservasi" data-testid="tab-reservasi">Reservasi</TabsTrigger>
          <TabsTrigger value="tamu" data-testid="tab-tamu">Tamu</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === "reservasi" ? <ReservasiTab /> : <TamuTab />}
    </div>
  );
}

function ReservasiTab() {
  const [reservations, setReservations] = useState([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Semua");
  const [date, setDate] = useState("");
  const [selected, setSelected] = useState(null);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({ jam_mulai: "", jam_selesai: "" });
  const [nominalOta, setNominalOta] = useState("");
  const [konfirmasiSaving, setKonfirmasiSaving] = useState(false);

  const load = async () => {
    const params = {};
    if (search) params.search = search;
    if (status !== "Semua") params.status = status;
    if (date) params.date = date;
    const { data } = await api.get("/bookings", { params });
    setReservations(data);
  };
  useEffect(() => { load(); }, [status, date]);
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [search]);

  const resetFilters = () => { setSearch(""); setStatus("Semua"); setDate(""); };
  const hasActiveFilter = search || status !== "Semua" || date;

  const openEdit = () => {
    setEditForm({ jam_mulai: toLocalInput(selected.jam_mulai), jam_selesai: toLocalInput(selected.jam_selesai) });
    setEditMode(true);
  };

  const saveEdit = async () => {
    if (!window.confirm(`Simpan perubahan jadwal untuk reservasi ${selected.kode}?`)) return;
    try {
      await api.put(`/bookings/${selected.id}`, {
        jam_mulai: new Date(editForm.jam_mulai).toISOString(),
        jam_selesai: new Date(editForm.jam_selesai).toISOString(),
      });
      toast.success(`Reservasi ${selected.kode} diperbarui`);
      setEditMode(false); setSelected(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const cancelReservation = async () => {
    if (!window.confirm(`Batalkan reservasi ${selected.kode} (${selected.nama_tamu})? Tindakan ini tidak dapat diurungkan.`)) return;
    try {
      await api.delete(`/bookings/${selected.id}`);
      toast.success(`Reservasi ${selected.kode} dibatalkan`);
      setSelected(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const konfirmasiHargaOta = async () => {
    const nominal = parseInt(nominalOta, 10);
    if (!nominal || nominal <= 0) { toast.error("Isi nominal yang valid"); return; }
    setKonfirmasiSaving(true);
    try {
      await api.post(`/bookings/${selected.id}/konfirmasi-harga-ota`, { total_nominal: nominal });
      toast.success(`Nominal OTA untuk ${selected.kode} dikonfirmasi`);
      setNominalOta(""); setSelected(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setKonfirmasiSaving(false); }
  };

  return (
    <div className="space-y-6">
      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <Label htmlFor="reservasi-search">Cari nama tamu / kode</Label>
            <div className="relative mt-1.5">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <Input id="reservasi-search" data-testid="reservasi-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Mis: Dewi, BK-2026…" className="pl-9" />
            </div>
          </div>
          <div className="w-full sm:w-48">
            <Label htmlFor="reservasi-status">Status</Label>
            <select id="reservasi-status" data-testid="reservasi-filter-status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm">
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s === "Semua" ? "Semua" : STATUS_LABEL[s]}</option>)}
            </select>
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="reservasi-tanggal">Tanggal</Label>
            <Input id="reservasi-tanggal" data-testid="reservasi-filter-tanggal" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="mt-1.5" />
          </div>
          {hasActiveFilter && (
            <Button data-testid="reservasi-reset-filter" variant="ghost" size="sm" onClick={resetFilters} className="gap-1.5">
              <X className="w-3.5 h-3.5" /> Reset
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm" data-testid="reservasi-table">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Kode</th>
                <th className="text-left p-3">Tamu</th>
                <th className="text-left p-3">Kamar</th>
                <th className="text-left p-3">Check-in</th>
                <th className="text-left p-3">Check-out</th>
                <th className="text-left p-3">Sumber</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Status Bayar</th>
              </tr>
            </thead>
            <tbody>
              {reservations.map((r) => {
                const sb = statusBayarOf(r);
                return (
                <tr key={r.id} data-testid={`reservasi-row-${r.kode}`} onClick={() => setSelected(r)} className="border-t border-slate-100 cursor-pointer hover:bg-slate-50">
                  <td className="p-3 font-bold">
                    {r.kode}
                    {r.ota_harga_dikonfirmasi === false && (
                      <span title="Nominal OTA belum dikonfirmasi" className="ml-1.5 inline-block w-2 h-2 rounded-full bg-amber-500 align-middle" />
                    )}
                  </td>
                  <td className="p-3">{r.nama_tamu}</td>
                  <td className="p-3">{r.room_nomor} ({r.room_tipe})</td>
                  <td className="p-3">{fmtDateTime(r.jam_mulai)}</td>
                  <td className="p-3">{fmtDateTime(r.jam_selesai)}</td>
                  <td className="p-3"><span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${SOURCE_BADGE[r.source] || "bg-slate-100 text-slate-700"}`}>{SOURCE_LABEL[r.source] || "Walk-in"}</span></td>
                  <td className="p-3"><span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${STATUS_BADGE[r.status] || "bg-slate-100 text-slate-700"}`}>{STATUS_LABEL[r.status] || r.status}</span></td>
                  <td className="p-3"><span data-testid={`reservasi-status-bayar-${r.kode}`} className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${STATUS_BAYAR_BADGE_CLASS[sb.status_bayar]}`}>{STATUS_BAYAR_LABEL[sb.status_bayar]}</span></td>
                </tr>
                );
              })}
              {reservations.length === 0 && (
                <tr><td colSpan={8} className="p-6 text-center text-slate-500">Tidak ada reservasi yang cocok dengan pencarian/filter</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) { setSelected(null); setEditMode(false); } }}>
        <DialogContent>
          <DialogHeader><DialogTitle data-testid="reservasi-detail-title">Reservasi {selected?.kode}</DialogTitle></DialogHeader>
          {selected && !editMode && (
            <div className="space-y-2 text-sm" data-testid="reservasi-detail-body">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${selected.tipe === "menginap" ? "bg-blue-700 text-white" : "bg-orange-100 text-orange-800"}`}>{selected.tipe === "menginap" ? "Menginap" : "Day Use"}</span>
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${STATUS_BADGE[selected.status] || "bg-slate-100 text-slate-700"}`}>{STATUS_LABEL[selected.status] || selected.status}</span>
                {(() => { const sb = statusBayarOf(selected); return (
                  <span data-testid="reservasi-detail-status-bayar" className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${STATUS_BAYAR_BADGE_CLASS[sb.status_bayar]}`}>{STATUS_BAYAR_LABEL[sb.status_bayar]}</span>
                ); })()}
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${SOURCE_BADGE[selected.source] || "bg-slate-100 text-slate-700"}`}>{SOURCE_LABEL[selected.source] || "Walk-in"}</span>
                {selected.ota_harga_dikonfirmasi === false && (
                  <span data-testid="reservasi-harga-belum-dikonfirmasi" className="text-[10px] uppercase font-bold px-2 py-1 rounded bg-amber-100 text-amber-800">Nominal Belum Dikonfirmasi</span>
                )}
              </div>
              <div><span className="text-slate-500">Tamu:</span> <b>{selected.nama_tamu}</b></div>
              {selected.no_hp && <div><span className="text-slate-500">HP:</span> {selected.no_hp}</div>}
              <div><span className="text-slate-500">Kamar:</span> {selected.room_nomor} ({selected.room_tipe})</div>
              <div><span className="text-slate-500">Jumlah Tamu:</span> {selected.jumlah_tamu}</div>
              <div><span className="text-slate-500">Check-in:</span> {fmtDateTime(selected.jam_mulai)}</div>
              <div><span className="text-slate-500">Check-out:</span> {fmtDateTime(selected.jam_selesai)}</div>
              {selected.total != null && (() => {
                const sb = statusBayarOf(selected);
                return (
                  <div className="bg-slate-50 border border-slate-200 rounded p-2 mt-2 text-xs space-y-1">
                    <div className="flex justify-between"><span className="text-slate-500">Subtotal</span><b>{fmtRp(selected.subtotal || 0)}</b></div>
                    {selected.diskon_member_persen > 0 && (
                      <div className="flex justify-between text-amber-700"><span>✨ Diskon Member ({selected.diskon_member_persen}%, kedatangan ke-{selected.kedatangan_ke})</span><b>-{fmtRp(selected.diskon_member_rp || 0)}</b></div>
                    )}
                    <div className="flex justify-between"><span className="text-slate-500">Service Fee 3%</span><b>{fmtRp(selected.service_fee || 0)}</b></div>
                    <div className="flex justify-between border-t pt-1 mt-1"><span className="font-bold">Total Booking</span><b className="text-blue-700">{fmtRp(selected.total)}</b></div>
                    {sb.jumlah_dibayar > 0 && <div className="flex justify-between"><span className="text-slate-500">Sudah Dibayar</span><b className="text-emerald-700">{fmtRp(sb.jumlah_dibayar)}</b></div>}
                    {sb.sisa_tagihan > 0 && (
                      <div className="flex justify-between pt-1 border-t border-amber-300 bg-amber-50 -mx-2 -mb-1 mt-1 px-2 pb-1 rounded-b">
                        <span className="font-bold text-amber-800">Sisa</span>
                        <b className="text-amber-900">{fmtRp(sb.sisa_tagihan)}</b>
                      </div>
                    )}
                    {sb.status_bayar === "dp" && <div className="text-slate-500">Pelunasan: Bayar saat Check-in</div>}
                  </div>
                );
              })()}
              {selected.ota_harga_dikonfirmasi === false && (
                <div className="bg-amber-50 border border-amber-200 rounded p-2 mt-2 text-xs space-y-2" data-testid="reservasi-konfirmasi-harga-ota">
                  <p className="text-amber-800">
                    Nominal di atas ({fmtRp(selected.total)}) masih <b>estimasi</b> dari tarif publik PMS — email OTA "Prepaid"
                    ini tidak mencantumkan nominal aslinya. Belum dihitung sebagai pendapatan di laporan sampai dikonfirmasi.
                    Isi nominal settlement asli begitu laporan/invoice dari OTA diterima:
                  </p>
                  <div className="flex gap-2">
                    <Input
                      data-testid="input-nominal-ota" type="number" placeholder="Nominal asli (Rp)"
                      value={nominalOta} onChange={(e) => setNominalOta(e.target.value)} className="h-8 text-xs"
                    />
                    <Button
                      data-testid="btn-konfirmasi-harga-ota" size="sm" disabled={konfirmasiSaving}
                      onClick={konfirmasiHargaOta} className="h-8 bg-amber-700 hover:bg-amber-800 shrink-0"
                    >
                      Konfirmasi
                    </Button>
                  </div>
                </div>
              )}
              {selected.catatan && <div className="italic text-slate-600">&ldquo;{selected.catatan}&rdquo;</div>}
              <div className="text-[10px] text-slate-400 pt-1">Dibuat oleh {selected.created_by}</div>
            </div>
          )}
          {selected && editMode && (
            <div className="space-y-3 text-sm" data-testid="reservasi-edit-form">
              <div><Label>Check-in</Label><Input data-testid="edit-jam-mulai" type="datetime-local" value={editForm.jam_mulai} onChange={(e) => setEditForm((f) => ({ ...f, jam_mulai: e.target.value }))} /></div>
              <div><Label>Check-out</Label><Input data-testid="edit-jam-selesai" type="datetime-local" value={editForm.jam_selesai} onChange={(e) => setEditForm((f) => ({ ...f, jam_selesai: e.target.value }))} /></div>
            </div>
          )}
          <DialogFooter className="flex-wrap gap-2">
            {selected && !editMode && (
              <Button asChild data-testid="reservasi-lihat-pembayaran" variant="outline" className="gap-1.5">
                <Link to={`/pembayaran?kode=${encodeURIComponent(selected.kode)}`}><CreditCard className="w-3.5 h-3.5" /> Lihat Pembayaran</Link>
              </Button>
            )}
            {selected && !editMode && selected.no_hp && (
              <a data-testid="reservasi-wa" href={bookingConfirmationWaLink(selected)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-3 h-9 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold">
                <MessageCircle className="w-3.5 h-3.5" /> WhatsApp
              </a>
            )}
            {selected && !editMode && CANCELLABLE.includes(selected.status) && (
              <>
                <Button data-testid="reservasi-batalkan" variant="outline" onClick={cancelReservation} className="gap-1.5 text-red-600 border-red-300 hover:bg-red-50"><Ban className="w-3.5 h-3.5" /> Batalkan</Button>
                <Button data-testid="reservasi-ubah" variant="outline" onClick={openEdit} className="gap-1.5">Ubah Jadwal</Button>
              </>
            )}
            {selected && editMode && (
              <>
                <Button variant="ghost" onClick={() => setEditMode(false)}>Batal</Button>
                <Button data-testid="reservasi-simpan-ubah" onClick={saveEdit} className="bg-blue-700 hover:bg-blue-800">Simpan Perubahan</Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const emptyGuestForm = { nama: "", no_hp: "", no_identitas: "", kendaraan: "" };

function TamuTab() {
  const [q, setQ] = useState("");
  const [guests, setGuests] = useState([]);
  const [history, setHistory] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingGuest, setEditingGuest] = useState(null);
  const [guestForm, setGuestForm] = useState(emptyGuestForm);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const { data } = await api.get("/guests", { params: q ? { q } : {} });
    setGuests(data);
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [q]);

  const showHistory = async (g) => {
    const { data } = await api.get(`/guests/${g.id}/history`);
    setHistory({ guest: g, items: data });
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
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row gap-3">
        <Input data-testid="search-guest" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama, HP, atau No KTP..." className="h-12 flex-1" />
        <Button data-testid="guest-add-btn" onClick={openAddGuest} className="h-12 gap-1.5 bg-blue-700 hover:bg-blue-800 shrink-0">
          <Plus className="w-4 h-4" /> Tambah Tamu
        </Button>
      </div>
      <div className="space-y-2">
        {guests.map(g => (
          <Card key={g.id} className="border-slate-200" data-testid={`guest-row-${g.id}`}>
            <CardContent className="p-4 flex flex-wrap items-center gap-4">
              <div className="min-w-[180px]">
                <div className="font-bold text-base">{g.nama}</div>
                <div className="text-xs text-slate-500">{g.no_hp || "-"} • {g.no_identitas || "-"}</div>
              </div>
              <div className="flex items-center gap-2 text-xs shrink-0">
                <div className="bg-slate-50 rounded-lg px-2.5 py-1.5"><span className="text-slate-500">Kunjungan </span><span className="font-bold">{g.total_kunjungan || 0}×</span></div>
                <div className="bg-slate-50 rounded-lg px-2.5 py-1.5"><span className="text-slate-500">Total Trx </span><span className="font-bold">{fmtRp(g.total_transaksi || 0)}</span></div>
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
            </CardContent>
          </Card>
        ))}
        {guests.length === 0 && <div className="text-slate-500 text-center py-10">Belum ada data tamu</div>}
      </div>

      <Dialog open={!!history} onOpenChange={(o) => !o && setHistory(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Riwayat {history?.guest?.nama}</DialogTitle></DialogHeader>
          <div className="max-h-96 overflow-y-auto space-y-2">
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
            {(history?.items || []).length === 0 && <div className="text-slate-500 text-center py-6">Belum ada riwayat</div>}
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
