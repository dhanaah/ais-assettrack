// Offline validation - same rules as the server, applied to the local cache. Developed by DT
import { resolveTag, getPicklist, localScans, localScanExists, kv, getLpn, lpnsOnPallet, lpnScans, parsePalletQr, gcsCardCount, gcsCardsOnPallet } from './db';

const PART_TYPES = ['CUSTOMER', 'STOCK_TRANSFER'];
const DISPATCH_ZONES = ['FGWH', 'DISPATCH', 'PACKING'];

// Pallet check shared by part / pallet-only lists. Missed-scan cases (pallet still AT_CUSTOMER, wrong zone) are allowed
// here with a warning - the server records them and auto-corrects, so production is never stopped.
async function palletForDispatch(pk, pallet, plant, warn) {
  if (pallet.home !== plant) return `Foreign pallet ${pallet.pallet_no} (${pallet.home})`;
  if (pallet.status === 'ALLOCATED' && pallet.picklist === pk.picklist_no) return null;
  if (['AT_CUSTOMER', 'IN_RETURN', 'IN_TRANSIT'].includes(pallet.status)) { warn.push(`${pallet.pallet_no} shows ${pallet.status} - return scan missed, will be recorded`); return null; }
  if (pallet.status !== 'AVAILABLE') return `${pallet.pallet_no} is ${pallet.status}${pallet.picklist ? ' (' + pallet.picklist + ')' : ''}`;
  if (pallet.zone && !DISPATCH_ZONES.includes(pallet.zone)) warn.push(`${pallet.pallet_no} shown in ${pallet.zone} - internal move missed, will be recorded`);
  // Dispatch Bench trips and GCS loads have no pallet count limit (same as the server)
  if (!['DISPATCH_BENCH', 'HMIL_BENCH', 'GCS'].includes(pk.source) && (await localScans(pk.picklist_no)).length >= pk.qty) return `Pallet qty ${pk.qty} already reached`;
  return null;
}

