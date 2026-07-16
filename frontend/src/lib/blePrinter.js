/**
 * Cetak struk ke printer thermal Bluetooth (BLE) langsung dari browser, tanpa aplikasi
 * native — pakai Web Bluetooth API. Cocok untuk printer thermal BLE generik (mayoritas
 * printer kasir portable murah pakai GATT service/characteristic "generic serial" di
 * bawah), yang menerima command ESC/POS mentah lewat characteristic write.
 *
 * Catatan dukungan browser: Web Bluetooth hanya jalan di Chrome/Edge Android & Desktop
 * lewat origin HTTPS — TIDAK jalan di iOS Safari (keterbatasan Apple, bukan bug kita).
 * Untuk printer biasa (non-Bluetooth) tetap pakai window.print() seperti sebelumnya.
 */

// UUID service/characteristic "generic serial" yang paling umum dipakai printer thermal
// BLE generik (mis. banyak printer 58mm/80mm murah bermerk Goojprt/HM-A300/dst).
const PRINTER_SERVICE_UUID = "000018f0-0000-1000-8000-00805f9b34fb";
const PRINTER_CHAR_UUID = "00002af1-0000-1000-8000-00805f9b34fb";

const ESC = 0x1b;
const GS = 0x1d;

let cachedDevice = null;
let cachedCharacteristic = null;

export function isBluetoothPrintSupported() {
  return typeof navigator !== "undefined" && !!navigator.bluetooth;
}

async function getCharacteristic() {
  if (cachedCharacteristic && cachedDevice?.gatt?.connected) return cachedCharacteristic;
  if (!isBluetoothPrintSupported()) {
    throw new Error("Browser ini tidak mendukung Web Bluetooth (pakai Chrome di Android/Desktop, bukan Safari/iOS).");
  }
  const device = await navigator.bluetooth.requestDevice({
    filters: [{ services: [PRINTER_SERVICE_UUID] }],
    optionalServices: [PRINTER_SERVICE_UUID],
  });
  const server = await device.gatt.connect();
  const service = await server.getPrimaryService(PRINTER_SERVICE_UUID);
  const characteristic = await service.getCharacteristic(PRINTER_CHAR_UUID);
  cachedDevice = device;
  cachedCharacteristic = characteristic;
  device.addEventListener("gattserverdisconnected", () => {
    cachedDevice = null;
    cachedCharacteristic = null;
  });
  return characteristic;
}

async function writeBytes(characteristic, bytes) {
  // Kebanyakan printer BLE cuma terima potongan kecil per write (MTU default ~20 byte) —
  // dipecah supaya kompatibel lintas merek/firmware, ditulis berurutan (GATT queue serial).
  const CHUNK = 20;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const chunk = bytes.slice(i, i + CHUNK);
    if (characteristic.writeValueWithoutResponse) {
      await characteristic.writeValueWithoutResponse(chunk);
    } else {
      await characteristic.writeValue(chunk);
    }
  }
}

function concatBytes(arrays) {
  const total = arrays.reduce((n, a) => n + a.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const a of arrays) { out.set(a, offset); offset += a.length; }
  return out;
}

const enc = new TextEncoder();

/**
 * Bangun payload ESC/POS dari daftar baris teks (array of string, sudah termasuk
 * newline manual kalau perlu) — plain text, align kiri, tanpa markdown/emoji (printer
 * thermal generik cuma dukung charset dasar).
 */
export function buildEscPosText(lines) {
  const parts = [
    new Uint8Array([ESC, 0x40]), // ESC @ — initialize
  ];
  for (const line of lines) {
    parts.push(enc.encode(line + "\n"));
  }
  parts.push(enc.encode("\n\n\n"));
  parts.push(new Uint8Array([GS, 0x56, 0x00])); // GS V 0 — full cut
  return concatBytes(parts);
}

/** Connect (kalau belum) & kirim struk (array baris teks) ke printer Bluetooth. */
export async function printViaBluetooth(lines) {
  const characteristic = await getCharacteristic();
  const payload = buildEscPosText(lines);
  await writeBytes(characteristic, payload);
}

/** Baris kanan-rata untuk kolom label/nilai pada lebar kertas (default 32 kolom = 58mm). */
export function padRow(label, value, width = 32) {
  const l = String(label);
  const v = String(value);
  const gap = Math.max(1, width - l.length - v.length);
  return l + " ".repeat(gap) + v;
}

export function centerRow(text, width = 32) {
  const t = String(text);
  const pad = Math.max(0, Math.floor((width - t.length) / 2));
  return " ".repeat(pad) + t;
}

export function divider(width = 32) {
  return "-".repeat(width);
}
