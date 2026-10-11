// Setup (open from the login screen and from Settings): 1. Server  2. Printer  3. Vehicles.
// Server: scan the server QR (web page /hht-setup or tray "HHT setup QR") - every address in it is tried and the ones
// that answer are kept, fastest first - or type a name / IP. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { S, C, Btn, Page, Header, Screen, Segmented, useToast, Toast, Footer, CameraScanner } from '../ui/kit';
import { api, setServer, getServer, getActiveServer, APP_VERSION } from '../lib/api';
import { PrinterCard } from './Misc';
import { allVehicles, addVehicle, removeVehicle, localVehicles, cleanVeh } from '../lib/vehicles';

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function b64(s) { s = s.replace(/-/g, '+').replace(/_/g, '/').replace(/[^A-Za-z0-9+/]/g, ''); let o = '', b = 0, n = 0; for (const ch of s) { b = (b << 6) | B64.indexOf(ch); n += 6; if (n >= 8) { n -= 8; o += String.fromCharCode((b >> n) & 255); } } return o; }
/** AISSRV1|<base64 json {a:[addresses], ports:[...]}> from the server's setup page. */
export function parseServerQr(t) {
  t = String(t || '').trim(); if (!t.startsWith('AISSRV1|')) return null;
  try { const j = JSON.parse(b64(t.slice(8))); return j && Array.isArray(j.a) && j.a.length ? j : null; } catch (e) { return null; }
}
async function probe(base, ms = 3500) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), ms); const t0 = Date.now();
  try { const r = await fetch(base + '/api/v1/health', { signal: ctl.signal }); const j = await r.json(); return r.ok && j.version ? { base, ms: Date.now() - t0, version: j.version } : null; }
  catch (e) { return null; } finally { clearTimeout(t); }
}
/** Try every address x port at once; returns the ones that answered, fastest first. */
export async function probeAll(addresses, ports = [80, 8001, 8002, 8003]) {
  const bases = []; addresses.forEach((a) => ports.forEach((p) => bases.push(`http://${a}${p === 80 ? '' : ':' + p}`)));
  return (await Promise.all(bases.map((b) => probe(b)))).filter(Boolean).sort((x, y) => x.ms - y.ms);
}

