import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import { Sparkles, Play } from "lucide-react";

export default function Housekeeping() {
  const { user } = useAuth();
  const [rooms, setRooms] = useState([]);
  const [logs, setLogs] = useState([]);
  const [petugasMap, setPetugasMap] = useState({});
  const [catatanMap, setCatatanMap] = useState({});
  const [pendingLogByRoom, setPendingLogByRoom] = useState({}); // room_id -> log pending/in-progress terbaru

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
    const pendingMap = {};
    l.data.filter(x => ["pending", "cleaning"].includes(x.status)).forEach(x => {
      if (!pendingMap[x.room_id] || x.tanggal > pendingMap[x.room_id].tanggal) pendingMap[x.room_id] = x;
    });
    setPendingLogByRoom(pendingMap);
  };
  useEffect(() => { load(); }, []);

  const mulai = async (r) => {
    try {
      await api.post(`/rooms/${r.id}/housekeeping-mulai`);
      toast.success(`Kamar ${r.nomor} mulai dibersihkan`); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const done = async (r) => {
    const petugas = (petugasMap[r.id] || "").trim();
    if (!petugas) { toast.error("Nama petugas wajib diisi"); return; }
    try {
      await api.post(`/rooms/${r.id}/housekeeping-done`, { petugas, catatan: (catatanMap[r.id] || "").trim() });
      toast.success(`Kamar ${r.nomor} selesai`);
      setCatatanMap(prev => ({ ...prev, [r.id]: "" }));
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const inspect = async (roomId, roomNomor) => {
    try {
      await api.post(`/rooms/${roomId}/housekeeping-inspect`);
      toast.success(`Kamar ${roomNomor} ditandai Inspected`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const perluInspeksi = logs.filter(l => l.status === "clean").slice(0, 20);
  const selesai = logs.filter(l => ["clean", "inspected"].includes(l.status)).slice(0, 30);
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

      <div className="grid sm:grid-cols-4 gap-4">
        <Stat label="Perlu Dibersihkan" value={rooms.length} color="#F97316" />
        <Stat label="Perlu Diperiksa" value={perluInspeksi.length} color="#8B5CF6" />
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
              {rooms.map(r => {
                const pendingLog = pendingLogByRoom[r.id];
                const sudahMulai = !!pendingLog?.jam_mulai;
                return (
                  <div key={r.id} className="rounded-xl border border-orange-200 bg-orange-50 p-4 flex flex-col gap-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-orange-500 text-white grid place-items-center"><Sparkles className="w-5 h-5" /></div>
                        <div>
                          <div className="font-bold text-lg">Kamar {r.nomor}</div>
                          <div className="text-xs text-slate-600">{r.tipe}</div>
                        </div>
                      </div>
                      {sudahMulai ? (
                        <span data-testid={`hk-status-${r.nomor}`} className="text-[10px] font-semibold uppercase tracking-wider text-blue-700 bg-blue-100 px-2 py-1 rounded-full">
                          Dibersihkan sejak {fmtDateTime(pendingLog.jam_mulai)}
                        </span>
                      ) : (
                        <span data-testid={`hk-status-${r.nomor}`} className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 bg-slate-100 px-2 py-1 rounded-full">Menunggu</span>
                      )}
                    </div>
                    <Input
                      data-testid={`hk-petugas-${r.nomor}`}
                      value={petugasMap[r.id] ?? ""}
                      onChange={(e) => setPetugasMap(prev => ({ ...prev, [r.id]: e.target.value }))}
                      placeholder="Nama petugas"
                      className="bg-white"
                    />
                    <Textarea
                      data-testid={`hk-catatan-${r.nomor}`}
                      value={catatanMap[r.id] ?? ""}
                      onChange={(e) => setCatatanMap(prev => ({ ...prev, [r.id]: e.target.value }))}
                      placeholder="Catatan (opsional)"
                      className="bg-white"
                      rows={2}
                    />
                    <div className="flex gap-2">
                      {!sudahMulai && (
                        <Button data-testid={`hk-mulai-${r.nomor}`} variant="outline" onClick={() => mulai(r)} className="flex-1">
                          <Play className="w-3.5 h-3.5 mr-1.5" /> Mulai
                        </Button>
                      )}
                      <Button data-testid={`hk-done-${r.nomor}`} onClick={() => done(r)} className="flex-1 bg-emerald-600 hover:bg-emerald-700">Selesai</Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-5">
          <h2 className="font-bold mb-4">Perlu Diperiksa (QC)</h2>
          {perluInspeksi.length === 0 ? (
            <p className="text-slate-500">Tidak ada kamar yang menunggu inspeksi</p>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {perluInspeksi.map(l => (
                <div key={l.id} className="rounded-xl border border-violet-200 bg-violet-50 p-4 flex items-center justify-between gap-3">
                  <div>
                    <div className="font-bold">Kamar {l.room_nomor}</div>
                    <div className="text-xs text-slate-600">Dibersihkan oleh {l.petugas || "-"} · {fmtDateTime(l.jam_selesai)}</div>
                  </div>
                  <Button data-testid={`hk-inspect-${l.room_nomor}`} size="sm" className="bg-violet-600 hover:bg-violet-700" onClick={() => inspect(l.room_id, l.room_nomor)}>
                    Tandai Diperiksa
                  </Button>
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
                <th className="p-2 text-left">Kamar</th><th className="p-2 text-left">Status</th>
                <th className="p-2 text-left">Mulai</th>
                <th className="p-2 text-left">Selesai</th><th className="p-2 text-left">Durasi</th>
                <th className="p-2 text-left">Petugas</th><th className="p-2 text-left">Catatan</th>
              </tr></thead>
              <tbody>
                {selesai.map(l => {
                  const durasi = l.jam_mulai && l.jam_selesai
                    ? `${Math.round((new Date(l.jam_selesai) - new Date(l.jam_mulai)) / 60000)} menit`
                    : "-";
                  return (
                    <tr key={l.id} className="border-t border-slate-100">
                      <td className="p-2 font-bold">{l.room_nomor}</td>
                      <td className="p-2">
                        {l.status === "inspected" ? (
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700 bg-emerald-100 px-2 py-1 rounded-full" title={l.inspected_by ? `Diperiksa oleh ${l.inspected_by}` : ""}>Inspected</span>
                        ) : (
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-violet-700 bg-violet-100 px-2 py-1 rounded-full">Clean</span>
                        )}
                      </td>
                      <td className="p-2">{l.jam_mulai ? fmtDateTime(l.jam_mulai) : "-"}</td>
                      <td className="p-2">{fmtDateTime(l.jam_selesai)}</td>
                      <td className="p-2">{durasi}</td>
                      <td className="p-2">{l.petugas || "-"}</td>
                      <td className="p-2 text-slate-600 max-w-[16rem] truncate" title={l.catatan}>{l.catatan || "-"}</td>
                    </tr>
                  );
                })}
                {selesai.length === 0 && <tr><td colSpan={7} className="p-6 text-center text-slate-500">Belum ada riwayat</td></tr>}
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
