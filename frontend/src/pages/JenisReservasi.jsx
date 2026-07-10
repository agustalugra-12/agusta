import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Clock, CalendarRange, Minus, Plus, Info, AlertCircle } from "lucide-react";
import { fmtRp } from "@/lib/apiClient";

// Tarif kamar nyata (sama seperti seed di server.py), dipakai supaya demo total harga
// realistis meski form ini masih demo/tidak tersambung ke booking sungguhan.
const ROOM_RATES = { Standard: 120000, Cottage: 140000 };
const todayStr = () => new Date().toISOString().slice(0, 10);
const isTanggalLampau = (tanggal) => tanggal < todayStr();
const isJumlahTamuValid = (jumlahTamu) => Number(jumlahTamu) >= 1;

function FormReservasiMenginap() {
  const [tanggalCheckin, setTanggalCheckin] = useState(todayStr());
  const [malam, setMalam] = useState(1);
  const [tipeKamar, setTipeKamar] = useState("Standard");
  const [jumlahTamu, setJumlahTamu] = useState(2);

  const checkinDate = new Date(`${tanggalCheckin}T14:00:00`);
  const checkoutDate = new Date(checkinDate.getTime() + malam * 86400000);
  const total = ROOM_RATES[tipeKamar] * malam;

  return (
    <Card className="border-blue-200 bg-blue-50/30" data-testid="form-reservasi-menginap">
      <CardContent className="p-4 space-y-4">
        <h3 className="text-sm font-semibold text-slate-700">Form Reservasi Menginap (Demo)</h3>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <Label htmlFor="menginap-tanggal">Tanggal Check-In</Label>
            <Input
              id="menginap-tanggal" data-testid="menginap-tanggal-checkin" type="date" value={tanggalCheckin}
              onChange={(e) => setTanggalCheckin(e.target.value)}
              className={`mt-1.5 ${isTanggalLampau(tanggalCheckin) ? "border-red-400 focus-visible:ring-red-400" : ""}`}
            />
            {isTanggalLampau(tanggalCheckin) && (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1" data-testid="menginap-tanggal-error"><AlertCircle className="w-3 h-3" /> Tanggal tidak boleh sebelum hari ini</p>
            )}
          </div>
          <div>
            <Label htmlFor="menginap-tipe">Tipe Kamar</Label>
            <select
              id="menginap-tipe"
              data-testid="menginap-tipe-kamar"
              value={tipeKamar}
              onChange={(e) => setTipeKamar(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {Object.keys(ROOM_RATES).map((t) => <option key={t} value={t}>{t} ({fmtRp(ROOM_RATES[t])}/malam)</option>)}
            </select>
          </div>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <Label>Jumlah Malam</Label>
            <div className="flex items-center gap-3 mt-1.5">
              <Button type="button" variant="outline" size="icon" data-testid="menginap-malam-kurang" onClick={() => setMalam((n) => Math.max(1, n - 1))} disabled={malam <= 1}>
                <Minus className="w-3.5 h-3.5" />
              </Button>
              <span className="w-6 text-center font-semibold" data-testid="menginap-malam-value">{malam}</span>
              <Button type="button" variant="outline" size="icon" data-testid="menginap-malam-tambah" onClick={() => setMalam((n) => Math.min(30, n + 1))}>
                <Plus className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
          <div>
            <Label htmlFor="menginap-tamu">Jumlah Tamu</Label>
            <Input
              id="menginap-tamu" data-testid="menginap-jumlah-tamu" type="number" min={1} value={jumlahTamu}
              onChange={(e) => setJumlahTamu(e.target.value)}
              className={`mt-1.5 ${!isJumlahTamuValid(jumlahTamu) ? "border-red-400 focus-visible:ring-red-400" : ""}`}
            />
            {!isJumlahTamuValid(jumlahTamu) && (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1" data-testid="menginap-tamu-error"><AlertCircle className="w-3 h-3" /> Minimal 1 tamu</p>
            )}
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-3 space-y-1.5 text-sm" data-testid="menginap-ringkasan">
          <div className="flex justify-between"><span className="text-slate-500">Check-In</span><span>{checkinDate.toLocaleDateString("id-ID", { dateStyle: "medium" })}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Check-Out</span><span>{checkoutDate.toLocaleDateString("id-ID", { dateStyle: "medium" })}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">{tipeKamar} &times; {malam} malam</span><span>{fmtRp(total)}</span></div>
          <div className="flex justify-between border-t border-slate-200 pt-1.5 mt-1.5">
            <span className="font-bold">Total</span><b className="text-blue-700" data-testid="menginap-total">{fmtRp(total)}</b>
          </div>
        </div>
        <p className="text-[11px] text-slate-400">Data tiruan — form demo ini belum membuat reservasi sungguhan.</p>
      </CardContent>
    </Card>
  );
}

// Service fee 3% sama seperti SERVICE_FEE_PCT di backend/core.py (dipakai juga di
// PublicBook.jsx sungguhan) — day use tarifnya flat per kamar (bukan per jam), durasi
// default 6 jam, overtime dihitung saat checkout bukan saat booking.
const SERVICE_FEE_PCT = 0.03;
const DAY_USE_DURATION_HOURS = 6;

function FormReservasiDayUse() {
  const [tanggal, setTanggal] = useState(todayStr());
  const [jamCheckin, setJamCheckin] = useState("14:00");
  const [tipeKamar, setTipeKamar] = useState("Standard");
  const [jumlahTamu, setJumlahTamu] = useState(2);

  const checkinDate = new Date(`${tanggal}T${jamCheckin}:00`);
  const checkoutDate = new Date(checkinDate.getTime() + DAY_USE_DURATION_HOURS * 3600000);
  const subtotal = ROOM_RATES[tipeKamar];
  const serviceFee = Math.round(subtotal * SERVICE_FEE_PCT);
  const total = subtotal + serviceFee;

  return (
    <Card className="border-orange-200 bg-orange-50/30" data-testid="form-reservasi-dayuse">
      <CardContent className="p-4 space-y-4">
        <h3 className="text-sm font-semibold text-slate-700">Form Reservasi Day Use (Demo)</h3>
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex gap-2 text-xs" data-testid="dayuse-ketentuan">
          <Info className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-amber-800">
            Durasi Day Use standar <b>6 jam</b> dari jam check-in. Kelebihan waktu dikenakan biaya overtime <b>{fmtRp(20000)}/jam</b>, dihitung saat check-out (bukan di muka).
          </p>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <Label htmlFor="dayuse-tanggal">Tanggal</Label>
            <Input
              id="dayuse-tanggal" data-testid="dayuse-tanggal" type="date" value={tanggal}
              onChange={(e) => setTanggal(e.target.value)}
              className={`mt-1.5 ${isTanggalLampau(tanggal) ? "border-red-400 focus-visible:ring-red-400" : ""}`}
            />
            {isTanggalLampau(tanggal) && (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1" data-testid="dayuse-tanggal-error"><AlertCircle className="w-3 h-3" /> Tanggal tidak boleh sebelum hari ini</p>
            )}
          </div>
          <div>
            <Label htmlFor="dayuse-jam">Jam Check-In</Label>
            <Input id="dayuse-jam" data-testid="dayuse-jam-checkin" type="time" value={jamCheckin} onChange={(e) => setJamCheckin(e.target.value)} className="mt-1.5" />
          </div>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <Label htmlFor="dayuse-tipe">Tipe Kamar</Label>
            <select
              id="dayuse-tipe"
              data-testid="dayuse-tipe-kamar"
              value={tipeKamar}
              onChange={(e) => setTipeKamar(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {Object.keys(ROOM_RATES).map((t) => <option key={t} value={t}>{t} ({fmtRp(ROOM_RATES[t])})</option>)}
            </select>
          </div>
          <div>
            <Label htmlFor="dayuse-tamu">Jumlah Tamu</Label>
            <Input
              id="dayuse-tamu" data-testid="dayuse-jumlah-tamu" type="number" min={1} value={jumlahTamu}
              onChange={(e) => setJumlahTamu(e.target.value)}
              className={`mt-1.5 ${!isJumlahTamuValid(jumlahTamu) ? "border-red-400 focus-visible:ring-red-400" : ""}`}
            />
            {!isJumlahTamuValid(jumlahTamu) && (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1" data-testid="dayuse-tamu-error"><AlertCircle className="w-3 h-3" /> Minimal 1 tamu</p>
            )}
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-3 space-y-1.5 text-sm" data-testid="dayuse-ringkasan">
          <div className="flex justify-between"><span className="text-slate-500">Check-In</span><span>{checkinDate.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Estimasi Selesai (6 jam)</span><span>{checkoutDate.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Tarif {tipeKamar}</span><span>{fmtRp(subtotal)}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Biaya Layanan (3%)</span><span>{fmtRp(serviceFee)}</span></div>
          <div className="flex justify-between border-t border-slate-200 pt-1.5 mt-1.5">
            <span className="font-bold">Total</span><b className="text-blue-700" data-testid="dayuse-total">{fmtRp(total)}</b>
          </div>
        </div>
        <p className="text-[11px] text-slate-400">Data tiruan — form demo ini belum membuat reservasi sungguhan.</p>
      </CardContent>
    </Card>
  );
}

// Komponen pemilih tipe reservasi (Day Use / Menginap) — gaya warna (oranye Day Use, biru
// Menginap) disamakan dengan yang sudah dipakai di form staf Bookings.jsx supaya konsisten.
// Belum diintegrasikan ke form booking publik (PublicBook.jsx) — itu saat ini cuma
// mendukung day_use, memperluasnya ke menginap adalah perubahan alur booking tamu yang
// lebih besar (perlu penyesuaian ketersediaan/harga multi-malam), disusul task terpisah.
export function TipeReservasiSelector({ value, onChange }) {
  return (
    <div className="grid grid-cols-2 gap-2" data-testid="tipe-reservasi-selector">
      <Button
        type="button"
        variant={value === "day_use" ? "default" : "outline"}
        className={`gap-1.5 h-12 ${value === "day_use" ? "bg-orange-500 hover:bg-orange-600" : ""}`}
        onClick={() => onChange("day_use")}
        data-testid="tipe-reservasi-dayuse"
      >
        <Clock className="w-4 h-4" /> Day Use
      </Button>
      <Button
        type="button"
        variant={value === "menginap" ? "default" : "outline"}
        className={`gap-1.5 h-12 ${value === "menginap" ? "bg-blue-700 hover:bg-blue-800" : ""}`}
        onClick={() => onChange("menginap")}
        data-testid="tipe-reservasi-menginap"
      >
        <CalendarRange className="w-4 h-4" /> Menginap
      </Button>
    </div>
  );
}

export default function JenisReservasi() {
  const [tipe, setTipe] = useState("day_use");

  return (
    <div className="space-y-6" data-testid="jenis-reservasi-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Jenis Reservasi</h1>
        <p className="text-slate-500 mt-1">
          Pratinjau komponen pemilih tipe reservasi — belum tersambung ke form booking tamu sungguhan.
        </p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Pratinjau Komponen</h3>
          <TipeReservasiSelector value={tipe} onChange={setTipe} />
          <p className="text-sm text-slate-600" data-testid="tipe-reservasi-keterangan">
            {tipe === "day_use"
              ? "Day Use: menginap beberapa jam saja (default 6 jam), tanpa bermalam."
              : "Menginap: check-in sampai check-out di hari berikutnya (bermalam)."}
          </p>
          <p className="text-[11px] text-slate-400">Data tiruan — form booking tamu saat ini masih selalu Day Use.</p>
        </CardContent>
      </Card>

      {tipe === "day_use" ? <FormReservasiDayUse /> : <FormReservasiMenginap />}
    </div>
  );
}
