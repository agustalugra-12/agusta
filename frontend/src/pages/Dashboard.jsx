import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api, { fmtRp, fmtDate, statusLabel, statusColor, bookingConfirmationWaLink, statusBayarOf, STATUS_BAYAR_LABEL, STATUS_BAYAR_BADGE_CLASS } from "@/lib/apiClient";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import {
  BedDouble, AlertTriangle, Hourglass, Clock, Wallet,
  CalendarRange, Users as UsersIcon, Sparkles, Wrench, Calendar, MessageCircle, X, Inbox, Check, Percent,
} from "lucide-react";
import { SetujuiDialog, TolakDialog, ActionRequiredRedDoorz } from "@/pages/BookingRequests";
import { PembatalanAlert } from "@/pages/Pembatalan";

const STAT_CARDS = [
  { key: "kosong", label: "Kosong", icon: BedDouble, color: "#10B981" },
  { key: "dipesan_hari_ini", label: "Dipesan (Belum Tiba)", icon: CalendarRange, color: "#8B5CF6" },
  { key: "day_use", label: "Day Use", icon: Clock, color: "#EF4444" },
  { key: "menginap", label: "Menginap", icon: BedDouble, color: "#3B82F6" },
  { key: "perlu_dibersihkan", label: "Perlu Bersih", icon: Sparkles, color: "#F97316" },
  { key: "maintenance", label: "Maintenance", icon: Wrench, color: "#EAB308" },
];

const todayLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const nowLocalDateTime = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const emptyQuickForm = (tarif) => ({
  tipe: "day_use", nama_tamu: "", no_hp: "", no_identitas: "", kendaraan: "", jumlah_tamu: 1,
  jam_checkin: nowLocalDateTime(), malam: 1, harga: tarif ?? 0, catatan: "",
});

