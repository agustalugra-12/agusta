import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import api, { fmtRp } from "@/lib/apiClient";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from "recharts";

// Fase 3 "Laporan & Analitik" — beda dari halaman "Laporan" (P&L operasional Fase 1).
// Fokus di sini: pendapatan, performa saluran (OTA/Website/WhatsApp), dan tren okupansi —
// metrik yang baru relevan setelah booking multi-saluran (Fase 2) tersedia. Data nyata dari
// backend/routes/laporan_analitik.py (collection `bookings` + `checkins`).
const SALURAN = [
  { key: "ota", label: "OTA", color: "#3B82F6" },
  { key: "website", label: "Website", color: "#10B981" },
  { key: "whatsapp", label: "WhatsApp", color: "#F97316" },
];

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const shortTanggal = (iso) => iso.slice(5, 10);

function usePendapatanHarian(from, to) {
  const [data, setData] = useState([]);
  useEffect(() => {
    let live = true;
    api.get("/laporan-analitik/pendapatan", { params: { from_date: from, to_date: to } })
      .then(({ data: rows }) => { if (live) setData(rows.map((r) => ({ ...r, tanggal: shortTanggal(r.tanggal) }))); })
      .catch(() => { if (live) setData([]); });
    return () => { live = false; };
  }, [from, to]);
  return data;
}

function usePerformaSaluran(channel) {
  const [data, setData] = useState([]);
  useEffect(() => {
    let live = true;
    api.get("/laporan-analitik/performa-saluran", { params: { channel } })
      .then(({ data: rows }) => {
        if (!live) return;
        const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));
        setData(SALURAN.filter((s) => channel === "Semua" || s.key === channel).map((s) => ({ ...s, ...byKey[s.key] })));
      })
      .catch(() => { if (live) setData([]); });
    return () => { live = false; };
  }, [channel]);
  return data;
}

function useTrenOkupansi(from, to) {
  const [data, setData] = useState([]);
  useEffect(() => {
    let live = true;
    api.get("/laporan-analitik/tren-okupansi", { params: { from_date: from, to_date: to } })
      .then(({ data: rows }) => { if (live) setData(rows.map((r) => ({ ...r, tanggal: shortTanggal(r.tanggal) }))); })
      .catch(() => { if (live) setData([]); });
    return () => { live = false; };
  }, [from, to]);
  return data;
}

function ChartCard({ title, children }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-5">
        <h3 className="font-bold mb-3">{title}</h3>
        {children}
      </CardContent>
    </Card>
  );
}

function PeriodeSaluranPicker({ from, setFrom, to, setTo, channel, setChannel }) {
  const setPreset = (p) => {
    if (p === "7") { setFrom(daysAgo(6)); setTo(today()); }
    if (p === "30") { setFrom(daysAgo(29)); setTo(today()); }
    if (p === "month") { const d = new Date(); setFrom(new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10)); setTo(today()); }
  };
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-5 flex flex-col sm:flex-row gap-3 items-end" data-testid="periode-saluran-picker">
        <div className="flex-1"><Label>Dari</Label><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-11 mt-1.5" data-testid="analitik-dari" /></div>
        <div className="flex-1"><Label>Sampai</Label><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-11 mt-1.5" data-testid="analitik-sampai" /></div>
        <div className="flex-1">
          <Label>Saluran</Label>
          <select
            value={channel} onChange={(e) => setChannel(e.target.value)} data-testid="analitik-saluran"
            className="w-full h-11 rounded-md border border-slate-300 px-3 bg-white mt-1.5 text-sm"
          >
            <option value="Semua">Semua Saluran</option>
            {SALURAN.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => setPreset("7")}>7 Hari</Button>
          <Button variant="outline" size="sm" onClick={() => setPreset("30")}>30 Hari</Button>
          <Button variant="outline" size="sm" onClick={() => setPreset("month")}>Bulan Ini</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function GrafikPendapatan({ from, to }) {
  const data = usePendapatanHarian(from, to);
  const total = data.reduce((s, r) => s + r.pendapatan, 0);
  return (
    <ChartCard title={`Laporan Pendapatan — Total ${fmtRp(total)}`}>
      <div className="h-64 w-full" data-testid="grafik-pendapatan">
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
            <XAxis dataKey="tanggal" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => (v / 1000000).toFixed(1) + "jt"} width={48} />
            <Tooltip formatter={(v) => fmtRp(v)} />
            <Line type="monotone" dataKey="pendapatan" stroke="#1E40AF" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function DiagramPerformaSaluran({ channel }) {
  const data = usePerformaSaluran(channel);
  return (
    <ChartCard title="Performa Saluran">
      <div className="h-64 w-full" data-testid="diagram-performa-saluran">
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => (v / 1000000).toFixed(0) + "jt"} />
            <YAxis type="category" dataKey="label" tick={{ fontSize: 12, fontWeight: 600 }} width={80} />
            <Tooltip formatter={(v, n) => n === "pendapatan" ? fmtRp(v) : v} />
            <Bar dataKey="pendapatan" radius={[0, 4, 4, 0]} barSize={28}>
              {data.map((d) => <Cell key={d.key} fill={d.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3 text-xs">
        {data.map((d) => (
          <span key={d.key} className="flex items-center gap-1.5 text-slate-600">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: d.color }} />
            {d.label} — <b>{d.booking} booking</b>
          </span>
        ))}
      </div>
    </ChartCard>
  );
}

function GrafikTrenOkupansi({ from, to }) {
  const data = useTrenOkupansi(from, to);
  const rata2 = Math.round(data.reduce((s, r) => s + r.okupansi, 0) / (data.length || 1));
  return (
    <ChartCard title={`Tren Okupansi — Rata-rata ${rata2}%`}>
      <div className="h-64 w-full" data-testid="grafik-tren-okupansi">
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
            <XAxis dataKey="tanggal" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => v + "%"} domain={[0, 100]} width={40} />
            <Tooltip formatter={(v) => v + "%"} />
            <Line type="monotone" dataKey="okupansi" stroke="#10B981" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

export default function LaporanAnalitik() {
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(today());
  const [channel, setChannel] = useState("Semua");

  return (
    <div className="space-y-6" data-testid="laporan-analitik-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 3 — Manajemen Sistem Internal</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Laporan &amp; Analitik</h1>
        <p className="text-slate-500 mt-1">Pendapatan, performa saluran, dan tren okupansi dari data booking multi-saluran sungguhan. Kosong/nol sampai ada booking online/OTA/WhatsApp yang lunas.</p>
      </div>

      <PeriodeSaluranPicker from={from} setFrom={setFrom} to={to} setTo={setTo} channel={channel} setChannel={setChannel} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GrafikPendapatan from={from} to={to} />
        <DiagramPerformaSaluran channel={channel} />
        <div className="lg:col-span-2"><GrafikTrenOkupansi from={from} to={to} /></div>
      </div>
    </div>
  );
}
