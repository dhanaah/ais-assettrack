// Customer mode (HHT at the customer's site, used by Customer Staff who sign in with their own user):
//  * Receive delivery - scan each pallet while unloading an AIS vehicle (works offline, sent later)
//  * Return slip (Option A) - scan the empty pallets -> slip with AIS-signed QR -> portable printer. Talks to AIS directly on the AIS network, through the internet address otherwise (see custapi).
// Developed by DT
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { View, Text, TextInput, TouchableOpacity, Alert, AppState } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import qrcode from 'qrcode-generator';
import { S, C, T, Btn, Header, Page, Screen, ScanInput, Pill, useToast, Toast, Glass, Ring, Empty, Footer, ButtonGroup } from '../ui/kit';
import { ext, findRoute, getPairing, getRoute, createSlip, sendPending, outbox, history, refreshSlip, unpair, parsePairing, savePairing, setInternetAddress, refreshMe, canPrintOffline, loadStaff, staffLogin, staffLogout, getStaff, staffCan, incoming, receive, sendReceipts } from '../lib/custapi';
import { VehiclePicker } from '../ui/vehicle';
import Setup from './Setup';
import { parsePalletQr, kv } from '../lib/db';
import { printSlip, canPrint, testPrint } from '../lib/printer';
import { feedback } from '../lib/feedback';
import { fDT, fDate } from '../lib/when';
import { Settings } from './Misc';
import { vpnActive, openVpnApp } from '../lib/vpn';

/** QR drawn with plain views (dark runs merged per row) - shown so the gate can scan it from the screen too. */
export function QrView({ text, size = 220 }) {
  if (!text) return null;
  const q = qrcode(0, 'M'); q.addData(text); q.make();
  const n = q.getModuleCount(); const cell = size / (n + 4);
  const rows = [];
  for (let r = 0; r < n; r++) {
    const runs = []; let c = 0;
    while (c < n) { if (q.isDark(r, c)) { const s = c; while (c < n && q.isDark(r, c)) c++; runs.push([s, c - s]); } else c++; }
    rows.push(<View key={r} style={{ height: cell, width: n * cell }}>{runs.map(([s, w], i) => <View key={i} style={{ position: 'absolute', left: s * cell, width: w * cell + 0.5, height: cell + 0.5, backgroundColor: '#000' }} />)}</View>);
  }
  return <View style={{ width: size, height: size, backgroundColor: '#fff', padding: cell * 2, alignSelf: 'center', borderRadius: 8 }}>{rows}</View>;
}


