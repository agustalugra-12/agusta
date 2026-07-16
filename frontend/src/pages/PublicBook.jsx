import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { bookingConfirmationWaLink, waLink, STATUS_BAYAR_LABEL } from "@/lib/apiClient";
import { ExtraBedSelector } from "@/pages/PermintaanKhususExtraBed";
import {
  BedDouble, Wifi, Snowflake, Tv, Droplets, Bath, Trees, CheckCircle2, XCircle,
  Calendar, Clock, User, Phone, IdCard, Car, Users as UsersIcon, Building2, ArrowRight, Mail, Ban, Download,
} from "lucide-react";

// API client tanpa auth (untuk endpoint /api/public/*)
const PUBLIC_API = axios.create({ baseURL: `${process.env.REACT_APP_BACKEND_URL}/api` });
const fmtRp = (n) => "Rp " + Number(n || 0).toLocaleString("id-ID");
// Sama dengan EXTRA_BED_PRICE/EXTRA_BED_MAX di backend/core.py.
// Day Use: flat sekali bayar. Menginap: dikali jumlah malam (lihat summary di bawah).
const EXTRA_BED_PRICE = 50000;
const EXTRA_BED_MAX = 2;
// Sama dengan BREAKFAST_PRICE di backend/core.py — hanya berlaku untuk booking menginap.
const BREAKFAST_PRICE = 25000;
const CS_WHATSAPP = "0851-1945-9269";
const CS_EMAIL = "pelangihomestay9@gmail.com";
const JAM_OPERASIONAL = "07.00 – 22.00 WITA";
// Disimpan begitu booking dibuat, dipakai SuccessView sebagai fallback kalau URL /book/sukses
// diakses tanpa :bookingId (mis. tamu menutup tab checkout Tripay lalu balik lewat riwayat
// browser, bukan lewat return_url yang sudah disisipi ID booking).
const LAST_BOOKING_ID_KEY = "pelangi_last_booking_id";
const ALAMAT_HOMESTAY = "Jl. Kebun Raya Bedugul, Candikuning, Kecamatan Baturiti, Kabupaten Tabanan, Bali 82191, Indonesia";
const addDays = (dateStr, n) => {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const todayStr = () => {
  const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const FACILITY_ICONS = {
  "AC": Snowflake, "Wi-Fi gratis": Wifi, "TV LED": Tv,
  "Kamar mandi dalam": Bath, "Air panas": Droplets, "Handuk & toiletries": CheckCircle2,
  "Cottage Style": BedDouble, "Area Outdoor": Trees,
};

export default function PublicBook({ successView = false }) {
  const { bookingId } = useParams();
  if (successView) return <SuccessView bookingId={bookingId} />;
  return <BookingForm />;
}

function BookingForm() {
  const [catalog, setCatalog] = useState([]);
  const [tanggal, setTanggal] = useState(todayStr());
  const [tipe, setTipe] = useState("");           // filter tipe kamar (kosong = semua)
  const [bookingTipe, setBookingTipe] = useState("day_use"); // "day_use" | "menginap"
  const [checkoutDate, setCheckoutDate] = useState(addDays(todayStr(), 1));
  const [availability, setAvailability] = useState({ rooms: [] });
  const [step, setStep] = useState(1);            // 1 = pilih kamar, 2 = form
  const [selectedRooms, setSelectedRooms] = useState([]); // [{id, nomor, tipe, tarif, tarif_menginap}, ...] — bisa >1 kamar sekaligus
  const [form, setForm] = useState({
    nama_tamu: "", no_hp: "", email: "", no_identitas: "", jumlah_tamu: 1, kendaraan: "",
    jam_checkin: "13:00", catatan: "",
  });
  const [extraBedQty, setExtraBedQty] = useState(0);
  const [denganSarapan, setDenganSarapan] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [paymentOption, setPaymentOption] = useState("dp50"); // dp50 | full
  const [channels, setChannels] = useState([]);
  const [method, setMethod] = useState(""); // kode channel Tripay, mis. "BRIVA"
  const nav = useNavigate();

  useEffect(() => {
    PUBLIC_API.get("/public/rooms-catalog").then(r => setCatalog(r.data)).catch(() => {});
    // daftar metode bayar Tripay dimuat sekali di awal (bukan tiap step 2) supaya siap saat
    // tamu sampai ke ringkasan — daftarnya jarang berubah, aman di-fetch lebih awal.
    PUBLIC_API.get("/payments/tripay/channels").then(r => setChannels(r.data)).catch(() => setChannels([]));
  }, []);

  // Kalau tanggal check-in digeser melewati check-out yang sudah dipilih, geser check-out juga
  useEffect(() => {
    if (bookingTipe === "menginap" && checkoutDate <= tanggal) {
      setCheckoutDate(addDays(tanggal, 1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tanggal, bookingTipe]);

  useEffect(() => {
    if (!tanggal) return;
    const params = { tanggal, tipe: tipe || undefined };
    if (bookingTipe === "menginap") params.checkout = checkoutDate;
    PUBLIC_API.get("/public/availability", { params })
      .then(r => setAvailability(r.data))
      .catch(() => setAvailability({ rooms: [] }));
  }, [tanggal, tipe, bookingTipe, checkoutDate]);

  const nights = useMemo(() => {
    if (bookingTipe !== "menginap") return 1;
    const a = new Date(`${tanggal}T00:00:00`), b = new Date(`${checkoutDate}T00:00:00`);
    return Math.max(1, Math.round((b - a) / 86400000));
  }, [bookingTipe, tanggal, checkoutDate]);

  // Ringkasan harga per kamar (extra bed & sarapan berlaku sama untuk tiap kamar yang
  // dipilih), dijumlah untuk grand total kalau tamu pilih >1 kamar sekaligus.
  const perRoomSummaries = useMemo(() => {
    const isMenginap = bookingTipe === "menginap";
    return selectedRooms.map((room) => {
      const breakfastTotal = isMenginap && denganSarapan ? BREAKFAST_PRICE * nights : 0;
      const extraBedTotal = extraBedQty * EXTRA_BED_PRICE * (isMenginap ? nights : 1);
      const tarifDasar = isMenginap ? room.tarif_menginap : room.tarif;
      const tarifKamar = tarifDasar * (isMenginap ? nights : 1);
      const subtotal = tarifKamar + breakfastTotal + extraBedTotal;
      const svc = Math.round(subtotal * 0.03);
      const total = subtotal + svc;
      return { room, tarifKamar, breakfastTotal, extraBedTotal, subtotal, service_fee: svc, total };
    });
  }, [selectedRooms, extraBedQty, denganSarapan, bookingTipe, nights]);

  const summary = useMemo(() => {
    if (perRoomSummaries.length === 0) return null;
    const sum = (key) => perRoomSummaries.reduce((a, s) => a + s[key], 0);
    return {
      tarifKamar: sum("tarifKamar"), breakfastTotal: sum("breakfastTotal"), extraBedTotal: sum("extraBedTotal"),
      subtotal: sum("subtotal"), service_fee: sum("service_fee"), total: sum("total"),
      dp_min: Math.round(sum("total") * 0.5), nights,
    };
  }, [perRoomSummaries, nights]);

  const toggleRoom = (room) => {
    setSelectedRooms((rooms) => rooms.some((r) => r.id === room.id)
      ? rooms.filter((r) => r.id !== room.id)
      : [...rooms, room]);
  };
  const lanjutkanPilihKamar = () => {
    if (selectedRooms.length === 0) return;
    setExtraBedQty(0);
    // denganSarapan TIDAK direset di sini — tamu sudah memilihnya di katalog (step 1)
    // lewat tombol harga Tanpa/Dengan Sarapan, harus terbawa ke ringkasan step 2.
    setStep(2);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const submit = async () => {
    if (!form.nama_tamu.trim() || !form.no_hp.trim() || !form.no_identitas.trim()) {
      toast.error("Lengkapi nama, no HP, dan no identitas");
      return;
    }
    const emailTrimmed = form.email.trim();
    const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailTrimmed);
    if (!emailTrimmed || !emailValid) {
      toast.error("Email wajib diisi dengan format yang valid — untuk menerima bukti pembayaran");
      return;
    }
    if (selectedRooms.length === 0) { toast.error("Pilih kamar dulu"); return; }
    if (!method) { toast.error("Pilih metode pembayaran dulu"); return; }
    setSubmitting(true);
    try {
      // 1. Buat booking — 1 kamar (room_id) atau beberapa sekaligus (room_ids, 1 grup 1
      // transaksi pembayaran). Response beda bentuk: dict datar kalau 1 kamar, {group_id,
      // bookings:[...]} kalau lebih dari 1 (lihat public_create_booking, backend/routes/public.py).
      const { data: resp } = await PUBLIC_API.post("/public/bookings", {
        nama_tamu: form.nama_tamu.trim(),
        no_hp: form.no_hp.trim(),
        email: emailTrimmed,
        no_identitas: form.no_identitas.trim(),
        jumlah_tamu: Number(form.jumlah_tamu) || 1,
        kendaraan: form.kendaraan.trim(),
        room_ids: selectedRooms.map((r) => r.id),
        tanggal, jam_checkin: form.jam_checkin,
        catatan: form.catatan.trim(),
        extra_bed_qty: extraBedQty,
        tipe: bookingTipe,
        ...(bookingTipe === "menginap" ? { tanggal_checkout: checkoutDate, dengan_sarapan: denganSarapan } : {}),
      });
      const primaryBooking = resp.bookings ? resp.bookings[0] : resp;
      localStorage.setItem(LAST_BOOKING_ID_KEY, primaryBooking.id);
      // 2. Buat transaksi Tripay untuk metode yang dipilih, lalu redirect ke halaman
      // instruksi bayar ter-hosted Tripay (checkout_url) — beda dari Snap Midtrans yang
      // dulu buka popup, Tripay tidak punya widget popup jadi tamu diarahkan ke tab ini juga.
      // Kalau primaryBooking bagian dari grup, backend otomatis menagih TOTAL GABUNGAN semua
      // kamar dalam grup itu dalam 1 transaksi (lihat tripay_create_transaction).
      const { data: tx } = await PUBLIC_API.post("/payments/tripay/create-transaction", {
        booking_id: primaryBooking.id, payment_option: paymentOption, method,
      });
      toast.dismiss();
      window.location.href = tx.checkout_url;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal membuat booking");
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-cream text-ink font-sans">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-paper/95 backdrop-blur border-b border-teal-deep/10">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <img src="/pelangi-logo.png" alt="Pelangi Homestay" className="h-12 w-auto object-contain" />
          </div>
          <Link to="/login" className="text-xs text-teal-deep/60 hover:text-teal-deep font-medium">Staff Login</Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-10 space-y-8">
        {/* Hero */}
        <section className="text-center space-y-3">
          <p className="text-xs uppercase tracking-[0.3em] text-mustard-deep font-semibold">Reservasi Online</p>
          <h1 className="font-display text-3xl sm:text-5xl font-bold tracking-tight text-teal-deep">
            Istirahat Sejenak di<br className="hidden sm:block" /> Sejuknya Bedugul
          </h1>
          <p className="text-teal-deep/70 max-w-xl mx-auto">
            Day use untuk singgah sejenak, atau menginap menikmati udara pegunungan lebih lama —
            harga jujur, konfirmasi instan. Pilih tanggal, pilih kamar, selesai.
          </p>
        </section>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-2 text-xs">
          <StepDot active={step >= 1} done={step > 1} label="Pilih Kamar" />
          <div className="w-6 h-px bg-teal-deep/30" />
          <StepDot active={step >= 2} done={false} label="Isi Data & Bayar" />
        </div>

        {step === 1 && (
          <>
            {/* Date picker */}
            <Card className="bg-paper border-teal-deep/15 shadow-paper-sm">
              <CardContent className="p-4 sm:p-5 space-y-4">
                <div>
                  <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60 mb-1.5 block">Jenis Kunjungan</Label>
                  <div className="flex gap-2">
                    <Button data-testid="pb-booking-tipe-dayuse" type="button" variant={bookingTipe === "day_use" ? "default" : "outline"} className={bookingTipe === "day_use" ? "h-12 flex-1 rounded-full bg-teal-deep hover:bg-teal-deep/90 text-cream" : "h-12 flex-1 rounded-full border-2 border-teal-deep/25 text-teal-deep hover:bg-teal-deep/5"} onClick={() => setBookingTipe("day_use")}>Day Use</Button>
                    <Button data-testid="pb-booking-tipe-menginap" type="button" variant={bookingTipe === "menginap" ? "default" : "outline"} className={bookingTipe === "menginap" ? "h-12 flex-1 rounded-full bg-teal-deep hover:bg-teal-deep/90 text-cream" : "h-12 flex-1 rounded-full border-2 border-teal-deep/25 text-teal-deep hover:bg-teal-deep/5"} onClick={() => setBookingTipe("menginap")}>Menginap</Button>
                  </div>
                </div>
                <div className="grid sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
                  <div>
                    <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60">{bookingTipe === "menginap" ? "Tanggal Check-In" : "Tanggal Kunjungan"}</Label>
                    <Input data-testid="pb-tanggal" type="date" value={tanggal} min={todayStr()} onChange={(e) => setTanggal(e.target.value)} className="h-12 mt-1.5 text-base rounded-full border-teal-deep/20 focus-visible:ring-mustard" />
                  </div>
                  {bookingTipe === "menginap" && (
                    <div>
                      <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60">Tanggal Check-Out</Label>
                      <Input data-testid="pb-tanggal-checkout" type="date" value={checkoutDate} min={addDays(tanggal, 1)} onChange={(e) => setCheckoutDate(e.target.value)} className="h-12 mt-1.5 text-base rounded-full border-teal-deep/20 focus-visible:ring-mustard" />
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button data-testid="pb-tipe-all" type="button" variant={tipe === "" ? "default" : "outline"} className={tipe === "" ? "h-12 rounded-full bg-teal-deep hover:bg-teal-deep/90 text-cream" : "h-12 rounded-full border-2 border-teal-deep/25 text-teal-deep hover:bg-teal-deep/5"} onClick={() => setTipe("")}>Semua</Button>
                    <Button data-testid="pb-tipe-std" type="button" variant={tipe === "Standard" ? "default" : "outline"} className={tipe === "Standard" ? "h-12 rounded-full bg-teal-deep hover:bg-teal-deep/90 text-cream" : "h-12 rounded-full border-2 border-teal-deep/25 text-teal-deep hover:bg-teal-deep/5"} onClick={() => setTipe("Standard")}>Standard</Button>
                    <Button data-testid="pb-tipe-cot" type="button" variant={tipe === "Cottage" ? "default" : "outline"} className={tipe === "Cottage" ? "h-12 rounded-full bg-mustard hover:bg-mustard-deep text-teal-deep" : "h-12 rounded-full border-2 border-mustard/40 text-mustard-deep hover:bg-mustard/10"} onClick={() => setTipe("Cottage")}>Cottage</Button>
                  </div>
                </div>
                {bookingTipe === "menginap" && (
                  <p className="text-xs text-teal-deep/60">{nights} malam &middot; Check-out jam 12:00 siang</p>
                )}
              </CardContent>
            </Card>

            {/* Catalog (per tipe dengan foto + fasilitas) */}
            <div className="grid sm:grid-cols-2 gap-4 sm:gap-6">
              {catalog.map((c) => {
                const availOfTipe = availability.rooms.filter(r => r.tipe === c.tipe);
                const isSoldOut = availOfTipe.length === 0;
                return (
                  <Card key={c.tipe} data-testid={`pb-catalog-${c.tipe}`} className="bg-paper border-teal-deep/10 rounded-2xl overflow-hidden shadow-paper-sm hover:shadow-paper hover:-translate-y-0.5 transition-all">
                    {c.image && (
                      <div className="relative aspect-[4/3] overflow-hidden bg-teal-deep/5">
                        <img src={c.image} alt={`${c.tipe} — Pelangi Homestay`} className="w-full h-full object-cover" loading="lazy" />
                        {isSoldOut && (
                          <div className="absolute inset-0 bg-teal-deep/70 flex items-center justify-center">
                            <span className="bg-cream text-teal-deep font-display font-bold px-4 py-2 rounded-full text-sm rotate-[-6deg] shadow-paper-sm">Sold Out</span>
                          </div>
                        )}
                        {bookingTipe !== "menginap" && (
                          <div className="absolute top-3 right-3 bg-mustard text-teal-deep px-3 py-1 rounded-full text-xs font-bold shadow-paper-sm">
                            {fmtRp(c.tarif)} <span className="font-normal text-teal-deep/70">/ 6 jam</span>
                          </div>
                        )}
                      </div>
                    )}
                    <CardContent className="p-5 space-y-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.25em] text-mustard-deep font-semibold">Kamar</div>
                          <h3 className="font-display text-xl font-bold text-teal-deep">{c.tipe}</h3>
                          {c.size && (
                            <p className="text-xs text-teal-deep/60 mt-0.5">📐 {c.size} &middot; 👥 {c.capacity}</p>
                          )}
                        </div>
                        {bookingTipe !== "menginap" && !c.image && (
                          <div className="text-right">
                            <div className="font-display text-2xl font-bold text-teal-deep">{fmtRp(c.tarif)}</div>
                            <div className="text-[10px] uppercase tracking-wider text-teal-deep/60">/ 6 jam</div>
                          </div>
                        )}
                      </div>
                      {c.description && (
                        <p className="text-sm text-teal-deep/75 leading-relaxed">{c.description}</p>
                      )}
                      {bookingTipe === "menginap" && (
                        <div className="grid grid-cols-2 gap-2" data-testid={`pb-sarapan-pilihan-${c.tipe}`}>
                          <button
                            type="button"
                            data-testid={`pb-harga-tanpa-sarapan-${c.tipe}`}
                            onClick={() => setDenganSarapan(false)}
                            className={`p-2.5 rounded-lg border-2 text-left transition-colors ${!denganSarapan ? "border-teal-deep bg-teal-deep/8" : "border-teal-deep/15 hover:border-teal-deep/30"}`}
                          >
                            <div className="text-[9px] uppercase tracking-wider text-teal-deep/60 font-semibold">Tanpa Sarapan</div>
                            <div className="font-bold text-teal-deep">{fmtRp(c.tarif_menginap)}</div>
                            <div className="text-[9px] text-teal-deep/50">/ malam</div>
                          </button>
                          <button
                            type="button"
                            data-testid={`pb-harga-dengan-sarapan-${c.tipe}`}
                            onClick={() => setDenganSarapan(true)}
                            className={`p-2.5 rounded-lg border-2 text-left transition-colors ${denganSarapan ? "border-teal-deep bg-teal-deep/8" : "border-teal-deep/15 hover:border-teal-deep/30"}`}
                          >
                            <div className="text-[9px] uppercase tracking-wider text-teal-deep/60 font-semibold">Dengan Sarapan</div>
                            <div className="font-bold text-teal-deep">{fmtRp(c.tarif_menginap + BREAKFAST_PRICE)}</div>
                            <div className="text-[9px] text-teal-deep/50">/ malam</div>
                          </button>
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2">
                        {c.fasilitas.map((f) => {
                          const Ico = FACILITY_ICONS[f] || CheckCircle2;
                          return (
                            <span key={f} className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-full bg-teal-deep/8 text-teal-deep font-medium">
                              <Ico className="w-3 h-3" /> {f}
                            </span>
                          );
                        })}
                      </div>
                      <div className="pt-2 border-t border-dashed border-teal-deep/20">
                        <div className="text-xs text-teal-deep/60 mb-2 font-medium">
                          {availOfTipe.length > 0 ? `✨ ${availOfTipe.length} kamar tersedia` : "Kamar habis di tanggal ini"}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {availOfTipe.length === 0 && (
                            <span className="text-xs text-red-700 italic">Coba pilih tanggal lain</span>
                          )}
                          {availOfTipe.map((r) => {
                            const dipilih = selectedRooms.some((sr) => sr.id === r.id);
                            return (
                              <button
                                key={r.id}
                                data-testid={`pb-room-${r.nomor}`}
                                onClick={() => toggleRoom(r)}
                                className={`px-3 py-1.5 text-xs font-bold border-2 rounded-full transition-colors ${dipilih ? "border-teal-deep bg-teal-deep text-cream" : "border-teal-deep/25 hover:border-teal-deep hover:bg-teal-deep/5"}`}
                              >
                                {dipilih ? "✓ " : ""}Kamar {r.nomor}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
              {catalog.length === 0 && (
                <div className="col-span-full text-center text-teal-deep/60 py-10 font-display italic">Memuat katalog...</div>
              )}
            </div>

            {selectedRooms.length > 0 && (
              <div data-testid="pb-selected-bar" className="sticky bottom-4 z-10">
                <Card className="border-teal-deep/20 shadow-paper bg-paper/95 backdrop-blur">
                  <CardContent className="p-3 sm:p-4 flex items-center justify-between gap-3 flex-wrap">
                    <div className="text-sm text-teal-deep">
                      <b>{selectedRooms.length} kamar dipilih</b>: {selectedRooms.map((r) => r.nomor).join(", ")}
                    </div>
                    <div className="flex gap-2">
                      <Button variant="ghost" size="sm" className="text-teal-deep hover:bg-teal-deep/5" onClick={() => setSelectedRooms([])}>Batal</Button>
                      <Button data-testid="pb-lanjutkan" className="rounded-full bg-teal-deep hover:bg-teal-deep/90 text-cream" onClick={lanjutkanPilihKamar}>
                        Lanjutkan ({selectedRooms.length} Kamar)
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
          </>
        )}

        {step === 2 && selectedRooms.length > 0 && summary && (
          <div className="grid md:grid-cols-[1fr_360px] gap-6">
            {/* Form */}
            <Card className="bg-paper border-teal-deep/15 shadow-paper-sm">
              <CardContent className="p-5 sm:p-6 space-y-4">
                <button onClick={() => setStep(1)} className="text-sm text-teal-deep hover:underline">&larr; Pilih kamar lain</button>
                <h2 className="font-display text-2xl font-bold text-teal-deep">Data Tamu</h2>
                <FieldIcon icon={User} label="Nama Lengkap"><Input data-testid="pb-nama" value={form.nama_tamu} onChange={(e) => setForm(f => ({ ...f, nama_tamu: e.target.value }))} className="h-12" /></FieldIcon>
                <FieldIcon icon={Phone} label="Nomor WhatsApp"><Input data-testid="pb-hp" placeholder="08xxxxxxxxxx" value={form.no_hp} onChange={(e) => setForm(f => ({ ...f, no_hp: e.target.value }))} className="h-12" /></FieldIcon>
                <div>
                  <FieldIcon icon={Mail} label="Email">
                    <Input
                      data-testid="pb-email"
                      type="email"
                      inputMode="email"
                      autoComplete="email"
                      placeholder="nama@email.com"
                      value={form.email}
                      onChange={(e) => setForm(f => ({ ...f, email: e.target.value }))}
                      className="h-12"
                      required
                    />
                  </FieldIcon>
                  <p className="mt-1.5 text-[11px] text-mustard-deep bg-mustard/10 border border-mustard/30 rounded-md px-2.5 py-1.5">
                    <span className="font-bold">Wajib diisi</span> — bukti pembayaran & konfirmasi booking akan dikirim ke email ini.
                  </p>
                </div>
                <FieldIcon icon={IdCard} label="Nomor Identitas (KTP/Paspor)"><Input data-testid="pb-ktp" value={form.no_identitas} onChange={(e) => setForm(f => ({ ...f, no_identitas: e.target.value }))} className="h-12" /></FieldIcon>
                <div className="grid grid-cols-2 gap-3">
                  <FieldIcon icon={UsersIcon} label="Jumlah Tamu"><Input data-testid="pb-jumlah" type="number" min="1" value={form.jumlah_tamu} onChange={(e) => setForm(f => ({ ...f, jumlah_tamu: e.target.value }))} className="h-12" /></FieldIcon>
                  <FieldIcon icon={Car} label="Kendaraan"><Input data-testid="pb-kendaraan" placeholder="Mis: B 1234 ABC" value={form.kendaraan} onChange={(e) => setForm(f => ({ ...f, kendaraan: e.target.value }))} className="h-12" /></FieldIcon>
                </div>
                <FieldIcon icon={Clock} label="Jam Check-In">
                  <Input data-testid="pb-jam" type="time" value={form.jam_checkin} onChange={(e) => setForm(f => ({ ...f, jam_checkin: e.target.value }))} className="h-12" />
                </FieldIcon>
                {bookingTipe === "menginap" && (
                  <div>
                    <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60 mb-1.5 block">Paket Kamar</Label>
                    <button
                      type="button"
                      data-testid="pb-sarapan-toggle"
                      onClick={() => setDenganSarapan((v) => !v)}
                      className={`w-full flex items-center justify-between border rounded-lg p-3 text-left transition-colors ${denganSarapan ? "border-teal-deep bg-teal-deep/8" : "border-teal-deep/15 hover:border-teal-deep/30"}`}
                    >
                      <div>
                        <div className="font-medium text-sm text-teal-deep">Sarapan Pagi</div>
                        <div className="text-xs text-teal-deep/60">{fmtRp(BREAKFAST_PRICE)} / malam per kamar (opsional)</div>
                      </div>
                      <div className={`w-5 h-5 rounded border-2 grid place-items-center shrink-0 ${denganSarapan ? "border-teal-deep bg-teal-deep" : "border-teal-deep/30"}`}>
                        {denganSarapan && <CheckCircle2 className="w-3.5 h-3.5 text-cream" />}
                      </div>
                    </button>
                  </div>
                )}
                <div>
                  <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60 mb-1.5 block">Permintaan Khusus</Label>
                  <ExtraBedSelector value={extraBedQty} onChange={setExtraBedQty} max={EXTRA_BED_MAX} harga={EXTRA_BED_PRICE} satuan={selectedRooms.length > 1 ? "kamar" : "pemesanan"} />
                </div>
                <div>
                  <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60">Catatan (opsional)</Label>
                  <Textarea data-testid="pb-catatan" value={form.catatan} onChange={(e) => setForm(f => ({ ...f, catatan: e.target.value }))} className="mt-1.5" rows={3} placeholder="Mis: request lantai bawah, late check-in, dll" />
                </div>
              </CardContent>
            </Card>

            {/* Summary sidebar */}
            <Card className="bg-paper border-teal-deep/15 shadow-paper-sm h-fit md:sticky md:top-20">
              <CardContent className="p-5 space-y-4">
                <div>
                  <div className="text-xs uppercase tracking-wider text-teal-deep/60">Booking Anda</div>
                  {selectedRooms.length === 1 ? (
                    <div className="font-display font-bold text-lg text-teal-deep">{selectedRooms[0].tipe} • Kamar {selectedRooms[0].nomor}</div>
                  ) : (
                    <div className="font-display font-bold text-lg text-teal-deep" data-testid="pb-multi-room-summary">{selectedRooms.length} Kamar: {selectedRooms.map((r) => `${r.nomor} (${r.tipe})`).join(", ")}</div>
                  )}
                </div>
                <div className="space-y-2 text-sm border-t border-teal-deep/10 pt-3">
                  <Row icon={Calendar} label="Check-In" value={new Date(`${tanggal}T00:00:00`).toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "long", year: "numeric" })} />
                  {bookingTipe === "menginap" ? (
                    <>
                      <Row icon={Calendar} label="Check-Out" value={new Date(`${checkoutDate}T00:00:00`).toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "long", year: "numeric" })} />
                      <Row icon={Clock} label="Lama Menginap" value={`${summary.nights} malam`} />
                    </>
                  ) : (
                    <Row icon={Clock} label="Jam Check-In" value={`${form.jam_checkin} (6 jam)`} />
                  )}
                  {selectedRooms.length === 1 && <Row icon={Building2} label="Tipe" value={selectedRooms[0].tipe} />}
                </div>
                <div className="space-y-1.5 border-t border-teal-deep/10 pt-3 text-sm">
                  <div className="flex justify-between"><span className="text-teal-deep/70">Tarif Kamar{bookingTipe === "menginap" ? ` × ${summary.nights} malam` : ""}{selectedRooms.length > 1 ? ` × ${selectedRooms.length} kamar` : ""}</span><b className="text-teal-deep">{fmtRp(summary.tarifKamar)}</b></div>
                  {summary.breakfastTotal > 0 && (
                    <div className="flex justify-between" data-testid="pb-breakfast-fee"><span className="text-teal-deep/70">Sarapan Pagi × {summary.nights} malam{selectedRooms.length > 1 ? ` × ${selectedRooms.length} kamar` : ""}</span><b className="text-teal-deep">{fmtRp(summary.breakfastTotal)}</b></div>
                  )}
                  {extraBedQty > 0 && (
                    <div className="flex justify-between" data-testid="pb-extra-bed-fee"><span className="text-teal-deep/70">Extra Bed &times;{extraBedQty}{selectedRooms.length > 1 ? ` × ${selectedRooms.length} kamar` : ""}</span><b className="text-teal-deep">{fmtRp(summary.extraBedTotal)}</b></div>
                  )}
                  <div className="flex justify-between"><span className="text-teal-deep/70">Service Fee (3%)</span><b className="text-teal-deep" data-testid="pb-service-fee">{fmtRp(summary.service_fee)}</b></div>
                  <div className="flex justify-between text-base pt-1.5 border-t border-teal-deep/15 mt-1.5"><span className="font-bold text-teal-deep">Total</span><b className="text-mustard-deep" data-testid="pb-total">{fmtRp(summary.total)}</b></div>
                </div>
                <div className="border-t border-teal-deep/10 pt-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60">Opsi Pembayaran</Label>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <button data-testid="pb-pay-dp50" type="button" onClick={() => setPaymentOption("dp50")} className={`p-3 rounded-lg border-2 text-left transition-colors ${paymentOption === "dp50" ? "border-teal-deep bg-teal-deep/8" : "border-teal-deep/15 hover:border-teal-deep/30"}`}>
                      <div className="text-[10px] uppercase tracking-wider text-teal-deep/60 font-semibold">DP 50%</div>
                      <div className="font-bold text-teal-deep" data-testid="pb-dp">{fmtRp(summary.dp_min)}</div>
                      <div className="text-[10px] text-teal-deep/50">Sisa di lokasi</div>
                    </button>
                    <button data-testid="pb-pay-full" type="button" onClick={() => setPaymentOption("full")} className={`p-3 rounded-lg border-2 text-left transition-colors ${paymentOption === "full" ? "border-teal-deep bg-teal-deep/8" : "border-teal-deep/15 hover:border-teal-deep/30"}`}>
                      <div className="text-[10px] uppercase tracking-wider text-teal-deep/60 font-semibold">Bayar Penuh</div>
                      <div className="font-bold text-teal-deep">{fmtRp(summary.total)}</div>
                      <div className="text-[10px] text-teal-deep/50">Tanpa sisa</div>
                    </button>
                  </div>
                </div>
                <div className="border-t border-teal-deep/10 pt-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60">Metode Pembayaran</Label>
                  {channels.length === 0 ? (
                    <p className="text-xs text-teal-deep/40 mt-2">Memuat metode pembayaran...</p>
                  ) : (
                    <div className="mt-2 space-y-3 max-h-64 overflow-y-auto pr-1" data-testid="pb-payment-methods">
                      {Object.entries(
                        channels.reduce((acc, c) => {
                          acc[c.group] = acc[c.group] || [];
                          acc[c.group].push(c);
                          return acc;
                        }, {})
                      ).map(([group, items]) => (
                        <div key={group}>
                          <div className="text-[10px] uppercase tracking-wider text-teal-deep/40 font-semibold mb-1">{group}</div>
                          <div className="grid grid-cols-2 gap-1.5">
                            {items.map((c) => (
                              <button
                                key={c.code}
                                type="button"
                                data-testid={`pb-method-${c.code}`}
                                onClick={() => setMethod(c.code)}
                                className={`flex items-center gap-2 p-2 rounded-lg border-2 text-left transition-colors ${method === c.code ? "border-teal-deep bg-teal-deep/8" : "border-teal-deep/15 hover:border-teal-deep/30"}`}
                              >
                                <img src={c.icon_url} alt="" className="w-6 h-6 object-contain shrink-0" />
                                <span className="text-xs font-medium truncate text-teal-deep">{c.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <Button data-testid="pb-submit" disabled={submitting || !method} onClick={submit} className="w-full h-12 rounded-full bg-teal-deep hover:bg-teal-deep/90 text-cream text-base font-bold">
                  {submitting ? "Memproses..." : "Bayar Sekarang"} <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
                <p className="text-[10px] text-center text-teal-deep/50">
                  Dengan menekan tombol, Anda menyetujui kebijakan reservasi.
                  Pembatalan gratis sampai {bookingTipe === "menginap" ? "H-3" : "H-1"} sebelum check-in, setelah itu dikenakan biaya 10% dari total pembayaran.
                </p>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Footer info */}
        <footer className="text-center text-xs text-teal-deep/60 pt-8 border-t border-teal-deep/10 space-y-2">
          <p className="font-semibold text-teal-deep">Pelangi Homestay &middot; Bersantai di kaki Bedugul, Bali</p>
          <p className="max-w-md mx-auto">{ALAMAT_HOMESTAY}</p>
          <p className="flex items-center justify-center gap-1.5">
            <Clock className="w-3.5 h-3.5" /> Jam Operasional: {JAM_OPERASIONAL}
          </p>
          <p className="flex items-center justify-center gap-1.5">
            <Mail className="w-3.5 h-3.5" />
            <a href={`mailto:${CS_EMAIL}`} className="hover:text-teal-deep">{CS_EMAIL}</a>
          </p>
          <a
            href={waLink(CS_WHATSAPP, "Halo, saya ingin bertanya tentang booking di Pelangi Homestay.")}
            target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-leaf hover:text-teal-deep font-semibold"
          >
            <Phone className="w-3.5 h-3.5" /> Chat Admin/CS: {CS_WHATSAPP}
          </a>
        </footer>
      </main>
    </div>
  );
}

function StepDot({ active, done, label }) {
  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full ${active ? "bg-teal-deep text-cream" : "bg-teal-deep/10 text-teal-deep/60"}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      <span className="font-semibold">{label}</span>
      {done && <CheckCircle2 className="w-3 h-3" />}
    </div>
  );
}

function FieldIcon({ icon: Icon, label, children }) {
  return (
    <div>
      <Label className="text-xs font-semibold uppercase tracking-wider text-teal-deep/60 inline-flex items-center gap-1.5"><Icon className="w-3 h-3" /> {label}</Label>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

function Row({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="inline-flex items-center gap-1.5 text-teal-deep/70"><Icon className="w-3.5 h-3.5" /> {label}</span>
      <b className="text-right text-teal-deep">{value}</b>
    </div>
  );
}

// Kebijakan pembatalan yang sama dengan yang sudah dijanjikan di pesan konfirmasi WA
// (lihat buildBookingConfirmationMessage di apiClient.js): batas bebas biaya H-3 untuk
// booking menginap, H-1 untuk day use; biaya 10% dari total jika sudah lewat batas, dan
// tidak ada refund untuk No Show/hari-H. Booking publik saat ini selalu day_use, tapi
// dibuat tipe-aware supaya tetap benar kalau nanti booking menginap dibuka untuk publik.
function batasJamBebasBiaya(bk) {
  return bk.tipe === "menginap" ? 72 : 24;
}

function calcCancelPolicy(bk) {
  const batasJam = batasJamBebasBiaya(bk);
  const batasLabel = bk.tipe === "menginap" ? "H-3" : "H-1";
  const jamCheckin = new Date(bk.jam_mulai);
  const jamTersisa = (jamCheckin.getTime() - Date.now()) / 3600000;
  const dasarBiaya = bk.payment_status === "paid" ? Number(bk.total || 0) : Number(bk.dp_min || 0);
  if (jamTersisa < 0) return { label: "Hari check-in / lewat", biaya: dasarBiaya, gratis: false };
  if (jamTersisa < batasJam) return { label: `Kurang dari ${batasLabel}`, biaya: Math.round(dasarBiaya * 0.1), gratis: false };
  return { label: `Lebih dari ${batasLabel}`, biaya: 0, gratis: true };
}

function CountdownBebasBiaya({ bk }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 30000); // update tiap 30 detik, cukup untuk granularitas menit
    return () => clearInterval(t);
  }, []);
  const batasJam = batasJamBebasBiaya(bk);
  const batasLabel = bk.tipe === "menginap" ? "H-3" : "H-1";
  const msTersisa = new Date(bk.jam_mulai).getTime() - batasJam * 3600000 - Date.now();
  if (msTersisa <= 0) return null;
  const totalMenit = Math.floor(msTersisa / 60000);
  const hari = Math.floor(totalMenit / 1440);
  const jam = Math.floor((totalMenit % 1440) / 60);
  const menit = totalMenit % 60;
  return (
    <p className="text-xs text-emerald-700" data-testid="batalkan-countdown">
      Waktu tersisa sebelum kena biaya ({batasLabel}): <b>{hari > 0 && `${hari}h `}{jam}j {menit}m</b>
    </p>
  );
}

function BatalkanPesananDialog({ bk, open, onOpenChange, onCancelled }) {
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [hasil, setHasil] = useState(null);
  const policy = calcCancelPolicy(bk);

  const ajukan = async () => {
    setSubmitting(true);
    try {
      const { data } = await PUBLIC_API.post(`/public/bookings/${bk.id}/batalkan`, {});
      setHasil(data);
      setSent(true);
      const { data: updated } = await PUBLIC_API.get(`/public/bookings/${bk.id}`);
      onCancelled?.(updated);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal membatalkan pesanan");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setSent(false); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="batalkan-dialog-title">Batalkan Pesanan {bk.kode}</DialogTitle>
        </DialogHeader>
        {!sent ? (
          <div className="space-y-3 text-sm text-left">
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs space-y-1.5">
              <p className="font-semibold text-slate-700">Kebijakan Pembatalan</p>
              <p className="text-slate-600">
                Gratis jika dibatalkan lebih dari {bk.tipe === "menginap" ? "3 hari (H-3)" : "24 jam (H-1)"} sebelum check-in.
                Kurang dari itu dikenakan biaya 10% dari total tagihan. Tidak ada refund untuk pembatalan di hari check-in atau tidak datang (No Show).
              </p>
            </div>
            <div className="flex justify-between items-center bg-white border border-slate-200 rounded-lg p-3">
              <div>
                <div className="text-xs text-slate-500">Status waktu ini</div>
                <div className="font-semibold" data-testid="batalkan-status-waktu">{policy.label}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-slate-500">Biaya Pembatalan</div>
                <div className={`font-bold ${policy.gratis ? "text-emerald-600" : "text-red-600"}`} data-testid="batalkan-biaya">
                  {policy.gratis ? "Gratis" : fmtRp(policy.biaya)}
                </div>
              </div>
            </div>
            {policy.gratis && <CountdownBebasBiaya bk={bk} />}
          </div>
        ) : (
          <div className="space-y-2 text-sm text-left" data-testid="batalkan-terkirim">
            <p className="text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-3">
              Booking <b>{bk.kode}</b> sudah dibatalkan.
              {hasil?.cancel_fee > 0 ? ` Biaya pembatalan ${fmtRp(hasil.cancel_fee)}.` : " Tidak ada biaya pembatalan."}
              {hasil?.refund_amount > 0 && ` Refund ${fmtRp(hasil.refund_amount)} akan diproses tim kami secara manual.`}
            </p>
          </div>
        )}
        <DialogFooter>
          {!sent ? (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>Tutup</Button>
              <Button data-testid="batalkan-ajukan" onClick={ajukan} disabled={submitting} className="bg-red-600 hover:bg-red-700">
                {submitting ? "Membatalkan…" : "Batalkan Pesanan"}
              </Button>
            </>
          ) : (
            <Button data-testid="batalkan-selesai" onClick={() => onOpenChange(false)} className="bg-teal-deep hover:bg-teal-deep/90">Tutup</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Dialog "Coba Bayar Lagi" — untuk booking yang otomatis dibatalkan karena pembayaran
// expired/gagal (bukan dibatalkan mandiri tamu/staf). Membuka lagi booking (re-cek
// ketersediaan kamar) lalu langsung lanjut ke pembuatan transaksi Tripay baru — dua
// langkah backend (retry-bayar + create-transaction) digabung jadi satu submit supaya
// tidak ada booking "menggantung" di status booking_pending tanpa transaksi aktif.
function RetryBayarDialog({ bk, open, onOpenChange, channels }) {
  const [opsi, setOpsi] = useState("dp50");
  const [method, setMethod] = useState(channels[0]?.code || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const nominal = opsi === "dp50" ? bk.dp_min : bk.total;

  useEffect(() => {
    if (open) { setMethod(channels[0]?.code || ""); setError(""); }
  }, [open, channels]);

  const bayarLagi = async () => {
    if (!method) return;
    setSubmitting(true);
    setError("");
    try {
      await PUBLIC_API.post(`/public/bookings/${bk.id}/retry-bayar`);
      const { data: tx } = await PUBLIC_API.post("/payments/tripay/create-transaction", {
        booking_id: bk.id, payment_option: opsi, method,
      });
      window.location.href = tx.checkout_url;
    } catch (e) {
      setError(e?.response?.data?.detail || "Gagal membuka ulang booking untuk dibayar lagi");
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!submitting) onOpenChange(o); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="retry-bayar-title">Coba Bayar Lagi {bk.kode}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm text-left">
          <p className="text-slate-600 text-xs">Kamar akan dicek ulang ketersediaannya — kalau masih kosong, booking dibuka lagi dan Anda lanjut ke pembayaran.</p>
          <div>
            <Label>Channel Pembayaran</Label>
            <select
              data-testid="retry-channel"
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {channels.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <Label>Metode Bayar</Label>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <button
                type="button"
                data-testid="retry-opsi-dp50"
                onClick={() => setOpsi("dp50")}
                className={`p-2.5 rounded-lg border-2 text-left text-xs ${opsi === "dp50" ? "border-teal-deep bg-teal-deep/8" : "border-slate-200"}`}
              >
                <div className="font-semibold">DP 50%</div>
                <div className="text-slate-500">{fmtRp(bk.dp_min)}</div>
              </button>
              <button
                type="button"
                data-testid="retry-opsi-full"
                onClick={() => setOpsi("full")}
                className={`p-2.5 rounded-lg border-2 text-left text-xs ${opsi === "full" ? "border-teal-deep bg-teal-deep/8" : "border-slate-200"}`}
              >
                <div className="font-semibold">Lunas</div>
                <div className="text-slate-500">{fmtRp(bk.total)}</div>
              </button>
            </div>
          </div>
          <div className="bg-slate-50 border border-slate-200 rounded p-2 flex justify-between">
            <span className="font-bold">Total Ditagih</span><b className="text-teal-deep">{fmtRp(nominal)}</b>
          </div>
          {error && <p className="text-red-600 text-xs" data-testid="retry-error">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>Tutup</Button>
          <Button data-testid="retry-bayar-submit" onClick={bayarLagi} disabled={!method || submitting} className="bg-teal-deep hover:bg-teal-deep/90">
            {submitting ? "Memproses…" : "Bayar Sekarang"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SuccessView({ bookingId: bookingIdFromUrl }) {
  const nav = useNavigate();
  // Fallback kalau URL diakses tanpa :bookingId (mis. tamu menutup tab checkout Tripay lalu
  // balik lewat riwayat browser, bukan lewat return_url yang sudah disisipi ID booking) —
  // pakai booking terakhir yang tersimpan di perangkat ini saat checkout, lalu betulkan URL-nya.
  const [bookingId] = useState(() => bookingIdFromUrl || localStorage.getItem(LAST_BOOKING_ID_KEY));
  const [bk, setBk] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [retryOpen, setRetryOpen] = useState(false);
  const [channels, setChannels] = useState([]);

  useEffect(() => {
    if (!bookingIdFromUrl && bookingId) nav(`/book/sukses/${bookingId}`, { replace: true });
  }, [bookingIdFromUrl, bookingId, nav]);

  useEffect(() => {
    PUBLIC_API.get("/payments/tripay/channels").then(r => setChannels(r.data)).catch(() => setChannels([]));
  }, []);

  useEffect(() => {
    if (!bookingId) { setNotFound(true); return; }
    let stop = false;
    const fetch = () => PUBLIC_API.get(`/public/bookings/${bookingId}`).then((r) => {
      if (stop) return;
      setBk(r.data);
      // hentikan polling begitu status final (paid, atau dibatalkan karena expired/gagal) — tidak akan berubah lagi
      const b = r.data;
      const isTerminal = b.payment_status === "paid" || (b.status === "cancelled" && (b.payment_status === "expired" || b.payment_status === "failed"));
      if (isTerminal) { stop = true; clearInterval(t); }
    }).catch(() => { if (!stop) setNotFound(true); });
    fetch();
    // poll status setiap 5 detik untuk auto-refresh pembayaran
    const t = setInterval(fetch, 5000);
    return () => { stop = true; clearInterval(t); };
  }, [bookingId]);

  if (notFound) {
    return (
      <div className="min-h-screen grid place-items-center p-4 bg-gradient-to-b from-amber-50 via-white to-blue-50">
        <Card className="max-w-md w-full border-amber-200">
          <CardContent className="p-6 sm:p-8 text-center space-y-4">
            <div className="w-16 h-16 mx-auto rounded-full bg-amber-100 grid place-items-center">
              <XCircle className="w-9 h-9 text-amber-600" />
            </div>
            <div>
              <h2 className="text-xl font-extrabold">Detail Booking Tidak Ditemukan</h2>
              <p className="text-slate-600 text-sm mt-1">
                Link ini tidak menyertakan nomor booking yang valid. Cek email/WhatsApp konfirmasi Anda untuk link booking yang benar, atau hubungi CS kami.
              </p>
            </div>
            <a
              href={waLink(CS_WHATSAPP, "Halo, saya butuh bantuan terkait status booking saya.")}
              target="_blank" rel="noreferrer"
              className="inline-flex items-center justify-center gap-2 w-full px-4 h-10 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-bold"
            >
              Hubungi CS via WhatsApp
            </a>
            <Link to="/book" className="block text-sm text-teal-deep hover:underline">Buat booking baru</Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!bk) return <div className="min-h-screen grid place-items-center text-slate-500">Memuat...</div>;
  const isPaid = bk.payment_status === "paid";
  const isFailed = bk.status === "cancelled" && (bk.payment_status === "expired" || bk.payment_status === "failed");
  const isPending = !isFailed && (bk.payment_status === "pending" || bk.status === "booking_pending");
  // status_bayar (belum_bayar/dp/lunas) dari backend — beda dari payment_status mentah
  // yang cuma tahu "paid" (settlement gateway) tanpa peduli itu DP atau bayar penuh.
  const statusBayar = bk.status_bayar || (isPaid ? "lunas" : "belum_bayar");
  const isDp = isPaid && statusBayar === "dp";
  // Kalau booking ini bagian dari grup (>1 kamar dibayar dalam 1 checkout, lihat group_id di
  // public_create_booking), gabungkan angka semua kamar dalam grup untuk ringkasan total.
  const groupRooms = bk.group_bookings || [];
  const isGrouped = groupRooms.length > 0;
  const groupTotal = bk.total + groupRooms.reduce((a, g) => a + (g.total || 0), 0);
  const groupDpMin = bk.dp_min + groupRooms.reduce((a, g) => a + (g.dp_min || 0), 0);
  const groupSisa = (bk.sisa_tagihan || 0) + groupRooms.reduce((a, g) => a + (g.sisa_tagihan || 0), 0);
  return (
    <div className={`min-h-screen grid place-items-center p-4 bg-gradient-to-b print:bg-white print:block print:p-0 ${isPaid ? "from-emerald-50 via-white to-blue-50" : isFailed ? "from-red-50 via-white to-blue-50" : "from-amber-50 via-white to-blue-50"}`}>
      <Card className={`max-w-md w-full print:max-w-none print:shadow-none print:border-0 ${isPaid ? "border-emerald-200" : isFailed ? "border-red-200" : "border-amber-200"}`}>
        <CardContent className="p-6 sm:p-8 text-center space-y-4">
          <div className={`w-16 h-16 mx-auto rounded-full grid place-items-center ${isPaid ? "bg-emerald-100" : isFailed ? "bg-red-100" : "bg-amber-100"}`}>
            {isFailed ? <XCircle className="w-9 h-9 text-red-600" /> : <CheckCircle2 className={`w-9 h-9 ${isPaid ? "text-emerald-600" : "text-amber-600"}`} />}
          </div>
          <div>
            <h2 className="text-2xl font-extrabold">{isDp ? "DP Diterima!" : isPaid ? "Pembayaran Diterima!" : isFailed ? "Booking Dibatalkan" : "Booking Berhasil Dibuat!"}</h2>
            <p className="text-slate-600 text-sm mt-1">
              {isDp
                ? "Booking Anda sudah terkonfirmasi dengan DP. Sisa pembayaran dilunasi saat check-in di lokasi."
                : isPaid
                ? "Booking Anda sudah terkonfirmasi. Simpan nomor booking di bawah."
                : isFailed
                ? "Pembayaran tidak diselesaikan tepat waktu sehingga booking otomatis dibatalkan dan kamar dilepas kembali."
                : "Selesaikan pembayaran agar booking terkonfirmasi. Halaman ini akan auto-refresh setiap 5 detik."}
            </p>
          </div>
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-left space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-slate-500">Nomor Booking</span><b data-testid="pb-success-kode">{bk.kode}</b></div>
            <div className="flex justify-between"><span className="text-slate-500">Nama</span><b>{bk.nama_tamu}</b></div>
            {isGrouped ? (
              <div data-testid="pb-success-group-rooms">
                <div className="flex justify-between"><span className="text-slate-500">Kamar ({1 + groupRooms.length})</span><b>{bk.room_nomor} ({bk.room_tipe})</b></div>
                {groupRooms.map((g) => (
                  <div key={g.id} className="flex justify-between pl-3"><span className="text-slate-400">+</span><b>{g.room_nomor} ({g.room_tipe})</b></div>
                ))}
              </div>
            ) : (
              <div className="flex justify-between"><span className="text-slate-500">Kamar</span><b>{bk.room_nomor} ({bk.room_tipe})</b></div>
            )}
            <div className="flex justify-between"><span className="text-slate-500">Check-In</span><b>{new Date(bk.jam_mulai).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</b></div>
            {bk.jam_selesai && (
              <div className="flex justify-between" data-testid="pb-success-checkout"><span className="text-slate-500">Check-Out</span><b>{new Date(bk.jam_selesai).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</b></div>
            )}
            {bk.dengan_sarapan && (
              <div className="flex justify-between" data-testid="pb-success-sarapan"><span className="text-slate-500">Paket Kamar</span><b>Termasuk Sarapan Pagi{isGrouped ? " (semua kamar)" : ""}</b></div>
            )}
            {bk.extra_bed_qty > 0 && (
              <div className="flex justify-between" data-testid="pb-success-extra-bed"><span className="text-slate-500">Permintaan Khusus</span><b>Extra Bed &times;{bk.extra_bed_qty}{isGrouped ? " / kamar" : ""}</b></div>
            )}
            <div className="flex justify-between border-t pt-2 mt-2"><span className="text-slate-500">Total{isGrouped ? " Semua Kamar" : ""}</span><b className="text-teal-deep">{fmtRp(groupTotal)}</b></div>
            <div className="flex justify-between"><span className="text-slate-500">DP Minimum</span><b>{fmtRp(groupDpMin)}</b></div>
            <div className="flex justify-between"><span className="text-slate-500">Status Pembayaran</span>
              <b data-testid="pb-success-paystatus" className={isDp ? "text-amber-600" : isPaid ? "text-emerald-600" : isFailed ? "text-red-600" : "text-amber-600"}>{STATUS_BAYAR_LABEL[statusBayar] || bk.payment_status?.toUpperCase()}</b>
            </div>
            {isDp && groupSisa > 0 && (
              <div className="flex justify-between" data-testid="pb-success-sisa"><span className="text-slate-500">Sisa Dibayar di Lokasi</span><b className="text-amber-600">{fmtRp(groupSisa)}</b></div>
            )}
          </div>
          {isFailed && (
            <div data-testid="pb-payment-failed" className="bg-red-50 border-2 border-red-300 rounded-lg p-4 text-left text-xs space-y-2">
              <p className="font-bold text-red-900">✕ Kamar Sudah Dilepas Kembali</p>
              <p className="text-red-800">Karena booking ini dibatalkan otomatis, kamar yang tadi dipesan sudah tersedia lagi untuk tamu lain. Kalau masih ingin menginap, coba bayar lagi di bawah (kamar akan dicek ulang) — atau buat reservasi baru kalau kamarnya sudah diambil tamu lain.</p>
            </div>
          )}
          {isFailed && (
            <button
              type="button"
              data-testid="pb-coba-bayar-lagi"
              onClick={() => setRetryOpen(true)}
              className="print:hidden inline-flex items-center justify-center gap-2 w-full px-4 h-11 rounded-md bg-teal-deep hover:bg-teal-deep/90 text-white text-sm font-bold"
            >
              Coba Bayar Lagi
            </button>
          )}
          {isPending && (
            <div className="bg-amber-50 border-2 border-amber-300 rounded-lg p-4 text-left text-xs space-y-2">
              <p className="font-bold text-amber-900">⚠ Pembayaran Belum Selesai</p>
              <p className="text-amber-800">Selesaikan pembayaran sesuai instruksi yang tadi ditampilkan (nomor Virtual Account/QRIS/dll). Saat <b>uang masuk</b>, sistem otomatis update status menjadi PAID.</p>
              <p className="text-amber-700 text-[10px]">
                <b>Untuk testing Sandbox:</b> buka <a className="underline" href="https://tripay.co.id/simulator/console/callback" target="_blank" rel="noreferrer">simulator Tripay</a> untuk simulasikan status pembayaran. Status di halaman ini akan auto-refresh setelah webhook diterima.
              </p>
            </div>
          )}
          {isPaid && (
            <p className="text-xs text-slate-500">
              {isDp
                ? `Mohon tunjukkan nomor booking saat kedatangan dan lunasi sisa ${fmtRp(bk.sisa_tagihan)} di lokasi.`
                : "Mohon tunjukkan nomor booking saat kedatangan."}
            </p>
          )}
          <button
            type="button"
            data-testid="pb-unduh-voucher"
            onClick={() => window.open(`${PUBLIC_API.defaults.baseURL}/public/bookings/${bk.id}/voucher.pdf`, "_blank")}
            className="print:hidden inline-flex items-center justify-center gap-2 w-full px-4 h-10 rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50 text-sm font-medium"
          >
            <Download className="w-4 h-4" /> Unduh Voucher (PDF)
          </button>
          {isPaid && bk.email && (
            <p data-testid="pb-voucher-email-status" className="print:hidden text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-md px-2.5 py-1.5 flex items-center justify-center gap-1.5">
              <Mail className="w-3.5 h-3.5" /> Voucher & bukti booking ini juga akan otomatis terkirim ke <b>{bk.email}</b>
            </p>
          )}
          {bk.no_hp && (
            <a
              data-testid="pb-success-wa"
              href={bookingConfirmationWaLink(bk)}
              target="_blank" rel="noreferrer"
              className="print:hidden inline-flex items-center justify-center gap-2 w-full px-4 h-11 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-bold"
            >
              <CheckCircle2 className="w-4 h-4" /> Konfirmasi via WhatsApp
            </a>
          )}
          {!isFailed && bk.status !== "cancelled" && (
            <button
              type="button"
              data-testid="pb-batalkan-pesanan"
              onClick={() => setCancelOpen(true)}
              className="print:hidden inline-flex items-center justify-center gap-2 w-full px-4 h-10 rounded-md border border-red-300 text-red-600 hover:bg-red-50 text-sm font-medium"
            >
              <Ban className="w-4 h-4" /> Batalkan Pesanan
            </button>
          )}
          <Link to="/book" className="print:hidden block text-sm text-teal-deep hover:underline">Buat booking lain</Link>
        </CardContent>
      </Card>
      <BatalkanPesananDialog bk={bk} open={cancelOpen} onOpenChange={setCancelOpen} onCancelled={setBk} />
      {isFailed && <RetryBayarDialog bk={bk} open={retryOpen} onOpenChange={setRetryOpen} channels={channels} />}
    </div>
  );
}
