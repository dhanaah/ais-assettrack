// Server API client with timeout; token kept in SecureStore. Developed by DT
import * as SecureStore from 'expo-secure-store';
import { kv } from './db';

export const APP_VERSION = '2.0.1';
let token = null, baseUrl = null, deviceHeader = 'HHT';
export const setApiDevice = (id) => { deviceHeader = id; };

export async function loadSession() {
  token = await SecureStore.getItemAsync('token');
  baseUrl = (await kv.get('server_url')) || 'http://assettrack';
  return { token, baseUrl };
}
export async function setServer(url) { baseUrl = url.replace(/\/+$/, ''); activeUrl = null; await kv.set('server_url', baseUrl); }
export const getServer = () => baseUrl;
export const getActiveServer = () => activeUrl || candidates()[0];

// Server address = a NAME (e.g. "assettrack" or the PC name "AISCHNL215"), no IP or port needed.
// The server listens on 80, 8001, 8002, 8003: the HHT tries the name on each port; if one is slow / unreachable the
// next is used and remembered. The field may also hold a list, e.g. "assettrack, AISCHNL215".
const FAILOVER_PORTS = [8001, 8002, 8003];
let activeUrl = null;
function candidates() {
  const list = [];
  const add = (u) => { u = (u || '').trim().replace(/\/+$/, ''); if (u && !/^https?:\/\//i.test(u)) u = 'http://' + u; if (u && !list.includes(u)) list.push(u); };
  const typed = (baseUrl || '').split(/[,;\s]+/).filter(Boolean);
  if (activeUrl) add(activeUrl);
  typed.forEach(add);
  typed.forEach((u) => {
    const m = u.trim().match(/^(https?:\/\/)?([^/:]+)(:\d+)?/i);
    if (m) { add((m[1] || 'http://') + m[2]); FAILOVER_PORTS.forEach((p) => add((m[1] || 'http://') + m[2] + ':' + p)); }
  });
  return list;
}
export async function setToken(t) { token = t; if (t) await SecureStore.setItemAsync('token', t); else await SecureStore.deleteItemAsync('token'); }
export const hasToken = () => !!token;

export class ApiError extends Error { constructor(msg, status, offline) { super(msg); this.status = status; this.offline = offline; } }

// calls that are safe to send twice (server de-duplicates or nothing changes)
const SAFE = (method, path) => (method || 'GET') === 'GET' || /^\/(sync\/push|auth\/login|activity\/device)/.test(path);

export async function api(path, opts = {}) {
  const list = candidates();
  const safe = SAFE(opts.method, path);
  let last = null;
  for (let i = 0; i < list.length; i++) {
    // first address: normal wait (max 10 s unless the call asks for more); others: short wait so a slow port does not hold the operator
    const timeout = i === 0 ? (opts.timeout > 15000 ? opts.timeout : Math.min(opts.timeout || 15000, 10000)) : Math.max(5000, opts.timeout > 15000 ? 15000 : 0);
    try {
      const r = await apiAt(list[i], path, { ...opts, timeout });
      activeUrl = list[i];
      return r;
    } catch (e) {
      if (!e.offline) { activeUrl = list[i]; throw e; }     // server answered with an error: no failover
      last = e;
      if (e.timedOut && !safe) break;                       // may have been saved already - do not send a second time
    }
  }
  throw last || new ApiError('Server unreachable', 0, true);
}

async function apiAt(url, path, { method = 'GET', body, timeout = 15000, auth = true } = {}) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(url + '/api/v1' + path, {
      method, signal: ctl.signal,
      headers: { 'Content-Type': 'application/json', 'X-Device': 'HHT', 'X-Device-Id': deviceHeader, 'X-App-Version': APP_VERSION, ...(auth && token ? { Authorization: 'Bearer ' + token } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await r.json().catch(() => ({}));
    if (r.status === 401 && auth) { throw new ApiError(j.detail || 'Session expired', 401); }
    if (!r.ok) throw new ApiError(typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || r.statusText), r.status);
    return j;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    const err = new ApiError('Server unreachable', 0, true); err.timedOut = e?.name === 'AbortError'; throw err;
  } finally { clearTimeout(t); }
}

export async function login(user_id, password, device_id) {
  const r = await api('/auth/login', { method: 'POST', body: { user_id, password, device_id, app_version: APP_VERSION }, auth: false });
  await setToken(r.token);
  await kv.set('me', r);
  return r;
}
export const me = async () => kv.get('me');
