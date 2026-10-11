// Gate IN, Gate OUT, Damage/Tag, Lookup, Pending & Sync, Settings. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { S, C, Btn, Page, Header, ScanInput, Pill, useToast, Toast, Footer, AisLogo, Segmented, SwitchRow, Empty, ListRow } from '../ui/kit';
import { Screen, applyTheme, T, useScanMode, setScanMode } from '../ui/kit';
import { THEMES, THEME_KEYS } from '../ui/theme';
import { api, getServer, setServer, APP_VERSION } from '../lib/api';
import { resolveTag, enqueue, recentEvents, pendingDocs, kv, setPalletLocal, logActivity, recentActivity, getLpn, lpnsOnPallet } from '../lib/db';
import { state as sync, syncNow, subscribe } from '../lib/sync';
import { listPrinters, connect, connAvailable, testPrint, findLanguage, getConfig, setConfig, LANGS, CONNS, WIDTHS, IMGS } from '../lib/printer';
import { setSoundEnabled, soundEnabled, feedback } from '../lib/feedback';
import { checkUpdate, openUpdate } from '../lib/update';
import { fDT, fDate, fTimeS } from '../lib/when';

const needOnline = (toast) => { if (!sync.online) { toast('This step needs the server (gate documents are online-only). Use manual gate pass + supervisor PIN if the outage continues.', 'err'); return false; } return true; };

export function GateIn({ onBack }) {
  const [msg, toast] = useToast(); const [last, setLast] = useState(null);
  const onScan = async (code) => {
    if (!needOnline(toast)) return;
    const no = code.startsWith('AIS1|RS|') || code.startsWith('AIS1|RO|') || code.startsWith('RTS|') ? code.split('|')[code.startsWith('AIS1|') ? 2 : 1] : code;   // RO = printed by a customer HHT without network
    try { const r = await api(`/slips/${encodeURIComponent(no)}/gate-in`, { method: 'POST', body: { qr: code !== no ? code : null } }); setLast(r); toast(`Gate entry ${r.gate_entry || ''} · ` + (r.kind === 'CHALLAN' ? `challan ${r.challan_no} from ${r.from_plant}: ${r.declared_qty} pallets - receive at yard` : `${no}: ${r.status} · GCS-IN ${r.gcs_in_no || 'queued'}`)); logActivity('GATE_IN', no, r.status); syncNow().catch(() => {}); }
    catch (e) { toast(e.message, 'err'); }
  };
  return (<Screen><Header title="IN Gate" sub="Customer: return slip QR · AIS plant: challan QR" onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan return slip / challan QR" /></View>
    {last ? <View style={S.card}><Text style={S.h2}>{last.slip_no} <Pill s={last.status} /></Text><Text style={S.mute}>{last.kind === 'CHALLAN' ? `Other-plant return from ${last.from_plant} · vehicle ${last.vehicle_no || '-'} · ${last.declared_qty} pallets on challan · receive at pallet yard` : `Customer ${last.customer_code} · vehicle ${last.vehicle_no} · declared ${last.declared_qty} · GCS ${last.gcs_in_no || 'pending (retry queue)'}`}</Text></View> : null}
    <Text style={S.mute}>Customer vehicle without slip: make one with "Return Slip (Option B)". Pallets from another AIS plant come only with that plant's challan - scan the challan QR.</Text></Page><Toast msg={msg} /></Screen>);
}

export function GateOut({ onBack }) {
  const [msg, toast] = useToast(); const [lists, setLists] = useState([]); const [pin, setPin] = useState(''); const [override, setOverride] = useState(false);
  const load = async () => { try { setLists(await api('/picklists?status=APPROVED')); } catch (e) { toast(e.message, 'err'); } };
  useEffect(() => { load(); }, []);
  const onScan = async (code) => {
    if (!needOnline(toast)) return;
    const sc = code.startsWith('CHL|') ? code.split('|')[1] : code.startsWith('AIS1|GCS|') ? code.split('|')[2] : code;
    const k = lists.find(l => l.gcs_no === sc || l.challan_no === sc);
    if (!k && !override && !code.startsWith('AIS1|GCS|')) { logActivity('GATE_OUT_MISMATCH', sc, 'vehicle held'); return toast('No approved vehicle matches this QR - HOLD VEHICLE', 'err'); }
    try {
      const r = code.startsWith('AIS1|GCS|') || !k
        ? await api('/gate-out/scan', { method: 'POST', body: { scanned: code, manual_override: override, supervisor_pin: override ? pin : null } })
        : await api(`/picklists/${k.picklist_no}/gate-out`, { method: 'POST', body: { scanned: sc, manual_override: override, supervisor_pin: override ? pin : null } });
      toast(`${r.gcs_no || r.picklist_no} DISPATCHED · ${r.qty} pallets · ${r.vehicle_no || ''} → ${r.customer_code}`, 'done'); logActivity(override ? 'GATE_OUT_OVERRIDE' : 'GATE_OUT', r.picklist_no, `${r.qty} pallets`); load(); syncNow().catch(() => {}); }
    catch (e) { toast(e.message, 'err'); }
  };
  return (<Screen><Header title="OUT Gate" sub="Scan the GCS QR printed after loading" onBack={onBack} /><Page onRefresh={load}>
    <View style={S.card}><ScanInput onScan={onScan} placeholder="Scan GCS or challan QR" />
      <SwitchRow label="Manual override (paper challan)" hint="Needs a supervisor PIN; recorded in the audit log" value={override} onChange={setOverride} danger />
      {override ? <TextInput style={[S.input, { marginTop: 6 }]} placeholder="Supervisor PIN" value={pin} onChangeText={setPin} secureTextEntry keyboardType="number-pad" /> : null}</View>
    <Text style={S.h2}>Approved, waiting at gate</Text>
    {lists.length === 0 ? <Empty icon="car-outline" text="No vehicle approved yet" hint="Logistics approves the vehicle on the web after the challan." /> : null}
    {lists.map(k => <ListRow key={k.picklist_no} title={`${k.vehicle_no || '—'} · ${k.customer_code}`} sub={`${k.picklist_no} · challan ${k.challan_no} · GCS ${k.gcs_no || 'pending'} · ${k.qty} pallets`} right={<Pill s={k.dispatch_type || 'PALLET_ONLY'} />} />)}
    <Btn title="Refresh" secondary icon="refresh" onPress={load} /></Page><Toast msg={msg} /></Screen>);
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
    <Segmented options={[['DAMAGE', 'Mark damaged', C.warn], ['TAG', 'Tag unreadable / lost', C.amber]]} value={kind} onChange={setKind} />
    <View style={S.card}><TextInput style={S.input} placeholder="Remarks" value={remarks} onChangeText={setRemarks} /><ScanInput onScan={onScan} placeholder={kind === 'TAG' ? 'Scan tag or type pallet no' : 'Scan pallet tag'} /></View>
  </Page><Toast msg={msg} /></Screen>);
}

