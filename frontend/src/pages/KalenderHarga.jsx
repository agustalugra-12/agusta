import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import api, { fmtRp } from "@/lib/apiClient";
import { ChevronLeft, ChevronRight, Tag, CheckCircle2 } from "lucide-react";

// Fase 3 "Manajemen Harga (Rates)" — data nyata dari backend/routes/rates.py
// (collection `rates`, tarif dasar tetap satu sumber kebenaran di `rooms.tarif`).
const WARNA_TIPE = { Standard: "#1E40AF", Cottage: "#F97316" };
const warnaUntuk = (tipe, i) => WARNA_TIPE[tipe] || ["#1E40AF", "#F97316", "#0EA5E9", "#8B5CF6"][i % 4];

const monthLabel = (d) => d.toLocaleDateString("id-ID", { month: "long", year: "numeric" });
const toIso = (d) => d.toISOString().slice(0, 10);

function daysInMonth(viewDate) {
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const n = new Date(year, month + 1, 0).getDate();
  return Array.from({ length: n }, (_, i) => new Date(year, month, i + 1));
}

function useTipeKamar() {
  const [tipeKamar, setTipeKamar] = useState([]);
  useEffect(() => {
    api.get("/rates/tipe-kamar").then(({ data }) => {
      setTipeKamar(data.map((t, i) => ({ ...t, color: warnaUntuk(t.tipe, i) })));
    }).catch(() => setTipeKamar([]));
  }, []);
  return tipeKamar;
}

