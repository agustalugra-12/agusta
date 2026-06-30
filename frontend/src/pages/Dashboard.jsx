import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api, { fmtRp, statusLabel, statusColor } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import {
  BedDouble, AlertTriangle, Hourglass, Clock, Wallet,
  CalendarRange, Users as UsersIcon, Sparkles, Wrench,
} from "lucide-react";

const STAT_CARDS = [
  { key: "kosong", label: "Kosong", icon: BedDouble, color: "#10B981" },
  { key: "day_use", label: "Day Use", icon: Clock, color: "#EF4444" },
  { key: "menginap", label: "Menginap", icon: BedDouble, color: "#3B82F6" },
  { key: "perlu_dibersihkan", label: "Perlu Bersih", icon: Sparkles, color: "#F97316" },
  { key: "maintenance", label: "Maintenance", icon: Wrench, color: "#EAB308" },
];

export default function Dashboard() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [summary, setSummary] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [active, setActive] = useState([]);
  const [actionRoom, setActionRoom] = useState(null);
  const [statusForm, setStatusForm] = useState({ status: "", nama_tamu: "", catatan: "" });

  const load = async () => {
    try {
      const [s, r, c] = await Promise.all([
        api.get("/reports/summary"),
        api.get("/rooms"),
        api.get("/checkins", { params: { status: "aktif" } }),
      ]);
      setSummary(s.data); setRooms(r.data); setActive(c.data);
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  // notify overdue (>=5h since checkin) — simple banner
  const nearDue = active.filter(c => (Date.now() - new Date(c.jam_checkin).getTime()) / 3600000 >= 5);
  const overtime = active.filter(c => (Date.now() - new Date(c.jam_checkin).getTime()) / 3600000 >= 6);

  const handleRoomClick = (room) => {
    if (room.status === "day_use") {
      // navigate to checkout
      const ci = active.find((x) => x.room_id === room.id);
      if (ci) nav(`/checkout/${ci.id}`);
      else toast.error("Data check-in tidak ditemukan");
      return;
    }
    if (room.status === "kosong") {
      nav(`/checkin/${room.id}`);
      return;
    }
    setActionRoom(room);
    setStatusForm({ status: room.status, nama_tamu: room.info?.nama_tamu || "", catatan: room.info?.catatan || "" });
  };

  const changeStatus = async (newStatus) => {
    try {
      await api.put(`/rooms/${actionRoom.id}/status`, {
        status: newStatus,
        nama_tamu: statusForm.nama_tamu,
        catatan: statusForm.catatan,
      });
      toast.success("Status kamar diubah");
      setActionRoom(null);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal mengubah status"); }
  };

  const housekeepingDone = async () => {
    try {
      await api.post(`/rooms/${actionRoom.id}/housekeeping-done`, { petugas: user?.nama });
      toast.success("Kamar selesai dibersihkan");
      setActionRoom(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Dashboard</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Selamat datang, {user?.nama?.split(" ")[0]} 👋</h1>
          <p className="text-slate-500 mt-1">Ringkasan operasional Pelangi Homestay hari ini.</p>
        </div>
      </div>

      {/* Alerts */}
      {overtime.length > 0 && (
        <div data-testid="overtime-alert" className="rounded-xl bg-red-50 border border-red-200 p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-red-800">{overtime.length} kamar overtime</div>
            <div className="text-red-700">
              {overtime.map(c => `Kamar ${c.room_nomor} (${c.nama_tamu})`).join(", ")}
            </div>
          </div>
        </div>
      )}
      {nearDue.length > overtime.length && (
        <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 flex items-start gap-3">
          <Hourglass className="w-5 h-5 text-amber-600 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-amber-800">{nearDue.length - overtime.length} tamu mendekati batas 6 jam</div>
          </div>
        </div>
      )}

      {/* Status cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4">
        {STAT_CARDS.map((s) => (
          <Card key={s.key} className="border-slate-200">
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500">{s.label}</div>
                  <div className="text-3xl font-extrabold mt-1" style={{ color: s.color }}>
                    {summary?.rooms?.[s.key] ?? "—"}
                  </div>
                </div>
                <div className="w-9 h-9 rounded-lg grid place-items-center" style={{ background: s.color + "1A", color: s.color }}>
                  <s.icon className="w-5 h-5" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <RevCard icon={UsersIcon} label="Tamu Hari Ini" value={summary?.tamu_hari_ini ?? "—"} hint={`${summary?.checkout_hari_ini ?? 0} sudah check-out`} />
        <RevCard icon={Wallet} label="Pendapatan Hari Ini" value={fmtRp(summary?.pendapatan_hari_ini || 0)} hint={`Kamar ${fmtRp(summary?.pendapatan_kamar_hari_ini || 0)} • Kasir ${fmtRp(summary?.pendapatan_kasir_hari_ini || 0)}`} />
        <RevCard icon={CalendarRange} label="Pendapatan Bulan Ini" value={fmtRp(summary?.pendapatan_bulan_ini || 0)} hint="Total semua transaksi" />
        <RevCard icon={Wallet} label="Laba Bersih Bulan" value={fmtRp(summary?.laba_bersih_bulan_ini || 0)} hint={`Pengeluaran ${fmtRp(summary?.pengeluaran_bulan_ini || 0)}`} />
      </div>

      {/* Room grid */}
      <Card className="border-slate-200">
        <CardContent className="p-4 sm:p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold">Daftar Kamar</h2>
            <div className="flex flex-wrap gap-3 text-xs">
              {STAT_CARDS.map((s) => (
                <div key={s.key} className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm" style={{ background: s.color }} />
                  <span className="text-slate-600">{s.label}</span>
                </div>
              ))}
            </div>
          </div>
          <div data-testid="room-grid" className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
            {rooms.map((r) => (
              <button
                key={r.id}
                data-testid={`room-${r.nomor}`}
                onClick={() => handleRoomClick(r)}
                className="room-card relative rounded-xl text-white p-4 aspect-square flex flex-col justify-between text-left"
                style={{ background: statusColor(r.status) }}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-semibold tracking-wider opacity-90">{r.tipe}</span>
                  <span className="text-[10px] bg-white/25 rounded px-1.5 py-0.5">{statusLabel(r.status)}</span>
                </div>
                <div className="text-3xl sm:text-4xl font-extrabold">{r.nomor}</div>
                <div className="text-[11px] opacity-90 truncate">
                  {r.status === "kosong" ? fmtRp(r.tarif) : (r.info?.nama_tamu || "—")}
                </div>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Action Dialog */}
      <Dialog open={!!actionRoom} onOpenChange={(o) => !o && setActionRoom(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Kamar {actionRoom?.nomor} — {actionRoom?.tipe}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-sm" style={{ background: statusColor(actionRoom?.status) }} />
              <span className="font-medium">{statusLabel(actionRoom?.status)}</span>
            </div>
            {actionRoom?.status === "menginap" && (
              <>
                <div><span className="text-slate-500">Tamu:</span> {actionRoom?.info?.nama_tamu || "-"}</div>
                <div><span className="text-slate-500">Catatan:</span> {actionRoom?.info?.catatan || "-"}</div>
              </>
            )}
            {actionRoom?.status === "perlu_dibersihkan" && (
              <p className="text-slate-600">Tekan tombol di bawah jika kamar sudah selesai dibersihkan.</p>
            )}
            {(actionRoom?.status === "menginap" || actionRoom?.status === "maintenance") && (
              <>
                <div>
                  <Label>Nama tamu (untuk menginap)</Label>
                  <Input data-testid="status-nama-tamu" value={statusForm.nama_tamu} onChange={(e) => setStatusForm(f => ({ ...f, nama_tamu: e.target.value }))} />
                </div>
                <div>
                  <Label>Catatan</Label>
                  <Textarea data-testid="status-catatan" value={statusForm.catatan} onChange={(e) => setStatusForm(f => ({ ...f, catatan: e.target.value }))} />
                </div>
              </>
            )}
          </div>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            {actionRoom?.status === "perlu_dibersihkan" && (
              <Button data-testid="hk-done" onClick={housekeepingDone} className="bg-emerald-600 hover:bg-emerald-700">Selesai Dibersihkan</Button>
            )}
            {actionRoom?.status === "menginap" && (
              <Button data-testid="selesai-menginap" onClick={() => changeStatus("kosong")} className="bg-emerald-600 hover:bg-emerald-700">Selesai Menginap</Button>
            )}
            {actionRoom?.status === "maintenance" && (
              <Button data-testid="selesai-maintenance" onClick={() => changeStatus("kosong")} className="bg-emerald-600 hover:bg-emerald-700">Kembalikan ke Kosong</Button>
            )}
            {actionRoom?.status === "kosong" && (
              <>
                <Button data-testid="tandai-menginap" variant="outline" onClick={() => changeStatus("menginap")}>Tandai Menginap</Button>
                <Button data-testid="tandai-maintenance" variant="outline" onClick={() => changeStatus("maintenance")}>Tandai Maintenance</Button>
              </>
            )}
            <Button variant="ghost" onClick={() => setActionRoom(null)}>Tutup</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RevCard({ icon: Icon, label, value, hint }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
            <div className="text-2xl font-extrabold mt-1 break-words">{value}</div>
            {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
          </div>
          <div className="w-9 h-9 rounded-lg grid place-items-center bg-blue-50 text-blue-700">
            <Icon className="w-5 h-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
