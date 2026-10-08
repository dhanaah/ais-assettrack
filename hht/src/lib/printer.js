// Bluetooth ESC/POS printing (2"/3" thermal). Uses react-native-bluetooth-escpos-printer when built with
// expo prebuild / EAS. In Expo Go the module is absent and print falls back to showing the slip text. Developed by DT
import { kv } from './db';
import { PRINT_LOGO_B64, PRINT_LOGO_W } from './printLogo';
let BT = null;
try { BT = require('react-native-bluetooth-escpos-printer'); } catch (e) { BT = null; }

export const printerAvailable = () => !!BT;

export async function listPaired() {
  if (!BT) return [];
  const { BluetoothManager } = BT;
  const r = await BluetoothManager.enableBluetooth();
  return (r || []).map(x => JSON.parse(x)).filter(d => d.name);
}
export async function connect(address) {
  if (!BT) throw new Error('Printer module not available in this build');
  await BT.BluetoothManager.connect(address);
  await kv.set('printer', address);
}
export async function ensureConnected() {
  const addr = await kv.get('printer');
  if (!addr) throw new Error('No printer selected (Settings > Printer)');
  try { await BT.BluetoothManager.connect(addr); } catch (e) { /* already connected */ }
}

async function printLogo(P) {
  try { await P.printPic(PRINT_LOGO_B64, { width: PRINT_LOGO_W, left: 0 }); await P.printText('\n', {}); }
  catch (e) { await P.printText('AIS - ASAHI INDIA GLASS LTD.\n', { fonttype: 1 }); }
}
function pad(l, r, w = 32) { const s = l + ' '.repeat(Math.max(1, w - l.length - r.length)) + r; return s.slice(0, w); }

// Return slip text (32 cols for 2", 48 for 3")
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
export const slipQr = (slip, plant) => `RTS|${slip.slip_no}|${plant?.code || ''}|${slip.customer_code}|${slip.declared_qty}`;

export async function printSlip(slip, plant, copies = 2) {
  if (!BT) { return { printed: false, text: slipText(slip, plant), qr: slipQr(slip, plant) }; }
  await ensureConnected();
  const { BluetoothEscposPrinter: P } = BT;
  for (let c = 0; c < copies; c++) {
    await P.printerInit();
    await P.printerAlign(P.ALIGN.CENTER);
    await P.setBlob(0);
    await printLogo(P);
    await P.printText('PALLET RETURN SLIP\n\n', { widthtimes: 1, heigthtimes: 1, fonttype: 1 });
    await P.printQRCode(slipQr(slip, plant), 220, P.ERROR_CORRECTION.M);
    await P.printText('\n', {});
    await P.printerAlign(P.ALIGN.LEFT);
    await P.printText(slipText(slip, plant) + '\n\n\n', {});
  }
  return { printed: true };
}

export async function printChallan(k, plant, lines, copies = 2) {
  const text = [`ASAHI INDIA GLASS LTD.`, `PALLET CHALLAN (RETURNABLE)`, plant?.name || '', '-'.repeat(32), `Challan : ${k.challan_no}`, `PickList: ${k.picklist_no}`, `SO      : ${k.so_number || ''}`,
    `Customer: ${k.customer_code}`, `Vehicle : ${k.vehicle_no || ''}`, '-'.repeat(32), ...lines.map((p, i) => pad(`${i + 1}.`, p)), '-'.repeat(32), `TOTAL PALLETS: ${lines.length}`, '', 'Returnable - property of AIS Glass', ''].join('\n');
  if (!BT) return { printed: false, text, qr: `CHL|${k.challan_no}|${k.picklist_no}|${lines.length}` };
  await ensureConnected();
  const { BluetoothEscposPrinter: P } = BT;
  for (let c = 0; c < copies; c++) { await P.printerInit(); await P.printerAlign(P.ALIGN.CENTER); await printLogo(P); await P.printText('PALLET CHALLAN (RETURNABLE)\n', { fonttype: 1 }); await P.printQRCode(`CHL|${k.challan_no}|${k.picklist_no}|${lines.length}`, 220, P.ERROR_CORRECTION.M); await P.printerAlign(P.ALIGN.LEFT); await P.printText(text + '\n\n\n', {}); }
  return { printed: true };
}
