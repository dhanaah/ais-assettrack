// Vehicle list for quick pick (works offline): vehicles AIS knows (sent by the server - recent loads, return slips and
// transporter vehicles) + vehicles added on this HHT (Setup > Vehicles), most recently used first. Developed by DT
import { kv } from './db';

export const cleanVeh = (v) => String(v || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 15);
export async function setServerVehicles(list) { if (Array.isArray(list)) await kv.set('vehicles_srv', list.map(cleanVeh).filter(Boolean)); }
export async function localVehicles() { return (await kv.get('vehicles_local')) || []; }
export async function addVehicle(v) { v = cleanVeh(v); if (!v) return; const l = await localVehicles(); if (!l.includes(v)) { l.unshift(v); await kv.set('vehicles_local', l.slice(0, 300)); } }
export async function removeVehicle(v) { await kv.set('vehicles_local', (await localVehicles()).filter((x) => x !== v)); }
export async function usedVehicle(v) { v = cleanVeh(v); if (!v) return; const r = ((await kv.get('vehicles_recent')) || []).filter((x) => x !== v); r.unshift(v); await kv.set('vehicles_recent', r.slice(0, 30)); await addVehicle(v); }
/** All vehicles: recently used first, then this HHT's list, then the server's. */
export async function allVehicles() {
  const out = []; const add = (v) => { v = cleanVeh(v); if (v && !out.includes(v)) out.push(v); };
  ((await kv.get('vehicles_recent')) || []).forEach(add); (await localVehicles()).forEach(add); ((await kv.get('vehicles_srv')) || []).forEach(add);
  return out;
}
