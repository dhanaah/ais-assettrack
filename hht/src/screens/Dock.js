// Dock out-ward scan. Part pick list: scan LPN (fetches its pallet) or pallet (fetches all its LPNs), any order.
// Empty return: scan other-plant empty pallets. Pick List Control -> confirm (online). Missed-scan alerts shown at once.
// yard mode: empty pallets of another plant loaded at the Pallet Yard - start (owner plant + vehicle), scan, Finish loading -> challan. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, FlatList, Alert, TextInput } from 'react-native';
import { S, C, Btn, Header, ScanInput, Pill, useToast, Toast, Ring, Glass, Screen, Page, Empty } from '../ui/kit';
import { listPicklists, getPicklist, enqueue, addLocalScan, localScans, removeLocalScan, setPalletLocal, addLpnScan, lpnScans, removeLpnScans, setLpnLocal, logActivity, kv } from '../lib/db';
import { validateDockScan2 } from '../lib/rules';
import { api } from '../lib/api';
import { printGcs } from '../lib/printer';
import { state as sync, syncNow, pushAndResult } from '../lib/sync';

const isPart = (k) => ['CUSTOMER', 'STOCK_TRANSFER'].includes(k?.dispatch_type);
const isYard = (k) => k?.load_point === 'YARD';
const isGcs = (k) => k?.source === 'GCS';
const label = (k) => k.dispatch_type === 'EMPTY_RETURN' ? `Empty pallets → ${k.to_plant}${isYard(k) ? ' · Yard loading' + (k.vehicle_no ? ' · ' + k.vehicle_no : '') : ''}` : isGcs(k) ? `GCS ${k.gcs_no || ''} · ${k.customer} · ${k.vehicle_no || 'vehicle ?'}${k.invoice_no ? ' · inv ' + k.invoice_no : ''}` : isPart(k) ? (k.part_no ? `${k.customer} · ${k.part_no} × ${k.part_qty}` : `Dispatch Bench trip · ${k.customer} · ${k.part_qty} pcs`) : `Customer ${k.customer} · pallets only`;

