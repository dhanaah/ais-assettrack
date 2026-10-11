// Printing on whatever portable printer is at hand - not tied to one model. Settings > Printer chooses:
//   connection : Bluetooth (classic, paired in Android)  |  Bluetooth LE (scan)  |  Android print (printer's own app/plugin)
//   language   : ESC/POS (most receipt printers: SEZNIK, Xprinter, Rongta, Epson, MTP...) | CPCL (Zebra/Honeywell mobile)
//                | ZPL (Zebra) | TSPL (TSC / label printers)
//   width      : 2" 58 mm (384 dots) | 3" 80 mm (576) | 4" 104 mm (832)
//   images     : raster (GS v 0, default) | ESC * (older ESC/POS) | text only (printer's own QR)
// Slips are laid out once (./printdoc.js) and converted to the chosen language. Developed by DT
import { PermissionsAndroid, Platform } from 'react-native';
import { kv } from './db';
import { bytesToBase64 } from './escpos';
import { Doc, toEscPos, toCpcl, toZpl, toTspl, toHtml, languageSample } from './printdoc';
import { bleAvailable, bleScan, bleOpen, bleWrite } from './ble';
import { PRINT_LOGO_B64 } from './printLogo';
import { fDT } from './when';

let RNBC = null;
try { RNBC = require('react-native-bluetooth-classic').default; } catch (e) { RNBC = null; }
let ExpoPrint = null;
try { ExpoPrint = require('expo-print'); } catch (e) { ExpoPrint = null; }

export const LANGS = [['escpos', 'ESC/POS'], ['cpcl', 'CPCL'], ['zpl', 'ZPL'], ['tspl', 'TSPL']];
export const CONNS = [['bt', 'Bluetooth'], ['ble', 'Bluetooth LE'], ['system', 'Android print']];
export const WIDTHS = [['384', '2" 58mm'], ['576', '3" 80mm'], ['832', '4" 104mm']];
export const IMGS = [['raster', 'Raster'], ['escstar', 'Old ESC*'], ['native', 'Text only']];

export const printerAvailable = () => !!(RNBC || bleAvailable() || ExpoPrint);
export const connAvailable = (c) => (c === 'bt' ? !!RNBC : c === 'ble' ? bleAvailable() : !!ExpoPrint);
const CHUNK = 512, CHUNK_DELAY_MS = 40;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function getConfig() {
  const [conn, lang, dots, img, w] = await Promise.all(['printer_conn', 'printer_lang', 'printer_dots', 'printer_img', 'printer_width'].map((k) => kv.get(k)));
  return { conn: conn || 'bt', lang: lang || 'escpos', dots: Number(dots) || (w === '80' ? 576 : 384), img: img || 'raster' };
}
export async function setConfig(part) {
  for (const [k, v] of Object.entries(part)) await kv.set('printer_' + k, String(v));
  if (part.dots) await kv.set('printer_width', Number(part.dots) >= 576 ? '80' : '58');   // older builds read this
}
export async function paperDots() { return (await getConfig()).dots; }
export async function setPaperWidth(mm) { await setConfig({ dots: String(mm) === '80' ? 576 : String(mm) === '104' ? 832 : 384 }); }

/** True when a slip can actually go to a printer (else the slip is shown on screen). */
export async function canPrint() {
  const c = await getConfig();
  if (!connAvailable(c.conn)) return false;
  return c.conn === 'system' ? true : !!(await kv.get('printer'));
}

async function permissions() {
  if (Platform.OS !== 'android' || Platform.Version < 31) return true;
  const r = await PermissionsAndroid.requestMultiple([PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT, PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN]);
  return Object.values(r).every((v) => v === PermissionsAndroid.RESULTS.GRANTED);
}

/** Printers to choose from: paired devices (Bluetooth) or a 6 s scan (Bluetooth LE). [{ id, name, address }] */
export async function listPrinters(conn) {
  if (conn === 'ble') return (await bleScan(6000)).map((d) => ({ id: d.id, address: d.id, name: d.name }));
  return listPaired();
}
export async function listPaired() {
  if (!RNBC) return [];
  if (!(await permissions())) throw new Error('Bluetooth permission refused');
  if (!(await RNBC.isBluetoothEnabled())) await RNBC.requestBluetoothEnabled();
  const list = await RNBC.getBondedDevices();
  return list.map((d) => ({ id: d.address, name: d.name, address: d.address })).filter((d) => d.name);
}

