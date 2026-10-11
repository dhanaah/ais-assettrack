// Customer device (Option A return slips at the customer's site). Paired once by a QR from the AIS web (Customers >
// HHT pairing): customer, plant, a device key and two kinds of address -
//   * AIS network: the AssetTrack server name / IPs (used when the HHT is on AIS Wi-Fi / VPN - direct, fastest)
//   * internet:    the customer API address IT publishes (used everywhere else)
// Every call picks the route that answers: all AIS-network addresses are tried at once (short wait), then the internet
// address. The route is remembered for a few minutes. Slips carry a client reference, so a resend never makes a
// second slip; slips made without any network wait in an outbox and are sent automatically. Developed by DT
import * as SecureStore from 'expo-secure-store';
import { kv } from './db';
import { APP_VERSION } from './api';

let pair = null;                 // { v, p, c, n, d, lan: [], ports: [], wan, k }
let route = null;                // { base, kind: 'LAN' | 'WAN', at }
let deviceId = 'HHT';
const ROUTE_TTL = 3 * 60000;
export const setCustDevice = (id) => { deviceId = id; };

// ---------------------------------------------------------------- pairing
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function b64decode(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/').replace(/[^A-Za-z0-9+/]/g, '');
  const bytes = []; let buf = 0, bits = 0;
  for (const ch of s) { buf = (buf << 6) | B64.indexOf(ch); bits += 6; if (bits >= 8) { bits -= 8; bytes.push((buf >> bits) & 0xff); } }
  let out = '', i = 0;                                   // UTF-8 -> string
  while (i < bytes.length) {
    const b = bytes[i++];
    if (b < 0x80) out += String.fromCharCode(b);
    else if (b < 0xe0) out += String.fromCharCode(((b & 0x1f) << 6) | (bytes[i++] & 0x3f));
    else if (b < 0xf0) out += String.fromCharCode(((b & 0x0f) << 12) | ((bytes[i++] & 0x3f) << 6) | (bytes[i++] & 0x3f));
    else { i += 3; out += '?'; }
  }
  return out;
}
export function parsePairing(text) {
  const s = String(text || '').trim();
  if (!s.startsWith('AISCUST1|')) return null;
  try { const j = JSON.parse(b64decode(s.slice(9))); return j && j.k && j.c && j.p ? j : null; } catch (e) { return null; }
}
export async function savePairing(j) {
  const { k, ...meta } = j;
  await SecureStore.setItemAsync('cust_key', k);
  await kv.set('cust_pair', meta);
  pair = j; route = null;
}
export async function loadPairing() {
  const meta = await kv.get('cust_pair'); if (!meta) { pair = null; return null; }
  const k = await SecureStore.getItemAsync('cust_key'); if (!k) { pair = null; return null; }
  pair = { ...meta, k }; return pair;
}
export async function unpair() { await SecureStore.deleteItemAsync('cust_key'); await kv.set('cust_pair', null); pair = null; route = null; }
export const getPairing = () => pair;
export const getRoute = () => route;
export async function setInternetAddress(url) {        // if IT publishes the address after pairing
  if (!pair) return; pair = { ...pair, wan: (url || '').trim().replace(/\/+$/, '') };
  const { k, ...meta } = pair; await kv.set('cust_pair', meta); route = null;
}

