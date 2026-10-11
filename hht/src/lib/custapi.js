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
import { setNet } from '../ui/kit';
import { hmacSha256Hex, sha256Hex } from './hmac';
import { setServerVehicles, usedVehicle, cleanVeh } from './vehicles';
import { parsePalletQr } from './db';

let pair = null;                 // { v, p, c, n, d, lan: [], ports: [], wan, k }
let route = null;                // { base, kind: 'LAN' | 'WAN', at }
let deviceId = 'HHT';
let staff = null;                // { user_id, name, perms, tok } - Customer Staff signed in on this HHT
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
  const { k, s: sk, ...meta } = j;
  await SecureStore.setItemAsync('cust_key', k);
  if (sk) await SecureStore.setItemAsync('cust_sign', sk);
  await kv.set('cust_pair', meta);
  pair = j; route = null;
}
export async function loadPairing() {
  const meta = await kv.get('cust_pair'); if (!meta) { pair = null; return null; }
  const k = await SecureStore.getItemAsync('cust_key'); if (!k) { pair = null; return null; }
  const sk = await SecureStore.getItemAsync('cust_sign');
  pair = { ...meta, k, s: sk || null }; return pair;
}
/** /me: sign key + device id for slips printed without network (older pairings get it here), vehicles for quick pick. */
export async function refreshMe() {
  const me = await ext('/me');
  if (me.sign_key && pair && (pair.s !== me.sign_key || pair.i !== me.device_id)) {
    await SecureStore.setItemAsync('cust_sign', me.sign_key); pair = { ...pair, s: me.sign_key, i: me.device_id };
    const { k, s: _s, ...meta } = pair; await kv.set('cust_pair', meta);
  }
  if (me.vehicles) await setServerVehicles(me.vehicles);
  return me;
}
export const canPrintOffline = () => !!(pair && pair.s && pair.i);
export async function unpair() { await SecureStore.deleteItemAsync('cust_key'); await SecureStore.deleteItemAsync('cust_sign').catch(() => {}); await kv.set('cust_pair', null); pair = null; route = null; }
export const getPairing = () => pair;
export const getRoute = () => route;
export async function setInternetAddress(url) {        // if IT publishes the address after pairing
  if (!pair) return; pair = { ...pair, wan: (url || '').trim().replace(/\/+$/, '') };
  const { k, s: _s, ...meta } = pair; await kv.set('cust_pair', meta); route = null;
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
  if (hit) { route = { base: hit, kind: 'LAN', at: Date.now() }; setNet({ state: 'online' }); return route; }
  if (pair.wan && await ping(pair.wan, 8000)) { route = { base: pair.wan, kind: 'WAN', at: Date.now() }; setNet({ state: 'online' }); return route; }
  route = null; setNet({ state: 'offline' });
  const e = new Error(pair.wan ? 'No network to AIS (AIS Wi-Fi or internet)' : 'AIS server not reachable and no internet address set'); e.offline = true; throw e;
}

