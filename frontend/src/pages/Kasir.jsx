import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtRp, fmtDateTime, kasirReceiptWaLink } from "@/lib/apiClient";
import { printViaBluetooth, isBluetoothPrintSupported, padRow, centerRow, divider } from "@/lib/blePrinter";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ShoppingCart, Plus, Minus, Trash2, Printer, MessageCircle, Bluetooth } from "lucide-react";

const HOMESTAY_NAMA = "Pelangi Homestay";
const HOMESTAY_ALAMAT = "Jl. Kebun Raya Bedugul, Candikuning, Kec. Baturiti, Tabanan - Bali";
const METODE_LABEL = { tunai: "Tunai", transfer: "Transfer", qris: "QRIS" };

// Lebar kertas thermal dalam jumlah karakter/baris ESC-POS (font default printer) —
// 58mm ~32 kolom, 80mm ~48 kolom, sesuai konvensi umum printer thermal generik.
const PAPER_COLS = { "58": 32, "80": 48 };
const PAPER_WIDTH_KEY = "kasir_paper_width";

function kasirBluetoothLines(trx, kolom = 32) {
  const lines = [
    centerRow(HOMESTAY_NAMA, kolom), centerRow(HOMESTAY_ALAMAT, kolom),
    divider(kolom),
    padRow("No. Transaksi", trx.trx_no, kolom),
    padRow("Tanggal", fmtDateTime(trx.timestamp), kolom),
    padRow("Kasir", trx.petugas || "-", kolom),
    divider(kolom),
  ];
  for (const it of trx.items) {
    lines.push(`${it.qty} x ${it.nama}`);
    lines.push(padRow("", fmtRp(it.subtotal), kolom));
  }
  lines.push(divider(kolom));
  lines.push(padRow("Subtotal", fmtRp(trx.subtotal), kolom));
  if (trx.diskon > 0) lines.push(padRow("Diskon", `-${fmtRp(trx.diskon)}`, kolom));
  lines.push(padRow("TOTAL", fmtRp(trx.total), kolom));
  lines.push(divider(kolom));
  for (const p of trx.pembayaran || []) {
    lines.push(padRow(`Bayar (${METODE_LABEL[p.metode] || p.metode})`, fmtRp(p.jumlah), kolom));
  }
  if (trx.catatan) { lines.push(divider(kolom)); lines.push(`Catatan: ${trx.catatan}`); }
  lines.push(divider(kolom));
  lines.push(centerRow("Terima kasih.", kolom));
  return lines;
}

// Struk kasir — hanya terlihat saat print (hidden print:block), supaya window.print()
// tidak ikut mencetak sidebar/katalog produk/keranjang seperti sebelumnya. Lebar pakai
// satuan mm (bukan px) supaya presisi mengikuti kertas thermal fisik 58mm/80mm saat dicetak.
function Receipt({ trx, lebar }) {
  if (!trx) return null;
  return (
    <div className={`hidden print:block font-mono mx-auto ${lebar === "80" ? "text-sm" : "text-[11px]"}`} style={{ width: `${lebar}mm` }}>
      <div className="text-center space-y-0.5 mb-2">
        <div className="font-bold text-sm">{HOMESTAY_NAMA}</div>
        <div>{HOMESTAY_ALAMAT}</div>
      </div>
      <div className="border-t border-dashed border-black my-1" />
      <div className="flex justify-between"><span>No. Transaksi</span><span>{trx.trx_no}</span></div>
      <div className="flex justify-between"><span>Tanggal</span><span>{fmtDateTime(trx.timestamp)}</span></div>
      <div className="flex justify-between"><span>Kasir</span><span>{trx.petugas}</span></div>
      <div className="flex justify-between"><span>Customer</span><span>Walk In</span></div>
      <div className="border-t border-dashed border-black my-1" />
      {trx.items.map((it, i) => (
        <div key={i} className="mb-0.5">
          <div>{it.qty} x {it.nama}</div>
          <div className="flex justify-between"><span>&nbsp;</span><span>{fmtRp(it.subtotal)}</span></div>
        </div>
      ))}
      <div className="border-t border-dashed border-black my-1" />
      <div className="flex justify-between"><span>Subtotal</span><span>{fmtRp(trx.subtotal)}</span></div>
      {trx.diskon > 0 && <div className="flex justify-between"><span>Diskon</span><span>-{fmtRp(trx.diskon)}</span></div>}
      <div className="flex justify-between font-bold"><span>Total</span><span>{fmtRp(trx.total)}</span></div>
      <div className="border-t border-dashed border-black my-1" />
      {trx.pembayaran.map((p, i) => (
        <div key={i} className="flex justify-between"><span>Bayar ({METODE_LABEL[p.metode] || p.metode})</span><span>{fmtRp(p.jumlah)}</span></div>
      ))}
      {trx.catatan && (
        <>
          <div className="border-t border-dashed border-black my-1" />
          <div>Catatan: {trx.catatan}</div>
        </>
      )}
      <div className="border-t border-dashed border-black my-1" />
      <div className="text-center mt-2">Terima kasih.</div>
    </div>
  );
}

