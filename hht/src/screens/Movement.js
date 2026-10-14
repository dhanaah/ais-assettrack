// Internal movement, other-plant receipt, PDI and missed-scan view. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, TextInput } from 'react-native';
import { S, C, Btn, Page, Header, ScanInput, Pill, useToast, Toast, Glass, Ring, Screen, Segmented, Empty, ListRow } from '../ui/kit';
import { enqueue, setPalletLocal, logActivity, resolveTag, listPicklists, listSlips, getLpn } from '../lib/db';
import { validateMove, isCard, isPalletQr } from '../lib/rules';
import { api } from '../lib/api';
import { state as sync, syncNow, pushAndResult } from '../lib/sync';
import { fDT, fTimeS } from '../lib/when';

// [key, title, sub, to zone, load, scan]: empty pallets = pallet QR (Yard staff); loaded = pallet card (FGWH / Packing)
const ROUTES = [
  ['PRODUCTION', 'Empty pallets to Production', 'Pallet Yard → Production · scan the pallet QR', 'PRODUCTION', 'EMPTY', 'QR'],
  ['PACKING_E', 'Empty pallets to Packing', 'Pallet Yard → Packing · scan the pallet QR', 'PACKING', 'EMPTY', 'QR'],
  ['YARD', 'Empty pallets back to Yard', 'From Production / FGWH / Packing · scan the pallet QR', 'YARD', 'EMPTY', 'QR'],
  ['FGWH', 'Production → FGWH', 'Loaded with finished goods · scan the pallet card', 'FGWH', 'LOADED', 'CARD'],
  ['PACKING', 'Production → Packing', 'Loaded with finished goods · scan the pallet card', 'PACKING', 'LOADED', 'CARD'],
];

const AlertBox = ({ text, onClose }) => text ? (
  <TouchableOpacity onPress={onClose} style={{ backgroundColor: C.warn, borderRadius: 12, padding: 10, marginBottom: 8 }}>
    <Text style={{ color: '#fff', fontWeight: '700' }}>⚠ {text}</Text><Text style={{ color: '#fff', fontSize: 11 }}>tap to dismiss · recorded in Missed Scans</Text></TouchableOpacity>) : null;

export function Move({ onBack, preset }) {     // preset: open one route straight from the home button
  const [route, setRoute] = useState(preset ? ROUTES.find((r) => r[0] === preset) || null : null); const [done, setDone] = useState([]); const [alert, setAlert] = useState(null); const [msg, toast] = useToast();
  const onScan = async (code) => {
    const zone = route[3], load = route[4];
    if (route[5] === 'QR' && await isCard(code)) return toast('Empty pallet move: scan the pallet QR, not the pallet card', 'err');
    if (route[5] === 'CARD' && !(await isCard(code))) return toast(await isPalletQr(code) ? 'Loaded pallet move: scan the pallet card, not the pallet QR' : 'Pallet card not known - sync / upload the WMS stock', 'err');
    const v = await validateMove(code, zone);
    if (!v.ok) return toast(v.msg, v.dup ? 'warn' : 'err');
    await setPalletLocal(v.pallet.pallet_no, { zone, load, status: zone === 'PRODUCTION' && v.pallet.status === 'HELD' ? 'IN_WIP' : (zone === 'YARD' && v.pallet.status === 'IN_WIP' ? 'HELD' : v.pallet.status) });
    const id = await enqueue('PALLET_MOVE', { scanned: code, to_zone: zone, load, strict: 1 }, !sync.online);
    logActivity('PALLET_MOVE', v.pallet.pallet_no, zone);
    setDone(d => [{ p: v.pallet.pallet_no, load, t: fTimeS(new Date()) }, ...d].slice(0, 50));
    toast(`${v.pallet.pallet_no} → ${zone} (${load})`, v.warn.length ? 'warn' : 'ok');
    if (v.warn.length) setAlert(v.warn.join('\n'));
    const r = await pushAndResult(id);
    if (r.status === 'REJECTED') { setAlert('Server rejected: ' + r.result); toast(r.result, 'err'); syncNow({ full: true }).catch(() => {}); }
    else if (r.status === 'EXCEPTION') setAlert(r.result);
  };
  if (!route) return (<Screen><Header title="Internal Movement" sub="Select the route" onBack={onBack} /><Page>
    {ROUTES.map(r => <TouchableOpacity key={r[0]} style={S.card} onPress={() => { setRoute(r); setDone([]); setAlert(null); }}>
      <Text style={S.h2}>{r[1]}</Text><Text style={S.mute}>{r[2]}</Text></TouchableOpacity>)}
    <Text style={S.mute}>Pallet Yard holds EMPTY pallets only. A skipped step is detected at the next scan and recorded.</Text></Page><Toast msg={msg} /></Screen>);
  return (<Screen><Header title={route[1]} sub={route[2]} onBack={preset ? onBack : () => setRoute(null)} /><Page>
    <Glass style={{ alignItems: 'center' }}><Ring value={String(done.length)} label="moved this session" color={C.ok} size={84} /></Glass>
    <AlertBox text={alert} onClose={() => setAlert(null)} />
    <View style={S.card}><ScanInput onScan={onScan} placeholder={route[5] === 'QR' ? 'Scan the pallet QR' : 'Scan the pallet card'} /></View>
    {done.length === 0 ? <Empty icon="scan-outline" text="Scan the first pallet" hint="Each pallet moved in this session is listed here." /> : null}
    {done.map((d, i) => <ListRow key={i} index={done.length - i} title={d.p} sub={d.t} right={<Pill s={d.load} />} />)}
  </Page><Toast msg={msg} /></Screen>);
}

