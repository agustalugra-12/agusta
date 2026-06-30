import { useEffect, useMemo, useState } from "react";
import api, { fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search } from "lucide-react";

const QUICK_FILTERS = [
  { key: "", label: "Semua" },
  { key: "cancel_with_fee", label: "Cancel + Fee" },
  { key: "no_show", label: "No-Show" },
  { key: "create_booking", label: "Booking Baru" },
  { key: "update_booking", label: "Edit Booking" },
  { key: "checkout", label: "Check-out" },
  { key: "move_room", label: "Pindah Kamar" },
  { key: "payment_settlement", label: "Pembayaran" },
];

export default function Audit() {
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("");

  useEffect(() => { api.get("/audit-log").then(r => setItems(r.data)); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter(x => {
      if (actionFilter && !x.action?.toLowerCase().includes(actionFilter)) return false;
      if (!q) return true;
      return (x.action || "").toLowerCase().includes(q) ||
             (x.detail || "").toLowerCase().includes(q) ||
             (x.username || "").toLowerCase().includes(q) ||
             (x.entity || "").toLowerCase().includes(q);
    });
  }, [items, search, actionFilter]);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Audit Log</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Riwayat Aktivitas</h1>
        <p className="text-sm text-slate-500 mt-1">Total {items.length} aktivitas • Tampil {filtered.length}</p>
      </div>

      {/* Search + filter */}
      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-3">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-3.5 text-slate-400" />
            <Input
              data-testid="audit-search"
              placeholder="Cari: cancel_with_fee, nama tamu, kode booking, kamar..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 h-11"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {QUICK_FILTERS.map(f => (
              <Button
                key={f.key || "all"}
                data-testid={`audit-filter-${f.key || "all"}`}
                type="button"
                size="sm"
                variant={actionFilter === f.key ? "default" : "outline"}
                onClick={() => setActionFilter(f.key)}
                className={actionFilter === f.key ? "bg-blue-700 hover:bg-blue-800" : ""}
              >
                {f.label}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0">
          <ul className="divide-y divide-slate-100">
            {filtered.map(x => (
              <li key={x.id} data-testid={`audit-item-${x.action}`} className="p-4 text-sm flex items-start gap-3">
                <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded font-bold whitespace-nowrap ${
                  x.action?.includes("cancel") ? "bg-red-50 text-red-700" :
                  x.action === "no_show" ? "bg-amber-50 text-amber-700" :
                  x.action?.includes("payment") ? "bg-emerald-50 text-emerald-700" :
                  "bg-blue-50 text-blue-700"
                }`}>{x.action}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{x.detail || "-"}</div>
                  <div className="text-xs text-slate-500">
                    {fmtDateTime(x.timestamp)} • {x.username}
                    {x.entity && <span> • Entity: <b>{x.entity}</b></span>}
                  </div>
                </div>
              </li>
            ))}
            {filtered.length === 0 && <li className="p-6 text-center text-slate-500">Tidak ada aktivitas yang cocok</li>}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
