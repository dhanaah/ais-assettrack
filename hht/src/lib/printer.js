// Bluetooth printing (ESC/POS over Bluetooth Classic / SPP) for 2" and 3" portable thermal printers - set up for the
// SEZNIK DEV 2" (58 mm, 203 dpi, 384 dots). Pair the printer in Android Bluetooth settings first, then pick it in
// Settings > Printer. Data is built with ./escpos.js and sent in small chunks (cheap printers drop flooded data).
// Without the Bluetooth module (Expo Go) the slip text is shown on screen instead. Developed by DT
import { PermissionsAndroid, Platform } from 'react-native';
import { kv } from './db';
import { EscPos } from './escpos';

let RNBC = null;
try { RNBC = require('react-native-bluetooth-classic').default; } catch (e) { RNBC = null; }

export const printerAvailable = () => !!RNBC;
const CHUNK = 512, CHUNK_DELAY_MS = 40;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function paperDots() { return (await kv.get('printer_width')) === '80' ? 576 : 384; }
export async function setPaperWidth(mm) { await kv.set('printer_width', String(mm)); }

async function permissions() {
  if (Platform.OS !== 'android' || Platform.Version < 31) return true;
  const r = await PermissionsAndroid.requestMultiple([PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT, PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN]);
  return Object.values(r).every((v) => v === PermissionsAndroid.RESULTS.GRANTED);
}

export async function listPaired() {
  if (!RNBC) return [];
  if (!(await permissions())) throw new Error('Bluetooth permission refused');
  if (!(await RNBC.isBluetoothEnabled())) await RNBC.requestBluetoothEnabled();
  const list = await RNBC.getBondedDevices();
  return list.map((d) => ({ name: d.name, address: d.address })).filter((d) => d.name);
}

export async function connect(address) {
  if (!RNBC) throw new Error('Printer module not available in this build');
  await permissions();
  await open(address);
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

export async function ensureConnected() {
  const addr = await kv.get('printer');
  if (!addr) throw new Error('No printer selected (Settings > Printer)');
  try { return await open(addr); }
  catch (e) { throw new Error('Printer not reachable - switch it on and keep it near the HHT (' + (e.message || e) + ')'); }
}

async function send(escpos) {
  const dev = await ensureConnected();
  const bytes = escpos.bytes();
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const part = bytes.subarray(i, Math.min(bytes.length, i + CHUNK));
    const ok = await dev.write(bytesToB64(part), 'base64');
    if (ok === false) throw new Error('Printer refused data');
    await sleep(CHUNK_DELAY_MS);
  }
}
function bytesToB64(u8) { const { bytesToBase64 } = require('./escpos'); return bytesToBase64(u8); }

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
  L.push(`Mode    : ${slip.mode}  Date: ${slip.date}`);
  L.push(`Customer: ${slip.customer_code} ${slip.customer_name || ''}`.slice(0, cols));
  L.push(`Vehicle : ${slip.vehicle_no || ''}`);
  if (slip.customer_challan_no) L.push(`Cust DC : ${slip.customer_challan_no}`);
  if (slip.driver_name) L.push(`Driver  : ${slip.driver_name} ${slip.driver_mobile || ''}`);
  L.push('-'.repeat(cols));
  if (slip.pallets && slip.pallets.length) { slip.pallets.forEach((p, i) => L.push(pad(`${i + 1}.`, p, cols))); }
  L.push('-'.repeat(cols));
  L.push(`TOTAL PALLETS: ${slip.declared_qty}${slip.mode === 'B2' ? '  (QTY ONLY - PENDING VERIFICATION)' : ''}`);
  if (slip.provisional) L.push('** PROVISIONAL - created offline **');
  L.push(''); L.push('Security sign: ________    Driver: ________'); L.push('');
  return L.join('\n');
}
// Same layout as the server label; HHT cannot sign offline, so the check code is '-' (server trusts its own HHT slips)
const yymmddhhmm = (d = new Date()) => d.toISOString().replace(/[-T:]/g, '').slice(2, 12);
export const slipQr = (slip, plant) => `AIS1|RS|${slip.slip_no}|${plant?.code || ''}|${slip.customer_code}|${slip.vehicle_no || ''}|${slip.declared_qty}|${yymmddhhmm()}|-`;

