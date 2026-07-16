import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import api, { fmtRp, fmtDateTime, checkoutReceiptWaLink } from "@/lib/apiClient";
import { printViaBluetooth, isBluetoothPrintSupported, padRow, centerRow, divider } from "@/lib/blePrinter";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ArrowLeft, Printer, MessageCircle, Bluetooth } from "lucide-react";

function checkoutBluetoothLines(ci) {
  const lines = [
    centerRow("PELANGI HOMESTAY"), centerRow("Struk Check-Out Day Use"),
    divider(),
    padRow("No", ci.trx_no),
    padRow("Tamu", ci.nama_tamu),
    padRow("Kamar", `${ci.room_nomor} (${ci.room_tipe})`),
    padRow("Check-In", fmtDateTime(ci.jam_checkin)),
    padRow("Check-Out", fmtDateTime(ci.jam_checkout)),
    padRow("Durasi", `${ci.durasi_jam} jam`),
    divider(),
    padRow("Tarif Dasar", fmtRp(ci.tarif_dasar)),
    padRow(`Overtime (${ci.overtime_jam} jam)`, fmtRp(ci.biaya_tambahan)),
    padRow("Subtotal", fmtRp(ci.subtotal ?? (ci.tarif_dasar + (ci.biaya_tambahan || 0)))),
    padRow("Service Fee (3%)", fmtRp(ci.service_fee || 0)),
    padRow("TOTAL", fmtRp(ci.total)),
    divider(),
  ];
  for (const p of ci.pembayaran || []) lines.push(padRow(p.metode, fmtRp(p.jumlah)));
  lines.push(divider());
  lines.push(centerRow("Terima kasih atas kunjungan Anda"));
  return lines;
}