export function Lookup({ onBack, initial }) {
  const [p, setP] = useState(null); const [hist, setHist] = useState(null); const [lp, setLp] = useState([]); const [msg, toast] = useToast();
  useEffect(() => { if (initial) onScan(initial); }, [initial]);
  const onScan = async (code) => { let r = await resolveTag(code); setHist(null);
    if (!r.pallet) { const l = await getLpn(code); if (l && l.pallet) r = await resolveTag(l.pallet); else if (l) return toast(`LPN ${l.lpn}: ${l.part} × ${l.qty} · ${l.status} · no pallet linked`, 'warn'); }
    if (!r.pallet) return toast('Not in local cache' + (r.tag ? ` (tag ${r.tag.tag} ${r.tag.status})` : ''), 'err'); setP(r.pallet); setLp(await lpnsOnPallet(r.pallet.pallet_no));
    if (sync.online) { try { const h = await api('/pallets/' + r.pallet.pallet_no); setHist(h.history.slice(0, 15)); } catch { } } };
  return (<Screen><Header title="Pallet Lookup" onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onScan} /></View>
    {!p ? <Empty icon="search-outline" text="Scan a pallet, tag or LPN" hint="Shows status, load, zone, LPNs and recent history (history needs the server)." /> : null}
    {p ? <View style={S.card}><Text style={S.h1}>{p.pallet_no} <Pill s={p.status} /></Text><View style={[S.row, { marginVertical: 4 }]}><Pill s={p.load || 'EMPTY'} /><Text style={S.mute}>  zone {p.zone || '-'}{p.load_ref ? ' · ' + p.load_ref : ''}</Text></View><Text style={S.mute}>Home {p.home} · type {p.type} · tag {p.tag}</Text>{lp.map(l => <Text key={l.lpn} style={S.mute}>• LPN {l.lpn} · {l.part} × {l.qty} · {l.status}</Text>)}{p.customer ? <Text style={S.mute}>At customer {p.customer}</Text> : null}{p.picklist ? <Text style={S.mute}>Pick list {p.picklist}</Text> : null}</View> : null}
    {hist ? <View style={S.card}><Text style={S.h2}>Recent history</Text>{hist.map(h => <Text key={h.id} style={[S.mute, { marginBottom: 3 }]}>{fDT(h.ts)} · {h.event_type} → {h.to_status || ''} {h.ref_doc || ''} {h.customer_code || ''} · {h.user_id}</Text>)}</View> : null}
  </Page><Toast msg={msg} /></Screen>);
}

