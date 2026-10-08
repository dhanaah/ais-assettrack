// Server API client with timeout; token kept in SecureStore. Developed by DT
import * as SecureStore from 'expo-secure-store';
import { kv } from './db';

export const APP_VERSION = '1.1.0';
let token = null, baseUrl = null;

export async function loadSession() {
  token = await SecureStore.getItemAsync('token');
  baseUrl = (await kv.get('server_url')) || 'http://192.168.1.10:8001';
  return { token, baseUrl };
}
export async function setServer(url) { baseUrl = url.replace(/\/+$/, ''); await kv.set('server_url', baseUrl); }
export const getServer = () => baseUrl;
export async function setToken(t) { token = t; if (t) await SecureStore.setItemAsync('token', t); else await SecureStore.deleteItemAsync('token'); }
export const hasToken = () => !!token;

export class ApiError extends Error { constructor(msg, status, offline) { super(msg); this.status = status; this.offline = offline; } }

export async function api(path, { method = 'GET', body, timeout = 15000, auth = true } = {}) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(baseUrl + '/api/v1' + path, {
      method, signal: ctl.signal,
      headers: { 'Content-Type': 'application/json', 'X-Device': 'HHT', ...(auth && token ? { Authorization: 'Bearer ' + token } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await r.json().catch(() => ({}));
    if (r.status === 401 && auth) { throw new ApiError(j.detail || 'Session expired', 401); }
    if (!r.ok) throw new ApiError(typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || r.statusText), r.status);
    return j;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError('Server unreachable', 0, true);
  } finally { clearTimeout(t); }
}

export async function login(user_id, password, device_id) {
  const r = await api('/auth/login', { method: 'POST', body: { user_id, password, device_id, app_version: APP_VERSION }, auth: false });
  await setToken(r.token);
  await kv.set('me', r);
  return r;
}
export const me = async () => kv.get('me');
