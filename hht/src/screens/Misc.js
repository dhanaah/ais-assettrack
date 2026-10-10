// Gate IN, Gate OUT, Damage/Tag, Lookup, Pending & Sync, Settings. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, Switch } from 'react-native';
import { S, C, Btn, Page, Header, ScanInput, Pill, useToast, Toast, Footer, AisLogo } from '../ui/kit';
import { Screen, applyTheme, T } from '../ui/kit';
import { THEMES, THEME_KEYS } from '../ui/theme';
import { api, getServer, setServer } from '../lib/api';
import { resolveTag, enqueue, recentEvents, pendingDocs, kv, setPalletLocal, logActivity, recentActivity, getLpn, lpnsOnPallet } from '../lib/db';
import { state as sync, syncNow, subscribe } from '../lib/sync';
import { listPaired, connect, printerAvailable, testPrint, setPaperWidth } from '../lib/printer';

const needOnline = (toast) => { if (!sync.online) { toast('This step needs the server (gate documents are online-only). Use manual gate pass + supervisor PIN if the outage continues.', 'err'); return false; } return true; };

export function GateIn({ onBack }) {
  const [msg, toast] = useToast(); const [last, setLast] = useState(null);
  const onScan = async (code) => {
    if (!needOnline(toast)) return;
    const no = code.startsWith('AIS1|RS|') || code.startsWith('RTS|') ? code.split('|')[code.startsWith('AIS1|') ? 2 : 1] : code;
    try { const r = await api(`/slips/${encodeURIComponent(no)}/gate-in`, { method: 'POST', body: { qr: code !== no ? code : null } }); setLast(r); toast(`${no}: ${r.status} · GCS-IN ${r.gcs_in_no || 'queued'}`); logActivity('GATE_IN', no, r.status); syncNow().catch(() => {}); }
    catch (e) { toast(e.message, 'err'); }
  };
  return (<Screen><Header title="IN Gate" sub="Scan return slip QR → GCS inward" onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan return slip QR" /></View>
    {last ? <View style={S.card}><Text style={S.h2}>{last.slip_no} <Pill s={last.status} /></Text><Text style={S.mute}>Customer {last.customer_code} · vehicle {last.vehicle_no} · declared {last.declared_qty} · GCS {last.gcs_in_no || 'pending (retry queue)'}</Text></View> : null}
    <Text style={S.mute}>No slip? Create one with "Return Slip (B1/B2)" first.</Text></Page><Toast msg={msg} /></Screen>);
}

export function GateOut({ onBack }) {
  const [msg, toast] = useToast(); const [lists, setLists] = useState([]); const [pin, setPin] = useState(''); const [override, setOverride] = useState(false);
  const load = async () => { try { setLists(await api('/picklists?status=APPROVED')); } catch (e) { toast(e.message, 'err'); } };
  useEffect(() => { load(); }, []);
  const onScan = async (code) => {
    if (!needOnline(toast)) return;
    const sc = code.startsWith('CHL|') ? code.split('|')[1] : code;
    const k = lists.find(l => l.gcs_no === sc || l.challan_no === sc);
    if (!k && !override) { logActivity('GATE_OUT_MISMATCH', sc, 'vehicle held'); return toast('No approved vehicle matches this QR - HOLD VEHICLE', 'err'); }
    const target = k || lists[0]; if (!target) return toast('No approved pick lists', 'err');
    try { const r = await api(`/picklists/${target.picklist_no}/gate-out`, { method: 'POST', body: { scanned: sc, manual_override: override, supervisor_pin: override ? pin : null } }); toast(`${r.picklist_no} DISPATCHED · ${r.qty} pallets to ${r.customer_code}`); logActivity(override ? 'GATE_OUT_OVERRIDE' : 'GATE_OUT', r.picklist_no, `${r.qty} pallets`); load(); syncNow().catch(() => {}); }
    catch (e) { toast(e.message, 'err'); }
  };
  return (<Screen><Header title="OUT Gate" sub="Scan GCS / challan QR" onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan GCS or challan QR" />
      <View style={[S.row, { marginTop: 8 }]}><Switch value={override} onValueChange={setOverride} trackColor={{ true: C.warn }} /><Text>Manual override (paper challan)</Text></View>
      {override ? <TextInput style={[S.input, { marginTop: 6 }]} placeholder="Supervisor PIN" value={pin} onChangeText={setPin} secureTextEntry keyboardType="number-pad" /> : null}</View>
    <Text style={S.h2}>Approved, waiting at gate</Text>
    {lists.map(k => <View key={k.picklist_no} style={S.card}><Text style={{ fontWeight: '700' }}>{k.vehicle_no} · {k.customer_code}</Text><Text style={S.mute}>{k.picklist_no} · challan {k.challan_no} · GCS {k.gcs_no || 'pending'} · {k.qty} pallets</Text></View>)}
    <Btn title="Refresh" secondary onPress={load} /></Page><Toast msg={msg} /></Screen>);
}