export async function connect(address, conn) {
  conn = conn || (await getConfig()).conn;
  if (conn === 'ble') await bleOpen(address);
  else { if (!RNBC) throw new Error('Bluetooth module not available in this build'); await permissions(); await open(address); }
  await kv.set('printer', address);
}

let current = null;
async function open(address) {
  if (current && current.address === address && (await current.isConnected().catch(() => false))) return current;
  try { if (current) await current.disconnect(); } catch (e) { }
  current = null;
  if (await RNBC.isDeviceConnected(address).catch(() => false)) current = await RNBC.getConnectedDevice(address);
  else current = await RNBC.connectToDevice(address, { CONNECTOR_TYPE: 'rfcomm', DELIMITER: '\n', DEVICE_CHARSET: 'ascii', SECURE_SOCKET: false });
  return current;
}

function render(doc, c) {
  return c.lang === 'cpcl' ? toCpcl(doc) : c.lang === 'zpl' ? toZpl(doc) : c.lang === 'tspl' ? toTspl(doc) : toEscPos(doc, c.img);
}
async function sendBytes(bytes, c) {
  const addr = await kv.get('printer');
  if (!addr) throw new Error('No printer selected (Settings > Printer)');
  try {
    if (c.conn === 'ble') return await bleWrite(addr, bytes);
    const dev = await open(addr);
    for (let i = 0; i < bytes.length; i += CHUNK) {
      const ok = await dev.write(bytesToBase64(bytes.subarray(i, Math.min(bytes.length, i + CHUNK))), 'base64');
      if (ok === false) throw new Error('Printer refused data');
      await sleep(CHUNK_DELAY_MS);
    }
  } catch (e) { throw new Error('Printer not reachable - switch it on and keep it near the HHT (' + (e.message || e) + ')'); }
}
/** Print one or more documents (copies) the way Settings > Printer says. */
async function send(docs) {
  docs = Array.isArray(docs) ? docs : [docs];
  const c = await getConfig();
  if (c.conn === 'system') { if (!ExpoPrint) throw new Error('Android print not available in this build'); await ExpoPrint.printAsync({ html: toHtml(docs, PRINT_LOGO_B64) }); return; }
  for (const d of docs) await sendBytes(render(d, c), c);
}
const newDoc = async () => new Doc((await getConfig()).dots);

/** Settings > Printer > "Find my printer language": prints a short sample in each language, one after the other. */
export async function findLanguage() {
  const c = await getConfig(); if (c.conn === 'system') throw new Error('Not needed for Android print');
  for (const [l] of LANGS) { await sendBytes(languageSample(l, c.dots), c); await sleep(800); }
}

// ------------------------------------------------------------------ documents
function pad(l, r, w = 32) { const s = l + ' '.repeat(Math.max(1, w - l.length - r.length)) + r; return s.slice(0, w); }

