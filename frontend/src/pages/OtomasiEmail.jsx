import { useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Mail, Inbox, Wand2, FileWarning, CheckCircle2, Unlink, AlertTriangle, Plus, Pencil, Trash2, FlaskConical } from "lucide-react";
import { fmtDateTime, fmtRp } from "@/lib/apiClient";

// Field hasil ekstraksi yang bisa dipetakan — sinkron dengan bentuk `extracted_data`
// di tab Log Email Masuk (lihat MOCK_EMAIL_LOGS di bawah).
const FIELD_OPTIONS = [
  { value: "no_reservasi", label: "Nomor Reservasi" },
  { value: "nama_tamu", label: "Nama Tamu" },
  { value: "tipe_kamar", label: "Tipe Kamar" },
  { value: "check_in", label: "Tanggal Check-in" },
  { value: "check_out", label: "Tanggal Check-out" },
  { value: "harga", label: "Harga" },
  { value: "status_pembayaran", label: "Status Pembayaran" },
];
const fieldLabel = (v) => FIELD_OPTIONS.find((f) => f.value === v)?.label || v;

const SUMBER_OPTIONS = ["Agoda", "Traveloka", "Booking.com", "Lainnya"];

// Data tiruan (stub) — aturan yang menentukan bagaimana AI Email Parser menemukan tiap
// field di badan email tiap sumber OTA (mis. pola regex/kata kunci penanda).
const MOCK_MAPPING_RULES = [
  { id: "1", sumber: "Agoda", field: "no_reservasi", pola: "Booking ID: #AGD-\\d+", aktif: true },
  { id: "2", sumber: "Agoda", field: "nama_tamu", pola: "Guest name: (.+)", aktif: true },
  { id: "3", sumber: "Traveloka", field: "no_reservasi", pola: "Booking Code: (BKN-\\d+)", aktif: true },
  { id: "4", sumber: "Traveloka", field: "harga", pola: "Total Payment: Rp ([\\d.,]+)", aktif: true },
  { id: "5", sumber: "Booking.com", field: "no_reservasi", pola: "Reservation number (\\d+)", aktif: false },
];

// Data tiruan (stub) — log email OTA yang sudah diproses AI Email Parser. `extracted_data`
// mengikuti entitas EMAIL_LOGS di PRD (JSON hasil ekstraksi AI); kosong untuk email yang
// gagal/perlu proses manual, digantikan `alasan`.
const MOCK_EMAIL_LOGS = [
  {
    id: "1", subjek: "Konfirmasi Reservasi #AGD-88213", pengirim: "noreply@agoda.com", sumber: "Agoda",
    status: "Parsed_Success", processed_at: "2026-07-10T08:12:00", gmail_message_id: "18f2a9c7b3e4d501",
    extracted_data: {
      no_reservasi: "AGD-88213", nama_tamu: "Ahmad Fauzi", tipe_kamar: "Standard",
      check_in: "2026-07-12T14:00:00", check_out: "2026-07-14T12:00:00",
      jumlah_tamu: 2, harga: 240000, status_pembayaran: "Lunas",
    },
  },
  {
    id: "2", subjek: "Booking Baru - Traveloka BKN-4471", pengirim: "no-reply@traveloka.com", sumber: "Traveloka",
    status: "Parsed_Success", processed_at: "2026-07-10T09:03:00", gmail_message_id: "18f2a8b1c9d3e402",
    extracted_data: {
      no_reservasi: "BKN-4471", nama_tamu: "Rina Kusuma", tipe_kamar: "Standard",
      check_in: "2026-07-13T14:00:00", check_out: "2026-07-15T12:00:00",
      jumlah_tamu: 2, harga: 240000, status_pembayaran: "Lunas",
    },
  },
  {
    id: "3", subjek: "New reservation confirmed - Booking.com", pengirim: "noreply@booking.com", sumber: "Booking.com",
    status: "Manual_Required", processed_at: "2026-07-10T10:41:00", gmail_message_id: "18f2a6d4a1b2c303",
    extracted_data: null,
    alasan: "Format email Booking.com ini belum dikenali parser AI (template baru) — perlu dipetakan manual di tab \"Proses Manual\".",
  },
  {
    id: "4", subjek: "Pembatalan Pesanan #AGD-88190", pengirim: "noreply@agoda.com", sumber: "Agoda",
    status: "Parsed_Success", processed_at: "2026-07-09T21:15:00", gmail_message_id: "18f29f0e5c6d7204",
    extracted_data: {
      no_reservasi: "AGD-88190", nama_tamu: "Sri Wahyuni", tipe_kamar: "Cottage",
      check_in: "2026-07-10T14:00:00", check_out: "2026-07-11T12:00:00",
      jumlah_tamu: 3, harga: 130000, status_pembayaran: "Dibatalkan",
    },
  },
  {
    id: "5", subjek: "Fwd: Detail Reservasi (format tidak dikenal)", pengirim: "reservasi.staff@gmail.com", sumber: "Lainnya",
    status: "Failed", processed_at: "2026-07-09T18:30:00", gmail_message_id: "18f29c2b4e5f6105",
    extracted_data: null,
    alasan: "Isi email tidak mengandung pola reservasi OTA yang dikenali (kemungkinan email diteruskan manual, bukan notifikasi asli OTA).",
  },
];