/** Connection to AIS: green pill when online; red / amber card with "Connect VPN" (opens FortiClient) when not. */
function NetCard({ route, pend, onRecheck, toast, style }) {
  const [vpn, setVpn] = useState(vpnActive);
  useEffect(() => { setVpn(vpnActive()); }, [route]);
  const vpnCheck = useCallback(() => setVpn(vpnActive()), []); useOnResume(vpnCheck, 1500);   // route may stay "none" while the VPN came up
  const recheck = () => { setVpn(vpnActive()); onRecheck && onRecheck(); };
  if (route === undefined) return (<View style={[S.row, { alignSelf: 'flex-start', marginHorizontal: 14, marginTop: 10, backgroundColor: C.input, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 }, style]}>
    <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: '#94a3b8' }} /><Text style={{ fontWeight: '700', color: C.fg }}>Checking…</Text></View>);
  if (route) return (<TouchableOpacity onPress={recheck} style={[{ backgroundColor: '#16a34a', paddingVertical: 7, paddingHorizontal: 14, marginHorizontal: 14, marginTop: 10, borderRadius: 999, flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start' }, style]}>
    <Ionicons name={vpn ? 'lock-closed-outline' : route.kind === 'LAN' ? 'business-outline' : 'globe-outline'} size={14} color="#fff" />
    <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12.5 }}>Online{vpn ? ' · via VPN' : ''}{pend ? ` · ${pend} waiting` : ''} · tap to recheck</Text></TouchableOpacity>);
  const open = async () => { const r = await openVpnApp();
    if (r === 'store') toast('FortiClient VPN is not installed - install it, then add the AIS VPN connection', 'warn');
    else if (r === 'none') toast('FortiClient VPN is not installed on this HHT - ask AIS IT', 'err'); };
  const amber = vpn;
  return (<View style={[{ marginHorizontal: 14, marginTop: 10, borderRadius: 14, padding: 12, borderWidth: 1.5, backgroundColor: amber ? '#fffbeb' : '#fef2f2', borderColor: amber ? '#fcd34d' : '#fca5a5' }, style]}>
    <View style={[S.row, { gap: 6 }]}><Ionicons name={amber ? 'warning' : 'cloud-offline'} size={18} color={amber ? '#b45309' : '#b91c1c'} />
      <Text style={{ flex: 1, fontWeight: '800', fontSize: 14, color: amber ? '#b45309' : '#b91c1c' }}>{amber ? 'VPN connected – AIS server not answering' : `Not connected to AIS${pend ? ` · ${pend} waiting` : ''}`}</Text></View>
    <Text style={{ fontSize: 12, color: '#334155', marginTop: 4, marginBottom: 10 }}>{amber ? 'Ask AIS IT to check the VPN account can reach AssetTrack. Slips still print offline.' : 'VPN is off. Connect the VPN to send slips now. Slips still print offline.'}</Text>
    <View style={[S.row, { gap: 8 }]}>
      <TouchableOpacity onPress={open} style={{ flex: 1, backgroundColor: '#2563eb', borderRadius: 10, paddingVertical: 10, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 6 }}>
        <Ionicons name="lock-closed" size={15} color="#fff" /><Text style={{ color: '#fff', fontWeight: '700' }}>{amber ? 'Open VPN' : 'Connect VPN'}</Text></TouchableOpacity>
      <TouchableOpacity onPress={recheck} style={{ flex: 1, backgroundColor: '#e2e8f0', borderRadius: 10, paddingVertical: 10, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 6 }}>
        <Ionicons name="refresh" size={15} color="#0f172a" /><Text style={{ color: '#0f172a', fontWeight: '700' }}>Recheck</Text></TouchableOpacity></View></View>);
}
/** Recheck when the operator comes back to AssetTrack (e.g. after connecting FortiClient). */
function useOnResume(fn, delay = 0) {
  useEffect(() => { let st = AppState.currentState; let t = null;
    const sub = AppState.addEventListener('change', (n) => { if (/inactive|background/.test(String(st)) && n === 'active') { clearTimeout(t); t = setTimeout(fn, delay); } st = n; });
    return () => { clearTimeout(t); sub.remove(); }; }, [fn, delay]);
}

// ---------------------------------------------------------------- pairing (from the Login screen)
export function PairDevice({ onBack, onPaired }) {
  const [msg, toast] = useToast(); const [found, setFound] = useState(null); const [busy, setBusy] = useState(false); const [test, setTest] = useState(null);
  const onScan = async (code) => {
    const j = parsePairing(code);
    if (!j) { feedback('err'); return toast('Not an AssetTrack pairing QR - open Customers > HHT pairing on the AIS web', 'err'); }
    feedback('ok'); setFound(j); setTest(null);
  };
  const save = async () => {
    setBusy(true);
    try { await savePairing(found); const r = await findRoute(true).catch((e) => ({ err: e.message })); setTest(r);
      if (r && !r.err) { await ext('/me'); toast('Paired with AIS', 'done'); setTimeout(onPaired, 600); }
      else { toast('Paired - no network to AIS right now; slips wait on the HHT and go when online', 'warn'); setTimeout(onPaired, 2500); } }
    catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  return (<Screen><Header title="Customer device" sub="Pair this HHT for Option A return slips" onBack={onBack} /><Page>
    <View style={S.card}><Text style={S.h2}>Scan the pairing QR</Text>
      <Text style={S.mute}>AIS opens Customers › HHT pairing on the AssetTrack web and shows a QR for this customer. Scan it here once.</Text>
      <ScanInput onScan={onScan} placeholder="Scan pairing QR" /></View>
    {found ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.ok }]}>
      <Text style={S.h2}>{found.n}</Text>
      <Text style={S.body}>Customer {found.c} · AIS plant {found.p} · device "{found.d}"</Text>
      <Text style={[S.mute, { marginTop: 6 }]}>AIS network: {(found.lan || []).length ? 'set' : '—'}</Text>
      <Text style={S.mute}>Internet: {found.wan ? 'set' : 'not set yet (AIS IT publishes it)'}</Text>
      <Btn title="Pair this HHT" icon="link-outline" onPress={save} busy={busy} />
      {test?.err ? <Text style={[S.mute, { color: C.warn }]}>{test.err}</Text> : null}
    </View> : null}
    <Footer /></Page><Toast msg={msg} /></Screen>);
}

