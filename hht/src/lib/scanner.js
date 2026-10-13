// Hardware scanner without keyboard: the device scanner sends each barcode as an Android broadcast (no text field,
// no keystrokes). Zebra DataWedge gets its own AssetTrack profile automatically (keystroke output OFF). Urovo,
// Newland, iData and Chainway default broadcasts are understood too; another brand can be set in Setup › Scanner.
// The screen that is open receives the scan (last opened scan area first). Developed by DT
import { AppState } from 'react-native';
import { requireOptionalNativeModule, EventEmitter } from 'expo-modules-core';
import { kv } from './db';

const Native = requireOptionalNativeModule('AisScanner');
export const ZEBRA_ACTION = 'com.aisglass.assettrack.SCAN';
export const PRESETS = [
  { id: 'zebra', name: 'Zebra (DataWedge - set up automatically)', action: ZEBRA_ACTION, key: 'com.symbol.datawedge.data_string' },
  { id: 'urovo', name: 'Urovo', action: 'android.intent.ACTION_DECODE_DATA', key: 'barcode_string' },
  { id: 'newland', name: 'Newland', action: 'nlscan.action.SCANNER_RESULT', key: 'SCAN_BARCODE1' },
  { id: 'idata', name: 'iData', action: 'android.intent.action.SCANRESULT', key: 'value' },
  { id: 'chainway', name: 'Chainway', action: 'com.scanner.broadcast', key: 'data' },
];
export const scannerAvailable = () => !!Native;
export const deviceName = () => { try { return Native ? Native.manufacturer() : ''; } catch (e) { return ''; } };

const handlers = [];               // scan areas on screen; the last one opened gets the scan
let sub = null;
export const STATUS = { started: false, zebra: false, custom: null, last: null };

/** Start listening (app start, and again after Setup › Scanner changes). */
export async function startScanner() {
  if (!Native) return false;
  const custom = (await kv.get('scanner_custom')) || null;   // { action, key } for another brand
  const actions = PRESETS.map((p) => p.action); const keys = PRESETS.map((p) => p.key);
  if (custom?.action) { actions.push(custom.action); if (custom.key) keys.push(custom.key); }
  try {
    if (Native.start(actions, [...new Set(keys)]) === false) { STATUS.started = false; return false; }
    const dev = deviceName().toLowerCase();
    if (dev.includes('zebra') || dev.includes('symbol')) { Native.configureZebra('AIS AssetTrack', ZEBRA_ACTION); STATUS.zebra = true; }
    if (!sub) sub = new EventEmitter(Native).addListener('onScan', (e) => {
      // scans made while AssetTrack is in the background belong to the app in front (e.g. MSCA) - never act on them here
      if (AppState.currentState !== 'active') return;
      const code = String(e?.data || '').trim(); if (!code) return;
      STATUS.last = { code, at: new Date() };
      const h = handlers[handlers.length - 1]; if (h) h(code);
    });
    STATUS.started = true; STATUS.custom = custom;
    return true;
  } catch (e) { STATUS.started = false; return false; }
}
/** Zebra: (re)create the DataWedge profile now (Setup › Scanner button). */
export function setupZebra() { if (!Native) return false; try { Native.configureZebra('AIS AssetTrack', ZEBRA_ACTION); STATUS.zebra = true; return true; } catch (e) { return false; } }
export function onHardwareScan(fn) { handlers.push(fn); return () => { const i = handlers.lastIndexOf(fn); if (i >= 0) handlers.splice(i, 1); }; }
