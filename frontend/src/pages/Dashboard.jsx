import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api, { fmtRp, fmtDate, statusLabel, statusColor, bookingConfirmationWaLink, statusBayarOf, STATUS_BAYAR_LABEL, STATUS_BAYAR_BADGE_CLASS, waLink } from "@/lib/apiClient";
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
  Gift, ListChecks, LogIn, LogOut, PhoneCall,
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

const toDateOnly = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

// Warna marun (2026-08-02, permintaan Agus) - booking (Menginap/Day Use) yang SUDAH
// di-checkout staf (status "checked_out"), dipakai di grid Daftar Kamar supaya beda
// jelas dari biru/coklat (masih occupies tanggal itu TAPI belum di-checkout).
const MARUN_CHECKOUT = "#7F1D1D";
// Coklat muda (2026-08-02, permintaan Agus) - booking Day Use yang masih menunggu/belum
// checkout, sebelumnya #92400E (coklat tua) kelihatan mirip MARUN_CHECKOUT di kartu kecil
// - dibedakan lebih jelas biar staf tidak salah baca "booking Day Use" sebagai "sudah
// checkout".
const DAY_USE_BOOKING_COLOR = "#B08968";

// Exclusive-checkout-date rule (2026-08-02) - diekstrak dari logika bookingsOnDate yang
// sudah ada supaya bisa dipakai ulang utk Grid 6 Hari (permintaan Agus) TANPA duplikasi
// aturan yang sama (hari CHECK-OUT tidak dihitung menempati, KECUALI day-use checkin/
// checkout di hari yang sama) - sumber kebenaran yang sama dgn _occupies_date backend.
const bookingOccupiesDateOnly = (b, dateOnly) => {
  const start = toDateOnly(new Date(b.jam_mulai));
  let end = toDateOnly(new Date(b.jam_selesai));
  if (end.getTime() === start.getTime()) end = new Date(start.getTime() + 24 * 3600 * 1000);
  return start <= dateOnly && dateOnly < end;
};

const nowLocalDateTime = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

// Kebijakan pembatalan TUNGGAL (2026-07-31, bug nyata dibenerin - dashboard sebelumnya
// hardcode fee 10% flat, tidak sesuai kebijakan resmi yang sudah dipakai channel lain sejak
// 2026-07-19) - sama persis dgn hitung_kebijakan_pembatalan (core.py) & calcCancelPolicy
// (PublicBook.jsx): H-7 s/d H-3 (>=72 jam sblm check-in) = gratis, H-2 s/d hari-H = 50%.
// Cuma dipakai utk PRATINJAU di dialog konfirmasi staf - angka final tetap dihitung ulang
// server-side saat submit (cancel-with-fee), tidak dipercaya dari sini.
const calcCancelFeePolicy = (jamMulaiIso) => {
  const jamCheckin = new Date(jamMulaiIso);
  const jamTersisa = (jamCheckin.getTime() - Date.now()) / 3600000;
  if (jamTersisa >= 72) {
    return { label: "H-7 s/d H-3 (masih ≥ 72 jam sebelum check-in): refund 100%", biaya_persen: 0 };
  }
  return { label: "H-2 s/d Hari-H (<72 jam sebelum check-in): biaya 50%", biaya_persen: 50 };
};
const emptyQuickForm = (tarif, defaultTipe) => ({
  tipe: defaultTipe || "day_use", nama_tamu: "", no_hp: "", no_identitas: "", kendaraan: "", jumlah_tamu: 1,
  jam_checkin: nowLocalDateTime(), malam: 1, harga: tarif ?? 0, catatan: "",
  metode_bayar: "tunai", // (2026-07-31) tarif dasar WAJIB lunas di depan, lihat submitQuickBook
  // (2026-07-31, permintaan Agus) - Quick Book juga dipakai utk tamu yang datang LANGSUNG
  // ke lokasi tapi mau booking utk TANGGAL LAIN (bukan cuma "sekarang") - tanggal_mulai
  // dipakai khusus Menginap (Day Use sudah punya jam_checkin sendiri yang bisa dimundurkan
  // ke tanggal lain juga). Default hari ini.
  tanggal_mulai: todayLocal(),
  // jam_checkin_menginap (2026-08-02, permintaan Agus - PRD "tamu datang jam 9 pagi minta
  // Menginap, kamar masih terisi tamu Day Use, baru siap jam 2 siang, jangan kalah cepat
  // dgn bookingan online WA/RedDoorz") - KOSONG = perilaku lama (check-in Menginap SEKARANG
  // literal, kalau tanggal_mulai hari ini). Diisi (format "HH:MM") = mode RESERVASI: booking
  // dibuat aktif TAPI TIDAK langsung check-in - kamar yang sekarang masih terisi tamu lain
  // tetap dibiarkan apa adanya, staf check-in manual nanti pas tamu yang baru benar2 datang
  // (tombol "Check-in Tamu" yang sudah ada di dialog detail booking).
  jam_checkin_menginap: "",
});