const EMAIL_STATUS_BADGE = {
  Parsed_Success: { label: "Berhasil Diproses", cls: "bg-emerald-100 text-emerald-800" },
  Manual_Required: { label: "Perlu Diproses Manual", cls: "bg-amber-100 text-amber-800" },
  Failed: { label: "Gagal", cls: "bg-red-100 text-red-800" },
};

// Layout utama halaman Otomasi Email & Pemesanan (Fase 2). Isi tiap tab (koneksi Gmail,
// log email, aturan pemetaan AI, proses manual) dibangun di task terpisah berikutnya —
// task ini hanya menyusun struktur navigasi & shell halamannya.
const TABS = [
  { value: "koneksi", label: "Hubungkan Gmail", icon: Mail },
  { value: "log", label: "Log Email Masuk", icon: Inbox },
  { value: "aturan", label: "Aturan Pemetaan AI", icon: Wand2 },
  { value: "manual", label: "Proses Manual", icon: FileWarning },
];

function TabPlaceholder({ label }) {
  return (
    <Card className="border-slate-200">
      <CardContent className="p-8 text-center text-slate-500">
        <p className="text-sm">Bagian &ldquo;{label}&rdquo; akan dibangun di task berikutnya.</p>
      </CardContent>
    </Card>
  );
}