function slipDoc(slip, plant, dots) {
  const p = new EscPos(dots);
  p.init().align('center').logo().line().bold(true).size(1, 2).line('PALLET RETURN SLIP').size(1, 1).bold(false)
    .line(plant?.name || plant?.code || '').line()
    .qr(slipQr(slip, plant), { scale: dots >= 576 ? 7 : 6 }).line().bold(true).line(slip.slip_no).bold(false).line()
    .align('left').rule()
    .line(`Mode    : ${slip.mode}   ${slip.date || ''}`.slice(0, p.cols))
    .line(`Customer: ${slip.customer_code}`).line(`          ${(slip.customer_name || '').slice(0, p.cols - 10)}`)
    .line(`Vehicle : ${slip.vehicle_no || ''}`);
  if (slip.customer_challan_no) p.line(`Cust DC : ${slip.customer_challan_no}`);
  if (slip.driver_name) p.line(`Driver  : ${slip.driver_name} ${slip.driver_mobile || ''}`.slice(0, p.cols));
  p.rule();
  (slip.pallets || []).forEach((x, i) => p.pad(`${i + 1}.`, x));
  p.rule().bold(true).line(`TOTAL PALLETS: ${slip.declared_qty}`).bold(false);
  if (slip.mode === 'B2') p.line('(QTY ONLY - PENDING VERIFICATION)');
  if (slip.provisional) p.line('** PROVISIONAL - created offline **');
  p.line().line('Security: ____________').line().line('Driver  : ____________').line().align('center').line('Developed by DT').feed(4).cut();
  return p;
}

export async function printSlip(slip, plant, copies = 2) {
  if (!RNBC) return { printed: false, text: slipText(slip, plant), qr: slipQr(slip, plant) };
  const dots = await paperDots();
  for (let c = 0; c < copies; c++) await send(slipDoc(slip, plant, dots));
  return { printed: true };
}

export async function printChallan(k, plant, lines, copies = 2) {
  const text = [`ASAHI INDIA GLASS LTD.`, `PALLET CHALLAN (RETURNABLE)`, plant?.name || '', '-'.repeat(32), `Challan : ${k.challan_no}`, `PickList: ${k.picklist_no}`, `SO      : ${k.so_number || ''}`,
    `Customer: ${k.customer_code}`, `Vehicle : ${k.vehicle_no || ''}`, '-'.repeat(32), ...lines.map((p, i) => pad(`${i + 1}.`, p)), '-'.repeat(32), `TOTAL PALLETS: ${lines.length}`, '', 'Returnable - property of AIS Glass', ''].join('\n');
  const qr = `CHL|${k.challan_no}|${k.picklist_no}|${lines.length}`;
  if (!RNBC) return { printed: false, text, qr };
  const dots = await paperDots();
  for (let c = 0; c < copies; c++) {
    const p = new EscPos(dots);
    p.init().align('center').logo().line().bold(true).line('PALLET CHALLAN (RETURNABLE)').bold(false).line(plant?.name || '').line().qr(qr).line().align('left').rule()
      .line(`Challan : ${k.challan_no}`).line(`PickList: ${k.picklist_no}`).line(`SO      : ${k.so_number || ''}`).line(`Customer: ${k.customer_code}`).line(`Vehicle : ${k.vehicle_no || ''}`).rule();
    lines.forEach((x, i) => p.pad(`${i + 1}.`, x));
    p.rule().bold(true).line(`TOTAL PALLETS: ${lines.length}`).bold(false).line().line('Returnable - property of AIS Glass').feed(4).cut();
    await send(p);
  }
  return { printed: true };
}

/** GCS (gate pass) slip with the signed QR the OUT gate scans - handed to the driver with the challan. */
export async function printGcs(k, plant, qr, copies = 1) {
  if (!RNBC) return { printed: false };
  const dots = await paperDots();
  for (let c = 0; c < copies; c++) {
    const p = new EscPos(dots);
    p.init().align('center').logo().line().bold(true).size(1, 2).line('GATE PASS (GCS)').size(1, 1).bold(false).line(plant?.name || plant?.code || '').line()
      .qr(qr, { scale: dots >= 576 ? 7 : 6 }).line().bold(true).size(2, 2).line(String(k.gcs_no || '')).size(1, 1).bold(false).line().align('left').rule()
      .line(`Vehicle : ${k.vehicle_no || ''}`).line(`Customer: ${k.customer_code || ''}`).line(`Invoice : ${k.invoice_no || ''}`).line(`Challan : ${k.challan_no || ''}`).line(`Pallets : ${k.scanned ?? k.qty ?? ''}`).rule()
      .line('Show this QR at the OUT gate.').line().line('Loaded by: ____________').line().line('Driver   : ____________').line().align('center').line('Developed by DT').feed(4).cut();
    await send(p);
  }
  return { printed: true };
}

/** Settings > Printer > Test print: proves the printer speaks ESC/POS (text + logo + QR). */
export async function testPrint(plant) {
  if (!RNBC) throw new Error('Printer module not available in this build');
  const dots = await paperDots();
  const p = new EscPos(dots);
  p.init().align('center').logo().line().bold(true).size(2, 2).line('AssetTrack').size(1, 1).bold(false).line('Printer test OK').line(`${plant?.code || ''} ${new Date().toLocaleString()}`).line()
    .qr('AIS1|TEST|' + Date.now(), { scale: 5 }).line().align('left').rule().pad('Paper', dots >= 576 ? '80 mm / 48 cols' : '58 mm / 32 cols').pad('Columns', '0123456789'.repeat(5).slice(0, p.cols - 8)).rule().line('If you can read this and see the').line('QR, the printer is set up.').feed(4).cut();
  await send(p);
}