export async function ext(path, { method = 'GET', body, timeout = 15000 } = {}, retried) {
  const r0 = await findRoute();
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(r0.base + '/api/ext/v1' + path, {
      method, signal: ctl.signal, body: body ? JSON.stringify(body) : undefined,
      headers: { 'Content-Type': 'application/json', 'X-API-Key': pair.k, 'X-Route': r0.kind, 'X-App-Version': APP_VERSION, 'X-Device-Id': deviceId, ...(staff?.tok ? { 'X-Staff-Token': staff.tok } : {}) },
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
  body = { ...body, vehicle_no: cleanVeh(body.vehicle_no) }; usedVehicle(body.vehicle_no).catch(() => {});
  const item = { client_ref: uid(), body, created: new Date().toISOString(), tries: 0 };
  try {
    const slip = await ext('/return-slip', { method: 'POST', body: { ...body, client_ref: item.client_ref } });
    await remember({ ...slip, made_on_device: item.created });
    return { sent: true, slip };
  } catch (e) {
    if (!e.offline) throw e;
    let slip = null;
    if (canPrintOffline()) { slip = await offlineSlip(body, item.created); item.body = { ...body, slip_no: slip.slip_no }; await remember(slip); }
    const ob = await outbox(); ob.push({ ...item, last_error: e.message }); await kv.set('cust_outbox', ob);
    setNet({ state: 'offline', pending: ob.length });
    return { sent: false, queued: item, reason: e.message, slip };
  }
}

// ---------------------------------------------------------------- slip printed without network (signed by this HHT)
const pad = (n, w) => String(n).padStart(w, '0');
function stamp(d) { return `${pad(d.getFullYear() % 100, 2)}${pad(d.getMonth() + 1, 2)}${pad(d.getDate(), 2)}${pad(d.getHours(), 2)}${pad(d.getMinutes(), 2)}`; }
/** Short pallet reference (type + serial, e.g. F-02948) for the QR - the AIS gate finds the pallet from it. */
function shortRef(scanned) {
  const q = parsePalletQr(scanned); const pn = q?.pallet_no || String(scanned || '').trim().toUpperCase();
  const m = /^AIS-[A-Z0-9]+-([A-Z0-9]+)-(\d+)-\d+$/.exec(pn); return m ? `${m[1]}-${m[2]}` : null;
}
async function offlineSlip(body, created) {
  const seq = ((await kv.get('ro_seq')) || 0) + 1; await kv.set('ro_seq', seq);
  const slip_no = `RO-${pair.p}-${pair.i}-${pad(seq, 5)}`;
  const qty = body.pallets.length; const veh = cleanVeh(body.vehicle_no);
  let refs = body.pallets.map(shortRef).filter(Boolean); if (refs.join(',').length > 600) refs = [];   // very long list: count only in the QR
  const head = `AIS1|RO|${slip_no}|${pair.p}|${pair.c}|${veh}|${qty}|${stamp(new Date(created))}|${pair.i}|${refs.join(',')}`;
  const qr = `${head}|${hmacSha256Hex(pair.s, head).slice(0, 10).toUpperCase()}`;
  return { slip_no, status: 'PRINTED OFFLINE', plant: pair.p, customer: pair.c, vehicle_no: veh, customer_challan_no: body.customer_challan_no || '',
    declared_qty: qty, created_at: created, qr_payload: qr, offline: true, pallets: body.pallets.map((x) => ({ pallet_no: parsePalletQr(x)?.pallet_no || x })) };
}
/** Send waiting slips (same client reference: never doubled). Returns the slips sent now. */
export async function sendPending() {
  const ob = await outbox(); if (!ob.length) return [];
  const left = [], sent = [];
  for (const it of ob) {
    try { const slip = await ext('/return-slip', { method: 'POST', body: { ...it.body, client_ref: it.client_ref } }); await remember({ ...slip, offline: false, made_on_device: it.created }); sent.push(slip); }
    catch (e) { left.push({ ...it, tries: (it.tries || 0) + 1, last_error: e.message }); if (e.offline) { left.push(...ob.slice(ob.indexOf(it) + 1)); break; } }
  }
  await kv.set('cust_outbox', left);
  return sent;
}
export async function refreshSlip(no) { const s = await ext('/return-slip/' + encodeURIComponent(no)); await remember(s); return s; }

// ---------------------------------------------------------------- customer staff sign-in (role Customer Staff)
// Online: checked by AIS, gives a token valid 30 days. Offline: the same user can sign in again with the password
// checked against a hash kept on this HHT (only users who signed in here online before).
const keyOf = (u) => 'cust_tok_' + String(u).replace(/[^A-Za-z0-9._-]/g, '_');
export const getStaff = () => staff;
export const staffCan = (perm) => !!(staff && (staff.perms || []).includes(perm));
export async function loadStaff() { const s = await kv.get('cust_staff_now'); if (!s) return null; const tok = await SecureStore.getItemAsync(keyOf(s.user_id)); staff = tok ? { ...s, tok } : null; return staff; }
export async function staffLogin(user, pw) {
  user = String(user || '').trim().toLowerCase(); const h = sha256Hex(user + '|' + pw + '|' + (pair?.c || ''));
  try {
    const r = await ext('/staff-login', { method: 'POST', body: { user_id: user, password: pw } });
    await SecureStore.setItemAsync(keyOf(r.user_id), r.token);
    const known = (await kv.get('cust_staff_known')) || {}; known[r.user_id] = { name: r.name, perms: r.perms, h, until: Date.now() + r.days * 86400000 }; await kv.set('cust_staff_known', known);
    staff = { user_id: r.user_id, name: r.name, perms: r.perms, tok: r.token }; await kv.set('cust_staff_now', { user_id: r.user_id, name: r.name, perms: r.perms });
    return staff;
  } catch (e) {
    if (!e.offline) throw e;
    const k = ((await kv.get('cust_staff_known')) || {})[user]; const tok = await SecureStore.getItemAsync(keyOf(user));
    if (!k || !tok || k.h !== h) throw new Error('No network - sign in once online on this HHT first (or wrong password)');
    staff = { user_id: user, name: k.name, perms: k.perms, tok, offline: true }; await kv.set('cust_staff_now', { user_id: user, name: k.name, perms: k.perms });
    return staff;
  }
}
export async function staffLogout() { staff = null; await kv.set('cust_staff_now', null); }

// ---------------------------------------------------------------- receiving AIS deliveries (unloading at the customer)
export async function incoming(refresh = true) {
  if (refresh) { try { const r = await ext('/incoming'); await kv.set('cust_incoming', r.deliveries || []); } catch (e) { if (!e.offline) throw e; } }
  return (await kv.get('cust_incoming')) || [];
}
/** Send the pallets scanned while unloading; without network they wait and are sent automatically. */
export async function receive(picklist_no, scanned) {
  const item = { picklist_no, scanned, client_ref: uid(), at: new Date().toISOString() };
  try { const r = await ext('/receive', { method: 'POST', body: item }); incoming(true).catch(() => {}); return { sent: true, result: r }; }
  catch (e) {
    if (!e.offline) throw e;
    const q = (await kv.get('cust_recv_outbox')) || []; q.push(item); await kv.set('cust_recv_outbox', q);
    return { sent: false };
  }
}
export async function sendReceipts() {
  const q = (await kv.get('cust_recv_outbox')) || []; if (!q.length) return 0;
  const left = []; let n = 0;
  for (const it of q) { try { await ext('/receive', { method: 'POST', body: it }); n++; } catch (e) { left.push(it); if (e.offline) { left.push(...q.slice(q.indexOf(it) + 1)); break; } } }
  await kv.set('cust_recv_outbox', left); return n;
}
