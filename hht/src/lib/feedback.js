// Audio + haptic feedback for scan results - distinct, loud, short, so an operator never has to look at the screen
// to know whether a scan was accepted. Tones are generated in the app (no audio files) and cached as WAV.
// OK = one high beep · WARN = two mid beeps · ERROR = one long low buzz. Developed by DT
import { Vibration } from 'react-native';
import { kv } from './db';

let Audio = null, FS = null;
try { Audio = require('expo-av').Audio; } catch (e) { Audio = null; }
try { FS = require('expo-file-system'); } catch (e) { FS = null; }

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function toB64(bytes) {
  let out = ''; let i = 0;
  for (; i + 2 < bytes.length; i += 3) { const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2]; out += B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + B64[n & 63]; }
  if (i < bytes.length) { const n = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8); out += B64[n >> 18] + B64[(n >> 12) & 63] + (i + 1 < bytes.length ? B64[(n >> 6) & 63] : '=') + '='; }
  return out;
}
/** segments: [[freqHz, ms], [0, gapMs], ...] -> 8-bit mono WAV at 16 kHz with a short fade to avoid clicks */
function wav(segments, volume = 0.9) {
  const rate = 16000; const total = segments.reduce((a, s) => a + Math.round(rate * s[1] / 1000), 0);
  const data = new Uint8Array(total); let o = 0;
  for (const [f, ms] of segments) {
    const n = Math.round(rate * ms / 1000); const fade = Math.min(80, n >> 2);
    for (let i = 0; i < n; i++) {
      const env = i < fade ? i / fade : i > n - fade ? (n - i) / fade : 1;
      const v = f ? Math.sin(2 * Math.PI * f * i / rate) * volume * env : 0;
      data[o++] = 128 + Math.round(v * 127);
    }
  }
  const h = new Uint8Array(44); const dv = new DataView(h.buffer); const str = (p, s) => { for (let i = 0; i < s.length; i++) h[p + i] = s.charCodeAt(i); };
  str(0, 'RIFF'); dv.setUint32(4, 36 + total, true); str(8, 'WAVE'); str(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, rate, true); dv.setUint32(28, rate, true); dv.setUint16(32, 1, true); dv.setUint16(34, 8, true); str(36, 'data'); dv.setUint32(40, total, true);
  const all = new Uint8Array(44 + total); all.set(h); all.set(data, 44); return toB64(all);
}

const TONES = {
  ok: [[1760, 90]],
  warn: [[880, 110], [0, 70], [880, 110]],
  err: [[220, 420]],
  done: [[1318, 90], [0, 40], [1760, 140]],
};
const PATTERNS = { ok: 40, warn: [0, 60, 60, 60], err: [0, 120, 80, 220], done: [0, 40, 40, 80] };
const sounds = {}; let enabled = true; let ready = false;

export async function initFeedback() {
  try { enabled = (await kv.get('sound')) !== false; } catch (e) { }
  if (!Audio || !FS || ready) return;
  try {
    await Audio.setAudioModeAsync({ playsInSilentModeIOS: true, staysActiveInBackground: false, shouldDuckAndroid: true });
    for (const k of Object.keys(TONES)) {
      const uri = FS.cacheDirectory + `at_${k}.wav`;
      await FS.writeAsStringAsync(uri, wav(TONES[k]), { encoding: FS.EncodingType.Base64 });
      const { sound } = await Audio.Sound.createAsync({ uri }, { shouldPlay: false, volume: 1.0 });
      sounds[k] = sound;
    }
    ready = true;
  } catch (e) { ready = false; }
}
export async function setSoundEnabled(on) { enabled = !!on; await kv.set('sound', !!on); }
export const soundEnabled = () => enabled;

/** kind: 'ok' | 'warn' | 'err' | 'done' */
export function feedback(kind = 'ok') {
  try { Vibration.vibrate(PATTERNS[kind] || 40); } catch (e) { }
  if (!enabled || !ready || !sounds[kind]) return;
  sounds[kind].replayAsync().catch(() => { });
}
