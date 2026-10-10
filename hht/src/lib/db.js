// Local SQLite: reference cache + outbox (durable queue of scans). Developed by DT
import * as SQLite from 'expo-sqlite';

let db;
export async function openDb() {
  if (db) return db;
  db = await SQLite.openDatabaseAsync('pallet_hht.db');
  // v2 (app 1.5) / v3 (app 1.8): cache tables gained columns - cache only, so drop & rebuild, then a full pull refills them
  const ver = await db.getFirstAsync("SELECT v FROM kv WHERE k='schema'").catch(() => null);
  if (!ver || JSON.parse(ver.v) < 4) {
    await db.execAsync(`DROP TABLE IF EXISTS pallets; DROP TABLE IF EXISTS picklists; CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
      DELETE FROM kv WHERE k='last_pull'; INSERT OR REPLACE INTO kv(k,v) VALUES('schema','4');`);
  }
  await db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS pallets (pallet_no TEXT PRIMARY KEY, tag TEXT, home TEXT, type TEXT, status TEXT, customer TEXT, picklist TEXT, zone TEXT, load TEXT, load_ref TEXT, location TEXT);
    CREATE TABLE IF NOT EXISTS lpns (lpn TEXT PRIMARY KEY, part TEXT, qty INTEGER, pallet TEXT, status TEXT, reserved_for TEXT, picklist TEXT);
    CREATE INDEX IF NOT EXISTS ix_lpns_pallet ON lpns(pallet);
    CREATE TABLE IF NOT EXISTS local_lpn_scans (id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, lpn TEXT, pallet TEXT, qty INTEGER, ts TEXT);
    CREATE INDEX IF NOT EXISTS ix_pallets_tag ON pallets(tag);
    CREATE TABLE IF NOT EXISTS tags (tag TEXT PRIMARY KEY, pallet TEXT, status TEXT);
    CREATE TABLE IF NOT EXISTS picklists (picklist_no TEXT PRIMARY KEY, customer TEXT, type TEXT, qty INTEGER, status TEXT, scanned INTEGER, dispatch_type TEXT, part_no TEXT, part_qty INTEGER, to_plant TEXT, picked_qty INTEGER, source TEXT, load_point TEXT, vehicle_no TEXT, gcs_no TEXT, invoice_no TEXT);
    CREATE TABLE IF NOT EXISTS slips (slip_no TEXT PRIMARY KEY, customer TEXT, mode TEXT, qty INTEGER, status TEXT, pallets TEXT);
    CREATE TABLE IF NOT EXISTS customers (code TEXT PRIMARY KEY, name TEXT, return_mode TEXT);
    CREATE TABLE IF NOT EXISTS outbox (
      event_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, local_ts TEXT, offline INTEGER,
      status TEXT DEFAULT 'PENDING', result TEXT, attempts INTEGER DEFAULT 0, created_at TEXT);
    CREATE INDEX IF NOT EXISTS ix_outbox_status ON outbox(status);
    CREATE TABLE IF NOT EXISTS local_docs (doc_no TEXT PRIMARY KEY, kind TEXT, payload TEXT, status TEXT DEFAULT 'PENDING', result TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS local_scans (id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, pallet_no TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, action TEXT, ref TEXT, result TEXT, detail TEXT, sent INTEGER DEFAULT 0);
  `);
  return db;
}

export const kv = {
  async get(k, d = null) { const r = await (await openDb()).getFirstAsync('SELECT v FROM kv WHERE k=?', k); return r ? JSON.parse(r.v) : d; },
  async set(k, v) { await (await openDb()).runAsync('INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)', k, JSON.stringify(v)); },
};

// ---------- reference cache
export async function applyPull(data) {
  const d = await openDb();
  await d.withTransactionAsync(async () => {
    if (data.full) { await d.execAsync('DELETE FROM pallets; DELETE FROM tags; DELETE FROM picklists; DELETE FROM slips; DELETE FROM customers; DELETE FROM lpns;'); }
    for (const p of data.pallets) await d.runAsync('INSERT OR REPLACE INTO pallets VALUES(?,?,?,?,?,?,?,?,?,?,?)', p.pallet_no, p.tag, p.home, p.type, p.status, p.customer, p.picklist, p.zone || 'YARD', p.load || 'EMPTY', p.load_ref || null, p.location || null);
    for (const l of (data.lpns || [])) { if (['DISPATCHED', 'REJECTED', 'MISSING'].includes(l.status)) await d.runAsync('DELETE FROM lpns WHERE lpn=?', l.lpn); else await d.runAsync('INSERT OR REPLACE INTO lpns VALUES(?,?,?,?,?,?,?)', l.lpn, l.part, l.qty, l.pallet, l.status, l.reserved_for, l.picklist); }
    for (const t of data.tags) await d.runAsync('INSERT OR REPLACE INTO tags VALUES(?,?,?)', t.tag, t.pallet, t.status);
    await d.execAsync('DELETE FROM picklists; DELETE FROM slips; DELETE FROM customers;');
    for (const k of data.picklists) await d.runAsync('INSERT OR REPLACE INTO picklists VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', k.picklist_no, k.customer, k.type, k.qty, k.status, k.scanned, k.dispatch_type || 'PALLET_ONLY', k.part_no, k.part_qty, k.to_plant, k.picked_qty || 0, k.source || 'APP', k.load_point || null, k.vehicle_no || null, k.gcs_no || null, k.invoice_no || null);
    for (const s of data.slips) await d.runAsync('INSERT OR REPLACE INTO slips VALUES(?,?,?,?,?,?)', s.slip_no, s.customer, s.mode, s.qty, s.status, JSON.stringify(s.pallets));
    for (const c of data.customers) await d.runAsync('INSERT OR REPLACE INTO customers VALUES(?,?,?)', c.code, c.name, c.return_mode);
  });
  await kv.set('plant', data.plant);
  await kv.set('last_pull', data.server_time);
}

// AIS pallet label QR: {"uniquePalletID":"AIS-AAB-ANF-00001-0000001","ownerPlant":"AAB","palletType":"ANF",...} or the plain ID
export function parsePalletQr(scanned) {
  const s = String(scanned || '').trim();
  if (s.startsWith('{')) { try { const d = JSON.parse(s); const id = String(d.uniquePalletID || d.palletID || d.pallet_no || '').trim().toUpperCase(); if (!id) return null; const m = id.match(/^AIS-([A-Z0-9]{2,6})-([A-Z0-9]{1,8})-/); return { pallet_no: id, owner: String(d.ownerPlant || (m ? m[1] : '')).toUpperCase() || null, type: String(d.palletType || (m ? m[2] : '')).toUpperCase() || null }; } catch (e) { return null; } }
  const m = s.toUpperCase().match(/^AIS-([A-Z0-9]{2,6})-([A-Z0-9]{1,8})-(\d{3,8})-(\d{4,10})$/);
  return m ? { pallet_no: s.toUpperCase(), owner: m[1], type: m[2] } : null;
}
export async function resolveTag(scanned) {
  const d = await openDb(); const q = parsePalletQr(scanned); const s = q ? q.pallet_no : String(scanned).trim();
  let p = await d.getFirstAsync('SELECT * FROM pallets WHERE tag=?', s);
  if (!p) p = await d.getFirstAsync('SELECT * FROM pallets WHERE pallet_no=?', s);
  if (!p) { const t = await d.getFirstAsync('SELECT * FROM tags WHERE tag=?', s); if (t && t.pallet) p = await d.getFirstAsync('SELECT * FROM pallets WHERE pallet_no=?', t.pallet); if (!p && t) return { tag: t, pallet: null }; }
  return { tag: null, pallet: p || null };
}
export const getLpn = async (s) => (await openDb()).getFirstAsync('SELECT * FROM lpns WHERE lpn=?', String(s).trim());
export const lpnsOnPallet = async (pallet) => (await openDb()).getAllAsync("SELECT * FROM lpns WHERE pallet=? AND status IN ('AVAILABLE','RESERVED','PICKED','PDI_OK')", pallet);
export const setLpnLocal = async (lpn, fields) => {
  const d = await openDb(); const sets = Object.keys(fields).map(k => `${k}=?`).join(',');
  await d.runAsync(`UPDATE lpns SET ${sets} WHERE lpn=?`, ...Object.values(fields), lpn);
};
export const addLpnScan = async (ref, lpn, pallet, qty) => (await openDb()).runAsync('INSERT INTO local_lpn_scans(ref,lpn,pallet,qty,ts) VALUES(?,?,?,?,?)', ref, lpn, pallet, qty, new Date().toISOString());
export const lpnScans = async (ref) => (await openDb()).getAllAsync('SELECT * FROM local_lpn_scans WHERE ref=? ORDER BY id', ref);
export const removeLpnScans = async (ref, { lpn, pallet }) => lpn ? (await openDb()).runAsync('DELETE FROM local_lpn_scans WHERE ref=? AND lpn=?', ref, lpn) : (await openDb()).runAsync('DELETE FROM local_lpn_scans WHERE ref=? AND pallet=?', ref, pallet);
export const eventResult = async (event_id) => (await openDb()).getFirstAsync('SELECT status, result FROM outbox WHERE event_id=?', event_id);
export const setPalletLocal = async (pallet_no, fields) => {
  const d = await openDb(); const sets = Object.keys(fields).map(k => `${k}=?`).join(',');
  await d.runAsync(`UPDATE pallets SET ${sets} WHERE pallet_no=?`, ...Object.values(fields), pallet_no);
};
export const listPicklists = async (statuses = ['OPEN', 'SO_PENDING', 'READY']) => (await openDb()).getAllAsync(`SELECT * FROM picklists WHERE status IN (${statuses.map(() => '?').join(',')}) ORDER BY picklist_no DESC`, ...statuses);
export const listSlips = async () => (await openDb()).getAllAsync("SELECT * FROM slips ORDER BY slip_no DESC");
export const listCustomers = async () => (await openDb()).getAllAsync('SELECT * FROM customers ORDER BY name');
export const getPicklist = async (no) => (await openDb()).getFirstAsync('SELECT * FROM picklists WHERE picklist_no=?', no);
export const getSlip = async (no) => (await openDb()).getFirstAsync('SELECT * FROM slips WHERE slip_no=?', no);

// local scan ledger per document (works offline, survives restart)
export const addLocalScan = async (ref, pallet_no) => (await openDb()).runAsync('INSERT INTO local_scans(ref,pallet_no,ts) VALUES(?,?,?)', ref, pallet_no, new Date().toISOString());
export const localScans = async (ref) => (await openDb()).getAllAsync('SELECT * FROM local_scans WHERE ref=? ORDER BY id', ref);
export const localScanExists = async (ref, pallet_no) => !!(await (await openDb()).getFirstAsync('SELECT 1 FROM local_scans WHERE ref=? AND pallet_no=?', ref, pallet_no));
export const removeLocalScan = async (ref, pallet_no) => (await openDb()).runAsync('DELETE FROM local_scans WHERE ref=? AND pallet_no=?', ref, pallet_no);

// ---------- outbox
export async function enqueue(event_type, payload, offline) {
  const d = await openDb();
  const event_id = globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : uuid();
  await d.runAsync('INSERT INTO outbox(event_id,event_type,payload,local_ts,offline,created_at) VALUES(?,?,?,?,?,?)',
    event_id, event_type, JSON.stringify(payload), new Date().toISOString(), offline ? 1 : 0, new Date().toISOString());
  return event_id;
}
export const pendingEvents = async (limit = 200) => (await openDb()).getAllAsync("SELECT * FROM outbox WHERE status='PENDING' ORDER BY local_ts LIMIT ?", limit);
export const pendingCount = async () => (await (await openDb()).getFirstAsync("SELECT COUNT(*) c FROM outbox WHERE status='PENDING'")).c;
export const markEvent = async (event_id, status, result) => {
  const d = await openDb();
  await d.runAsync('UPDATE outbox SET status=?, result=?, attempts=attempts+1 WHERE event_id=?', status, result || null, event_id);
  if (status === 'REJECTED') await undoRejected(d, event_id);
};
// a dock scan the server refused must leave the local pick-list ledger too (otherwise the count on the HHT is wrong)
async function undoRejected(d, event_id) {
  try {
    const e = await d.getFirstAsync('SELECT event_type, payload FROM outbox WHERE event_id=?', event_id);
    if (!e || e.event_type !== 'PALLET_SCAN_DOCK') return;
    const p = JSON.parse(e.payload); const pallet = p.local_pallet; if (!pallet) return;
    await d.runAsync('DELETE FROM local_scans WHERE ref=? AND pallet_no=?', p.picklist_no, pallet);
    await d.runAsync('DELETE FROM local_lpn_scans WHERE ref=? AND pallet=?', p.picklist_no, pallet);
    const plant = (await kv.get('plant'))?.code || '';
    await d.runAsync("UPDATE pallets SET status=CASE WHEN home=? THEN 'AVAILABLE' ELSE 'HELD' END, picklist=NULL WHERE pallet_no=? AND picklist=?", plant, pallet, p.picklist_no);
    await d.runAsync("UPDATE lpns SET status='RESERVED', picklist=NULL WHERE picklist=? AND pallet=?", p.picklist_no, pallet);
  } catch (err) { }
}
export const recentEvents = async (n = 100) => (await openDb()).getAllAsync('SELECT * FROM outbox ORDER BY created_at DESC LIMIT ?', n);
export const purgeOld = async (days = 30) => (await openDb()).runAsync("DELETE FROM outbox WHERE status<>'PENDING' AND created_at < ?", new Date(Date.now() - days * 864e5).toISOString());

// local documents created offline (return slips) - replayed on sync
export const enqueueDoc = async (doc_no, kind, payload) => (await openDb()).runAsync('INSERT OR REPLACE INTO local_docs(doc_no,kind,payload,created_at) VALUES(?,?,?,?)', doc_no, kind, JSON.stringify(payload), new Date().toISOString());
export const pendingDocs = async () => (await openDb()).getAllAsync("SELECT * FROM local_docs WHERE status='PENDING' ORDER BY created_at");
export const markDoc = async (doc_no, status, result) => (await openDb()).runAsync('UPDATE local_docs SET status=?, result=? WHERE doc_no=?', status, result || null, doc_no);

function uuid() { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); }); }

// ---------- activity trail (who did what on this device; reported to server on sync)
export async function logActivity(action, ref = null, result = null, detail = null) {
  try { await (await openDb()).runAsync('INSERT INTO activity(ts,action,ref,result,detail) VALUES(?,?,?,?,?)', new Date().toISOString(), action, ref, result, detail ? JSON.stringify(detail).slice(0, 2000) : null); } catch (e) { }
}
export const unsentActivity = async (n = 500) => (await openDb()).getAllAsync('SELECT * FROM activity WHERE sent=0 ORDER BY id LIMIT ?', n);
export const markActivitySent = async (ids) => { if (ids.length) await (await openDb()).runAsync(`UPDATE activity SET sent=1 WHERE id IN (${ids.map(() => '?').join(',')})`, ...ids); };
export const recentActivity = async (n = 100) => (await openDb()).getAllAsync('SELECT * FROM activity ORDER BY id DESC LIMIT ?', n);
export const purgeActivity = async (days = 30) => (await openDb()).runAsync('DELETE FROM activity WHERE sent=1 AND ts < ?', new Date(Date.now() - days * 864e5).toISOString());
