import { useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ArrowRight, Search, X } from "lucide-react";

const SUMBER_BADGE = {
  Agoda: "bg-violet-100 text-violet-800",
  Traveloka: "bg-blue-100 text-blue-800",
  "Booking.com": "bg-amber-100 text-amber-800",
};

const PMS_TIPE_OPTIONS = ["Semua", "Standard", "Cottage"];
const SUMBER_OPTIONS = ["Semua", "Agoda", "Traveloka", "Booking.com"];

// Data tiruan (stub) — mengikuti entitas ROOM_MAPPINGS di PRD (id, pms_room_id,
// ota_room_name, ota_source). Tiap OTA punya istilah sendiri untuk tipe kamar yang sama
// di Pelangi PMS; pemetaan ini yang dipakai AI Email Parser & Availability Engine supaya
// merujuk ke kamar PMS yang benar.
const MOCK_MAPPINGS = [
  { id: "1", pms_tipe: "Standard", ota_nama: "Deluxe Room", sumber: "Agoda" },
  { id: "2", pms_tipe: "Standard", ota_nama: "Superior Twin", sumber: "Traveloka" },
  { id: "3", pms_tipe: "Standard", ota_nama: "Standard Double Room", sumber: "Booking.com" },
  { id: "4", pms_tipe: "Cottage", ota_nama: "Bungalow Deluxe", sumber: "Agoda" },
  { id: "5", pms_tipe: "Cottage", ota_nama: "Family Cottage", sumber: "Traveloka" },
];

export default function PemetaanTipeKamar() {
  const [search, setSearch] = useState("");
  const [pmsTipe, setPmsTipe] = useState("Semua");
  const [sumber, setSumber] = useState("Semua");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return MOCK_MAPPINGS.filter((m) => {
      if (q && !m.ota_nama.toLowerCase().includes(q)) return false;
      if (pmsTipe !== "Semua" && m.pms_tipe !== pmsTipe) return false;
      if (sumber !== "Semua" && m.sumber !== sumber) return false;
      return true;
    });
  }, [search, pmsTipe, sumber]);

  const resetFilters = () => { setSearch(""); setPmsTipe("Semua"); setSumber("Semua"); };
  const hasActiveFilter = search || pmsTipe !== "Semua" || sumber !== "Semua";

  return (
    <div className="space-y-6" data-testid="pemetaan-tipe-kamar-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Pemetaan Tipe Kamar</h1>
        <p className="text-slate-500 mt-1">
          Samakan nama tipe kamar di tiap OTA dengan tipe kamar yang dipakai Pelangi PMS.
        </p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <Label htmlFor="pemetaan-search">Cari nama di OTA</Label>
            <div className="relative mt-1.5">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <Input
                id="pemetaan-search"
                data-testid="pemetaan-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Mis: Deluxe Room…"
                className="pl-9"
              />
            </div>
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="pemetaan-tipe">Tipe Kamar PMS</Label>
            <select
              id="pemetaan-tipe"
              data-testid="pemetaan-filter-tipe"
              value={pmsTipe}
              onChange={(e) => setPmsTipe(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {PMS_TIPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="w-full sm:w-44">
            <Label htmlFor="pemetaan-sumber">Sumber OTA</Label>
            <select
              id="pemetaan-sumber"
              data-testid="pemetaan-filter-sumber"
              value={sumber}
              onChange={(e) => setSumber(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {SUMBER_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {hasActiveFilter && (
            <Button data-testid="pemetaan-reset-filter" variant="ghost" size="sm" onClick={resetFilters} className="gap-1.5">
              <X className="w-3.5 h-3.5" /> Reset
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm" data-testid="pemetaan-table">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Nama di OTA</th>
                <th className="text-left p-3"></th>
                <th className="text-left p-3">Tipe Kamar PMS</th>
                <th className="text-left p-3">Sumber</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((m) => (
                <tr key={m.id} data-testid={`pemetaan-row-${m.id}`} className="border-t border-slate-100">
                  <td className="p-3 font-medium">{m.ota_nama}</td>
                  <td className="p-3 text-slate-300"><ArrowRight className="w-4 h-4" /></td>
                  <td className="p-3 font-semibold text-blue-700">{m.pms_tipe}</td>
                  <td className="p-3">
                    <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${SUMBER_BADGE[m.sumber] || "bg-slate-100 text-slate-600"}`}>{m.sumber}</span>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={4} className="p-6 text-center text-slate-500">Tidak ada pemetaan yang cocok dengan pencarian/filter</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[11px] text-slate-400">Data tiruan — belum tersambung ke pemetaan sungguhan.</p>
    </div>
  );
}
