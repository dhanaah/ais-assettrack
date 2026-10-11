// Customer mode: the HHT at the customer's site makes Option A return slips (scan pallets -> slip with AIS-signed QR ->
// portable printer). Talks to AIS directly on the AIS network, through the internet address otherwise (see custapi).
// Developed by DT
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, TextInput, TouchableOpacity, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import qrcode from 'qrcode-generator';
import { S, C, T, Btn, Header, Page, Screen, ScanInput, Pill, useToast, Toast, Glass, Ring, Empty, Footer } from '../ui/kit';
import { ext, findRoute, getPairing, getRoute, createSlip, sendPending, outbox, history, refreshSlip, unpair, parsePairing, savePairing, setInternetAddress } from '../lib/custapi';
import { parsePalletQr } from '../lib/db';
import { printSlip } from '../lib/printer';
import { feedback } from '../lib/feedback';
import { fDT, fDate } from '../lib/when';
import { Settings } from './Misc';

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

const routeText = (r) => !r ? 'Offline' : r.kind === 'LAN' ? 'AIS network (direct)' : 'Internet (customer API)';
const routeColor = (r) => !r ? C.warn : r.kind === 'LAN' ? C.ok : C.accent;

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
      <Text style={[S.mute, { marginTop: 6 }]}>AIS network: {(found.lan || []).join(', ') || '—'}</Text>
      <Text style={S.mute}>Internet: {found.wan || 'not set yet (AIS IT publishes it)'}</Text>
      <Btn title="Pair this HHT" icon="link-outline" onPress={save} busy={busy} />
      {test?.err ? <Text style={[S.mute, { color: C.warn }]}>{test.err}</Text> : null}
    </View> : null}
    <Footer /></Page><Toast msg={msg} /></Screen>);
}

// ---------------------------------------------------------------- customer app
export default function CustomerApp({ deviceId, onUnpaired, onTheme, onUi }) {
  const [screen, setScreen] = useState('home'); const pair = getPairing();
  const back = () => setScreen('home');
  if (screen === 'new') return <NewSlip onBack={back} onDone={() => setScreen('slips')} />;
  if (screen === 'holding') return <Holding onBack={back} />;
  if (screen === 'slips') return <Slips onBack={back} />;
  if (screen === 'settings') return <CustSettings onBack={back} deviceId={deviceId} onUnpaired={onUnpaired} onTheme={onTheme} onUi={onUi} />;
  return <CustHome pair={pair} nav={setScreen} />;
}