export default function Dock({ onBack, yard = false }) {
  const [lists, setLists] = useState([]); const [pk, setPk] = useState(null); const [scans, setScans] = useState([]); const [lpns, setLpns] = useState([]);
  const [waitLpn, setWaitLpn] = useState(null); const [alert, setAlert] = useState(null); const [msg, toast] = useToast();
  const [opts, setOpts] = useState(null); const [owner, setOwner] = useState(null); const [veh, setVeh] = useState('');
  const [gcsAsk, setGcsAsk] = useState(null); const [gcsCust, setGcsCust] = useState(''); const [gcsVeh, setGcsVeh] = useState(''); const [result, setResult] = useState(null);
  const openGcs = async (code, manual) => {
    try { const body = { gcs_no: code }; if (manual) { body.vehicle_no = gcsVeh; body.customer_code = gcsCust; }
      const k = await api('/picklists/gcs-open', { method: 'POST', body }); logActivity('GCS_OPEN', k.picklist_no, k.gcs_no); setGcsAsk(null); await syncNow(); const fresh = (await listPicklists(['OPEN'])).find(x => x.picklist_no === k.picklist_no); await load(); if (fresh) open(fresh); else toast('Opened ' + k.gcs_no + ' - pull down to refresh', 'ok'); }
    catch (e) { if (e.status === 404) { setGcsAsk(code); toast('GCS not received yet - enter vehicle and customer', 'warn'); } else toast(e.offline ? 'Opening a GCS needs the server' : e.message, 'err'); }
  };
  const load = async () => setLists((await listPicklists(['OPEN'])).filter(k => yard ? isYard(k) : !isYard(k)));
  useEffect(() => { load(); }, []);
  const newReturn = async () => { try { setOpts(await api('/picklists/yard-return/options')); setOwner(null); setVeh(''); } catch (e) { toast(e.offline ? 'Starting a return needs the server (offline)' : e.message, 'err'); } };
  const start = async () => {
    if (!owner) return toast('Select the owner plant', 'err');
    try { const k = await api('/picklists/yard-return', { method: 'POST', body: { to_plant: owner, vehicle_no: veh || null } }); logActivity('YARD_RETURN_START', k.picklist_no, owner); setOpts(null); await syncNow(); const fresh = (await listPicklists(['OPEN'])).find(x => x.picklist_no === k.picklist_no); await load(); if (fresh) open(fresh); }
    catch (e) { toast(e.message, 'err'); }
  };
  const [srv, setSrv] = useState(null);
  const [items, setItems] = useState(null); const [showItems, setShowItems] = useState(false);
  const refresh = async (k = pk) => { setScans(await localScans(k.picklist_no)); setLpns(await lpnScans(k.picklist_no)); const fresh = await getPicklist(k.picklist_no); setSrv(fresh ? { scanned: fresh.scanned, picked: fresh.picked_qty } : null);
    if (isGcs(k) && sync.online) api(`/picklists/${k.picklist_no}`).then(r => setItems(r.items || [])).catch(() => { }); };
  const open = async (k) => { setPk(k); setWaitLpn(null); setAlert(null); setItems(null); setShowItems(false); await refresh(k); };

  const onScan = async (code) => {
    let first = code, second = null;
    if (waitLpn) { first = waitLpn.lpn; second = code; }
    const v = await validateDockScan2(pk.picklist_no, first, second);
    if (!v.ok) {
      if (v.needPallet) { setWaitLpn(v.lpn); return toast(v.msg, 'warn'); }
      setWaitLpn(null); toast(v.msg, v.dup ? 'warn' : 'err'); logActivity('SCAN_REJECTED_LOCAL', pk.picklist_no, v.msg, { scanned: code }); return;
    }
    setWaitLpn(null);
    if (!(await localScans(pk.picklist_no)).some(x => x.pallet_no === v.pallet.pallet_no)) await addLocalScan(pk.picklist_no, v.pallet.pallet_no);
    await setPalletLocal(v.pallet.pallet_no, { status: 'ALLOCATED', picklist: pk.picklist_no, load: pk.dispatch_type === 'EMPTY_RETURN' ? 'EMPTY' : (v.lpns.length ? 'LOADED' : v.pallet.load) });
    for (const l of v.lpns) { await addLpnScan(pk.picklist_no, l.lpn, v.pallet.pallet_no, l.qty); await setLpnLocal(l.lpn, { status: 'PICKED', picklist: pk.picklist_no, pallet: v.pallet.pallet_no }); }
    const payload = { picklist_no: pk.picklist_no, scanned: first, local_pallet: v.pallet.pallet_no }; if (second) payload.pallet = second;
    const id = await enqueue('PALLET_SCAN_DOCK', payload, !sync.online);
    logActivity(sync.online ? 'SCAN_DOCK' : 'SCAN_DOCK_OFFLINE', pk.picklist_no, v.pallet.pallet_no, { lpns: v.lpns.map(l => l.lpn) });
    await refresh();
    toast(v.lpns.length ? `${v.pallet.pallet_no}: ${v.lpns.map(l => l.lpn).join(', ')}` : v.pallet.pallet_no, v.warn.length ? 'warn' : 'ok');
    if (v.warn.length) setAlert(v.warn.join('\n'));
    const r = await pushAndResult(id);
    if (r.status === 'REJECTED') { setAlert('Server rejected: ' + r.result); toast(r.result, 'err'); await syncNow({ full: true }).catch(() => {}); await refresh(); }
    else if (r.status === 'EXCEPTION') setAlert(r.result);
  };
  const remove = (item, isLpn) => Alert.alert('Remove', (isLpn ? 'LPN ' + item.lpn : 'Pallet ' + item.pallet_no + ' and its LPNs') + ' from this list?', [{ text: 'Cancel' }, { text: 'Remove', style: 'destructive', onPress: async () => {
    if (isLpn) { await removeLpnScans(pk.picklist_no, { lpn: item.lpn }); await setLpnLocal(item.lpn, { status: 'RESERVED', picklist: null }); }
    else { await removeLocalScan(pk.picklist_no, item.pallet_no); await removeLpnScans(pk.picklist_no, { pallet: item.pallet_no }); await setPalletLocal(item.pallet_no, { status: pk.dispatch_type === 'EMPTY_RETURN' ? 'HELD' : 'AVAILABLE', picklist: null }); }
    await enqueue('PALLET_UNSCAN_DOCK', { picklist_no: pk.picklist_no, scanned: isLpn ? item.lpn : item.pallet_no }, !sync.online); await refresh(); if (sync.online) syncNow().catch(() => {}); } }]);
  const picked = lpns.reduce((a, x) => a + (x.qty || 0), 0);
  const complete = isGcs(pk) || isYard(pk) ? scans.length > 0 : isPart(pk) ? picked === pk?.part_qty && scans.length > 0 : scans.length === pk?.qty;
  const confirm = async () => {
    if (!complete) return toast(isPart(pk) ? `Pick List Control: part ${picked} vs ${pk.part_qty}` : `Pick List Control: ${scans.length} scanned vs qty ${pk.qty}`, 'err');
    if (!sync.online) return toast('Confirm needs the server (offline). Scans are saved; confirm when online.', 'warn');
    if (isYard(pk) && !(await new Promise(res => Alert.alert('Finish loading', `${scans.length} empty pallets → ${pk.to_plant}. Make the challan now?`, [{ text: 'Cancel', onPress: () => res(false) }, { text: 'Finish & challan', onPress: () => res(true) }])))) return;
    if (isGcs(pk) && !(await new Promise(res => Alert.alert('Finish loading', `${scans.length} pallet(s) loaded on ${pk.vehicle_no || 'the vehicle'} for GCS ${pk.gcs_no}. Make the challan and the gate QR now?`, [{ text: 'Not yet', onPress: () => res(false) }, { text: 'Finish loading', onPress: () => res(true) }])))) return;
    try { await syncNow(); const r = await api(`/picklists/${pk.picklist_no}/confirm`, { method: 'POST' });
      if (isGcs(pk)) { setResult({ ...r, pk }); logActivity('GCS_LOADED', pk.picklist_no, r.challan_no); }
      else if (isYard(pk)) { if (r.challan_no) Alert.alert('Challan ready', `Challan ${r.challan_no}\nE-way bill ${r.ewaybill_no || '-'}\n${r.qty} pallets → ${pk.to_plant}\n\nPrint it from the web Pick Lists page; logistics approval and OUT gate as usual.`); else Alert.alert('Loading finished', r.challan_message || 'Challan pending'); }
      else toast(`${pk.picklist_no} is ${r.status}${r.status === 'PDI_PENDING' ? ' → QA / PDI next' : ''}`); logActivity('PICKLIST_CONFIRM', pk.picklist_no, r.status); if (!isGcs(pk)) { setPk(null); } await syncNow(); load(); }
    catch (e) { toast(e.message, 'err'); }
  };

  if (result) return (<Screen><Header title="Loading complete" sub={`GCS ${result.gcs_no} · ${result.vehicle_no || ''}`} onBack={() => { setResult(null); setPk(null); }} /><Page>
    <Glass style={{ alignItems: 'center' }}><Ring value={String(result.scanned ?? result.qty)} label="pallets loaded" color={C.ok} size={92} /></Glass>
    {result.gcs_check && (result.gcs_check.missing_lpns.length || result.gcs_check.extra_lpns.length || (result.gcs_check.missing_pallets || []).length || (result.gcs_check.expected_pallets && result.gcs_check.expected_pallets !== result.gcs_check.loaded_pallets)) ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.warn }]}>
      <Text style={[S.h2, { color: C.warn }]}>Check with the GCS</Text>
      {result.gcs_check.expected_pallets && result.gcs_check.expected_pallets !== result.gcs_check.loaded_pallets ? <Text style={S.body}>Pallets: GCS {result.gcs_check.expected_pallets}, loaded {result.gcs_check.loaded_pallets}</Text> : null}
      {(result.gcs_check.missing_pallets || []).length ? <Text style={S.body}>Pallets in GCS not loaded ({result.gcs_check.missing_pallets.length}): {result.gcs_check.missing_pallets.slice(0, 8).join(', ')}{result.gcs_check.missing_pallets.length > 8 ? ' …' : ''}</Text> : null}
      {(result.gcs_check.extra_pallets || []).length ? <Text style={S.body}>Pallets loaded but not in GCS ({result.gcs_check.extra_pallets.length}): {result.gcs_check.extra_pallets.slice(0, 8).join(', ')}</Text> : null}
      {result.gcs_check.missing_lpns.length ? <Text style={S.body}>Part cards in GCS not scanned ({result.gcs_check.missing_lpns.length}): {result.gcs_check.missing_lpns.slice(0, 8).join(', ')}{result.gcs_check.missing_lpns.length > 8 ? ' …' : ''}</Text> : null}
      {result.gcs_check.extra_lpns.length ? <Text style={S.body}>Scanned but not in GCS ({result.gcs_check.extra_lpns.length}): {result.gcs_check.extra_lpns.slice(0, 8).join(', ')}</Text> : null}
      <Text style={S.mute}>Recorded in the audit log.</Text></View> : null}
    <View style={S.card}><Text style={S.h2}>Challan {result.challan_no}</Text><Text style={S.mute}>Customer {result.customer_code} · invoice {result.invoice_no || '—'} · status {result.status}</Text>
      <Text style={[S.body, { marginTop: 8, color: result.gcs_print && result.gcs_print !== 'off' && !/fail/i.test(result.gcs_print) ? C.ok : C.amber }]}>{result.gcs_print && result.gcs_print !== 'off' ? `GCS PDF ${result.gcs_print} - collect it from the plant printer and hand it to the driver with the challan.` : 'Automatic printing is off for this plant - print the GCS PDF from the web (Pick Lists) or on the portable printer.'}</Text></View>
    {result.gcs_print && result.gcs_print !== 'off' ? <Btn title="Print again on plant printer" secondary icon="print-outline" onPress={async () => { try { const r = await api(`/picklists/${result.picklist_no}/gcs-print`, { method: 'POST' }); toast('GCS ' + r.print, 'ok'); } catch (e) { toast(e.message, 'err'); } }} /> : null}
    <Btn title="Print GCS slip (portable printer)" icon="print-outline" onPress={async () => { try { const plant = await kv.get('plant'); const r = await printGcs(result, plant, result.gcs_qr); toast(r.printed ? 'Printed' : 'No printer - print from the web', r.printed ? 'done' : 'warn'); } catch (e) { toast('Print failed: ' + e.message, 'err'); } }} />
    <Btn title="Done" secondary icon="checkmark-outline" onPress={() => { setResult(null); setPk(null); }} />
  </Page><Toast msg={msg} /></Screen>);

  if (!pk && gcsAsk !== null) return (<Screen><Header title="Open GCS manually" sub="The GCS file has not reached the server yet" onBack={() => setGcsAsk(null)} /><Page>
    <View style={S.card}><Text style={S.h2}>GCS {gcsAsk}</Text>
      <Text style={S.mute}>Vehicle number</Text><TextInput style={S.input} value={gcsVeh} onChangeText={t => setGcsVeh(t.toUpperCase())} autoCapitalize="characters" placeholder="TN01AB1234" />
      <Text style={S.mute}>Customer code</Text><TextInput style={S.input} value={gcsCust} onChangeText={t => setGcsCust(t.toUpperCase())} autoCapitalize="characters" placeholder="HMIL" />
      <Btn title="Open loading sheet" icon="play-outline" onPress={() => openGcs(gcsAsk, true)} color={gcsVeh && gcsCust ? C.ok : C.accent} /></View></Page><Toast msg={msg} /></Screen>);

  if (!pk && opts) return (<Screen><Header title="New empty pallet return" sub="Loading at the Pallet Yard" onBack={() => setOpts(null)} /><Page>
    <Text style={S.h2}>Owner plant of the pallets</Text>
    {opts.length === 0 ? <Text style={S.mute}>No other plant's pallets are held here.</Text> : null}
    {opts.map(o => <TouchableOpacity key={o.plant} style={[S.card, owner === o.plant ? { borderWidth: 2, borderColor: C.ok } : null]} onPress={() => setOwner(o.plant)}>
      <View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{o.plant}</Text><Pill s={`${o.pallets} held`} /></View><Text style={S.mute}>{o.name}</Text></TouchableOpacity>)}
    <Text style={S.mute}>Vehicle no. (optional now, needed before OUT gate)</Text><TextInput style={S.input} value={veh} onChangeText={t => setVeh(t.toUpperCase())} autoCapitalize="characters" placeholder="TN01AB1234" />
    <Btn title="Start loading" icon="play-outline" onPress={start} color={owner ? C.ok : C.accent} /></Page><Toast msg={msg} /></Screen>);

  if (!pk) return (<Screen><Header title={yard ? 'Empty Pallet Return' : 'Vehicle Loading'} sub={yard ? 'Other plants\' empty pallets, loaded at the Yard' : 'Select a pick list'} onBack={onBack} /><Page onRefresh={async () => { await syncNow(); load(); }}>
    {yard ? <Btn title="New empty return (scan at Yard)" icon="add-circle-outline" onPress={newReturn} /> : <View style={[S.card, { paddingVertical: 10 }]}><Text style={S.h2}>Load a vehicle by GCS</Text><Text style={S.mute}>Scan the GCS QR or type the GCS number; the loading sheet opens with vehicle, customer and invoice.</Text><ScanInput autoFocus={false} placeholder="Scan / type GCS number" onScan={(code) => openGcs(code, false)} /></View>}
    {lists.length === 0 ? <Empty icon="list-outline" text={yard ? 'No open Yard loading' : 'No open trips'} hint={yard ? 'Start a new empty return above.' : 'Trips planned in the Dispatch Planning Bench appear here within a minute. Pull down to refresh.'} /> : null}
    {lists.map(k => <TouchableOpacity key={k.picklist_no} style={S.card} onPress={() => open(k)}>
      <View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{k.picklist_no}</Text><Pill s={k.dispatch_type || 'PALLET_ONLY'} /></View>
      <Text style={S.mute}>{label(k)} · pallets {isYard(k) ? k.scanned : `${k.scanned}/${k.qty}`}{isPart(k) ? ` · picked ${k.picked_qty}` : ''}</Text></TouchableOpacity>)}
    <Btn title="Refresh" secondary icon="refresh" onPress={async () => { await syncNow(); load(); }} /></Page><Toast msg={msg} /></Screen>);

  const byPallet = scans.map(p => ({ ...p, lpns: lpns.filter(l => l.pallet === p.pallet_no) }));
  return (<Screen><Header title={pk.picklist_no} sub={label(pk)} onBack={() => setPk(null)} />
    <View style={[S.pad, { paddingBottom: 0 }]}>
      <Glass style={{ flexDirection: 'row', justifyContent: 'space-around' }}>
        {isPart(pk) && !isGcs(pk) ? <Ring value={`${picked}/${pk.part_qty}`} label={pk.part_no ? `${pk.part_no} picked` : 'Bench LPN qty'} color={picked === pk.part_qty ? C.ok : C.accent} size={92} /> : null}
        {isGcs(pk) ? <Ring value={String(lpns.length)} label="part cards" color={C.accent} size={92} /> : null}
        <Ring value={isYard(pk) || isGcs(pk) ? `${scans.length}${isGcs(pk) && pk.qty ? '/' + pk.qty : ''}` : `${scans.length}/${pk.qty}`} label={isYard(pk) ? 'empty pallets loaded' : isGcs(pk) ? 'pallets loaded' : 'pallets'} color={complete ? C.ok : C.accent} size={92} />
      </Glass>
      {isGcs(pk) && items && items.length ? <TouchableOpacity activeOpacity={0.8} onPress={() => setShowItems(!showItems)} style={[S.card, { paddingVertical: 8, marginTop: 8, marginBottom: 0 }]}>
        <View style={S.row}><Text style={{ flex: 1, fontWeight: '700', color: C.fg }}>{new Set(items.map(i => i.invoice_no).filter(Boolean)).size} invoice(s) · {items.length} line(s) · qty {items.reduce((a, i) => a + (i.qty || 0), 0)}</Text><Text style={S.mute}>{showItems ? 'hide ▲' : 'show ▼'}</Text></View>
        {showItems ? items.map(i => <View key={i.line_no} style={{ flexDirection: 'row', marginTop: 4 }}><Text style={[S.mute, { flex: 1 }]} numberOfLines={1}>{i.invoice_no || '—'} · {i.part_no || ''}</Text><Text style={{ fontWeight: '700', color: lpns.length && i.qty && i.loaded < i.qty ? C.amber : C.ok }}>{lpns.length ? `${i.loaded}/` : ''}{i.qty ?? ''}</Text></View>) : null}
      </TouchableOpacity> : null}
      {srv && srv.scanned !== scans.length ? <Text style={[S.mute, { textAlign: 'center', marginTop: 4 }]}>Server has {srv.scanned} pallet{srv.scanned === 1 ? '' : 's'} on this list (this HHT: {scans.length}) · another HHT may be scanning too</Text> : null}
      {waitLpn ? <Text style={{ color: C.amber, fontWeight: '700', marginTop: 6 }}>LPN {waitLpn.lpn} waiting → scan its PALLET</Text> : null}
      {alert ? <TouchableOpacity onPress={() => setAlert(null)} style={{ backgroundColor: C.warn, borderRadius: 12, padding: 10, marginTop: 6 }}><Text style={{ color: '#fff', fontWeight: '700' }}>⚠ {alert}</Text><Text style={{ color: '#fff', fontSize: 11 }}>tap to dismiss · recorded in Missed Scans</Text></TouchableOpacity> : null}
      <ScanInput onScan={onScan} placeholder={pk.dispatch_type === 'EMPTY_RETURN' ? 'Scan empty pallet' : isGcs(pk) ? 'Scan pallet tag or part card' : isPart(pk) ? 'Scan LPN or pallet' : 'Scan pallet tag'} />
    </View>
    <FlatList style={{ flex: 1, paddingHorizontal: 14, marginTop: 8 }} data={byPallet} keyExtractor={x => x.pallet_no} renderItem={({ item, index }) => (
      <View style={[S.card, { paddingVertical: 8, marginBottom: 6 }]}>
        <TouchableOpacity onLongPress={() => remove(item, false)} style={{ flexDirection: 'row' }}><Text style={{ flex: 1, fontWeight: '700' }}>{index + 1}. {item.pallet_no}</Text><Text style={S.mute}>{item.ts.slice(11, 19)}</Text></TouchableOpacity>
        {item.lpns.map(l => <TouchableOpacity key={l.lpn} onLongPress={() => remove(l, true)}><Text style={[S.mute, { marginLeft: 14 }]}>• {l.lpn} × {l.qty}</Text></TouchableOpacity>)}
      </View>)} />
    <View style={S.pad}><Btn title={isGcs(pk) ? 'Finish loading → challan + gate QR' : isPart(pk) ? 'Confirm → send to PDI' : isYard(pk) ? 'Finish loading → make challan' : 'Confirm load list (Pick List Control)'} icon="checkmark-circle-outline" onPress={confirm} color={complete ? C.ok : C.accent} /><Text style={[S.mute, { textAlign: 'center', marginTop: 4 }]}>Long-press a pallet or LPN to remove</Text></View>
    <Toast msg={msg} /></Screen>);
}