export function Pending({ onBack }) {
  const [st, setSt] = useState({ ...sync }); const [ev, setEv] = useState([]); const [docs, setDocs] = useState([]); const [acts, setActs] = useState([]); const [tab, setTab] = useState('events');
  const load = async () => { setEv(await recentEvents(80)); setDocs(await pendingDocs()); setActs(await recentActivity(80)); };
  useEffect(() => { load(); return subscribe(s => { setSt(s); load(); }); }, []);
  return (<Screen><Header title="Pending & Sync" onBack={onBack} /><Page refreshing={st.syncing} onRefresh={() => syncNow()}>
    <View style={[S.card, { flexDirection: 'row', justifyContent: 'space-around' }]}>
      <View style={{ alignItems: 'center' }}><Text style={[S.big, { color: st.online ? C.ok : C.warn }]}>{st.online ? 'ON' : 'OFF'}</Text><Text style={S.mute}>network</Text></View>
      <View style={{ alignItems: 'center' }}><Text style={[S.big, { color: st.pending ? C.amber : C.ok }]}>{st.pending}</Text><Text style={S.mute}>pending events</Text></View>
      <View style={{ alignItems: 'center' }}><Text style={[S.big, { fontSize: 18, marginTop: 10 }]}>{st.lastSync ? fDate(st.lastSync) + ' ' + fTimeS(st.lastSync) : '—'}</Text><Text style={S.mute}>last sync</Text></View></View>
    {st.lastError ? <View style={[S.card, { borderLeftWidth: 4, borderLeftColor: C.warn }]}><Text style={{ color: C.warn }}>{st.lastError === 'LOGIN' ? 'Session expired - login again to sync' : st.lastError}</Text></View> : null}
    <Btn title="Sync now" icon="sync-outline" onPress={() => syncNow()} busy={st.syncing} />
    {docs.length ? <View style={S.card}><Text style={S.h2}>Offline documents waiting</Text>{docs.map(d => <Text key={d.doc_no} style={S.mute}>{d.kind} {d.doc_no}</Text>)}</View> : null}
    <Segmented options={[['events', 'Recent events'], ['activity', 'My activity']]} value={tab} onChange={setTab} />
    {tab === 'activity' ? acts.map(a => <View key={a.id} style={[S.card, { paddingVertical: 8, marginBottom: 6 }]}><View style={S.row}><Text style={{ flex: 1, fontWeight: '600' }}>{a.action}</Text><Text style={S.mute}>{a.sent ? '✓ sent' : 'pending'}</Text></View><Text style={S.mute}>{a.ts.slice(0, 19).replace('T', ' ')} · {a.ref || ''} {a.result ? '· ' + a.result : ''}</Text></View>) : null}
    {tab === 'events' ? ev.map(e => <View key={e.event_id} style={[S.card, { paddingVertical: 8, marginBottom: 6 }]}><View style={S.row}><Text style={{ flex: 1, fontWeight: '600' }}>{e.event_type}</Text><Pill s={e.status} /></View><Text style={S.mute}>{e.local_ts.slice(0, 19).replace('T', ' ')} · {JSON.parse(e.payload).scanned || JSON.parse(e.payload).slip_no || ''} {e.result ? '· ' + e.result : ''}</Text></View>) : null}
  </Page></Screen>);
}

