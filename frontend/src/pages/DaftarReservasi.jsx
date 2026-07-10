import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Search, X, Pencil, Ban } from "lucide-react";
import { fmtDateTime, fmtRp } from "@/lib/apiClient";

const ROOM_TYPES = ["Standard", "Cottage"];

const toLocalInput = (iso) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

// Data tiruan (stub) — daftar reservasi lintas saluran, sebelum tersinkron dengan Pelangi PMS/Gmail/WhatsApp.
const MOCK_RESERVATIONS = [
  { id: "1", kode: "RSV-1042", nama_tamu: "Dewi Anggraini", no_hp: "081234567001", room_tipe: "Cottage", jam_mulai: "2026-07-11T14:00:00", jam_selesai: "2026-07-12T12:00:00", jumlah_tamu: 2, total: 260000, status: "Confirmed", source: "Website", catatan: "Minta kamar dekat kolam." },
  { id: "2", kode: "RSV-1041", nama_tamu: "Budi Santoso", no_hp: "081234567002", room_tipe: "Standard", jam_mulai: "2026-07-11T10:00:00", jam_selesai: "2026-07-11T16:00:00", jumlah_tamu: 1, total: 123600, status: "Pending", source: "WhatsApp", catatan: "" },
  { id: "3", kode: "RSV-1040", nama_tamu: "Agoda - Ahmad Fauzi", no_hp: "", room_tipe: "Standard", jam_mulai: "2026-07-12T14:00:00", jam_selesai: "2026-07-14T12:00:00", jumlah_tamu: 2, total: 240000, status: "Confirmed", source: "OTA", catatan: "Booking via Agoda, konfirmasi email terlampir." },
  { id: "4", kode: "RSV-1039", nama_tamu: "Sri Wahyuni", no_hp: "081234567004", room_tipe: "Cottage", jam_mulai: "2026-07-10T14:00:00", jam_selesai: "2026-07-11T12:00:00", jumlah_tamu: 3, total: 130000, status: "Cancelled", source: "Website", catatan: "Dibatalkan tamu H-1." },
  { id: "5", kode: "RSV-1038", nama_tamu: "Traveloka - Rina Kusuma", no_hp: "", room_tipe: "Standard", jam_mulai: "2026-07-13T14:00:00", jam_selesai: "2026-07-15T12:00:00", jumlah_tamu: 2, total: 240000, status: "Confirmed", source: "OTA", catatan: "" },
  { id: "6", kode: "RSV-1037", nama_tamu: "Hendra Wijaya", no_hp: "081234567006", room_tipe: "Standard", jam_mulai: "2026-07-10T09:00:00", jam_selesai: "2026-07-10T15:00:00", jumlah_tamu: 1, total: 123600, status: "Pending", source: "WhatsApp", catatan: "Menunggu pembayaran DP." },
];

const SOURCE_BADGE = {
  Website: "bg-blue-100 text-blue-800",
  OTA: "bg-violet-100 text-violet-800",
  WhatsApp: "bg-emerald-100 text-emerald-800",
};

const STATUS_BADGE = {
  Confirmed: "bg-emerald-100 text-emerald-800",
  Pending: "bg-amber-100 text-amber-800",
  Cancelled: "bg-slate-200 text-slate-600",
};

const STATUS_OPTIONS = ["Semua", "Confirmed", "Pending", "Cancelled"];

