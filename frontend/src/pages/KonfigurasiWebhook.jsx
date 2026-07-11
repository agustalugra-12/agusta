import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { MessageCircle, Save, Eye, EyeOff, CheckCircle2, XCircle, Zap, Loader2, Undo2, AlertCircle } from "lucide-react";
import api, { fmtDateTime } from "@/lib/apiClient";

// Provider webhook WhatsApp pihak ketiga yang umum dipakai bisnis di Indonesia.
const PROVIDER_OPTIONS = ["Fonnte", "Wablas", "Qontak", "Lainnya (Custom API)"];

const EMPTY_CONFIG = {
  aktif: false, provider: "Fonnte", webhook_url: "", api_key: "", nomor_whatsapp: "", updated_at: null,
};

export default function KonfigurasiWebhook() {
  const [saved, setSaved] = useState(EMPTY_CONFIG);
  const [form, setForm] = useState(EMPTY_CONFIG);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // { ok, message, tested_at }
  const [attemptedSave, setAttemptedSave] = useState(false);

  useEffect(() => {
    api.get("/konfigurasi-webhook").then((r) => { setSaved(r.data); setForm(r.data); }).catch(() => {});
  }, []);

  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const errors = {
    webhook_url: !form.webhook_url.trim() && "Wajib diisi",
    api_key: !form.api_key.trim() && "Wajib diisi",
    nomor_whatsapp: !form.nomor_whatsapp.trim() && "Wajib diisi",
  };
  const valid = !errors.webhook_url && !errors.api_key && !errors.nomor_whatsapp;

  const maskedKey = (key) => (key.length <= 8 ? "••••••••" : `${key.slice(0, 6)}${"•".repeat(Math.min(16, key.length - 10))}${key.slice(-4)}`);

  const simpan = async () => {
    setAttemptedSave(true);
    if (!valid) { toast.error("Lengkapi dulu field yang wajib diisi"); return; }
    try {
      const { data } = await api.put("/konfigurasi-webhook", { ...form, aktif: true });
      setSaved(data);
      setForm(data);
      setTestResult(null);
      setAttemptedSave(false);
      toast.success("Konfigurasi webhook WhatsApp disimpan");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan konfigurasi");
    }
  };

  const batalkanPerubahan = () => {
    setForm(saved);
    setAttemptedSave(false);
  };

  const ujiKoneksi = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data } = await api.post("/konfigurasi-webhook/test");
      setTestResult(data);
      if (data.ok) toast.success("Uji koneksi berhasil"); else toast.error("Uji koneksi gagal");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menguji koneksi");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="konfigurasi-webhook-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Konfigurasi Webhook</h1>
        <p className="text-slate-500 mt-1">
          Hubungkan sistem dengan penyedia layanan WhatsApp agar bot bisa membaca ketersediaan &amp; membuat reservasi otomatis.
        </p>
      </div>

      <Card className={saved.aktif ? "border-emerald-300 bg-emerald-50" : "border-slate-200"}>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className={`w-11 h-11 rounded-xl grid place-items-center shrink-0 ${saved.aktif ? "bg-emerald-100 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
                <MessageCircle className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <div className="font-semibold flex items-center gap-1.5" data-testid="webhook-status-label">
                  {saved.aktif ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : <XCircle className="w-4 h-4 text-slate-400" />}
                  {saved.aktif ? `Aktif — ${saved.provider}` : "Belum Dikonfigurasi"}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  Nomor bot: {saved.nomor_whatsapp} &bull; Terakhir diperbarui: {fmtDateTime(saved.updated_at)}
                </div>
              </div>
            </div>
            <Button data-testid="webhook-uji-koneksi" variant="outline" size="sm" onClick={ujiKoneksi} disabled={testing} className="gap-1.5 shrink-0">
              {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />} {testing ? "Menguji…" : "Uji Koneksi"}
            </Button>
          </div>
          {testResult && (
            <div
              data-testid="webhook-test-result"
              className={`text-xs rounded-lg p-2.5 flex items-start gap-2 ${testResult.ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}
            >
              {testResult.ok ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" /> : <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
              <span>{testResult.message} <span className="opacity-70">({fmtDateTime(testResult.tested_at)})</span></span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">Endpoint &amp; Kredensial</h3>
            {dirty && (
              <span data-testid="webhook-dirty-badge" className="text-[10px] uppercase font-bold text-amber-700 bg-amber-100 px-2 py-1 rounded">
                Perubahan belum disimpan
              </span>
            )}
          </div>
          <div>
            <Label htmlFor="webhook-provider">Penyedia Layanan WhatsApp</Label>
            <select
              id="webhook-provider"
              data-testid="webhook-provider"
              value={form.provider}
              onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
            >
              {PROVIDER_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <Label htmlFor="webhook-url">Webhook / Endpoint URL</Label>
            <Input
              id="webhook-url"
              data-testid="webhook-url"
              value={form.webhook_url}
              onChange={(e) => setForm((f) => ({ ...f, webhook_url: e.target.value }))}
              placeholder="https://api.penyedia.com/send"
              className={`mt-1.5 font-mono text-sm ${attemptedSave && errors.webhook_url ? "border-red-400 focus-visible:ring-red-400" : ""}`}
            />
            {attemptedSave && errors.webhook_url && (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> {errors.webhook_url}</p>
            )}
          </div>
          <div>
            <Label htmlFor="webhook-api-key">API Key / Token</Label>
            <div className="relative mt-1.5">
              <Input
                id="webhook-api-key"
                data-testid="webhook-api-key"
                type={showKey ? "text" : "password"}
                value={form.api_key}
                onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                className={`font-mono text-sm pr-10 ${attemptedSave && errors.api_key ? "border-red-400 focus-visible:ring-red-400" : ""}`}
              />
              <button
                type="button"
                data-testid="webhook-toggle-key"
                onClick={() => setShowKey((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {attemptedSave && errors.api_key ? (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> {errors.api_key}</p>
            ) : !showKey && form.api_key === saved.api_key && (
              <p className="text-xs text-slate-400 mt-1 font-mono">Tersimpan: {maskedKey(saved.api_key)}</p>
            )}
          </div>
          <div>
            <Label htmlFor="webhook-nomor">Nomor WhatsApp Bot</Label>
            <Input
              id="webhook-nomor"
              data-testid="webhook-nomor"
              value={form.nomor_whatsapp}
              onChange={(e) => setForm((f) => ({ ...f, nomor_whatsapp: e.target.value }))}
              placeholder="628123456789"
              className={`mt-1.5 ${attemptedSave && errors.nomor_whatsapp ? "border-red-400 focus-visible:ring-red-400" : ""}`}
            />
            {attemptedSave && errors.nomor_whatsapp && (
              <p className="text-xs text-red-600 mt-1 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> {errors.nomor_whatsapp}</p>
            )}
          </div>
          <div className="flex gap-2">
            <Button data-testid="webhook-simpan" onClick={simpan} disabled={!dirty} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
              <Save className="w-3.5 h-3.5" /> Simpan Konfigurasi
            </Button>
            {dirty && (
              <Button data-testid="webhook-batal" variant="ghost" onClick={batalkanPerubahan} className="gap-1.5">
                <Undo2 className="w-3.5 h-3.5" /> Batalkan Perubahan
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
