import { useEffect, useMemo, useState } from "react";
import api, { fmtRp, fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, LineChart, Line,
} from "recharts";

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };

function downloadCsv(filename, headers, rows) {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [headers.map(esc).join(",")].concat(rows.map(r => r.map(esc).join(","))).join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function DateRange({ from, setFrom, to, setTo }) {
  const set = (p) => {
    if (p === "today") { setFrom(today()); setTo(today()); }
    if (p === "7") { setFrom(daysAgo(6)); setTo(today()); }
    if (p === "30") { setFrom(daysAgo(29)); setTo(today()); }
    if (p === "month") { const d = new Date(); setFrom(new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10)); setTo(today()); }
  };
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-5 flex flex-col sm:flex-row gap-3 items-end">
        <div className="flex-1"><Label>Dari</Label><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-11 mt-1.5" /></div>
        <div className="flex-1"><Label>Sampai</Label><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-11 mt-1.5" /></div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => set("today")}>Hari Ini</Button>
          <Button variant="outline" size="sm" onClick={() => set("7")}>7 Hari</Button>
          <Button variant="outline" size="sm" onClick={() => set("30")}>30 Hari</Button>
          <Button variant="outline" size="sm" onClick={() => set("month")}>Bulan Ini</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, color = "#1E40AF" }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4">
        <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
        <div className="text-xl font-extrabold mt-1 break-words" style={{ color }}>{value}</div>
      </CardContent>
    </Card>
  );
}

export default function Laporan() {
  const [tab, setTab] = useState("ringkasan");
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(today());

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Laporan</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Laporan & Analisis</h1>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex flex-wrap h-auto">
          <TabsTrigger value="ringkasan" data-testid="tab-ringkasan">Ringkasan</TabsTrigger>
          <TabsTrigger value="kamar" data-testid="tab-kamar">Laporan Kamar</TabsTrigger>
          <TabsTrigger value="kasir" data-testid="tab-kasir">Laporan Kasir</TabsTrigger>
          <TabsTrigger value="items" data-testid="tab-items">Item Terjual</TabsTrigger>
          <TabsTrigger value="top" data-testid="tab-top">Produk Terlaris</TabsTrigger>
        </TabsList>

        <div className="mt-4 space-y-4">
          {tab !== "top" && <DateRange from={from} setFrom={setFrom} to={to} setTo={setTo} />}

          <TabsContent value="ringkasan"><Ringkasan from={from} to={to} /></TabsContent>
          <TabsContent value="kamar"><LaporanKamar from={from} to={to} /></TabsContent>
          <TabsContent value="kasir"><LaporanKasir from={from} to={to} /></TabsContent>
          <TabsContent value="items"><LaporanItems from={from} to={to} /></TabsContent>
          <TabsContent value="top"><TopProducts /></TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function Ringkasan({ from, to }) {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/reports/daily", { params: { from_date: from, to_date: to } }).then(r => setRows(r.data)); }, [from, to]);
  const t = useMemo(() => {
    const t = { kamar: 0, makanan: 0, minuman: 0, laundry: 0, pengeluaran: 0, pendapatan: 0, laba: 0 };
    rows.forEach(r => { for (const k of Object.keys(t)) t[k] += r[k] || 0; });
    return t;
  }, [rows]);
  const exp = () => downloadCsv(`Laporan_Ringkasan_${from}_${to}.csv`,
    ["Tanggal", "Kamar", "Makanan", "Minuman", "Laundry", "Pendapatan", "Pengeluaran", "Laba"],
    rows.map(r => [r.tanggal, r.kamar, r.makanan, r.minuman, r.laundry, r.pendapatan, r.pengeluaran, r.laba]));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Pendapatan" value={fmtRp(t.pendapatan)} />
        <Stat label="Pengeluaran" value={fmtRp(t.pengeluaran)} color="#EF4444" />
        <Stat label="Laba Bersih" value={fmtRp(t.laba)} color="#10B981" />
        <Stat label="Hari" value={rows.length} color="#64748B" />
      </div>
      <Card className="border-slate-200"><CardContent className="p-5">
        <h3 className="font-bold mb-3">Grafik Pendapatan Harian</h3>
        <div className="h-72 w-full"><ResponsiveContainer>
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
        </ResponsiveContainer></div>
      </CardContent></Card>
      <Card className="border-slate-200"><CardContent className="p-5">
        <h3 className="font-bold mb-3">Laba vs Pengeluaran</h3>
        <div className="h-56 w-full"><ResponsiveContainer>
          <LineChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
            <XAxis dataKey="tanggal" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => (v / 1000).toFixed(0) + "k"} />
            <Tooltip formatter={(v) => fmtRp(v)} />
            <Line type="monotone" dataKey="laba" stroke="#10B981" strokeWidth={3} />
            <Line type="monotone" dataKey="pengeluaran" stroke="#EF4444" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer></div>
      </CardContent></Card>
      <Button onClick={exp} variant="outline" data-testid="export-ringkasan">Export CSV / Excel</Button>
    </div>
  );
}