export function Receipt({ onBack, zone = 'FGWH' }) {   // other-plant material at FGWH or Packing: pallet card on a challan endorsed at the IN gate
  const [chl, setChl] = useState([]); const [ref, setRef] = useState(null); const [pin, setPin] = useState(''); const [done, setDone] = useState([]); const [alert, setAlert] = useState(null); const [msg, toast] = useToast();
  const loadChl = async () => setChl((await listSlips()).filter((s) => s.mode === 'CHM'));
  useEffect(() => { loadChl(); }, []);
  const closeChl = async () => {
    if (!sync.online) return toast('Closing needs the server; scans are saved and will sync.', 'warn');
    try { await syncNow(); const r = await api(`/slips/${encodeURIComponent(ref)}/close`, { method: 'POST', body: { supervisor_pin: pin || null } }); setPin('');
      toast(`Challan ${ref} closed: received ${r.received}${r.short?.length ? `, short ${r.short.length}` : ''}`, 'done'); logActivity('CHALLAN_CLOSE', ref, String(r.received)); setRef(null); await syncNow(); loadChl(); }
    catch (e) { setAlert(e.message); toast(e.message, 'err'); }
  };
  const onScan = async (code) => {
    if (!ref) return toast('Pick the challan first (registered at the IN gate)', 'warn');
    if (!(await isCard(code)) && (await isPalletQr(code))) return toast('Scan the pallet card, not the pallet QR', 'err');   // unknown card: the server decides
    const l = await getLpn(code.includes('.') ? code.split('.').pop().toUpperCase() : code); const pno = l?.pallet || code;
    const id = await enqueue('PLANT_RECEIPT', { scanned: code, zone, ref, strict: 1 }, !sync.online);
    if (l?.pallet) await setPalletLocal(l.pallet, { status: 'IN_WIP', zone, load: 'LOADED' });
    logActivity('PLANT_RECEIPT', pno, zone);
    setDone(d => [{ p: pno, c: code, t: fTimeS(new Date()) }, ...d]);
    toast(`${pno} received at ${zone}`);
    const r = await pushAndResult(id);
    if (r.status === 'REJECTED') { setAlert(r.result); toast(r.result, 'err'); } else if (r.status === 'EXCEPTION') setAlert(r.result);
  };
  return (<Screen><Header title={`Other-plant material · ${zone === 'PACKING' ? 'Packing' : 'FGWH'}`} sub="Pallet card on a challan endorsed at the IN gate" onBack={onBack} /><Page onRefresh={async () => { await syncNow(); loadChl(); }}>
    <AlertBox text={alert} onClose={() => setAlert(null)} />
    <Text style={S.h2}>1 · Challan (endorsed at the IN gate)</Text>
    {chl.length === 0 ? <Empty icon="document-outline" text="No material challan at the gate" hint="The IN gate scans the sending plant's challan first. Pull down to refresh." /> : null}
    {chl.map((s) => <TouchableOpacity key={s.slip_no} onPress={() => setRef(s.slip_no)} style={[S.card, { paddingVertical: 10, borderWidth: ref === s.slip_no ? 2 : 1, borderColor: ref === s.slip_no ? C.accent : C.line }]}>
      <Text style={{ fontWeight: '700', color: C.fg }}>{s.slip_no}</Text><Text style={S.mute}>From plant {s.customer} · {s.qty} pallet(s)</Text></TouchableOpacity>)}
    {ref ? <><Text style={S.h2}>2 · Scan each pallet card</Text><View style={S.card}><ScanInput onScan={onScan} placeholder="Scan the pallet card" /></View>
      <Text style={S.h2}>3 · All received</Text>
      <TextInput style={S.input} placeholder="Supervisor PIN (only if pallets are short)" value={pin} onChangeText={setPin} secureTextEntry keyboardType="number-pad" />
      <Btn title="Close challan" icon="checkmark-done-outline" onPress={closeChl} /></> : null}
    <Text style={S.mute}>Received pallets stay IN WIP at {zone === 'PACKING' ? 'Packing' : 'FGWH'}. When emptied they go to the Pallet Yard (Yard-In · Empty pallets back to Yard) and are sent home on an empty-return challan.</Text>
    {done.map((d, i) => <View key={i} style={[S.card, { paddingVertical: 8, marginBottom: 6 }]}><Text style={{ fontWeight: '600', color: C.fg }}>{d.p}</Text><Text style={S.mute}>card {d.c} · {d.t}</Text></View>)}
  </Page><Toast msg={msg} /></Screen>);
}

