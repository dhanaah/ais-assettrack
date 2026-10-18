// AIS AssetTrack HHT - printdoc.js. Developed by DT
// Printer-independent slip layout + converters to the printer's own language, so any Bluetooth printer can be used:
//   ESC/POS  - most portable receipt printers (SEZNIK, Xprinter, Rongta, Epson, Bixolon, MTP, generic "58mm/80mm")
//   CPCL     - Zebra / Honeywell / Intermec mobile printers
//   ZPL      - Zebra printers in ZPL mode
//   TSPL     - TSC / Xprinter / Gprinter label printers
//   HTML     - Android print (any printer with its maker's print app / plugin, Wi-Fi or Bluetooth)
// Text uses the printer's own monospace font; logo and QR are bitmaps built here (identical on every printer).
// Developed by DT
import qrcode from 'qrcode-generator';
import { LOGO_RASTER } from './printLogoRaster';
import { EscPos, base64ToBytes } from './escpos';

/** Same chain API the slip builders always used (align / bold / size / line / rule / pad / logo / qr / feed / cut). */
export class Doc {
  constructor(dots = 384) { this.ops = []; this.dots = dots; this.cols = Math.floor(dots / 12); }
  _(o) { this.ops.push(o); return this; }
  init() { return this; }
  align(a) { return this._({ t: 'align', a }); }
  bold(on) { return this._({ t: 'bold', on: !!on }); }
  size(w = 1, h = 1) { return this._({ t: 'size', w, h }); }
  line(s = '') { return this._({ t: 'line', s: String(s) }); }
  text(s) { return this.line(s); }
  feed(n = 3) { return this._({ t: 'feed', n }); }
  cut() { return this._({ t: 'cut' }); }
  rule(ch = '-') { return this.line(ch.repeat(this.cols)); }
  pad(l, r) { const w = this.cols; const s = l + ' '.repeat(Math.max(1, w - l.length - r.length)) + r; return this.line(s.slice(0, w)); }
  logo() { return this._({ t: 'logo' }); }
  qr(text, { scale = 6 } = {}) { return this._({ t: 'qr', text: String(text), scale }); }
}

// ---------------------------------------------------------------- bitmaps (rows of packed bits, 1 = black)
function logoBitmap(dots) {
  const { widthBytes, height, data } = LOGO_RASTER; const bytes = base64ToBytes(data);
  const wb = Math.ceil(dots / 8); const pad = Math.max(0, Math.floor((wb - widthBytes) / 2)); const rows = [];
  for (let y = 0; y < height; y++) { const o = new Uint8Array(wb); o.set(bytes.subarray(y * widthBytes, y * widthBytes + Math.min(widthBytes, wb)), pad); rows.push(o); }
  return { rows, wb, h: height };
}
function qrBitmap(text, scale, dots) {
  const q = qrcode(0, 'M'); q.addData(text); q.make();
  const n = q.getModuleCount(); const quiet = 2;
  scale = Math.max(2, Math.min(scale, Math.floor(dots / (n + quiet * 2))));
  const side = (n + quiet * 2) * scale; const wb = Math.ceil(dots / 8); const offX = Math.max(0, Math.floor((dots - side) / 2)); const rows = [];
  for (let my = 0; my < n + quiet * 2; my++) {
    const row = new Uint8Array(wb);
    for (let mx = 0; mx < n + quiet * 2; mx++) {
      const r = my - quiet, c = mx - quiet;
      if (r < 0 || c < 0 || r >= n || c >= n || !q.isDark(r, c)) continue;
      for (let s = 0; s < scale; s++) { const x = offX + mx * scale + s; row[x >> 3] |= 0x80 >> (x & 7); }
    }
    for (let s = 0; s < scale; s++) rows.push(row);
  }
  return { rows, wb, h: rows.length };
}
const hex = (rows) => rows.map((r) => Array.from(r, (b) => b.toString(16).padStart(2, '0')).join('')).join('').toUpperCase();
const ascii = (s) => String(s).replace(/[^\x20-\x7e]/g, '?');
const enc = (s) => Array.from(s, (c) => c.charCodeAt(0) & 0xff);

// ---------------------------------------------------------------- ESC/POS
export function toEscPos(doc, img = 'raster') {
  const p = new EscPos(doc.dots); p.init();
  for (const o of doc.ops) {
    if (o.t === 'align') p.align(o.a); else if (o.t === 'bold') p.bold(o.on); else if (o.t === 'size') p.size(o.w, o.h);
    else if (o.t === 'line') p.line(o.s); else if (o.t === 'feed') p.feed(o.n); else if (o.t === 'cut') p.cut();
    else if (o.t === 'logo') { if (img === 'native') p.bold(true).line('ASAHI INDIA GLASS LTD.').line('AssetTrack').bold(false); else { const b = logoBitmap(doc.dots); img === 'escstar' ? p.bitImage(b.rows, b.wb) : p.raster(b.rows, b.wb); } }
    else if (o.t === 'qr') { if (img === 'native') p.qrNative(o.text, Math.max(4, o.scale)); else { const b = qrBitmap(o.text, o.scale, doc.dots); img === 'escstar' ? p.bitImage(b.rows, b.wb) : p.raster(b.rows, b.wb); } }
  }
  return p.bytes();
}

