// Internal movement, other-plant receipt, PDI and missed-scan view. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, TextInput } from 'react-native';
import { S, C, Btn, Page, Header, ScanInput, Pill, useToast, Toast, Glass, Ring, Screen } from '../ui/kit';
import { enqueue, setPalletLocal, logActivity, resolveTag, listPicklists } from '../lib/db';
import { validateMove } from '../lib/rules';
import { api } from '../lib/api';
import { state as sync, syncNow, pushAndResult } from '../lib/sync';

const ROUTES = [
  ['PRODUCTION', 'Pallet Yard → Production', 'empty pallets to the line'],
  ['FGWH', 'Production → FGWH', 'loaded with finished goods'],
  ['PACKING', 'Production / FGWH → Packing', 'loaded for packing'],
  ['YARD', 'Packing → Pallet Yard', 'EMPTY pallets only'],
];

const AlertBox = ({ text, onClose }) => text ? (
  <TouchableOpacity onPress={onClose} style={{ backgroundColor: C.warn, borderRadius: 12, padding: 10, marginBottom: 8 }}>
    <Text style={{ color: '#fff', fontWeight: '700' }}>⚠ {text}</Text><Text style={{ color: '#fff', fontSize: 11 }}>tap to dismiss · recorded in Missed Scans</Text></TouchableOpacity>) : null;

export function Move({ onBack }) {
  const [route, setRoute] = useState(null); const [done, setDone] = useState([]); const [alert, setAlert] = useState(null); const [msg, toast] = useToast();
  const onScan = async (code) => {
    const v = await validateMove(code, route[0]);
    if (!v.ok) return toast(v.msg, v.dup ? 'warn' : 'err');
    const load = route[0] === 'YARD' || route[0] === 'PRODUCTION' ? 'EMPTY' : 'LOADED';
    await setPalletLocal(v.pallet.pallet_no, { zone: route[0], load, status: route[0] === 'PRODUCTION' && v.pallet.status === 'HELD' ? 'IN_WIP' : (route[0] === 'YARD' && v.pallet.status === 'IN_WIP' ? 'HELD' : v.pallet.status) });
    const id = await enqueue('PALLET_MOVE', { scanned: code, to_zone: route[0] }, !sync.online);
    logActivity('PALLET_MOVE', v.pallet.pallet_no, route[0]);
    setDone(d => [{ p: v.pallet.pallet_no, load, t: new Date().toISOString().slice(11, 19) }, ...d].slice(0, 50));
    toast(`${v.pallet.pallet_no} → ${route[0]} (${load})`, v.warn.length ? 'warn' : 'ok');
    if (v.warn.length) setAlert(v.warn.join('\n'));
    const r = await pushAndResult(id);
    if (r.status === 'REJECTED') { setAlert('Server rejected: ' + r.result); toast(r.result, 'err'); syncNow({ full: true }).catch(() => {}); }
    else if (r.status === 'EXCEPTION') setAlert(r.result);
  };
  if (!route) return (<Screen><Header title="Internal Movement" sub="Select the route" onBack={onBack} /><Page>
    {ROUTES.map(r => <TouchableOpacity key={r[0]} style={S.card} onPress={() => { setRoute(r); setDone([]); setAlert(null); }}>
      <Text style={S.h2}>{r[1]}</Text><Text style={S.mute}>{r[2]}</Text></TouchableOpacity>)}
    <Text style={S.mute}>Pallet Yard holds EMPTY pallets only. A skipped step is detected at the next scan and recorded.</Text></Page><Toast msg={msg} /></Screen>);
  return (<Screen><Header title={route[1]} sub={route[2]} onBack={() => setRoute(null)} /><Page>
    <Glass style={{ alignItems: 'center' }}><Ring value={String(done.length)} label="moved this session" color={C.ok} size={84} /></Glass>
    <AlertBox text={alert} onClose={() => setAlert(null)} />
    <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan pallet (or any LPN on it)" /></View>
    {done.map((d, i) => <View key={i} style={[S.card, { paddingVertical: 8, marginBottom: 6, flexDirection: 'row' }]}><Text style={{ flex: 1, fontWeight: '600' }}>{d.p}</Text><Pill s={d.load} /><Text style={[S.mute, { marginLeft: 8 }]}>{d.t}</Text></View>)}
  </Page><Toast msg={msg} /></Screen>);
}