export function Damage({ onBack }) {
  const [msg, toast] = useToast(); const [remarks, setRemarks] = useState(''); const [kind, setKind] = useState('DAMAGE');
  const onScan = async (code) => {
    const { pallet } = await resolveTag(code); if (!pallet) return toast('Unknown tag', 'err');
    if (kind === 'DAMAGE') { await setPalletLocal(pallet.pallet_no, { status: 'DAMAGED' }); await enqueue('DAMAGE_MARK', { scanned: code, remarks }, !sync.online); toast(`${pallet.pallet_no} marked DAMAGED`, 'warn'); }
    else { await enqueue('TAG_REPLACE_REQ', { scanned: code, remarks }, !sync.online); toast(`Tag replacement requested for ${pallet.pallet_no}`); }
    setRemarks(''); if (sync.online) syncNow().catch(() => {});
  };
  return (<Screen><Header title="Damage / Tag issue" onBack={onBack} /><Page>
    <View style={[S.row, { marginBottom: 8 }]}>{[['DAMAGE', 'Mark damaged'], ['TAG', 'Tag unreadable / lost']].map(([k, l]) => <TouchableOpacity key={k} onPress={() => setKind(k)} style={[S.btnS, { flex: 1, marginTop: 0, backgroundColor: kind === k ? C.accent : undefined }]}><Text style={[S.btnSText, kind === k ? { color: '#fff' } : null]}>{l}</Text></TouchableOpacity>)}</View>
    <View style={S.card}><TextInput style={S.input} placeholder="Remarks" value={remarks} onChangeText={setRemarks} /><ScanInput onScan={onScan} placeholder={kind === 'TAG' ? 'Scan tag or type pallet no' : 'Scan pallet tag'} /></View>
  </Page><Toast msg={msg} /></Screen>);
}

export function Lookup({ onBack }) {
  const [p, setP] = useState(null); const [hist, setHist] = useState(null); const [lp, setLp] = useState([]); const [msg, toast] = useToast();
  const onScan = async (code) => { let r = await resolveTag(code); setHist(null);
    if (!r.pallet) { const l = await getLpn(code); if (l && l.pallet) r = await resolveTag(l.pallet); else if (l) return toast(`LPN ${l.lpn}: ${l.part} × ${l.qty} · ${l.status} · no pallet linked`, 'warn'); }
    if (!r.pallet) return toast('Not in local cache' + (r.tag ? ` (tag ${r.tag.tag} ${r.tag.status})` : ''), 'err'); setP(r.pallet); setLp(await lpnsOnPallet(r.pallet.pallet_no));
    if (sync.online) { try { const h = await api('/pallets/' + r.pallet.pallet_no); setHist(h.history.slice(0, 15)); } catch { } } };
  return (<Screen><Header title="Pallet Lookup" onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onScan} /></View>
    {p ? <View style={S.card}><Text style={S.h1}>{p.pallet_no} <Pill s={p.status} /></Text><View style={[S.row, { marginVertical: 4 }]}><Pill s={p.load || 'EMPTY'} /><Text style={S.mute}>  zone {p.zone || '-'}{p.load_ref ? ' · ' + p.load_ref : ''}</Text></View><Text style={S.mute}>Home {p.home} · type {p.type} · tag {p.tag}</Text>{lp.map(l => <Text key={l.lpn} style={S.mute}>• LPN {l.lpn} · {l.part} × {l.qty} · {l.status}</Text>)}{p.customer ? <Text style={S.mute}>At customer {p.customer}</Text> : null}{p.picklist ? <Text style={S.mute}>Pick list {p.picklist}</Text> : null}</View> : null}
    {hist ? <View style={S.card}><Text style={S.h2}>Recent history</Text>{hist.map(h => <Text key={h.id} style={[S.mute, { marginBottom: 3 }]}>{String(h.ts).slice(0, 16)} · {h.event_type} → {h.to_status || ''} {h.ref_doc || ''} {h.customer_code || ''} · {h.user_id}</Text>)}</View> : null}
  </Page><Toast msg={msg} /></Screen>);
}