// ---------------------------------------------------------------- layout for page languages (CPCL / ZPL / TSPL)
function layout(doc, charW, lineH) {
  const items = []; let y = 10, align = 'left', bold = false, w = 1, h = 1;
  for (const o of doc.ops) {
    if (o.t === 'align') align = o.a; else if (o.t === 'bold') bold = o.on; else if (o.t === 'size') { w = o.w; h = o.h; }
    else if (o.t === 'line') {
      const s = ascii(o.s); const width = s.length * charW * w;
      const x = align === 'center' ? Math.max(0, Math.floor((doc.dots - width) / 2)) : align === 'right' ? Math.max(0, doc.dots - width) : 0;
      if (s.trim()) items.push({ k: 'text', x, y, s, bold, w, h });
      y += lineH * h + 4;
    } else if (o.t === 'feed') y += lineH * o.n;
    else if (o.t === 'logo' || o.t === 'qr') { const b = o.t === 'logo' ? logoBitmap(doc.dots) : qrBitmap(o.text, o.scale, doc.dots); items.push({ k: 'img', x: 0, y, b }); y += b.h + 4; }
  }
  return { items, height: y + 16 };
}

export function toCpcl(doc) {
  const { items, height } = layout(doc, 12, 24); const L = [`! 0 200 200 ${height} 1`, `PAGE-WIDTH ${doc.dots}`];
  for (const it of items) {
    if (it.k === 'img') L.push(`EG ${it.b.wb} ${it.b.h} 0 ${it.y} ${hex(it.b.rows)}`);
    else { L.push(`SETMAG ${it.w} ${it.h}`, `SETBOLD ${it.bold ? 1 : 0}`, `TEXT 7 0 ${it.x} ${it.y} ${it.s}`); }
  }
  L.push('SETMAG 0 0', 'SETBOLD 0', 'FORM', 'PRINT', '');
  return Uint8Array.from(enc(L.join('\r\n')));
}

export function toZpl(doc) {
  const { items, height } = layout(doc, 10, 22); const L = ['^XA', '^CI0', `^PW${doc.dots}`, `^LL${height}`, '^LH0,0'];
  for (const it of items) {
    if (it.k === 'img') { const tot = it.b.wb * it.b.h; L.push(`^FO0,${it.y}^GFA,${tot},${tot},${it.b.wb},${hex(it.b.rows)}^FS`); }
    else { const s = it.s.replace(/[\^~]/g, ' '); L.push(`^FO${it.x},${it.y}^ADN,${18 * it.h},${10 * it.w}^FD${s}^FS`); if (it.bold) L.push(`^FO${it.x + 1},${it.y}^ADN,${18 * it.h},${10 * it.w}^FD${s}^FS`); }
  }
  L.push('^XZ', '');
  return Uint8Array.from(enc(L.join('\n')));
}

export function toTspl(doc) {
  const { items, height } = layout(doc, 12, 22); const out = [];
  const push = (s) => out.push(...enc(s + '\r\n'));
  push(`SIZE ${Math.round(doc.dots / 8)} mm,${Math.ceil(height / 8)} mm`); push('GAP 0 mm,0 mm'); push('DIRECTION 0'); push('CLS');
  for (const it of items) {
    if (it.k === 'img') {                                   // TSPL bitmap: bit 0 = dot printed -> invert
      out.push(...enc(`BITMAP 0,${it.y},${it.b.wb},${it.b.h},0,`)); for (const r of it.b.rows) for (const v of r) out.push(~v & 0xff); push('');
    } else { const s = it.s.replace(/"/g, "'"); push(`TEXT ${it.x},${it.y},"2",0,${it.w},${it.h},"${s}"`); if (it.bold) push(`TEXT ${it.x + 1},${it.y},"2",0,${it.w},${it.h},"${s}"`); }
  }
  push('PRINT 1,1');
  return Uint8Array.from(out);
}

/** Android print (expo-print): the slip as a small HTML page - logo, QR and text the same as on the thermal slip. */
export function toHtml(docs, logoPngB64) {
  docs = Array.isArray(docs) ? docs : [docs];
  const mm = Math.round(docs[0].dots / 8);
  const body = docs.map((d, i) => `<div style="${i < docs.length - 1 ? 'page-break-after:always' : ''}">${htmlBody(d, logoPngB64)}</div>`).join('');
  return `<!doctype html><html><head><meta charset="utf-8"><style>@page{size:${mm}mm auto;margin:3mm}body{font-family:monospace;margin:0;width:${mm - 6}mm}</style></head><body>${body}</body></html>`;
}
function htmlBody(doc, logoPngB64) {
  let html = '', align = 'left', bold = false, w = 1, h = 1;
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  for (const o of doc.ops) {
    if (o.t === 'align') align = o.a; else if (o.t === 'bold') bold = o.on; else if (o.t === 'size') { w = o.w; h = o.h; }
    else if (o.t === 'line') html += `<div style="text-align:${align};font-weight:${bold ? 700 : 400};font-size:${11 * h}px;white-space:pre">${esc(o.s) || '&nbsp;'}</div>`;
    else if (o.t === 'feed') html += '<div style="height:10px"></div>';
    else if (o.t === 'logo' && logoPngB64) html += `<div style="text-align:center"><img src="data:image/png;base64,${logoPngB64}" style="width:70%"></div>`;
    else if (o.t === 'qr') { const q = qrcode(0, 'M'); q.addData(o.text); q.make(); html += `<div style="text-align:center;margin:6px 0">${q.createSvgTag({ cellSize: 3, margin: 2, scalable: true }).replace('<svg ', '<svg style="width:45%" ')}</div>`; }
  }
  return html;
}

/** One small sample per language: the readable one tells which language the printer speaks. */
export function languageSample(lang, dots) {
  const d = new Doc(dots); d.align('center').bold(true).line(`>> ${lang.toUpperCase()} <<`).bold(false).line('If you can read this,').line(`choose ${lang.toUpperCase()}`).line('in AssetTrack Settings').feed(3);
  return lang === 'cpcl' ? toCpcl(d) : lang === 'zpl' ? toZpl(d) : lang === 'tspl' ? toTspl(d) : toEscPos(d, 'native');
}
