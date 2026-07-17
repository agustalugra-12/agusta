// Bunyi alert notifikasi (pembayaran/booking/komplain baru) — disintesis pakai Web Audio
// API, tidak butuh file audio eksternal. Browser memblokir autoplay audio tanpa interaksi
// user dulu, jadi AudioContext dibuat malas & di-resume saat user pertama kali klik/ketik
// di mana pun dalam app (lihat unlockAlertSound, dipanggil dari Layout).

let ctx = null;

function getCtx() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  return ctx;
}

export function unlockAlertSound() {
  const c = getCtx();
  if (c && c.state === "suspended") c.resume();
}

/** Nada dua-ketuk pendek (mirip "cha-ching" sederhana) — dipanggil tiap ada push masuk
 * selagi tab PMS sedang dibuka, supaya resepsionis/owner langsung sadar tanpa perlu
 * bergantung pada suara notifikasi OS (yang sering di-mute/generik). */
export function playAlertSound() {
  const c = getCtx();
  if (!c) return;
  if (c.state === "suspended") c.resume();
  const now = c.currentTime;
  [[880, now, 0.15], [1320, now + 0.12, 0.18]].forEach(([freq, start, dur]) => {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.3, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
    osc.connect(gain).connect(c.destination);
    osc.start(start);
    osc.stop(start + dur + 0.05);
  });
}
