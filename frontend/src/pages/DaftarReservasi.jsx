import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import api, { fmtDateTime, fmtRp, waLink, bookingConfirmationWaLink } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Search, X, Ban, CreditCard, MessageCircle, Phone, History } from "lucide-react";

const toLocalInput = (iso) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

const STATUS_OPTIONS = ["Semua", "aktif", "booking_pending", "booking_paid", "checked_in", "cancelled", "no_show"];
const STATUS_LABEL = {
  aktif: "Aktif", booking_pending: "Menunggu Bayar", booking_paid: "Lunas",
  checked_in: "Sudah Check-In", cancelled: "Dibatalkan", no_show: "No-Show",
};
const STATUS_BADGE = {
  aktif: "bg-blue-100 text-blue-800", booking_pending: "bg-amber-100 text-amber-800",
  booking_paid: "bg-emerald-100 text-emerald-800", checked_in: "bg-violet-100 text-violet-800",
  cancelled: "bg-slate-200 text-slate-600", no_show: "bg-red-100 text-red-700",
};
const SOURCE_BADGE = { walk_in: "bg-slate-100 text-slate-700", online: "bg-blue-100 text-blue-800" };
const CANCELLABLE = ["aktif", "booking_pending", "booking_paid"];

export default function DaftarReservasi() {
  const [tab, setTab] = useState("reservasi");
  return (
    <div className="space-y-6" data-testid="daftar-reservasi-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Reservasi</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Reservasi &amp; Tamu</h1>
        <p className="text-slate-500 mt-1">Semua pemesanan (walk-in &amp; online) dan riwayat tamu dalam satu halaman.</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
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
              </tr>
            </thead>
            <tbody>
              {reservations.map((r) => (
                <tr key={r.id} data-testid={`reservasi-row-${r.kode}`} onClick={() => setSelected(r)} className="border-t border-slate-100 cursor-pointer hover:bg-slate-50">
                  <td className="p-3 font-bold">{r.kode}</td>
                  <td className="p-3">{r.nama_tamu}</td>
                  <td className="p-3">{r.room_nomor} ({r.room_tipe})</td>
                  <td className="p-3">{fmtDateTime(r.jam_mulai)}</td>
                  <td className="p-3">{fmtDateTime(r.jam_selesai)}</td>
                  <td className="p-3"><span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${SOURCE_BADGE[r.source] || "bg-slate-100 text-slate-700"}`}>{r.source === "online" ? "Online" : "Walk-in"}</span></td>
                  <td className="p-3"><span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${STATUS_BADGE[r.status] || "bg-slate-100 text-slate-700"}`}>{STATUS_LABEL[r.status] || r.status}</span></td>
                </tr>
              ))}
              {reservations.length === 0 && (
                <tr><td colSpan={7} className="p-6 text-center text-slate-500">Tidak ada reservasi yang cocok dengan pencarian/filter</td></tr>
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
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${SOURCE_BADGE[selected.source] || "bg-slate-100 text-slate-700"}`}>{selected.source === "online" ? "Online" : "Walk-in"}</span>
              </div>
              <div><span className="text-slate-500">Tamu:</span> <b>{selected.nama_tamu}</b></div>
              {selected.no_hp && <div><span className="text-slate-500">HP:</span> {selected.no_hp}</div>}
              <div><span className="text-slate-500">Kamar:</span> {selected.room_nomor} ({selected.room_tipe})</div>
              <div><span className="text-slate-500">Jumlah Tamu:</span> {selected.jumlah_tamu}</div>
              <div><span className="text-slate-500">Check-in:</span> {fmtDateTime(selected.jam_mulai)}</div>
              <div><span className="text-slate-500">Check-out:</span> {fmtDateTime(selected.jam_selesai)}</div>
              {selected.total != null && (
                <div className="bg-slate-50 border border-slate-200 rounded p-2 mt-2 text-xs space-y-1">
                  <div className="flex justify-between"><span className="text-slate-500">Subtotal</span><b>{fmtRp(selected.subtotal || 0)}</b></div>
                  <div className="flex justify-between"><span className="text-slate-500">Service Fee 3%</span><b>{fmtRp(selected.service_fee || 0)}</b></div>
                  <div className="flex justify-between border-t pt-1 mt-1"><span className="font-bold">Total</span><b className="text-blue-700">{fmtRp(selected.total)}</b></div>
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

function TamuTab() {
  const [q, setQ] = useState("");
  const [guests, setGuests] = useState([]);
  const [history, setHistory] = useState(null);

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

  return (
    <div className="space-y-6">
      <Input data-testid="search-guest" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama, HP, atau No KTP..." className="h-12" />
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {guests.map(g => (
          <Card key={g.id} className="border-slate-200">
            <CardContent className="p-4 space-y-3">
              <div>
                <div className="font-bold text-base">{g.nama}</div>
                <div className="text-xs text-slate-500">{g.no_hp || "-"} • {g.no_identitas || "-"}</div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-slate-50 rounded-lg p-2"><div className="text-slate-500">Kunjungan</div><div className="font-bold">{g.total_kunjungan || 0}×</div></div>
                <div className="bg-slate-50 rounded-lg p-2"><div className="text-slate-500">Total Trx</div><div className="font-bold">{fmtRp(g.total_transaksi || 0)}</div></div>
              </div>
              <div className="text-xs text-slate-500">Terakhir: {fmtDateTime(g.last_visit)}</div>
              <div className="flex gap-2">
                {g.no_hp && <a href={waLink(g.no_hp)} target="_blank" rel="noreferrer" className="flex-1"><Button size="sm" variant="outline" className="w-full"><MessageCircle className="w-3.5 h-3.5 mr-1" /> WA</Button></a>}
                {g.no_hp && <a href={`tel:${g.no_hp}`} className="flex-1"><Button size="sm" variant="outline" className="w-full"><Phone className="w-3.5 h-3.5 mr-1" /> Telepon</Button></a>}
                <Button size="sm" variant="outline" onClick={() => showHistory(g)} data-testid={`hist-${g.id}`}><History className="w-3.5 h-3.5" /></Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {guests.length === 0 && <div className="col-span-full text-slate-500 text-center py-10">Belum ada data tamu</div>}
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
    </div>
  );
}