// ---------------------------------------------------------------- customer app
export default function CustomerApp({ deviceId, onUnpaired, onTheme, onUi }) {
  const [screen, setScreen] = useState('home'); const pair = getPairing(); const [staff, setStaff] = useState(undefined);
  useEffect(() => { loadStaff().then((x) => setStaff(x || null)).catch(() => setStaff(null)); }, []);
  const back = () => setScreen('home');
  if (staff === undefined) return null;
  if (!staff) {
    if (screen === 'setup') return <Setup customer onBack={() => setScreen('home')} />;
    return <StaffLogin onDone={(x) => { setStaff(x); setScreen('home'); }} onSetup={() => setScreen('setup')} />;
  }
  if (screen === 'receive') return <Receive onBack={back} />;
  if (screen === 'new') return <NewSlip onBack={back} onDone={() => setScreen('slips')} />;
  if (screen === 'holding') return <Holding onBack={back} />;
  if (screen === 'slips') return <Slips onBack={back} />;
  if (screen === 'setup') return <Setup customer onBack={() => setScreen('settings')} />;
  if (screen === 'settings') return <CustSettings onBack={back} onSetup={() => setScreen('setup')} onLogout={async () => { await staffLogout(); setStaff(null); setScreen('home'); }} deviceId={deviceId} onUnpaired={onUnpaired} onTheme={onTheme} onUi={onUi} />;
  return <CustHome pair={pair} nav={setScreen} />;
}

function CustHome({ pair, nav }) {
  const [route, setRoute] = useState(getRoute() || undefined); const [pend, setPend] = useState(0); const [held, setHeld] = useState(null); const [me, setMe] = useState(null); const [msg, toast] = useToast();
  const refresh = useCallback(async (force) => {
    try { const r = await findRoute(force); setRoute(r); } catch (e) { setRoute(null); }
    const sent = await sendPending().catch(() => []); if (sent.length) toast(`${sent.length} waiting slip(s) sent`, 'done');
    const rc = await sendReceipts().catch(() => 0); if (rc) toast(`${rc} waiting receipt(s) sent`, 'done');
    setPend((await outbox()).length);
    try { setMe(await refreshMe()); const h = await ext('/holding'); setHeld(h); } catch (e) { if (e.status === 401) toast(e.message, 'err'); }
  }, []);
  useEffect(() => { refresh(true); const t = setInterval(() => refresh(false), 60000); return () => clearInterval(t); }, []);
  const resume = useCallback(() => refresh(true), [refresh]); useOnResume(resume, 1500);   // VPN takes a moment after FortiClient
  const overdue = held ? held.pallets.filter((p) => p.overdue).length : 0;
  const [inc, setInc] = useState(0);
  useEffect(() => { kv.get('cust_incoming').then((l) => setInc((l || []).length)).catch(() => {}); }, [route, held]);
  const can = (it) => !it[3] || staffCan(it[3]);
  const CGROUPS = [
    { key: 'cin', title: 'Inward', sub: 'AIS vehicles unloading at our site', icon: 'download-outline', grad: ['#f59e0b', '#c2410c'], items: [
      ['receive', 'Receive delivery', 'Scan each pallet while unloading', 'CUST_RECEIVE', 'download-outline', 'inc'] ] },
    { key: 'cret', title: 'Return to AIS', sub: 'Empty pallets back to AIS · Option A slip', icon: 'return-up-back-outline', grad: ['#a855f7', '#7e22ce'], items: [
      ['new', 'Return empty pallets', 'Scan pallets, print the signed return slip', 'CUST_RETURN', 'document-text-outline'],
      ['slips', 'Our return slips', pend ? `${pend} waiting to send` : 'Status, reprint', null, 'list-outline', 'pend'] ] },
    { key: 'coth', title: 'Others', sub: 'Pallets at our site, settings', icon: 'apps-outline', grad: ['#0ea5e9', '#2563eb'], items: [
      ['holding', 'Pallets with us', held ? `${held.count} pallet(s)${overdue ? ` · ${overdue} overdue` : ''}` : 'AIS pallets at this site', null, 'cube-outline'],
      ['settings', 'Settings', 'Printer, vehicles · sign out', null, 'settings-outline'] ] },
  ];
  return (<Screen><Header logo sub={`${getStaff()?.name || ''} · ${me?.name || pair?.n || ''}`} />
    <NetCard route={route} pend={pend} onRecheck={() => refresh(true)} toast={toast} />
    <Page onRefresh={() => refresh(true)}>
      <Glass style={{ flexDirection: 'row', justifyContent: 'space-around' }}>
        <Ring value={held ? String(held.count) : '—'} label="AIS pallets here" color={C.accent} size={88} />
        <Ring value={held ? String(overdue) : '—'} label="over holding limit" color={overdue ? C.warn : C.ok} size={88} />
      </Glass>
      {CGROUPS.map((g) => <ButtonGroup key={g.key} g={g} items={g.items.filter(can)} n={{ inc, pend }} nav={nav} />)}
      <Text style={{ color: C.mute, opacity: 0.35, fontSize: 10, textAlign: 'center', marginTop: 14 }}>Device "{pair?.d}" · customer {pair?.c}</Text>
      <Footer /></Page><Toast msg={msg} /></Screen>);
}

