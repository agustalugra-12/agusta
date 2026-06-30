import { useEffect, useMemo, useState } from "react";
import api, { fmtRp } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, LineChart, Line,
} from "recharts";

function todayIso() { return new Date().toISOString().slice(0, 10); }
function daysAgo(n) { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); }

export default function Laporan() {
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(todayIso());
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);

  const load = async () => {
    const [d, s] = await Promise.all([
      api.get("/reports/daily", { params: { from_date: from, to_date: to } }),
      api.get("/reports/summary"),
    ]);
    setRows(d.data); setSummary(s.data);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [from, to]);

  const totals = useMemo(() => {
    const t = { kamar: 0, makanan: 0, minuman: 0, laundry: 0, pengeluaran: 0, pendapatan: 0, laba: 0 };
    rows.forEach(r => { for (const k of Object.keys(t)) t[k] += r[k] || 0; });
    return t;
  }, [rows]);

  const exportCsv = () => {
    const head = ["Tanggal", "Kamar", "Makanan", "Minuman", "Laundry", "Pendapatan", "Pengeluaran", "Laba"];
    const lines = [head.join(",")].concat(rows.map(r => [r.tanggal, r.kamar, r.makanan, r.minuman, r.laundry, r.pendapatan, r.pengeluaran, r.laba].join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `laporan-${from}_${to}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  const setRange = (preset) => {
    if (preset === "today") { setFrom(todayIso()); setTo(todayIso()); }
    if (preset === "7") { setFrom(daysAgo(6)); setTo(todayIso()); }
    if (preset === "30") { setFrom(daysAgo(29)); setTo(todayIso()); }
    if (preset === "month") {
      const d = new Date(); const start = new Date(d.getFullYear(), d.getMonth(), 1);
      setFrom(start.toISOString().slice(0, 10)); setTo(todayIso());
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Laporan</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Pendapatan & Laba</h1>
        </div>
        <Button data-testid="export-csv" onClick={exportCsv} variant="outline">Export CSV</Button>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-4 sm:p-5 flex flex-col sm:flex-row gap-3 items-end">
          <div className="flex-1"><Label>Dari</Label><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-12 mt-1.5" /></div>
          <div className="flex-1"><Label>Sampai</Label><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-12 mt-1.5" /></div>
          <div className="flex gap-2 flex-wrap">
            <Button variant="outline" size="sm" onClick={() => setRange("today")}>Hari Ini</Button>
            <Button variant="outline" size="sm" onClick={() => setRange("7")}>7 Hari</Button>
            <Button variant="outline" size="sm" onClick={() => setRange("30")}>30 Hari</Button>
            <Button variant="outline" size="sm" onClick={() => setRange("month")}>Bulan Ini</Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Pendapatan" value={fmtRp(totals.pendapatan)} color="#1E40AF" />
        <Stat label="Pengeluaran" value={fmtRp(totals.pengeluaran)} color="#EF4444" />
        <Stat label="Laba Bersih" value={fmtRp(totals.laba)} color="#10B981" />
        <Stat label="Total Hari" value={rows.length} color="#64748B" />
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-5">
          <h2 className="font-bold mb-3">Grafik Pendapatan Harian</h2>
          <div className="h-72 w-full">
            <ResponsiveContainer>
              <BarChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="tanggal" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => (v / 1000).toFixed(0) + "k"} />
                <Tooltip formatter={(v) => fmtRp(v)} />
                <Legend />
                <Bar dataKey="kamar" stackId="a" fill="#1E40AF" />
                <Bar dataKey="makanan" stackId="a" fill="#10B981" />
                <Bar dataKey="minuman" stackId="a" fill="#3B82F6" />
                <Bar dataKey="laundry" stackId="a" fill="#F97316" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-5">
          <h2 className="font-bold mb-3">Laba Harian</h2>
          <div className="h-64 w-full">
            <ResponsiveContainer>
              <LineChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="tanggal" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => (v / 1000).toFixed(0) + "k"} />
                <Tooltip formatter={(v) => fmtRp(v)} />
                <Line type="monotone" dataKey="laba" stroke="#10B981" strokeWidth={3} />
                <Line type="monotone" dataKey="pengeluaran" stroke="#EF4444" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
              <tr>{["Tanggal", "Kamar", "Makanan", "Minuman", "Laundry", "Pendapatan", "Pengeluaran", "Laba"].map(h => <th key={h} className="text-left p-3">{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.tanggal} className="border-t border-slate-100">
                  <td className="p-3 font-semibold">{r.tanggal}</td>
                  <td className="p-3">{fmtRp(r.kamar)}</td>
                  <td className="p-3">{fmtRp(r.makanan)}</td>
                  <td className="p-3">{fmtRp(r.minuman)}</td>
                  <td className="p-3">{fmtRp(r.laundry)}</td>
                  <td className="p-3 font-bold text-blue-700">{fmtRp(r.pendapatan)}</td>
                  <td className="p-3 text-red-600">-{fmtRp(r.pengeluaran)}</td>
                  <td className="p-3 font-bold text-emerald-700">{fmtRp(r.laba)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={8} className="text-center text-slate-500 p-6">Tidak ada data</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4">
        <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
        <div className="text-2xl font-extrabold mt-1 break-words" style={{ color }}>{value}</div>
      </CardContent>
    </Card>
  );
}
