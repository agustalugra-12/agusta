import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDateTime } from "@/lib/apiClient";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, LineChart, Line, Cell,
} from "recharts";

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const shortTanggal = (iso) => iso.slice(5, 10);

const SALURAN = [
  { key: "ota", label: "OTA", color: "#3B82F6" },
  { key: "website", label: "Website", color: "#10B981" },
  { key: "whatsapp", label: "WhatsApp", color: "#F97316" },
];

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
    if (p === "year") { const d = new Date(); setFrom(new Date(d.getFullYear(), 0, 1).toISOString().slice(0, 10)); setTo(today()); }
  };
  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 sm:p-5 flex flex-col sm:flex-row gap-3 items-end">
        <div className="flex-1"><Label>Dari</Label><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-11 mt-1.5" /></div>
        <div className="flex-1"><Label>Sampai</Label><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-11 mt-1.5" /></div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => set("today")}>Harian</Button>
          <Button variant="outline" size="sm" onClick={() => set("7")}>Mingguan</Button>
          <Button variant="outline" size="sm" onClick={() => set("30")}>30 Hari</Button>
          <Button variant="outline" size="sm" onClick={() => set("month")}>Bulanan</Button>
          <Button variant="outline" size="sm" onClick={() => set("year")}>Tahunan</Button>
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
          <TabsTrigger value="expenses" data-testid="tab-expenses">Pengeluaran</TabsTrigger>
          <TabsTrigger value="shift" data-testid="tab-shift">Laporan Shift</TabsTrigger>
          <TabsTrigger value="service" data-testid="tab-service">Service</TabsTrigger>
          <TabsTrigger value="cancel" data-testid="tab-cancel">Cancel & No-Show</TabsTrigger>
          <TabsTrigger value="saluran" data-testid="tab-saluran">Analitik Saluran</TabsTrigger>
          <TabsTrigger value="ota-prepaid" data-testid="tab-ota-prepaid">OTA Prepaid</TabsTrigger>
        </TabsList>

        <div className="mt-4 space-y-4">
          {tab !== "top" && tab !== "saluran" && tab !== "ota-prepaid" && <DateRange from={from} setFrom={setFrom} to={to} setTo={setTo} />}

          <TabsContent value="ringkasan"><Ringkasan from={from} to={to} /></TabsContent>
          <TabsContent value="kamar"><LaporanKamar from={from} to={to} /></TabsContent>
          <TabsContent value="kasir"><LaporanKasir from={from} to={to} /></TabsContent>
          <TabsContent value="items"><LaporanItems from={from} to={to} /></TabsContent>
          <TabsContent value="expenses"><LaporanExpenses from={from} to={to} /></TabsContent>
          <TabsContent value="shift"><LaporanShift from={from} to={to} /></TabsContent>
          <TabsContent value="service"><LaporanService from={from} to={to} /></TabsContent>
          <TabsContent value="cancel"><LaporanCancel from={from} to={to} /></TabsContent>
          <TabsContent value="top"><TopProducts /></TabsContent>
          <TabsContent value="saluran"><LaporanSaluran /></TabsContent>
          <TabsContent value="ota-prepaid"><LaporanOtaPrepaid /></TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function KasMetodeBayar({ from, to }) {
  const [kas, setKas] = useState({ tunai: 0, qris: 0, transfer: 0, total: 0 });
  useEffect(() => { api.get("/reports/kas-metode-bayar", { params: { from_date: from, to_date: to } }).then(r => setKas(r.data)); }, [from, to]);
  return (
    <Card className="border-slate-200">
      <CardContent className="p-5">
        <h3 className="font-bold">Kas per Metode Bayar</h3>
        <p className="text-xs text-slate-500 mb-3">Dari Kasir (POS) & Check-In walk-in — untuk cocokkan uang fisik di laci. Tidak termasuk booking online/OTA (uang masuk lewat Tripay, bukan laci).</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label="Tunai" value={fmtRp(kas.tunai)} color="#10B981" />
          <Stat label="QRIS" value={fmtRp(kas.qris)} color="#3B82F6" />
          <Stat label="Transfer" value={fmtRp(kas.transfer)} color="#F97316" />
          <Stat label="Total" value={fmtRp(kas.total)} color="#1E40AF" />
        </div>
      </CardContent>
    </Card>
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
      <KasMetodeBayar from={from} to={to} />
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

function LaporanExpenses({ from, to }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setLoading(true);
    api.get("/expenses", { params: { from_date: from, to_date: to } })
      .then(r => setRows(r.data || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [from, to]);

  const stats = useMemo(() => {
    const total = rows.reduce((s, r) => s + (r.nominal || 0), 0);
    const byCat = {};
    rows.forEach(r => { byCat[r.kategori] = (byCat[r.kategori] || 0) + (r.nominal || 0); });
    return { total, count: rows.length, byCat };
  }, [rows]);

  const exp = () => downloadCsv(`Laporan_Pengeluaran_${from}_${to}.csv`,
    ["Tanggal", "Kategori", "Deskripsi", "Nominal", "Petugas"],
    rows.map(r => [fmtDateTime(r.tanggal), r.kategori, r.deskripsi || "-", r.nominal, r.user || "-"]));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Total Pengeluaran" value={fmtRp(stats.total)} color="#EF4444" />
        <Stat label="Jumlah Transaksi" value={stats.count} color="#64748B" />
        {Object.entries(stats.byCat).slice(0, 6).map(([k, v]) => (
          <Stat key={k} label={k} value={fmtRp(v)} color="#F97316" />
        ))}
      </div>
      <div className="flex justify-end">
        <Button variant="outline" onClick={exp} data-testid="export-expenses">Export CSV</Button>
      </div>
      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
              <tr>
                <th className="text-left p-3">Tanggal</th>
                <th className="text-left p-3">Kategori</th>
                <th className="text-left p-3">Deskripsi</th>
                <th className="text-right p-3">Nominal</th>
                <th className="text-left p-3">Petugas</th>
              </tr>
            </thead>
            <tbody data-testid="expenses-tbody">
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-slate-100" data-testid={`expense-row-${r.id}`}>
                  <td className="p-3 text-xs">{fmtDateTime(r.tanggal)}</td>
                  <td className="p-3 capitalize font-semibold">{r.kategori}</td>
                  <td className="p-3 text-slate-700">{r.deskripsi || <span className="text-slate-400 italic">-</span>}</td>
                  <td className="p-3 text-right font-bold text-red-600">{fmtRp(r.nominal)}</td>
                  <td className="p-3 text-xs text-slate-500">{r.user || "-"}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-slate-500">
                    {loading ? "Memuat..." : "Tidak ada pengeluaran dalam rentang ini"}
                  </td>
                </tr>
              )}
            </tbody>
            {rows.length > 0 && (
              <tfoot>
                <tr className="border-t-2 border-slate-300 bg-slate-50 font-bold">
                  <td className="p-3" colSpan={3}>TOTAL</td>
                  <td className="p-3 text-right text-red-700" data-testid="expenses-total">{fmtRp(stats.total)}</td>
                  <td className="p-3"></td>
                </tr>
              </tfoot>
            )}
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function LaporanShift({ from, to }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setLoading(true);
    api.get("/reports/shift", { params: { from_date: from, to_date: to } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [from, to]);

  if (loading || !data) return <Card className="border-slate-200"><CardContent className="p-6 text-center text-slate-500">{loading ? "Memuat..." : "Data tidak tersedia"}</CardContent></Card>;

  const perPetugas = data.per_petugas || [];
  const rows = data.rows || [];

  const exp = () => downloadCsv(`Laporan_Shift_${from}_${to}.csv`,
    ["Tanggal", "Petugas", "Transaksi Kasir", "Total Kasir", "Check-In", "Check-Out", "Total Check-Out", "Pengeluaran Dicatat", "Total Pengeluaran", "Kamar Dibersihkan"],
    rows.map(r => [r.tanggal, r.petugas, r.kasir_count, r.kasir_total, r.checkin_count, r.checkout_count, r.checkout_total, r.expense_count, r.expense_total, r.housekeeping_count]));

  return (
    <div className="space-y-4">
      <p className="text-slate-500 text-sm">
        Rangkuman aktivitas per petugas per hari — dirangkum dari jejak petugas yang sudah tercatat di kasir,
        check-in/out, pengeluaran, dan housekeeping (sistem ini belum punya jam clock-in/clock-out shift asli).
      </p>
      <div className="flex justify-end">
        <Button variant="outline" onClick={exp} data-testid="export-shift">Export CSV</Button>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-5 space-y-3">
          <h3 className="font-bold">Ringkasan per Petugas</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
                <tr>
                  <th className="text-left p-3">Petugas</th>
                  <th className="text-right p-3">Trx Kasir</th>
                  <th className="text-right p-3">Total Kasir</th>
                  <th className="text-right p-3">Check-In</th>
                  <th className="text-right p-3">Check-Out</th>
                  <th className="text-right p-3">Total Check-Out</th>
                  <th className="text-right p-3">Pengeluaran</th>
                  <th className="text-right p-3">Kamar Dibersihkan</th>
                </tr>
              </thead>
              <tbody data-testid="shift-petugas-tbody">
                {perPetugas.map((p, i) => (
                  <tr key={p.petugas} className="border-t border-slate-100" data-testid={`shift-petugas-row-${i}`}>
                    <td className="p-3 font-semibold">{p.petugas}</td>
                    <td className="p-3 text-right">{p.kasir_count}</td>
                    <td className="p-3 text-right font-bold text-blue-700">{fmtRp(p.kasir_total)}</td>
                    <td className="p-3 text-right">{p.checkin_count}</td>
                    <td className="p-3 text-right">{p.checkout_count}</td>
                    <td className="p-3 text-right font-bold text-emerald-700">{fmtRp(p.checkout_total)}</td>
                    <td className="p-3 text-right text-red-600">{fmtRp(p.expense_total)} <span className="text-slate-400">({p.expense_count}x)</span></td>
                    <td className="p-3 text-right">{p.housekeeping_count}</td>
                  </tr>
                ))}
                {perPetugas.length === 0 && <tr><td colSpan={8} className="p-6 text-center text-slate-500">Tidak ada aktivitas dalam rentang ini</td></tr>}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-5 space-y-3">
          <h3 className="font-bold">Detail per Hari</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
                <tr>
                  <th className="text-left p-3">Tanggal</th>
                  <th className="text-left p-3">Petugas</th>
                  <th className="text-right p-3">Trx Kasir</th>
                  <th className="text-right p-3">Total Kasir</th>
                  <th className="text-right p-3">Check-In</th>
                  <th className="text-right p-3">Check-Out</th>
                  <th className="text-right p-3">Total Check-Out</th>
                  <th className="text-right p-3">Pengeluaran</th>
                  <th className="text-right p-3">Kamar Dibersihkan</th>
                </tr>
              </thead>
              <tbody data-testid="shift-detail-tbody">
                {rows.map((r, i) => (
                  <tr key={`${r.tanggal}-${r.petugas}-${i}`} className="border-t border-slate-100">
                    <td className="p-3 text-xs">{r.tanggal}</td>
                    <td className="p-3">{r.petugas}</td>
                    <td className="p-3 text-right">{r.kasir_count}</td>
                    <td className="p-3 text-right">{fmtRp(r.kasir_total)}</td>
                    <td className="p-3 text-right">{r.checkin_count}</td>
                    <td className="p-3 text-right">{r.checkout_count}</td>
                    <td className="p-3 text-right">{fmtRp(r.checkout_total)}</td>
                    <td className="p-3 text-right text-red-600">{fmtRp(r.expense_total)}</td>
                    <td className="p-3 text-right">{r.housekeeping_count}</td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={9} className="p-6 text-center text-slate-500">Tidak ada aktivitas dalam rentang ini</td></tr>}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function LaporanService({ from, to }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setLoading(true);
    api.get("/reports/service-revenue", { params: { from_date: from, to_date: to } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [from, to]);

  if (loading || !data) return <Card className="border-slate-200"><CardContent className="p-6 text-center text-slate-500">{loading ? "Memuat..." : "Data tidak tersedia"}</CardContent></Card>;

  const feePct = ((data.service_fee_pct || 0) * 100).toFixed(0);
  const exportFee = () => {
    const rows = [
      ...(data.checkin_items || []).map(it => ["Fee 3% Walk-In", it.kode, it.tanggal, it.nama_tamu, it.room_nomor, it.subtotal, it.service_fee, it.total, it.source, it.petugas]),
      ...(data.booking_items || []).map(it => ["Fee 3% Online", it.kode, it.tanggal, it.nama_tamu, it.room_nomor, it.subtotal, it.service_fee, it.total, it.source, it.petugas]),
    ];
    downloadCsv(`Laporan_Service_Fee_${from}_${to}.csv`,
      ["Tipe", "Kode", "Tanggal", "Nama Tamu", "Kamar", "Subtotal", "Service Fee", "Total", "Source", "Petugas"], rows);
  };
  const exportManual = () => {
    const rows = (data.manual_services || []).map(s => [s.kode, s.tanggal, s.kategori, s.deskripsi, s.tamu || "-", s.room_nomor || "-", s.metode_pembayaran, s.nominal, s.user]);
    downloadCsv(`Laporan_Service_Manual_${from}_${to}.csv`,
      ["Kode", "Tanggal", "Kategori", "Deskripsi", "Tamu", "Kamar", "Metode", "Nominal", "Petugas"], rows);
  };

  return (
    <div className="space-y-4">
      {/* Header stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label={`Service Fee ${feePct}% (Walk-In)`} value={fmtRp(data.checkin_service_fee_total)} color="#1E40AF" />
        <Stat label={`Service Fee ${feePct}% (Online)`} value={fmtRp(data.booking_service_fee_total)} color="#3B82F6" />
        <Stat label="Layanan Manual" value={fmtRp(data.manual_service_total)} color="#10B981" />
        <Stat label="Grand Total Pendapatan Service" value={fmtRp(data.grand_total)} color="#059669" />
      </div>

      {/* Chart per hari */}
      <Card className="border-slate-200">
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-bold">Pendapatan Service per Hari</h3>
              <p className="text-xs text-slate-500">
                {data.checkin_count} walk-in fee • {data.booking_count} online fee • {data.manual_service_count} layanan manual
              </p>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.by_day}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="tanggal" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `Rp${(v / 1000).toFixed(0)}k`} />
                <Tooltip formatter={(v) => fmtRp(v)} />
                <Legend />
                <Bar dataKey="checkin_fee" name={`Fee ${feePct}% Walk-In`} fill="#1E40AF" stackId="a" />
                <Bar dataKey="booking_fee" name={`Fee ${feePct}% Online`} fill="#3B82F6" stackId="a" />
                <Bar dataKey="manual" name="Layanan Manual" fill="#10B981" stackId="a" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Detail Service Fee 3% */}
      <Card className="border-slate-200">
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-bold">Rincian Service Fee {feePct}%</h3>
              <p className="text-xs text-slate-500">Dihitung otomatis dari check-in walk-in & booking online yang lunas</p>
            </div>
            <Button data-testid="export-service-fee" size="sm" variant="outline" onClick={exportFee}>Export CSV</Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
                <tr>
                  <th className="text-left p-3">Tipe</th>
                  <th className="text-left p-3">Kode</th>
                  <th className="text-left p-3">Tanggal</th>
                  <th className="text-left p-3">Tamu</th>
                  <th className="text-left p-3">Kamar</th>
                  <th className="text-right p-3">Subtotal</th>
                  <th className="text-right p-3">Fee {feePct}%</th>
                  <th className="text-right p-3">Total</th>
                </tr>
              </thead>
              <tbody data-testid="service-fee-tbody">
                {[
                  ...(data.checkin_items || []).map(it => ({ ...it, _tipe: "walk_in" })),
                  ...(data.booking_items || []).map(it => ({ ...it, _tipe: "online" })),
                ].sort((a, b) => (b.tanggal || "").localeCompare(a.tanggal || "")).map((it, i) => (
                  <tr key={`fee-${it.id}-${i}`} className="border-t border-slate-100" data-testid={`svc-fee-row-${i}`}>
                    <td className="p-3">
                      <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded ${it._tipe === "online" ? "bg-blue-100 text-blue-700" : "bg-indigo-100 text-indigo-700"}`}>{it._tipe}</span>
                    </td>
                    <td className="p-3 font-mono text-xs">{it.kode}</td>
                    <td className="p-3 text-xs">{fmtDateTime(it.tanggal)}</td>
                    <td className="p-3">{it.nama_tamu}</td>
                    <td className="p-3">{it.room_nomor}</td>
                    <td className="p-3 text-right">{fmtRp(it.subtotal)}</td>
                    <td className="p-3 text-right font-bold text-blue-700">{fmtRp(it.service_fee)}</td>
                    <td className="p-3 text-right font-semibold">{fmtRp(it.total)}</td>
                  </tr>
                ))}
                {(data.checkin_items.length + data.booking_items.length) === 0 && (
                  <tr><td colSpan={8} className="p-6 text-center text-slate-500">Belum ada service fee {feePct}% pada rentang ini</td></tr>
                )}
              </tbody>
              {(data.checkin_items.length + data.booking_items.length) > 0 && (
                <tfoot>
                  <tr className="border-t-2 border-slate-300 bg-slate-50 font-bold">
                    <td className="p-3" colSpan={6}>TOTAL SERVICE FEE {feePct}%</td>
                    <td className="p-3 text-right text-blue-700" data-testid="svc-fee-total">{fmtRp(data.service_fee_grand_total)}</td>
                    <td className="p-3"></td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Detail Layanan Manual */}
      <Card className="border-slate-200">
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-bold">Rincian Layanan Manual (Nominal Fleksibel)</h3>
              <p className="text-xs text-slate-500">Layanan tambahan yang dicatat staff via menu Service</p>
            </div>
            <Button data-testid="export-service-manual" size="sm" variant="outline" onClick={exportManual}>Export CSV</Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
                <tr>
                  <th className="text-left p-3">Kode</th>
                  <th className="text-left p-3">Tanggal</th>
                  <th className="text-left p-3">Kategori</th>
                  <th className="text-left p-3">Deskripsi</th>
                  <th className="text-left p-3">Tamu / Kamar</th>
                  <th className="text-left p-3">Metode</th>
                  <th className="text-right p-3">Nominal</th>
                  <th className="text-left p-3">Petugas</th>
                </tr>
              </thead>
              <tbody data-testid="service-manual-tbody">
                {(data.manual_services || []).map((s, i) => (
                  <tr key={s.id} className="border-t border-slate-100" data-testid={`svc-manual-row-${i}`}>
                    <td className="p-3 font-mono text-xs">{s.kode}</td>
                    <td className="p-3 text-xs">{fmtDateTime(s.tanggal)}</td>
                    <td className="p-3"><span className="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-100 text-emerald-700">{s.kategori}</span></td>
                    <td className="p-3">{s.deskripsi}</td>
                    <td className="p-3 text-xs">
                      {s.tamu || <span className="text-slate-400">-</span>}
                      {s.room_nomor && <div className="text-slate-500">Kamar {s.room_nomor}</div>}
                    </td>
                    <td className="p-3 text-xs capitalize">{s.metode_pembayaran}</td>
                    <td className="p-3 text-right font-bold text-emerald-700">{fmtRp(s.nominal)}</td>
                    <td className="p-3 text-xs">{s.user}</td>
                  </tr>
                ))}
                {(data.manual_services || []).length === 0 && (
                  <tr><td colSpan={8} className="p-6 text-center text-slate-500">Belum ada layanan manual pada rentang ini</td></tr>
                )}
              </tbody>
              {(data.manual_services || []).length > 0 && (
                <tfoot>
                  <tr className="border-t-2 border-slate-300 bg-slate-50 font-bold">
                    <td className="p-3" colSpan={6}>TOTAL LAYANAN MANUAL</td>
                    <td className="p-3 text-right text-emerald-700" data-testid="svc-manual-total">{fmtRp(data.manual_service_total)}</td>
                    <td className="p-3"></td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function LaporanCancel({ from, to }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    api.get("/reports/cancellation-revenue", { params: { from_date: from, to_date: to } })
      .then(r => setData(r.data)).catch(() => setData(null));
  }, [from, to]);
  if (!data) return <Card className="border-slate-200"><CardContent className="p-6 text-center text-slate-500">Memuat...</CardContent></Card>;
  const exportCsv = () => {
    const rows = data.items.map(it => [it.tipe, it.kode, it.room_nomor, it.nama_tamu, it.source, it.tanggal, it.nominal, it.petugas, it.alasan]);
    downloadCsv(`pendapatan-cancel-noshow-${from}-${to}.csv`,
      ["Tipe", "Kode Booking", "Kamar", "Nama Tamu", "Source", "Tanggal", "Nominal", "Petugas", "Alasan"], rows);
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Stat label="Cancel Fees" value={fmtRp(data.cancel_fees_total)} color="#DC2626" />
        <Stat label="No-Show Retention" value={fmtRp(data.no_show_total)} color="#D97706" />
        <Stat label="Grand Total Pendapatan" value={fmtRp(data.grand_total)} color="#059669" />
      </div>
      <Card className="border-slate-200">
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-bold">Grafik per Hari</h3>
              <p className="text-xs text-slate-500">{data.cancel_count} cancel + {data.no_show_count} no-show</p>
            </div>
            <Button data-testid="cancel-export" size="sm" variant="outline" onClick={exportCsv}>Export CSV</Button>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.by_day}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="tanggal" />
                <YAxis tickFormatter={(v) => `Rp${(v / 1000).toFixed(0)}k`} />
                <Tooltip formatter={(v) => fmtRp(v)} />
                <Legend />
                <Bar dataKey="cancel_fee" name="Cancel Fee" fill="#DC2626" stackId="a" />
                <Bar dataKey="no_show" name="No-Show" fill="#D97706" stackId="a" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
      <Card className="border-slate-200">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-600">
              <tr>
                <th className="text-left p-3">Tipe</th>
                <th className="text-left p-3">Kode</th>
                <th className="text-left p-3">Kamar</th>
                <th className="text-left p-3">Tamu</th>
                <th className="text-left p-3">Source</th>
                <th className="text-left p-3">Tanggal</th>
                <th className="text-right p-3">Nominal</th>
                <th className="text-left p-3">Petugas</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it, i) => (
                <tr key={i} className="border-t border-slate-100" data-testid={`cancel-row-${i}`}>
                  <td className="p-3">
                    <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded ${it.tipe === "no_show" ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-700"}`}>{it.tipe}</span>
                  </td>
                  <td className="p-3 font-mono text-xs">{it.kode}</td>
                  <td className="p-3">{it.room_nomor}</td>
                  <td className="p-3">{it.nama_tamu}</td>
                  <td className="p-3 text-xs uppercase">{it.source}</td>
                  <td className="p-3 text-xs">{it.tanggal}</td>
                  <td className="p-3 text-right font-bold">{fmtRp(it.nominal)}</td>
                  <td className="p-3 text-xs">{it.petugas}</td>
                </tr>
              ))}
              {data.items.length === 0 && <tr><td colSpan={8} className="p-6 text-center text-slate-500">Tidak ada cancel/no-show dalam rentang ini</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function LaporanOtaPrepaid() {
  const [menunggu, setMenunggu] = useState(null);
  const [hasil, setHasil] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [terapkanId, setTerapkanId] = useState(null);

  const load = () => api.get("/otomasi-email/ota-belum-dikonfirmasi").then((r) => setMenunggu(r.data)).catch(() => setMenunggu([]));
  useEffect(() => { load(); }, []);

  const uploadPdf = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setHasil(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/otomasi-email/parse-reddoorz-pdf", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setHasil(data);
      if (data.items?.length === 0) toast.error(data.pesan || "Tidak ada data terbaca dari PDF");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Gagal memproses PDF");
    } finally {
      setUploading(false);
    }
  };

  const terapkan = async (row) => {
    setTerapkanId(row.booking_id);
    try {
      await api.post(`/bookings/${row.booking_id}/konfirmasi-harga-ota`, { total_nominal: row.extracted_nominal });
      toast.success(`Nominal ${row.kode} dikonfirmasi: ${fmtRp(row.extracted_nominal)}`);
      setHasil((h) => ({ ...h, items: h.items.filter((it) => it.booking_id !== row.booking_id) }));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Gagal menerapkan");
    } finally {
      setTerapkanId(null);
    }
  };

  const cocokRows = (hasil?.items || []).filter((it) => it.matched);
  const tidakCocokRows = (hasil?.items || []).filter((it) => !it.matched);

  return (
    <div className="space-y-4">
      <Card className="border-slate-200">
        <CardContent className="p-4 sm:p-5">
          <div className="flex items-start justify-between flex-wrap gap-3">
            <div>
              <h3 className="font-bold">Booking OTA Menunggu Konfirmasi Nominal</h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Booking RedDoorz "Prepaid" yang emailnya tidak mencantumkan nominal - masih pakai ESTIMASI, dikecualikan dari semua laporan pendapatan sampai nominal settlement asli dikonfirmasi.
              </p>
            </div>
            <label className="shrink-0">
              <input type="file" accept="application/pdf" className="hidden" onChange={uploadPdf} disabled={uploading} data-testid="ota-pdf-input" />
              <span className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-md text-sm font-medium cursor-pointer ${uploading ? "bg-slate-200 text-slate-500" : "bg-blue-700 hover:bg-blue-800 text-white"}`} data-testid="ota-pdf-upload-btn">
                {uploading ? "Memproses PDF…" : "Upload PDF Settlement RedDoorz"}
              </span>
            </label>
          </div>

          {menunggu === null ? (
            <p className="text-sm text-slate-500 mt-4">Memuat…</p>
          ) : menunggu.length === 0 ? (
            <p className="text-sm text-slate-500 mt-4">Tidak ada booking OTA yang menunggu konfirmasi saat ini.</p>
          ) : (
            <table className="w-full mt-4 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b">
                  <th className="p-2">Kode</th><th className="p-2">Nama Tamu</th><th className="p-2">Kamar</th>
                  <th className="p-2">Check-in</th><th className="p-2 text-right">Kamar</th><th className="p-2 text-right">Estimasi</th>
                </tr>
              </thead>
              <tbody>
                {menunggu.map((g) => (
                  <tr key={g.booking_id} className="border-b border-slate-100" data-testid={`ota-pending-${g.booking_id}`}>
                    <td className="p-2 font-mono text-xs">{g.kode}</td>
                    <td className="p-2">{g.nama_tamu}</td>
                    <td className="p-2">{g.room_tipe}</td>
                    <td className="p-2 text-xs">{fmtDateTime(g.jam_mulai)}</td>
                    <td className="p-2 text-right">{g.jumlah_kamar}</td>
                    <td className="p-2 text-right text-amber-600 font-semibold">{fmtRp(g.estimasi_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {hasil && cocokRows.length + tidakCocokRows.length > 0 && (
        <Card className="border-slate-200">
          <CardContent className="p-4 sm:p-5">
            <h3 className="font-bold mb-1">Hasil Baca PDF ({hasil.total_dibaca} baris, {hasil.total_cocok} cocok)</h3>
            <p className="text-xs text-slate-500 mb-3">Review dulu sebelum menerapkan - klik "Terapkan" per baris untuk konfirmasi nominal settlement-nya ke booking yang cocok.</p>
            {cocokRows.length > 0 && (
              <table className="w-full text-sm mb-4">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b">
                    <th className="p-2">Nama (dari PDF)</th><th className="p-2">Cocok dengan Booking</th>
                    <th className="p-2 text-right">Estimasi Lama</th><th className="p-2 text-right">Nominal PDF</th><th className="p-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {cocokRows.map((row, i) => (
                    <tr key={i} className="border-b border-slate-100" data-testid={`ota-match-${i}`}>
                      <td className="p-2">{row.extracted_nama}</td>
                      <td className="p-2 text-xs">{row.kode} · {row.room_tipe} · {row.jumlah_kamar} kamar</td>
                      <td className="p-2 text-right text-slate-400">{fmtRp(row.estimasi_total)}</td>
                      <td className="p-2 text-right font-bold text-emerald-700">{fmtRp(row.extracted_nominal)}</td>
                      <td className="p-2 text-right">
                        <Button size="sm" data-testid={`ota-terapkan-${i}`} disabled={terapkanId === row.booking_id} onClick={() => terapkan(row)}>
                          {terapkanId === row.booking_id ? "Menerapkan…" : "Terapkan"}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {tidakCocokRows.length > 0 && (
              <div className="text-xs text-slate-500 bg-slate-50 rounded-lg p-3">
                <div className="font-medium text-slate-600 mb-1">Tidak ketemu booking yang cocok ({tidakCocokRows.length}):</div>
                {tidakCocokRows.map((row, i) => (
                  <div key={i}>{row.extracted_nama} — {fmtRp(row.extracted_nominal)} (cek manual di halaman Reservasi, mungkin nama sedikit beda)</div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

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

function LaporanSaluran() {
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(today());
  const [channel, setChannel] = useState("Semua");

  return (
    <div className="space-y-4" data-testid="laporan-analitik-page">
      <p className="text-slate-500 text-sm">Pendapatan, performa saluran, dan tren okupansi dari data booking multi-saluran sungguhan. Kosong/nol sampai ada booking online/OTA/WhatsApp yang lunas.</p>
      <PeriodeSaluranPicker from={from} setFrom={setFrom} to={to} setTo={setTo} channel={channel} setChannel={setChannel} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GrafikPendapatan from={from} to={to} />
        <DiagramPerformaSaluran channel={channel} />
        <div className="lg:col-span-2"><GrafikTrenOkupansi from={from} to={to} /></div>
      </div>
    </div>
  );
}