const CATS = [
  { key: "", label: "Semua" },
  { key: "makanan", label: "Makanan" },
  { key: "minuman", label: "Minuman" },
  { key: "laundry", label: "Laundry" },
];

export default function Kasir() {
  const [products, setProducts] = useState([]);
  const [cat, setCat] = useState("");
  const [search, setSearch] = useState("");
  const [cart, setCart] = useState([]); // {product, qty}
  const [diskon, setDiskon] = useState(0);
  const [catatan, setCatatan] = useState("");
  const [pays, setPays] = useState([{ metode: "tunai", jumlah: 0 }]);
  const [namaPembeli, setNamaPembeli] = useState("");
  const [noHpPembeli, setNoHpPembeli] = useState("");
  const [last, setLast] = useState(null);
  const [lastBuyer, setLastBuyer] = useState(null);
  const [showCart, setShowCart] = useState(false);
  const [lebarKertas, setLebarKertas] = useState(() => localStorage.getItem(PAPER_WIDTH_KEY) || "58");
  const gantiLebarKertas = (v) => { setLebarKertas(v); localStorage.setItem(PAPER_WIDTH_KEY, v); };

  const load = async () => {
    const { data } = await api.get("/products");
    setProducts(data.filter(p => p.aktif));
  };
  useEffect(() => { load(); }, []);

  const filtered = products
    .filter(p => !cat || p.kategori === cat)
    .filter(p => !search || p.nama.toLowerCase().includes(search.toLowerCase()) || p.kode.toLowerCase().includes(search.toLowerCase()));

  const addToCart = (p) => {
    setCart(c => {
      const idx = c.findIndex(x => x.product.id === p.id);
      if (idx >= 0) return c.map((x, i) => i === idx ? { ...x, qty: x.qty + 1 } : x);
      return [...c, { product: p, qty: 1 }];
    });
  };
  const changeQty = (id, d) => setCart(c => c.map(x => x.product.id === id ? { ...x, qty: Math.max(1, x.qty + d) } : x));
  const removeItem = (id) => setCart(c => c.filter(x => x.product.id !== id));

  const subtotal = cart.reduce((a, x) => a + x.product.harga * x.qty, 0);
  const total = Math.max(0, subtotal - (Number(diskon) || 0));
  const totalPay = pays.reduce((a, p) => a + (Number(p.jumlah) || 0), 0);
  const kurang = total - totalPay;

  const submit = async () => {
    if (cart.length === 0) { toast.error("Keranjang kosong"); return; }
    if (kurang > 0) { toast.error(`Pembayaran kurang ${fmtRp(kurang)}`); return; }
    try {
      const { data } = await api.post("/kasir", {
        items: cart.map(x => ({ product_id: x.product.id, qty: x.qty })),
        diskon: Number(diskon) || 0,
        catatan,
        pembayaran: pays.filter(p => Number(p.jumlah) > 0).map(p => ({ metode: p.metode, jumlah: Number(p.jumlah) })),
      });
      setLast(data);
      setLastBuyer({ nama: namaPembeli, no_hp: noHpPembeli });
      toast.success(`Transaksi ${data.trx_no} berhasil`);
      setCart([]); setDiskon(0); setCatatan(""); setPays([{ metode: "tunai", jumlah: 0 }]);
      setNamaPembeli(""); setNoHpPembeli("");
      setShowCart(false);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-6">
      <div className="no-print flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Kasir</p>
          <h1 className="text-3xl sm:text-4xl font-extrabold">Point of Sale</h1>
        </div>
        <Button data-testid="open-cart" onClick={() => setShowCart(true)} className="lg:hidden bg-blue-700 hover:bg-blue-800 relative">
          <ShoppingCart className="w-4 h-4 mr-2" /> Keranjang
          {cart.length > 0 && <span className="absolute -top-1 -right-1 bg-red-600 text-white text-xs rounded-full w-5 h-5 grid place-items-center">{cart.length}</span>}
        </Button>
      </div>

      <div className="no-print grid lg:grid-cols-[1fr_400px] gap-6">
        {/* Products */}
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-3">
            <Input data-testid="kasir-search" placeholder="Cari produk..." value={search} onChange={(e) => setSearch(e.target.value)} className="h-12 flex-1" />
          </div>
          <Tabs value={cat} onValueChange={setCat}>
            <TabsList className="grid grid-cols-4 w-full sm:max-w-md">
              {CATS.map(c => <TabsTrigger key={c.key} value={c.key} data-testid={`tab-${c.label}`}>{c.label}</TabsTrigger>)}
            </TabsList>
          </Tabs>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {filtered.map(p => (
              <button key={p.id} data-testid={`prod-${p.kode}`} onClick={() => addToCart(p)} className="text-left bg-white border border-slate-200 rounded-xl p-4 hover:border-blue-500 hover:shadow-md transition-all">
                <div className="text-xs text-slate-500 uppercase tracking-wider">{p.kategori}</div>
                <div className="font-bold mt-1 line-clamp-2">{p.nama}</div>
                <div className="text-blue-700 font-extrabold mt-2">{fmtRp(p.harga)}</div>
                {p.kategori !== "laundry" && <div className="text-xs text-slate-500 mt-1">Stok: {p.stok}</div>}
              </button>
            ))}
            {filtered.length === 0 && <div className="col-span-full text-slate-500 text-center py-10">Tidak ada produk</div>}
          </div>
        </div>

        {/* Cart */}
        <div className={`${showCart ? "fixed inset-0 z-40 bg-slate-900/40" : "hidden lg:block"} lg:relative`}>
          <div className={`${showCart ? "fixed bottom-0 inset-x-0 max-h-[90vh] overflow-y-auto" : ""} lg:sticky lg:top-6 bg-white border border-slate-200 rounded-2xl p-5 space-y-4`}>
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold">Keranjang</h2>
              <button className="lg:hidden text-slate-500" onClick={() => setShowCart(false)}>Tutup</button>
            </div>
            {cart.length === 0 && <p className="text-slate-500 text-sm">Keranjang masih kosong</p>}
            <div className="space-y-2 max-h-72 overflow-y-auto">
              {cart.map(x => (
                <div key={x.product.id} className="flex items-center gap-2 border-b border-slate-100 pb-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold truncate">{x.product.nama}</div>
                    <div className="text-xs text-slate-500">{fmtRp(x.product.harga)} × {x.qty} = {fmtRp(x.product.harga * x.qty)}</div>
                  </div>
                  <Button data-testid={`qty-minus-${x.product.kode}`} size="icon" variant="outline" onClick={() => changeQty(x.product.id, -1)}><Minus className="w-3 h-3" /></Button>
                  <span className="w-6 text-center font-bold">{x.qty}</span>
                  <Button data-testid={`qty-plus-${x.product.kode}`} size="icon" variant="outline" onClick={() => changeQty(x.product.id, 1)}><Plus className="w-3 h-3" /></Button>
                  <Button size="icon" variant="ghost" onClick={() => removeItem(x.product.id)}><Trash2 className="w-3 h-3 text-red-500" /></Button>
                </div>
              ))}
            </div>
            <div className="text-sm space-y-1 border-t pt-3">
              <div className="flex justify-between"><span>Subtotal</span><span>{fmtRp(subtotal)}</span></div>
              <div className="flex justify-between items-center">
                <Label className="flex-1">Diskon</Label>
                <Input data-testid="kasir-diskon" type="number" min="0" value={diskon} onChange={(e) => setDiskon(e.target.value)} className="h-9 w-32" />
              </div>
              <div className="flex justify-between font-extrabold text-lg pt-1 border-t">
                <span>TOTAL</span><span className="text-blue-700">{fmtRp(total)}</span>
              </div>
            </div>
            <div>
              <Label>Pembayaran (split didukung)</Label>
              <div className="space-y-2 mt-1.5">
                {pays.map((p, idx) => (
                  <div key={idx} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                    <select value={p.metode} onChange={(e) => setPays(ps => ps.map((x, i) => i === idx ? { ...x, metode: e.target.value } : x))} className="h-10 rounded-md border border-slate-300 px-2 bg-white text-sm">
                      <option value="tunai">Tunai</option>
                      <option value="transfer">Transfer</option>
                      <option value="qris">QRIS</option>
                    </select>
                    <Input type="number" min="0" value={p.jumlah} onChange={(e) => setPays(ps => ps.map((x, i) => i === idx ? { ...x, jumlah: e.target.value } : x))} className="h-10" />
                    {pays.length > 1 && <Button size="icon" variant="ghost" onClick={() => setPays(ps => ps.filter((_, i) => i !== idx))}><Trash2 className="w-3 h-3" /></Button>}
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => setPays(ps => [...ps, { metode: "transfer", jumlah: 0 }])}>+ Tambah</Button>
              </div>
              <div className="text-xs mt-2">
                Bayar: <span className="font-bold">{fmtRp(totalPay)}</span>{" • "}
                {kurang > 0 ? <span className="text-red-600">Kurang {fmtRp(kurang)}</span> : <span className="text-emerald-700">Lunas {kurang < 0 ? `(Kembalian ${fmtRp(-kurang)})` : ""}</span>}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Nama Pembeli (opsional)</Label>
                <Input data-testid="kasir-nama-pembeli" placeholder="Utk struk WA" value={namaPembeli} onChange={(e) => setNamaPembeli(e.target.value)} className="h-9 mt-1" />
              </div>
              <div>
                <Label className="text-xs">No. HP (opsional)</Label>
                <Input data-testid="kasir-no-hp-pembeli" placeholder="Utk kirim struk WA" value={noHpPembeli} onChange={(e) => setNoHpPembeli(e.target.value)} className="h-9 mt-1" />
              </div>
            </div>
            <Textarea data-testid="kasir-catatan" placeholder="Catatan (opsional)" value={catatan} onChange={(e) => setCatatan(e.target.value)} rows={2} />
            <Button data-testid="kasir-submit" onClick={submit} className="w-full h-12 bg-blue-700 hover:bg-blue-800 text-base">Bayar Sekarang</Button>
          </div>
        </div>
      </div>

      {last && (
        <Card className="border-emerald-200 bg-emerald-50 no-print">
          <CardContent className="p-4 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div className="font-bold">Transaksi {last.trx_no} berhasil</div>
              <div className="text-sm text-slate-600">{last.items.length} item • {fmtRp(last.total)}</div>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <div className="no-print flex items-center gap-1.5 text-xs text-slate-600">
                <span>Kertas:</span>
                <select
                  data-testid="kasir-lebar-kertas"
                  value={lebarKertas}
                  onChange={(e) => gantiLebarKertas(e.target.value)}
                  className="h-8 rounded-md border border-slate-300 px-2 bg-white"
                >
                  <option value="58">58mm</option>
                  <option value="80">80mm</option>
                </select>
              </div>
              <Button data-testid="kasir-cetak-struk" variant="outline" onClick={() => { window.print(); }}>
                <Printer className="w-4 h-4 mr-2" /> Cetak Struk
              </Button>
              {isBluetoothPrintSupported() && (
                <Button
                  data-testid="kasir-cetak-bluetooth"
                  variant="outline"
                  onClick={async () => {
                    try {
                      await printViaBluetooth(kasirBluetoothLines(last, PAPER_COLS[lebarKertas]));
                      toast.success("Terkirim ke printer Bluetooth");
                    } catch (e) {
                      toast.error(e?.message || "Gagal mencetak via Bluetooth");
                    }
                  }}
                >
                  <Bluetooth className="w-4 h-4 mr-2" /> Cetak Bluetooth
                </Button>
              )}
              {lastBuyer?.no_hp && (
                <a href={kasirReceiptWaLink(last, lastBuyer.no_hp, lastBuyer.nama)} target="_blank" rel="noreferrer">
                  <Button data-testid="kasir-kirim-wa" variant="outline">
                    <MessageCircle className="w-4 h-4 mr-2" /> Kirim Bukti Transaksi WA
                  </Button>
                </a>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      <Receipt trx={last} lebar={lebarKertas} />
    </div>
  );
}