export function Pending({ onBack }) {
  const [st, setSt] = useState({ ...sync }); const [ev, setEv] = useState([]); const [docs, setDocs] = useState([]); const [acts, setActs] = useState([]); const [tab, setTab] = useState('events');
  const load = async () => { setEv(await recentEvents(80)); setDocs(await pendingDocs()); setActs(await recentActivity(80)); };
  useEffect(() => { load(); return subscribe(s => { setSt(s); load(); }); }, []);
  return (<Screen><Header title="Pending & Sync" onBack={onBack} /><Page>
    <View style={[S.card, { flexDirection: 'row', justifyContent: 'space-around' }]}>
      <View style={{ alignItems: 'center' }}><Text style={[S.big, { color: st.online ? C.ok : C.warn }]}>{st.online ? 'ON' : 'OFF'}</Text><Text style={S.mute}>network</Text></View>
      <View style={{ alignItems: 'center' }}><Text style={[S.big, { color: st.pending ? C.amber : C.ok }]}>{st.pending}</Text><Text style={S.mute}>pending events</Text></View>
      <View style={{ alignItems: 'center' }}><Text style={[S.big, { fontSize: 18, marginTop: 10 }]}>{st.lastSync ? st.lastSync.slice(11, 19) : '—'}</Text><Text style={S.mute}>last sync</Text></View></View>
    {st.lastError ? <View style={[S.card, { borderLeftWidth: 4, borderLeftColor: C.warn }]}><Text style={{ color: C.warn }}>{st.lastError === 'LOGIN' ? 'Session expired - login again to sync' : st.lastError}</Text></View> : null}
    <Btn title={st.syncing ? 'Syncing…' : 'Sync now'} onPress={() => syncNow()} disabled={st.syncing} />
    {docs.length ? <View style={S.card}><Text style={S.h2}>Offline documents waiting</Text>{docs.map(d => <Text key={d.doc_no} style={S.mute}>{d.kind} {d.doc_no}</Text>)}</View> : null}
    <View style={[S.row, { marginBottom: 8 }]}>{[['events', 'Recent events'], ['activity', 'My activity']].map(([k, l]) => <TouchableOpacity key={k} onPress={() => setTab(k)} style={[S.btnS, { flex: 1, marginTop: 0, backgroundColor: tab === k ? C.accent : undefined }]}><Text style={[S.btnSText, tab === k ? { color: '#fff' } : null]}>{l}</Text></TouchableOpacity>)}</View>
    {tab === 'activity' ? acts.map(a => <View key={a.id} style={[S.card, { paddingVertical: 8, marginBottom: 6 }]}><View style={S.row}><Text style={{ flex: 1, fontWeight: '600' }}>{a.action}</Text><Text style={S.mute}>{a.sent ? '✓ sent' : 'pending'}</Text></View><Text style={S.mute}>{a.ts.slice(0, 19).replace('T', ' ')} · {a.ref || ''} {a.result ? '· ' + a.result : ''}</Text></View>) : null}
    {tab === 'events' ? ev.map(e => <View key={e.event_id} style={[S.card, { paddingVertical: 8, marginBottom: 6 }]}><View style={S.row}><Text style={{ flex: 1, fontWeight: '600' }}>{e.event_type}</Text><Pill s={e.status} /></View><Text style={S.mute}>{e.local_ts.slice(0, 19).replace('T', ' ')} · {JSON.parse(e.payload).scanned || JSON.parse(e.payload).slip_no || ''} {e.result ? '· ' + e.result : ''}</Text></View>) : null}
  </Page></Screen>);
}