function NewSlip({ onBack, onDone }) {
  const [list, setList] = useState([]); const [veh, setVeh] = useState(''); const [dc, setDc] = useState(''); const [drv, setDrv] = useState(''); const [mob, setMob] = useState('');
  const [busy, setBusy] = useState(false); const [done, setDone] = useState(null); const [msg, toast] = useToast(); const pair = getPairing();
  const listRef = useRef(list); listRef.current = list;          // latest list (pallets scanned while the confirm box is open)
  const onScan = async (code) => {
    const q = parsePalletQr(code); const shown = q?.pallet_no || code.trim();
    if (listRef.current.some((x) => x.shown === shown)) { feedback('warn'); return toast(`${shown} already on this slip`, 'warn'); }
    // no route to AIS right now: do not wait for the ledger check - the slip works without it
    if (!getRoute()) { const row = { scanned: code.trim(), shown, state: 'unchecked' }; listRef.current = [row, ...listRef.current]; setList((l) => [row, ...l]); feedback('ok'); return; }
    const row = { scanned: code.trim(), shown, state: 'checking' };
    listRef.current = [row, ...listRef.current]; setList((l) => [row, ...l]);
    try {
      const r = await ext('/validate', { method: 'POST', body: { tags: [code.trim()] }, timeout: 8000 }); const v = r.results[0];
      setList((l) => l.map((x) => x.shown === shown ? { ...x, state: v.ok ? 'ok' : 'warn', pallet_no: v.pallet_no || shown, reason: v.reason } : x));
      feedback(v.ok ? 'ok' : 'warn'); if (!v.ok) toast(`${shown}: ${v.reason}`, 'warn');
    } catch (e) { setList((l) => l.map((x) => x.shown === shown ? { ...x, state: 'unchecked' } : x)); feedback('ok'); if (!e.offline) toast(e.message, 'err'); }
  };
  const submit = async () => {
    if (!list.length) return toast('Scan the pallets first', 'err');
    if (!veh.trim()) return toast('Select or type the vehicle number', 'err');
    const warn = list.filter((x) => x.state === 'warn').length;
    const ok = await new Promise((res) => Alert.alert('Create return slip', `${list.length} pallet(s) on ${veh.toUpperCase()}${warn ? `\n${warn} pallet(s) not in your AIS ledger - AIS will check them at the gate` : ''}`, [{ text: 'Cancel', onPress: () => res(false) }, { text: 'Create slip', onPress: () => res(true) }]));
    if (!ok) return;
    setBusy(true);
    try {
      const r = await createSlip({ pallets: listRef.current.map((x) => x.scanned).reverse(), vehicle_no: veh.trim(), customer_challan_no: dc.trim(), customer_challan_date: new Date().toISOString(), driver_name: drv.trim() || null, driver_mobile: mob.trim() || null });
      if (r.sent) { feedback('done'); setDone(r.slip); doPrint(r.slip); }
      else if (r.slip) { feedback('done'); setDone(r.slip); doPrint(r.slip); }          // no network: printed with this HHT's own signed QR
      else { feedback('warn'); Alert.alert('Saved on this HHT', 'There is no network to AIS and this HHT has not got its offline signing key yet (connect once). The slip is sent automatically when online; print it from "Our return slips" then.', [{ text: 'OK', onPress: onDone }]); }
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const doPrint = async (s) => {
    try { const r = await printSlip(toPrint(s, pair), { code: pair?.p, name: 'AIS ' + (pair?.p || '') }, 2, s.qr_payload); toast(r.printed ? 'Slip printed (2 copies)' : 'No printer - show the QR on screen at the AIS gate', r.printed ? 'done' : 'warn'); }
    catch (e) { toast('Print failed: ' + e.message, 'err'); }
  };
  if (done) return (<Screen><Header title="Return slip ready" sub={`${done.slip_no} · ${done.vehicle_no}`} onBack={onDone} /><Page>
    <View style={[S.card, { alignItems: 'center' }]}><QrView text={done.qr_payload} size={230} /><Text style={[S.h2, { marginTop: 10 }]}>{done.slip_no}</Text>
      <Text style={S.mute}>{done.declared_qty} pallet(s) · vehicle {done.vehicle_no}{done.customer_challan_no ? ` · your DC ${done.customer_challan_no}` : ''}</Text>
      {done.offline ? <Text style={[S.body, { marginTop: 8, color: C.amber, textAlign: 'center', fontWeight: '700' }]}>No network - slip printed with this HHT's signed QR. AIS accepts it at the gate; the HHT sends the details when it is online.</Text> : null}
      <Text style={[S.body, { marginTop: 8, textAlign: 'center' }]}>Hand the printed slip to the driver. The AIS IN gate scans this QR.</Text></View>
    {done.warnings?.length ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.amber }]}>{done.warnings.map((w, i) => <Text key={i} style={S.mute}>• {w}</Text>)}</View> : null}
    <Btn title="Print again" icon="print-outline" onPress={() => doPrint(done)} />
    <Btn title="Done" secondary icon="checkmark-outline" onPress={onDone} />
  </Page><Toast msg={msg} /></Screen>);
  return (<Screen><Header title="New return slip (Option A)" sub={`${list.length} pallet(s) scanned`} onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan pallet QR / tag" />
      {list.map((x, i) => <TouchableOpacity key={x.shown} onLongPress={() => setList((l) => l.filter((y) => y.shown !== x.shown))} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 6, borderBottomWidth: 0.5, borderBottomColor: '#cbd5e1' }}>
        <Text style={[S.mute, { width: 28 }]}>{list.length - i}</Text><Text style={{ flex: 1, fontWeight: '700', color: C.fg }}>{x.pallet_no || x.shown}</Text>
        <Pill s={x.state === 'ok' ? 'AVAILABLE' : x.state === 'warn' ? 'HELD' : 'IN_RETURN'} label={x.state === 'ok' ? 'OK' : x.state === 'warn' ? 'CHECK' : 'WAIT'} /><Text style={[S.mute, { marginLeft: 6, fontSize: 11 }]}>{x.state === 'ok' ? 'in ledger' : x.state === 'warn' ? 'check' : x.state === 'checking' ? '…' : 'not checked'}</Text></TouchableOpacity>)}
      {list.length ? <Text style={[S.mute, { marginTop: 4 }]}>Long-press a pallet to remove it.</Text> : null}</View>
    <View style={S.card}>
      <VehiclePicker value={veh} onChange={setVeh} />
      <Text style={S.mute}>Your delivery challan (DC) number - if you have one</Text><TextInput style={S.input} value={dc} onChangeText={setDc} autoCapitalize="characters" />
      <Text style={S.mute}>Driver name</Text><TextInput style={S.input} value={drv} onChangeText={setDrv} />
      <Text style={S.mute}>Driver mobile</Text><TextInput style={S.input} value={mob} onChangeText={setMob} keyboardType="phone-pad" />
      <Btn title={`Create slip · ${list.length} pallet(s)`} icon="checkmark-circle-outline" onPress={submit} busy={busy} color={list.length && veh ? C.ok : C.accent} />
      <Text style={[S.mute, { textAlign: 'center', marginTop: 6 }]}>Return slip number is generated automatically.</Text>
      {!getRoute() ? <Text style={[S.mute, { marginTop: 6, color: canPrintOffline() ? C.ok : C.amber, textAlign: 'center' }]}>{canPrintOffline() ? 'No network is fine: the slip prints with this HHT\'s signed QR and is sent later.' : 'Connect once to AIS so this HHT can print slips without network.'}</Text> : null}</View>
  </Page><Toast msg={msg} /></Screen>);
}

