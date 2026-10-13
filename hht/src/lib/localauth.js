// Password check without network (plant idle-lock unlock, customer staff sign-in): a salted, iterated SHA-256 of the
// last online sign-in is kept in SecureStore (random salt per user on this HHT). 5 wrong tries -> 5 minutes wait.
// Developed by DT
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import { kv } from './db';
import { sha256Hex } from './hmac';

const ROUNDS = 1000, MAX_FAILS = 5, WAIT_MS = 5 * 60000;
const keyOf = (scope, user) => ('pw_' + scope + '_' + String(user || '').trim().toLowerCase()).replace(/[^A-Za-z0-9._-]/g, '_');
const salt = () => { try { return Array.from(Crypto.getRandomBytes(16), (b) => b.toString(16).padStart(2, '0')).join(''); } catch (e) { return (Date.now().toString(16) + Math.random().toString(16).slice(2)).slice(0, 32); } };
function hash(s, user, pw) {
  let h = sha256Hex(s + '|' + String(user).trim().toLowerCase() + '|' + encodeURIComponent(pw));   // encodeURIComponent: any character -> ASCII
  for (let i = 1; i < ROUNDS; i++) h = sha256Hex(h + s);
  return h;
}

/** After a successful online sign-in: remember the password check for this user (scope e.g. 'plant' or 'cust_HMIL'). */
export async function saveCred(scope, user, pw) {
  try { const s = salt(); await SecureStore.setItemAsync(keyOf(scope, user), JSON.stringify({ s, h: hash(s, user, pw) })); await kv.set('fail_' + keyOf(scope, user), null); } catch (e) { }
}
/** Offline check: true = right password, false = wrong, null = this user never signed in online here. Throws while locked out. */
export async function checkCred(scope, user, pw) {
  const k = keyOf(scope, user); const f = (await kv.get('fail_' + k)) || { n: 0, until: 0 };
  if (f.until > Date.now()) throw new Error(`Too many wrong passwords - try again in ${Math.ceil((f.until - Date.now()) / 60000)} min`);
  let c = null; try { c = JSON.parse((await SecureStore.getItemAsync(k)) || 'null'); } catch (e) { c = null; }
  if (!c || !c.s || !c.h) return null;
  if (hash(c.s, user, pw) === c.h) { await kv.set('fail_' + k, null); return true; }
  const n = (f.n || 0) + 1;
  await kv.set('fail_' + k, n >= MAX_FAILS ? { n: 0, until: Date.now() + WAIT_MS } : { n, until: 0 });
  return false;
}
