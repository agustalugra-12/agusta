import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Hotel, Eye, EyeOff } from "lucide-react";
import { LOGIN } from "@/constants/testIds";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(username.trim(), password);
      toast.success("Selamat datang!");
      nav("/", { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login gagal");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      <div
        className="hidden md:flex md:w-1/2 relative items-center justify-center p-10 text-white"
        style={{
          backgroundImage:
            "linear-gradient(135deg, rgba(30,64,175,0.92), rgba(15,23,42,0.85)), url('https://images.pexels.com/photos/35747338/pexels-photo-35747338.jpeg')",
          backgroundSize: "cover", backgroundPosition: "center",
        }}
      >
        <div className="max-w-md">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-12 h-12 rounded-2xl bg-white/15 backdrop-blur grid place-items-center">
              <Hotel className="w-7 h-7" />
            </div>
            <div>
              <p className="text-xs tracking-[0.3em] uppercase opacity-80">Pelangi</p>
              <h2 className="text-2xl font-bold">Homestay System</h2>
            </div>
          </div>
          <h1 className="text-4xl lg:text-5xl font-extrabold leading-tight">Operasional Penginapan Day Use yang Cepat & Rapi.</h1>
          <p className="mt-6 text-white/80 text-lg">Check-in, kasir, kamar, laporan — semuanya dalam satu aplikasi yang siap dipakai resepsionis Anda.</p>
          <div className="mt-10 grid grid-cols-3 gap-4 text-center">
            {[
              ["18", "Kamar"], ["6 Jam", "Tarif Dasar"], ["24/7", "Offline Ready"],
            ].map(([v, l]) => (
              <div key={l} className="bg-white/10 rounded-xl py-4">
                <div className="text-2xl font-bold">{v}</div>
                <div className="text-xs uppercase tracking-wider text-white/70">{l}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="flex-1 flex items-center justify-center p-6 bg-slate-50">
        <Card className="w-full max-w-md border-slate-200 shadow-none">
          <CardContent className="p-8">
            <div className="md:hidden flex items-center gap-3 mb-6">
              <div className="w-11 h-11 rounded-xl bg-blue-700 grid place-items-center text-white">
                <Hotel className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs tracking-[0.3em] uppercase text-slate-500">Pelangi</p>
                <h2 className="text-xl font-bold">Homestay System</h2>
              </div>
            </div>
            <h1 className="text-3xl font-extrabold mb-2">Masuk</h1>
            <p className="text-slate-500 mb-6">Gunakan akun yang diberikan oleh Owner.</p>
            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <Label htmlFor="username">Username</Label>
                <Input id="username" data-testid="login-username" value={username} onChange={(e) => setUsername(e.target.value)} className="h-12 text-base mt-1.5" autoFocus />
              </div>
              <div>
                <Label htmlFor="password">Password</Label>
                <div className="relative mt-1.5">
                  <Input id="password" data-testid="login-password" type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} className="h-12 text-base pr-12" />
                  <button type="button" aria-label="toggle" onClick={() => setShow(s => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700">
                    {show ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                  </button>
                </div>
              </div>
              <Button data-testid="login-submit" type="submit" disabled={loading} className="w-full h-12 text-base font-semibold bg-blue-700 hover:bg-blue-800">
                {loading ? "Memproses…" : "Masuk"}
              </Button>
            </form>
            <p className="text-sm text-slate-500 mt-6 text-center">
              Belum punya akun?{" "}
              <Link to="/register" data-testid={LOGIN.registerLink} className="text-blue-700 font-semibold hover:underline">
                Daftar
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
