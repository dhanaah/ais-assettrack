// Offline validation - same rules as the server, applied to the local cache. Developed by DT
import { resolveTag, getPicklist, localScans, localScanExists, kv, getLpn, lpnsOnPallet, lpnScans } from './db';

const PART_TYPES = ['CUSTOMER', 'STOCK_TRANSFER'];
const DISPATCH_ZONES = ['FGWH', 'PACKING'];

// Pallet check shared by part / pallet-only lists. Missed-scan cases (pallet still AT_CUSTOMER, wrong zone) are allowed
// here with a warning - the server records them and auto-corrects, so production is never stopped.
async function palletForDispatch(pk, pallet, plant, warn) {
  if (pallet.home !== plant) return `Foreign pallet ${pallet.pallet_no} (${pallet.home})`;
  if (pallet.status === 'ALLOCATED' && pallet.picklist === pk.picklist_no) return null;
  if (['AT_CUSTOMER', 'IN_RETURN', 'IN_TRANSIT'].includes(pallet.status)) { warn.push(`${pallet.pallet_no} shows ${pallet.status} - return scan missed, will be recorded`); return null; }
  if (pallet.status !== 'AVAILABLE') return `${pallet.pallet_no} is ${pallet.status}${pallet.picklist ? ' (' + pallet.picklist + ')' : ''}`;
  if (pallet.zone && !DISPATCH_ZONES.includes(pallet.zone)) warn.push(`${pallet.pallet_no} shown in ${pallet.zone} - internal move missed, will be recorded`);
  if ((await localScans(pk.picklist_no)).length >= pk.qty) return `Pallet qty ${pk.qty} already reached`;
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
  if (!lpn) pallet = (await resolveTag(scanned)).pallet;
  if (palletScan) { const p2 = (await resolveTag(palletScan)).pallet; if (!p2) return { ok: false, msg: `Unknown pallet ${palletScan}` }; pallet = p2; }
  if (!lpn && !pallet) return { ok: false, msg: `Unknown LPN / tag ${scanned}` };

  if (pk.dispatch_type === 'EMPTY_RETURN') {
    if (lpn) return { ok: false, msg: 'Empty return: scan the pallet' };
    if (pallet.home !== pk.to_plant) return { ok: false, msg: `${pallet.pallet_no} belongs to ${pallet.home}, return is for ${pk.to_plant}` };
    if (!['HELD', 'IN_WIP'].includes(pallet.status)) return { ok: false, msg: `${pallet.pallet_no} is ${pallet.status}` };
    if (await localScanExists(picklist_no, pallet.pallet_no)) return { ok: false, msg: 'Already scanned', dup: true };
    if (pallet.load === 'LOADED') warn.push(`${pallet.pallet_no} shown LOADED - WIP consumption not scanned`);
    if ((await localScans(picklist_no)).length >= pk.qty) return { ok: false, msg: `Pallet qty ${pk.qty} reached` };
    return { ok: true, pallet, lpns: [], warn };
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
    if (!pk.part_no && l.reserved_for !== picklist_no && l.picklist !== picklist_no) return `LPN ${l.lpn} is not on this HMIL Bench trip`;
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

const ROUTES = { PRODUCTION: ['YARD'], FGWH: ['PRODUCTION'], PACKING: ['PRODUCTION', 'FGWH'], YARD: ['PACKING'] };
export async function validateMove(scanned, toZone) {
  let { pallet } = await resolveTag(scanned);
  if (!pallet) { const l = await getLpn(scanned); if (l && l.pallet) pallet = (await resolveTag(l.pallet)).pallet; }
  if (!pallet) return { ok: false, msg: `Unknown pallet ${scanned}` };
  if (['ALLOCATED', 'DISCONTINUED', 'DAMAGED', 'UNDER_REPAIR'].includes(pallet.status)) return { ok: false, msg: `${pallet.pallet_no} is ${pallet.status}` };
  const plant = (await kv.get('plant'))?.code;
  if (toZone === 'YARD' && pallet.home !== plant && ['AT_CUSTOMER', 'IN_TRANSIT'].includes(pallet.status)) return { ok: false, msg: `${pallet.pallet_no} is other-plant material - receive at FGWH / Packing` };
  const warn = [];
  const from = pallet.zone || 'YARD';
  if (from === toZone) return { ok: false, msg: `${pallet.pallet_no} already in ${toZone}`, dup: true };
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
  const { tag, pallet } = await resolveTag(scanned);
  if (!pallet) return { ok: true, exception: 'UNKNOWN', msg: `Unknown tag ${scanned} - quarantine`, pallet: null };
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
