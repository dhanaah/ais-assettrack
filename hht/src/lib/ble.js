// Bluetooth LE printers (many new portable printers - and some that are BLE only, e.g. cheap "cat" style, newer
// Xprinter / Rongta / Zebra ZQ models). Scan, connect, find the printer's write characteristic and send in MTU-sized
// pieces. Known printer services are tried first, then any characteristic that accepts writes. Developed by DT
import { PermissionsAndroid, Platform } from 'react-native';
import { bytesToBase64 } from './escpos';

let Ble = null;
try { Ble = require('react-native-ble-plx'); } catch (e) { Ble = null; }
let mgr = null;
const manager = () => { if (!Ble) throw new Error('Bluetooth LE module not available in this build'); if (!mgr) mgr = new Ble.BleManager(); return mgr; };
export const bleAvailable = () => !!Ble;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// service -> write characteristic, most common printer chips first
const KNOWN = [
  ['000018f0-0000-1000-8000-00805f9b34fb', '00002af1-0000-1000-8000-00805f9b34fb'],   // generic ESC/POS (Xprinter, SEZNIK, MTP...)
  ['e7810a71-73ae-499d-8c15-faa9aef0c3f2', 'bef8d6c9-9c21-4c9e-b632-bd58c1009f9f'],   // ISSC / Rongta / Goojprt
  ['49535343-fe7d-4ae5-8fa9-9fafd205e455', '49535343-8841-43f4-a8d4-ecbe34729bb3'],   // Microchip transparent UART
  ['38eb4a80-c570-11e3-9507-0002a5d5c51b', '38eb4a82-c570-11e3-9507-0002a5d5c51b'],   // Zebra "Parser" service
  ['0000ff00-0000-1000-8000-00805f9b34fb', '0000ff02-0000-1000-8000-00805f9b34fb'],
  ['0000ffe0-0000-1000-8000-00805f9b34fb', '0000ffe1-0000-1000-8000-00805f9b34fb'],
  ['0000fee7-0000-1000-8000-00805f9b34fb', '0000fec7-0000-1000-8000-00805f9b34fb'],
];

async function permissions() {
  if (Platform.OS !== 'android') return true;
  const P = PermissionsAndroid.PERMISSIONS;
  const want = Platform.Version >= 31 ? [P.BLUETOOTH_SCAN, P.BLUETOOTH_CONNECT] : [P.ACCESS_FINE_LOCATION];
  const r = await PermissionsAndroid.requestMultiple(want);
  return Object.values(r).every((v) => v === PermissionsAndroid.RESULTS.GRANTED);
}

/** Scan for `ms` and return named devices [{ id, name, rssi }] (printers usually show their model name). */
export async function bleScan(ms = 6000) {
  const m = manager();
  if (!(await permissions())) throw new Error('Bluetooth permission refused');
  const found = new Map();
  await new Promise((resolve) => {
    m.startDeviceScan(null, { allowDuplicates: false }, (err, d) => {
      if (err) { resolve(); return; }
      const name = d?.name || d?.localName; if (d && name) found.set(d.id, { id: d.id, name, rssi: d.rssi });
    });
    setTimeout(resolve, ms);
  });
  m.stopDeviceScan();
  return [...found.values()].sort((a, b) => (b.rssi || -999) - (a.rssi || -999));
}

let cur = null;              // { id, dev, svc, chr, noResp, mtu }
async function pickWriter(dev) {
  await dev.discoverAllServicesAndCharacteristics();
  const services = await dev.services(); const all = [];
  for (const s of services) for (const c of await s.characteristics()) all.push({ s: s.uuid.toLowerCase(), c });
  for (const [s, c] of KNOWN) { const hit = all.find((x) => x.s === s && x.c.uuid.toLowerCase() === c && (x.c.isWritableWithoutResponse || x.c.isWritableWithResponse)); if (hit) return hit; }
  const any = all.find((x) => x.c.isWritableWithoutResponse) || all.find((x) => x.c.isWritableWithResponse && !x.s.startsWith('00001801') && !x.s.startsWith('00001800'));
  if (!any) throw new Error('This device has no printer (write) channel');
  return any;
}

export async function bleOpen(id) {
  if (cur && cur.id === id && (await cur.dev.isConnected().catch(() => false))) return cur;
  try { if (cur) await cur.dev.cancelConnection(); } catch (e) { }
  cur = null;
  await permissions();
  const m = manager();
  let dev = await m.connectToDevice(id, { timeout: 10000 });
  try { dev = await dev.requestMTU(247); } catch (e) { }
  const w = await pickWriter(dev);
  cur = { id, dev, svc: w.s, chr: w.c.uuid, noResp: !!w.c.isWritableWithoutResponse, mtu: Math.max(20, (dev.mtu || 23) - 3) };
  return cur;
}

/** Send bytes: MTU-sized pieces; "write without response" is paced so small printer buffers keep up. */
export async function bleWrite(id, bytes) {
  const c = await bleOpen(id);
  const n = Math.min(c.mtu, 180);
  for (let i = 0; i < bytes.length; i += n) {
    const b64 = bytesToBase64(bytes.subarray(i, Math.min(bytes.length, i + n)));
    if (c.noResp) { await c.dev.writeCharacteristicWithoutResponseForService(c.svc, c.chr, b64); await sleep(12); }
    else await c.dev.writeCharacteristicWithResponseForService(c.svc, c.chr, b64);
  }
}