export default function DaftarReservasi() {
  const [reservations, setReservations] = useState(MOCK_RESERVATIONS);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Semua");
  const [date, setDate] = useState("");
  const [selected, setSelected] = useState(null);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({ room_tipe: "", jam_mulai: "", jam_selesai: "" });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return reservations.filter((r) => {
      if (q && !r.nama_tamu.toLowerCase().includes(q) && !r.kode.toLowerCase().includes(q)) return false;
      if (status !== "Semua" && r.status !== status) return false;
      if (date) {
        const dayStart = new Date(`${date}T00:00:00`);
        const dayEnd = new Date(`${date}T23:59:59.999`);
        const start = new Date(r.jam_mulai);
        const end = new Date(r.jam_selesai);
        if (!(start <= dayEnd && end >= dayStart)) return false;
      }
      return true;
    });
  }, [reservations, search, status, date]);

  const resetFilters = () => { setSearch(""); setStatus("Semua"); setDate(""); };
  const hasActiveFilter = search || status !== "Semua" || date;

  const openEdit = () => {
    setEditForm({ room_tipe: selected.room_tipe, jam_mulai: toLocalInput(selected.jam_mulai), jam_selesai: toLocalInput(selected.jam_selesai) });
    setEditMode(true);
  };

  const saveEdit = () => {
    if (!window.confirm(`Simpan perubahan untuk reservasi ${selected.kode}?`)) return;
    const updated = {
      ...selected,
      room_tipe: editForm.room_tipe,
      jam_mulai: new Date(editForm.jam_mulai).toISOString(),
      jam_selesai: new Date(editForm.jam_selesai).toISOString(),
    };
    setReservations((rs) => rs.map((r) => (r.id === selected.id ? updated : r)));
    setSelected(updated);
    setEditMode(false);
    toast.success(`Reservasi ${selected.kode} diperbarui`);
  };

  const cancelReservation = () => {
    if (!window.confirm(`Batalkan reservasi ${selected.kode} (${selected.nama_tamu})? Tindakan ini tidak dapat diurungkan.`)) return;
    const updated = { ...selected, status: "Cancelled" };
    setReservations((rs) => rs.map((r) => (r.id === selected.id ? updated : r)));
    setSelected(updated);
    toast.success(`Reservasi ${selected.kode} dibatalkan`);
  };

  return (
    <div className="space-y-6" data-testid="daftar-reservasi-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Daftar Reservasi</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Semua Pemesanan</h1>
        <p className="text-slate-500 mt-1">
          Reservasi dari seluruh saluran (Website, OTA, WhatsApp) dalam satu daftar. Data di bawah masih data tiruan.
        </p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <Label htmlFor="reservasi-search">Cari nama tamu / kode</Label>
            <div className="relative mt-1.5">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <Input
                id="reservasi-search"
                data-testid="reservasi-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Mis: Dewi, RSV-1042…"
                className="pl-9"
              />
            </div>
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="reservasi-status">Status</Label>
            <select
              id="reservasi-status"
              data-testid="reservasi-filter-status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="reservasi-tanggal">Tanggal</Label>
            <Input
              id="reservasi-tanggal"
              data-testid="reservasi-filter-tanggal"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="mt-1.5"
            />
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
                <th className="text-left p-3">Tipe Kamar</th>
                <th className="text-left p-3">Check-in</th>
                <th className="text-left p-3">Check-out</th>
                <th className="text-left p-3">Saluran</th>
                <th className="text-left p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.id}
                  data-testid={`reservasi-row-${r.kode}`}
                  onClick={() => setSelected(r)}
                  className="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                >
                  <td className="p-3 font-bold">{r.kode}</td>
                  <td className="p-3">{r.nama_tamu}</td>
                  <td className="p-3">{r.room_tipe}</td>
                  <td className="p-3">{fmtDateTime(r.jam_mulai)}</td>
                  <td className="p-3">{fmtDateTime(r.jam_selesai)}</td>
                  <td className="p-3">
                    <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${SOURCE_BADGE[r.source]}`}>{r.source}</span>
                  </td>
                  <td className="p-3">
                    <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${STATUS_BADGE[r.status]}`}>{r.status}</span>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={7} className="p-6 text-center text-slate-500">Tidak ada reservasi yang cocok dengan pencarian/filter</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) { setSelected(null); setEditMode(false); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle data-testid="reservasi-detail-title">Reservasi {selected?.kode}</DialogTitle>
          </DialogHeader>
          {selected && !editMode && (
            <div className="space-y-2 text-sm" data-testid="reservasi-detail-body">
              <div className="flex items-center gap-2">
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${STATUS_BADGE[selected.status]}`}>{selected.status}</span>
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${SOURCE_BADGE[selected.source]}`}>{selected.source}</span>
              </div>
              <div><span className="text-slate-500">Tamu:</span> <b>{selected.nama_tamu}</b></div>
              {selected.no_hp && <div><span className="text-slate-500">HP:</span> {selected.no_hp}</div>}
              <div><span className="text-slate-500">Tipe Kamar:</span> {selected.room_tipe}</div>
              <div><span className="text-slate-500">Jumlah Tamu:</span> {selected.jumlah_tamu}</div>
              <div><span className="text-slate-500">Check-in:</span> {fmtDateTime(selected.jam_mulai)}</div>
              <div><span className="text-slate-500">Check-out:</span> {fmtDateTime(selected.jam_selesai)}</div>
              <div className="bg-slate-50 border border-slate-200 rounded p-2 mt-2">
                <div className="flex justify-between"><span className="font-bold">Total</span><b className="text-blue-700">{fmtRp(selected.total)}</b></div>
              </div>
              {selected.catatan && <div className="italic text-slate-600">&ldquo;{selected.catatan}&rdquo;</div>}
              <p className="text-[11px] text-slate-400 pt-1">Data tiruan — belum tersinkron dengan Pelangi PMS.</p>
            </div>
          )}
          {selected && editMode && (
            <div className="space-y-3 text-sm" data-testid="reservasi-edit-form">
              <div>
                <Label>Tipe Kamar</Label>
                <select
                  data-testid="edit-room-tipe"
                  value={editForm.room_tipe}
                  onChange={(e) => setEditForm((f) => ({ ...f, room_tipe: e.target.value }))}
                  className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
                >
                  {ROOM_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <Label>Check-in</Label>
                <Input data-testid="edit-jam-mulai" type="datetime-local" value={editForm.jam_mulai} onChange={(e) => setEditForm((f) => ({ ...f, jam_mulai: e.target.value }))} />
              </div>
              <div>
                <Label>Check-out</Label>
                <Input data-testid="edit-jam-selesai" type="datetime-local" value={editForm.jam_selesai} onChange={(e) => setEditForm((f) => ({ ...f, jam_selesai: e.target.value }))} />
              </div>
            </div>
          )}
          <DialogFooter>
            {selected && !editMode && selected.status !== "Cancelled" && (
              <>
                <Button data-testid="reservasi-batalkan" variant="outline" onClick={cancelReservation} className="gap-1.5 text-red-600 border-red-300 hover:bg-red-50">
                  <Ban className="w-3.5 h-3.5" /> Batalkan
                </Button>
                <Button data-testid="reservasi-ubah" variant="outline" onClick={openEdit} className="gap-1.5">
                  <Pencil className="w-3.5 h-3.5" /> Ubah Pesanan
                </Button>
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