const toPrint = (s, pair) => ({ slip_no: s.slip_no, mode: 'A', date: fDT(s.created_at), customer_code: s.customer, customer_name: pair?.n || '', vehicle_no: s.vehicle_no,
  customer_challan_no: s.customer_challan_no, pallets: (s.pallets || []).map((p) => p.pallet_no), declared_qty: s.declared_qty, provisional: !!s.offline });

function Holding({ onBack }) {
  const [h, setH] = useState(null); const [msg, toast] = useToast();
  const load = async () => { try { setH(await ext('/holding')); } catch (e) { toast(e.message, 'err'); } };
  useEffect(() => { load(); }, []);
  return (<Screen><Header title="AIS pallets with us" sub={h ? `${h.count} pallet(s) · holding limit ${h.holding_limit_days || '—'} days` : ''} onBack={onBack} /><Page onRefresh={load}>
    {h && !h.pallets.length ? <Empty text="No AIS pallets recorded at your site" /> : null}
    {(h?.pallets || []).map((p) => <View key={p.pallet_no} style={[S.card, { paddingVertical: 8, marginBottom: 6, borderLeftWidth: p.overdue ? 5 : 0, borderLeftColor: C.warn }]}>
      <View style={S.row}><Text style={{ flex: 1, fontWeight: '700', color: C.fg }}>{p.pallet_no}</Text><Text style={{ fontWeight: '700', color: p.overdue ? C.warn : C.ok }}>{p.days ?? '—'} days</Text></View>
      <Text style={S.mute}>{p.type || ''} · challan {p.challan || '—'} · sent {fDate(p.dispatched)}</Text></View>)}
  </Page><Toast msg={msg} /></Screen>);
}