// ---------------------------------------------------------------- route: AIS network first, internet second
function lanBases() {
  const out = []; const ports = pair?.ports?.length ? pair.ports : [80, 8001, 8002, 8003];
  (pair?.lan || []).forEach((h) => ports.forEach((p) => { const u = `http://${h}${p === 80 ? '' : ':' + p}`; if (!out.includes(u)) out.push(u); }));
  return out;
}
async function ping(base, timeout) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeout);
  try { const r = await fetch(base + '/api/ext/v1/ping', { signal: ctl.signal }); const j = await r.json(); return !!(r.ok && j.ok); }
  catch (e) { return false; } finally { clearTimeout(t); }
}
function firstTrue(promises, items) {          // resolves with the first item whose promise is true (or null)
  return new Promise((res) => {
    let left = promises.length; if (!left) return res(null);
    promises.forEach((p, i) => p.then((ok) => { if (ok) res(items[i]); else if (--left === 0) res(null); }));
  });
}
export async function findRoute(force) {
  if (!pair) throw new Error('Not paired');
  if (!force && route && Date.now() - route.at < ROUTE_TTL) return route;
  const lan = lanBases();
  const hit = await firstTrue(lan.map((b) => ping(b, 2500)), lan);
  if (hit) { route = { base: hit, kind: 'LAN', at: Date.now() }; return route; }
  if (pair.wan && await ping(pair.wan, 8000)) { route = { base: pair.wan, kind: 'WAN', at: Date.now() }; return route; }
  route = null;
  const e = new Error(pair.wan ? 'No network to AIS (AIS Wi-Fi or internet)' : 'AIS server not reachable and no internet address set'); e.offline = true; throw e;
}

export async function ext(path, { method = 'GET', body, timeout = 15000 } = {}, retried) {
  const r0 = await findRoute();
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(r0.base + '/api/ext/v1' + path, {
      method, signal: ctl.signal, body: body ? JSON.stringify(body) : undefined,
      headers: { 'Content-Type': 'application/json', 'X-API-Key': pair.k, 'X-Route': r0.kind, 'X-App-Version': APP_VERSION, 'X-Device-Id': deviceId },
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(typeof j.detail === 'string' ? j.detail : (r.statusText || 'Server error')); e.status = r.status; throw e; }
    return j;
  } catch (e) {
    if (e.status) throw e;
    route = null;                                          // that route went away: find another once
    if (!retried) return ext(path, { method, body, timeout }, true);
    const x = new Error('No network to AIS - saved, will be sent automatically'); x.offline = true; throw x;
  } finally { clearTimeout(t); }
}

// ---------------------------------------------------------------- slips: outbox + history on this device
const uid = () => (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16); }));
export async function outbox() { return (await kv.get('cust_outbox')) || []; }
export async function history() { return (await kv.get('cust_slips')) || []; }
async function remember(slip) {
  const h = await history(); const i = h.findIndex((x) => x.slip_no === slip.slip_no);
  if (i >= 0) h[i] = { ...h[i], ...slip }; else h.unshift(slip);
  await kv.set('cust_slips', h.slice(0, 200));
}
/** Create an Option A return slip. Returns { sent: true, slip } or { sent: false, queued } when there is no network. */
export async function createSlip(body) {
  const item = { client_ref: uid(), body, created: new Date().toISOString(), tries: 0 };
  try {
    const slip = await ext('/return-slip', { method: 'POST', body: { ...body, client_ref: item.client_ref } });
    await remember({ ...slip, made_on_device: item.created });
    return { sent: true, slip };
  } catch (e) {
    if (!e.offline) throw e;
    const ob = await outbox(); ob.push({ ...item, last_error: e.message }); await kv.set('cust_outbox', ob);
    return { sent: false, queued: item, reason: e.message };
  }
}
/** Send waiting slips (same client reference: never doubled). Returns the slips sent now. */
export async function sendPending() {
  const ob = await outbox(); if (!ob.length) return [];
  const left = [], sent = [];
  for (const it of ob) {
    try { const slip = await ext('/return-slip', { method: 'POST', body: { ...it.body, client_ref: it.client_ref } }); await remember({ ...slip, made_on_device: it.created }); sent.push(slip); }
    catch (e) { left.push({ ...it, tries: (it.tries || 0) + 1, last_error: e.message }); if (e.offline) { left.push(...ob.slice(ob.indexOf(it) + 1)); break; } }
  }
  await kv.set('cust_outbox', left);
  return sent;
}
export async function refreshSlip(no) { const s = await ext('/return-slip/' + encodeURIComponent(no)); await remember(s); return s; }
