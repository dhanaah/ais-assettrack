// App update check: the server announces the newest APK it holds (server\apk\ folder) at /api/v1/app/latest.
// The HHT compares with its own version and shows a banner; tapping opens the download in the browser. Developed by DT
import { Linking } from 'react-native';
import { api, APP_VERSION, getActiveServer } from './api';

export const vlt = (a, b) => { const p = (x) => String(x || '0').split('-')[0].split('.').map((n) => +n || 0); const A = p(a), B = p(b); for (let i = 0; i < 3; i++) { if ((A[i] || 0) < (B[i] || 0)) return true; if ((A[i] || 0) > (B[i] || 0)) return false; } return false; };

export async function checkUpdate() {
  try {
    const r = await api('/app/latest', { auth: false, timeout: 6000 });
    if (!r || !r.version) return null;
    return { ...r, newer: vlt(APP_VERSION, r.version), required: r.min_client ? vlt(APP_VERSION, r.min_client) : false };
  } catch (e) { return null; }
}
export function openUpdate(info) {
  const base = getActiveServer();
  const url = info.url && info.url.startsWith('http') ? info.url : base + info.url;
  Linking.openURL(url).catch(() => { });
}