function Slips({ onBack }) {
  const [rows, setRows] = useState([]); const [pend, setPend] = useState([]); const [msg, toast] = useToast(); const pair = getPairing();
  const load = async (net) => {
    if (net) { const sent = await sendPending().catch(() => []); if (sent.length) toast(`${sent.length} waiting slip(s) sent`, 'done'); }
    const h = await history(); setPend(await outbox()); setRows(h);
    if (net) for (const s of h.slice(0, 15).filter((x) => x.status !== 'CLOSED')) { try { await refreshSlip(s.slip_no); } catch (e) { break; } }
    setRows(await history());
  };
  useEffect(() => { load(true); }, []);
  return (<Screen><Header title="Our return slips" sub={`${rows.length} slip(s)${pend.length ? ` · ${pend.length} waiting` : ''}`} onBack={onBack} /><Page onRefresh={() => load(true)}>
    {pend.map((p) => <View key={p.client_ref} style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.amber }]}><Text style={S.h2}>Waiting to send · {p.body.pallets.length} pallet(s)</Text>
      <Text style={S.mute}>{p.body.vehicle_no}{p.body.customer_challan_no ? ` · DC ${p.body.customer_challan_no}` : ''} · made {fDT(p.created)}</Text><Text style={[S.mute, { color: C.warn }]}>{p.last_error}</Text></View>)}
    {!rows.length && !pend.length ? <Empty icon="document-text-outline" text="No return slips from this HHT yet" /> : null}
    {rows.map((s) => <View key={s.slip_no} style={S.card}>
      <View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{s.slip_no}</Text><Pill s={s.status === 'CLOSED' ? 'AVAILABLE' : s.status === 'OPEN' ? 'IN_RETURN' : 'ALLOCATED'} /></View>
      <Text style={S.mute}>{s.declared_qty} pallet(s) · {s.vehicle_no}{s.customer_challan_no ? ` · DC ${s.customer_challan_no}` : ''} · {fDT(s.created_at)} · {s.status}</Text>
      <Btn title="Print slip" secondary icon="print-outline" onPress={async () => { try { const r = await printSlip(toPrint(s, pair), { code: pair?.p, name: 'AIS ' + (pair?.p || '') }, 1, s.qr_payload); toast(r.printed ? 'Printed' : 'No printer selected', r.printed ? 'done' : 'warn'); } catch (e) { toast(e.message, 'err'); } }} /></View>)}
  </Page><Toast msg={msg} /></Screen>);
}

function CustSettings({ onBack, onSetup, onLogout, deviceId, onUnpaired, onTheme, onUi }) {
  const pair = getPairing(); const [wan, setWan] = useState(''); const [msg, toast] = useToast();
  return (<View style={{ flex: 1 }}>
    <Settings onBack={onBack} onSetup={onSetup} deviceId={deviceId} onTheme={onTheme} onUi={onUi} customer
      extra={<View style={S.card}><Btn title={`Sign out (${getStaff()?.name || ''})`} secondary icon="log-out-outline" onPress={onLogout} /><Text style={[S.h2, { marginTop: 12 }]}>AIS connection</Text>
        <Text style={S.mute}>Customer {pair?.c} · AIS plant {pair?.p} · device "{pair?.d}"</Text>
        <Text style={[S.mute, { marginTop: 8 }]}>Internet address (from AIS IT)</Text>
        <TextInput style={S.input} value={wan} onChangeText={setWan} autoCapitalize="none" autoCorrect={false} secureTextEntry placeholder={pair?.wan ? 'set ✓ - type to change' : 'from AIS IT'} />
        <Btn title="Save address" secondary icon="save-outline" onPress={async () => { try { await setInternetAddress(wan); } catch (e) { return toast(e.message, 'err'); } try { await findRoute(true); toast('Online', 'done'); } catch (e) { toast(e.message, 'warn'); } }} />
        <Btn title="Remove pairing" secondary icon="unlink-outline" onPress={() => Alert.alert('Remove pairing', 'This HHT will stop working for return slips until AIS pairs it again. Slips still waiting must be sent first.', [{ text: 'Cancel' }, { text: 'Remove', style: 'destructive', onPress: async () => { try { await unpair(); onUnpaired(); } catch (e) { feedback('err'); Alert.alert('Cannot remove pairing yet', e.message); } } }])} /></View>} />
    <Toast msg={msg} /></View>);
}

