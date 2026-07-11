import { useState } from "react";
import { toast } from "sonner";
import api from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UserCircle } from "lucide-react";

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
    </div>
  );
}