function CustHome({ pair, nav }) {
  const [route, setRoute] = useState(getRoute()); const [pend, setPend] = useState(0); const [held, setHeld] = useState(null); const [me, setMe] = useState(null); const [msg, toast] = useToast();
  const refresh = useCallback(async (force) => {
    try { const r = await findRoute(force); setRoute(r); } catch (e) { setRoute(null); }
    const sent = await sendPending().catch(() => []); if (sent.length) toast(`${sent.length} waiting slip(s) sent`, 'done');
    setPend((await outbox()).length);
    try { setMe(await ext('/me')); const h = await ext('/holding'); setHeld(h); } catch (e) { if (e.status === 401) toast(e.message, 'err'); }
  }, []);
  useEffect(() => { refresh(true); const t = setInterval(() => refresh(false), 60000); return () => clearInterval(t); }, []);
  const overdue = held ? held.pallets.filter((p) => p.overdue).length : 0;
  const tiles = [['new', 'New return slip', 'Option A · scan pallets, print slip', ['#a855f7', '#7e22ce'], 'document-text-outline'],
    ['holding', 'Pallets with us', held ? `${held.count} pallet(s)${overdue ? ` · ${overdue} overdue` : ''}` : 'AIS pallets at this site', ['#0ea5e9', '#2563eb'], 'cube-outline'],
    ['slips', 'Our return slips', pend ? `${pend} waiting to send` : 'Status, reprint', ['#22c55e', '#15803d'], 'list-outline'],
    ['settings', 'Settings', 'Printer · text size · pairing', ['#64748b', '#334155'], 'settings-outline']];
  return (<Screen><Header logo sub={`${me?.name || pair?.n || ''} · AIS ${pair?.p || ''}`} />
    <TouchableOpacity onPress={() => refresh(true)} style={{ backgroundColor: routeColor(route), paddingVertical: 7, paddingHorizontal: 14, marginHorizontal: 14, marginTop: 10, borderRadius: 999, flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start' }}>
      <Ionicons name={route ? (route.kind === 'LAN' ? 'business-outline' : 'globe-outline') : 'cloud-offline-outline'} size={14} color="#fff" />
      <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12.5 }}>{routeText(route)}{pend ? ` · ${pend} waiting` : ''} · tap to recheck</Text></TouchableOpacity>
    <Page onRefresh={() => refresh(true)}>
      <Glass style={{ flexDirection: 'row', justifyContent: 'space-around' }}>
        <Ring value={held ? String(held.count) : '—'} label="AIS pallets here" color={C.accent} size={88} />
        <Ring value={held ? String(overdue) : '—'} label="over holding limit" color={overdue ? C.warn : C.ok} size={88} />
      </Glass>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>{tiles.map((t) => (
        <TouchableOpacity key={t[0]} onPress={() => nav(t[0])} activeOpacity={0.8} style={[S.card, { width: '47.5%', marginBottom: 0, minHeight: Math.round(118 * T.scale) }]}>
          <LinearGradient colors={t[3]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', marginBottom: 8 }}><Ionicons name={t[4]} size={22} color="#fff" /></LinearGradient>
          <Text style={{ fontWeight: '700', fontSize: Math.round(14 * T.scale), color: C.fg }}>{t[1]}</Text><Text style={[S.mute, { marginTop: 3, fontSize: Math.round(11.5 * T.scale) }]}>{t[2]}</Text></TouchableOpacity>))}</View>
      <Text style={[S.mute, { textAlign: 'center', marginTop: 14 }]}>Device "{pair?.d}" · customer {pair?.c}</Text>
      <Footer /></Page><Toast msg={msg} /></Screen>);
}

function NewSlip({ onBack, onDone }) {
  const [list, setList] = useState([]); const [veh, setVeh] = useState(''); const [dc, setDc] = useState(''); const [drv, setDrv] = useState(''); const [mob, setMob] = useState('');
  const [busy, setBusy] = useState(false); const [done, setDone] = useState(null); const [msg, toast] = useToast(); const pair = getPairing();
  const onScan = async (code) => {
    const q = parsePalletQr(code); const shown = q?.pallet_no || code.trim();
    if (list.some((x) => x.shown === shown)) { feedback('warn'); return toast(`${shown} already on this slip`, 'warn'); }
    const row = { scanned: code.trim(), shown, state: 'checking' };
    setList((l) => [row, ...l]);
    try {
      const r = await ext('/validate', { method: 'POST', body: { tags: [code.trim()] }, timeout: 8000 }); const v = r.results[0];
      setList((l) => l.map((x) => x.shown === shown ? { ...x, state: v.ok ? 'ok' : 'warn', pallet_no: v.pallet_no || shown, reason: v.reason } : x));
      feedback(v.ok ? 'ok' : 'warn'); if (!v.ok) toast(`${shown}: ${v.reason}`, 'warn');
    } catch (e) { setList((l) => l.map((x) => x.shown === shown ? { ...x, state: 'unchecked' } : x)); feedback('ok'); if (!e.offline) toast(e.message, 'err'); }
  };
  const submit = async () => {
    if (!list.length) return toast('Scan the pallets first', 'err');
    if (!veh.trim() || !dc.trim()) return toast('Vehicle number and your challan number are required', 'err');
    const warn = list.filter((x) => x.state === 'warn').length;
    const ok = await new Promise((res) => Alert.alert('Create return slip', `${list.length} pallet(s) on ${veh.toUpperCase()}${warn ? `\n${warn} pallet(s) not in your AIS ledger - AIS will check them at the gate` : ''}`, [{ text: 'Cancel', onPress: () => res(false) }, { text: 'Create slip', onPress: () => res(true) }]));
    if (!ok) return;
    setBusy(true);
    try {
      const r = await createSlip({ pallets: list.map((x) => x.scanned).reverse(), vehicle_no: veh.trim(), customer_challan_no: dc.trim(), customer_challan_date: new Date().toISOString(), driver_name: drv.trim() || null, driver_mobile: mob.trim() || null });
      if (r.sent) { feedback('done'); setDone(r.slip); doPrint(r.slip); }
      else { feedback('warn'); Alert.alert('Saved on this HHT', 'There is no network to AIS right now. The slip is sent automatically when the HHT is online; print it from "Our return slips" then (the QR comes from AIS).', [{ text: 'OK', onPress: onDone }]); }
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const doPrint = async (s) => {
    try { const r = await printSlip(toPrint(s, pair), { code: pair?.p, name: 'AIS ' + (pair?.p || '') }, 2, s.qr_payload); toast(r.printed ? 'Slip printed (2 copies)' : 'No printer - show the QR on screen at the AIS gate', r.printed ? 'done' : 'warn'); }
    catch (e) { toast('Print failed: ' + e.message, 'err'); }
  };
  if (done) return (<Screen><Header title="Return slip ready" sub={`${done.slip_no} · ${done.vehicle_no}`} onBack={onDone} /><Page>
    <View style={[S.card, { alignItems: 'center' }]}><QrView text={done.qr_payload} size={230} /><Text style={[S.h2, { marginTop: 10 }]}>{done.slip_no}</Text>
      <Text style={S.mute}>{done.declared_qty} pallet(s) · vehicle {done.vehicle_no} · your DC {done.customer_challan_no}</Text>
      <Text style={[S.body, { marginTop: 8, textAlign: 'center' }]}>Hand the printed slip to the driver. The AIS IN gate scans this QR.</Text></View>
    {done.warnings?.length ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.amber }]}>{done.warnings.map((w, i) => <Text key={i} style={S.mute}>• {w}</Text>)}</View> : null}
    <Btn title="Print again" icon="print-outline" onPress={() => doPrint(done)} />
    <Btn title="Done" secondary icon="checkmark-outline" onPress={onDone} />
  </Page><Toast msg={msg} /></Screen>);
  return (<Screen><Header title="New return slip (Option A)" sub={`${list.length} pallet(s) scanned`} onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan pallet QR / tag" />
      {list.map((x, i) => <TouchableOpacity key={x.shown} onLongPress={() => setList((l) => l.filter((y) => y.shown !== x.shown))} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 6, borderBottomWidth: 0.5, borderBottomColor: '#cbd5e1' }}>
        <Text style={[S.mute, { width: 28 }]}>{list.length - i}</Text><Text style={{ flex: 1, fontWeight: '700', color: C.fg }}>{x.pallet_no || x.shown}</Text>
        <Pill s={x.state === 'ok' ? 'AVAILABLE' : x.state === 'warn' ? 'HELD' : 'IN_RETURN'} /><Text style={[S.mute, { marginLeft: 6, fontSize: 11 }]}>{x.state === 'ok' ? 'in ledger' : x.state === 'warn' ? 'check' : x.state === 'checking' ? '…' : 'not checked'}</Text></TouchableOpacity>)}
      {list.length ? <Text style={[S.mute, { marginTop: 4 }]}>Long-press a pallet to remove it.</Text> : null}</View>
    <View style={S.card}>
      <Text style={S.mute}>Vehicle number *</Text><TextInput style={S.input} value={veh} onChangeText={(t) => setVeh(t.toUpperCase())} autoCapitalize="characters" placeholder="TN09AB1234" />
      <Text style={S.mute}>Your delivery challan number *</Text><TextInput style={S.input} value={dc} onChangeText={setDc} autoCapitalize="characters" />
      <Text style={S.mute}>Driver name</Text><TextInput style={S.input} value={drv} onChangeText={setDrv} />
      <Text style={S.mute}>Driver mobile</Text><TextInput style={S.input} value={mob} onChangeText={setMob} keyboardType="phone-pad" />
      <Btn title={`Create slip · ${list.length} pallet(s)`} icon="checkmark-circle-outline" onPress={submit} busy={busy} color={list.length && veh && dc ? C.ok : C.accent} /></View>
  </Page><Toast msg={msg} /></Screen>);
}

