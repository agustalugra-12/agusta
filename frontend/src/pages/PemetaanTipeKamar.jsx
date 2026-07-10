import { Card, CardContent } from "@/components/ui/card";
import { ArrowRight } from "lucide-react";

const SUMBER_BADGE = {
  Agoda: "bg-violet-100 text-violet-800",
  Traveloka: "bg-blue-100 text-blue-800",
  "Booking.com": "bg-amber-100 text-amber-800",
};

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
              {MOCK_MAPPINGS.map((m) => (
                <tr key={m.id} data-testid={`pemetaan-row-${m.id}`} className="border-t border-slate-100">
                  <td className="p-3 font-medium">{m.ota_nama}</td>
                  <td className="p-3 text-slate-300"><ArrowRight className="w-4 h-4" /></td>
                  <td className="p-3 font-semibold text-blue-700">{m.pms_tipe}</td>
                  <td className="p-3">
                    <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${SUMBER_BADGE[m.sumber] || "bg-slate-100 text-slate-600"}`}>{m.sumber}</span>
                  </td>
                </tr>
              ))}
              {MOCK_MAPPINGS.length === 0 && (
                <tr><td colSpan={4} className="p-6 text-center text-slate-500">Belum ada pemetaan tipe kamar</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[11px] text-slate-400">Data tiruan — belum tersambung ke pemetaan sungguhan.</p>
    </div>
  );
}
