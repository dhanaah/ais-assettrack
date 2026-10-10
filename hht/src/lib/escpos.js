// ESC/POS byte builder for 2" (58 mm, 384 dots) and 3" (80 mm, 576 dots) thermal printers such as the SEZNIK DEV.
// Text uses the printer's own font; logo and QR go as raster images (GS v 0) so every ESC/POS printer prints them the same.
// Developed by DT
import qrcode from 'qrcode-generator';
import { LOGO_RASTER } from './printLogoRaster';

const ESC = 0x1b, GS = 0x1d;
const enc = (s) => Array.from(String(s), (ch) => { const c = ch.charCodeAt(0); return c < 128 ? c : 0x3f; });   // ASCII only (printer code page)

export class EscPos {
  constructor(dots = 384) { this.b = []; this.dots = dots; this.cols = dots >= 576 ? 48 : 32; }
  raw(...bytes) { this.b.push(...bytes); return this; }
  init() { return this.raw(ESC, 0x40); }
  align(a) { return this.raw(ESC, 0x61, { left: 0, center: 1, right: 2 }[a] ?? 0); }
  bold(on) { return this.raw(ESC, 0x45, on ? 1 : 0); }
  size(w = 1, h = 1) { return this.raw(GS, 0x21, ((w - 1) << 4) | (h - 1)); }
  text(s) { return this.raw(...enc(s)); }
  line(s = '') { return this.text(s).raw(0x0a); }
  feed(n = 3) { return this.raw(ESC, 0x64, n); }
  cut() { return this.raw(GS, 0x56, 0x42, 0x00); }
  rule(ch = '-') { return this.line(ch.repeat(this.cols)); }
  pad(l, r) { const w = this.cols; const s = l + ' '.repeat(Math.max(1, w - l.length - r.length)) + r; return this.line(s.slice(0, w)); }
  /** GS v 0 raster: rows = array of Uint8Array/arrays of packed bits (1 = black), widthBytes per row. */
  raster(rows, widthBytes) {
    const h = rows.length;
    this.raw(GS, 0x76, 0x30, 0x00, widthBytes & 0xff, (widthBytes >> 8) & 0xff, h & 0xff, (h >> 8) & 0xff);
    for (const r of rows) for (let i = 0; i < widthBytes; i++) this.b.push(r[i] || 0);
    return this;
  }
  logo() {
    const { widthBytes, height, data } = LOGO_RASTER;
    const bytes = base64ToBytes(data);
    if (widthBytes * 8 > this.dots) return this;          // logo is 384 px wide - fits 2" and 3"
    const rows = []; for (let y = 0; y < height; y++) rows.push(bytes.subarray(y * widthBytes, (y + 1) * widthBytes));
    const padL = Math.floor((this.dots / 8 - widthBytes) / 2);
    if (padL > 0) { const wb = this.dots / 8; return this.raster(rows.map((r) => { const o = new Uint8Array(wb); o.set(r, padL); return o; }), wb); }
    return this.raster(rows, widthBytes);
  }
  /** QR as raster, centred. scale = dots per module (6 -> ~ 30 mm for a 41-module code). */
  qr(text, { scale = 6, ecl = 'M', quiet = 2 } = {}) {
    const q = qrcode(0, ecl); q.addData(text); q.make();
    const n = q.getModuleCount(); const side = (n + quiet * 2) * scale;
    const wb = this.dots / 8; const rows = []; const offX = Math.max(0, Math.floor((this.dots - side) / 2));
    for (let my = 0; my < n + quiet * 2; my++) {
      const row = new Uint8Array(wb);
      for (let mx = 0; mx < n + quiet * 2; mx++) {
        const r = my - quiet, c = mx - quiet;
        if (r < 0 || c < 0 || r >= n || c >= n || !q.isDark(r, c)) continue;
        for (let s = 0; s < scale; s++) { const x = offX + mx * scale + s; row[x >> 3] |= 0x80 >> (x & 7); }
      }
      for (let s = 0; s < scale; s++) rows.push(row);
    }
    return this.raster(rows, wb);
  }
  bytes() { return Uint8Array.from(this.b); }
  base64() { return bytesToBase64(this.bytes()); }
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
export function bytesToBase64(bytes) {
  let out = ''; let i = 0;
  for (; i + 2 < bytes.length; i += 3) { const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2]; out += B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + B64[n & 63]; }
  if (i < bytes.length) { const n = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8); out += B64[n >> 18] + B64[(n >> 12) & 63] + (i + 1 < bytes.length ? B64[(n >> 6) & 63] : '=') + '='; }
  return out;
}
export function base64ToBytes(s) {
  s = s.replace(/[^A-Za-z0-9+/]/g, '');
  const out = []; let acc = 0, bits = 0;
  for (let i = 0; i < s.length; i++) {
    acc = (acc << 6) | B64.indexOf(s[i]); bits += 6;
    if (bits >= 8) { bits -= 8; out.push((acc >> bits) & 255); acc &= (1 << bits) - 1; }
  }
  return Uint8Array.from(out);
}