export default function Dashboard() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [summary, setSummary] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [active, setActive] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [widgets, setWidgets] = useState(null);
  const [bookingRequests, setBookingRequests] = useState([]); // waiting_approval — supaya owner/resepsionis lihat langsung dari Dashboard, tidak perlu buka halaman terpisah
  const [kedatanganHarian, setKedatanganHarian] = useState([]); // grafik kedatangan tamu 30 hari (2026-07-21, permintaan user)
  const [approveReqTarget, setApproveReqTarget] = useState(null);
  const [rejectReqTarget, setRejectReqTarget] = useState(null);
  const [filterDate, setFilterDate] = useState(todayLocal());
  const [actionRoom, setActionRoom] = useState(null);
  const [statusForm, setStatusForm] = useState({ status: "", nama_tamu: "", catatan: "" });
  const [hkPetugas, setHkPetugas] = useState("");

  // Quick Book — klik kamar kosong: pilih Day Use/Menginap + harga custom, langsung tercatat.
  // Bisa >1 kamar sekaligus (mis. rombongan walk-in) lewat mode "Pilih Banyak Kamar" —
  // quickBookRooms selalu array (1 kamar = alur lama, >1 = grup, tarif sama per kamar).
  const [quickBookRooms, setQuickBookRooms] = useState([]); // kamar yang sedang di-quick-book
  const [quickForm, setQuickForm] = useState(emptyQuickForm());
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);

  const [slotWarnings, setSlotWarnings] = useState([]); // [{room_nomor, alasan, rekomendasi_selesai}]

  const openQuickBook = (rooms) => { setQuickForm(emptyQuickForm(rooms[0]?.tarif)); setQuickBookRooms(rooms); setSlotWarnings([]); };
  const toggleRoomSelect = (room) => {
    setSelectedIds((ids) => ids.includes(room.id) ? ids.filter((id) => id !== room.id) : [...ids, room.id]);
  };
  const cancelMultiSelect = () => { setMultiSelectMode(false); setSelectedIds([]); };

  const quickEst = useMemo(() => {
    const harga = Number(quickForm.harga) || 0;
    if (quickForm.tipe === "menginap") {
      const nights = Math.max(1, Number(quickForm.malam) || 1);
      const subtotal = harga * nights;
      const svc = Math.round(subtotal * 0.03);
      return { subtotal, service_fee: svc, total: subtotal + svc, nights };
    }
    const svc = Math.round(harga * 0.03);
    return { subtotal: harga, service_fee: svc, total: harga + svc, nights: 1 };
  }, [quickForm]);

  // Scheduling Engine — cek advisory tiap kamar yang dipilih kalau tipe Day Use & jam
  // check-in terisi, supaya resepsionis tahu lebih dulu kalau kamar ini ada tamu menginap
  // yang akan check-in tidak lama lagi (murni info, tidak pernah memblokir submit — PRD
  // Rule 5: keputusan akhir tetap di resepsionis).
  useEffect(() => {
    if (quickForm.tipe !== "day_use" || !quickForm.jam_checkin || quickBookRooms.length === 0) {
      setSlotWarnings([]);
      return;
    }
    let batal = false;
    const jamIso = new Date(quickForm.jam_checkin).toISOString();
    Promise.all(quickBookRooms.map((r) =>
      api.get("/scheduling/rekomendasi-dayuse", { params: { room_id: r.id, jam_mulai: jamIso } })
        .then(({ data }) => (data.dipersingkat ? { room_nomor: r.nomor, alasan: data.alasan } : null))
        .catch(() => null)
    )).then((hasil) => { if (!batal) setSlotWarnings(hasil.filter(Boolean)); });
    return () => { batal = true; };
  }, [quickForm.tipe, quickForm.jam_checkin, quickBookRooms]);

  const submitQuickBook = async () => {
    if (!quickBookRooms.length) return;
    if (!quickForm.nama_tamu.trim()) { toast.error("Nama tamu wajib diisi"); return; }
    const harga = Number(quickForm.harga) || 0;
    if (harga <= 0) { toast.error("Harga harus lebih dari 0"); return; }
    const roomIds = quickBookRooms.map((r) => r.id);
    const isGroup = roomIds.length > 1;
    try {
      if (quickForm.tipe === "day_use") {
        const jamIso = quickForm.jam_checkin ? new Date(quickForm.jam_checkin).toISOString() : undefined;
        const { data } = await api.post("/checkins", {
          room_ids: roomIds, nama_tamu: quickForm.nama_tamu, no_hp: quickForm.no_hp,
          no_identitas: quickForm.no_identitas, kendaraan: quickForm.kendaraan,
          jumlah_tamu: Number(quickForm.jumlah_tamu) || 1, catatan: quickForm.catatan,
          jam_checkin: jamIso, tarif_override: harga,
        });
        toast.success(isGroup ? `Check-in berhasil untuk ${data.checkins.length} kamar` : `Check-in berhasil • ${data.trx_no}`);
      } else {
        const nights = Math.max(1, Number(quickForm.malam) || 1);
        const start = new Date();
        const end = new Date(start);
        end.setDate(end.getDate() + nights);
        const { data } = await api.post("/bookings", {
          room_ids: roomIds, tipe: "menginap", nama_tamu: quickForm.nama_tamu, no_hp: quickForm.no_hp,
          no_identitas: quickForm.no_identitas, kendaraan: quickForm.kendaraan,
          jumlah_tamu: Number(quickForm.jumlah_tamu) || 1, catatan: quickForm.catatan,
          jam_mulai: start.toISOString(), jam_selesai: end.toISOString(), tarif_override: harga,
        });
        const bks = isGroup ? data.bookings : [data];
        await Promise.all(bks.map((bk) => api.put(`/rooms/${bk.room_id}/status`, {
          status: "menginap", nama_tamu: quickForm.nama_tamu, catatan: quickForm.catatan,
        })));
        toast.success(isGroup ? `Booking menginap dibuat untuk ${bks.length} kamar, semua ditandai terisi` : "Booking menginap dibuat, kamar ditandai terisi");
      }
      setQuickBookRooms([]); cancelMultiSelect(); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const load = async () => {
    try {
      const [s, r, c, b, w, br, kd] = await Promise.all([
        api.get("/reports/summary"),
        api.get("/rooms"),
        api.get("/checkins", { params: { status: "aktif" } }),
        api.get("/bookings"),
        api.get("/reports/booking-widgets"),
        api.get("/booking-requests", { params: { status: "waiting_approval" } }),
        api.get("/reports/kedatangan-harian"),
      ]);
      // tampilkan semua booking yang menempati kamar: aktif, booking_pending, booking_paid
      // sync_status waiting_reddoorz_* (Tahap 2 Modul Reservasi) — booking Menginap dari
      // Booking Request yang belum diinput/disinkron manual ke PMS RedDoorz TETAP memblokir
      // slotnya di backend (check_room_available tidak berubah), tapi belum ditampilkan
      // sebagai tamu terkonfirmasi di grid Dashboard sampai email RedDoorz cocok.
      const occupying = b.data.filter(x => ["aktif", "booking_pending", "booking_paid"].includes(x.status)
        && !["waiting_reddoorz_input", "waiting_reddoorz_sync"].includes(x.sync_status));
      setSummary(s.data); setRooms(r.data); setActive(c.data); setBookings(occupying); setWidgets(w.data);
      setBookingRequests(br.data);
      setKedatanganHarian(kd.data);
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  // notify overdue (>=5h since checkin) — simple banner
  const nearDue = active.filter(c => (Date.now() - new Date(c.jam_checkin).getTime()) / 3600000 >= 5);
  const overtime = active.filter(c => (Date.now() - new Date(c.jam_checkin).getTime()) / 3600000 >= 6);

  // Filter bookings: ribbon hanya muncul jika filterDate ada di rentang [checkin_date, checkout_date)
  // — hari CHECK-OUT TIDAK dihitung menempati (tamu sudah checkout), KECUALI day-use yang
  // checkin/checkout di hari yang sama (tetap occupy hari itu). Bug ditemukan 2026-07-12: versi
  // lama pakai overlap TIMESTAMP mentah (start <= dayEnd && end >= dayStart), yang membuat hari
  // check-out booking menginap selalu ikut tampil sebagai "booked" di grid kamar — sama seperti
  // bug yang sudah diperbaiki di backend (_occupies_date di routes/ketersediaan.py).
  const bookingsOnDate = useMemo(() => {
    const toDateOnly = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const filterDateOnly = toDateOnly(new Date(`${filterDate}T00:00:00`));
    return bookings.filter(b => {
      const start = toDateOnly(new Date(b.jam_mulai));
      let end = toDateOnly(new Date(b.jam_selesai));
      if (end.getTime() === start.getTime()) end = new Date(start.getTime() + 24 * 3600 * 1000);
      return start <= filterDateOnly && filterDateOnly < end;
    });
  }, [bookings, filterDate]);

  const isToday = filterDate === todayLocal();
  // BookingDetail dialog state (saat klik room yang punya booking di tanggal filter)
  const [bookingDetail, setBookingDetail] = useState(null);
  const [rescheduleMode, setRescheduleMode] = useState(false);
  const [rescheduleForm, setRescheduleForm] = useState({ jam_mulai: "", jam_selesai: "" });
  // MoveRoom dialog state
  const [moveDialog, setMoveDialog] = useState(null); // { fromRoom }
  const [moveTargetId, setMoveTargetId] = useState("");
  const [moveAlasan, setMoveAlasan] = useState("");
  // Check-in dialog state — minta no_hp tamu sebelum check-in bisa dilakukan
  const [checkinDialog, setCheckinDialog] = useState(null); // { booking, no_hp }
  // Collect sisa pelunasan dialog state
  const [collectDialog, setCollectDialog] = useState(null); // { booking, sisa, nominal, metode }

  const handleRoomClick = (room, upcomingBk) => {
    // Jika tanggal yang dilihat punya booking di room ini → buka detail booking
    if (upcomingBk) {
      setBookingDetail(upcomingBk);
      setRescheduleMode(false);
      const toLocal = (iso) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
      setRescheduleForm({ jam_mulai: toLocal(upcomingBk.jam_mulai), jam_selesai: toLocal(upcomingBk.jam_selesai) });
      return;
    }
    // Hanya hari ini yang boleh trigger flow check-in/checkout/action
    if (!isToday) {
      toast.info("Tanggal ini tidak ada booking. Untuk transaksi gunakan tanggal hari ini.");
      return;
    }
    if (room.status === "day_use") {
      const ci = active.find((x) => x.room_id === room.id);
      if (ci) {
        // buka action dialog untuk pilih: checkout atau move room
        setActionRoom({ ...room, _checkin: ci });
        setStatusForm({ status: room.status, nama_tamu: ci.nama_tamu, catatan: ci.catatan || "" });
      } else { toast.error("Data check-in tidak ditemukan"); }
      return;
    }
    if (room.status === "kosong") {
      if (multiSelectMode) { toggleRoomSelect(room); return; }
      openQuickBook([room]);
      return;
    }
    setActionRoom(room);
    setStatusForm({ status: room.status, nama_tamu: room.info?.nama_tamu || "", catatan: room.info?.catatan || "" });
    setHkPetugas(user?.nama || "");
  };

  const cancelBookingDetail = async () => {
    if (!bookingDetail) return;
    const totalNum = Number(bookingDetail.total || 0);
    const fee = Math.round(totalNum * 0.10);
    const paid = Number(bookingDetail.amount_due || 0);
    const refund = bookingDetail.status === "booking_paid" ? Math.max(0, paid - fee) : 0;
    const msg = bookingDetail.status === "booking_paid"
      ? `Batalkan booking ${bookingDetail.kode}? Fee 10% (${fmtRp(fee)}) dipotong dari pembayaran. Refund: ${fmtRp(refund)}.`
      : `Batalkan booking ${bookingDetail.kode}? Fee 10% (${fmtRp(fee)}) akan dicatat sebagai biaya pembatalan.`;
    if (!window.confirm(msg)) return;
    try {
      const { data } = await api.post(`/bookings/${bookingDetail.id}/cancel-with-fee`, { alasan: "" });
      const tmsg = data.refund_amount > 0
        ? `Booking dibatalkan. Refund ${fmtRp(data.refund_amount)} (fee ${fmtRp(data.fee)})`
        : `Booking dibatalkan. Fee ${fmtRp(data.fee)} tercatat.`;
      toast.success(tmsg);
      setBookingDetail(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  // Collect sisa pelunasan (DP 50% yang belum lunas) — buka dialog form
  const openCollectDialog = () => {
    if (!bookingDetail) return;
    const total = Number(bookingDetail.total || 0);
    const paid = Number(bookingDetail.amount_due || 0);
    const sisa = Math.max(0, total - paid);
    if (sisa <= 0) { toast.info("Booking sudah lunas"); return; }
    setCollectDialog({ booking: bookingDetail, sisa, nominal: String(sisa), metode: "cash" });
  };

  const submitCollectBalance = async () => {
    if (!collectDialog) return;
    const nominal = Number(collectDialog.nominal);
    if (!nominal || nominal <= 0) { toast.error("Nominal harus > 0"); return; }
    try {
      const { data } = await api.post(`/bookings/${collectDialog.booking.id}/collect-balance`, { nominal, metode: collectDialog.metode });
      const m = collectDialog.metode.toUpperCase();
      const msg = data.remaining > 0
        ? `Diterima Rp ${data.amount_collected.toLocaleString("id-ID")} (${m}). Sisa Rp ${data.remaining.toLocaleString("id-ID")}.`
        : `Pelunasan diterima Rp ${data.amount_collected.toLocaleString("id-ID")} (${m}). Booking LUNAS.`;
      toast.success(msg);
      setCollectDialog(null); setBookingDetail(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  // Check-in tamu dari booking (booking_paid/aktif → checked_in) — buka dialog minta no_hp dulu
  const openCheckinDialog = () => {
    if (!bookingDetail) return;
    setCheckinDialog({ booking: bookingDetail, no_hp: bookingDetail.no_hp || "" });
  };

  const submitCheckin = async () => {
    if (!checkinDialog) return;
    const b = checkinDialog.booking;
    const no_hp = (checkinDialog.no_hp || "").trim();
    if (!no_hp) { toast.error("Nomor telepon tamu wajib diisi sebelum check-in"); return; }
    const total = Number(b.total || 0);
    const paid = Number(b.amount_due || 0);
    const sisa = Math.max(0, total - paid);
    const warn = sisa > 0 ? `\nPERHATIAN: Sisa pembayaran Rp ${sisa.toLocaleString("id-ID")} belum di-collect. Lanjutkan check-in?` : "";
    if (!window.confirm(`Check-in tamu ${b.nama_tamu} (kamar ${b.room_nomor})?${warn}`)) return;
    try {
      const { data } = await api.post(`/bookings/${b.id}/checkin`, { no_hp });
      const trxLabel = data.trx_no ? `Check-in OK. TRX ${data.trx_no}` : `Check-in OK, kamar ditandai terisi`;
      toast.success(`${trxLabel}${data.remaining > 0 ? ` (sisa Rp ${data.remaining.toLocaleString("id-ID")})` : ""}`);
      setCheckinDialog(null); setBookingDetail(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  // Konfirmasi pembayaran manual (transfer rekening) — staff verify booking_pending → booking_paid
  const markPaidManual = async () => {
    if (!bookingDetail) return;
    const total = Number(bookingDetail.total || 0);
    const nominalStr = window.prompt(`Konfirmasi pembayaran manual untuk ${bookingDetail.kode}.\nNominal yang diterima (default: ${fmtRp(total)}):`, total);
    if (nominalStr === null) return;
    const nominal = Number(nominalStr) || total;
    try {
      const { data } = await api.post(`/bookings/${bookingDetail.id}/mark-paid-manual`, { nominal, metode: "transfer_manual" });
      toast.success(`Booking ${data.booking_kode} dikonfirmasi PAID (${fmtRp(data.amount)})`);
      setBookingDetail(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  // Mark No-Show (tamu tidak datang): hanya untuk booking_paid, DP/full payment tidak direfund
  const markNoShow = async () => {
    if (!bookingDetail) return;
    const paid = Number(bookingDetail.amount_due || 0);
    if (!window.confirm(`Tandai booking ${bookingDetail.kode} sebagai NO-SHOW?\nPembayaran ${fmtRp(paid)} TIDAK direfund dan tetap masuk pembukuan.`)) return;
    try {
      const { data } = await api.post(`/bookings/${bookingDetail.id}/no-show`, { alasan: "" });
      toast.success(`No-show ditandai. ${fmtRp(data.amount_retained)} masuk pembukuan.`);
      setBookingDetail(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  // Quick cancel langsung dari kartu kamar (tombol X) - juga apply 10% fee universal
  const quickCancelBooking = async (bk) => {
    if (!bk) return;
    const totalNum = Number(bk.total || 0);
    const fee = Math.round(totalNum * 0.10);
    if (!window.confirm(`Batalkan booking ${bk.kode} (${bk.nama_tamu}, kamar ${bk.room_nomor})? Fee pembatalan 10% (${fmtRp(fee)}) akan dicatat.`)) return;
    try {
      const { data } = await api.post(`/bookings/${bk.id}/cancel-with-fee`, { alasan: "" });
      const tmsg = data.refund_amount > 0
        ? `Booking dibatalkan. Refund ${fmtRp(data.refund_amount)} (fee ${fmtRp(data.fee)})`
        : `Booking ${bk.kode} dibatalkan. Fee ${fmtRp(data.fee)} tercatat.`;
      toast.success(tmsg);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const submitReschedule = async () => {
    if (!bookingDetail) return;
    try {
      const payload = {
        tipe: bookingDetail.tipe, room_id: bookingDetail.room_id,
        nama_tamu: bookingDetail.nama_tamu, no_hp: bookingDetail.no_hp || "",
        no_identitas: bookingDetail.no_identitas || "", kendaraan: bookingDetail.kendaraan || "",
        jumlah_tamu: bookingDetail.jumlah_tamu || 1,
        jam_mulai: new Date(rescheduleForm.jam_mulai).toISOString(),
        jam_selesai: new Date(rescheduleForm.jam_selesai).toISOString(),
        catatan: bookingDetail.catatan || "",
      };
      await api.put(`/bookings/${bookingDetail.id}`, payload);
      toast.success("Booking diperbarui");
      setBookingDetail(null); setRescheduleMode(false); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const submitMoveRoom = async () => {
    if (!moveDialog || !moveTargetId) { toast.error("Pilih kamar tujuan"); return; }
    try {
      const res = await api.post(`/rooms/${moveDialog.fromRoom.id}/move`, { new_room_id: moveTargetId, alasan: moveAlasan });
      toast.success(`Tamu pindah: Kamar ${res.data.from} → Kamar ${res.data.to}`);
      setMoveDialog(null); setMoveTargetId(""); setMoveAlasan("");
      setActionRoom(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const changeStatus = async (newStatus) => {
    try {
      await api.put(`/rooms/${actionRoom.id}/status`, {
        status: newStatus,
        nama_tamu: statusForm.nama_tamu,
        catatan: statusForm.catatan,
      });
      toast.success("Status kamar diubah");
      setActionRoom(null);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal mengubah status"); }
  };

  const housekeepingDone = async () => {
    if (!hkPetugas.trim()) { toast.error("Nama petugas wajib diisi"); return; }
    try {
      await api.post(`/rooms/${actionRoom.id}/housekeeping-done`, { petugas: hkPetugas.trim() });
      toast.success("Kamar selesai dibersihkan");
      setActionRoom(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Dashboard</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Selamat datang, {user?.nama?.split(" ")[0]} 👋</h1>
          <p className="text-slate-500 mt-1">Ringkasan operasional Pelangi Homestay hari ini.</p>
        </div>
      </div>

      {/* Alerts */}
      <ActionRequiredRedDoorz />
      <PembatalanAlert />
      {bookingRequests.length > 0 && (
        <div data-testid="booking-request-alert" className="rounded-xl bg-blue-50 border border-blue-200 p-4">
          <div className="flex items-start gap-3 mb-3">
            <Inbox className="w-5 h-5 text-blue-600 mt-0.5 shrink-0" />
            <div className="text-sm">
              <div className="font-semibold text-blue-900">{bookingRequests.length} Booking Request menunggu persetujuan</div>
              <div className="text-blue-700">Permintaan dari AI WhatsApp — tinjau ketersediaan lalu terima/tolak.</div>
            </div>
          </div>
          <div className="space-y-2">
            {bookingRequests.map((it) => (
              <div key={it.id} data-testid={`br-alert-${it.id}`} className="flex items-center justify-between gap-3 bg-white border border-blue-100 rounded-lg p-2.5 text-sm">
                <div>
                  <div className="font-semibold">{it.nama_tamu}</div>
                  <div className="text-xs text-slate-500">
                    {it.tipe === "menginap" ? "Menginap" : "Day Use"} · {it.room_tipe || "(tipe bebas)"} x{it.jumlah_kamar} · check-in {it.tanggal_checkin}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => setApproveReqTarget(it)}>
                    <Check className="w-3.5 h-3.5 mr-1" /> Terima
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setRejectReqTarget(it)}>
                    <X className="w-3.5 h-3.5 mr-1" /> Tolak
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {overtime.length > 0 && (
        <div data-testid="overtime-alert" className="rounded-xl bg-red-50 border border-red-200 p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-red-800">{overtime.length} kamar overtime</div>
            <div className="text-red-700">
              {overtime.map(c => `Kamar ${c.room_nomor} (${c.nama_tamu})`).join(", ")}
            </div>
          </div>
        </div>
      )}
      {nearDue.length > overtime.length && (
        <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 flex items-start gap-3">
          <Hourglass className="w-5 h-5 text-amber-600 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-amber-800">{nearDue.length - overtime.length} tamu mendekati batas 6 jam</div>
          </div>
        </div>
      )}

      {/* Status cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4">
        {STAT_CARDS.map((s) => (
          <Card key={s.key} className="border-slate-200">
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500">{s.label}</div>
                  <div className="text-3xl font-extrabold mt-1" style={{ color: s.color }}>
                    {summary?.rooms?.[s.key] ?? "—"}
                  </div>
                </div>
                <div className="w-9 h-9 rounded-lg grid place-items-center" style={{ background: s.color + "1A", color: s.color }}>
                  <s.icon className="w-5 h-5" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
        <RevCard icon={Percent} label="Okupansi Hari Ini" value={`${summary?.okupansi_persen ?? 0}%`} hint={`${(summary?.total_rooms || 0) - (summary?.rooms?.kosong || 0)} dari ${summary?.total_rooms ?? 0} kamar terisi`} />
        <RevCard icon={UsersIcon} label="Tamu Hari Ini" value={summary?.tamu_hari_ini ?? "—"} hint={`${summary?.checkout_hari_ini ?? 0} sudah check-out`} />
        <RevCard icon={Wallet} label="Pendapatan Hari Ini" value={fmtRp(summary?.pendapatan_hari_ini || 0)} hint={`Kamar ${fmtRp(summary?.pendapatan_kamar_hari_ini || 0)} • Kasir ${fmtRp(summary?.pendapatan_kasir_hari_ini || 0)}`} />
        <RevCard icon={CalendarRange} label="Pendapatan Bulan Ini" value={fmtRp(summary?.pendapatan_bulan_ini || 0)} hint="Total semua transaksi" />
        <RevCard icon={Wallet} label="Laba Bersih Bulan" value={fmtRp(summary?.laba_bersih_bulan_ini || 0)} hint={`Pengeluaran ${fmtRp(summary?.pengeluaran_bulan_ini || 0)}`} />
      </div>

      {/* Grafik Kedatangan Tamu 30 Hari (2026-07-21, permintaan user) */}
      <Card className="border-slate-200">
        <CardContent className="p-4 sm:p-6">
          <h2 className="text-lg font-bold mb-1">Kedatangan Tamu (30 Hari Terakhir)</h2>
          <p className="text-xs text-slate-500 mb-4">Jumlah booking per tanggal check-in, semua tipe & channel (kecuali yang dibatalkan)</p>
          <div className="h-64 w-full">
            <ResponsiveContainer>
              <BarChart data={kedatanganHarian} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="tanggal" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} interval={2} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip labelFormatter={(d) => fmtDate(d)} formatter={(v) => [v, "Kedatangan"]} />
                <Bar dataKey="jumlah" fill="#2563EB" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Online Booking Widgets (Fase D) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        <MiniWidget label="Booking Hari Ini" value={widgets?.booking_hari_ini ?? "—"} color="#2563EB" testid="w-today" />
        <MiniWidget label="Pending" value={widgets?.booking_pending ?? "—"} color="#F59E0B" testid="w-pending" />
        <MiniWidget label="Paid" value={widgets?.booking_paid ?? "—"} color="#10B981" testid="w-paid" />
        <MiniWidget label="Pendapatan Online" value={fmtRp(widgets?.pendapatan_online_bulan || 0)} color="#7C3AED" testid="w-rev-online" wide />
        <MiniWidget label="Total Transaksi Bayar" value={`${widgets?.payment_total_count || 0} trx`} hint={fmtRp(widgets?.payment_total_sum || 0)} color="#0EA5E9" testid="w-mt-total" wide />
        <MiniWidget label="Online (Bulan)" value={widgets?.booking_online_bulan ?? "—"} color="#06B6D4" testid="w-online-month" />
        <MiniWidget label="Walk-In (Bulan)" value={widgets?.booking_walkin_bulan ?? "—"} color="#64748B" testid="w-walkin-month" />
      </div>

      {/* Room grid */}
      <Card className="border-slate-200">
        <CardContent className="p-4 sm:p-6">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <h2 className="text-xl font-bold">Daftar Kamar</h2>
            <div className="flex items-center gap-2 flex-wrap">
              <Calendar className="w-4 h-4 text-slate-500" />
              <Label htmlFor="filter-date" className="text-xs text-slate-600">Booking pada:</Label>
              <Input
                id="filter-date"
                data-testid="dashboard-filter-date"
                type="date"
                value={filterDate}
                onChange={(e) => setFilterDate(e.target.value || todayLocal())}
                className="h-9 w-[160px] text-sm"
              />
              {!isToday && (
                <Button data-testid="dashboard-filter-today" size="sm" variant="outline" onClick={() => setFilterDate(todayLocal())} className="h-9">
                  Hari ini
                </Button>
              )}
              {isToday && (
                <Button
                  data-testid="multi-select-toggle"
                  size="sm" variant={multiSelectMode ? "default" : "outline"}
                  className={multiSelectMode ? "bg-blue-700 hover:bg-blue-800 h-9" : "h-9"}
                  onClick={() => (multiSelectMode ? cancelMultiSelect() : setMultiSelectMode(true))}
                >
                  {multiSelectMode ? "Batal Pilih Banyak" : "Pilih Banyak Kamar"}
                </Button>
              )}
            </div>
          </div>
          {multiSelectMode && (
            <div data-testid="multi-select-bar" className="mb-3 rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 text-xs sm:text-sm flex items-center justify-between flex-wrap gap-2">
              <span className="text-blue-800">Klik kamar kosong untuk pilih rombongan — <b>{selectedIds.length} kamar dipilih</b></span>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={cancelMultiSelect}>Batal</Button>
                <Button
                  size="sm" data-testid="multi-select-lanjut"
                  disabled={selectedIds.length === 0}
                  className="bg-blue-700 hover:bg-blue-800"
                  onClick={() => openQuickBook(rooms.filter((r) => selectedIds.includes(r.id)))}
                >
                  Lanjut ({selectedIds.length})
                </Button>
              </div>
            </div>
          )}
          {!isToday && (
            <div data-testid="filter-date-banner" className="mb-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
              Menampilkan booking untuk <b>{new Date(`${filterDate}T00:00:00`).toLocaleDateString("id-ID", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</b>. Hanya kamar yang punya booking di tanggal ini yang ditandai; status real-time (Day Use/Menginap/dll) hanya berlaku untuk hari ini.
            </div>
          )}
          <div className="flex flex-wrap gap-3 text-xs mb-3">
            {STAT_CARDS.map((s) => (
              <div key={s.key} className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-sm" style={{ background: s.color }} />
                <span className="text-slate-600">{s.label}</span>
              </div>
            ))}
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ background: "#92400E" }} />
              <span className="text-slate-600">Booked Day Use</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ background: "#3B82F6" }} />
              <span className="text-slate-600">Booked Menginap ({bookingsOnDate.length})</span>
            </div>
          </div>
          <div data-testid="room-grid" className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
            {rooms.map((r) => {
              // Saat tanggal yang dilihat BUKAN hari ini, status realtime kamar (day_use/menginap/dll) tidak relevan → anggap kosong.
              const effStatus = isToday ? r.status : "kosong";
              const upcomingBk = effStatus === "kosong" ? bookingsOnDate
                .filter(b => b.room_id === r.id)
                .sort((a, c) => a.jam_mulai.localeCompare(c.jam_mulai))[0] : null;
              const bg = upcomingBk ? (upcomingBk.tipe === "menginap" ? "#3B82F6" : "#92400E") : statusColor(effStatus);
              const bkLabel = upcomingBk
                ? new Date(upcomingBk.jam_mulai).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
                : null;
              const selectable = multiSelectMode && effStatus === "kosong" && !upcomingBk;
              const isSelected = selectable && selectedIds.includes(r.id);
              return (
              <div
                key={r.id}
                data-testid={`room-${r.nomor}`}
                onClick={() => handleRoomClick(r, upcomingBk)}
                role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") handleRoomClick(r, upcomingBk); }}
                className={`room-card relative rounded-xl text-white p-4 aspect-square flex flex-col justify-between text-left overflow-hidden cursor-pointer ${isSelected ? "ring-4 ring-blue-500 ring-offset-2" : ""} ${selectable && !isSelected ? "ring-2 ring-dashed ring-white/60" : ""}`}
                style={{ background: bg }}
              >
                {isSelected && (
                  <div className="absolute top-1 right-1 w-5 h-5 rounded-full bg-blue-600 border-2 border-white grid place-items-center text-[10px] font-bold z-10">✓</div>
                )}
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-semibold tracking-wider opacity-90">{r.tipe}</span>
                  <span className="text-[10px] bg-white/25 rounded px-1.5 py-0.5">{upcomingBk ? "Booked" : statusLabel(effStatus)}</span>
                </div>
                <div className="text-3xl sm:text-4xl font-extrabold">{r.nomor}</div>
                <div className="text-[11px] opacity-90 truncate">
                  {upcomingBk ? `${upcomingBk.nama_tamu}` : (effStatus === "kosong" ? fmtRp(r.tarif) : (r.info?.nama_tamu || "—"))}
                </div>
                {bkLabel && (
                  <div className="absolute top-0 right-0 bg-amber-900/80 text-[9px] font-bold px-1.5 py-0.5 rounded-bl-md">
                    {bkLabel}
                  </div>
                )}
                {upcomingBk && (
                  <button
                    type="button"
                    data-testid={`room-cancel-${r.nomor}`}
                    onClick={(e) => { e.stopPropagation(); quickCancelBooking(upcomingBk); }}
                    title="Batalkan booking ini"
                    className="absolute top-1 left-1 w-6 h-6 rounded-full bg-white/95 text-red-600 hover:bg-red-600 hover:text-white grid place-items-center transition-colors z-10"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Quick Book Dialog — klik kamar kosong: pilih Day Use/Menginap + harga custom. quickBookRooms
          bisa >1 kamar (rombongan) — harga/tipe yang sama berlaku untuk tiap kamar dalam grup. */}
      <Dialog open={quickBookRooms.length > 0} onOpenChange={(o) => !o && setQuickBookRooms([])}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {quickBookRooms.length > 1
                ? `${quickBookRooms.length} Kamar: ${quickBookRooms.map((r) => r.nomor).join(", ")}`
                : `Kamar ${quickBookRooms[0]?.nomor} — ${quickBookRooms[0]?.tipe}`}
            </DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3 max-h-[70vh] overflow-y-auto">
            <div className="col-span-2">
              <Label>Tipe</Label>
              <div className="grid grid-cols-2 gap-2 mt-1.5">
                <Button type="button" variant={quickForm.tipe === "day_use" ? "default" : "outline"} className={quickForm.tipe === "day_use" ? "bg-orange-500 hover:bg-orange-600" : ""} onClick={() => setQuickForm(f => ({ ...f, tipe: "day_use", harga: quickBookRooms[0]?.tarif ?? f.harga }))} data-testid="q-tipe-dayuse">Day Use</Button>
                <Button type="button" variant={quickForm.tipe === "menginap" ? "default" : "outline"} className={quickForm.tipe === "menginap" ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setQuickForm(f => ({ ...f, tipe: "menginap", harga: quickBookRooms[0]?.tarif_menginap ?? f.harga }))} data-testid="q-tipe-menginap">Menginap</Button>
              </div>
            </div>
            <div className="col-span-2"><Label>Nama Tamu *</Label><Input data-testid="q-nama" value={quickForm.nama_tamu} onChange={(e) => setQuickForm(f => ({ ...f, nama_tamu: e.target.value }))} autoFocus /></div>
            <div><Label>HP</Label><Input data-testid="q-hp" value={quickForm.no_hp} onChange={(e) => setQuickForm(f => ({ ...f, no_hp: e.target.value }))} /></div>
            <div><Label>KTP</Label><Input value={quickForm.no_identitas} onChange={(e) => setQuickForm(f => ({ ...f, no_identitas: e.target.value }))} /></div>
            <div><Label>Kendaraan</Label><Input value={quickForm.kendaraan} onChange={(e) => setQuickForm(f => ({ ...f, kendaraan: e.target.value }))} /></div>
            <div><Label>Jumlah Tamu</Label><Input type="number" min="1" value={quickForm.jumlah_tamu} onChange={(e) => setQuickForm(f => ({ ...f, jumlah_tamu: e.target.value }))} /></div>
            {quickForm.tipe === "day_use" ? (
              <div className="col-span-2">
                <Label>Jam Check-In</Label>
                <Input data-testid="q-jam" type="datetime-local" value={quickForm.jam_checkin} onChange={(e) => setQuickForm(f => ({ ...f, jam_checkin: e.target.value }))} />
                {slotWarnings.map((w) => (
                  <div key={w.room_nomor} data-testid={`q-slot-warning-${w.room_nomor}`} className="mt-2 flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md p-2.5">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <span><b>Kamar {w.room_nomor}:</b> {w.alasan}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="col-span-2"><Label>Jumlah Malam</Label><Input data-testid="q-malam" type="number" min="1" value={quickForm.malam} onChange={(e) => setQuickForm(f => ({ ...f, malam: e.target.value }))} /></div>
            )}
            <div className="col-span-2">
              <Label>{quickForm.tipe === "day_use" ? "Harga (per 6 jam)" : "Harga per Malam"}{quickBookRooms.length > 1 ? " — per kamar" : ""}</Label>
              <Input data-testid="q-harga" type="number" min="0" value={quickForm.harga} onChange={(e) => setQuickForm(f => ({ ...f, harga: e.target.value }))} />
            </div>
            <div className="col-span-2"><Label>Catatan</Label><Textarea value={quickForm.catatan} onChange={(e) => setQuickForm(f => ({ ...f, catatan: e.target.value }))} rows={2} /></div>
            <div data-testid="q-est-summary" className="col-span-2 rounded-lg bg-blue-50 border border-blue-200 p-3 text-sm space-y-1">
              <div className="flex justify-between"><span className="text-slate-600">Subtotal{quickForm.tipe === "menginap" ? ` (${quickEst.nights} malam)` : ""}{quickBookRooms.length > 1 ? " / kamar" : ""}</span><b>{fmtRp(quickEst.subtotal)}</b></div>
              <div className="flex justify-between"><span className="text-slate-600">Service Fee (3%){quickBookRooms.length > 1 ? " / kamar" : ""}</span><b>{fmtRp(quickEst.service_fee)}</b></div>
              <div className="flex justify-between text-base pt-1 border-t border-blue-200 mt-1"><span className="font-bold">Estimasi Total{quickBookRooms.length > 1 ? " / kamar" : ""}</span><b className="text-blue-700">{fmtRp(quickEst.total)}</b></div>
              {quickBookRooms.length > 1 && (
                <div className="flex justify-between text-base pt-1 border-t border-blue-300 mt-1"><span className="font-bold">Total {quickBookRooms.length} Kamar</span><b className="text-blue-800">{fmtRp(quickEst.total * quickBookRooms.length)}</b></div>
              )}
              {quickForm.tipe === "day_use" && <p className="text-[10px] text-slate-500">*Belum termasuk overtime setelah 6 jam.</p>}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setQuickBookRooms([])}>Batal</Button>
            <Button data-testid="q-submit" onClick={submitQuickBook} className="bg-blue-700 hover:bg-blue-800">
              {quickForm.tipe === "day_use" ? "Konfirmasi Check-In" : "Buat Booking Menginap"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Action Dialog */}
      <Dialog open={!!actionRoom} onOpenChange={(o) => !o && setActionRoom(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Kamar {actionRoom?.nomor} — {actionRoom?.tipe}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-sm" style={{ background: statusColor(actionRoom?.status) }} />
              <span className="font-medium">{statusLabel(actionRoom?.status)}</span>
            </div>
            {actionRoom?.status === "day_use" && actionRoom?._checkin && (
              <>
                <div><span className="text-slate-500">Tamu:</span> <b>{actionRoom._checkin.nama_tamu}</b></div>
                <div><span className="text-slate-500">HP:</span> {actionRoom._checkin.no_hp || "-"}</div>
                <div><span className="text-slate-500">Check-in:</span> {new Date(actionRoom._checkin.jam_checkin).toLocaleString("id-ID")}</div>
                <div><span className="text-slate-500">Trx:</span> {actionRoom._checkin.trx_no}</div>
              </>
            )}
            {actionRoom?.status === "menginap" && (
              <>
                <div><span className="text-slate-500">Tamu:</span> {actionRoom?.info?.nama_tamu || "-"}</div>
                <div><span className="text-slate-500">Catatan:</span> {actionRoom?.info?.catatan || "-"}</div>
              </>
            )}
            {actionRoom?.status === "perlu_dibersihkan" && (
              <div>
                <p className="text-slate-600 mb-2">Isi nama petugas lalu tekan tombol di bawah jika kamar sudah selesai dibersihkan.</p>
                <Label>Nama Petugas</Label>
                <Input data-testid="hk-petugas" value={hkPetugas} onChange={(e) => setHkPetugas(e.target.value)} placeholder="Nama staff yang membersihkan" />
              </div>
            )}
            {(actionRoom?.status === "menginap" || actionRoom?.status === "maintenance") && (
              <>
                <div>
                  <Label>Nama tamu (untuk menginap)</Label>
                  <Input data-testid="status-nama-tamu" value={statusForm.nama_tamu} onChange={(e) => setStatusForm(f => ({ ...f, nama_tamu: e.target.value }))} />
                </div>
                <div>
                  <Label>Catatan</Label>
                  <Textarea data-testid="status-catatan" value={statusForm.catatan} onChange={(e) => setStatusForm(f => ({ ...f, catatan: e.target.value }))} />
                </div>
              </>
            )}
          </div>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            {actionRoom?.status === "day_use" && actionRoom?._checkin && (
              <Button data-testid="lanjut-checkout" onClick={() => { const ci = actionRoom._checkin; setActionRoom(null); nav(`/checkout/${ci.id}`); }} className="bg-red-600 hover:bg-red-700">Lanjut Check-out</Button>
            )}
            {(actionRoom?.status === "day_use" || actionRoom?.status === "menginap") && (
              <Button data-testid="pindah-kamar" variant="outline" onClick={() => { setMoveDialog({ fromRoom: actionRoom }); setMoveTargetId(""); setMoveAlasan(""); }}>
                Pindah Kamar
              </Button>
            )}
            {actionRoom?.status === "perlu_dibersihkan" && (
              <Button data-testid="hk-done" onClick={housekeepingDone} className="bg-emerald-600 hover:bg-emerald-700">Selesai Dibersihkan</Button>
            )}
            {actionRoom?.status === "menginap" && (
              <Button data-testid="selesai-menginap" onClick={() => changeStatus("kosong")} className="bg-emerald-600 hover:bg-emerald-700">Selesai Menginap</Button>
            )}
            {actionRoom?.status === "maintenance" && (
              <Button data-testid="selesai-maintenance" onClick={() => changeStatus("kosong")} className="bg-emerald-600 hover:bg-emerald-700">Kembalikan ke Kosong</Button>
            )}
            {actionRoom?.status === "kosong" && (
              <>
                <Button data-testid="tandai-menginap" variant="outline" onClick={() => changeStatus("menginap")}>Tandai Menginap</Button>
                <Button data-testid="tandai-maintenance" variant="outline" onClick={() => changeStatus("maintenance")}>Tandai Maintenance</Button>
              </>
            )}
            <Button variant="ghost" onClick={() => setActionRoom(null)}>Tutup</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Booking Detail Dialog (saat klik room yang ada booking di tanggal filter) */}
      <Dialog open={!!bookingDetail} onOpenChange={(o) => { if (!o) { setBookingDetail(null); setRescheduleMode(false); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle data-testid="booking-detail-title">Booking {bookingDetail?.kode}</DialogTitle>
          </DialogHeader>
          {bookingDetail && !rescheduleMode && (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${bookingDetail.tipe === "menginap" ? "bg-blue-700 text-white" : "bg-orange-100 text-orange-800"}`}>
                  {bookingDetail.tipe === "menginap" ? "Menginap" : "Day Use"}
                </span>
                <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${
                  bookingDetail.status === "booking_paid" ? "bg-emerald-100 text-emerald-800" :
                  bookingDetail.status === "booking_pending" ? "bg-amber-100 text-amber-800" :
                  "bg-slate-100 text-slate-700"
                }`}>{bookingDetail.status}</span>
                {(() => { const sb = statusBayarOf(bookingDetail); return (
                  <span data-testid="booking-detail-status-bayar" className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${STATUS_BAYAR_BADGE_CLASS[sb.status_bayar]}`}>
                    {STATUS_BAYAR_LABEL[sb.status_bayar]}
                  </span>
                ); })()}
                {bookingDetail.source !== "walk_in" && (
                  <span className="text-[10px] uppercase font-bold px-2 py-1 rounded bg-violet-100 text-violet-800">
                    {{ online: "Online", ota: "OTA", whatsapp_request: "WhatsApp AI" }[bookingDetail.source] || bookingDetail.source}
                  </span>
                )}
                {bookingDetail.ota_harga_dikonfirmasi === false && (
                  <span className="text-[10px] uppercase font-bold px-2 py-1 rounded bg-amber-100 text-amber-800">Nominal Belum Dikonfirmasi</span>
                )}
              </div>
              <div><span className="text-slate-500">Tamu:</span> <b data-testid="booking-detail-nama">{bookingDetail.nama_tamu}</b></div>
              <div><span className="text-slate-500">Kamar:</span> {bookingDetail.room_nomor} ({bookingDetail.room_tipe})</div>
              {bookingDetail.no_hp && <div><span className="text-slate-500">HP:</span> {bookingDetail.no_hp}</div>}
              {bookingDetail.jumlah_tamu && <div><span className="text-slate-500">Jumlah Tamu:</span> {bookingDetail.jumlah_tamu}</div>}
              <div><span className="text-slate-500">Jam Mulai:</span> {new Date(bookingDetail.jam_mulai).toLocaleString("id-ID")}</div>
              <div><span className="text-slate-500">Jam Selesai:</span> {new Date(bookingDetail.jam_selesai).toLocaleString("id-ID")}</div>
              {(bookingDetail.total != null) && (() => {
                const sb = statusBayarOf(bookingDetail);
                return (
                  <div className="bg-slate-50 border border-slate-200 rounded p-2 text-xs space-y-1 mt-2" data-testid="booking-detail-status-pembayaran">
                    <div className="flex justify-between"><span className="text-slate-500">Subtotal</span><b>{fmtRp(bookingDetail.subtotal || 0)}</b></div>
                    <div className="flex justify-between"><span className="text-slate-500">Service Fee 3%</span><b>{fmtRp(bookingDetail.service_fee || 0)}</b></div>
                    <div className="flex justify-between border-t pt-1 mt-1"><span className="font-bold">Total Booking</span><b className="text-blue-700">{fmtRp(bookingDetail.total)}</b></div>
                    <div className="flex justify-between"><span className="text-slate-500">Status Pembayaran</span><b>{STATUS_BAYAR_LABEL[sb.status_bayar]}</b></div>
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
              {bookingDetail.catatan && <div className="italic text-slate-600">&ldquo;{bookingDetail.catatan}&rdquo;</div>}
              <div className="text-[10px] text-slate-400">Dibuat oleh {bookingDetail.created_by}</div>
            </div>
          )}
          {bookingDetail && rescheduleMode && (
            <div className="space-y-3 text-sm">
              <p className="text-slate-600 text-xs">Geser jam mulai dan jam selesai untuk reschedule booking.</p>
              <div>
                <Label>Jam Mulai</Label>
                <Input data-testid="resched-mulai" type="datetime-local" value={rescheduleForm.jam_mulai} onChange={(e) => setRescheduleForm(f => ({ ...f, jam_mulai: e.target.value }))} />
              </div>
              <div>
                <Label>Jam Selesai</Label>
                <Input data-testid="resched-selesai" type="datetime-local" value={rescheduleForm.jam_selesai} onChange={(e) => setRescheduleForm(f => ({ ...f, jam_selesai: e.target.value }))} />
              </div>
            </div>
          )}
          <DialogFooter className="flex-wrap gap-2">
            {!rescheduleMode && bookingDetail?.status === "aktif" && (
              <>
                <Button data-testid="bd-checkin-aktif" onClick={openCheckinDialog} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                  Check-in Tamu
                </Button>
                <Button data-testid="bd-reschedule" variant="outline" onClick={() => setRescheduleMode(true)}>Reschedule</Button>
                <Button data-testid="bd-cancel" variant="outline" onClick={cancelBookingDetail} className="text-red-600 border-red-300 hover:bg-red-50">Batalkan (Fee 10%)</Button>
              </>
            )}
            {!rescheduleMode && bookingDetail?.status === "booking_pending" && (
              <>
                <Button data-testid="bd-reschedule" variant="outline" onClick={() => setRescheduleMode(true)}>Reschedule</Button>
                <Button data-testid="bd-mark-paid-manual" variant="outline" onClick={markPaidManual} className="text-emerald-700 border-emerald-400 hover:bg-emerald-50">
                  Konfirmasi Pembayaran Manual
                </Button>
                <Button data-testid="bd-cancel-pending" variant="outline" onClick={cancelBookingDetail} className="text-red-600 border-red-300 hover:bg-red-50">Batalkan (Fee 10%)</Button>
              </>
            )}
            {!rescheduleMode && bookingDetail?.no_hp && (
              <a
                data-testid="bd-wa-confirm"
                href={bookingConfirmationWaLink(bookingDetail)}
                target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-2 px-3 h-9 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold"
              >
                <MessageCircle className="w-4 h-4" /> Kirim WhatsApp
              </a>
            )}
            {!rescheduleMode && bookingDetail?.status === "booking_paid" && (
              <>
                <Button data-testid="bd-checkin" onClick={openCheckinDialog} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                  Check-in Tamu
                </Button>
                {Number(bookingDetail.total || 0) - Number(bookingDetail.amount_due || 0) > 0 && (
                  <Button data-testid="bd-collect" variant="outline" onClick={openCollectDialog} className="text-blue-700 border-blue-400 hover:bg-blue-50">
                    Collect Sisa Rp {(Number(bookingDetail.total || 0) - Number(bookingDetail.amount_due || 0)).toLocaleString("id-ID")}
                  </Button>
                )}
                <Button data-testid="bd-reschedule-paid" variant="outline" onClick={() => setRescheduleMode(true)}>Reschedule</Button>
                <Button data-testid="bd-cancel-refund" variant="outline" onClick={cancelBookingDetail} className="text-red-600 border-red-300 hover:bg-red-50">
                  Batalkan + Refund (Fee 10%)
                </Button>
                <Button data-testid="bd-no-show" variant="outline" onClick={markNoShow} className="text-amber-700 border-amber-400 hover:bg-amber-50">
                  Tandai No-Show
                </Button>
              </>
            )}
            {rescheduleMode && (
              <>
                <Button data-testid="bd-resched-save" onClick={submitReschedule} className="bg-blue-700 hover:bg-blue-800">Simpan Jadwal Baru</Button>
                <Button variant="ghost" onClick={() => setRescheduleMode(false)}>Batal</Button>
              </>
            )}
            <Button variant="ghost" onClick={() => { setBookingDetail(null); setRescheduleMode(false); }}>Tutup</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Move Room Dialog */}
      <Dialog open={!!moveDialog} onOpenChange={(o) => { if (!o) setMoveDialog(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Pindah Tamu — Kamar {moveDialog?.fromRoom?.nomor}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-slate-600 text-xs">
              Tamu di Kamar <b>{moveDialog?.fromRoom?.nomor}</b> ({statusLabel(moveDialog?.fromRoom?.status)}) akan dipindahkan ke kamar lain.
              Kamar lama akan otomatis berstatus <i>Perlu Dibersihkan</i>.
            </p>
            <div>
              <Label>Kamar Tujuan</Label>
              <select data-testid="move-target-room" value={moveTargetId} onChange={(e) => setMoveTargetId(e.target.value)} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5">
                <option value="">— Pilih kamar kosong —</option>
                {rooms.filter(rr => rr.id !== moveDialog?.fromRoom?.id && rr.status === "kosong").map(rr => (
                  <option key={rr.id} value={rr.id}>Kamar {rr.nomor} ({rr.tipe}) — {fmtRp(rr.tarif)}</option>
                ))}
              </select>
            </div>
            <div>
              <Label>Alasan (opsional)</Label>
              <Input data-testid="move-alasan" value={moveAlasan} onChange={(e) => setMoveAlasan(e.target.value)} placeholder="Mis: AC rusak, request tamu, dll" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setMoveDialog(null)}>Batal</Button>
            <Button data-testid="move-submit" onClick={submitMoveRoom} className="bg-blue-700 hover:bg-blue-800">Pindahkan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Check-in Dialog — wajib isi no_hp tamu sebelum check-in bisa dilakukan */}
      <Dialog open={!!checkinDialog} onOpenChange={(o) => { if (!o) setCheckinDialog(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Check-in Tamu</DialogTitle>
          </DialogHeader>
          {checkinDialog && (
            <div className="space-y-3 text-sm">
              <div>
                <span className="text-slate-500">Tamu:</span> <b>{checkinDialog.booking.nama_tamu}</b>
                {" — "}Kamar {checkinDialog.booking.room_nomor}
              </div>
              <div>
                <Label htmlFor="checkin-no-hp">Nomor Telepon Tamu *</Label>
                <Input
                  id="checkin-no-hp" data-testid="checkin-no-hp-input" placeholder="08xxxxxxxxxx"
                  value={checkinDialog.no_hp}
                  onChange={(e) => setCheckinDialog((d) => ({ ...d, no_hp: e.target.value }))}
                  className="mt-1.5"
                />
                <p className="text-xs text-slate-400 mt-1">Wajib diisi — check-in tidak bisa dilakukan tanpa nomor telepon tamu.</p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCheckinDialog(null)}>Batal</Button>
            <Button
              data-testid="checkin-confirm-submit"
              disabled={!checkinDialog?.no_hp?.trim()}
              onClick={submitCheckin}
              className="bg-emerald-600 hover:bg-emerald-700 text-white"
            >
              Check-in
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Collect Sisa Pelunasan Dialog */}
      <Dialog open={!!collectDialog} onOpenChange={(o) => { if (!o) setCollectDialog(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Collect Sisa Pelunasan</DialogTitle>
          </DialogHeader>
          {collectDialog && (
            <div className="space-y-3 text-sm">
              <div><span className="text-slate-500">Booking:</span> <b>{collectDialog.booking.kode}</b></div>
              <div><span className="text-slate-500">Sisa Tagihan:</span> <b className="text-blue-700">Rp {collectDialog.sisa.toLocaleString("id-ID")}</b></div>
              <div>
                <Label htmlFor="collect-nominal">Nominal Diterima</Label>
                <Input
                  id="collect-nominal" data-testid="collect-nominal-input" type="number"
                  value={collectDialog.nominal}
                  onChange={(e) => setCollectDialog((d) => ({ ...d, nominal: e.target.value }))}
                  className="mt-1.5"
                />
              </div>
              <div>
                <Label htmlFor="collect-metode">Metode Pembayaran</Label>
                <select
                  id="collect-metode" data-testid="collect-metode-select"
                  value={collectDialog.metode}
                  onChange={(e) => setCollectDialog((d) => ({ ...d, metode: e.target.value }))}
                  className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
                >
                  <option value="cash">Cash</option>
                  <option value="qris">QRIS</option>
                </select>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCollectDialog(null)}>Batal</Button>
            <Button data-testid="collect-confirm-submit" onClick={submitCollectBalance} className="bg-blue-700 hover:bg-blue-800">
              Konfirmasi Terima
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SetujuiDialog req={approveReqTarget} onOpenChange={(o) => { if (!o) setApproveReqTarget(null); }} onApproved={load} />
      <TolakDialog req={rejectReqTarget} onOpenChange={(o) => { if (!o) setRejectReqTarget(null); }} onDone={() => { setRejectReqTarget(null); load(); }} />
    </div>
  );
}

function RevCard({ icon: Icon, label, value, hint }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
            <div className="text-2xl font-extrabold mt-1 break-words">{value}</div>
            {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
          </div>
          <div className="w-9 h-9 rounded-lg grid place-items-center bg-blue-50 text-blue-700">
            <Icon className="w-5 h-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function MiniWidget({ label, value, hint, color, testid, wide }) {
  return (
    <div data-testid={testid} className={`rounded-xl border border-slate-200 bg-white p-3 ${wide ? "col-span-2" : ""}`}>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className="text-lg font-extrabold mt-0.5 truncate" style={{ color }}>{value}</div>
      {hint && <div className="text-[10px] text-slate-500 truncate">{hint}</div>}
    </div>
  );
}