export function Receipt({ onBack }) {
  const [zone, setZone] = useState('FGWH'); const [ref, setRef] = useState(''); const [done, setDone] = useState([]); const [alert, setAlert] = useState(null); const [msg, toast] = useToast();
  const onScan = async (code) => {
    const { pallet } = await resolveTag(code);
    if (!pallet) return toast('Unknown pallet - sync / check tag', 'err');
    const id = await enqueue('PLANT_RECEIPT', { scanned: code, zone, ref: ref || null }, !sync.online);
    await setPalletLocal(pallet.pallet_no, { status: 'IN_WIP', zone, load: 'LOADED' });
    logActivity('PLANT_RECEIPT', pallet.pallet_no, zone);
    setDone(d => [{ p: pallet.pallet_no, h: pallet.home, t: new Date().toISOString().slice(11, 19) }, ...d]);
    toast(`${pallet.pallet_no} (${pallet.home}) received at ${zone}`);
    const r = await pushAndResult(id);
    if (r.status === 'REJECTED') { setAlert(r.result); toast(r.result, 'err'); } else if (r.status === 'EXCEPTION') setAlert(r.result);
  };
  return (<Screen><Header title="Other-plant Material Receipt" sub="Loaded pallets from another AIS plant" onBack={onBack} /><Page>
    <View style={[S.row, { marginBottom: 8 }]}>{['FGWH', 'PACKING'].map(z => <TouchableOpacity key={z} onPress={() => setZone(z)} style={[S.btnS, { flex: 1, marginTop: 0, backgroundColor: zone === z ? C.accent : undefined }]}><Text style={[S.btnSText, zone === z ? { color: '#fff' } : null]}>Receive at {z}</Text></TouchableOpacity>)}</View>
    <AlertBox text={alert} onClose={() => setAlert(null)} />
    <View style={S.card}><TextInput style={S.input} placeholder="Sending plant challan / invoice (optional)" value={ref} onChangeText={setRef} /><ScanInput onScan={onScan} placeholder="Scan pallet" /></View>
    <Text style={S.mute}>Received pallets stay IN WIP. When emptied: Internal Movement → Packing → Pallet Yard, then an Empty Return pick list sends them home (EBS challan + e-way bill).</Text>
    {done.map((d, i) => <View key={i} style={[S.card, { paddingVertical: 8, marginBottom: 6 }]}><Text style={{ fontWeight: '600' }}>{d.p} · home {d.h}</Text><Text style={S.mute}>{d.t}</Text></View>)}
  </Page><Toast msg={msg} /></Screen>);
}