// Status koneksi Gmail — data tiruan. OAuth (Client ID/Secret) menyusul di task backend terpisah.
function KoneksiGmail() {
  const [connected, setConnected] = useState(false);
  const [email, setEmail] = useState("");

  const connect = () => {
    // Mock: nanti diganti alur OAuth Google (redirect ke consent screen).
    setConnected(true);
    setEmail("reservasi@pelangihomestay.com");
    toast.success("Gmail terhubung (mock) — reservasi@pelangihomestay.com");
  };

  const disconnect = () => {
    if (!window.confirm("Putuskan koneksi Gmail? Otomasi email OTA akan berhenti sampai dihubungkan lagi.")) return;
    setConnected(false);
    setEmail("");
    toast.success("Koneksi Gmail diputuskan");
  };

  return (
    <Card className="border-slate-200">
      <CardContent className="p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className={`w-11 h-11 rounded-xl grid place-items-center ${connected ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
            <Mail className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold" data-testid="gmail-status-label">
              {connected ? "Gmail Terhubung" : "Belum Terhubung"}
            </div>
            <div className="text-sm text-slate-500" data-testid="gmail-status-detail">
              {connected ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-700">
                  <CheckCircle2 className="w-3.5 h-3.5" /> {email}
                </span>
              ) : (
                "Hubungkan akun Gmail untuk membaca email reservasi OTA secara otomatis."
              )}
            </div>
          </div>
        </div>
        {connected ? (
          <Button data-testid="gmail-disconnect" variant="outline" onClick={disconnect} className="gap-1.5 text-red-600 border-red-300 hover:bg-red-50">
            <Unlink className="w-3.5 h-3.5" /> Putuskan
          </Button>
        ) : (
          <Button data-testid="gmail-connect" onClick={connect} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
            <Mail className="w-3.5 h-3.5" /> Hubungkan Gmail
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function LogEmailDetailDialog({ log, onClose }) {
  return (
    <Dialog open={!!log} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="email-log-detail-title">Detail Email</DialogTitle>
        </DialogHeader>
        {log && (
          <div className="space-y-3 text-sm" data-testid="email-log-detail-body">
            <div className="flex items-center gap-2">
              <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded ${EMAIL_STATUS_BADGE[log.status].cls}`}>
                {EMAIL_STATUS_BADGE[log.status].label}
              </span>
              <span className="text-[10px] uppercase font-bold px-2 py-1 rounded bg-slate-100 text-slate-600">{log.sumber}</span>
            </div>
            <div><span className="text-slate-500">Subjek:</span> <b>{log.subjek}</b></div>
            <div><span className="text-slate-500">Pengirim:</span> {log.pengirim}</div>
            <div><span className="text-slate-500">Diproses Pada:</span> {fmtDateTime(log.processed_at)}</div>
            {log.gmail_message_id && (
              <div><span className="text-slate-500">Gmail Message ID:</span> <span className="font-mono text-xs">{log.gmail_message_id}</span></div>
            )}

            {log.extracted_data ? (
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 mt-2 space-y-1.5">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Data Hasil Ekstraksi AI</p>
                <div><span className="text-slate-500">No. Reservasi:</span> <b>{log.extracted_data.no_reservasi}</b></div>
                <div><span className="text-slate-500">Nama Tamu:</span> {log.extracted_data.nama_tamu}</div>
                <div><span className="text-slate-500">Tipe Kamar:</span> {log.extracted_data.tipe_kamar}</div>
                <div><span className="text-slate-500">Check-in:</span> {fmtDateTime(log.extracted_data.check_in)}</div>
                <div><span className="text-slate-500">Check-out:</span> {fmtDateTime(log.extracted_data.check_out)}</div>
                <div><span className="text-slate-500">Jumlah Tamu:</span> {log.extracted_data.jumlah_tamu}</div>
                <div className="flex justify-between pt-1 border-t border-slate-200 mt-1">
                  <span className="font-bold">Harga</span><b className="text-blue-700">{fmtRp(log.extracted_data.harga)}</b>
                </div>
                <div><span className="text-slate-500">Status Pembayaran:</span> {log.extracted_data.status_pembayaran}</div>
              </div>
            ) : (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mt-2 flex gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                <p className="text-amber-800">{log.alasan || "AI tidak berhasil mengekstrak data reservasi dari email ini."}</p>
              </div>
            )}
            <p className="text-[11px] text-slate-400 pt-1">Data tiruan — belum tersambung ke Gmail sungguhan.</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const emptyRuleForm = { sumber: SUMBER_OPTIONS[0], field: FIELD_OPTIONS[0].value, pola: "" };

function AturanRuleDialog({ open, onOpenChange, initial, onSave }) {
  const [form, setForm] = useState(initial || emptyRuleForm);

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (o) setForm(initial || emptyRuleForm); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle data-testid="mapping-rule-form-title">{initial ? "Ubah Aturan" : "Tambah Aturan"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div>
            <Label>Sumber OTA</Label>
            <select
              data-testid="mapping-rule-sumber"
              value={form.sumber}
              onChange={(e) => setForm((f) => ({ ...f, sumber: e.target.value }))}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
            >
              {SUMBER_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <Label>Field yang Diekstrak</Label>
            <select
              data-testid="mapping-rule-field"
              value={form.field}
              onChange={(e) => setForm((f) => ({ ...f, field: e.target.value }))}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
            >
              {FIELD_OPTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </div>
          <div>
            <Label>Pola / Kata Kunci Penanda</Label>
            <Input
              data-testid="mapping-rule-pola"
              value={form.pola}
              onChange={(e) => setForm((f) => ({ ...f, pola: e.target.value }))}
              placeholder="Mis: Booking ID: #AGD-\d+"
              className="mt-1.5 font-mono text-sm"
            />
            <p className="text-xs text-slate-400 mt-1">Teks/pola penanda yang dipakai AI untuk menemukan nilai field ini di badan email.</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button
            data-testid="mapping-rule-save"
            className="bg-blue-700 hover:bg-blue-800"
            disabled={!form.pola.trim()}
            onClick={() => { onSave(form); onOpenChange(false); }}
          >
            Simpan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Uji aturan pemetaan dengan menempel contoh isi email — regex tiap aturan aktif untuk
// sumber terpilih benar-benar dijalankan (bukan hasil acak) terhadap teks yang ditempel,
// jadi staff bisa cek apakah pola yang dibuat memang akan menangkap data yang benar
// sebelum aturan itu dipakai AI Email Parser sungguhan.
function UjiAturan({ rules }) {
  const [sumber, setSumber] = useState(SUMBER_OPTIONS[0]);
  const [contohEmail, setContohEmail] = useState("");
  const [hasil, setHasil] = useState(null);

  const aturanAktif = rules.filter((r) => r.sumber === sumber && r.aktif);

  const jalankanUji = () => {
    const rows = aturanAktif.map((r) => {
      let nilai = null;
      let polaValid = true;
      try {
        const m = contohEmail.match(new RegExp(r.pola));
        nilai = m ? (m[1] ?? m[0]) : null;
      } catch {
        polaValid = false;
      }
      return { ...r, nilai, polaValid };
    });
    setHasil(rows);
    if (rows.length === 0) {
      toast.error(`Tidak ada aturan aktif untuk sumber ${sumber}`);
    } else {
      const cocok = rows.filter((r) => r.nilai !== null).length;
      toast.success(`Uji selesai: ${cocok}/${rows.length} field cocok`);
    }
  };

  return (
    <Card className="border-slate-200">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <FlaskConical className="w-4 h-4" /> Uji Aturan dengan Contoh Email
        </div>
        <p className="text-xs text-slate-500 -mt-2">
          Tempel isi email OTA yang sebenarnya di sini untuk mengecek apakah aturan di atas berhasil menangkap datanya.
        </p>
        <div className="grid sm:grid-cols-[160px_1fr] gap-3 items-start">
          <div>
            <Label>Sumber OTA</Label>
            <select
              data-testid="uji-aturan-sumber"
              value={sumber}
              onChange={(e) => { setSumber(e.target.value); setHasil(null); }}
              className="w-full h-10 rounded-md border border-slate-300 px-3 bg-white mt-1.5"
            >
              {SUMBER_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <Label>Contoh Isi Email</Label>
            <Textarea
              data-testid="uji-aturan-contoh"
              value={contohEmail}
              onChange={(e) => { setContohEmail(e.target.value); setHasil(null); }}
              placeholder={"Tempel isi email di sini, mis:\nBooking ID: #AGD-88213\nGuest name: Ahmad Fauzi"}
              className="mt-1.5 min-h-[100px] font-mono text-xs"
            />
          </div>
        </div>
        <Button data-testid="uji-aturan-jalankan" onClick={jalankanUji} className="gap-1.5 bg-blue-700 hover:bg-blue-800">
          <FlaskConical className="w-3.5 h-3.5" /> Jalankan Uji
        </Button>

        {hasil && (
          <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 mt-2" data-testid="uji-aturan-hasil">
            {hasil.map((r) => (
              <div key={r.id} className="p-2.5 flex items-center justify-between text-sm gap-3">
                <span className="text-slate-500">{fieldLabel(r.field)}</span>
                {!r.polaValid ? (
                  <span className="text-xs font-medium text-red-700 bg-red-100 px-2 py-1 rounded">Pola regex tidak valid</span>
                ) : r.nilai !== null ? (
                  <span className="text-xs font-medium text-emerald-700 bg-emerald-100 px-2 py-1 rounded font-mono">{r.nilai}</span>
                ) : (
                  <span className="text-xs font-medium text-amber-700 bg-amber-100 px-2 py-1 rounded">Tidak ditemukan</span>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AturanPemetaanAI() {
  const [rules, setRules] = useState(MOCK_MAPPING_RULES);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null); // rule yang sedang diubah, null = tambah baru

  const openAdd = () => { setEditing(null); setFormOpen(true); };
  const openEdit = (rule) => { setEditing(rule); setFormOpen(true); };

  const saveRule = (form) => {
    if (editing) {
      setRules((rs) => rs.map((r) => (r.id === editing.id ? { ...editing, ...form } : r)));
      toast.success(`Aturan ${fieldLabel(form.field)} (${form.sumber}) diperbarui`);
    } else {
      const newRule = { id: crypto.randomUUID(), aktif: true, ...form };
      setRules((rs) => [...rs, newRule]);
      toast.success(`Aturan baru untuk ${form.sumber} ditambahkan`);
    }
  };

  const toggleAktif = (rule) => {
    setRules((rs) => rs.map((r) => (r.id === rule.id ? { ...r, aktif: !r.aktif } : r)));
    toast.success(`Aturan ${fieldLabel(rule.field)} (${rule.sumber}) ${rule.aktif ? "dinonaktifkan" : "diaktifkan"}`);
  };

  const deleteRule = (rule) => {
    if (!window.confirm(`Hapus aturan "${fieldLabel(rule.field)}" untuk sumber ${rule.sumber}?`)) return;
    setRules((rs) => rs.filter((r) => r.id !== rule.id));
    toast.success("Aturan dihapus");
  };

  return (
    <div className="space-y-4">
    <Card className="border-slate-200">
      <CardContent className="p-0">
        <div className="p-4 flex items-center justify-between border-b border-slate-100">
          <p className="text-sm text-slate-500">Atur pola/kata kunci yang dipakai AI untuk menemukan tiap data di email OTA.</p>
          <Button data-testid="mapping-rule-add" size="sm" onClick={openAdd} className="gap-1.5 bg-blue-700 hover:bg-blue-800 shrink-0">
            <Plus className="w-3.5 h-3.5" /> Tambah Aturan
          </Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="mapping-rules-table">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left p-3">Sumber OTA</th>
                <th className="text-left p-3">Field</th>
                <th className="text-left p-3">Pola / Kata Kunci</th>
                <th className="text-left p-3">Status</th>
                <th className="text-right p-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} data-testid={`mapping-rule-row-${r.id}`} className="border-t border-slate-100">
                  <td className="p-3 font-medium">{r.sumber}</td>
                  <td className="p-3">{fieldLabel(r.field)}</td>
                  <td className="p-3 font-mono text-xs text-slate-500">{r.pola}</td>
                  <td className="p-3">
                    <button
                      data-testid={`mapping-rule-toggle-${r.id}`}
                      onClick={() => toggleAktif(r)}
                      className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${r.aktif ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-600"}`}
                    >
                      {r.aktif ? "Aktif" : "Nonaktif"}
                    </button>
                  </td>
                  <td className="p-3">
                    <div className="flex justify-end gap-1">
                      <Button data-testid={`mapping-rule-edit-${r.id}`} variant="ghost" size="icon" onClick={() => openEdit(r)}>
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      <Button data-testid={`mapping-rule-delete-${r.id}`} variant="ghost" size="icon" onClick={() => deleteRule(r)} className="text-red-600 hover:bg-red-50">
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {rules.length === 0 && (
                <tr><td colSpan={5} className="p-6 text-center text-slate-500">Belum ada aturan pemetaan</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
      <AturanRuleDialog open={formOpen} onOpenChange={setFormOpen} initial={editing} onSave={saveRule} />
    </Card>
    <UjiAturan rules={rules} />
    </div>
  );
}

function LogEmail() {
  const [selected, setSelected] = useState(null);
  return (
    <Card className="border-slate-200">
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm" data-testid="email-log-table">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left p-3">Subjek</th>
              <th className="text-left p-3">Pengirim</th>
              <th className="text-left p-3">Sumber</th>
              <th className="text-left p-3">Diproses Pada</th>
              <th className="text-left p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {MOCK_EMAIL_LOGS.map((e) => {
              const badge = EMAIL_STATUS_BADGE[e.status];
              return (
                <tr
                  key={e.id}
                  data-testid={`email-log-row-${e.id}`}
                  onClick={() => setSelected(e)}
                  className="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                >
                  <td className="p-3 font-medium">{e.subjek}</td>
                  <td className="p-3 text-slate-500">{e.pengirim}</td>
                  <td className="p-3">{e.sumber}</td>
                  <td className="p-3">{fmtDateTime(e.processed_at)}</td>
                  <td className="p-3">
                    <span className={`inline-flex px-2 py-1 rounded-md text-xs font-medium ${badge.cls}`}>{badge.label}</span>
                  </td>
                </tr>
              );
            })}
            {MOCK_EMAIL_LOGS.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-slate-500">Belum ada email yang diproses</td></tr>
            )}
          </tbody>
        </table>
      </CardContent>
      <LogEmailDetailDialog log={selected} onClose={() => setSelected(null)} />
    </Card>
  );
}

export default function OtomasiEmail() {
  return (
    <div className="space-y-6" data-testid="otomasi-email-page">
      <div>
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fase 2 — AI Reservation Automation</p>
        <h1 className="text-3xl sm:text-4xl font-extrabold">Otomasi Email &amp; Pemesanan</h1>
        <p className="text-slate-500 mt-1">
          Baca email konfirmasi OTA secara otomatis dan buat reservasi tanpa input manual.
        </p>
      </div>

      <Tabs defaultValue="koneksi">
        <TabsList data-testid="otomasi-email-tabs">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} data-testid={`tab-${t.value}`} className="gap-1.5">
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="koneksi" className="mt-4">
          <KoneksiGmail />
        </TabsContent>
        <TabsContent value="log" className="mt-4">
          <LogEmail />
        </TabsContent>
        <TabsContent value="aturan" className="mt-4">
          <AturanPemetaanAI />
        </TabsContent>
        {TABS.filter((t) => !["koneksi", "log", "aturan"].includes(t.value)).map((t) => (
          <TabsContent key={t.value} value={t.value} className="mt-4">
            <TabPlaceholder label={t.label} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
