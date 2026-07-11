import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sparkles, Clock, AlertTriangle, CheckCircle2 } from "lucide-react";
import api from "@/lib/apiClient";

const todayStr = () => new Date().toISOString().slice(0, 10);
const ROOM_TYPE_OPTIONS = ["Standard", "Cottage"];
const CLEANING_BUFFER_JAM = 1;

export default function RekomendasiCheckinDayUse() {
  const [tanggal, setTanggal] = useState(todayStr());
  const [tipeKamar, setTipeKamar] = useState("Standard");
  const [hasil, setHasil] = useState(null);
  const [loading, setLoading] = useState(false);

  // Otomatis diperbarui tiap kali tanggal/tipe kamar berubah — fetch ulang ke backend
  // (rekomendasi dihitung dari data reservasi Menginap sungguhan, bukan data tiruan).
  useEffect(() => {
    setLoading(true);
    api.get("/rekomendasi-checkin", { params: { tanggal, tipe_kamar: tipeKamar } })
      .then((r) => setHasil(r.data))
      .catch(() => setHasil(null))
      .finally(() => setLoading(false));
  }, [tanggal, tipeKamar]);

  return (
    <div className="space-y-6" data-testid="rekomendasi-checkin-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Rekomendasi AI Check-in Day Use</h1>
        <p className="text-slate-500 mt-1">
          Sistem menganalisis jam check-out Menginap sungguhan pada tanggal itu (+ jeda bersih-bersih {CLEANING_BUFFER_JAM} jam) untuk menyarankan jam check-in Day Use yang realistis.
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
                {ROOM_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          {loading && <p className="text-sm text-slate-500">Menghitung rekomendasi…</p>}

          {!loading && hasil?.is_penuh && (
            <div className="bg-red-50 border-2 border-red-300 rounded-lg p-4 text-sm space-y-2" data-testid="rekom-penuh">
              <p className="font-bold text-red-900 flex items-center gap-1.5"><AlertTriangle className="w-4 h-4" /> {tipeKamar} penuh di tanggal ini</p>
              <p className="text-red-800 text-xs">Semua kamar {tipeKamar} sudah terisi Day Use lain di jam-jam awal. Coba pilih tipe kamar lain atau tanggal lain.</p>
            </div>
          )}

          {!loading && hasil && !hasil.is_penuh && (
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

          {!loading && hasil && (
            <p className="text-[11px] text-slate-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Batas jam check-in paling awal hari ini: {hasil.batas_awal}.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