// Return slip text (32 cols for 2", 48 for 3") - also the on-screen fallback
export function slipText(slip, plant, cols = 32) {
  const L = [];
  L.push('ASAHI INDIA GLASS LTD.');
  L.push('PALLET RETURN SLIP');
  L.push(plant?.name || plant?.code || '');
  L.push('-'.repeat(cols));
  L.push(`Slip No : ${slip.slip_no}`);
  L.push(`Date    : ${slip.date || ''}`);
  L.push(`Mode    : ${MODE_TXT[slip.mode] || slip.mode}`);
  L.push(`Customer: ${slip.customer_code}`);
  wrap(slip.customer_name || '', cols - 10).slice(0, 3).forEach((t) => L.push('          ' + t));
  L.push(`Vehicle : ${slip.vehicle_no || ''}`);
  if (slip.customer_challan_no) L.push(`Cust DC : ${slip.customer_challan_no}`);
  if (slip.driver_name) L.push(`Driver  : ${slip.driver_name} ${slip.driver_mobile || ''}`);
  L.push('-'.repeat(cols));
  if (slip.pallets && slip.pallets.length) { slip.pallets.forEach((p, i) => L.push(pad(`${i + 1}.`, p, cols))); L.push('-'.repeat(cols)); }
  L.push(`NO. OF PALLETS: ${slip.declared_qty}`);
  if (qtyOnly(slip)) L.push('Scanned & knocked off at pallet yard');
  if (slip.provisional) L.push('** PROVISIONAL - created offline **');
  L.push(''); L.push('Security sign: ________    Driver: ________'); L.push('');
  return L.join('\n');
}
// Same layout as the server label; HHT cannot sign offline, so the check code is '-' (server trusts its own HHT slips)
const yymmddhhmm = (d = new Date()) => d.toISOString().replace(/[-T:]/g, '').slice(2, 12);
export const slipQr = (slip, plant) => `AIS1|RS|${slip.slip_no}|${plant?.code || ''}|${slip.customer_code}|${slip.vehicle_no || ''}|${slip.declared_qty}|${yymmddhhmm()}|-`;

const MODE_TXT = { A: 'A - by customer', B1: 'B - AIS IN gate', B2: 'B - AIS IN gate' };
const qtyOnly = (slip) => slip.mode !== 'A' && !(slip.pallets || []).length;
function wrap(text, w) {            // word wrap for the printer's fixed columns
  const out = []; let cur = '';
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    if (!cur) cur = word.slice(0, w); else if ((cur + ' ' + word).length <= w) cur += ' ' + word; else { out.push(cur); cur = word.slice(0, w); }
  }
  if (cur) out.push(cur); return out;
}
export function slipDoc(slip, plant, dots, qr) {
  const p = new Doc(dots);
  p.align('center').logo().line().bold(true).size(1, 2).line('PALLET RETURN SLIP').size(1, 1).bold(false)
    .line(plant?.name || plant?.code || '').line()
    .qr(qr || slipQr(slip, plant), { scale: dots >= 576 ? 7 : 6 }).line().bold(true).line(slip.slip_no).bold(false).line()
    .align('left').rule()
    .line(`Date    : ${slip.date || ''}`.slice(0, p.cols))
    .line(`Mode    : ${MODE_TXT[slip.mode] || slip.mode}`.slice(0, p.cols))
    .line(`Customer: ${slip.customer_code}`);
  wrap(slip.customer_name || '', p.cols - 10).slice(0, 3).forEach((t) => p.line('          ' + t));
  p.line(`Vehicle : ${slip.vehicle_no || ''}`);
  if (slip.customer_challan_no) p.line(`Cust DC : ${slip.customer_challan_no}`);
  if (slip.driver_name) p.line(`Driver  : ${slip.driver_name} ${slip.driver_mobile || ''}`.slice(0, p.cols));
  p.rule();
  if (qtyOnly(slip)) {                // Option B: count only - scanned and knocked off at pallet-yard receiving
    p.align('center').bold(true).line('NO. OF PALLETS').size(2, 2).line(String(slip.declared_qty ?? '')).size(1, 1).bold(false)
      .line('Count at IN gate.').line('Scanned & knocked off at').line('pallet yard receiving.').align('left').rule();
  } else {
    (slip.pallets || []).forEach((x, i) => p.pad(`${i + 1}.`, x));
    p.rule().bold(true).line(`TOTAL PALLETS: ${slip.declared_qty}`).bold(false);
  }
  if (slip.provisional) p.align('center').bold(true).line('PRINTED WITHOUT NETWORK').bold(false).line(slip.mode === 'A' ? 'QR signed by this HHT' : 'Sent to AIS when online').align('left');
  p.line().line('Security: ____________').line().line('Driver  : ____________').feed(4).cut();
  return p;
}

/** qr: the server's signed QR (Option A slips from the customer HHT); without it the HHT slip QR is used. */
export async function printSlip(slip, plant, copies = 2, qr = null) {
  if (!(await canPrint())) return { printed: false, text: slipText(slip, plant), qr: qr || slipQr(slip, plant) };
  const dots = await paperDots();
  await send(Array.from({ length: copies }, () => slipDoc(slip, plant, dots, qr)));
  return { printed: true };
}