const toPrint = (s, pair) => ({ slip_no: s.slip_no, mode: 'A', date: fDT(s.created_at), customer_code: s.customer, customer_name: pair?.n || '', vehicle_no: s.vehicle_no,
  customer_challan_no: s.customer_challan_no, pallets: (s.pallets || []).map((p) => p.pallet_no), declared_qty: s.declared_qty });

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
      <Text style={S.mute}>{p.body.vehicle_no} · DC {p.body.customer_challan_no} · made {fDT(p.created)}</Text><Text style={[S.mute, { color: C.warn }]}>{p.last_error}</Text></View>)}
    {!rows.length && !pend.length ? <Empty icon="document-text-outline" text="No return slips from this HHT yet" /> : null}
    {rows.map((s) => <View key={s.slip_no} style={S.card}>
      <View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{s.slip_no}</Text><Pill s={s.status === 'CLOSED' ? 'AVAILABLE' : s.status === 'OPEN' ? 'IN_RETURN' : 'ALLOCATED'} /></View>
      <Text style={S.mute}>{s.declared_qty} pallet(s) · {s.vehicle_no} · DC {s.customer_challan_no} · {fDT(s.created_at)} · {s.status}</Text>
      <Btn title="Print slip" secondary icon="print-outline" onPress={async () => { try { const r = await printSlip(toPrint(s, pair), { code: pair?.p, name: 'AIS ' + (pair?.p || '') }, 1, s.qr_payload); toast(r.printed ? 'Printed' : 'No printer selected', r.printed ? 'done' : 'warn'); } catch (e) { toast(e.message, 'err'); } }} /></View>)}
  </Page><Toast msg={msg} /></Screen>);
}