export default function Dashboard() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [summary, setSummary] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [active, setActive] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [bookingRequests, setBookingRequests] = useState([]); // waiting_approval — supaya owner/resepsionis lihat langsung dari Dashboard, tidak perlu buka halaman terpisah
  const [kedatanganHarian, setKedatanganHarian] = useState([]); // grafik kedatangan tamu 30 hari (2026-07-21, permintaan user)
  const [ulangTahun, setUlangTahun] = useState([]); // tamu ulang tahun hari ini (Member Intelligence, 2026-07-31)
  const [tugasHarian, setTugasHarian] = useState(null); // AI Daily Assistant - daftar tugas resepsionis hari ini
  const [brief, setBrief] = useState(null);
  const [briefLoading, setBriefLoading] = useState(true);
  const isOwner = user?.role === "owner";
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
  const [memberPreview, setMemberPreview] = useState(null); // {nama, total_kunjungan, kedatangan_ke, diskon_persen} | null

  const openQuickBook = (rooms, defaultTipe) => { setQuickForm(emptyQuickForm(rooms[0]?.tarif, defaultTipe)); setQuickBookRooms(rooms); setSlotWarnings([]); setMemberPreview(null); };
  // Reservasi tamu baru utk kamar yang SEKARANG masih terisi tamu lain (2026-08-02,
  // permintaan Agus) - dipanggil dari tombol di dialog aksi kamar (bukan dari klik kamar
  // kosong spt openQuickBook biasa). SENGAJA default tipe "menginap" (skenario nyata yang
  // diminta: tamu walk-in mau Menginap, kamar masih dipakai Day Use, siap beberapa jam
  // lagi) dan langsung set jam_checkin_menginap ke jam sekarang+beberapa saat sbg starting
  // point yang masuk akal (staf tinggal sesuaikan ke jam pastinya) - BUKAN dikosongkan spt
  // openQuickBook biasa (kosong = perilaku "check-in SEKARANG", tidak masuk akal utk kamar
  // yang jelas-jelas masih terisi).
  const openReservasiNanti = (room) => {
    setQuickForm({ ...emptyQuickForm(room.tarif_menginap ?? room.tarif, "menginap"), jam_checkin_menginap: nowLocalDateTime().slice(11, 16) });
    setQuickBookRooms([room]);
    setSlotWarnings([]);
    setMemberPreview(null);
    setActionRoom(null);
  };
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

  // Pengenalan Member real-time (2026-07-31, permintaan Agus - "Member Intelligence") - staf
  // sebelumnya TIDAK dapat info sama sekali saat mengetik HP/KTP tamu walk-in di Quick Book,
  // padahal diskon loyalitas SUDAH benar dihitung di backend saat submit - staf cuma tidak
  // tahu SEBELUM submit, jadi tidak bisa menyapa/menginformasikan tamu itu member. Debounce
  // 400ms supaya tidak query tiap ketikan huruf; butuh minimal 5 digit HP atau 4 karakter KTP
  // (nomor sangat pendek/awal terlalu banyak match acak, tidak berguna).
  useEffect(() => {
    const hp = quickForm.no_hp.trim();
    const ktp = quickForm.no_identitas.trim();
    if (hp.length < 5 && ktp.length < 4) { setMemberPreview(null); return; }
    let batal = false;
    const t = setTimeout(() => {
      api.get("/guests", { params: { q: ktp.length >= 4 ? ktp : hp } })
        .then(({ data }) => {
          if (batal) return;
          const match = data.find((g) =>
            (ktp && g.no_identitas && g.no_identitas === ktp) ||
            (hp && g.no_hp && g.no_hp.replace(/\D/g, "").endsWith(hp.replace(/\D/g, "").slice(-9)))
          );
          setMemberPreview(match && match.total_kunjungan > 0 ? match : null);
        })
        .catch(() => { if (!batal) setMemberPreview(null); });
    }, 400);
    return () => { batal = true; clearTimeout(t); };
  }, [quickForm.no_hp, quickForm.no_identitas]);

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
        // (2026-07-31, keputusan bisnis Agus) - tarif dasar Day Use WAJIB lunas di depan.
        // jumlah dari quickEst.total (sudah termasuk service fee 3%), sama persis dgn
        // perhitungan backend.
        const totalPerKamar = quickEst.total;
        // (2026-07-31, permintaan Agus: "buat day use seperti itu [Menginap] juga") -
        // Day Use jg dipakai utk tamu yg datang langsung tapi mau booking TANGGAL LAIN.
        // Kalau tanggal check-in yg dipilih BUKAN hari ini: jangan langsung /checkins
        // (itu langsung menempati kamar SEKARANG) - buat sbg booking biasa (lunas
        // dibayar), kamar baru ditempati nanti lewat "Check-in Tamu" pas tamu benar2
        // datang (endpoint yg sama sudah menangani konversi booking Day Use -> checkins,
        // lihat checkin_from_booking di routes/bookings.py).
        const dayUseIsToday = quickForm.jam_checkin && quickForm.jam_checkin.slice(0, 10) === todayLocal();
        if (!dayUseIsToday) {
          const { data } = await api.post("/bookings", {
            room_ids: roomIds, tipe: "day_use", nama_tamu: quickForm.nama_tamu, no_hp: quickForm.no_hp,
            no_identitas: quickForm.no_identitas, kendaraan: quickForm.kendaraan,
            jumlah_tamu: Number(quickForm.jumlah_tamu) || 1, catatan: quickForm.catatan,
            jam_mulai: jamIso, tarif_override: harga,
            pembayaran: [{ metode: quickForm.metode_bayar, jumlah: totalPerKamar }],
          });
          const bks = isGroup ? data.bookings : [data];
          toast.success(isGroup ? `Day Use lunas untuk ${bks.length} kamar, dijadwalkan check-in ${quickForm.jam_checkin.slice(0, 10)}` : `Day Use lunas, dijadwalkan check-in ${quickForm.jam_checkin.slice(0, 10)}`);
          setQuickBookRooms([]); cancelMultiSelect(); load();
          return;
        }
        const { data } = await api.post("/checkins", {
          room_ids: roomIds, nama_tamu: quickForm.nama_tamu, no_hp: quickForm.no_hp,
          no_identitas: quickForm.no_identitas, kendaraan: quickForm.kendaraan,
          jumlah_tamu: Number(quickForm.jumlah_tamu) || 1, catatan: quickForm.catatan,
          jam_checkin: jamIso, tarif_override: harga,
          pembayaran: [{ metode: quickForm.metode_bayar, jumlah: totalPerKamar * roomIds.length }],
        });
        toast.success(isGroup ? `Check-in berhasil untuk ${data.checkins.length} kamar` : `Check-in berhasil • ${data.trx_no}`);
      } else {
        // (2026-07-31, keputusan bisnis Agus: "iya bayar di depan semua") - walk-in
        // Menginap via Quick Book sekarang WAJIB lunas + check-in beneran di tempat,
        // sama seperti Day Use. Sebelumnya cuma PUT status kamar manual - TIDAK PERNAH
        // lewat /bookings/{id}/checkin, jadi upsert_guest(count_kunjungan=True) &
        // total_transaksi tidak pernah kepanggil - tamu walk-in Menginap via jalur ini
        // kedatangannya tidak pernah kehitung sama sekali (bug nyata, ditemukan 2026-07-31).
        const isToday = quickForm.tanggal_mulai === todayLocal();
        if (isToday && !quickForm.no_hp.trim()) { toast.error("Nomor HP wajib diisi untuk check-in Menginap"); return; }
        // Mode RESERVASI (2026-08-02, permintaan Agus) - staf isi jam_checkin_menginap saat
        // kamar masih terisi tamu lain sekarang tapi mau dikunci utk tamu baru yang siap
        // menunggu (PRD: "tamu datang jam 9 pagi, kamar ready jam 2 siang, jangan kalah
        // cepat dgn bookingan online"). Beda dari `isToday` biasa (yang berarti check-in
        // LITERAL SEKARANG): di sini instant HANYA kalau hari ini DAN staf TIDAK mengisi jam
        // spesifik - begitu jam diisi, booking dibuat "aktif" (slot terkunci di backend,
        // sudah lolos guard create_reservation yg sudah WIB-aware, lihat reservation_service.py)
        // TAPI check-in beneran (kamar ditandai terisi) BARU terjadi manual nanti.
        const jamNantiRaw = (quickForm.jam_checkin_menginap || "").trim();
        const isInstant = isToday && !jamNantiRaw;
        const nights = Math.max(1, Number(quickForm.malam) || 1);
        // Jam mulai: hari ini + jam reservasi kalau diisi > hari ini + sekarang kalau instant
        // > tanggal lain jam 12:00 (WITA/WIB, sama pola dgn PublicBook.jsx).
        let start;
        if (isToday && jamNantiRaw) {
          start = new Date(`${quickForm.tanggal_mulai}T${jamNantiRaw}:00`);
        } else if (isToday) {
          start = new Date();
        } else {
          start = new Date(`${quickForm.tanggal_mulai}T12:00:00`);
        }
        const end = new Date(start);
        end.setDate(end.getDate() + nights);
        // pembayaran dikirim SEKALIAN saat bikin booking (bukan panggilan mark-paid-manual
        // terpisah - endpoint itu khusus alur booking_pending, Quick Book selalu mulai
        // "aktif", lihat catatan di create_booking/routes/bookings.py). Jumlah dari
        // quickEst.total (belum tentu final persis kalau ada diskon member - sama
        // keterbatasan yg sudah diterima di jalur Day Use, staf sesuaikan fisik kalau beda).
        const totalPerKamarMenginap = quickEst.total;
        const { data } = await api.post("/bookings", {
          room_ids: roomIds, tipe: "menginap", nama_tamu: quickForm.nama_tamu, no_hp: quickForm.no_hp,
          no_identitas: quickForm.no_identitas, kendaraan: quickForm.kendaraan,
          jumlah_tamu: Number(quickForm.jumlah_tamu) || 1, catatan: quickForm.catatan,
          jam_mulai: start.toISOString(), jam_selesai: end.toISOString(), tarif_override: harga,
          pembayaran: [{ metode: quickForm.metode_bayar, jumlah: totalPerKamarMenginap }],
        });
        const bks = isGroup ? data.bookings : [data];
        // Lunas sudah tercatat sekalian saat create (di atas) - check-in SUNGGUHAN (kamar
        // jadi terisi, kedatangan kehitung) HANYA kalau tamu benar2 datang SEKARANG (instant).
        // Mode reservasi & booking utk tanggal lain tetap "aktif"+lunas, di-check-in nanti
        // lewat tombol "Check-in Tamu" saat tamu tiba (sudah ada di dialog detail booking).
        if (isInstant) {
          for (const bk of bks) {
            await api.post(`/bookings/${bk.id}/checkin`, { no_hp: quickForm.no_hp });
          }
        }
        toast.success(
          isInstant
            ? (isGroup ? `Menginap lunas + check-in untuk ${bks.length} kamar` : "Menginap lunas, tamu sudah check-in")
            : isToday
              ? (isGroup ? `Reservasi lunas untuk ${bks.length} kamar, check-in nanti jam ${jamNantiRaw}` : `Reservasi lunas, check-in nanti jam ${jamNantiRaw}`)
              : (isGroup ? `Menginap lunas untuk ${bks.length} kamar, dijadwalkan check-in ${quickForm.tanggal_mulai}` : `Menginap lunas, dijadwalkan check-in ${quickForm.tanggal_mulai}`)
        );
      }
      setQuickBookRooms([]); cancelMultiSelect(); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const load = async () => {
    try {
      const [s, r, c, b, br, kd, ut, th] = await Promise.all([
        api.get("/reports/summary"),
        api.get("/rooms"),
        api.get("/checkins", { params: { status: "aktif" } }),
        api.get("/bookings"),
        api.get("/booking-requests", { params: { status: "waiting_approval" } }),
        api.get("/reports/kedatangan-harian"),
        api.get("/guests/ulang-tahun-hari-ini"),
        api.get("/dashboard/tugas-harian"),
      ]);
      setUlangTahun(ut.data);
      setTugasHarian(th.data);
      // tampilkan semua booking yang menempati kamar: aktif, booking_pending, booking_paid,
      // checked_in (2026-08-01, bug nyata ditemukan Agus - tamu Opa Isa yang sedang menginap
      // sampai 10 Agustus "hilang" total dari Dashboard begitu tanggal yang dilihat digeser
      // ke tengah masa inapnya, misal tanggal 5/8 Agustus - sebabnya status booking-nya sudah
      // berubah dari "aktif" jadi "checked_in" begitu dia benar-benar check-in hari pertama,
      // dan filter ini sebelumnya TIDAK PERNAH menyertakan "checked_in" - jadi booking-nya
      // sama sekali tidak masuk ke array `bookings`, membuat kamarnya kelihatan "kosong" utk
      // SEMUA tanggal selain hari ini. Hari ini sendiri tidak kena krn dashboard pakai status
      // real-time kamar (r.status/r.info) utk hari ini, bukan array `bookings` ini - baru
      // kelihatan begitu staf pindah ke tanggal lain di date picker).
      // sync_status waiting_reddoorz_* (Tahap 2 Modul Reservasi) — booking Menginap dari
      // Booking Request yang belum diinput/disinkron manual ke PMS RedDoorz TETAP memblokir
      // slotnya di backend (check_room_available tidak berubah), tapi belum ditampilkan
      // sebagai tamu terkonfirmasi di grid Dashboard sampai email RedDoorz cocok.
      // "checked_out" (2026-08-02, bug nyata ditemukan Agus - kamar 11 sudah di-checkout
      // TAPI kolom tanggal lain di grid tidak berubah marun & namanya hilang) - booking
      // yang SUDAH checked_out sengaja TIDAK masuk status aktif/blocking manapun (lihat
      // change_room_status/checkins.py checkout()), tapi array `bookings` ini dipakai JUGA
      // buat RENDER histori (warna marun) di grid, bukan cuma cek "masih aktif atau tidak"
      // - kalau checked_out tidak disertakan di sini, booking itu sama sekali tidak pernah
      // sampai ke renderRoomCard, jadi logic warna marun-nya tidak pernah ke-trigger sama
      // sekali (bukan salah warna, tapi datanya memang tidak pernah dikirim ke situ).
      const occupying = b.data.filter(x => ["aktif", "booking_pending", "booking_paid", "checked_in", "checked_out"].includes(x.status)
        && !["waiting_reddoorz_input", "waiting_reddoorz_sync"].includes(x.sync_status));
      setSummary(s.data); setRooms(r.data); setActive(c.data); setBookings(occupying);
      setBookingRequests(br.data);
      setKedatanganHarian(kd.data);
    } catch (e) { console.error(e); }
  };

  const loadBrief = async () => {
    setBriefLoading(true);
    try {
      const { data } = await api.get("/ai-grow/daily-brief");
      setBrief(data);
    } catch (e) { console.error(e); }
    finally { setBriefLoading(false); }
  };

  // Kasih voucher ulang tahun (Member Intelligence, 2026-07-31) - staf klik manual,
  // TIDAK otomatis (hadiah nyata/berdampak uang). Pengiriman pesan JUGA manual lewat
  // WhatsApp pribadi staf (waLink) - Agus eksplisit menolak broadcast otomatis krn
  // risiko nomor WA kena banned.
  const kasihVoucherUlangTahun = async (g) => {
    try {
      await api.post(`/guests/${g.id}/reward-wallet/voucher-ulang-tahun`);
      toast.success(`Voucher ulang tahun diberikan ke ${g.nama}`);
      setUlangTahun((list) => list.map((x) => x.id === g.id ? { ...x, sudah_dapat_voucher_tahun_ini: true } : x));
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal memberi voucher"); }
  };
  const pesanUlangTahunUntuk = (g) =>
    `Halo ${g.nama}! 🎉 Selamat ulang tahun dari kami di Pelangi Homestay. Sebagai apresiasi, kami kasih voucher menginap GRATIS 1 malam untuk 1 kamar standard - tinggal hubungi kami untuk atur jadwalnya ya. Terima kasih sudah jadi tamu setia kami!`;
  // CRM & Marketing - follow up tamu dorman (Member Intelligence, 2026-07-31). Manual
  // klik per tamu via wa.me, TIDAK ada broadcast otomatis (permintaan eksplisit Agus,
  // risiko nomor WA banned).
  const pesanFollowUpUntuk = (g) =>
    g.diskon_persen > 0
      ? `Halo ${g.nama}, kangen nih sudah lama gak mampir ke Pelangi Homestay! Kalau booking lagi sekarang, kamu dapat diskon member ${g.diskon_persen}% (kedatangan ke-${g.kedatangan_ke}). Yuk atur jadwal menginapmu berikutnya 😊`
      : `Halo ${g.nama}, kangen nih sudah lama gak mampir ke Pelangi Homestay! Yuk atur jadwal menginapmu berikutnya, kami tunggu ya 😊`;

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    // AI Grow brief sengaja TIDAK ikut polling 30 detik (mahal & lambat, tidak perlu
    // realtime) - cukup dimuat sekali saat halaman dibuka.
    if (isOwner) loadBrief();
    return () => clearInterval(t);
  }, []);

  // notify overdue (>=5h since checkin) — simple banner
  const nearDue = active.filter(c => (Date.now() - new Date(c.jam_checkin).getTime()) / 3600000 >= 5);
  const overtime = active.filter(c => (Date.now() - new Date(c.jam_checkin).getTime()) / 3600000 >= 6);
  // Khusus yang "mendekati" tapi BELUM overtime (5-6 jam) - dipisah dari nearDue supaya
  // alert "mendekati batas 6 jam" bisa tampilkan nama tamu & nomor kamar-nya sendiri
  // (2026-08-02, permintaan Agus - sebelumnya cuma tampil angka "1 tamu", tidak jelas
  // kamar/tamu mana, beda dari alert "overtime" di atasnya yang sudah lengkap).
  const nearOnly = active.filter(c => {
    const h = (Date.now() - new Date(c.jam_checkin).getTime()) / 3600000;
    return h >= 5 && h < 6;
  });

  // Filter bookings: ribbon hanya muncul jika filterDate ada di rentang [checkin_date, checkout_date)
  // — hari CHECK-OUT TIDAK dihitung menempati (tamu sudah checkout), KECUALI day-use yang
  // checkin/checkout di hari yang sama (tetap occupy hari itu). Bug ditemukan 2026-07-12: versi
  // lama pakai overlap TIMESTAMP mentah (start <= dayEnd && end >= dayStart), yang membuat hari
  // check-out booking menginap selalu ikut tampil sebagai "booked" di grid kamar — sama seperti
  // bug yang sudah diperbaiki di backend (_occupies_date di routes/ketersediaan.py).
  const bookingsOnDate = useMemo(() => {
    const filterDateOnly = toDateOnly(new Date(`${filterDate}T00:00:00`));
    return bookings.filter(b => bookingOccupiesDateOnly(b, filterDateOnly));
  }, [bookings, filterDate]);

  // Jendela 8 Tanggal (2026-08-02, permintaan Agus - Daftar Kamar tampil beberapa
  // tanggal HORIZONTAL/ke samping, bukan 1 tanggal seperti sebelumnya; awalnya 6, lalu
  // ditambah jadi 8 krn masih ada sisa ruang layar). Anchor-nya `filterDate` (state
  // date-picker "Booking pada" yang SUDAH ADA) - supaya tidak ada state/filter paralel,
  // date-picker yang sama sekarang menggeser jendela tanggal ini.
  const JUMLAH_KOLOM_TANGGAL = 8;
  const windowDates = useMemo(() => {
    const start = toDateOnly(new Date(`${filterDate}T00:00:00`));
    return Array.from({ length: JUMLAH_KOLOM_TANGGAL }, (_, i) => new Date(start.getTime() + i * 24 * 3600 * 1000));
  }, [filterDate]);

  const todayOnlyTs = useMemo(() => toDateOnly(new Date()).getTime(), []);

  // Bookings per kolom tanggal - generalisasi dari `bookingsOnDate` (yang cuma utk
  // `filterDate` tunggal) supaya bisa dipakai tiap kolom di grid horizontal.
  const windowColumns = useMemo(() => {
    return windowDates.map((date) => ({
      date,
      isColToday: date.getTime() === todayOnlyTs,
      bookingsForCol: bookings.filter(b => bookingOccupiesDateOnly(b, date)),
    }));
  }, [windowDates, todayOnlyTs, bookings]);

  const isToday = filterDate === todayLocal();
  // BookingDetail dialog state (saat klik room yang punya booking di tanggal filter)
  const [bookingDetail, setBookingDetail] = useState(null);
  const [rescheduleMode, setRescheduleMode] = useState(false);
  const [rescheduleForm, setRescheduleForm] = useState({ jam_mulai: "", jam_selesai: "", room_id: "" });
  // MoveRoom dialog state
  const [moveDialog, setMoveDialog] = useState(null); // { fromRoom }
  const [moveTargetId, setMoveTargetId] = useState("");
  const [moveAlasan, setMoveAlasan] = useState("");
  // Check-in dialog state — minta no_hp tamu sebelum check-in bisa dilakukan
  const [checkinDialog, setCheckinDialog] = useState(null); // { booking, no_hp }
  // Collect sisa pelunasan dialog state
  const [collectDialog, setCollectDialog] = useState(null); // { booking, sisa, nominal, metode }

  const handleRoomClick = (room, upcomingBk, laterTodayBk, isColToday) => {
    // Jika tanggal yang dilihat punya booking di room ini → buka detail booking
    if (upcomingBk) {
      setBookingDetail(upcomingBk);
      setRescheduleMode(false);
      const toLocal = (iso) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
      setRescheduleForm({ jam_mulai: toLocal(upcomingBk.jam_mulai), jam_selesai: toLocal(upcomingBk.jam_selesai), room_id: upcomingBk.room_id });
      return;
    }
    // Hanya hari ini yang boleh trigger flow check-in/checkout/action
    if (!isColToday) {
      toast.info("Tanggal ini tidak ada booking. Untuk transaksi gunakan tanggal hari ini.");
      return;
    }
    if (room.status === "day_use") {
      const ci = active.find((x) => x.room_id === room.id);
      if (ci) {
        // buka action dialog untuk pilih: checkout atau move room. _laterTodayBk (2026-07-28,
        // permintaan user - kamar yang menumpuk Day Use+Menginap hari yang sama cuma kelihatan
        // 1 warna di grid) diteruskan ke sini supaya dialog-nya juga tampilkan booking lain yang
        // sudah mengantre hari ini di kamar yang sama, bukan cuma titik warna di grid.
        setActionRoom({ ...room, _checkin: ci, _laterTodayBk: laterTodayBk });
        setStatusForm({ status: room.status, nama_tamu: ci.nama_tamu, catatan: ci.catatan || "" });
      } else { toast.error("Data check-in tidak ditemukan"); }
      return;
    }
    if (room.status === "kosong") {
      if (multiSelectMode) { toggleRoomSelect(room); return; }
      openQuickBook([room]);
      return;
    }
    setActionRoom({ ...room, _laterTodayBk: laterTodayBk });
    setStatusForm({ status: room.status, nama_tamu: room.info?.nama_tamu || "", catatan: room.info?.catatan || "" });
    setHkPetugas(user?.nama || "");
  };

  // Kartu 1 kamar x 1 tanggal - kartu yang SAMA PERSIS (markup, warna, badge, klik) dgn
  // sebelum grid ini jadi multi-kolom, cuma di-generalisir dari `isToday`/`bookingsOnDate`
  // (state tunggal) jadi `isColToday`/`bookingsForCol` (parameter per kolom) supaya bisa
  // dipanggil ulang JUMLAH_KOLOM_TANGGAL kali per kamar. JANGAN dianggap "komponen grid
  // baru" - ini refactor ekstraksi kartu yang sudah ada, dipakai ulang apa adanya.
  const renderRoomCard = (r, isColToday, bookingsForCol, dateKey) => {
    // KEPUTUSAN FINAL 2026-08-02 (Agus membalik koreksi lifecycle sebelumnya -
    // "gini aku gunakan pms red dors tamu menginap hari ini tampil hari ini saja
    // tidak tampil di tanggal 3... ini yang aku mau tetap konsisten"): status kamar
    // SEKARANG murni berdasarkan TANGGAL (persis cara RedDoorz), bukan lifecycle
    // checked-in/checked-out staf lagi - begitu tanggal checkout tiba (walau staf
    // belum sempat klik Checkout sungguhan), kamar dianggap "kosong" utk tampilan &
    // otomatis masuk jalur upcomingBk (exclusive-checkout-date, sama persis logika
    // Occupancy Calendar) supaya booking BERIKUTNYA di kamar sama hari ini tetap
    // kelihatan.
    const menginapLewatCheckout = (isColToday && r.status === "menginap")
      ? bookings.find(b => b.room_id === r.id && b.tipe === "menginap" &&
          toDateOnly(new Date(b.jam_selesai)).getTime() <= toDateOnly(new Date()).getTime())
      : null;
    const effStatus = isColToday ? (menginapLewatCheckout ? "kosong" : r.status) : "kosong";
    // Pengingat staf (BUKAN blokir booking baru - backend check_room_available
    // tetap jadi penjaga asli anti-double-booking dari data booking sungguhan,
    // ini cuma nudge visual) - kamar kelihatan "kosong" di atas TAPI tamu lama
    // belum benar-benar di-checkout staf, supaya tidak lupa diproses.
    const checkoutHariIniBk = menginapLewatCheckout;
    // "kosong" ATAU "perlu_dibersihkan" - kamar yang baru saja ditinggal tamu lain
    // (belum dibersihkan) TIDAK ADA tamu aktif di dalamnya, sama seperti kamar
    // kosong, jadi booking tamu BERIKUTNYA di tanggal ini tetap harus kelihatan.
    const belumAdaTamuAktif = effStatus === "kosong" || effStatus === "perlu_dibersihkan";
    // (2026-08-02/03, bug nyata ditemukan Agus - kamar 1 Harmoni masih nunjukin info tamu
    // Pranata yang sudah checkout & lunas walau kamarnya sudah kosong; lanjutannya 2026-08-03
    // - kolom tanggal LAIN (bukan hari ini) juga masih nunjukin warna coklat muda utk Day
    // Use yang SUDAH checkout, kelihatan spt "histori masih ada" padahal Day Use itu selesai
    // sehari, tidak perlu histori spt Menginap) checked_out DIKECUALIKAN dari kandidat
    // upcomingBk kalau tipenya Day Use [tidak peduli kolom tanggal mana - Day Use checked_out
    // SELALU tampil kosong polos, tidak pernah ada histori warna].
    // Menginap checked_out TETAP disertakan DI SEMUA kolom termasuk Hari Ini (2026-08-03,
    // dipertegas ulang oleh Agus - sebelumnya ada pengecualian "isColToday" di sini yang
    // SALAH: kalau tamu menginap tanggal 2/checkout tanggal 3, marun WAJIB muncul di kolom
    // tanggal 2 - termasuk kalau kebetulan hari ini PERSIS tanggal 2 itu sendiri [checkout
    // diproses lebih awal dari tanggal checkout resminya]. Tanggal 3 [hari checkout] sendiri
    // TIDAK PERNAH kebagian booking ini sama sekali di bookingsForCol - sudah otomatis
    // dikecualikan oleh bookingOccupiesDateOnly (exclusive end date), jadi tidak perlu
    // pengecualian tambahan apa pun di sini utk Menginap.
    const upcomingBk = belumAdaTamuAktif ? bookingsForCol
      .filter(b => b.room_id === r.id && !(b.status === "checked_out" && b.tipe === "day_use"))
      .sort((a, c) => a.jam_mulai.localeCompare(c.jam_mulai))[0] : null;
    // Marun utk booking MENGINAP yang SUDAH di-checkout (2026-08-02, permintaan Agus -
    // kolom tanggal lain di grid sebelumnya nunjukin biru/menginap terus walau tamunya
    // sudah benar2 checkout, karena bookingOccupiesDateOnly cuma cek rentang tanggal,
    // tidak peduli status). Biru = masih occupies tanggal itu TAPI belum di-checkout
    // staf (butuh perhatian/pengingat), marun = sudah selesai di-checkout (murni
    // histori). KHUSUS Menginap (2026-08-02, revisi Agus - marun jangan dipakai utk Day
    // Use, itu tetap pakai warna coklat muda DAY_USE_BOOKING_COLOR spt biasa walau
    // sudah checked_out) - Day Use memang WAJAR selalu berakhir checkout tiap hari,
    // marun di situ jadi berisik/tidak informatif, beda dgn Menginap yang jarang-jarang.
    const sudahCheckout = upcomingBk?.status === "checked_out" && upcomingBk?.tipe === "menginap";
    const bg = upcomingBk
      ? (sudahCheckout ? MARUN_CHECKOUT : (upcomingBk.tipe === "menginap" ? "#3B82F6" : DAY_USE_BOOKING_COLOR))
      : statusColor(effStatus);
    const bkLabel = upcomingBk
      ? new Date(upcomingBk.jam_mulai).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
      : null;
    // Kamar yang MENUMPUK Day Use + Menginap di hari yang sama - cuma relevan utk
    // kolom hari ini (real-time, jam sungguhan), sama seperti sebelumnya.
    const laterTodayBk = (isColToday && !belumAdaTamuAktif) ? bookingsForCol
      .filter(b => b.room_id === r.id && new Date(b.jam_mulai) > new Date())
      .sort((a, c) => a.jam_mulai.localeCompare(c.jam_mulai))[0] : null;
    const laterColor = laterTodayBk ? (laterTodayBk.tipe === "menginap" ? "#3B82F6" : DAY_USE_BOOKING_COLOR) : null;
    const laterLabel = laterTodayBk
      ? `${laterTodayBk.tipe === "menginap" ? "Menginap" : "Day Use"} ${new Date(laterTodayBk.jam_mulai).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}`
      : null;
    const selectable = isColToday && multiSelectMode && effStatus === "kosong" && !upcomingBk;
    const isSelected = selectable && selectedIds.includes(r.id);
    // Testid kolom "hari ini" tetap `room-{nomor}` (backward compat), kolom lain dapat
    // suffix tanggal supaya tidak ada testid duplikat lintas 6 kolom.
    const suffix = isColToday ? r.nomor : `${r.nomor}-${dateKey}`;
    return (
      <div
        data-testid={`room-${suffix}`}
        onClick={() => handleRoomClick(r, upcomingBk, laterTodayBk, isColToday)}
        role="button" tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter") handleRoomClick(r, upcomingBk, laterTodayBk, isColToday); }}
        className={`room-card relative rounded-xl text-white p-4 aspect-square flex flex-col justify-between text-left overflow-hidden cursor-pointer ${isSelected ? "ring-4 ring-blue-500 ring-offset-2" : ""} ${selectable && !isSelected ? "ring-2 ring-dashed ring-white/60" : ""}`}
        style={{ background: bg }}
      >
        {isSelected && (
          <div className="absolute top-1 right-1 w-5 h-5 rounded-full bg-blue-600 border-2 border-white grid place-items-center text-[10px] font-bold z-10">✓</div>
        )}
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase font-semibold tracking-wider opacity-90">{r.tipe}</span>
          <span className="text-[10px] bg-white/25 rounded px-1.5 py-0.5">{upcomingBk ? (upcomingBk.status === "checked_out" ? "Selesai" : "Booked") : statusLabel(effStatus)}</span>
        </div>
        {/* (2026-08-03, permintaan Agus) - nomor kamar diperkecil (dari 3xl/4xl) supaya
            nama tamu di bawahnya tidak kalah kecil/kepotong - Harmoni khususnya, field
            `nomor`-nya di database memang tersimpan "kamar 1"/"kamar 2" dst (beda dari
            Pelangi yang cuma "1"), jadi digabung dgn label tipe "COTTAGE" di atasnya
            kartu jadi terasa berulang ("Cottage" lalu "kamar 1") - prefix "kamar "
            dibuang HANYA saat tampil di sini (data asli di database TIDAK diubah, tempat
            lain yang pakai r.nomor apa adanya tetap sama). */}
        <div className="text-xl sm:text-2xl font-extrabold leading-tight">{r.nomor.replace(/^kamar\s+/i, "")}</div>
        <div className="text-xs opacity-90 line-clamp-2 leading-snug">
          {upcomingBk ? `${upcomingBk.nama_tamu}` : (effStatus === "kosong" ? fmtRp(r.tarif) : (r.info?.nama_tamu || "—"))}
        </div>
        {bkLabel && (
          <div className="absolute top-0 right-0 bg-amber-900/80 text-[9px] font-bold px-1.5 py-0.5 rounded-bl-md">
            {bkLabel}
          </div>
        )}
        {laterTodayBk && (
          <div
            data-testid={`room-later-${suffix}`}
            title={`Ada booking lain hari ini: ${laterLabel} — ${laterTodayBk.nama_tamu}`}
            className="absolute top-7 left-1 right-1 flex items-center justify-center gap-1.5 text-white font-extrabold text-[13px] px-2 py-1.5 rounded-lg shadow-lg z-10 border-2 border-white animate-pulse"
            style={{ background: laterColor }}
          >
            <span className="text-base leading-none">{laterTodayBk.tipe === "menginap" ? "🌙" : "☀️"}</span>
            <span className="whitespace-nowrap">{laterLabel}</span>
          </div>
        )}
        {upcomingBk && (
          <button
            type="button"
            data-testid={`room-cancel-${suffix}`}
            onClick={(e) => { e.stopPropagation(); quickCancelBooking(upcomingBk); }}
            title="Batalkan booking ini"
            className="absolute top-1 left-1 w-6 h-6 rounded-full bg-white/95 text-red-600 hover:bg-red-600 hover:text-white grid place-items-center transition-colors z-10"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        {checkoutHariIniBk && (
          <div
            data-testid={`room-checkout-due-${suffix}`}
            title={`Kamar tampil kosong sesuai tanggal checkout (${checkoutHariIniBk.nama_tamu}), TAPI staf belum klik Checkout sungguhan - kamar mungkin masih fisik terisi, jangan lupa proses checkout-nya`}
            className="absolute bottom-0 left-0 right-0 bg-violet-900/85 text-white text-[9px] font-bold text-center px-1.5 py-1"
          >
            ⚠ Belum Di-checkout
          </div>
        )}
      </div>
    );
  };

  const cancelBookingDetail = async () => {
    if (!bookingDetail) return;
    const totalNum = Number(bookingDetail.total || 0);
    const policy = calcCancelFeePolicy(bookingDetail.jam_mulai);
    const fee = Math.round(totalNum * policy.biaya_persen / 100);
    const paid = Number(bookingDetail.amount_due || 0);
    const refund = bookingDetail.status === "booking_paid" ? Math.max(0, paid - fee) : 0;
    const msg = bookingDetail.status === "booking_paid"
      ? `Batalkan booking ${bookingDetail.kode}? ${policy.label} - fee ${fmtRp(fee)} dipotong dari pembayaran. Refund: ${fmtRp(refund)}.`
      : `Batalkan booking ${bookingDetail.kode}? ${policy.label} - fee ${fmtRp(fee)} akan dicatat sebagai biaya pembatalan.`;
    if (!window.confirm(msg)) return;
    try {
      const { data } = await api.post(`/bookings/${bookingDetail.id}/cancel-with-fee`, { alasan: "" });
      const tmsg = data.refund_amount > 0
        ? `Booking dibatalkan. Refund ${fmtRp(data.refund_amount)} (fee ${fmtRp(data.fee)}, ${data.policy_label})`
        : `Booking dibatalkan. Fee ${fmtRp(data.fee)} tercatat (${data.policy_label}).`;
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
  // Checkout tamu Menginap langsung dari dialog Booking Detail (2026-08-02, bug nyata
  // ditemukan Agus - kamar 11/Maulana tidak bisa check-in karena tamu sebelumnya belum
  // di-checkout, TAPI tidak ada tombol checkout sama sekali kalau booking dibuka lewat
  // klik kolom tanggal LAIN (bukan Hari Ini) di grid - itu membuka dialog ini
  // [bookingDetail], bukan dialog Action Room [actionRoom] yang punya "Selesai
  // Menginap". Aturan tetap: setiap tamu WAJIB di-checkout dulu sebelum kamar bisa
  // dipakai tamu baru (tidak diubah/dilonggarkan) - ini cuma nambah jalur akses ke aksi
  // checkout yang sama persis (PUT /rooms/{id}/status), bukan tombol baru.
  // (2026-08-03, permintaan Agus) - SEBELUMNYA langsung set status "kosong", melompati
  // proses housekeeping sama sekali (beda dari Day Use, checkins.py checkout() sudah
  // benar set "perlu_dibersihkan" dulu). Sekarang disamakan: checkout Menginap juga
  // masuk antrian Perlu Dibersihkan dulu (muncul di halaman Housekeeping), staf baru
  // tandai kamar kembali Kosong setelah beneran dibersihkan (housekeeping-done).
  const checkoutMenginapFromDetail = async () => {
    if (!bookingDetail) return;
    if (!window.confirm(`Checkout tamu ${bookingDetail.nama_tamu} dari Kamar ${bookingDetail.room_nomor}? Kamar akan masuk antrian Perlu Dibersihkan.`)) return;
    try {
      await api.put(`/rooms/${bookingDetail.room_id}/status`, { status: "perlu_dibersihkan" });
      toast.success(`Kamar ${bookingDetail.room_nomor} berhasil di-checkout, masuk antrian Perlu Dibersihkan.`);
      setBookingDetail(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal checkout"); }
  };

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

  // Quick cancel langsung dari kartu kamar (tombol X) - fee pakai kebijakan pembatalan
  // tunggal (2026-07-31, bug nyata dibenerin - sebelumnya hardcode 10% flat, tidak sesuai
  // aturan resmi H-7~H-3=gratis/H-2~hari-H=50%, lihat calcCancelFeePolicy).
  const quickCancelBooking = async (bk) => {
    if (!bk) return;
    const totalNum = Number(bk.total || 0);
    const policy = calcCancelFeePolicy(bk.jam_mulai);
    const fee = Math.round(totalNum * policy.biaya_persen / 100);
    if (!window.confirm(`Batalkan booking ${bk.kode} (${bk.nama_tamu}, kamar ${bk.room_nomor})? ${policy.label} - fee ${fmtRp(fee)} akan dicatat.`)) return;
    try {
      const { data } = await api.post(`/bookings/${bk.id}/cancel-with-fee`, { alasan: "" });
      const tmsg = data.refund_amount > 0
        ? `Booking dibatalkan. Refund ${fmtRp(data.refund_amount)} (fee ${fmtRp(data.fee)}, ${data.policy_label})`
        : `Booking ${bk.kode} dibatalkan. Fee ${fmtRp(data.fee)} tercatat (${data.policy_label}).`;
      toast.success(tmsg);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const submitReschedule = async () => {
    if (!bookingDetail) return;
    try {
      const payload = {
        tipe: bookingDetail.tipe, room_id: rescheduleForm.room_id || bookingDetail.room_id,
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
      {nearOnly.length > 0 && (
        <div data-testid="near-due-alert" className="rounded-xl bg-amber-50 border border-amber-200 p-4 flex items-start gap-3">
          <Hourglass className="w-5 h-5 text-amber-600 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-amber-800">{nearOnly.length} tamu mendekati batas 6 jam</div>
            <div className="text-amber-700">
              {nearOnly.map(c => `Kamar ${c.room_nomor} (${c.nama_tamu})`).join(", ")}
            </div>
          </div>
        </div>
      )}

      {/* Notif Ulang Tahun (Member Intelligence, 2026-07-31) - kirim pesan & kasih
          voucher SELALU manual lewat tombol staf, tidak ada broadcast otomatis */}
      {ulangTahun.length > 0 && (
        <div data-testid="ulang-tahun-alert" className="rounded-xl bg-pink-50 border border-pink-200 p-4">
          <div className="flex items-start gap-3 mb-3">
            <Gift className="w-5 h-5 text-pink-600 mt-0.5 shrink-0" />
            <div className="text-sm">
              <div className="font-semibold text-pink-900">{ulangTahun.length} tamu ulang tahun hari ini 🎉</div>
              <div className="text-pink-700">Kirim ucapan & tawarkan voucher menginap gratis (1 malam, 1 kamar standard).</div>
            </div>
          </div>
          <div className="space-y-2">
            {ulangTahun.map((g) => (
              <div key={g.id} data-testid={`ulang-tahun-${g.id}`} className="flex items-center justify-between gap-3 bg-white border border-pink-100 rounded-lg p-2.5 text-sm">
                <div>
                  <div className="font-semibold">{g.nama}</div>
                  <div className="text-xs text-slate-500">{g.no_hp || "-"}</div>
                </div>
                <div className="flex gap-2 shrink-0">
                  {g.no_hp && (
                    <a href={waLink(g.no_hp, pesanUlangTahunUntuk(g))} target="_blank" rel="noreferrer">
                      <Button size="sm" variant="outline"><MessageCircle className="w-3.5 h-3.5 mr-1" /> Kirim Pesan</Button>
                    </a>
                  )}
                  <Button size="sm" className="bg-pink-600 hover:bg-pink-700" disabled={g.sudah_dapat_voucher_tahun_ini}
                    onClick={() => kasihVoucherUlangTahun(g)} data-testid={`kasih-voucher-${g.id}`}>
                    <Gift className="w-3.5 h-3.5 mr-1" /> {g.sudah_dapat_voucher_tahun_ini ? "Voucher Sudah Diberi" : "Kasih Voucher"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI Daily Assistant (Member Intelligence, 2026-07-31) - daftar tugas resepsionis
          hari ini, deterministik dari data yang sudah ada (bukan generate GPT) */}
      {tugasHarian && (
        tugasHarian.kedatangan_menginap_hari_ini.length + tugasHarian.keberangkatan_menginap_hari_ini.length
          + tugasHarian.day_use_sedang_berlangsung.length + tugasHarian.tamu_perlu_follow_up.length > 0
      ) && (
        <Card className="border-slate-200" data-testid="tugas-harian-card">
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center gap-2 mb-3">
              <ListChecks className="w-4.5 h-4.5 text-indigo-600" />
              <div className="font-semibold">Tugas Hari Ini</div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              {tugasHarian.kedatangan_menginap_hari_ini.length > 0 && (
                <div className="border border-slate-200 rounded-lg p-3">
                  <div className="flex items-center gap-1.5 font-semibold text-slate-700 mb-1.5"><LogIn className="w-3.5 h-3.5" /> Kedatangan Menginap ({tugasHarian.kedatangan_menginap_hari_ini.length})</div>
                  {tugasHarian.kedatangan_menginap_hari_ini.map((b) => (
                    <div key={b.id} className="text-xs text-slate-500 py-0.5">{b.nama_tamu} - kamar {b.room_nomor}</div>
                  ))}
                </div>
              )}
              {tugasHarian.keberangkatan_menginap_hari_ini.length > 0 && (
                <div className="border border-slate-200 rounded-lg p-3">
                  <div className="flex items-center gap-1.5 font-semibold text-slate-700 mb-1.5"><LogOut className="w-3.5 h-3.5" /> Keberangkatan Menginap ({tugasHarian.keberangkatan_menginap_hari_ini.length})</div>
                  {tugasHarian.keberangkatan_menginap_hari_ini.map((b) => (
                    <div key={b.id} className="text-xs text-slate-500 py-0.5">{b.nama_tamu} - kamar {b.room_nomor}</div>
                  ))}
                </div>
              )}
              {tugasHarian.day_use_sedang_berlangsung.length > 0 && (
                <div className="border border-slate-200 rounded-lg p-3">
                  <div className="flex items-center gap-1.5 font-semibold text-slate-700 mb-1.5"><Clock className="w-3.5 h-3.5" /> Day Use Berlangsung ({tugasHarian.day_use_sedang_berlangsung.length})</div>
                  {tugasHarian.day_use_sedang_berlangsung.map((c) => (
                    <div key={c.id} className="text-xs text-slate-500 py-0.5">{c.nama_tamu} - kamar {c.room_nomor}</div>
                  ))}
                </div>
              )}
              {tugasHarian.tamu_perlu_follow_up.length > 0 && (
                <div className="border border-slate-200 rounded-lg p-3 sm:col-span-2">
                  <div className="flex items-center gap-1.5 font-semibold text-slate-700 mb-1.5"><PhoneCall className="w-3.5 h-3.5" /> Follow Up Tamu Lama ({tugasHarian.tamu_perlu_follow_up.length})</div>
                  <div className="space-y-1">
                    {tugasHarian.tamu_perlu_follow_up.slice(0, 8).map((g) => (
                      <div key={g.id} className="flex items-center justify-between text-xs text-slate-500 py-0.5 gap-2">
                        <span className="truncate">
                          {g.nama} - {g.total_kunjungan}x, terakhir {fmtDate(g.last_visit)}
                          {g.peluang_kembali && <span className="text-slate-400"> · peluang kembali ~{g.peluang_kembali.persen}% ({g.peluang_kembali.label})</span>}
                        </span>
                        {g.no_hp && (
                          <a href={waLink(g.no_hp, pesanFollowUpUntuk(g))} target="_blank" rel="noreferrer" className="shrink-0">
                            <Button size="sm" variant="outline" className="h-6 text-xs px-2"><MessageCircle className="w-3 h-3 mr-1" /> Kirim Pesan</Button>
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                  {tugasHarian.tamu_perlu_follow_up.length > 8 && (
                    <button onClick={() => nav("/tamu")} className="text-xs text-blue-600 hover:underline mt-1.5">Lihat semua di Data Tamu →</button>
                  )}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
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

      {/* AI Grow — Daily Executive Brief (2026-07-22, permintaan user: Executive Business
          Intelligence di atas PMS - Health Score + narasi + rekomendasi prioritas, satu
          tempat di Dashboard utama, owner-only. Juga terkirim ke Telegram tiap 07:30 WIB. */}
      {isOwner && (
        <Card className="border-slate-200 bg-teal-50/40">
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3 mb-2">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-blue-700" />
                <p className="font-bold text-sm">AI Grow — Daily Executive Brief</p>
              </div>
              {brief?.health_score && (
                <div
                  className={`shrink-0 text-xs font-bold px-2.5 py-1 rounded-full ${
                    brief.health_score.skor >= 80 ? "bg-emerald-100 text-emerald-700"
                    : brief.health_score.skor >= 60 ? "bg-amber-100 text-amber-700"
                    : "bg-red-100 text-red-700"
                  }`}
                  title="Business Health Score"
                >
                  Health Score {brief.health_score.skor}/100
                </div>
              )}
            </div>
            <p className="text-sm text-slate-700 whitespace-pre-line">{briefLoading ? "Menyusun ringkasan…" : brief?.narasi}</p>

            {!briefLoading && brief?.rekomendasi?.length > 0 && (
              <div className="mt-3 pt-3 border-t border-teal-900/10 space-y-1.5">
                {brief.rekomendasi.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <AlertTriangle className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${r.tipe === "risiko" ? "text-red-500" : "text-amber-500"}`} />
                    <span><b>{r.judul}</b> — {r.aksi}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Grafik Kedatangan Tamu 30 Hari (2026-07-21, permintaan user) - dipecah jadi 2
          grafik terpisah kiri/kanan (2026-08-03, revisi Agus dari versi stik bertumpuk
          sebelumnya) - Menginap kiri, Day Use kanan, supaya masing-masing lebih mudah
          dibaca sendiri-sendiri (skala Y beda kalau volumenya jauh berbeda antar tipe). */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-slate-200">
          <CardContent className="p-4 sm:p-6">
            <h2 className="text-lg font-bold mb-1">Kedatangan Menginap (30 Hari Terakhir)</h2>
            <p className="text-xs text-slate-500 mb-4">Jumlah booking Menginap per tanggal check-in (kecuali yang dibatalkan)</p>
            <div className="h-64 w-full">
              <ResponsiveContainer>
                <BarChart data={kedatanganHarian} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="tanggal" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} interval={2} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip labelFormatter={(d) => fmtDate(d)} formatter={(v) => [v, "Menginap"]} />
                  <Bar dataKey="menginap" name="Menginap" fill="#2563EB" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4 sm:p-6">
            <h2 className="text-lg font-bold mb-1">Kedatangan Day Use (30 Hari Terakhir)</h2>
            <p className="text-xs text-slate-500 mb-4">Jumlah booking Day Use per tanggal check-in (kecuali yang dibatalkan)</p>
            <div className="h-64 w-full">
              <ResponsiveContainer>
                <BarChart data={kedatanganHarian} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="tanggal" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} interval={2} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip labelFormatter={(d) => fmtDate(d)} formatter={(v) => [v, "Day Use"]} />
                  <Bar dataKey="day_use" name="Day Use" fill="#8B5CF6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
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
              <span className="w-3 h-3 rounded-sm" style={{ background: DAY_USE_BOOKING_COLOR }} />
              <span className="text-slate-600">Booked Day Use</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ background: "#3B82F6" }} />
              <span className="text-slate-600">Booked Menginap ({bookingsOnDate.length})</span>
            </div>
            {isToday && (
              <div className="flex items-center gap-1.5" title="Titik kecil di pojok kiri-atas kamar menandakan sudah ada booking lain (Day Use/Menginap) yang mengantre di kamar yang sama hari ini">
                <span className="w-2 h-2 rounded-full bg-slate-400" />
                <span className="text-slate-600">Titik = ada booking lain menyusul hari ini di kamar sama</span>
              </div>
            )}
          </div>
          {/* Daftar Kamar - N tanggal horizontal (2026-08-02, revisi permintaan Agus: SEBELUMNYA
              sempat dibuat sbg tabel/grid terpisah yang memanjang ke BAWAH - itu salah paham,
              dihapus. Yang benar: tanggal jadi HEADER KOLOM ke samping, kamar tetap jadi baris,
              dan tiap sel MEMAKAI ULANG persis kartu kamar yang sama (lihat renderRoomCard) -
              bukan komponen/grid baru, cuma dipanggil JUMLAH_KOLOM_TANGGAL kali per kamar (1x
              per tanggal) alih-alih 1x. Kolom pertama = `filterDate` (date-picker "Booking pada"
              yang sudah ada, jadi tidak ada state filter tanggal baru/paralel), kolom berikutnya
              = filterDate+1..+(JUMLAH_KOLOM_TANGGAL-1) hari. Kartu ukurannya FIXED (w-36, TIDAK
              menyusut) - scroll horizontal kalau sempit. */}
          <div className="overflow-x-auto -mx-1 px-1">
            <div className="inline-block min-w-full">
              <div className="flex sticky top-0 z-30 bg-white pb-2">
                <div className="sticky left-0 z-40 bg-white w-20 shrink-0" />
                {windowColumns.map(({ date, isColToday }) => (
                  <div key={date.toISOString()} className="w-36 shrink-0 px-1 text-center">
                    <div className={`text-xs font-bold rounded-md py-1.5 ${isColToday ? "bg-blue-700 text-white" : "bg-slate-100 text-slate-600"}`}>
                      {date.toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "short" })}
                      {isColToday && <span className="block text-[9px] font-normal opacity-90">Hari ini</span>}
                    </div>
                  </div>
                ))}
              </div>
              <div data-testid="room-grid" className="flex flex-col gap-3">
                {rooms.map((r) => (
                  <div key={r.id} className="flex items-center">
                    <div className="sticky left-0 z-20 bg-white w-20 shrink-0 pr-2">
                      <div className="text-sm font-extrabold text-slate-700 leading-tight">{r.nomor}</div>
                      <div className="text-[10px] text-slate-400 uppercase truncate">{r.tipe}</div>
                    </div>
                    {windowColumns.map(({ date, isColToday, bookingsForCol }) => {
                      const dateKey = date.toISOString().slice(0, 10);
                      return (
                        <div key={dateKey} className="w-36 shrink-0 px-1">
                          {renderRoomCard(r, isColToday, bookingsForCol, dateKey)}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
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
            {memberPreview && (
              <div data-testid="q-member-badge" className="col-span-2 flex items-center gap-2.5 rounded-lg border-2 border-amber-300 bg-amber-50 px-3 py-2.5">
                <Percent className="w-5 h-5 text-amber-600 shrink-0" />
                <div className="text-sm">
                  <p className="font-bold text-amber-900">
                    {memberPreview.nama} — Member, kedatangan ke-{memberPreview.kedatangan_ke}
                  </p>
                  <p className="text-amber-800">
                    {memberPreview.diskon_persen > 0
                      ? `Dapat diskon loyalitas ${memberPreview.diskon_persen}% hari ini`
                      : "Belum dapat diskon di kedatangan ini (lihat tabel loyalitas)"}
                    {memberPreview.total_kunjungan > 0 && ` — sudah ${memberPreview.total_kunjungan}x datang`}
                  </p>
                </div>
              </div>
            )}
            <div><Label>Kendaraan</Label><Input value={quickForm.kendaraan} onChange={(e) => setQuickForm(f => ({ ...f, kendaraan: e.target.value }))} /></div>
            <div><Label>Jumlah Tamu</Label><Input type="number" min="1" value={quickForm.jumlah_tamu} onChange={(e) => setQuickForm(f => ({ ...f, jumlah_tamu: e.target.value }))} /></div>
            {quickForm.tipe === "day_use" ? (
              <div className="col-span-2">
                <Label>Jam Check-In</Label>
                <Input data-testid="q-jam" type="datetime-local" value={quickForm.jam_checkin} onChange={(e) => setQuickForm(f => ({ ...f, jam_checkin: e.target.value }))} />
                {quickForm.jam_checkin && quickForm.jam_checkin.slice(0, 10) !== todayLocal() && (
                  <p className="text-[10px] text-amber-600 mt-1">Tanggal lain (bukan hari ini) - kamar TIDAK langsung ditandai terisi, tamu di-check-in nanti pas benar-benar datang.</p>
                )}
                {slotWarnings.map((w) => (
                  <div key={w.room_nomor} data-testid={`q-slot-warning-${w.room_nomor}`} className="mt-2 flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md p-2.5">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <span><b>Kamar {w.room_nomor}:</b> {w.alasan}</span>
                  </div>
                ))}
              </div>
            ) : (
              <>
                <div>
                  <Label>Tanggal Check-In</Label>
                  <Input data-testid="q-tanggal-mulai" type="date" min={todayLocal()} value={quickForm.tanggal_mulai} onChange={(e) => setQuickForm(f => ({ ...f, tanggal_mulai: e.target.value }))} />
                  {quickForm.tanggal_mulai !== todayLocal() && (
                    <p className="text-[10px] text-amber-600 mt-1">Tanggal lain (bukan hari ini) - kamar TIDAK langsung ditandai terisi, tamu di-check-in nanti pas benar-benar datang.</p>
                  )}
                </div>
                {/* (2026-08-02, permintaan Agus) - kalau tanggalnya hari ini, staf bisa
                    pilih: kosongkan = tamu check-in SEKARANG (perilaku lama), atau isi jam
                    = mode RESERVASI (kamar mungkin masih terisi tamu lain, booking dikunci
                    dulu di sistem, check-in beneran menyusul manual pas tamu datang). */}
                {quickForm.tanggal_mulai === todayLocal() && (
                  <div className="col-span-2">
                    <Label>Jam Check-In (kosongkan = sekarang)</Label>
                    <Input data-testid="q-jam-menginap" type="time" value={quickForm.jam_checkin_menginap} onChange={(e) => setQuickForm(f => ({ ...f, jam_checkin_menginap: e.target.value }))} />
                    {quickForm.jam_checkin_menginap ? (
                      <p className="text-[10px] text-amber-600 mt-1">Mode reservasi - booking dikunci di sistem sekarang, tapi kamar TIDAK langsung ditandai terisi. Staf check-in manual nanti pas tamu benar-benar datang (tombol "Check-in Tamu" di detail booking).</p>
                    ) : (
                      <p className="text-[10px] text-slate-500 mt-1">Kosong = tamu check-in sekarang juga (kamar langsung ditandai terisi).</p>
                    )}
                  </div>
                )}
                <div><Label>Jumlah Malam</Label><Input data-testid="q-malam" type="number" min="1" value={quickForm.malam} onChange={(e) => setQuickForm(f => ({ ...f, malam: e.target.value }))} /></div>
              </>
            )}
            <div className="col-span-2">
              <Label>{quickForm.tipe === "day_use" ? "Harga (per 6 jam)" : "Harga per Malam"}{quickBookRooms.length > 1 ? " — per kamar" : ""}</Label>
              <Input data-testid="q-harga" type="number" min="0" value={quickForm.harga} onChange={(e) => setQuickForm(f => ({ ...f, harga: e.target.value }))} />
            </div>
            <div className="col-span-2"><Label>Catatan</Label><Textarea value={quickForm.catatan} onChange={(e) => setQuickForm(f => ({ ...f, catatan: e.target.value }))} rows={2} /></div>
            {/* (2026-07-31, keputusan bisnis Agus "bayar di depan semua") - berlaku Day Use
                MAUPUN Menginap walk-in via Quick Book sekarang, bukan cuma Day Use lagi. */}
            <div className="col-span-2">
              <Label>Metode Bayar (wajib lunas sekarang)</Label>
              <select data-testid="q-metode-bayar" value={quickForm.metode_bayar} onChange={(e) => setQuickForm(f => ({ ...f, metode_bayar: e.target.value }))} className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5">
                <option value="tunai">Tunai</option>
                <option value="qris">QRIS</option>
                <option value="transfer">Transfer</option>
                <option value="edc">EDC/Kartu</option>
              </select>
            </div>
            <div data-testid="q-est-summary" className="col-span-2 rounded-lg bg-blue-50 border border-blue-200 p-3 text-sm space-y-1">
              <div className="flex justify-between"><span className="text-slate-600">Subtotal{quickForm.tipe === "menginap" ? ` (${quickEst.nights} malam)` : ""}{quickBookRooms.length > 1 ? " / kamar" : ""}</span><b>{fmtRp(quickEst.subtotal)}</b></div>
              <div className="flex justify-between"><span className="text-slate-600">Service Fee (3%){quickBookRooms.length > 1 ? " / kamar" : ""}</span><b>{fmtRp(quickEst.service_fee)}</b></div>
              <div className="flex justify-between text-base pt-1 border-t border-blue-200 mt-1">
                <span className="font-bold">Dibayar Sekarang{quickBookRooms.length > 1 ? " / kamar" : ""}</span>
                <b className="text-blue-700">{fmtRp(quickEst.total)}</b>
              </div>
              {quickBookRooms.length > 1 && (
                <div className="flex justify-between text-base pt-1 border-t border-blue-300 mt-1"><span className="font-bold">Total {quickBookRooms.length} Kamar</span><b className="text-blue-800">{fmtRp(quickEst.total * quickBookRooms.length)}</b></div>
              )}
              {quickForm.tipe === "day_use"
                ? <p className="text-[10px] text-slate-500">*Tarif dasar 6 jam ini lunas sekarang. Kalau tamu extend/overtime, ditagih terpisah saat checkout.</p>
                : <p className="text-[10px] text-slate-500">*Lunas untuk {quickEst.nights} malam, dibayar sekarang saat check-in.</p>}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setQuickBookRooms([])}>Batal</Button>
            <Button data-testid="q-submit" onClick={submitQuickBook} className="bg-blue-700 hover:bg-blue-800">
              {quickForm.tipe === "day_use"
                ? "Konfirmasi Check-In"
                : (quickForm.tanggal_mulai === todayLocal() && quickForm.jam_checkin_menginap ? "Bayar & Reservasi" : "Bayar & Check-In")}
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
            {actionRoom?._laterTodayBk && (
              <div className="rounded-lg bg-amber-50 border border-amber-200 p-2.5 flex items-start gap-2">
                <span className="w-2.5 h-2.5 rounded-full mt-1 shrink-0" style={{ background: actionRoom._laterTodayBk.tipe === "menginap" ? "#3B82F6" : DAY_USE_BOOKING_COLOR }} />
                <div>
                  <p className="font-medium text-amber-900">
                    Kamar ini juga sudah ada booking {actionRoom._laterTodayBk.tipe === "menginap" ? "Menginap" : "Day Use"} lain hari ini
                  </p>
                  <p className="text-amber-800">
                    {actionRoom._laterTodayBk.nama_tamu} — mulai {new Date(actionRoom._laterTodayBk.jam_mulai).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
              </div>
            )}
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
            {/* (2026-08-02, permintaan Agus) - staf bisa langsung reservasi tamu WALK-IN
                BARU utk kamar ini walau masih terisi tamu lain sekarang, supaya tidak kalah
                cepat dgn bookingan online (WA/RedDoorz) yang bisa masuk kapan saja. Booking
                dibuat "aktif" (slotnya terkunci di sistem) TANPA mengganggu tamu yang
                sekarang - check-in tamu baru dilakukan manual nanti pas dia benar2 datang. */}
            {(actionRoom?.status === "day_use" || actionRoom?.status === "menginap") && (
              <Button data-testid="reservasi-nanti" variant="outline" onClick={() => openReservasiNanti(actionRoom)}>
                Reservasi Tamu Baru (Nanti Kosong)
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
              {bookingDetail.group_bookings?.length > 0 && (
                <div className="bg-indigo-50 border border-indigo-200 rounded p-2 text-xs space-y-1" data-testid="booking-detail-rombongan">
                  <div className="font-bold text-indigo-800">
                    Bagian dari Rombongan ({bookingDetail.group_bookings.length + 1} kamar, dibayar dalam 1 transaksi)
                  </div>
                  {bookingDetail.group_bookings.map((g) => (
                    <div key={g.id} className="flex justify-between">
                      <span>{g.kode} — {g.room_nomor} ({g.room_tipe})</span>
                      <span className="px-1.5 rounded bg-slate-100 text-slate-700">{g.status}</span>
                    </div>
                  ))}
                </div>
              )}
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
              <p className="text-slate-600 text-xs">Geser jam mulai/selesai dan/atau pindahkan ke kamar lain untuk reschedule booking.</p>
              <div>
                <Label>Kamar</Label>
                <select
                  data-testid="resched-room"
                  value={rescheduleForm.room_id}
                  onChange={(e) => setRescheduleForm(f => ({ ...f, room_id: e.target.value }))}
                  className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
                >
                  {rooms
                    .filter(r => r.status !== "maintenance" || r.id === rescheduleForm.room_id)
                    .map((r) => (
                      <option key={r.id} value={r.id}>{r.nomor} - {r.tipe} ({r.status})</option>
                    ))}
                </select>
                {/* (2026-08-03, permintaan Agus) - tamu BELUM check-in di sini (reschedule
                    cuma tersedia utk status aktif/booking_pending/booking_paid, lihat tombol
                    di bawah) - jadi TIDAK ADA tamu fisik di kamar manapun, kamar tujuan tidak
                    perlu "kosong/bersih" dulu (beda dari Pindah Kamar di kartu kamar Dashboard
                    yang khusus tamu SUDAH check-in, itu tetap wajib kamar tujuan kosong).
                    Backend cuma cek jadwal tidak bentrok (check_room_available), sama seperti
                    reschedule tanggal biasa. */}
                <p className="text-[11px] text-slate-500 mt-1">Tamu belum check-in - kamar tujuan tidak harus kosong/sudah dibersihkan, sistem cuma memastikan jadwalnya tidak bentrok.</p>
              </div>
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
                <Button data-testid="bd-cancel" variant="outline" onClick={cancelBookingDetail} className="text-red-600 border-red-300 hover:bg-red-50">Batalkan (Fee {calcCancelFeePolicy(bookingDetail.jam_mulai).biaya_persen}%)</Button>
              </>
            )}
            {!rescheduleMode && bookingDetail?.status === "booking_pending" && (
              <>
                <Button data-testid="bd-reschedule" variant="outline" onClick={() => setRescheduleMode(true)}>Reschedule</Button>
                <Button data-testid="bd-mark-paid-manual" variant="outline" onClick={markPaidManual} className="text-emerald-700 border-emerald-400 hover:bg-emerald-50">
                  Konfirmasi Pembayaran Manual
                </Button>
                <Button data-testid="bd-cancel-pending" variant="outline" onClick={cancelBookingDetail} className="text-red-600 border-red-300 hover:bg-red-50">Batalkan (Fee {calcCancelFeePolicy(bookingDetail.jam_mulai).biaya_persen}%)</Button>
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
                  Batalkan + Refund (Fee {calcCancelFeePolicy(bookingDetail.jam_mulai).biaya_persen}%)
                </Button>
                <Button data-testid="bd-no-show" variant="outline" onClick={markNoShow} className="text-amber-700 border-amber-400 hover:bg-amber-50">
                  Tandai No-Show
                </Button>
              </>
            )}
            {!rescheduleMode && bookingDetail?.status === "checked_in" && (
              <>
                {Number(bookingDetail.total || 0) - Number(bookingDetail.amount_due || 0) > 0 && (
                  <Button data-testid="bd-collect-checked-in" onClick={openCollectDialog} className="bg-blue-700 hover:bg-blue-800 text-white">
                    Collect Sisa Rp {(Number(bookingDetail.total || 0) - Number(bookingDetail.amount_due || 0)).toLocaleString("id-ID")}
                  </Button>
                )}
                {bookingDetail.tipe === "menginap" && (
                  <Button data-testid="bd-checkout-menginap" onClick={checkoutMenginapFromDetail} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                    Checkout Tamu
                  </Button>
                )}
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