// ---------------------------------------------------------------- customer staff sign-in
function StaffLogin({ onDone, onSetup }) {
  const pair = getPairing(); const [u, setU] = useState(''); const [p, setP] = useState(''); const [busy, setBusy] = useState(false); const [route, setRoute] = useState(undefined); const [msg, toast] = useToast();
  const recheck = useCallback(() => { setRoute(undefined); findRoute(true).then(setRoute).catch(() => setRoute(null)); }, []);
  useEffect(() => { recheck(); }, []);
  useOnResume(recheck, 1500);
  const go = async () => { if (!u.trim() || !p) return toast('Enter user ID and password', 'warn'); setBusy(true);
    try { const r = await staffLogin(u, p); toast(r.offline ? 'Signed in (no network)' : 'Signed in', 'done'); onDone(r); } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); } };
  return (<Screen><Header logo sub={`${pair?.n || pair?.c || ''} · customer HHT`} /><Page>
    <NetCard route={route} onRecheck={recheck} toast={toast} style={{ marginHorizontal: 0, marginTop: 0, marginBottom: 10 }} />
    <View style={S.card}><Text style={S.h2}>Customer staff sign-in</Text>
      <Text style={S.mute}>User ID (given by AIS)</Text><TextInput style={S.input} value={u} onChangeText={setU} autoCapitalize="none" autoCorrect={false} />
      <Text style={S.mute}>Password</Text><TextInput style={S.input} value={p} onChangeText={setP} secureTextEntry onSubmitEditing={go} />
      <Btn title="Sign in" icon="log-in-outline" busy={busy} onPress={go} /></View>
    <Btn title="Setup · Printer · Vehicles" secondary icon="construct-outline" onPress={onSetup} />
    <Btn title="Test printer" secondary icon="print-outline" onPress={async () => { if (!(await canPrint())) { toast('Choose the printer in Setup first', 'warn'); return onSetup(); } try { await testPrint({ code: pair?.p }); toast('Test page sent', 'done'); } catch (e) { toast('Printer not working: ' + e.message, 'err'); } }} />
    <Footer credit /></Page><Toast msg={msg} /></Screen>);
}