export async function printChallan(k, plant, lines, copies = 2) {
  const text = [`ASAHI INDIA GLASS LTD.`, `PALLET CHALLAN (RETURNABLE)`, plant?.name || '', '-'.repeat(32), `Challan : ${k.challan_no}`, `PickList: ${k.picklist_no}`, `SO      : ${k.so_number || ''}`,
    `Customer: ${k.customer_code}`, `Vehicle : ${k.vehicle_no || ''}`, '-'.repeat(32), ...lines.map((p, i) => pad(`${i + 1}.`, p)), '-'.repeat(32), `TOTAL PALLETS: ${lines.length}`, '', 'Returnable - property of AIS Glass', ''].join('\n');
  const qr = `CHL|${k.challan_no}|${k.picklist_no}|${lines.length}`;
  if (!(await canPrint())) return { printed: false, text, qr };
  const dots = await paperDots();
  const one = () => {
    const p = new Doc(dots);
    p.align('center').logo().line().bold(true).line('PALLET CHALLAN (RETURNABLE)').bold(false).line(plant?.name || '').line().qr(qr).line().align('left').rule()
      .line(`Challan : ${k.challan_no}`).line(`PickList: ${k.picklist_no}`).line(`SO      : ${k.so_number || ''}`).line(`Customer: ${k.customer_code}`).line(`Vehicle : ${k.vehicle_no || ''}`).rule();
    lines.forEach((x, i) => p.pad(`${i + 1}.`, x));
    return p.rule().bold(true).line(`TOTAL PALLETS: ${lines.length}`).bold(false).line().line('Returnable - property of AIS Glass').feed(4).cut();
  };
  await send(Array.from({ length: copies }, one));
  return { printed: true };
}

/** GCS (gate pass) slip with the signed QR the OUT gate scans - handed to the driver with the challan. */
export async function printGcs(k, plant, qr, copies = 1) {
  if (!(await canPrint())) return { printed: false };
  const dots = await paperDots();
  const one = () => new Doc(dots).align('center').logo().line().bold(true).size(1, 2).line('GATE PASS (GCS)').size(1, 1).bold(false).line(plant?.name || plant?.code || '').line()
    .qr(qr, { scale: dots >= 576 ? 7 : 6 }).line().bold(true).size(2, 2).line(String(k.gcs_no || '')).size(1, 1).bold(false).line().align('left').rule()
    .line(`Vehicle : ${k.vehicle_no || ''}`).line(`Customer: ${k.customer_code || ''}`).line(`Invoice : ${k.invoice_no || ''}`).line(`Challan : ${k.challan_no || ''}`).line(`Pallets : ${k.scanned ?? k.qty ?? ''}`).rule()
    .line('Show this QR at the OUT gate.').line().line('Loaded by: ____________').line().line('Driver   : ____________').feed(4).cut();
  await send(Array.from({ length: copies }, one));
  return { printed: true };
}

/** Settings > Printer > Test print: text + logo + QR in the chosen language / connection. */
export async function testPrint(plant) {
  const c = await getConfig();
  if (!connAvailable(c.conn)) throw new Error('This connection is not available in this build');
  const p = new Doc(c.dots);
  const lang = LANGS.find((x) => x[0] === c.lang)?.[1] || c.lang;
  p.align('center').logo().line().bold(true).size(2, 2).line('AssetTrack').size(1, 1).bold(false).line('Printer test OK').line(`${plant?.code || ''} ${fDT(new Date())}`).line()
    .qr('AIS1|TEST|' + Date.now(), { scale: 5 }).line().align('left').rule()
    .pad('Paper', `${Math.round(c.dots / 8)} mm / ${p.cols} cols`).pad('Language', c.conn === 'system' ? 'Android print' : lang)
    .line('0123456789'.repeat(10).slice(0, p.cols)).rule().line('Text, logo and QR printed clearly').line('= printer is set up.').feed(4).cut();
  await send(p);
}