/** Dock scan: LPN or pallet in any order. Returns {ok, pallet, lpns, needPallet, msg, warn}. */
export async function validateDockScan2(picklist_no, scanned, palletScan) {
  const plant = (await kv.get('plant'))?.code;
  const pk = await getPicklist(picklist_no);
  if (!pk) return { ok: false, msg: 'Pick list not in cache - sync first' };
  if (pk.status !== 'OPEN') return { ok: false, msg: `Pick list is ${pk.status}` };
  const warn = [];
  let lpn = await getLpn(scanned); let pallet = null;
  const retired = (t) => t && t.status === 'RETIRED';
  if (!lpn) { const rt = await resolveTag(scanned); if (retired(rt.tag)) return { ok: false, msg: `Tag ${rt.tag.tag} is retired` }; pallet = rt.pallet; }
  if (palletScan) { const rt2 = await resolveTag(palletScan); if (retired(rt2.tag)) return { ok: false, msg: `Tag ${rt2.tag.tag} is retired` }; const p2 = rt2.pallet; if (!p2) return { ok: false, msg: `Unknown pallet ${palletScan}` }; pallet = p2; }
  // GCS loading: an unknown part card is not "unknown" - it is a card that is not on this GCS (no PDI) -> STOP below
  const looksPallet = /^\s*(\{|AIS-)/i.test(scanned);
  if (!lpn && !pallet && (pk.source !== 'GCS' || looksPallet)) return { ok: false, msg: `Unknown ${looksPallet ? 'pallet' : 'LPN / tag'} ${scanned}` };

  if (pk.dispatch_type === 'EMPTY_RETURN') {
    if (lpn) return { ok: false, msg: 'Empty return: scan the pallet' };
    if (!pallet) return { ok: false, msg: `Unknown pallet ${scanned}` };
    if (pallet.home !== pk.to_plant) return { ok: false, msg: `${pallet.pallet_no} belongs to ${pallet.home}, return is for ${pk.to_plant}` };
    if (!['HELD', 'IN_WIP'].includes(pallet.status)) return { ok: false, msg: `${pallet.pallet_no} is ${pallet.status}` };
    if (await localScanExists(picklist_no, pallet.pallet_no)) return { ok: false, msg: 'Already scanned', dup: true };
    if (pallet.load === 'LOADED') warn.push(`${pallet.pallet_no} shown LOADED - WIP consumption not scanned`);
    if (pk.load_point === 'YARD') { if (pallet.zone && pallet.zone !== 'YARD') warn.push(`${pallet.pallet_no} shown in ${pallet.zone} - move to Yard not scanned, will be recorded`); }
    else if ((await localScans(picklist_no)).length >= pk.qty) return { ok: false, msg: `Pallet qty ${pk.qty} reached` };
    return { ok: true, pallet, lpns: [], warn };
  }
  if (pk.source === 'GCS') {
    // part cards must be on this GCS (= PDI passed and invoiced for this vehicle) - otherwise stop: do PDI first
    if (!lpn && !pallet && scanned.includes('.')) lpn = await getLpn(scanned.trim().split('.').pop());
    const cardNo = lpn ? lpn.lpn : (!pallet ? scanned.trim().split('.').pop().toUpperCase() : null);
    if (cardNo && await gcsCardCount(picklist_no) && !(lpn && (lpn.reserved_for === picklist_no || lpn.picklist === picklist_no))) {
      if (lpn && lpn.reserved_for && String(lpn.reserved_for).startsWith('GCS-')) return { ok: false, stop: true, msg: `Part card ${cardNo} belongs to another GCS - wrong vehicle` };
      return { ok: false, stop: true, msg: `Part card ${cardNo} is NOT in GCS ${pk.gcs_no || ''} - not PDI passed for this vehicle.\nSTOP: do PDI first, keep it off the vehicle.` };
    }
    if (lpn && !pallet) { if (lpn.pallet) pallet = (await resolveTag(lpn.pallet)).pallet; if (!pallet) return { ok: false, needPallet: true, lpn, msg: `Part card ${lpn.lpn} - now scan the pallet it is on` }; }
    if (!lpn && !pallet) { if (palletScan) return { ok: false, msg: `Unknown pallet ${palletScan}` }; return { ok: false, needPallet: true, lpn: { lpn: scanned, qty: 0, part: pk.part_no }, msg: `Part card ${scanned} - now scan the pallet it is on` }; }
    if (pallet.home !== plant) return { ok: false, msg: `Foreign pallet ${pallet.pallet_no} (${pallet.home})` };
    if (!lpn && await localScanExists(picklist_no, pallet.pallet_no)) return { ok: false, msg: 'Already loaded on this GCS', dup: true };
    if (!['AVAILABLE', 'ALLOCATED'].includes(pallet.status) || (pallet.status === 'ALLOCATED' && pallet.picklist !== picklist_no)) { if (['AT_CUSTOMER', 'IN_RETURN', 'IN_TRANSIT'].includes(pallet.status)) warn.push(`${pallet.pallet_no} shows ${pallet.status} - return scan missed, will be recorded`); else return { ok: false, msg: `${pallet.pallet_no} is ${pallet.status}${pallet.picklist ? ' (' + pallet.picklist + ')' : ''}` }; }
    return { ok: true, pallet, lpns: lpn ? [lpn] : await gcsCardsOnPallet(picklist_no, pallet.pallet_no), warn };
  }
  if (!PART_TYPES.includes(pk.dispatch_type)) {
    if (lpn) return { ok: false, msg: 'Pallet-only list: scan the pallet' };
    if (await localScanExists(picklist_no, pallet.pallet_no)) return { ok: false, msg: 'Already scanned on this list', dup: true };
    const e = await palletForDispatch(pk, pallet, plant, warn); if (e) return { ok: false, msg: e };
    return { ok: true, pallet, lpns: [], warn };
  }
  // part pick list
  const picked = (await lpnScans(picklist_no)).reduce((a, x) => a + (x.qty || 0), 0);
  const okLpn = (l) => {
    if (pk.part_no && l.part !== pk.part_no) return `LPN ${l.lpn} is ${l.part}; list needs ${pk.part_no}`;
    if (!pk.part_no && l.reserved_for !== picklist_no && l.picklist !== picklist_no) return `LPN ${l.lpn} is not on this Dispatch Bench trip`;
    if (l.status === 'RESERVED' && l.reserved_for && l.reserved_for !== picklist_no) return `LPN ${l.lpn} reserved for ${l.reserved_for}`;
    if (!['AVAILABLE', 'RESERVED'].includes(l.status)) return `LPN ${l.lpn} is ${l.status}`;
    return null;
  };
  let lpns = [];
  if (lpn) {
    const e = okLpn(lpn); if (e) return { ok: false, msg: e };
    if (!pallet && lpn.pallet) pallet = (await resolveTag(lpn.pallet)).pallet;
    if (!pallet) return { ok: false, needPallet: true, lpn, msg: `LPN ${lpn.lpn} not linked - scan its pallet` };
    lpns = [lpn];
  } else {
    lpns = (await lpnsOnPallet(pallet.pallet_no)).filter(l => !okLpn(l));
    if (!lpns.length) return { ok: false, msg: `No ${pk.part_no || 'trip'} LPN linked to ${pallet.pallet_no} - scan the LPN label` };
  }
  const done = new Set((await lpnScans(picklist_no)).map(x => x.lpn));
  lpns = lpns.filter(l => !done.has(l.lpn));
  if (!lpns.length) return { ok: false, msg: 'Already scanned', dup: true };
  const add = lpns.reduce((a, l) => a + (l.qty || 0), 0);
  if (pk.part_no && picked + add > (pk.part_qty || 0)) return { ok: false, msg: `Qty ${add} exceeds balance ${(pk.part_qty || 0) - picked}` };
  if (!(await localScanExists(picklist_no, pallet.pallet_no))) { const e = await palletForDispatch(pk, pallet, plant, warn); if (e) return { ok: false, msg: e }; }
  return { ok: true, pallet, lpns, warn, picked: picked + add };
}

// FGWH is the centre: Production -> FGWH -> Main Dispatch / Packing; FGWH -> Production = return (rejection / damage / lot-out)
const ROUTES = { PRODUCTION: ['YARD', 'FGWH'], FGWH: ['PRODUCTION'], DISPATCH: ['FGWH'], PACKING: ['FGWH', 'YARD'], YARD: ['PACKING', 'PRODUCTION', 'FGWH', 'DISPATCH'] };
const NO_MOVE = { 'PRODUCTION>DISPATCH': 'Production -> Main Dispatch is not allowed - finished goods go to FGWH first', 'PRODUCTION>PACKING': 'Production -> Packing is not allowed - finished goods go to FGWH first', 'DISPATCH>PACKING': 'No movement between Main Dispatch and Packing', 'PACKING>DISPATCH': 'No movement between Main Dispatch and Packing' };
/** Pallet card (part card / LPN label on the pallet) known on this HHT. Developed by DT */
export const isCard = async (code) => !!(await getLpn(code)) || (String(code).includes('.') && !!(await getLpn(String(code).split('.').pop().toUpperCase())));
/** Pallet QR / tag known on this HHT (or a pallet QR label). */
export const isPalletQr = async (code) => !!(await resolveTag(code)).pallet || /^AIS-|^\{/.test(String(code).trim());
export async function validateMove(scanned, toZone) {
  if (!ROUTES[toZone]) return { ok: false, msg: `Unknown zone ${toZone}` };
  let { pallet } = await resolveTag(scanned);
  if (!pallet) { const l = await getLpn(scanned); if (l && l.pallet) pallet = (await resolveTag(l.pallet)).pallet; }
  if (!pallet) return { ok: false, msg: `Unknown pallet ${scanned}` };
  if (['ALLOCATED', 'DISCONTINUED', 'DAMAGED', 'UNDER_REPAIR'].includes(pallet.status)) return { ok: false, msg: `${pallet.pallet_no} is ${pallet.status}` };
  const plant = (await kv.get('plant'))?.code;
  if (toZone === 'YARD' && pallet.home !== plant && ['AT_CUSTOMER', 'IN_TRANSIT'].includes(pallet.status)) return { ok: false, msg: `${pallet.pallet_no} is other-plant material - receive at FGWH / Packing` };
  const warn = [];
  const from = pallet.zone || 'YARD';
  if (from === toZone) return { ok: false, msg: `${pallet.pallet_no} already in ${toZone}`, dup: true };
  if (NO_MOVE[`${from}>${toZone}`] && !(from === 'PRODUCTION' && toZone === 'PACKING' && pallet.load === 'EMPTY')) return { ok: false, msg: NO_MOVE[`${from}>${toZone}`] };
  if (!ROUTES[toZone].includes(from)) warn.push(`${pallet.pallet_no} shown in ${from} - skipped step will be recorded`);
  if (toZone === 'YARD' && pallet.load === 'LOADED') warn.push('Yard = empty only: pallet will be marked EMPTY');
  return { ok: true, pallet, warn };
}

export async function validateDockScan(picklist_no, scanned) {
  const plant = (await kv.get('plant'))?.code;
  const pk = await getPicklist(picklist_no);
  if (!pk) return { ok: false, msg: 'Pick list not in cache - sync first' };
  if (!['OPEN', 'SO_PENDING'].includes(pk.status)) return { ok: false, msg: `Pick list is ${pk.status}` };
  const { tag, pallet } = await resolveTag(scanned);
  if (!pallet && !tag) return { ok: false, msg: `Unknown tag ${scanned}` };
  if (tag && tag.status === 'RETIRED') return { ok: false, msg: `Tag ${tag.tag} is retired` };
  if (!pallet) return { ok: false, msg: 'Tag not assigned to a pallet' };
  if (pallet.home !== plant) return { ok: false, msg: `Foreign pallet ${pallet.pallet_no} (${pallet.home})` };
  if (await localScanExists(picklist_no, pallet.pallet_no)) return { ok: false, msg: 'Already scanned on this list', dup: true };
  if (pallet.status !== 'AVAILABLE') return { ok: false, msg: `${pallet.pallet_no} is ${pallet.status}${pallet.picklist ? ' (' + pallet.picklist + ')' : ''}` };
  const n = (await localScans(picklist_no)).length;
  if (n >= pk.qty) return { ok: false, msg: `Pick list qty ${pk.qty} already reached` };
  return { ok: true, pallet, count: n + 1, qty: pk.qty };
}

export async function validateYardScan(slip, scanned, acceptForeign) {
  const plant = (await kv.get('plant'))?.code;
  if (await isCard(scanned)) return { ok: false, msg: 'Pallet Yard: scan the pallet QR, not the pallet card' };
  const { tag, pallet } = await resolveTag(scanned);
  if (!pallet) { const q = parsePalletQr(scanned); if (q) return { ok: true, exception: 'NEW', msg: `New pallet ${q.pallet_no} (${q.type || '?'}, owner ${q.owner || '?'}) - will be registered from its QR`, pallet: null, newPallet: q }; return { ok: true, exception: 'UNKNOWN', msg: `Unknown tag ${String(scanned).slice(0, 40)} - quarantine`, pallet: null }; }
  if (slip && await localScanExists(slip.slip_no, pallet.pallet_no)) return { ok: false, msg: 'Already scanned', dup: true };
  if (pallet.home !== plant) {
    if (!acceptForeign) return { ok: false, msg: `Other-plant pallet ${pallet.pallet_no} (${pallet.home}) - tick Accept to hold it` };
    return { ok: true, exception: 'FOREIGN', msg: `${pallet.pallet_no} HELD for ${pallet.home}`, pallet };
  }
  let exception = null;
  if (slip) {
    const declared = JSON.parse(slip.pallets || '[]');
    if (!declared.includes(pallet.pallet_no)) exception = pallet.customer && pallet.customer !== slip.customer ? 'CROSS_CUSTOMER' : 'EXCESS';
  }
  return { ok: true, exception, pallet, msg: exception ? `${pallet.pallet_no} ${exception}` : `${pallet.pallet_no} received` };
}

export async function validateReturnPallet(customer, scanned) {
  const { pallet } = await resolveTag(scanned);
  if (!pallet) return { ok: true, warn: 'unknown tag - listed as declared', pallet_no: String(scanned).trim() };
  if (pallet.customer !== customer || pallet.status !== 'AT_CUSTOMER') return { ok: true, warn: `ledger shows ${pallet.status} ${pallet.customer || ''}`.trim(), pallet_no: pallet.pallet_no };
  return { ok: true, pallet_no: pallet.pallet_no };
}
