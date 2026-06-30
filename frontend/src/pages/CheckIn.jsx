import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import api, { fmtRp } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ArrowLeft, Hotel } from "lucide-react";

export default function CheckIn() {
  const { roomId } = useParams();
  const nav = useNavigate();
  const [room, setRoom] = useState(null);
  // default jam_checkin = sekarang dalam format datetime-local (lokal browser)
  const initLocal = () => {
    const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  };
  const [form, setForm] = useState({
    nama_tamu: "", no_hp: "", no_identitas: "", kendaraan: "", jumlah_tamu: 1, catatan: "",
    jam_checkin: initLocal(),
  });
  const [submitting, setSubmitting] = useState(false);

  // Estimasi check-out = jam_checkin + 6 jam
  const estCheckout = (() => {
    if (!form.jam_checkin) return "";
    const d = new Date(form.jam_checkin);
    d.setHours(d.getHours() + 6);
    return d.toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  })();

  useEffect(() => {
    api.get("/rooms").then(r => {
      const found = r.data.find(x => x.id === roomId);
      if (!found) { toast.error("Kamar tidak ditemukan"); nav("/"); return; }
      if (found.status !== "kosong") { toast.error("Kamar tidak tersedia"); nav("/"); return; }
      setRoom(found);
    });
  }, [roomId, nav]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.nama_tamu.trim()) { toast.error("Nama tamu wajib diisi"); return; }
    setSubmitting(true);
    try {
      // konversi datetime-local ke ISO dengan timezone lokal
      const localIso = form.jam_checkin ? new Date(form.jam_checkin).toISOString() : undefined;
      const { data } = await api.post("/checkins", {
        ...form, room_id: roomId,
        jumlah_tamu: Number(form.jumlah_tamu) || 1,
        jam_checkin: localIso,
      });
      toast.success(`Check-in berhasil • ${data.trx_no}`);
      nav("/");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal check-in");
    } finally { setSubmitting(false); }
  };

  if (!room) return <div className="p-6 text-slate-500">Memuat…</div>;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <button onClick={() => nav("/")} className="flex items-center gap-2 text-sm text-slate-600 hover:text-blue-700">
        <ArrowLeft className="w-4 h-4" /> Kembali
      </button>
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Check-In Tamu</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Kamar {room.nomor}</h1>
      </div>

      <Card className="border-blue-200 bg-blue-50/50">
        <CardContent className="p-4 sm:p-5 flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-700 text-white grid place-items-center">
            <Hotel className="w-6 h-6" />
          </div>
          <div className="flex-1">
            <div className="text-sm text-slate-600">{room.tipe}</div>
            <div className="text-lg font-bold">Tarif Dasar: {fmtRp(room.tarif)} / 6 jam</div>
            <div className="text-xs text-slate-500">Overtime Rp 20.000 / jam</div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-5 sm:p-6">
          <form onSubmit={submit} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Nama Tamu *" testid="ci-nama">
              <Input value={form.nama_tamu} onChange={(e) => setForm(f => ({ ...f, nama_tamu: e.target.value }))} className="h-12" autoFocus />
            </Field>
            <Field label="Nomor HP" testid="ci-hp">
              <Input value={form.no_hp} onChange={(e) => setForm(f => ({ ...f, no_hp: e.target.value }))} className="h-12" placeholder="08xxxx" />
            </Field>
            <Field label="No KTP / Paspor" testid="ci-ktp">
              <Input value={form.no_identitas} onChange={(e) => setForm(f => ({ ...f, no_identitas: e.target.value }))} className="h-12" />
            </Field>
            <Field label="Kendaraan" testid="ci-kendaraan">
              <Input value={form.kendaraan} onChange={(e) => setForm(f => ({ ...f, kendaraan: e.target.value }))} className="h-12" placeholder="Plat / jenis" />
            </Field>
            <Field label="Jumlah Tamu" testid="ci-jumlah">
              <Input type="number" min="1" value={form.jumlah_tamu} onChange={(e) => setForm(f => ({ ...f, jumlah_tamu: e.target.value }))} className="h-12" />
            </Field>
            <Field label="Jam Check-In" testid="ci-jam">
              <Input type="datetime-local" value={form.jam_checkin} onChange={(e) => setForm(f => ({ ...f, jam_checkin: e.target.value }))} className="h-12" />
            </Field>
            <div className="sm:col-span-2 rounded-lg bg-blue-50 border border-blue-200 p-3 text-sm flex items-center justify-between flex-wrap gap-2">
              <div>
                <div className="text-blue-700 font-semibold">Estimasi jam check-out (6 jam dari check-in)</div>
                <div className="text-xs text-slate-600">Setelah lewat 6 jam akan dikenakan overtime Rp 20.000 / jam saat check-out.</div>
              </div>
              <div className="text-lg font-extrabold text-blue-700">{estCheckout || "—"}</div>
            </div>
            <div className="sm:col-span-2">
              <Label>Catatan</Label>
              <Textarea data-testid="ci-catatan" value={form.catatan} onChange={(e) => setForm(f => ({ ...f, catatan: e.target.value }))} className="mt-1.5" rows={3} />
            </div>
            <div className="sm:col-span-2 flex flex-col sm:flex-row gap-3 mt-2">
              <Button data-testid="ci-submit" type="submit" disabled={submitting} className="h-12 text-base bg-blue-700 hover:bg-blue-800 flex-1">
                {submitting ? "Memproses…" : "Konfirmasi Check-In"}
              </Button>
              <Button type="button" variant="outline" onClick={() => nav("/")} className="h-12">Batal</Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, testid, children }) {
  return (
    <div>
      <Label>{label}</Label>
      <div className="mt-1.5" data-testid={testid}>{children}</div>
    </div>
  );
}
