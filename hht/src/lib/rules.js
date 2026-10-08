// Offline validation - same rules as the server, applied to the local cache. Developed by DT
import { resolveTag, getPicklist, localScans, localScanExists, kv } from './db';

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
