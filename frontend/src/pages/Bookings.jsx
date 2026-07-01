import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDateTime, bookingConfirmationWaLink } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Trash2, LogIn, BedDouble, Clock, Pencil, MessageCircle } from "lucide-react";

const nowLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const plusHours = (s, h) => { const d = new Date(s); d.setHours(d.getHours() + h); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

export default function Bookings() {
  const [items, setItems] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [filter, setFilter] = useState("aktif");
  const [open, setOpen] = useState(false);
  const [editId, setEditId] = useState(null);
  const [form, setForm] = useState({
    tipe: "day_use", room_id: "", nama_tamu: "", no_hp: "", no_identitas: "", kendaraan: "", jumlah_tamu: 1,
    jam_mulai: nowLocal(), jam_selesai: plusHours(nowLocal(), 6), catatan: "",
  });

  const load = async () => {
    const params = filter === "all" ? {} : { status: filter };
    const [b, r] = await Promise.all([api.get("/bookings", { params }), api.get("/rooms")]);
    setItems(b.data); setRooms(r.data);
  };
  useEffect(() => { load(); }, [filter]);

  const onTipeChange = (t) => {
    setForm(f => ({
      ...f, tipe: t,
      jam_selesai: t === "day_use" ? plusHours(f.jam_mulai, 6) : plusHours(f.jam_mulai, 24),
    }));
  };
  const onMulaiChange = (v) => {
    setForm(f => ({ ...f, jam_mulai: v, jam_selesai: f.tipe === "day_use" ? plusHours(v, 6) : f.jam_selesai }));
  };

  const submit = async () => {
    if (!form.room_id || !form.nama_tamu.trim()) { toast.error("Pilih kamar dan isi nama tamu"); return; }
    try {
      const payload = {
        ...form,
        jumlah_tamu: Number(form.jumlah_tamu) || 1,
        jam_mulai: new Date(form.jam_mulai).toISOString(),
        jam_selesai: new Date(form.jam_selesai).toISOString(),
      };
      if (editId) await api.put(`/bookings/${editId}`, payload);
      else await api.post("/bookings", payload);
      toast.success(editId ? "Booking diperbarui" : "Booking dibuat");
      setOpen(false); setEditId(null); load();
    } catch (e) {
      const msg = e?.response?.data?.detail || "Gagal";
      toast.error(msg);
      // Jika gagal karena overlap, fetch tanggal alternatif
      if (/sudah dibooking|tersedia/i.test(msg) && form.room_id) {
        try {
          const dStr = form.jam_mulai.slice(0, 10);
          const { data } = await api.get("/bookings/availability", { params: { room_id: form.room_id, from_date: dStr, days: 14 } });
          setAvailability(data);
        } catch (err) { /* ignore — availability lookup is best-effort */ }
      }
    }
  };

  const [availability, setAvailability] = useState(null);
  const pickAlternativeDate = (dateStr) => {
    // ganti hanya tanggal di jam_mulai/jam_selesai, jaga jam
    const replaceDate = (iso, newDate) => `${newDate}${iso.slice(10)}`;
    setForm(f => ({ ...f, jam_mulai: replaceDate(f.jam_mulai, dateStr), jam_selesai: replaceDate(f.jam_selesai, dateStr) }));
    setAvailability(null);
  };

  const selectedRoom = rooms.find(r => r.id === form.room_id);
  const estTotal = useMemo(() => {
    if (!selectedRoom || form.tipe !== "day_use") return null;
    // estimasi tarif dasar 6 jam saja (tidak hitung overtime untuk booking)
    const subtotal = selectedRoom.tarif;
    const svc = Math.round(subtotal * 0.03);
    return { subtotal, service_fee: svc, total: subtotal + svc };
  }, [selectedRoom, form.tipe]);


  const openEdit = (b) => {
    const toLocal = (iso) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
    setForm({
      tipe: b.tipe, room_id: b.room_id, nama_tamu: b.nama_tamu, no_hp: b.no_hp || "",
      no_identitas: b.no_identitas || "", kendaraan: b.kendaraan || "", jumlah_tamu: b.jumlah_tamu || 1,
      jam_mulai: toLocal(b.jam_mulai), jam_selesai: toLocal(b.jam_selesai), catatan: b.catatan || "",
    });
    setEditId(b.id);
    setOpen(true);
  };

  const openNew = () => {
    setEditId(null);
    setForm({
      tipe: "day_use", room_id: "", nama_tamu: "", no_hp: "", no_identitas: "", kendaraan: "", jumlah_tamu: 1,
      jam_mulai: nowLocal(), jam_selesai: plusHours(nowLocal(), 6), catatan: "",
    });
    setOpen(true);
  };

  const cancel = async (b) => {
    if (!window.confirm(`Batalkan booking ${b.kode}?`)) return;
    try { await api.delete(`/bookings/${b.id}`); toast.success("Dibatalkan"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const doCheckin = async (b) => {
    try {
      await api.post(`/bookings/${b.id}/checkin`);
      toast.success(`Booking ${b.kode} di-aktivasi`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Booking</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Daftar Booking</h1>
        </div>
        <Button data-testid="add-booking" onClick={openNew} className="bg-blue-700 hover:bg-blue-800"><Plus className="w-4 h-4 mr-2" /> Booking Baru</Button>
      </div>

      <Tabs value={filter} onValueChange={setFilter}>
        <TabsList>
          <TabsTrigger value="aktif" data-testid="filter-aktif">Aktif</TabsTrigger>
          <TabsTrigger value="checked_in" data-testid="filter-checked">Sudah Check-In</TabsTrigger>
          <TabsTrigger value="cancelled" data-testid="filter-dibatalkan">Dibatalkan</TabsTrigger>
          <TabsTrigger value="all" data-testid="filter-all">Semua</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map(b => (
          <Card key={b.id} className={`border ${b.tipe === "menginap" ? "border-blue-200 bg-blue-50/40" : "border-slate-200"}`}>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">{b.kode}</div>
                  <div className="font-bold text-lg">{b.nama_tamu}</div>
                </div>
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${b.tipe === "menginap" ? "bg-blue-700 text-white" : "bg-orange-100 text-orange-800"}`}>
                  {b.tipe === "menginap" ? "Menginap" : "Day Use"}
                </span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <BedDouble className="w-4 h-4 text-slate-500" />
                Kamar <span className="font-bold">{b.room_nomor}</span> ({b.room_tipe})
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-600">
                <Clock className="w-3.5 h-3.5" />
                {fmtDateTime(b.jam_mulai)} → {fmtDateTime(b.jam_selesai)}
              </div>
              {b.no_hp && <div className="text-xs text-slate-500">HP: {b.no_hp}</div>}
              {b.catatan && <div className="text-xs text-slate-500 italic">&ldquo;{b.catatan}&rdquo;</div>}
              <div className="text-[10px] text-slate-400">Status: {b.status} • dibuat oleh {b.created_by}</div>
              {b.no_hp && (
                <a
                  data-testid={`wa-${b.kode}`}
                  href={bookingConfirmationWaLink(b)}
                  target="_blank" rel="noreferrer"
                  className="inline-flex items-center justify-center gap-2 w-full px-3 h-9 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold"
                >
                  <MessageCircle className="w-3.5 h-3.5" /> Kirim WhatsApp Konfirmasi
                </a>
              )}
              {b.status === "aktif" && (
                <div className="flex gap-2 pt-2 border-t border-slate-100">
                  <Button data-testid={`activate-${b.kode}`} size="sm" onClick={() => doCheckin(b)} className="bg-emerald-600 hover:bg-emerald-700 flex-1">
                    <LogIn className="w-3.5 h-3.5 mr-1" /> Aktivasi
                  </Button>
                  <Button data-testid={`edit-${b.kode}`} size="sm" variant="outline" onClick={() => openEdit(b)}>
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                  <Button data-testid={`cancel-${b.kode}`} size="sm" variant="outline" onClick={() => cancel(b)}>
                    <Trash2 className="w-3.5 h-3.5 text-red-500" />
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
        {items.length === 0 && <div className="col-span-full text-slate-500 text-center py-10">Belum ada booking</div>}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{editId ? "Edit Booking" : "Booking Baru"}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3 max-h-[70vh] overflow-y-auto">
            <div className="col-span-2">
              <Label>Tipe Booking</Label>
              <div className="grid grid-cols-2 gap-2 mt-1.5">
                <Button type="button" variant={form.tipe === "day_use" ? "default" : "outline"} className={form.tipe === "day_use" ? "bg-orange-500 hover:bg-orange-600" : ""} onClick={() => onTipeChange("day_use")} data-testid="tipe-dayuse">Day Use</Button>
                <Button type="button" variant={form.tipe === "menginap" ? "default" : "outline"} className={form.tipe === "menginap" ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => onTipeChange("menginap")} data-testid="tipe-menginap">Blok / Menginap</Button>
              </div>
            </div>
            <div className="col-span-2">
              <Label>Kamar</Label>
              <select data-testid="bk-room" value={form.room_id} onChange={(e) => setForm(f => ({ ...f, room_id: e.target.value }))} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5">
                <option value="">— Pilih kamar —</option>
                {rooms.map(r => <option key={r.id} value={r.id}>Kamar {r.nomor} ({r.tipe}) — {r.status}</option>)}
              </select>
            </div>
            <div className="col-span-2"><Label>Nama Tamu</Label><Input data-testid="bk-nama" value={form.nama_tamu} onChange={(e) => setForm(f => ({ ...f, nama_tamu: e.target.value }))} /></div>
            <div><Label>HP</Label><Input data-testid="bk-hp" value={form.no_hp} onChange={(e) => setForm(f => ({ ...f, no_hp: e.target.value }))} /></div>
            <div><Label>KTP</Label><Input value={form.no_identitas} onChange={(e) => setForm(f => ({ ...f, no_identitas: e.target.value }))} /></div>
            <div><Label>Kendaraan</Label><Input value={form.kendaraan} onChange={(e) => setForm(f => ({ ...f, kendaraan: e.target.value }))} /></div>
            <div><Label>Jumlah Tamu</Label><Input type="number" min="1" value={form.jumlah_tamu} onChange={(e) => setForm(f => ({ ...f, jumlah_tamu: e.target.value }))} /></div>
            <div><Label>{form.tipe === "menginap" ? "Tanggal Check-In" : "Jam Check-In"}</Label><Input data-testid="bk-mulai" type="datetime-local" value={form.jam_mulai} onChange={(e) => onMulaiChange(e.target.value)} /></div>
            <div><Label>{form.tipe === "menginap" ? "Tanggal Check-Out" : "Estimasi Selesai"}</Label><Input data-testid="bk-selesai" type="datetime-local" value={form.jam_selesai} onChange={(e) => setForm(f => ({ ...f, jam_selesai: e.target.value }))} /></div>
            <div className="col-span-2"><Label>Catatan</Label><Textarea value={form.catatan} onChange={(e) => setForm(f => ({ ...f, catatan: e.target.value }))} rows={2} /></div>
            {estTotal && (
              <div data-testid="booking-est-summary" className="col-span-2 rounded-lg bg-blue-50 border border-blue-200 p-3 text-sm space-y-1">
                <div className="flex justify-between"><span className="text-slate-600">Tarif Kamar (6 jam)</span><b>{fmtRp(estTotal.subtotal)}</b></div>
                <div className="flex justify-between"><span className="text-slate-600">Service Fee (3%)</span><b data-testid="booking-service-fee">{fmtRp(estTotal.service_fee)}</b></div>
                <div className="flex justify-between text-base pt-1 border-t border-blue-200 mt-1"><span className="font-bold">Estimasi Total</span><b className="text-blue-700">{fmtRp(estTotal.total)}</b></div>
                <p className="text-[10px] text-slate-500">*Belum termasuk overtime. Service fee 3% ditambahkan saat check-out.</p>
              </div>
            )}
            {availability && (
              <div data-testid="alt-dates" className="col-span-2 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm">
                <p className="font-semibold text-amber-900 mb-2">Kamar {availability.room_nomor} tidak tersedia di tanggal pilihan. Tanggal alternatif yang masih kosong:</p>
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                  {availability.slots.filter(s => s.available).slice(0, 10).map(s => (
                    <Button key={s.date} type="button" data-testid={`alt-${s.date}`} size="sm" variant="outline" onClick={() => pickAlternativeDate(s.date)} className="text-xs border-amber-300 hover:bg-amber-100">
                      {new Date(`${s.date}T00:00:00`).toLocaleDateString("id-ID", { day: "2-digit", month: "short" })}
                    </Button>
                  ))}
                  {availability.slots.filter(s => s.available).length === 0 && <span className="text-xs text-slate-500 col-span-full">Tidak ada slot kosong dalam 14 hari kedepan.</span>}
                </div>
                <Button type="button" size="sm" variant="ghost" onClick={() => setAvailability(null)} className="text-xs mt-2 h-7">Tutup</Button>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Batal</Button>
            <Button data-testid="save-booking" onClick={submit} className="bg-blue-700 hover:bg-blue-800">Simpan Booking</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