export function Pdi({ onBack, packing = false }) {
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
  if (!pk) return (<Screen><Header title={packing ? 'PDI Check · Packing' : 'PDI Check'} sub="Pick lists waiting for QA · scan the pallet card" onBack={onBack} /><Page>
    {lists.length === 0 ? <Empty text="No pick list waiting for PDI" hint="Lists arrive here after the dock confirms them." /> : null}
    {lists.map(k => <TouchableOpacity key={k.picklist_no} style={S.card} onPress={() => open(k)}><Text style={S.h2}>{k.picklist_no}</Text><Text style={S.mute}>{k.customer_code || k.customer} · {k.part_no} × {k.part_qty}</Text></TouchableOpacity>)}
    <Btn title="Refresh" secondary icon="refresh" onPress={load} /></Page><Toast msg={msg} /></Screen>);
  const rows = data?.lpns || []; const left = rows.filter(r => !r.pdi_result).length;
  return (<Screen><Header title={`PDI · ${pk.picklist_no}`} sub={`${pk.part_no} × ${pk.part_qty}`} onBack={() => { setPk(null); setData(null); }} /><Page>
    <Glass style={{ alignItems: 'center' }}><Ring value={`${rows.length - left}/${rows.length}`} label="LPN checked" color={left ? C.accent : C.ok} size={88} /></Glass>
    <Segmented options={[[false, 'Scan = OK', C.ok], [true, 'Scan = REJECT', C.warn]]} value={rejectMode} onChange={setRejectMode} />
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
    {rows.length === 0 ? <Empty text="No open missed scans" hint="Every scan point was followed." /> : null}
    {rows.map(r => <View key={r.id} style={S.card}><View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{r.missed_point.replace(/_/g, ' ')}</Text><Pill s={r.action} /></View>
      <Text style={{ marginTop: 4 }}>{r.message}</Text><Text style={S.mute}>{fDT(r.ts)} · found at {r.detected_at} by {r.user_id} · should scan: {r.responsible_role || '-'}</Text></View>)}
    <Btn title="Refresh" secondary icon="refresh" onPress={load} /></Page><Toast msg={msg} /></Screen>);
}