// ---------------------------------------------------------------- receive an AIS delivery (unloading)
function Receive({ onBack }) {
  const [list, setList] = useState([]); const [sel, setSel] = useState(null); const [scans, setScans] = useState([]); const [busy, setBusy] = useState(false); const [done, setDone] = useState(null); const [msg, toast] = useToast();
  const load = async (refresh = true) => { try { setList(await incoming(refresh)); } catch (e) { toast(e.message, 'err'); } };
  useEffect(() => { load(false).then(() => load(true)); }, []);
  const scansRef = useRef(scans); scansRef.current = scans;      // latest scans for back-to-back scanner reads
  const pick = (d) => { setSel(d); setScans([]); setDone(null); };
  const onGcs = (code) => { const q = String(code).split('|'); const no = code.startsWith('AIS1|GCS|') ? q[2] : code.trim().toUpperCase();
    const d = list.find((x) => x.gcs_no === no || x.challan_no === no); if (!d) return toast(`No AIS delivery ${no} for you (pull down to refresh)`, 'warn'); pick(d); };
  const expected = sel ? sel.pallets.map((x) => x.pallet_no) : [];
  const onScan = (code) => {
    const pn = parsePalletQr(code)?.pallet_no || String(code).trim().toUpperCase();
    if (scansRef.current.some((x) => x.pn === pn)) { feedback('warn'); return toast('Already scanned', 'warn'); }
    const on = expected.includes(pn); feedback(on ? 'ok' : 'warn'); if (!on) toast(`${pn} is not on this delivery - kept as extra`, 'warn');
    const row = { code, pn, on }; scansRef.current = [row, ...scansRef.current]; setScans((s) => [row, ...s]);
  };
  const finish = async () => {
    if (!scans.length) return toast('Scan the pallets first', 'err');
    setBusy(true);
    try { const r = await receive(sel.picklist_no, scans.map((x) => x.code));
      if (r.sent) { setDone(r.result); feedback('done'); } else { setDone({ queued: true }); feedback('warn'); } }
    catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  if (sel) {
    const got = new Set(scans.filter((x) => x.on).map((x) => x.pn)); const prev = new Set(sel.pallets.filter((x) => x.received).map((x) => x.pallet_no));
    const missing = sel.pallets.filter((x) => !got.has(x.pallet_no) && !prev.has(x.pallet_no));
    if (done) return (<Screen><Header title="Delivery received" sub={`${sel.vehicle_no || ''} · GCS ${sel.gcs_no || '-'}`} onBack={() => { setSel(null); load(true); }} /><Page>
      <Glass style={{ alignItems: 'center' }}><Ring value={done.queued ? String(got.size) : `${done.received}/${done.expected}`} label={done.queued ? 'saved - sent when online' : 'pallets received'} color={C.ok} size={96} /></Glass>
      {!done.queued && done.received < done.expected ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.warn }]}><Text style={[S.h2, { color: C.warn }]}>Not received ({done.expected - done.received})</Text><Text style={S.mute}>{done.pallets.filter((x) => !x.received).map((x) => x.ref).join('  ·  ')}</Text><Text style={[S.mute, { marginTop: 4 }]}>AIS sees this list - tell the driver / AIS if pallets are missing.</Text></View> : null}
      {!done.queued && done.extra?.length ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.amber }]}><Text style={S.h2}>Extra pallets (not on this delivery)</Text><Text style={S.mute}>{done.extra.join('  ·  ')}</Text></View> : null}
      <Btn title="Done" icon="checkmark-outline" onPress={() => { setSel(null); load(true); }} /></Page><Toast msg={msg} /></Screen>);
    return (<Screen><Header title={`Unload ${sel.vehicle_no || ''}`} sub={`GCS ${sel.gcs_no || '-'} · ${got.size + prev.size}/${sel.expected} scanned`} onBack={() => setSel(null)} /><Page>
      <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan pallet QR / tag" /></View>
      <Glass style={{ flexDirection: 'row', justifyContent: 'space-around' }}><Ring value={String(got.size + prev.size)} label="received" color={C.ok} size={80} /><Ring value={String(missing.length)} label="still to scan" color={missing.length ? C.amber : C.ok} size={80} /><Ring value={String(scans.filter((x) => !x.on).length)} label="extra" color={scans.some((x) => !x.on) ? C.warn : C.accent} size={80} /></Glass>
      <View style={S.card}>{sel.pallets.map((x) => <View key={x.pallet_no} style={[S.row, { paddingVertical: 4 }]}><Text style={{ flex: 1, fontWeight: '700', color: C.fg }}>{x.ref}</Text><Text style={{ color: got.has(x.pallet_no) || prev.has(x.pallet_no) ? C.ok : C.mute, fontWeight: '700' }}>{got.has(x.pallet_no) || prev.has(x.pallet_no) ? '✓ received' : 'to scan'}</Text></View>)}
        {scans.filter((x) => !x.on).map((x) => <View key={x.pn} style={[S.row, { paddingVertical: 4 }]}><Text style={{ flex: 1, fontWeight: '700', color: C.warn }}>{x.pn}</Text><Text style={{ color: C.warn }}>⚠ not on delivery</Text></View>)}</View>
      <Btn title={`Finish unloading · ${scans.length} scanned`} icon="checkmark-done-outline" busy={busy} onPress={finish} color={missing.length ? C.amber : C.ok} />
    </Page><Toast msg={msg} /></Screen>);
  }
  return (<Screen><Header title="Receive delivery" sub="Scan the gate pass QR or pick the vehicle" onBack={onBack} /><Page onRefresh={() => load(true)}>
    <View style={S.card}><ScanInput onScan={onGcs} placeholder="Scan GCS / gate pass QR" /></View>
    {list.length ? list.map((d) => <TouchableOpacity key={d.picklist_no} style={S.card} onPress={() => pick(d)}>
      <View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{d.vehicle_no || '-'}</Text><Text style={{ fontWeight: '700', color: d.received >= d.expected ? C.ok : C.amber }}>{d.received}/{d.expected}</Text></View>
      <Text style={S.mute}>GCS {d.gcs_no || '-'} · invoice {d.invoice_no || '-'} · {fDT(d.dispatched)}</Text></TouchableOpacity>)
      : <Empty icon="cube-outline" text="No AIS deliveries for you right now (pull down to refresh)" />}
  </Page><Toast msg={msg} /></Screen>);
}
