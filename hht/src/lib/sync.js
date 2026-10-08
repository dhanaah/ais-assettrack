// Sync engine: push outbox in order (idempotent), replay offline-created docs, pull reference cache, heartbeat.
// Runs every 60 s when online and immediately after each scan when online. Developed by DT
import NetInfo from '@react-native-community/netinfo';
import { api, APP_VERSION, hasToken } from './api';
import { pendingEvents, markEvent, pendingDocs, markDoc, applyPull, kv, pendingCount, purgeOld } from './db';

export const state = { online: false, syncing: false, pending: 0, lastSync: null, lastError: null, serverVersion: null };
const listeners = new Set();
export const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
const emit = () => listeners.forEach(f => f({ ...state }));

let deviceId = 'HHT';
export const setDeviceId = (id) => { deviceId = id; };

NetInfo.addEventListener(s => { const was = state.online; state.online = !!(s.isConnected && s.isInternetReachable !== false); emit(); if (!was && state.online) syncNow().catch(() => {}); });

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
        if (e.offline) throw e;
        await markDoc(d.doc_no, e.status === 400 && /exists/i.test(e.message) ? 'DONE' : 'FAILED', e.message);
      }
    }
    // 2 push events in batches of 100
    let batch;
    while ((batch = await pendingEvents(100)).length) {
      const r = await api('/sync/push', { method: 'POST', body: { events: batch.map(e => ({ event_id: e.event_id, device_id: deviceId, event_type: e.event_type, payload: JSON.parse(e.payload), local_ts: e.local_ts, offline: !!e.offline, app_version: APP_VERSION })) }, timeout: 30000 });
      for (const x of r.results) await markEvent(x.event_id, x.status, x.result);
      if (batch.length < 100) break;
    }
    // 3 heartbeat + pull delta
    const pend = await pendingCount();
    await api('/sync/push', { method: 'POST', body: { events: [{ event_id: cryptoId(), device_id: deviceId, event_type: 'HEARTBEAT', payload: { pending: pend }, local_ts: new Date().toISOString(), app_version: APP_VERSION }] } });
    const since = full ? null : await kv.get('last_pull');
    const data = await api('/sync/pull' + (since ? '?since=' + encodeURIComponent(since) : ''), { timeout: 60000 });
    await applyPull(data);
    state.serverVersion = data.server_time; state.lastSync = new Date().toISOString();
    await purgeOld();
  } catch (e) {
    state.lastError = e.message; state.online = !e.offline && state.online;
    if (e.status === 401) state.lastError = 'LOGIN';
  } finally { state.syncing = false; state.pending = await pendingCount(); emit(); }
}

let timer;
export function startAutoSync() { stopAutoSync(); timer = setInterval(() => { if (state.online) syncNow().catch(() => {}); }, 60000); }
export function stopAutoSync() { if (timer) clearInterval(timer); timer = null; }
function cryptoId() { return globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : 'hb-' + Date.now() + '-' + Math.random().toString(16).slice(2); }
