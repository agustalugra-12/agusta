import { useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sparkles, Clock, AlertTriangle, CheckCircle2 } from "lucide-react";

const todayStr = () => new Date().toISOString().slice(0, 10);

// Aturan jam check-in Day Use per hari (sama dengan JenisReservasi.jsx): khusus Minggu
// paling awal jam 12:00, Senin-Sabtu jam 10:00.
function jamCheckinPalingAwal(tanggal) {
  const hari = new Date(`${tanggal}T00:00:00`).getDay();
  return hari === 0 ? "12:00" : "10:00";
}

const CLEANING_BUFFER_JAM = 1;

// Data tiruan (stub) — simulasi kamar yang malam sebelumnya dipakai tamu Menginap dan jam
// check-out mereka (null = kamar sudah kosong sejak sebelumnya, tidak perlu jeda bersih-bersih).
// Di dunia nyata ini akan query booking tipe "menginap" yang jam_selesai jatuh pada H-1.
const MOCK_ROOM_STATUS = {
  Standard: [
    { nomor: "1", checkout_malam_sebelumnya: null },
    { nomor: "5", checkout_malam_sebelumnya: "12:00" },
    { nomor: "9", checkout_malam_sebelumnya: "11:00" },
  ],
  Cottage: [
    { nomor: "14", checkout_malam_sebelumnya: "12:00" },
  ],
};

// Tanggal contoh untuk memperagakan skenario "penuh" (semua kamar tipe ini sudah terisi
// Day Use lain di jam-jam awal) — demi menunjukkan alur rekomendasi alternatif.
const TANGGAL_DEMO_PENUH = { tipe: "Cottage", tanggal: "2026-07-12" };

function jamTambah(jam, tambahJam) {
  const [h, m] = jam.split(":").map(Number);
  const total = h * 60 + m + tambahJam * 60;
  const hh = Math.floor(total / 60) % 24;
  const mm = total % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

function hitungRekomendasi(tipeKamar, tanggal) {
  const batasAwal = jamCheckinPalingAwal(tanggal);
  const rooms = MOCK_ROOM_STATUS[tipeKamar] || [];
  const isPenuh = tipeKamar === TANGGAL_DEMO_PENUH.tipe && tanggal === TANGGAL_DEMO_PENUH.tanggal;

  const opsi = rooms.map((r) => {
    const siapJam = r.checkout_malam_sebelumnya
      ? jamTambah(r.checkout_malam_sebelumnya, CLEANING_BUFFER_JAM)
      : batasAwal;
    const rekomendasi = siapJam > batasAwal ? siapJam : batasAwal;
    return { nomor: r.nomor, rekomendasi, ada_riwayat: !!r.checkout_malam_sebelumnya };
  }).sort((a, b) => a.rekomendasi.localeCompare(b.rekomendasi));

  return { batasAwal, isPenuh, opsi, utama: isPenuh ? null : opsi[0], alternatif: isPenuh ? [] : opsi.slice(1) };
}

export default function RekomendasiCheckinDayUse() {
  const [tanggal, setTanggal] = useState(todayStr());
  const [tipeKamar, setTipeKamar] = useState("Standard");

  // Rekomendasi otomatis diperbarui tiap kali tanggal/tipe kamar berubah (useMemo re-run).
  const hasil = useMemo(() => hitungRekomendasi(tipeKamar, tanggal), [tipeKamar, tanggal]);

  return (
    <div className="space-y-6" data-testid="rekomendasi-checkin-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Rekomendasi AI Check-in Day Use</h1>
        <p className="text-slate-500 mt-1">
          Sistem menganalisis jam check-out Menginap malam sebelumnya (+ jeda bersih-bersih {CLEANING_BUFFER_JAM} jam) untuk menyarankan jam check-in Day Use yang realistis.
        </p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 sm:p-5 space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label htmlFor="rekom-tanggal">Tanggal Day Use</Label>
              <Input id="rekom-tanggal" data-testid="rekom-tanggal" type="date" value={tanggal} min={todayStr()} onChange={(e) => setTanggal(e.target.value)} className="mt-1.5 h-11" />
            </div>
            <div>
              <Label htmlFor="rekom-tipe">Tipe Kamar</Label>
              <select
                id="rekom-tipe"
                data-testid="rekom-tipe-kamar"
                value={tipeKamar}
                onChange={(e) => setTipeKamar(e.target.value)}
                className="w-full h-11 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
              >
                {Object.keys(MOCK_ROOM_STATUS).map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          {hasil.isPenuh ? (
            <div className="bg-red-50 border-2 border-red-300 rounded-lg p-4 text-sm space-y-2" data-testid="rekom-penuh">
              <p className="font-bold text-red-900 flex items-center gap-1.5"><AlertTriangle className="w-4 h-4" /> {tipeKamar} penuh di tanggal ini</p>
              <p className="text-red-800 text-xs">Semua kamar {tipeKamar} sudah terisi Day Use lain di jam-jam awal. Coba pilih tipe kamar lain atau tanggal lain.</p>
            </div>
          ) : (
            <>
              <div className="bg-emerald-50 border-2 border-emerald-300 rounded-lg p-4 space-y-1.5" data-testid="rekom-utama">
                <p className="font-bold text-emerald-900 flex items-center gap-1.5"><Sparkles className="w-4 h-4" /> Rekomendasi AI</p>
                <p className="text-emerald-800 text-sm">
                  Check-in mulai <b data-testid="rekom-jam-utama">{hasil.utama?.rekomendasi}</b> di kamar <b>{tipeKamar} {hasil.utama?.nomor}</b>
                  {hasil.utama?.ada_riwayat ? " — kamar baru check-out tamu Menginap, sudah memperhitungkan jeda bersih-bersih." : " — kamar sudah kosong, tanpa jeda tambahan."}
                </p>
              </div>

              {hasil.alternatif.length > 0 && (
                <div className="space-y-1.5" data-testid="rekom-alternatif">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Alternatif kamar lain</p>
                  {hasil.alternatif.map((o) => (
                    <div key={o.nomor} data-testid={`rekom-alt-${o.nomor}`} className="flex items-center justify-between text-sm border border-slate-200 rounded-md p-2.5">
                      <span className="flex items-center gap-1.5 text-slate-600"><Clock className="w-3.5 h-3.5" /> {tipeKamar} {o.nomor}</span>
                      <b>{o.rekomendasi}</b>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          <p className="text-[11px] text-slate-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Batas jam check-in paling awal hari ini: {hasil.batasAwal}. Data tiruan — belum tersambung ke Availability Engine sungguhan.</p>
        </CardContent>
      </Card>
    </div>
  );
}
