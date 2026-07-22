import { Button } from "@/components/ui/button";
import { BedDouble, Minus, Plus } from "lucide-react";
import { fmtRp } from "@/lib/apiClient";

// Widget +/- extra bed generik (harga/batas selalu dikirim via props oleh pemanggil,
// nilai riil ada di PublicBook.jsx & backend/core.py — komponen ini murni presentational,
// tidak menyimpan data tiruan sendiri). Diekstrak dari bekas halaman demo
// "Permintaan Khusus Extra Bed" (dihapus 2026-07-22, permintaan user "rampingkan PMS" -
// halaman itu sendiri cuma form pratinjau yang tidak pernah tersambung ke booking
// sungguhan, tapi komponen ini genuinely dipakai live di PublicBook.jsx).
export function ExtraBedSelector({ value, onChange, max, harga, satuan = "malam" }) {
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