export default function CheckOut() {
  const { checkinId } = useParams();
  const nav = useNavigate();
  const [ci, setCi] = useState(null);
  const [overtimeOverride, setOvertimeOverride] = useState("");
  const [jamCheckout, setJamCheckout] = useState(() => {
    const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  });
  const [pays, setPays] = useState([{ metode: "tunai", jumlah: 0 }]);
  const [catatan, setCatatan] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);

  const load = async () => {
    const { data } = await api.get(`/checkins/${checkinId}`);
    setCi(data);
    if (data.preview) setPays([{ metode: "tunai", jumlah: data.preview.total }]);
  };
  useEffect(() => { load(); }, [checkinId]);

  const preview = ci?.preview;
  const overtimeNum = overtimeOverride === "" ? undefined : Number(overtimeOverride);
  // Hitung ulang berdasarkan jamCheckout yg dipilih (jika berbeda dari preview)
  const localCalc = (() => {
    if (!ci || !jamCheckout) return null;
    const inIso = new Date(ci.jam_checkin);
    const outIso = new Date(jamCheckout);
    if (outIso < inIso) return null;
    const hours = (outIso - inIso) / 3600000;
    const ot = overtimeNum !== undefined ? Math.max(0, overtimeNum) : Math.max(0, Math.ceil(hours - 6));
    const biaya = ot * 20000;
    const subtotal = ci.tarif_dasar + biaya;
    const serviceFee = Math.round(subtotal * 0.03);
    return { durasi_jam: hours.toFixed(2), overtime_jam: ot, biaya_tambahan: biaya, subtotal, service_fee: serviceFee, total: subtotal + serviceFee };
  })();
  const total = localCalc ? localCalc.total : (preview?.total || 0);

  // Sync default payment amount when total recalculated and user has the default single 'tunai' row at 0
  useEffect(() => {
    if (pays.length === 1 && pays[0].metode === "tunai" && (pays[0].jumlah === 0 || pays[0].jumlah === "0")) {
      setPays([{ metode: "tunai", jumlah: total }]);
    }
  }, [total, pays]);

  const totalPay = pays.reduce((a, p) => a + (Number(p.jumlah) || 0), 0);
  const kurang = total - totalPay;

  const submit = async () => {
    if (kurang > 0) { toast.error(`Pembayaran kurang ${fmtRp(kurang)}`); return; }
    setSubmitting(true);
    try {
      const { data } = await api.post(`/checkins/${checkinId}/checkout`, {
        pembayaran: pays.filter(p => Number(p.jumlah) > 0).map(p => ({ metode: p.metode, jumlah: Number(p.jumlah) })),
        overtime_manual: overtimeNum,
        jam_checkout: jamCheckout ? new Date(jamCheckout).toISOString() : undefined,
        catatan,
      });
      setDone(data);
      toast.success("Check-out berhasil!");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal");
    } finally { setSubmitting(false); }
  };

  if (!ci) return <div className="p-6 text-slate-500">Memuat…</div>;

  if (done) {
    return (
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-5 text-center">
          <h2 className="text-2xl font-bold text-emerald-800">Transaksi Selesai</h2>
          <p className="text-emerald-700 text-sm mt-1">{done.trx_no}</p>
        </div>
        <Receipt ci={done} />
        <div className="flex flex-col sm:flex-row gap-3 no-print">
          <Button onClick={() => window.print()} className="h-12 flex-1 bg-blue-700 hover:bg-blue-800"><Printer className="w-4 h-4 mr-2" /> Cetak Struk</Button>
          {isBluetoothPrintSupported() && (
            <Button
              variant="outline"
              className="h-12 flex-1"
              onClick={async () => {
                try {
                  await printViaBluetooth(checkoutBluetoothLines(done));
                  toast.success("Terkirim ke printer Bluetooth");
                } catch (e) {
                  toast.error(e?.message || "Gagal mencetak via Bluetooth");
                }
              }}
            >
              <Bluetooth className="w-4 h-4 mr-2" /> Cetak Bluetooth
            </Button>
          )}
          {done.no_hp && (
            <a href={checkoutReceiptWaLink(done)} target="_blank" rel="noreferrer" className="flex-1">
              <Button variant="outline" className="h-12 w-full"><MessageCircle className="w-4 h-4 mr-2" /> Kirim Bukti Transaksi WA</Button>
            </a>
          )}
          <Button variant="outline" className="h-12" onClick={() => nav("/")}>Kembali</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <button onClick={() => nav("/")} className="flex items-center gap-2 text-sm text-slate-600 hover:text-blue-700">
        <ArrowLeft className="w-4 h-4" /> Kembali
      </button>
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Check-Out</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Kamar {ci.room_nomor} • {ci.nama_tamu}</h1>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-5 sm:p-6 grid sm:grid-cols-2 gap-4 text-sm">
          <Row label="Jam Check-In" value={fmtDateTime(ci.jam_checkin)} />
          <div>
            <div className="text-xs uppercase tracking-wider text-slate-500">Jam Check-Out (bisa diubah)</div>
            <Input data-testid="co-jam" type="datetime-local" value={jamCheckout} onChange={(e) => setJamCheckout(e.target.value)} className="h-10 mt-1" />
          </div>
          <Row label="Tarif Dasar" value={fmtRp(ci.tarif_dasar)} />
          <Row label="Durasi" value={localCalc ? `${localCalc.durasi_jam} jam` : (preview ? `${preview.durasi_jam} jam` : "-")} />
          <Row label="Overtime" value={localCalc ? `${localCalc.overtime_jam} jam = ${fmtRp(localCalc.biaya_tambahan)}` : (preview ? `${preview.overtime_jam} jam = ${fmtRp(preview.biaya_tambahan)}` : "-")} />
          <Row label="Subtotal" value={fmtRp(localCalc ? localCalc.subtotal : (preview?.subtotal || 0))} />
          <Row label="Service Fee (3%)" value={<span data-testid="co-service-fee">{fmtRp(localCalc ? localCalc.service_fee : (preview?.service_fee || 0))}</span>} />
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-5 sm:p-6 space-y-4">
          <div>
            <Label>Override Overtime (jam) — opsional</Label>
            <Input data-testid="co-overtime" type="number" min="0" placeholder={`${preview?.overtime_jam ?? 0}`} value={overtimeOverride} onChange={(e) => setOvertimeOverride(e.target.value)} className="h-12 mt-1.5" />
            <p className="text-xs text-slate-500 mt-1">Kosongkan untuk pakai perhitungan otomatis.</p>
          </div>
          <div className="rounded-xl bg-blue-700 text-white p-5 flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wider opacity-80">Total Tagihan</div>
              <div className="text-3xl font-extrabold">{fmtRp(total)}</div>
            </div>
          </div>

          <div>
            <Label>Metode Pembayaran (split payment didukung)</Label>
            <div className="space-y-2 mt-2">
              {pays.map((p, idx) => (
                <div key={idx} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                  <select data-testid={`pay-method-${idx}`} value={p.metode} onChange={(e) => setPays(ps => ps.map((x, i) => i === idx ? { ...x, metode: e.target.value } : x))} className="h-12 rounded-md border border-slate-300 px-3 bg-white">
                    <option value="tunai">Tunai</option>
                    <option value="transfer">Transfer</option>
                    <option value="qris">QRIS</option>
                  </select>
                  <Input data-testid={`pay-amount-${idx}`} type="number" min="0" value={p.jumlah} onChange={(e) => setPays(ps => ps.map((x, i) => i === idx ? { ...x, jumlah: e.target.value } : x))} className="h-12" />
                  {pays.length > 1 && (
                    <Button variant="outline" onClick={() => setPays(ps => ps.filter((_, i) => i !== idx))}>Hapus</Button>
                  )}
                </div>
              ))}
              <Button data-testid="add-payment" variant="outline" type="button" onClick={() => setPays(ps => [...ps, { metode: "transfer", jumlah: 0 }])}>+ Tambah Metode</Button>
            </div>
            <div className="mt-3 text-sm">
              Total Bayar: <span className="font-bold">{fmtRp(totalPay)}</span> {" • "}
              {kurang > 0 ? <span className="text-red-600 font-semibold">Kurang {fmtRp(kurang)}</span> : <span className="text-emerald-700 font-semibold">Lunas {kurang < 0 ? `(Kembalian ${fmtRp(-kurang)})` : ""}</span>}
            </div>
          </div>

          <div>
            <Label>Catatan</Label>
            <Textarea data-testid="co-catatan" value={catatan} onChange={(e) => setCatatan(e.target.value)} className="mt-1.5" rows={2} />
          </div>

          <div className="flex gap-3">
            <Button data-testid="co-submit" disabled={submitting} onClick={submit} className="h-12 flex-1 bg-blue-700 hover:bg-blue-800 text-base">
              {submitting ? "Memproses…" : "Selesaikan Transaksi"}
            </Button>
            <Button variant="outline" onClick={() => nav("/")} className="h-12">Batal</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className="font-semibold mt-0.5">{value}</div>
    </div>
  );
}

