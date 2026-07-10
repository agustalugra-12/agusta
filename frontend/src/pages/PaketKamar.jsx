import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Coffee, Ban } from "lucide-react";
import { fmtRp } from "@/lib/apiClient";

// Data tiruan (stub) — harga tetap per tipe kamar x paket (dengan/tanpa breakfast), sesuai
// PRD: "Logika harga tetap untuk Standard/Cottage (dengan/tanpa breakfast)". Belum ada field
// paket di backend (BookingCreate/PublicBookingCreate), jadi komponen ini baru pratinjau —
// belum disambungkan ke form booking tamu sungguhan di PublicBook.jsx.
const PAKET_HARGA = {
  Standard: { tanpa_breakfast: 120000, dengan_breakfast: 150000 },
  Cottage: { tanpa_breakfast: 140000, dengan_breakfast: 170000 },
};

export function PaketKamarSelector({ tipeKamar, value, onChange }) {
  const harga = PAKET_HARGA[tipeKamar] || PAKET_HARGA.Standard;
  return (
    <div className="grid grid-cols-2 gap-2" data-testid="paket-kamar-selector">
      <button
        type="button"
        data-testid="paket-tanpa-breakfast"
        onClick={() => onChange("tanpa_breakfast")}
        className={`p-3 rounded-lg border-2 text-left transition-colors ${value === "tanpa_breakfast" ? "border-blue-600 bg-blue-50" : "border-slate-200 hover:border-slate-300"}`}
      >
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 font-semibold"><Ban className="w-3 h-3" /> Tanpa Breakfast</div>
        <div className="font-extrabold text-blue-700 mt-1">{fmtRp(harga.tanpa_breakfast)}</div>
      </button>
      <button
        type="button"
        data-testid="paket-dengan-breakfast"
        onClick={() => onChange("dengan_breakfast")}
        className={`p-3 rounded-lg border-2 text-left transition-colors ${value === "dengan_breakfast" ? "border-blue-600 bg-blue-50" : "border-slate-200 hover:border-slate-300"}`}
      >
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 font-semibold"><Coffee className="w-3 h-3" /> Dengan Breakfast</div>
        <div className="font-extrabold text-blue-700 mt-1">{fmtRp(harga.dengan_breakfast)}</div>
      </button>
    </div>
  );
}

export default function PaketKamar() {
  const [tipeKamar, setTipeKamar] = useState("Standard");
  const [paket, setPaket] = useState("tanpa_breakfast");
  const harga = PAKET_HARGA[tipeKamar][paket];

  return (
    <div className="space-y-6" data-testid="paket-kamar-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Paket Kamar</h1>
        <p className="text-slate-500 mt-1">
          Pratinjau komponen pemilih paket kamar (dengan/tanpa breakfast) — belum tersambung ke form booking tamu sungguhan.
        </p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-4">
          <h3 className="text-sm font-semibold text-slate-700">Pratinjau Komponen</h3>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Tipe Kamar</div>
            <div className="grid grid-cols-2 gap-2">
              {Object.keys(PAKET_HARGA).map((t) => (
                <button
                  key={t}
                  type="button"
                  data-testid={`paket-tipe-${t.toLowerCase()}`}
                  onClick={() => setTipeKamar(t)}
                  className={`h-10 rounded-md border-2 text-sm font-semibold transition-colors ${tipeKamar === t ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 hover:border-slate-300"}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Paket</div>
            <PaketKamarSelector tipeKamar={tipeKamar} value={paket} onChange={setPaket} />
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-3 flex justify-between text-sm" data-testid="paket-ringkasan">
            <span className="text-slate-500">{tipeKamar} &middot; {paket === "dengan_breakfast" ? "Dengan Breakfast" : "Tanpa Breakfast"}</span>
            <b className="text-blue-700" data-testid="paket-total">{fmtRp(harga)}</b>
          </div>
          <p className="text-[11px] text-slate-400">Data tiruan — belum tersambung ke form booking tamu sungguhan.</p>
        </CardContent>
      </Card>
    </div>
  );
}