export function Settings({ onBack, deviceId, onTheme }) {
  const [srv, setSrv] = useState(getServer()); const [printers, setPrinters] = useState([]); const [sel, setSel] = useState(null); const [selName, setSelName] = useState(null); const [paper, setPaper] = useState('58'); const [busy, setBusy] = useState(false); const [msg, toast] = useToast();
  useEffect(() => { kv.get('printer').then(setSel); kv.get('printer_name').then(setSelName); kv.get('printer_width').then(w => setPaper(w || '58')); }, []);
  return (<Screen><Header title="Settings" onBack={onBack} /><Page>
    <View style={S.card}><Text style={S.h2}>Server name</Text><TextInput style={S.input} value={srv} onChangeText={setSrv} autoCapitalize="none" placeholder="assettrack" /><Text style={S.mute}>Ports 80 / 8001 / 8002 / 8003 are tried automatically.</Text><Btn title="Save" secondary onPress={async () => { await setServer(srv); toast('Saved'); }} /><Text style={[S.mute, { marginTop: 6 }]}>Device ID: {deviceId}</Text></View>
    <View style={S.card}><Text style={S.h2}>Theme</Text><Text style={S.mute}>Current: {THEMES[T.key].name}</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>{THEME_KEYS.map(k => <TouchableOpacity key={k} onPress={async () => { applyTheme(k); await kv.set('theme', k); onTheme && onTheme(k); toast('Theme: ' + THEMES[k].name); }} style={[S.btnS, { flex: 1, minWidth: '45%', marginTop: 0, backgroundColor: T.key === k ? C.accent : undefined }]}><Text style={[S.btnSText, T.key === k ? { color: '#fff' } : null]}>{THEMES[k].name}</Text></TouchableOpacity>)}</View></View>
    <View style={S.card}><Text style={S.h2}>Bluetooth printer {printerAvailable() ? '' : '(module not in this build)'}</Text>
      <Text style={S.mute}>Selected: {selName ? `${selName} (${sel})` : (sel || 'none')}</Text>
      <Text style={[S.mute, { marginTop: 4 }]}>1. Switch the printer on. 2. Pair it once in Android Settings > Bluetooth. 3. List and tap it here. 4. Test print.</Text>
      <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>{[['58', '2" / 58 mm (SEZNIK)'], ['80', '3" / 80 mm']].map(([w, l]) => <TouchableOpacity key={w} onPress={async () => { setPaper(w); await setPaperWidth(w); }} style={[S.btnS, { flex: 1, marginTop: 0, backgroundColor: paper === w ? C.accent : undefined }]}><Text style={[S.btnSText, paper === w ? { color: '#fff' } : null]}>{l}</Text></TouchableOpacity>)}</View>
      <Btn title="List paired printers" secondary icon="bluetooth-outline" onPress={async () => { try { const l = await listPaired(); setPrinters(l); if (!l.length) toast('No paired Bluetooth devices - pair the printer in Android Settings first', 'warn'); } catch (e) { toast(e.message, 'err'); } }} />
      {printers.map(p => <TouchableOpacity key={p.address} onPress={async () => { setBusy(true); try { await connect(p.address); await kv.set('printer_name', p.name); setSel(p.address); setSelName(p.name); toast('Connected ' + p.name); } catch (e) { toast('Cannot connect: ' + e.message, 'err'); } finally { setBusy(false); } }} style={[S.btnS, { alignItems: 'flex-start', backgroundColor: sel === p.address ? C.ok : undefined }]}><Text style={[S.btnSText, sel === p.address ? { color: '#fff' } : null]}>{p.name}  {p.address}</Text></TouchableOpacity>)}
      {sel ? <Btn title={busy ? 'Printing…' : 'Test print'} icon="print-outline" onPress={async () => { setBusy(true); try { await testPrint(await kv.get('plant')); toast('Test sent - check the printer'); logActivity('PRINT_TEST', sel, 'ok'); } catch (e) { toast('Test print failed: ' + e.message, 'err'); logActivity('PRINT_TEST', sel, e.message); } finally { setBusy(false); } }} /> : null}
      <Text style={[S.mute, { marginTop: 6 }]}>Blank paper after a test = the printer does not use ESC/POS; tell DT the printer model.</Text></View>
    <View style={S.card}><Text style={S.h2}>Data</Text><Btn title="Full resync of reference data" secondary onPress={async () => { await syncNow({ full: true }); toast(sync.lastError || 'Resync done'); }} /></View>
    <Footer />
  </Page><Toast msg={msg} /></Screen>);
}