function LaporanKamar({ from, to }) {
  const [data, setData] = useState({ summary: {}, items: [] });
  useEffect(() => { api.get("/reports/rooms", { params: { from_date: from, to_date: to } }).then(r => setData(r.data)); }, [from, to]);
  const s = data.summary || {};
  const exp = () => downloadCsv(`Laporan_Kamar_${from}_${to}.csv`,
    ["No Transaksi", "Tanggal Check-In", "Tanggal Check-Out", "Nama Tamu", "Kamar", "Tipe", "Tarif Dasar", "Overtime", "Total", "Petugas"],
    (data.items || []).map(c => [c.trx_no, fmtDateTime(c.jam_checkin), fmtDateTime(c.jam_checkout), c.nama_tamu, c.room_nomor, c.room_tipe, c.tarif_dasar, c.biaya_tambahan, c.total, c.petugas_checkout || c.petugas_checkin]));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Total Transaksi" value={s.total_transaksi || 0} />
        <Stat label="Jumlah Tamu" value={s.total_tamu || 0} />
        <Stat label="Kamar Terpakai" value={s.kamar_terpakai || 0} />
        <Stat label="Total Overtime" value={fmtRp(s.total_overtime || 0)} color="#F97316" />
        <Stat label="Pendapatan Standard" value={fmtRp(s.pendapatan_standard || 0)} />
        <Stat label="Pendapatan Cottage" value={fmtRp(s.pendapatan_cottage || 0)} />
        <Stat label="Total Pendapatan Kamar" value={fmtRp(s.total_pendapatan || 0)} color="#10B981" />
      </div>
      <div className="flex justify-end"><Button variant="outline" onClick={exp} data-testid="export-kamar">Export CSV</Button></div>
      <Card className="border-slate-200"><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase"><tr>
            {["No Trx", "Tamu", "Kamar", "Tipe", "Check-In", "Check-Out", "Tarif", "Overtime", "Total", "Petugas"].map(h => <th key={h} className="text-left p-3">{h}</th>)}
          </tr></thead>
          <tbody>
            {(data.items || []).map(c => (
              <tr key={c.id} className="border-t border-slate-100">
                <td className="p-3 font-mono text-xs">{c.trx_no}</td>
                <td className="p-3 font-semibold">{c.nama_tamu}</td>
                <td className="p-3 font-bold">{c.room_nomor}</td>
                <td className="p-3">{c.room_tipe}</td>
                <td className="p-3 text-xs">{fmtDateTime(c.jam_checkin)}</td>
                <td className="p-3 text-xs">{fmtDateTime(c.jam_checkout)}</td>
                <td className="p-3">{fmtRp(c.tarif_dasar)}</td>
                <td className="p-3 text-orange-600">{fmtRp(c.biaya_tambahan)}</td>
                <td className="p-3 font-bold text-blue-700">{fmtRp(c.total)}</td>
                <td className="p-3 text-xs">{c.petugas_checkout || c.petugas_checkin}</td>
              </tr>
            ))}
            {(data.items || []).length === 0 && <tr><td colSpan={10} className="p-6 text-center text-slate-500">Tidak ada transaksi</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}

function LaporanKasir({ from, to }) {
  const [data, setData] = useState({ summary: {}, items: [] });
  useEffect(() => { api.get("/reports/kasir-detail", { params: { from_date: from, to_date: to } }).then(r => setData(r.data)); }, [from, to]);
  const s = data.summary || {};
  const exp = () => {
    const rows = [];
    (data.items || []).forEach(t => {
      (t.items || []).forEach(it => rows.push([t.trx_no, fmtDateTime(t.timestamp), it.nama, it.kategori, it.qty, it.harga, it.subtotal, t.petugas]));
    });
    downloadCsv(`Laporan_Kasir_${from}_${to}.csv`,
      ["No Trx", "Tanggal", "Item", "Kategori", "Qty", "Harga", "Subtotal", "Petugas"], rows);
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Total Transaksi" value={s.total_transaksi || 0} />
        <Stat label="Makanan" value={fmtRp(s.total_makanan || 0)} color="#10B981" />
        <Stat label="Minuman" value={fmtRp(s.total_minuman || 0)} color="#3B82F6" />
        <Stat label="Laundry" value={fmtRp(s.total_laundry || 0)} color="#F97316" />
      </div>
      <div className="flex justify-end"><Button variant="outline" onClick={exp} data-testid="export-kasir">Export CSV</Button></div>
      <Card className="border-slate-200"><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase"><tr>
            {["No Trx", "Tanggal", "Item", "Kat", "Qty", "Harga", "Subtotal", "Petugas"].map(h => <th key={h} className="text-left p-3">{h}</th>)}
          </tr></thead>
          <tbody>
            {(data.items || []).flatMap(t => (t.items || []).map((it, idx) => (
              <tr key={t.id + idx} className="border-t border-slate-100">
                <td className="p-3 font-mono text-xs">{t.trx_no}</td>
                <td className="p-3 text-xs">{fmtDateTime(t.timestamp)}</td>
                <td className="p-3 font-semibold">{it.nama}</td>
                <td className="p-3 capitalize text-xs">{it.kategori}</td>
                <td className="p-3 text-center">{it.qty}</td>
                <td className="p-3">{fmtRp(it.harga)}</td>
                <td className="p-3 font-semibold">{fmtRp(it.subtotal)}</td>
                <td className="p-3 text-xs">{t.petugas}</td>
              </tr>
            )))}
            {(data.items || []).length === 0 && <tr><td colSpan={8} className="p-6 text-center text-slate-500">Tidak ada transaksi</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}

function LaporanItems({ from, to }) {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/reports/items-sold", { params: { from_date: from, to_date: to } }).then(r => setRows(r.data)); }, [from, to]);
  const exp = () => downloadCsv(`Laporan_Item_Terjual_${from}_${to}.csv`,
    ["Nama", "Kategori", "Harga Jual", "Qty Terjual", "Total Pendapatan"],
    rows.map(r => [r.nama, r.kategori, r.harga, r.qty, r.pendapatan]));
  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button variant="outline" onClick={exp} data-testid="export-items">Export CSV</Button></div>
      <Card className="border-slate-200"><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase"><tr>
            <th className="text-left p-3">#</th>
            <th className="text-left p-3">Produk</th>
            <th className="text-left p-3">Kategori</th>
            <th className="text-right p-3">Harga</th>
            <th className="text-right p-3">Qty</th>
            <th className="text-right p-3">Pendapatan</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.product_id} className="border-t border-slate-100">
                <td className="p-3 text-slate-400">{i + 1}</td>
                <td className="p-3 font-semibold">{r.nama}</td>
                <td className="p-3 capitalize">{r.kategori}</td>
                <td className="p-3 text-right">{fmtRp(r.harga)}</td>
                <td className="p-3 text-right font-bold">{r.qty}</td>
                <td className="p-3 text-right font-bold text-blue-700">{fmtRp(r.pendapatan)}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="p-6 text-center text-slate-500">Tidak ada penjualan</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}

function TopProducts() {
  const [period, setPeriod] = useState("month");
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/reports/top-products", { params: { period, limit: 10 } }).then(r => setRows(r.data.rows)); }, [period]);
  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        {[["today", "Hari Ini"], ["month", "Bulan Ini"], ["year", "Tahun Ini"]].map(([k, lbl]) => (
          <Button key={k} variant={period === k ? "default" : "outline"} className={period === k ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setPeriod(k)} data-testid={`top-${k}`}>{lbl}</Button>
        ))}
      </div>
      <Card className="border-slate-200"><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase"><tr>
            <th className="text-left p-3">Rank</th>
            <th className="text-left p-3">Produk</th>
            <th className="text-left p-3">Kategori</th>
            <th className="text-right p-3">Qty Terjual</th>
            <th className="text-right p-3">Pendapatan</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.kode} className="border-t border-slate-100">
                <td className="p-3 font-bold text-blue-700">#{i + 1}</td>
                <td className="p-3 font-semibold">{r.nama}</td>
                <td className="p-3 capitalize">{r.kategori}</td>
                <td className="p-3 text-right font-bold">{r.qty}</td>
                <td className="p-3 text-right font-bold text-emerald-700">{fmtRp(r.pendapatan)}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-slate-500">Belum ada data</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}