export function ServerCard({ toast, onSaved }) {
  const [srv, setSrv] = useState(getServer() || ''); const [test, setTest] = useState(null); const [cam, setCam] = useState(false); const [busy, setBusy] = useState(false);
  const runTest = async (value = srv) => {
    setTest({ busy: true });
    try { await setServer(value); const t0 = Date.now(); const h = await api('/health', { auth: false, timeout: 8000 }); setTest({ ok: true, text: `Connected · v${h.version} · ${Date.now() - t0} ms · ${(getActiveServer() || '').replace(/^https?:\/\//, '')}` }); onSaved && onSaved(); }
    catch (e) { setTest({ ok: false, text: e.offline ? 'No answer - same Wi-Fi as the server? Is the server running? Try Scan server QR.' : e.message }); }
  };
  const onQr = async (code) => {
    setCam(false); const j = parseServerQr(code);
    if (!j) return toast('Not an AssetTrack server QR - open http://<server>:8001/hht-setup on the PC', 'err');
    setBusy(true); setTest({ busy: true });
    try {
      const ok = await probeAll(j.a, j.ports || [80, 8001, 8002, 8003]);
      const hosts = []; ok.forEach((o) => { const h = o.base.replace(/^https?:\/\//, '').replace(/:\d+$/, ''); if (!hosts.includes(h)) hosts.push(h); });
      j.a.filter((a) => /[a-z]/i.test(a) && a.includes('.') && !hosts.includes(a)).forEach((a) => hosts.push(a));   // domain name kept as a backup
      if (!ok.length) { setTest({ ok: false, text: `None of ${j.a.join(', ')} answered - connect the HHT to the same network as the server` }); setSrv(hosts.join(', ') || j.a[0]); return; }
      const value = hosts.join(', '); setSrv(value); await setServer(value);
      setTest({ ok: true, text: `Connected · v${ok[0].version} · ${ok[0].ms} ms · ${ok[0].base.replace(/^https?:\/\//, '')}` }); toast('Server set from QR', 'done'); onSaved && onSaved();
    } finally { setBusy(false); }
  };
  return (<View style={S.card}><Text style={S.h2}>1. Server</Text>
    <Btn title="Scan server QR" icon="qr-code-outline" busy={busy} onPress={() => setCam(true)} />
    <Text style={[S.mute, { marginTop: 4 }]}>On the server PC: tray icon › "HHT setup QR", or open http://localhost:8001/hht-setup.</Text>
    <Text style={[S.mute, { marginTop: 10 }]}>or type the server name / IP</Text>
    <View style={S.row}><TextInput style={[S.input, { flex: 1, marginBottom: 0 }]} value={srv} onChangeText={(t) => { setSrv(t); setTest(null); }} autoCapitalize="none" autoCorrect={false} placeholder="192.168.1.12 or PCNAME.asahiindia.com" />
      <TouchableOpacity onPress={() => runTest()} style={[S.btnS, { marginTop: 0, paddingHorizontal: 12, minHeight: 46, justifyContent: 'center' }]}>{test?.busy ? <ActivityIndicator color={C.accent} /> : <Text style={S.btnSText}>Save & test</Text>}</TouchableOpacity></View>
    {test && !test.busy ? <Text style={[S.body, { color: test.ok ? C.ok : C.warn, marginTop: 6, fontWeight: '700' }]}>{test.ok ? '✓ ' : '✗ '}{test.text}</Text> : <Text style={[S.mute, { marginTop: 4 }]}>Ports 80 / 8001 / 8002 / 8003 are tried automatically. Several addresses: separate with a comma.</Text>}
    <CameraScanner visible={cam} onClose={() => setCam(false)} onScan={onQr} /></View>);
}

export function VehiclesCard({ toast }) {
  const [list, setList] = useState([]); const [mine, setMine] = useState([]); const [v, setV] = useState('');
  const load = async () => { setList(await allVehicles()); setMine(await localVehicles()); };
  useEffect(() => { load(); }, []);
  return (<View style={S.card}><Text style={S.h2}>3. Vehicles</Text>
    <Text style={S.mute}>Picked from this list on the return slip - also without network. AIS vehicles come from the server (recent loads, transporters); add others here.</Text>
    <View style={[S.row, { marginTop: 8 }]}><TextInput style={[S.input, { flex: 1, marginBottom: 0 }]} value={v} onChangeText={(t) => setV(t.toUpperCase())} autoCapitalize="characters" placeholder="TN09AB1234" />
      <TouchableOpacity onPress={async () => { if (!cleanVeh(v)) return; await addVehicle(v); setV(''); await load(); toast && toast('Vehicle added', 'done'); }} style={[S.btnS, { marginTop: 0, paddingHorizontal: 14, minHeight: 46, justifyContent: 'center' }]}><Text style={S.btnSText}>Add</Text></TouchableOpacity></View>
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>{list.slice(0, 60).map((x) => <View key={x} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 9, paddingVertical: 5, borderRadius: 9, borderWidth: 1, borderColor: C.line }}>
      <Text style={{ fontWeight: '700', color: C.fg, fontSize: 12.5 }}>{x}</Text>{mine.includes(x) ? <TouchableOpacity onPress={async () => { await removeVehicle(x); await load(); }} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}><Ionicons name="close-circle" size={16} color={C.mute} /></TouchableOpacity> : null}</View>)}</View>
    <Text style={[S.mute, { marginTop: 6 }]}>{list.length} vehicle(s){list.length > 60 ? ' - first 60 shown' : ''}</Text></View>);
}

/** Setup screen (before login too). */
export default function Setup({ onBack, customer, initial }) {
  const [msg, toast] = useToast(); const [tab, setTab] = useState(initial || (customer ? 'printer' : 'server'));
  const tabs = customer ? [['printer', '2. Printer'], ['vehicles', '3. Vehicles']] : [['server', '1. Server'], ['printer', '2. Printer'], ['vehicles', '3. Vehicles']];
  return (<Screen><Header title="Setup" sub={`Server · Printer · Vehicles · v${APP_VERSION}`} onBack={onBack} /><Page>
    <Segmented options={tabs} value={tab} onChange={setTab} />
    {tab === 'server' ? <ServerCard toast={toast} /> : tab === 'printer' ? <PrinterCard toast={toast} /> : <VehiclesCard toast={toast} />}
    <Footer /></Page><Toast msg={msg} /></Screen>);
}