function CustSettings({ onBack, deviceId, onUnpaired, onTheme, onUi }) {
  const pair = getPairing(); const [wan, setWan] = useState(pair?.wan || ''); const [msg, toast] = useToast();
  return (<View style={{ flex: 1 }}>
    <Settings onBack={onBack} deviceId={deviceId} onTheme={onTheme} onUi={onUi} customer
      extra={<View style={S.card}><Text style={S.h2}>AIS connection</Text>
        <Text style={S.mute}>Customer {pair?.c} · AIS plant {pair?.p} · device "{pair?.d}"</Text>
        <Text style={[S.mute, { marginTop: 4 }]}>AIS network: {(pair?.lan || []).join(', ')}</Text>
        <Text style={[S.mute, { marginTop: 8 }]}>Internet address (from AIS IT)</Text>
        <TextInput style={S.input} value={wan} onChangeText={setWan} autoCapitalize="none" autoCorrect={false} placeholder="https://assettrack.aisglass.com" />
        <Btn title="Save address" secondary icon="save-outline" onPress={async () => { await setInternetAddress(wan); try { const r = await findRoute(true); toast('Connected: ' + routeText(r), 'done'); } catch (e) { toast(e.message, 'warn'); } }} />
        <Btn title="Remove pairing" secondary icon="unlink-outline" onPress={() => Alert.alert('Remove pairing', 'This HHT will stop working for return slips until AIS pairs it again. Waiting slips stay on the HHT.', [{ text: 'Cancel' }, { text: 'Remove', style: 'destructive', onPress: async () => { await unpair(); onUnpaired(); } }])} /></View>} />
    <Toast msg={msg} /></View>);
}
