import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { BedDouble, Minus, Plus } from "lucide-react";
import { fmtRp } from "@/lib/apiClient";

// Data tiruan (stub) — harga & batas extra bed per kamar. Belum ada field/harga extra bed
// di backend (BookingCreate/PublicBookingCreate) sama sekali, jadi komponen ini baru
// pratinjau — belum disambungkan ke alur booking tamu yang nyata di PublicBook.jsx atau
// Bookings.jsx. Form pemesanan di bawah juga DEMO (data tiruan), bukan form live, supaya
// total harga yang tampil tidak menyesatkan (backend belum benar-benar menagih extra bed).
const EXTRA_BED_PRICE = 75000; // per malam
const EXTRA_BED_MAX = 2; // maksimal per kamar

// Tarif kamar nyata (sama seperti seed di server.py) — dipakai supaya demo total harga
// realistis, meski form ini sendiri tetap demo/tidak tersambung ke booking sungguhan.
const ROOM_RATES = { Standard: 150000, Cottage: 200000 };

export function ExtraBedSelector({ value, onChange, max = EXTRA_BED_MAX, harga = EXTRA_BED_PRICE, satuan = "malam" }) {
  return (
    <div className="flex items-center justify-between border border-slate-200 rounded-lg p-3" data-testid="extra-bed-selector">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-600 grid place-items-center shrink-0">
          <BedDouble className="w-4 h-4" />
        </div>
        <div>
          <div className="font-medium text-sm">Extra Bed</div>
          <div className="text-xs text-slate-500">{fmtRp(harga)} / {satuan} per extra bed (maks {max})</div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button
          type="button" variant="outline" size="icon" data-testid="extra-bed-kurang"
          onClick={() => onChange(Math.max(0, value - 1))} disabled={value <= 0}
        >
          <Minus className="w-3.5 h-3.5" />
        </Button>
        <span className="w-6 text-center font-semibold" data-testid="extra-bed-qty">{value}</span>
        <Button
          type="button" variant="outline" size="icon" data-testid="extra-bed-tambah"
          onClick={() => onChange(Math.min(max, value + 1))} disabled={value >= max}
        >
          <Plus className="w-3.5 h-3.5" />
        </Button>
      </div>
    </div>
  );
}

export default function PermintaanKhususExtraBed() {
  const [tipeKamar, setTipeKamar] = useState("Standard");
  const [malam, setMalam] = useState(1);
  const [qty, setQty] = useState(0);

  const hargaKamar = ROOM_RATES[tipeKamar] * malam;
  const subtotalExtraBed = qty * EXTRA_BED_PRICE * malam;
  const total = hargaKamar + subtotalExtraBed;

  return (
    <div className="space-y-6" data-testid="permintaan-khusus-extra-bed-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Permintaan Khusus: Extra Bed</h1>
        <p className="text-slate-500 mt-1">
          Pratinjau komponen pemilih extra bed dalam form pemesanan demo — belum tersambung ke alur booking tamu sungguhan.
        </p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-4">
          <h3 className="text-sm font-semibold text-slate-700">Form Pemesanan (Demo)</h3>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label htmlFor="demo-tipe-kamar">Tipe Kamar</Label>
              <select
                id="demo-tipe-kamar"
                data-testid="demo-tipe-kamar"
                value={tipeKamar}
                onChange={(e) => setTipeKamar(e.target.value)}
                className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
              >
                {Object.keys(ROOM_RATES).map((t) => <option key={t} value={t}>{t} ({fmtRp(ROOM_RATES[t])}/malam)</option>)}
              </select>
            </div>
            <div>
              <Label htmlFor="demo-malam">Jumlah Malam</Label>
              <div className="flex items-center gap-3 mt-1.5">
                <Button type="button" variant="outline" size="icon" data-testid="demo-malam-kurang" onClick={() => setMalam((n) => Math.max(1, n - 1))} disabled={malam <= 1}>
                  <Minus className="w-3.5 h-3.5" />
                </Button>
                <span className="w-6 text-center font-semibold" data-testid="demo-malam-value">{malam}</span>
                <Button type="button" variant="outline" size="icon" data-testid="demo-malam-tambah" onClick={() => setMalam((n) => Math.min(14, n + 1))}>
                  <Plus className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
          </div>

          <ExtraBedSelector value={qty} onChange={setQty} />

          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 space-y-1.5 text-sm" data-testid="demo-total-breakdown">
            <div className="flex justify-between"><span className="text-slate-500">{tipeKamar} &times; {malam} malam</span><span>{fmtRp(hargaKamar)}</span></div>
            {qty > 0 && (
              <div className="flex justify-between"><span className="text-slate-500">Extra Bed ({qty}x &times; {malam} malam)</span><span>{fmtRp(subtotalExtraBed)}</span></div>
            )}
            <div className="flex justify-between border-t border-slate-200 pt-1.5 mt-1.5">
              <span className="font-bold">Total</span><b className="text-blue-700" data-testid="demo-total">{fmtRp(total)}</b>
            </div>
          </div>
          <p className="text-[11px] text-slate-400">Data tiruan — form demo ini belum membuat reservasi sungguhan.</p>
        </CardContent>
      </Card>
    </div>
  );
}
