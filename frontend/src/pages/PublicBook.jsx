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
import { bookingConfirmationWaLink, waLink } from "@/lib/apiClient";
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
const CS_WHATSAPP = "0895356644644";
const ALAMAT_HOMESTAY = "Jl. Kebun Raya Bedugul, Desa Candikuning, Kec. Baturiti, Tabanan - Bali";
const addDays = (dateStr, n) => {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const todayStr = () => {
  const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function loadSnapScript(snapUrl, clientKey) {
  return new Promise((resolve, reject) => {
    if (window.snap) { resolve(window.snap); return; }
    const s = document.createElement("script");
    s.src = snapUrl;
    s.setAttribute("data-client-key", clientKey);
    s.onload = () => window.snap ? resolve(window.snap) : reject(new Error("Snap not ready"));
    s.onerror = () => reject(new Error("Failed to load Snap.js"));
    document.body.appendChild(s);
  });
}

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
  const [selectedRoom, setSelectedRoom] = useState(null); // {id, nomor, tipe, tarif}
  const [form, setForm] = useState({
    nama_tamu: "", no_hp: "", email: "", no_identitas: "", jumlah_tamu: 1, kendaraan: "",
    jam_checkin: "13:00", catatan: "",
  });
  const [extraBedQty, setExtraBedQty] = useState(0);
  const [denganSarapan, setDenganSarapan] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [paymentOption, setPaymentOption] = useState("dp50"); // dp50 | full
  const nav = useNavigate();

  useEffect(() => {
    PUBLIC_API.get("/public/rooms-catalog").then(r => setCatalog(r.data)).catch(() => {});
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

  const summary = useMemo(() => {
    if (!selectedRoom) return null;
    const isMenginap = bookingTipe === "menginap";
    const breakfastTotal = isMenginap && denganSarapan ? BREAKFAST_PRICE * nights : 0;
    const extraBedTotal = extraBedQty * EXTRA_BED_PRICE * (isMenginap ? nights : 1);
    const tarifDasar = isMenginap ? selectedRoom.tarif_menginap : selectedRoom.tarif;
    const tarifKamar = tarifDasar * (isMenginap ? nights : 1);
    const subtotal = tarifKamar + breakfastTotal + extraBedTotal;
    const svc = Math.round(subtotal * 0.03);
    const total = subtotal + svc;
    return { tarifKamar, breakfastTotal, extraBedTotal, subtotal, service_fee: svc, total, dp_min: Math.round(total * 0.5), nights };
  }, [selectedRoom, extraBedQty, denganSarapan, bookingTipe, nights]);

  const onSelectRoom = (room) => {
    setSelectedRoom(room);
    setExtraBedQty(0);
    setDenganSarapan(false);
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
    if (!selectedRoom) { toast.error("Pilih kamar dulu"); return; }
    setSubmitting(true);
    try {
      // 1. Buat booking
      const { data: bk } = await PUBLIC_API.post("/public/bookings", {
        nama_tamu: form.nama_tamu.trim(),
        no_hp: form.no_hp.trim(),
        email: emailTrimmed,
        no_identitas: form.no_identitas.trim(),
        jumlah_tamu: Number(form.jumlah_tamu) || 1,
        kendaraan: form.kendaraan.trim(),
        room_id: selectedRoom.id,
        tanggal, jam_checkin: form.jam_checkin,
        catatan: form.catatan.trim(),
        extra_bed_qty: extraBedQty,
        tipe: bookingTipe,
        ...(bookingTipe === "menginap" ? { tanggal_checkout: checkoutDate, dengan_sarapan: denganSarapan } : {}),
      });
      // 2. Buat Snap token
      const { data: tx } = await PUBLIC_API.post("/payments/midtrans/create-snap-token", {
        booking_id: bk.id, payment_option: paymentOption,
      });
      // 3. Load Snap.js lazy lalu buka popup
      const { data: cfg } = await PUBLIC_API.get("/payments/midtrans/config");
      const snap = await loadSnapScript(cfg.snap_url, tx.client_key);
      toast.dismiss();
      snap.pay(tx.transaction_token, {
        onSuccess: () => { toast.success("Pembayaran berhasil!"); nav(`/book/sukses/${bk.id}`); },
        onPending: () => { toast.info("Pembayaran pending - selesaikan sesuai instruksi"); nav(`/book/sukses/${bk.id}`); },
        onError: () => { toast.error("Pembayaran gagal - silakan coba lagi"); setSubmitting(false); },
        onClose: () => { toast.warning("Popup pembayaran ditutup. Booking masih PENDING di /book/sukses"); nav(`/book/sukses/${bk.id}`); },
      });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal membuat booking");
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 via-white to-amber-50">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-white/90 backdrop-blur border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-600 to-amber-500 grid place-items-center text-white font-extrabold">P</div>
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Pelangi</div>
              <div className="font-extrabold leading-none">Homestay</div>
            </div>
          </div>
          <Link to="/login" className="text-xs text-slate-500 hover:text-blue-700">Staff Login</Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-10 space-y-8">
        {/* Hero */}
        <section className="text-center space-y-3">
          <p className="text-xs uppercase tracking-[0.3em] text-amber-700">Reservasi Online</p>
          <h1 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-slate-900">
            Istirahat Sejenak di<br className="hidden sm:block" /> Sejuknya Bedugul
          </h1>
          <p className="text-slate-600 max-w-xl mx-auto">
            Day use untuk singgah sejenak, atau menginap menikmati udara pegunungan lebih lama —
            harga jujur, konfirmasi instan. Pilih tanggal, pilih kamar, selesai.
          </p>
        </section>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-2 text-xs">
          <StepDot active={step >= 1} done={step > 1} label="Pilih Kamar" />
          <div className="w-6 h-px bg-slate-300" />
          <StepDot active={step >= 2} done={false} label="Isi Data & Bayar" />
        </div>

        {step === 1 && (
          <>
            {/* Date picker */}
            <Card className="border-slate-200 shadow-sm">
              <CardContent className="p-4 sm:p-5 space-y-4">
                <div>
                  <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5 block">Jenis Kunjungan</Label>
                  <div className="flex gap-2">
                    <Button data-testid="pb-booking-tipe-dayuse" type="button" variant={bookingTipe === "day_use" ? "default" : "outline"} className={bookingTipe === "day_use" ? "h-12 flex-1 bg-blue-700" : "h-12 flex-1"} onClick={() => setBookingTipe("day_use")}>Day Use</Button>
                    <Button data-testid="pb-booking-tipe-menginap" type="button" variant={bookingTipe === "menginap" ? "default" : "outline"} className={bookingTipe === "menginap" ? "h-12 flex-1 bg-blue-700" : "h-12 flex-1"} onClick={() => setBookingTipe("menginap")}>Menginap</Button>
                  </div>
                </div>
                <div className="grid sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
                  <div>
                    <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500">{bookingTipe === "menginap" ? "Tanggal Check-In" : "Tanggal Kunjungan"}</Label>
                    <Input data-testid="pb-tanggal" type="date" value={tanggal} min={todayStr()} onChange={(e) => setTanggal(e.target.value)} className="h-12 mt-1.5 text-base" />
                  </div>
                  {bookingTipe === "menginap" && (
                    <div>
                      <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Tanggal Check-Out</Label>
                      <Input data-testid="pb-tanggal-checkout" type="date" value={checkoutDate} min={addDays(tanggal, 1)} onChange={(e) => setCheckoutDate(e.target.value)} className="h-12 mt-1.5 text-base" />
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button data-testid="pb-tipe-all" type="button" variant={tipe === "" ? "default" : "outline"} className={tipe === "" ? "h-12 bg-blue-700" : "h-12"} onClick={() => setTipe("")}>Semua</Button>
                    <Button data-testid="pb-tipe-std" type="button" variant={tipe === "Standard" ? "default" : "outline"} className={tipe === "Standard" ? "h-12 bg-blue-700" : "h-12"} onClick={() => setTipe("Standard")}>Standard</Button>
                    <Button data-testid="pb-tipe-cot" type="button" variant={tipe === "Cottage" ? "default" : "outline"} className={tipe === "Cottage" ? "h-12 bg-amber-600" : "h-12"} onClick={() => setTipe("Cottage")}>Cottage</Button>
                  </div>
                </div>
                {bookingTipe === "menginap" && (
                  <p className="text-xs text-slate-500">{nights} malam &middot; Check-out jam 12:00 siang</p>
                )}
              </CardContent>
            </Card>

            {/* Catalog (per tipe dengan foto + fasilitas) */}
            <div className="grid sm:grid-cols-2 gap-4 sm:gap-6">
              {catalog.map((c) => {
                const availOfTipe = availability.rooms.filter(r => r.tipe === c.tipe);
                return (
                  <Card key={c.tipe} data-testid={`pb-catalog-${c.tipe}`} className="border-slate-200 overflow-hidden shadow-md hover:shadow-lg transition-shadow">
                    <CardContent className="p-5 space-y-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-wider text-slate-500">Kamar</div>
                          <h3 className="text-xl font-extrabold">{c.tipe}</h3>
                        </div>
                        <div className="text-right">
                          <div className="text-2xl font-extrabold text-blue-700">{fmtRp(bookingTipe === "menginap" ? c.tarif_menginap : c.tarif)}</div>
                          <div className="text-[10px] uppercase tracking-wider text-slate-500">{bookingTipe === "menginap" ? "/ malam" : "/ 6 jam"}</div>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {c.fasilitas.map((f) => {
                          const Ico = FACILITY_ICONS[f] || CheckCircle2;
                          return (
                            <span key={f} className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-full bg-slate-100 text-slate-700">
                              <Ico className="w-3 h-3" /> {f}
                            </span>
                          );
                        })}
                      </div>
                      <div className="pt-2 border-t border-slate-100">
                        <div className="text-xs text-slate-500 mb-2">
                          {availOfTipe.length > 0 ? `${availOfTipe.length} kamar tersedia` : "Kamar habis di tanggal ini"}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {availOfTipe.length === 0 && (
                            <span className="text-xs text-red-600">Coba pilih tanggal lain</span>
                          )}
                          {availOfTipe.map((r) => (
                            <button
                              key={r.id}
                              data-testid={`pb-room-${r.nomor}`}
                              onClick={() => onSelectRoom(r)}
                              className="px-3 py-1.5 text-xs font-bold border-2 border-blue-200 hover:border-blue-600 hover:bg-blue-50 rounded-md transition-colors"
                            >
                              Kamar {r.nomor}
                            </button>
                          ))}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
              {catalog.length === 0 && (
                <div className="col-span-full text-center text-slate-500 py-10">Memuat katalog...</div>
              )}
            </div>
          </>
        )}

        {step === 2 && selectedRoom && summary && (
          <div className="grid md:grid-cols-[1fr_360px] gap-6">
            {/* Form */}
            <Card className="border-slate-200">
              <CardContent className="p-5 sm:p-6 space-y-4">
                <button onClick={() => setStep(1)} className="text-sm text-blue-700 hover:underline">&larr; Pilih kamar lain</button>
                <h2 className="text-2xl font-extrabold">Data Tamu</h2>
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
                  <p className="mt-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-2.5 py-1.5">
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
                    <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5 block">Paket Kamar</Label>
                    <button
                      type="button"
                      data-testid="pb-sarapan-toggle"
                      onClick={() => setDenganSarapan((v) => !v)}
                      className={`w-full flex items-center justify-between border rounded-lg p-3 text-left transition-colors ${denganSarapan ? "border-blue-600 bg-blue-50" : "border-slate-200 hover:border-slate-300"}`}
                    >
                      <div>
                        <div className="font-medium text-sm">Sarapan Pagi</div>
                        <div className="text-xs text-slate-500">{fmtRp(BREAKFAST_PRICE)} / malam per kamar (opsional)</div>
                      </div>
                      <div className={`w-5 h-5 rounded border-2 grid place-items-center shrink-0 ${denganSarapan ? "border-blue-600 bg-blue-600" : "border-slate-300"}`}>
                        {denganSarapan && <CheckCircle2 className="w-3.5 h-3.5 text-white" />}
                      </div>
                    </button>
                  </div>
                )}
                <div>
                  <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5 block">Permintaan Khusus</Label>
                  <ExtraBedSelector value={extraBedQty} onChange={setExtraBedQty} max={EXTRA_BED_MAX} harga={EXTRA_BED_PRICE} satuan="pemesanan" />
                </div>
                <div>
                  <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Catatan (opsional)</Label>
                  <Textarea data-testid="pb-catatan" value={form.catatan} onChange={(e) => setForm(f => ({ ...f, catatan: e.target.value }))} className="mt-1.5" rows={3} placeholder="Mis: request lantai bawah, late check-in, dll" />
                </div>
              </CardContent>
            </Card>

            {/* Summary sidebar */}
            <Card className="border-slate-200 h-fit md:sticky md:top-20">
              <CardContent className="p-5 space-y-4">
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500">Booking Anda</div>
                  <div className="font-extrabold text-lg">{selectedRoom.tipe} • Kamar {selectedRoom.nomor}</div>
                </div>
                <div className="space-y-2 text-sm border-t border-slate-100 pt-3">
                  <Row icon={Calendar} label="Check-In" value={new Date(`${tanggal}T00:00:00`).toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "long", year: "numeric" })} />
                  {bookingTipe === "menginap" ? (
                    <>
                      <Row icon={Calendar} label="Check-Out" value={new Date(`${checkoutDate}T00:00:00`).toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "long", year: "numeric" })} />
                      <Row icon={Clock} label="Lama Menginap" value={`${summary.nights} malam`} />
                    </>
                  ) : (
                    <Row icon={Clock} label="Jam Check-In" value={`${form.jam_checkin} (6 jam)`} />
                  )}
                  <Row icon={Building2} label="Tipe" value={selectedRoom.tipe} />
                </div>
                <div className="space-y-1.5 border-t border-slate-100 pt-3 text-sm">
                  <div className="flex justify-between"><span className="text-slate-600">Tarif Kamar{bookingTipe === "menginap" ? ` × ${summary.nights} malam` : ""}</span><b>{fmtRp(summary.tarifKamar)}</b></div>
                  {summary.breakfastTotal > 0 && (
                    <div className="flex justify-between" data-testid="pb-breakfast-fee"><span className="text-slate-600">Sarapan Pagi × {summary.nights} malam</span><b>{fmtRp(summary.breakfastTotal)}</b></div>
                  )}
                  {extraBedQty > 0 && (
                    <div className="flex justify-between" data-testid="pb-extra-bed-fee"><span className="text-slate-600">Extra Bed &times;{extraBedQty}</span><b>{fmtRp(summary.extraBedTotal)}</b></div>
                  )}
                  <div className="flex justify-between"><span className="text-slate-600">Service Fee (3%)</span><b data-testid="pb-service-fee">{fmtRp(summary.service_fee)}</b></div>
                  <div className="flex justify-between text-base pt-1.5 border-t border-slate-200 mt-1.5"><span className="font-bold">Total</span><b className="text-blue-700" data-testid="pb-total">{fmtRp(summary.total)}</b></div>
                </div>
                <div className="border-t border-slate-100 pt-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Opsi Pembayaran</Label>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <button data-testid="pb-pay-dp50" type="button" onClick={() => setPaymentOption("dp50")} className={`p-3 rounded-lg border-2 text-left transition-colors ${paymentOption === "dp50" ? "border-blue-600 bg-blue-50" : "border-slate-200 hover:border-slate-300"}`}>
                      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">DP 50%</div>
                      <div className="font-extrabold text-blue-700" data-testid="pb-dp">{fmtRp(summary.dp_min)}</div>
                      <div className="text-[10px] text-slate-500">Sisa di lokasi</div>
                    </button>
                    <button data-testid="pb-pay-full" type="button" onClick={() => setPaymentOption("full")} className={`p-3 rounded-lg border-2 text-left transition-colors ${paymentOption === "full" ? "border-blue-600 bg-blue-50" : "border-slate-200 hover:border-slate-300"}`}>
                      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Bayar Penuh</div>
                      <div className="font-extrabold text-blue-700">{fmtRp(summary.total)}</div>
                      <div className="text-[10px] text-slate-500">Tanpa sisa</div>
                    </button>
                  </div>
                </div>
                <Button data-testid="pb-submit" disabled={submitting} onClick={submit} className="w-full h-12 bg-gradient-to-r from-blue-700 to-blue-600 hover:from-blue-800 hover:to-blue-700 text-base font-bold">
                  {submitting ? "Memproses..." : "Bayar Sekarang"} <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
                <p className="text-[10px] text-center text-slate-500">
                  Dengan menekan tombol, Anda menyetujui kebijakan reservasi.
                  Pembatalan gratis sampai {bookingTipe === "menginap" ? "H-3" : "H-1"} sebelum check-in, setelah itu dikenakan biaya 10% dari total pembayaran.
                </p>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Footer info */}
        <footer className="text-center text-xs text-slate-500 pt-8 border-t border-slate-200 space-y-2">
          <p>Pelangi Homestay &middot; Bersantai di kaki Bedugul, Bali</p>
          <p className="max-w-md mx-auto">{ALAMAT_HOMESTAY}</p>
          <a
            href={waLink(CS_WHATSAPP, "Halo, saya ingin bertanya tentang booking di Pelangi Homestay.")}
            target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-emerald-700 hover:text-emerald-800 font-semibold"
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
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full ${active ? "bg-blue-700 text-white" : "bg-slate-200 text-slate-600"}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      <span className="font-semibold">{label}</span>
      {done && <CheckCircle2 className="w-3 h-3" />}
    </div>
  );
}

function FieldIcon({ icon: Icon, label, children }) {
  return (
    <div>
      <Label className="text-xs font-semibold uppercase tracking-wider text-slate-500 inline-flex items-center gap-1.5"><Icon className="w-3 h-3" /> {label}</Label>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

function Row({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="inline-flex items-center gap-1.5 text-slate-600"><Icon className="w-3.5 h-3.5" /> {label}</span>
      <b className="text-right">{value}</b>
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
            <Button data-testid="batalkan-selesai" onClick={() => onOpenChange(false)} className="bg-blue-700 hover:bg-blue-800">Tutup</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SuccessView({ bookingId }) {
  const [bk, setBk] = useState(null);
  const [banks, setBanks] = useState(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  useEffect(() => {
    let stop = false;
    const fetch = () => PUBLIC_API.get(`/public/bookings/${bookingId}`).then((r) => {
      if (stop) return;
      setBk(r.data);
      // hentikan polling begitu status final (paid, atau dibatalkan karena expired/gagal) — tidak akan berubah lagi
      const b = r.data;
      const isTerminal = b.payment_status === "paid" || (b.status === "cancelled" && (b.payment_status === "expired" || b.payment_status === "failed"));
      if (isTerminal) { stop = true; clearInterval(t); }
    }).catch(() => {});
    fetch();
    PUBLIC_API.get(`/public/bank-accounts`).then(r => setBanks(r.data)).catch(() => {});
    // poll status setiap 5 detik untuk auto-refresh pembayaran
    const t = setInterval(fetch, 5000);
    return () => { stop = true; clearInterval(t); };
  }, [bookingId]);

  if (!bk) return <div className="min-h-screen grid place-items-center text-slate-500">Memuat...</div>;
  const isPaid = bk.payment_status === "paid";
  const isFailed = bk.status === "cancelled" && (bk.payment_status === "expired" || bk.payment_status === "failed");
  const isPending = !isFailed && (bk.payment_status === "pending" || bk.status === "booking_pending");
  return (
    <div className={`min-h-screen grid place-items-center p-4 bg-gradient-to-b print:bg-white print:block print:p-0 ${isPaid ? "from-emerald-50 via-white to-blue-50" : isFailed ? "from-red-50 via-white to-blue-50" : "from-amber-50 via-white to-blue-50"}`}>
      <Card className={`max-w-md w-full print:max-w-none print:shadow-none print:border-0 ${isPaid ? "border-emerald-200" : isFailed ? "border-red-200" : "border-amber-200"}`}>
        <CardContent className="p-6 sm:p-8 text-center space-y-4">
          <div className={`w-16 h-16 mx-auto rounded-full grid place-items-center ${isPaid ? "bg-emerald-100" : isFailed ? "bg-red-100" : "bg-amber-100"}`}>
            {isFailed ? <XCircle className="w-9 h-9 text-red-600" /> : <CheckCircle2 className={`w-9 h-9 ${isPaid ? "text-emerald-600" : "text-amber-600"}`} />}
          </div>
          <div>
            <h2 className="text-2xl font-extrabold">{isPaid ? "Pembayaran Diterima!" : isFailed ? "Booking Dibatalkan" : "Booking Berhasil Dibuat!"}</h2>
            <p className="text-slate-600 text-sm mt-1">
              {isPaid
                ? "Booking Anda sudah terkonfirmasi. Simpan nomor booking di bawah."
                : isFailed
                ? "Pembayaran tidak diselesaikan tepat waktu sehingga booking otomatis dibatalkan dan kamar dilepas kembali."
                : "Selesaikan pembayaran agar booking terkonfirmasi. Halaman ini akan auto-refresh setiap 5 detik."}
            </p>
          </div>
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-left space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-slate-500">Nomor Booking</span><b data-testid="pb-success-kode">{bk.kode}</b></div>
            <div className="flex justify-between"><span className="text-slate-500">Nama</span><b>{bk.nama_tamu}</b></div>
            <div className="flex justify-between"><span className="text-slate-500">Kamar</span><b>{bk.room_nomor} ({bk.room_tipe})</b></div>
            <div className="flex justify-between"><span className="text-slate-500">Check-In</span><b>{new Date(bk.jam_mulai).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</b></div>
            {bk.jam_selesai && (
              <div className="flex justify-between" data-testid="pb-success-checkout"><span className="text-slate-500">Check-Out</span><b>{new Date(bk.jam_selesai).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</b></div>
            )}
            {bk.dengan_sarapan && (
              <div className="flex justify-between" data-testid="pb-success-sarapan"><span className="text-slate-500">Paket Kamar</span><b>Termasuk Sarapan Pagi</b></div>
            )}
            {bk.extra_bed_qty > 0 && (
              <div className="flex justify-between" data-testid="pb-success-extra-bed"><span className="text-slate-500">Permintaan Khusus</span><b>Extra Bed &times;{bk.extra_bed_qty}</b></div>
            )}
            <div className="flex justify-between border-t pt-2 mt-2"><span className="text-slate-500">Total</span><b className="text-blue-700">{fmtRp(bk.total)}</b></div>
            <div className="flex justify-between"><span className="text-slate-500">DP Minimum</span><b>{fmtRp(bk.dp_min)}</b></div>
            <div className="flex justify-between"><span className="text-slate-500">Status Pembayaran</span>
              <b data-testid="pb-success-paystatus" className={isPaid ? "text-emerald-600" : isFailed ? "text-red-600" : "text-amber-600"}>{bk.payment_status?.toUpperCase()}</b>
            </div>
          </div>
          {isFailed && (
            <div data-testid="pb-payment-failed" className="bg-red-50 border-2 border-red-300 rounded-lg p-4 text-left text-xs space-y-2">
              <p className="font-bold text-red-900">✕ Kamar Sudah Dilepas Kembali</p>
              <p className="text-red-800">Karena booking ini dibatalkan otomatis, kamar yang tadi dipesan sudah tersedia lagi untuk tamu lain. Silakan buat reservasi baru di bawah jika masih ingin menginap.</p>
            </div>
          )}
          {isPending && (
            <div className="bg-amber-50 border-2 border-amber-300 rounded-lg p-4 text-left text-xs space-y-2">
              <p className="font-bold text-amber-900">⚠ Pembayaran Belum Selesai</p>
              <p className="text-amber-800">Jika Anda memilih <b>Virtual Account</b>, pastikan untuk benar-benar transfer ke nomor VA yang ditampilkan di Snap. Saat <b>uang masuk</b>, sistem otomatis update status menjadi PAID.</p>
              <p className="text-amber-700 text-[10px]">
                <b>Untuk testing Sandbox:</b> buka <a className="underline" href="https://simulator.sandbox.midtrans.com" target="_blank" rel="noreferrer">simulator.sandbox.midtrans.com</a>, pilih bank yang sama, paste VA Number, klik Inquiry → Pay. Status di halaman ini akan auto-refresh setelah webhook diterima.
              </p>
            </div>
          )}
          {isPending && banks?.accounts && (
            <div data-testid="pb-manual-transfer" className="bg-blue-50 border-2 border-blue-300 rounded-lg p-4 text-left text-xs space-y-3">
              <p className="font-bold text-blue-900">💳 Alternatif: Transfer Manual ke Rekening</p>
              <p className="text-blue-800 text-[11px]">Transfer minimum DP <b>{fmtRp(bk.dp_min)}</b> atau full <b>{fmtRp(bk.total)}</b> ke salah satu rekening:</p>
              <div className="space-y-2">
                {banks.accounts.map((acc, i) => (
                  <div key={i} className="bg-white rounded-md p-2 border border-blue-200" data-testid={`pb-bank-${acc.bank}`}>
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-blue-900">{acc.bank}</span>
                      <button
                        onClick={() => { navigator.clipboard.writeText(acc.nomor); toast.success("Nomor rekening disalin"); }}
                        className="text-[10px] px-2 py-0.5 bg-blue-100 hover:bg-blue-200 rounded text-blue-800"
                      >Salin</button>
                    </div>
                    <div className="font-mono text-sm text-slate-800">{acc.nomor}</div>
                    <div className="text-[10px] text-slate-500">a.n. {acc.atas_nama}</div>
                  </div>
                ))}
              </div>
              <p className="text-blue-700 text-[10px]">{banks.instruksi}</p>
              <a
                data-testid="pb-wa-konfirmasi-manual"
                href={`https://wa.me/${bk.no_hp.replace(/^0/, "62").replace(/\D/g, "")}?text=${encodeURIComponent(`Halo, saya sudah transfer untuk booking *${bk.kode}* sebesar Rp ${(bk.dp_min || bk.total).toLocaleString("id-ID")}. Mohon verifikasi pembayaran saya. Terima kasih.`)}`}
                target="_blank" rel="noreferrer"
                className="block w-full text-center px-3 h-10 leading-10 rounded-md bg-blue-700 hover:bg-blue-800 text-white text-xs font-bold print:hidden"
              >
                Saya Sudah Transfer — Minta Verifikasi via WhatsApp
              </a>
            </div>
          )}
          {isPaid && (
            <p className="text-xs text-slate-500">Mohon tunjukkan nomor booking saat kedatangan.</p>
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
          <Link to="/book" className="print:hidden block text-sm text-blue-700 hover:underline">Buat booking lain</Link>
        </CardContent>
      </Card>
      <BatalkanPesananDialog bk={bk} open={cancelOpen} onOpenChange={setCancelOpen} onCancelled={setBk} />
    </div>
  );
}
