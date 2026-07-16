import { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UserCircle, Send, Bell } from "lucide-react";
import { isPushSupported, subscribeToPush, unsubscribeFromPush, getPushStatus } from "@/lib/pushNotifications";

function PushNotifLink() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const cekStatus = () => getPushStatus().then(setStatus);
  useEffect(() => { cekStatus(); }, []);

  const aktifkan = async () => {
    setLoading(true);
    try {
      await subscribeToPush();
      toast.success("Notifikasi push diaktifkan");
      cekStatus();
    } catch (e) {
      toast.error(e?.message || "Gagal mengaktifkan notifikasi");
    } finally {
      setLoading(false);
    }
  };

  const matikan = async () => {
    try {
      await unsubscribeFromPush();
      toast.success("Notifikasi push dimatikan");
      cekStatus();
    } catch (e) {
      toast.error(e?.message || "Gagal");
    }
  };

  if (!status || !status.supported) return null;

  return (
    <Card className="border-slate-200">
      <CardContent className="p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-amber-100 grid place-items-center"><Bell className="w-5 h-5 text-amber-600" /></div>
          <div>
            <div className="font-semibold">Notifikasi Push</div>
            <div className="text-sm text-slate-500">Booking baru, pembayaran diterima, komplain, kamar perlu dibersihkan — walau tab PMS tidak dibuka.</div>
          </div>
        </div>
        {status.subscribed ? (
          <div className="flex items-center justify-between bg-emerald-50 border border-emerald-200 rounded-lg p-3">
            <span className="text-sm font-medium text-emerald-700" data-testid="push-status-aktif">✓ Aktif di perangkat ini</span>
            <Button size="sm" variant="outline" onClick={matikan} data-testid="push-matikan">Matikan</Button>
          </div>
        ) : (
          <Button onClick={aktifkan} disabled={loading} data-testid="push-aktifkan" className="bg-amber-600 hover:bg-amber-700">
            {loading ? "Mengaktifkan..." : "Aktifkan Notifikasi Push"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function TelegramLink() {
  const { user } = useAuth();
  const [connected, setConnected] = useState(null);
  const [kode, setKode] = useState(null);
  const [loading, setLoading] = useState(false);

  const cekStatus = () => api.get("/profil/telegram/status").then((r) => setConnected(r.data.connected)).catch(() => setConnected(false));
  useEffect(() => { cekStatus(); }, []);

  const generate = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/profil/telegram/generate-code");
      setKode(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal membuat kode link");
    } finally {
      setLoading(false);
    }
  };

  const putuskan = async () => {
    try {
      await api.post("/profil/telegram/putuskan");
      toast.success("Telegram diputuskan");
      setKode(null);
      cekStatus();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal");
    }
  };

  if (connected === null) return null;

  return (
    <Card className="border-slate-200">
      <CardContent className="p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-sky-100 grid place-items-center"><Send className="w-5 h-5 text-sky-600" /></div>
          <div>
            <div className="font-semibold">Bot Telegram {user?.role === "owner" ? "Owner" : "Staff"}</div>
            <div className="text-sm text-slate-500">
              {user?.role === "owner" ? "Dapat ringkasan bisnis kapan saja lewat chat" : "Kirim pengeluaran (foto+teks) & dapat laporan akhir hari"}
            </div>
          </div>
        </div>

        {connected ? (
          <div className="flex items-center justify-between bg-emerald-50 border border-emerald-200 rounded-lg p-3">
            <span className="text-sm font-medium text-emerald-700" data-testid="telegram-status-terhubung">✓ Sudah terhubung</span>
            <Button size="sm" variant="outline" onClick={putuskan} data-testid="telegram-putuskan">Putuskan</Button>
          </div>
        ) : kode ? (
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-2 text-sm">
            <p>Buka Telegram, cari bot yang sudah kamu buat, lalu kirim:</p>
            <p className="font-mono text-lg font-bold text-center py-2 bg-white rounded border" data-testid="telegram-kode">/start {kode.code}</p>
            {kode.deep_link && (
              <a href={kode.deep_link} target="_blank" rel="noreferrer" className="block text-center">
                <Button className="w-full bg-sky-600 hover:bg-sky-700" data-testid="telegram-buka-bot">Buka Bot di Telegram</Button>
              </a>
            )}
            <p className="text-xs text-slate-500 text-center">Kode berlaku 10 menit</p>
          </div>
        ) : (
          <Button onClick={generate} disabled={loading} data-testid="telegram-hubungkan" className="bg-sky-600 hover:bg-sky-700">
            {loading ? "Membuat kode..." : "Hubungkan Telegram"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default function Profil() {
  const { user, setUser } = useAuth();
  const [nama, setNama] = useState(user?.nama || "");
  const [passwordLama, setPasswordLama] = useState("");
  const [passwordBaru, setPasswordBaru] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async (e) => {
    e.preventDefault();
    if (passwordBaru && !passwordLama) {
      toast.error("Isi password lama untuk mengganti password");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.put("/auth/me", {
        nama,
        password_lama: passwordLama || undefined,
        password_baru: passwordBaru || undefined,
      });
      setUser(data);
      setPasswordLama("");
      setPasswordBaru("");
      toast.success("Profil tersimpan");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Gagal menyimpan profil");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Akun</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Profil Saya</h1>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-6 space-y-6">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full bg-slate-100 grid place-items-center">
              <UserCircle className="w-9 h-9 text-slate-400" />
            </div>
            <div>
              <div className="font-semibold text-lg">{user?.nama}</div>
              <div className="text-sm text-slate-500">
                <span className="font-mono">{user?.username}</span> · <span className="capitalize">{user?.role}</span>
              </div>
            </div>
          </div>

          <form onSubmit={save} className="space-y-4">
            <div>
              <Label htmlFor="profil-nama">Nama</Label>
              <Input id="profil-nama" data-testid="profil-nama" value={nama} onChange={(e) => setNama(e.target.value)} className="mt-1.5" />
            </div>

            <div className="border-t border-slate-100 pt-4 space-y-4">
              <p className="text-sm font-semibold text-slate-600">Ganti Password</p>
              <div>
                <Label htmlFor="profil-password-lama">Password Lama</Label>
                <Input id="profil-password-lama" data-testid="profil-password-lama" type="password" value={passwordLama} onChange={(e) => setPasswordLama(e.target.value)} className="mt-1.5" placeholder="Kosongkan jika tidak ganti password" />
              </div>
              <div>
                <Label htmlFor="profil-password-baru">Password Baru</Label>
                <Input id="profil-password-baru" data-testid="profil-password-baru" type="password" value={passwordBaru} onChange={(e) => setPasswordBaru(e.target.value)} className="mt-1.5" />
              </div>
            </div>

            <Button data-testid="profil-simpan" type="submit" disabled={saving} className="bg-blue-700 hover:bg-blue-800">
              {saving ? "Menyimpan…" : "Simpan Perubahan"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <PushNotifLink />
      <TelegramLink />
    </div>
  );
}