function Receipt({ ci }) {
  return (
    <div id="receipt" className="bg-white border border-slate-200 rounded-xl p-6 font-mono text-sm">
      <div className="text-center mb-3">
        <div className="font-extrabold text-lg">PELANGI HOMESTAY</div>
        <div className="text-xs text-slate-500">Struk Check-Out Day Use</div>
      </div>
      <hr className="my-2 border-dashed" />
      <div className="grid grid-cols-2 gap-1 text-xs">
        <div>No</div><div className="text-right">{ci.trx_no}</div>
        <div>Tamu</div><div className="text-right">{ci.nama_tamu}</div>
        <div>Kamar</div><div className="text-right">{ci.room_nomor} ({ci.room_tipe})</div>
        <div>Check-In</div><div className="text-right">{fmtDateTime(ci.jam_checkin)}</div>
        <div>Check-Out</div><div className="text-right">{fmtDateTime(ci.jam_checkout)}</div>
        <div>Durasi</div><div className="text-right">{ci.durasi_jam} jam</div>
      </div>
      <hr className="my-2 border-dashed" />
      <div className="grid grid-cols-2 gap-1 text-xs">
        <div>Tarif Dasar</div><div className="text-right">{fmtRp(ci.tarif_dasar)}</div>
        <div>Overtime ({ci.overtime_jam} jam)</div><div className="text-right">{fmtRp(ci.biaya_tambahan)}</div>
        <div>Subtotal</div><div className="text-right">{fmtRp(ci.subtotal ?? (ci.tarif_dasar + (ci.biaya_tambahan || 0)))}</div>
        <div>Service Fee (3%)</div><div className="text-right">{fmtRp(ci.service_fee || 0)}</div>
        <div className="font-bold pt-1 border-t mt-1">TOTAL</div>
        <div className="font-bold pt-1 border-t mt-1 text-right">{fmtRp(ci.total)}</div>
      </div>
      <hr className="my-2 border-dashed" />
      <div className="text-xs">
        <div className="font-semibold">Pembayaran:</div>
        {(ci.pembayaran || []).map((p, i) => (
          <div key={i} className="flex justify-between"><span className="capitalize">{p.metode}</span><span>{fmtRp(p.jumlah)}</span></div>
        ))}
      </div>
      <div className="text-center mt-3 text-xs text-slate-500">Terima kasih atas kunjungan Anda</div>
    </div>
  );
}
