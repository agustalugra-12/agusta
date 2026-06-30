import { useEffect, useState } from "react";
import api, { fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";

export default function Audit() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/audit-log").then(r => setItems(r.data)); }, []);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Audit Log</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Riwayat Aktivitas</h1>
      </div>
      <Card className="border-slate-200">
        <CardContent className="p-0">
          <ul className="divide-y divide-slate-100">
            {items.map(x => (
              <li key={x.id} className="p-4 text-sm flex items-start gap-3">
                <span className="text-[10px] uppercase tracking-wider bg-blue-50 text-blue-700 px-2 py-0.5 rounded font-bold">{x.action}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{x.detail || "-"}</div>
                  <div className="text-xs text-slate-500">{fmtDateTime(x.timestamp)} • {x.username}</div>
                </div>
              </li>
            ))}
            {items.length === 0 && <li className="p-6 text-center text-slate-500">Belum ada aktivitas</li>}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
