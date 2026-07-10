import { useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { MessageCircle, Save, Eye, EyeOff, CheckCircle2, XCircle } from "lucide-react";
import { fmtDateTime } from "@/lib/apiClient";

// Provider webhook WhatsApp pihak ketiga yang umum dipakai bisnis di Indonesia.
const PROVIDER_OPTIONS = ["Fonnte", "Wablas", "Qontak", "Lainnya (Custom API)"];

// Data tiruan (stub) — konfigurasi webhook WhatsApp Bot yang sudah tersimpan.
const MOCK_CONFIG = {
  aktif: true,
  provider: "Fonnte",
  webhook_url: "https://api.fonnte.com/send",
  api_key: "fonnte_live_sk_8f2a9c7b3e4d5061a2b3c4d5e6f7",
  nomor_whatsapp: "628123456789",
  updated_at: "2026-07-10T14:30:00",
};

export default function KonfigurasiWebhook() {
  const [saved, setSaved] = useState(MOCK_CONFIG);
  const [form, setForm] = useState(MOCK_CONFIG);
  const [showKey, setShowKey] = useState(false);

  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const valid = form.provider && form.webhook_url.trim() && form.api_key.trim() && form.nomor_whatsapp.trim();

  const maskedKey = (key) => (key.length <= 8 ? "••••••••" : `${key.slice(0, 6)}${"•".repeat(Math.min(16, key.length - 10))}${key.slice(-4)}`);

  const simpan = () => {
    const now = new Date().toISOString();
    const next = { ...form, updated_at: now };
    setSaved(next);
    setForm(next);
    toast.success("Konfigurasi webhook WhatsApp disimpan");
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
        <CardContent className="p-4 flex items-center gap-3">
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
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-4 space-y-4">
          <h3 className="text-sm font-semibold text-slate-700">Endpoint &amp; Kredensial</h3>
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
              className="mt-1.5 font-mono text-sm"
            />
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
                className="font-mono text-sm pr-10"
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
            {!showKey && form.api_key === saved.api_key && (
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
              className="mt-1.5"
            />
          </div>
          <Button data-testid="webhook-simpan" onClick={simpan} disabled={!valid || !dirty} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
            <Save className="w-3.5 h-3.5" /> Simpan Konfigurasi
          </Button>
          <p className="text-[11px] text-slate-400">Data tiruan — belum terhubung ke penyedia WhatsApp sungguhan.</p>
        </CardContent>
      </Card>
    </div>
  );
}