export function Pdi({ onBack }) {
  const [lists, setLists] = useState([]); const [pk, setPk] = useState(null); const [data, setData] = useState(null); const [rejectMode, setRejectMode] = useState(false); const [remarks, setRemarks] = useState(''); const [msg, toast] = useToast();
  const load = async () => { try { setLists(await api('/picklists?status=PDI_PENDING')); } catch (e) { setLists(await listPicklists(['PDI_PENDING'])); toast('Offline - PDI needs the server', 'warn'); } };
  useEffect(() => { load(); }, []);
  const refresh = async (no = pk.picklist_no) => setData(await api(`/picklists/${no}/lpns`));
  const open = async (k) => { setPk(k); try { await refresh(k.picklist_no); } catch (e) { toast(e.message, 'err'); } };
  const mark = async (code, result) => {
    if (!sync.online) return toast('PDI needs the server (online)', 'err');
    try { const r = await api(`/picklists/${pk.picklist_no}/pdi`, { method: 'POST', body: { scanned: code, result, remarks: result === 'REJECT' ? remarks : null } }); toast(`${code}: ${r.message}`, result === 'REJECT' ? 'warn' : 'ok'); logActivity('PDI_MARK', pk.picklist_no, `${code} ${result}`); setRemarks(''); await refresh(); }
    catch (e) { toast(e.message, 'err'); }
  };
  const complete = async () => {
    try { const r = await api(`/picklists/${pk.picklist_no}/pdi-complete`, { method: 'POST' }); toast(`${r.message} · ${r.status}${r.so_number ? ' · SO ' + r.so_number : ''}`, r.rejected?.length ? 'warn' : 'ok'); logActivity('PDI_COMPLETE', pk.picklist_no, r.status); setPk(null); setData(null); load(); syncNow().catch(() => {}); }
    catch (e) { toast(e.message, 'err'); }
  };
  if (!pk) return (<Screen><Header title="PDI Check" sub="Pick lists waiting for QA" onBack={onBack} /><Page>
    {lists.length === 0 ? <Text style={S.mute}>No pick list waiting for PDI.</Text> : null}
    {lists.map(k => <TouchableOpacity key={k.picklist_no} style={S.card} onPress={() => open(k)}><Text style={S.h2}>{k.picklist_no}</Text><Text style={S.mute}>{k.customer_code || k.customer} · {k.part_no} × {k.part_qty}</Text></TouchableOpacity>)}
    <Btn title="Refresh" secondary icon="refresh" onPress={load} /></Page><Toast msg={msg} /></Screen>);
  const rows = data?.lpns || []; const left = rows.filter(r => !r.pdi_result).length;
  return (<Screen><Header title={`PDI · ${pk.picklist_no}`} sub={`${pk.part_no} × ${pk.part_qty}`} onBack={() => { setPk(null); setData(null); }} /><Page>
    <Glass style={{ alignItems: 'center' }}><Ring value={`${rows.length - left}/${rows.length}`} label="LPN checked" color={left ? C.accent : C.ok} size={88} /></Glass>
    <View style={[S.row, { marginBottom: 8 }]}>{[[false, 'Scan = OK'], [true, 'Scan = REJECT']].map(([k, l]) => <TouchableOpacity key={l} onPress={() => setRejectMode(k)} style={[S.btnS, { flex: 1, marginTop: 0, backgroundColor: rejectMode === k ? (k ? C.warn : C.ok) : undefined }]}><Text style={[S.btnSText, rejectMode === k ? { color: '#fff' } : null]}>{l}</Text></TouchableOpacity>)}</View>
    <View style={S.card}>{rejectMode ? <TextInput style={S.input} placeholder="Defect / reason" value={remarks} onChangeText={setRemarks} /> : null}<ScanInput onScan={c => mark(c, rejectMode ? 'REJECT' : 'OK')} placeholder="Scan LPN (or pallet = all its LPN)" /></View>
    {rows.map(r => <View key={r.lpn_no} style={[S.card, { paddingVertical: 8, marginBottom: 6, flexDirection: 'row', alignItems: 'center' }]}><View style={{ flex: 1 }}><Text style={{ fontWeight: '600' }}>{r.lpn_no} × {r.qty}</Text><Text style={S.mute}>{r.pallet_no}{r.pdi_remarks ? ' · ' + r.pdi_remarks : ''}</Text></View>{r.pdi_result ? <Pill s={r.pdi_result} /> : <Text style={S.mute}>pending</Text>}</View>)}
    <Btn title="Complete PDI → EBS sub-inventory → SO" icon="checkmark-done-outline" disabled={left > 0 || !rows.length} onPress={complete} color={C.ok} />
    <Text style={[S.mute, { marginTop: 6 }]}>OK LPNs move to the customer/part sub-inventory and rejects to the reject sub-inventory by EBS API, each confirmed twice (EBS accepted + on-hand verified). The SO is created only after that.</Text>
  </Page><Toast msg={msg} /></Screen>);
}

export function Misses({ onBack }) {
  const [rows, setRows] = useState([]); const [msg, toast] = useToast();
  const load = async () => { try { setRows(await api('/scan-misses')); } catch (e) { toast(e.message, 'err'); } };
  useEffect(() => { load(); }, []);
  return (<Screen><Header title="Missed Scans" sub="Open alerts for this plant" onBack={onBack} /><Page>
    {rows.length === 0 ? <Text style={S.mute}>No open missed scans 👍</Text> : null}
    {rows.map(r => <View key={r.id} style={S.card}><View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{r.missed_point.replace(/_/g, ' ')}</Text><Pill s={r.action} /></View>
      <Text style={{ marginTop: 4 }}>{r.message}</Text><Text style={S.mute}>{(r.ts || '').slice(0, 16).replace('T', ' ')} · found at {r.detected_at} by {r.user_id} · should scan: {r.responsible_role || '-'}</Text></View>)}
    <Btn title="Refresh" secondary icon="refresh" onPress={load} /></Page><Toast msg={msg} /></Screen>);
}
