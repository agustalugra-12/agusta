import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Eye, EyeOff } from "lucide-react";
import { REGISTER } from "@/constants/testIds";
import api from "@/lib/apiClient";

export default function Register() {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (password !== passwordConfirm) {
      toast.error("Konfirmasi kata sandi tidak cocok");
      return;
    }
    if (password.length < 6) {
      toast.error("Kata sandi minimal 6 karakter");
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post("/auth/register", { nama: name.trim(), email: email.trim(), password });
      toast.success(data?.message || "Akun berhasil didaftarkan. Silakan masuk.");
      nav("/login", { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Pendaftaran gagal");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      <div
        className="hidden md:flex md:w-1/2 relative items-center justify-center p-10 text-white"
        style={{
          backgroundImage: "linear-gradient(135deg, rgba(15,76,92,0.95), rgba(8,61,56,0.92))",
        }}
      >
        <div className="max-w-md">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-12 h-12 rounded-2xl bg-white/15 backdrop-blur grid place-items-center overflow-hidden">
              <img src="/pelangi-logo.png" alt="Pelangi Homestay" className="w-9 h-9 object-contain" />
            </div>
            <div>
              <p className="text-xs tracking-[0.3em] uppercase opacity-80">Pelangi</p>
              <h2 className="text-2xl font-bold font-display">Homestay System</h2>
            </div>
          </div>
          <h1 className="text-4xl lg:text-5xl font-extrabold leading-tight font-display">Operasional Penginapan Day Use yang Cepat & Rapi.</h1>
          <p className="mt-6 text-white/80 text-lg">Check-in, kasir, kamar, laporan — semuanya dalam satu aplikasi yang siap dipakai resepsionis Anda.</p>
        </div>
      </div>
      <div className="flex-1 flex items-center justify-center p-6 bg-slate-50">
        <Card className="w-full max-w-md border-slate-200 shadow-none">
          <CardContent className="p-8">
            <div className="md:hidden flex items-center gap-3 mb-6">
              <div className="w-11 h-11 rounded-xl bg-teal grid place-items-center overflow-hidden">
                <img src="/pelangi-logo.png" alt="Pelangi Homestay" className="w-8 h-8 object-contain" />
              </div>
              <div>
                <p className="text-xs tracking-[0.3em] uppercase text-slate-500">Pelangi</p>
                <h2 className="text-xl font-bold font-display">Homestay System</h2>
              </div>
            </div>
            <h1 className="text-3xl font-extrabold mb-2 font-display">Daftar Akun</h1>
            <p className="text-slate-500 mb-6">Buat akun baru untuk mengakses Pelangi Homestay System.</p>
            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <Label htmlFor="name">Nama Lengkap</Label>
                <Input id="name" data-testid={REGISTER.nameInput} value={name} onChange={(e) => setName(e.target.value)} placeholder="cth: Budi Santoso" className="h-12 text-base mt-1.5" autoFocus required />
              </div>
              <div>
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" data-testid={REGISTER.emailInput} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="cth: budi@pelangi.id" className="h-12 text-base mt-1.5" required />
              </div>
              <div>
                <Label htmlFor="password">Kata Sandi</Label>
                <div className="relative mt-1.5">
                  <Input id="password" data-testid={REGISTER.passwordInput} type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} className="h-12 text-base pr-12" required />
                  <button type="button" aria-label="toggle" onClick={() => setShow(s => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700">
                    {show ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                  </button>
                </div>
              </div>
              <div>
                <Label htmlFor="passwordConfirm">Konfirmasi Kata Sandi</Label>
                <Input id="passwordConfirm" type={show ? "text" : "password"} data-testid={REGISTER.passwordConfirmInput} value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)} className="h-12 text-base mt-1.5" required />
              </div>
              <Button data-testid={REGISTER.submitButton} type="submit" disabled={loading} className="w-full h-12 text-base font-semibold bg-blue-700 hover:bg-blue-800">
                {loading ? "Memproses…" : "Daftar"}
              </Button>
            </form>
            <p className="text-sm text-slate-500 mt-6 text-center">
              Sudah punya akun?{" "}
              <Link to="/login" data-testid={REGISTER.loginLink} className="text-blue-700 font-semibold hover:underline">
                Masuk
              </Link>
            </p>
            <p className="text-[11px] text-slate-400 mt-4 text-center">Akun baru menunggu aktivasi Owner sebelum bisa digunakan untuk masuk.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