export function Settings({ onBack, deviceId, onTheme, onUi, customer, extra, onSetup }) {
  const [srv, setSrv] = useState(getServer()); const [busy, setBusy] = useState(false); const [msg, toast] = useToast();
  const [sound, setSound] = useState(soundEnabled()); const [scale, setScale] = useState(T.scale || 1); const [idle, setIdle] = useState(30); const [upd, setUpd] = useState(null);
  useEffect(() => { kv.get('idle_min').then(v => setIdle(v ?? 30)); }, []);
  return (<Screen><Header title="Settings" onBack={onBack} /><Page>
    {extra || null}
    {onSetup ? <TouchableOpacity onPress={onSetup} style={[S.card, { flexDirection: 'row', alignItems: 'center', gap: 12 }]}><Ionicons name="construct-outline" size={24} color={C.accent} /><View style={{ flex: 1 }}><Text style={S.h2}>Setup</Text><Text style={S.mute}>{customer ? '2. Printer · 3. Vehicles' : '1. Server · 2. Printer · 3. Vehicles'}</Text></View><Ionicons name="chevron-forward" size={20} color={C.mute} /></TouchableOpacity> : null}
    {customer ? null : <View style={S.card}><Text style={S.h2}>App</Text><Text style={{ color: C.mute, opacity: 0.35, fontSize: 10 }}>device {deviceId} · v{APP_VERSION}</Text>
      <Btn title={upd?.busy ? 'Checking…' : 'Check for app update'} secondary icon="cloud-download-outline" busy={upd?.busy} onPress={async () => { setUpd({ busy: true }); const r = await checkUpdate(); setUpd(r || { none: true }); if (!r) toast('Server has no APK published', 'warn'); else if (r.newer) toast(`v${r.version} available`, 'warn'); else toast('You have the latest version', 'ok'); }} />
      {upd?.newer ? <Btn title={`Download v${upd.version}`} icon="download-outline" onPress={() => openUpdate(upd)} /> : null}</View>}
    <ScanModeCard />
    <View style={S.card}><Text style={S.h2}>Operator feedback</Text>
      <SwitchRow label="Scan sounds" hint="High beep = OK · two beeps = warning · low buzz = rejected (vibration always on)" value={sound} onChange={async (v) => { setSound(v); await setSoundEnabled(v); if (v) feedback('ok'); }} />
      <View style={S.row}>{[['ok', 'Test OK'], ['warn', 'Warn'], ['err', 'Error']].map(([k, l]) => <TouchableOpacity key={k} onPress={() => feedback(k)} style={[S.btnS, { flex: 1, marginTop: 0 }]}><Text style={S.btnSText}>{l}</Text></TouchableOpacity>)}</View>
      <Text style={[S.h2, { marginTop: 12 }]}>Text size</Text>
      <Segmented options={[[1, 'Normal'], [1.15, 'Large'], [1.3, 'Glove / outdoor']]} value={scale} onChange={async (v) => { setScale(v); await kv.set('ui_scale', v); applyTheme(T.key, v); onUi && onUi({}); }} />
      <Text style={S.h2}>Auto-lock when idle</Text>
      <Segmented options={[[0, 'Off'], [15, '15 min'], [30, '30 min'], [60, '60 min']]} value={idle} onChange={async (v) => { setIdle(v); await kv.set('idle_min', v); onUi && onUi({ idle_min: v }); }} />
      <Text style={S.mute}>After this time without a touch the password is asked again. Scans and the outbox are kept.</Text></View>
    <View style={S.card}><Text style={S.h2}>Theme</Text><Text style={S.mute}>Current: {THEMES[T.key].name}</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>{THEME_KEYS.map(k => <TouchableOpacity key={k} onPress={async () => { applyTheme(k); await kv.set('theme', k); onTheme && onTheme(k); toast('Theme: ' + THEMES[k].name); }} style={[S.btnS, { flex: 1, minWidth: '45%', marginTop: 0, minHeight: 44, justifyContent: 'center', backgroundColor: T.key === k ? C.accent : undefined }]}><Text style={[S.btnSText, T.key === k ? { color: '#fff' } : null]}>{THEMES[k].name}</Text></TouchableOpacity>)}</View></View>
    {customer ? null : <View style={S.card}><Text style={S.h2}>Data</Text><Btn title="Full resync of reference data" secondary icon="refresh-circle-outline" onPress={async () => { await syncNow({ full: true }); toast(sync.lastError || 'Resync done', sync.lastError ? 'err' : 'done'); }} /></View>}
    <Footer />
  </Page><Toast msg={msg} /></Screen>);
}

