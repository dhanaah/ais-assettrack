// Sync engine: push outbox in order (idempotent), replay offline-created docs, pull reference cache, heartbeat.
// Runs every 60 s when online and immediately after each scan when online. Developed by DT
import NetInfo from '@react-native-community/netinfo';
import { api, APP_VERSION, hasToken } from './api';
import { eventResult, pendingEvents, markEvent, failEvent, pendingDocs, markDoc, failDoc, applyPull, kv, pendingCount, purgeOld, unsentActivity, markActivitySent, purgeActivity, logActivity } from './db';

export const state = { online: false, net: false, server: null, syncing: false, pending: 0, lastSync: null, lastError: null, serverVersion: null };
const listeners = new Set();
export const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
const emit = () => listeners.forEach(f => f({ ...state }));

let deviceId = 'HHT';
export const setDeviceId = (id) => { deviceId = id; };

// online = Wi-Fi / network up AND the AssetTrack server answered the last call (not just Wi-Fi)
NetInfo.addEventListener(s => { const was = state.net; state.net = !!s.isConnected; state.online = state.net && state.server !== false; emit(); if (!was && state.net) syncNow().catch(() => {}); });

export async function refreshPending() { state.pending = await pendingCount(); emit(); }

export async function syncNow({ full = false } = {}) {
  if (state.syncing || !hasToken()) return;
  state.syncing = true; state.lastError = null; emit();
  try {
    // 1 replay offline documents first (slips created offline) so their events can apply
    for (const d of await pendingDocs()) {
      try {
        const p = JSON.parse(d.payload);
        if (d.kind === 'RETURN_SLIP') { await api('/slips', { method: 'POST', body: { ...p, slip_no: d.doc_no } }); }
        await markDoc(d.doc_no, 'DONE', 'ok');
      } catch (e) {
        if (e.offline || [401, 403, 426].includes(e.status)) throw e;   // no network / sign-in needed / old app: the slip stays PENDING
        if (e.status === 400 && /exists/i.test(e.message)) await markDoc(d.doc_no, 'DONE', 'ok');
        else await failDoc(d.doc_no, e.message);                        // retried up to 5 times, then FAILED (Pending & Sync)
      }
    }
    // 1b photos of customer documents waiting for their slip (Option B)
    try { await require('./docscan').sendPhotos(); } catch (e) { }
    // 2 push events in batches of 100
    let batch; const suspects = new Map();            // events the server could not take (error answer) -> message
    const wire = (e) => ({ event_id: e.event_id, device_id: deviceId, event_type: e.event_type, payload: JSON.parse(e.payload), local_ts: e.local_ts, offline: !!e.offline, app_version: APP_VERSION });
    while ((batch = await pendingEvents(100)).length) {
      let r;
      try { r = await api('/sync/push', { method: 'POST', body: { events: batch.map(wire) }, timeout: 30000 }); }
      catch (e) {
        if (e.offline || [401, 403, 426].includes(e.status)) throw e;      // no network / login / plant / old app: whole sync waits as before
        // the server refused the batch: one bad event must not hold up the rest - send them one by one
        for (const ev of batch) {
          try { const r1 = await api('/sync/push', { method: 'POST', body: { events: [wire(ev)] } }); for (const x of r1.results) await markEvent(x.event_id, x.status, x.result); }
          catch (e1) { if (e1.offline || [401, 403, 426].includes(e1.status)) throw e1; suspects.set(ev.event_id, e1.message || 'Server error'); }
        }
        break;                                        // events still refused are tried again at the next sync
      }
      for (const x of r.results) await markEvent(x.event_id, x.status, x.result);
      if (batch.length < 100) break;
    }
    // 2b report device activity trail
    const acts = await unsentActivity();
    if (acts.length) {
      await api('/activity/device', { method: 'POST', body: { device_id: deviceId, app_version: APP_VERSION, items: acts.map(a => ({ ts: a.ts, action: a.action, ref: a.ref, result: a.result, detail: a.detail })) } });
      await markActivitySent(acts.map(a => a.id));
    }
    // 3 heartbeat + pull delta
    const pend = await pendingCount();
    await api('/sync/push', { method: 'POST', body: { events: [{ event_id: cryptoId(), device_id: deviceId, event_type: 'HEARTBEAT', payload: { pending: pend }, local_ts: new Date().toISOString(), app_version: APP_VERSION }] } });
    // the heartbeat went through, so the server is healthy: a refused event counts one try; after 5 it is FAILED
    // (shown in Pending & Sync › Recent events) and no longer sent
    let failed = 0;
    for (const [id, m] of suspects) if (await failEvent(id, m, 5)) { failed++; logActivity('EVENT_FAILED', id, m); }
    const since = full ? null : await kv.get('last_pull');
    const data = await api('/sync/pull' + (since ? '?since=' + encodeURIComponent(since) : ''), { timeout: 60000 });
    await applyPull(data);
    state.serverVersion = data.server_time; state.lastSync = new Date().toISOString();
    await purgeOld(); await purgeActivity();
    await logActivity('SYNC', null, `pushed ok, pending ${state.pending}`);
    state.server = true; state.online = true;
    if (suspects.size) state.lastError = `${suspects.size} event(s) refused by the server${failed ? ` (${failed} now FAILED)` : ' - will retry'} - see Recent events`;
  } catch (e) {
    state.lastError = e.message; logActivity('SYNC_ERROR', null, e.message); if (e.offline) { state.server = false; state.online = false; } else { state.server = true; state.online = true; }
    if (e.status === 401) state.lastError = 'LOGIN';
  } finally { state.syncing = false; state.pending = await pendingCount(); emit(); }
}

/** Send one queued event now (when online) and return the server verdict so missed-scan alerts show at once. */
export async function pushAndResult(event_id) {
  if (!state.online) return { status: 'PENDING', result: 'saved offline - will sync' };
  for (let i = 0; i < 3; i++) {
    await syncNow().catch(() => {});
    const r = await eventResult(event_id);
    if (r && r.status !== 'PENDING') return r;
    await new Promise(res => setTimeout(res, 700));
  }
  return { status: 'PENDING', result: 'queued' };
}

let timer;
// every 30 s (Bench trips reach the HHT quickly); also retries when the server was not reachable
export function startAutoSync() { stopAutoSync(); timer = setInterval(() => { if (state.net || state.online) syncNow().catch(() => {}); }, 30000); }
export function stopAutoSync() { if (timer) clearInterval(timer); timer = null; }
function cryptoId() { return globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : 'hb-' + Date.now() + '-' + Math.random().toString(16).slice(2); }
