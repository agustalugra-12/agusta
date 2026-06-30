import { useEffect, useState } from "react";
import api, { fmtRp, fmtDateTime, waLink } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MessageCircle, Phone, History } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export default function Tamu() {
  const [q, setQ] = useState("");
  const [guests, setGuests] = useState([]);
  const [history, setHistory] = useState(null);

  const load = async () => {
    const { data } = await api.get("/guests", { params: q ? { q } : {} });
    setGuests(data);
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [q]);

  const showHistory = async (g) => {
    const { data } = await api.get(`/guests/${g.id}/history`);
    setHistory({ guest: g, items: data });
  };

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Tamu</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Riwayat Tamu</h1>
      </div>
      <Input data-testid="search-guest" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama, HP, atau No KTP..." className="h-12" />
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {guests.map(g => (
          <Card key={g.id} className="border-slate-200">
            <CardContent className="p-4 space-y-3">
              <div>
                <div className="font-bold text-base">{g.nama}</div>
                <div className="text-xs text-slate-500">{g.no_hp || "-"} • {g.no_identitas || "-"}</div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-slate-50 rounded-lg p-2"><div className="text-slate-500">Kunjungan</div><div className="font-bold">{g.total_kunjungan || 0}×</div></div>
                <div className="bg-slate-50 rounded-lg p-2"><div className="text-slate-500">Total Trx</div><div className="font-bold">{fmtRp(g.total_transaksi || 0)}</div></div>
              </div>
              <div className="text-xs text-slate-500">Terakhir: {fmtDateTime(g.last_visit)}</div>
              <div className="flex gap-2">
                {g.no_hp && <a href={waLink(g.no_hp)} target="_blank" rel="noreferrer" className="flex-1"><Button size="sm" variant="outline" className="w-full"><MessageCircle className="w-3.5 h-3.5 mr-1" /> WA</Button></a>}
                {g.no_hp && <a href={`tel:${g.no_hp}`} className="flex-1"><Button size="sm" variant="outline" className="w-full"><Phone className="w-3.5 h-3.5 mr-1" /> Telepon</Button></a>}
                <Button size="sm" variant="outline" onClick={() => showHistory(g)} data-testid={`hist-${g.id}`}><History className="w-3.5 h-3.5" /></Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {guests.length === 0 && <div className="col-span-full text-slate-500 text-center py-10">Belum ada data tamu</div>}
      </div>

      <Dialog open={!!history} onOpenChange={(o) => !o && setHistory(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Riwayat {history?.guest?.nama}</DialogTitle></DialogHeader>
          <div className="max-h-96 overflow-y-auto space-y-2">
            {(history?.items || []).map(it => (
              <div key={it.id} className="border border-slate-200 rounded-lg p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-semibold">Kamar {it.room_nomor} ({it.room_tipe})</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${it.status === "selesai" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{it.status}</span>
                </div>
                <div className="text-xs text-slate-500 mt-1">{fmtDateTime(it.jam_checkin)} → {fmtDateTime(it.jam_checkout)}</div>
                {it.status === "selesai" && <div className="text-sm font-semibold mt-1">{fmtRp(it.total)}</div>}
              </div>
            ))}
            {(history?.items || []).length === 0 && <div className="text-slate-500 text-center py-6">Belum ada riwayat</div>}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