/** Any portable printer: connection, language, paper width and image mode are chosen here (not tied to one model). */
export function PrinterCard({ toast }) {
  const [cfg, setCfg] = useState(null); const [list, setList] = useState([]); const [sel, setSel] = useState(null); const [selName, setSelName] = useState(null); const [busy, setBusy] = useState(false);
  useEffect(() => { getConfig().then(setCfg); kv.get('printer').then(setSel); kv.get('printer_name').then(setSelName); }, []);
  if (!cfg) return null;
  const put = async (part) => { await setConfig(part); setCfg({ ...cfg, ...part }); };
  const run = async (fn) => { setBusy(true); try { await fn(); } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); } };
  const sys = cfg.conn === 'system'; const ble = cfg.conn === 'ble';
  return (<View style={S.card}><Text style={S.h2}>Printer (any portable printer)</Text>
    <Text style={S.mute}>Connection</Text>
    <Segmented options={CONNS} value={cfg.conn} onChange={(v) => { put({ conn: v }); setList([]); }} />
    {!connAvailable(cfg.conn) ? <Text style={[S.mute, { color: C.amber }]}>Not available in this build</Text> : null}
    {sys ? <Text style={S.mute}>Uses the Android print service - install the printer maker's print app / plugin (Bluetooth or Wi-Fi). Android asks which printer each time.</Text> : <>
      <Text style={S.mute}>Selected: {selName ? `${selName} (${sel})` : (sel || 'none')}</Text>
      <Text style={[S.mute, { marginTop: 4 }]}>{ble ? '1. Switch the printer on. 2. Scan and tap it. 3. Test print.' : '1. Switch the printer on. 2. Pair it once in Android Settings > Bluetooth. 3. List and tap it here. 4. Test print.'}</Text>
      <Btn title={ble ? 'Scan for printers (6 s)' : 'List paired printers'} secondary icon="bluetooth-outline" busy={busy} onPress={() => run(async () => { const l = await listPrinters(cfg.conn); setList(l); if (!l.length) toast(ble ? 'No Bluetooth LE devices found - is the printer on?' : 'No paired devices - pair the printer in Android Settings first', 'warn'); })} />
      {list.map(p => <TouchableOpacity key={p.id} onPress={() => run(async () => { await connect(p.id, cfg.conn); await kv.set('printer_name', p.name); setSel(p.id); setSelName(p.name); toast('Connected ' + p.name); })} style={[S.btnS, { alignItems: 'flex-start', backgroundColor: sel === p.id ? C.ok : undefined }]}><Text style={[S.btnSText, sel === p.id ? { color: '#fff' } : null]}>{p.name}  {p.id}</Text></TouchableOpacity>)}
      <Text style={[S.mute, { marginTop: 8 }]}>Printer language</Text>
      <Segmented options={LANGS} value={cfg.lang} onChange={(v) => put({ lang: v })} />
      <Text style={S.mute}>ESC/POS: most receipt printers (SEZNIK, Xprinter, Rongta, Epson, MTP). CPCL: Zebra / Honeywell mobile. ZPL: Zebra. TSPL: TSC / label printers.</Text>
      {cfg.lang === 'escpos' ? <><Text style={[S.mute, { marginTop: 8 }]}>Logo / QR printing</Text>
        <Segmented options={IMGS} value={cfg.img} onChange={(v) => put({ img: v })} />
        <Text style={S.mute}>Logo or QR missing / garbled: try Old ESC*. Still wrong: Text only (printer draws its own QR).</Text></> : null}
    </>}
    <Text style={[S.mute, { marginTop: 8 }]}>Paper width</Text>
    <Segmented options={WIDTHS} value={String(cfg.dots)} onChange={(v) => put({ dots: Number(v) })} />
    {(sys || sel) ? <Btn title="Test print" icon="print-outline" busy={busy} onPress={() => run(async () => { await testPrint(await kv.get('plant')); toast('Test sent - check the printer'); logActivity('PRINT_TEST', sel || 'system', `${cfg.conn} ${cfg.lang} ${cfg.dots}`); })} /> : null}
    {!sys && sel ? <Btn title="Find my printer language" secondary icon="help-circle-outline" busy={busy} onPress={() => run(async () => { await findLanguage(); toast('4 samples sent - choose the language whose sample printed clean text', 'warn'); })} /> : null}
    {!sys ? <Text style={[S.mute, { marginTop: 6 }]}>{'Unknown printer? Tap "Find my printer language": it prints one short sample per language. Choose the one that printed a clean ">> NAME <<" heading (the others print code like "! 0 200", "^XA", "TEXT" or nothing).'}</Text> : null}
  </View>);
}

function ScanModeCard() {
  const m = useScanMode();
  return (<View style={S.card}><Text style={S.h2}>Scanning</Text>
    <Segmented options={[['native', 'Built-in scanner'], ['camera', 'Camera']]} value={m} onChange={setScanMode} />
    <Text style={S.mute}>Built-in scanner: HHTs with a scan key (or a Bluetooth ring scanner). Camera: any Android phone / tablet. Also switchable on every scan screen.</Text></View>);
}
