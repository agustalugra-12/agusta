import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import { Trash2 } from "lucide-react";

const STATUS_LABEL = { open: "Open", in_progress: "In Progress", resolved: "Resolved" };
const STATUS_CLS = {
  open: "bg-red-100 text-red-700",
  in_progress: "bg-amber-100 text-amber-700",
  resolved: "bg-emerald-100 text-emerald-700",
};

export default function IssueBoard({ tipe, title, subtitle }) {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [rooms, setRooms] = useState([]);
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [roomId, setRoomId] = useState("");
  const [deskripsi, setDeskripsi] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    const [r, i] = await Promise.all([
      api.get("/rooms"),
      api.get("/issues", { params: { tipe, status: statusFilter || undefined } }),
    ]);
    setRooms(r.data);
    setItems(i.data);
  };
  useEffect(() => { load(); }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  const buat = async () => {
    if (!deskripsi.trim()) { toast.error("Deskripsi wajib diisi"); return; }
    setSubmitting(true);
    try {
      const room = rooms.find(r => r.id === roomId);
      await api.post("/issues", { tipe, room_id: roomId || null, room_nomor: room?.nomor || "", deskripsi: deskripsi.trim() });
      toast.success("Tercatat");
      setDeskripsi(""); setRoomId("");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
    finally { setSubmitting(false); }
  };

  const ubahStatus = async (it, status) => {
    try {
      await api.put(`/issues/${it.id}/status`, { status });
      toast.success("Status diperbarui");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const hapus = async (it) => {
    try {
      await api.delete(`/issues/${it.id}`);
      toast.success("Dihapus");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  const counts = { open: 0, in_progress: 0, resolved: 0 };
  items.forEach(it => { counts[it.status] = (counts[it.status] || 0) + 1; });

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">{title}</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">{title}</h1>
        <p className="text-slate-500 text-sm mt-1">{subtitle}</p>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-5 space-y-3">
          <h2 className="font-bold">Laporkan Baru</h2>
          <div className="grid sm:grid-cols-[220px_1fr] gap-3">
            <select
              data-testid="issue-room-select"
              value={roomId}
              onChange={(e) => setRoomId(e.target.value)}
              className="h-11 rounded-md border border-slate-300 px-3 bg-white text-sm"
            >
              <option value="">Kamar (opsional)</option>
              {rooms.map(r => <option key={r.id} value={r.id}>Kamar {r.nomor} ({r.tipe})</option>)}
            </select>
            <Textarea
              data-testid="issue-deskripsi"
              value={deskripsi}
              onChange={(e) => setDeskripsi(e.target.value)}
              placeholder={tipe === "complaint" ? "Mis: Handuk belum ada di kamar" : "Mis: Shower rusak, air tidak keluar"}
              rows={2}
            />
          </div>
          <Button data-testid="issue-submit" onClick={buat} disabled={submitting} className="bg-blue-700 hover:bg-blue-800">
            {submitting ? "Menyimpan..." : "Simpan"}
          </Button>
        </CardContent>
      </Card>

      <div className="flex gap-2 flex-wrap">
        {[["", "Semua"], ["open", `Open (${counts.open || 0})`], ["in_progress", `In Progress (${counts.in_progress || 0})`], ["resolved", `Resolved (${counts.resolved || 0})`]].map(([k, lbl]) => (
          <Button key={k} size="sm" variant={statusFilter === k ? "default" : "outline"} className={statusFilter === k ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setStatusFilter(k)}>{lbl}</Button>
        ))}
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map(it => (
          <Card key={it.id} className="border-slate-200" data-testid={`issue-card-${it.id}`}>
            <CardContent className="p-4 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="font-bold">{it.room_nomor ? `Kamar ${it.room_nomor}` : "Umum"}</div>
                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full shrink-0 ${STATUS_CLS[it.status]}`}>{STATUS_LABEL[it.status]}</span>
              </div>
              <p className="text-sm text-slate-700">{it.deskripsi}</p>
              {it.catatan_penyelesaian && (
                <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded p-2">Catatan: {it.catatan_penyelesaian}</p>
              )}
              <div className="text-xs text-slate-400">
                Dilaporkan {it.created_by} • {fmtDateTime(it.created_at)}
                {it.resolved_by && <> • Selesai oleh {it.resolved_by}</>}
              </div>
              <div className="flex gap-2 pt-1">
                {it.status !== "in_progress" && it.status !== "resolved" && (
                  <Button size="sm" variant="outline" onClick={() => ubahStatus(it, "in_progress")}>Tangani</Button>
                )}
                {it.status !== "resolved" && (
                  <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => ubahStatus(it, "resolved")}>Selesai</Button>
                )}
                {it.status === "resolved" && (
                  <Button size="sm" variant="outline" onClick={() => ubahStatus(it, "open")}>Buka Lagi</Button>
                )}
                {isOwner && (
                  <Button size="icon" variant="ghost" onClick={() => hapus(it)}><Trash2 className="w-3.5 h-3.5 text-red-500" /></Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
        {items.length === 0 && <div className="col-span-full text-center text-slate-500 py-10">Tidak ada data</div>}
      </div>
    </div>
  );
}