export default function KalenderHarga() {
  const [viewDate, setViewDate] = useState(() => { const d = new Date(); d.setDate(1); return d; });
  const tipeKamar = useTipeKamar();
  const [tab, setTab] = useState("");
  const [hargaPerHari, setHargaPerHari] = useState({}); // { "YYYY-MM-DD": harga }
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => { if (!tab && tipeKamar.length) setTab(tipeKamar[0].tipe); }, [tipeKamar, tab]);

  const days = useMemo(() => daysInMonth(viewDate), [viewDate]);
  const leadingBlanks = (new Date(viewDate.getFullYear(), viewDate.getMonth(), 1).getDay() + 6) % 7;
  const todayStr = new Date().toDateString();
  const tipeAktif = tipeKamar.find((t) => t.tipe === tab);

  const goMonth = (delta) => setViewDate((d) => new Date(d.getFullYear(), d.getMonth() + delta, 1));

  useEffect(() => {
    if (!tab || !days.length) return;
    let live = true;
    api.get("/rates/kalender", {
      params: { room_type: tab, from_date: toIso(days[0]), to_date: toIso(days[days.length - 1]) },
    }).then(({ data }) => {
      if (!live) return;
      setHargaPerHari(Object.fromEntries(data.days.map((d) => [d.tanggal, d.harga])));
    }).catch(() => { if (live) setHargaPerHari({}); });
    return () => { live = false; };
  }, [tab, viewDate, reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const hargaUntuk = (date) => hargaPerHari[toIso(date)] ?? tipeAktif?.tarif_dasar ?? 0;

  const terapkanMassal = async ({ dari, sampai, tipe, harga }) => {
    if (new Date(dari) > new Date(sampai)) {
      toast.error("Rentang tanggal tidak valid");
      return false;
    }
    try {
      const { data } = await api.post("/rates/update-massal", { room_type: tipe, dari, sampai, harga });
      toast.success(`Harga ${data.tipe.join(" & ")} diperbarui untuk ${data.jumlah_hari} hari (${fmtRp(harga)})`);
      setReloadKey((k) => k + 1);
      return true;
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Gagal update harga");
      return false;
    }
  };

  return (
    <div className="space-y-6" data-testid="kalender-harga-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 3 — Manajemen Sistem Internal</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Kalender Harga</h1>
        <p className="text-slate-500 mt-1">Pantau &amp; ubah harga kamar per tanggal. Tersambung ke Pelangi PMS sungguhan (sinkron ke saluran WhatsApp bot kalau webhook sudah dikonfigurasi).</p>
      </div>

      <FormUpdateMassal tipeKamar={tipeKamar} onTerapkan={terapkanMassal} />

      {tipeAktif && (
        <Card className="border-slate-200">
          <CardContent className="p-4 sm:p-6">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
              <div className="flex gap-1.5 bg-slate-100 rounded-lg p-1">
                {tipeKamar.map((t) => (
                  <button
                    key={t.tipe}
                    type="button"
                    data-testid={`harga-tab-${t.tipe.toLowerCase()}`}
                    onClick={() => setTab(t.tipe)}
                    className={`px-3 py-1.5 rounded-md text-sm font-semibold transition-colors ${tab === t.tipe ? "bg-white shadow text-slate-900" : "text-slate-500"}`}
                  >
                    {t.tipe}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <Button data-testid="harga-kalender-prev" size="icon" variant="outline" className="h-8 w-8" onClick={() => goMonth(-1)}>
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <span className="text-sm font-medium w-36 text-center capitalize" data-testid="harga-kalender-label">{monthLabel(viewDate)}</span>
                <Button data-testid="harga-kalender-next" size="icon" variant="outline" className="h-8 w-8" onClick={() => goMonth(1)}>
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-7 gap-1.5 text-center text-[11px] font-semibold text-slate-500 mb-1.5">
              {["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"].map((d) => <div key={d}>{d}</div>)}
            </div>
            <div className="grid grid-cols-7 gap-1.5" data-testid="kalender-harga-grid">
              {Array.from({ length: leadingBlanks }).map((_, i) => <div key={`b${i}`} />)}
              {days.map((date) => {
                const harga = hargaUntuk(date);
                const isOverride = harga !== tipeAktif.tarif_dasar;
                const isToday = date.toDateString() === todayStr;
                return (
                  <div
                    key={date.toISOString()}
                    data-testid={`harga-hari-${date.getDate()}`}
                    className="aspect-square rounded-lg flex flex-col items-center justify-center gap-0.5 border"
                    style={{
                      background: isOverride ? `${tipeAktif.color}14` : "#F8FAFC",
                      borderColor: isToday ? tipeAktif.color : "#E2E8F0",
                      borderWidth: isToday ? 2 : 1,
                    }}
                  >
                    <span className="text-xs font-bold text-slate-700">{date.getDate()}</span>
                    <span className="text-[9px] font-medium" style={{ color: isOverride ? tipeAktif.color : "#64748B" }}>
                      {(harga / 1000).toFixed(0)}k
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="flex items-center gap-4 mt-4 text-xs text-slate-500">
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-slate-50 border border-slate-200" /> Tarif dasar ({fmtRp(tipeAktif.tarif_dasar)})</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm" style={{ background: `${tipeAktif.color}14`, borderColor: tipeAktif.color, borderWidth: 1 }} /> Harga diubah manual</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function FormUpdateMassal({ tipeKamar, onTerapkan }) {
  const today = toIso(new Date());
  const [dari, setDari] = useState(today);
  const [sampai, setSampai] = useState(today);
  const [tipe, setTipe] = useState("Semua");
  const [harga, setHarga] = useState("");
  const [sukses, setSukses] = useState(false);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const nominal = Number(harga);
    if (!nominal || nominal <= 0) { toast.error("Isi harga baru yang valid"); return; }
    setSaving(true);
    const ok = await onTerapkan({ dari, sampai, tipe, harga: nominal });
    setSaving(false);
    if (ok) {
      setSukses(true);
      setHarga("");
      setTimeout(() => setSukses(false), 3000);
    }
  };

  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-5">
        <h2 className="font-bold flex items-center gap-2 mb-3"><Tag className="w-4 h-4 text-blue-700" /> Update Harga Massal</h2>
        <form onSubmit={submit} className="grid grid-cols-1 sm:grid-cols-5 gap-3 items-end" data-testid="form-update-harga-massal">
          <div>
            <Label htmlFor="harga-dari">Dari</Label>
            <Input id="harga-dari" data-testid="harga-dari" type="date" value={dari} onChange={(e) => setDari(e.target.value)} className="mt-1.5" />
          </div>
          <div>
            <Label htmlFor="harga-sampai">Sampai</Label>
            <Input id="harga-sampai" data-testid="harga-sampai" type="date" value={sampai} onChange={(e) => setSampai(e.target.value)} className="mt-1.5" />
          </div>
          <div>
            <Label htmlFor="harga-tipe">Tipe Kamar</Label>
            <select
              id="harga-tipe" data-testid="harga-tipe-select" value={tipe} onChange={(e) => setTipe(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              <option value="Semua">Semua Tipe</option>
              {tipeKamar.map((t) => <option key={t.tipe} value={t.tipe}>{t.tipe}</option>)}
            </select>
          </div>
          <div>
            <Label htmlFor="harga-baru">Harga Baru / Malam</Label>
            <Input id="harga-baru" data-testid="harga-baru" type="number" min="0" step="1000" placeholder="cth: 150000" value={harga} onChange={(e) => setHarga(e.target.value)} className="mt-1.5" />
          </div>
          <Button type="submit" data-testid="harga-terapkan" disabled={saving} className="bg-blue-700 hover:bg-blue-800 h-10">
            {saving ? "Menyimpan…" : "Terapkan ke Kalender"}
          </Button>
        </form>
        {sukses && (
          <div data-testid="harga-sukses-banner" className="mt-3 flex items-center gap-2 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
            <CheckCircle2 className="w-4 h-4" /> Harga berhasil diperbarui — cek kalender di bawah.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
