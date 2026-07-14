import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { Sparkles } from "lucide-react";

export default function Housekeeping() {
  const { user } = useAuth();
  const [rooms, setRooms] = useState([]);
  const [logs, setLogs] = useState([]);
  const [petugasMap, setPetugasMap] = useState({});

  const load = async () => {
    const [r, l] = await Promise.all([api.get("/rooms"), api.get("/housekeeping")]);
    const perlu = r.data.filter(x => x.status === "perlu_dibersihkan");
    setRooms(perlu);
    setPetugasMap(prev => {
      const next = { ...prev };
      perlu.forEach(x => { if (next[x.id] === undefined) next[x.id] = user?.nama || ""; });
      return next;
    });
    setLogs(l.data);
  };
  useEffect(() => { load(); }, []);

  const done = async (r) => {
    const petugas = (petugasMap[r.id] || "").trim();
    if (!petugas) { toast.error("Nama petugas wajib diisi"); return; }
    try {
      await api.post(`/rooms/${r.id}/housekeeping-done`, { petugas });
      toast.success(`Kamar ${r.nomor} selesai`); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const selesai = logs.filter(l => l.status === "selesai").slice(0, 30);
  const avg = selesai.length ? (selesai.reduce((a, x) => {
    if (!x.jam_checkout || !x.jam_selesai) return a;
    return a + (new Date(x.jam_selesai) - new Date(x.jam_checkout)) / 60000;
  }, 0) / selesai.length).toFixed(1) : "-";

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Housekeeping</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Pembersihan Kamar</h1>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        <Stat label="Perlu Dibersihkan" value={rooms.length} color="#F97316" />
        <Stat label="Selesai (30 terakhir)" value={selesai.length} color="#10B981" />
        <Stat label="Rata-rata Waktu (menit)" value={avg} color="#1E40AF" />
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-5">
          <h2 className="font-bold mb-4">Antrian</h2>
          {rooms.length === 0 ? (
            <p className="text-slate-500">Semua kamar sudah bersih ✨</p>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {rooms.map(r => (
                <div key={r.id} className="rounded-xl border border-orange-200 bg-orange-50 p-4 flex flex-col gap-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-orange-500 text-white grid place-items-center"><Sparkles className="w-5 h-5" /></div>
                    <div>
                      <div className="font-bold text-lg">Kamar {r.nomor}</div>
                      <div className="text-xs text-slate-600">{r.tipe}</div>
                    </div>
                  </div>
                  <Input
                    data-testid={`hk-petugas-${r.nomor}`}
                    value={petugasMap[r.id] ?? ""}
                    onChange={(e) => setPetugasMap(prev => ({ ...prev, [r.id]: e.target.value }))}
                    placeholder="Nama petugas"
                    className="bg-white"
                  />
                  <Button data-testid={`hk-done-${r.nomor}`} onClick={() => done(r)} className="bg-emerald-600 hover:bg-emerald-700">Selesai</Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-5">
          <h2 className="font-bold mb-3">Riwayat Pembersihan</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs uppercase text-slate-500"><tr>
                <th className="p-2 text-left">Kamar</th><th className="p-2 text-left">Check-Out</th>
                <th className="p-2 text-left">Selesai</th><th className="p-2 text-left">Petugas</th>
              </tr></thead>
              <tbody>
                {selesai.map(l => (
                  <tr key={l.id} className="border-t border-slate-100">
                    <td className="p-2 font-bold">{l.room_nomor}</td>
                    <td className="p-2">{fmtDateTime(l.jam_checkout)}</td>
                    <td className="p-2">{fmtDateTime(l.jam_selesai)}</td>
                    <td className="p-2">{l.petugas || "-"}</td>
                  </tr>
                ))}
                {selesai.length === 0 && <tr><td colSpan={4} className="p-6 text-center text-slate-500">Belum ada riwayat</td></tr>}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4">
        <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
        <div className="text-3xl font-extrabold mt-1" style={{ color }}>{value}</div>
      </CardContent>
    </Card>
  );
}
