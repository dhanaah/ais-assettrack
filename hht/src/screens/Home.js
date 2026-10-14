// Home: live status strip, what is waiting (counts from the local cache), quick lookup, functions grouped by area (Gate-In,
// Yard-In, Internal Move, Yard-Out / Dispatch, Gate-Out, Others) and by access right. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { S, C, Page, Header, Footer, Screen, ScanInput, T, UserChip, ButtonGroup } from '../ui/kit';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { openDb, kv } from '../lib/db';
import { checkUpdate, openUpdate } from '../lib/update';
import { getActiveServer } from '../lib/api';
import { fTime } from '../lib/when';

// Functions grouped by where the work happens, in the order a pallet moves: Gate-In -> Yard-In -> Internal move ->
// Yard-Out / dispatch -> Gate-Out, then Others. [key, title, sub, permission, icon, badge key]. Same screens as before.
const MV = 'INTERNAL_MOVE';   // the old "all internal moves" permission still opens every move button
const GROUPS = [
  { key: 'gin', title: 'Security · Gate-In', sub: 'Every vehicle coming in is endorsed here', icon: 'enter-outline', grad: ['#c026d3', '#a21caf'], items: [
    ['gatein', 'IN Gate', 'Slip A QR · other-plant challan (material or empty)', 'IN_GATE_SCAN', 'enter-outline'],
    ['slip', 'Return Slip (Option B)', 'Made at the gate: count + document photo', 'RETURN_SLIP_B', 'document-text-outline'] ] },
  { key: 'yin', title: 'Yard-In', sub: 'Empty pallets only · scan the pallet QR', icon: 'layers-outline', grad: ['#10b981', '#047857'], items: [
    ['yard', 'Customer returns', 'Slips A / B endorsed at Gate-In', 'YARD_SCAN', 'people-outline', 'slipsCust'],
    ['yardchl', 'Empty pallets from other plants', 'Plant challan endorsed at Gate-In', 'YARD_IN_PLANT', 'business-outline', 'slipsChl'],
    ['mvyard', 'Empty pallets back to Yard', 'From Production / FGWH / Packing', ['MOVE_TO_YARD', MV], 'arrow-undo-outline'],
    ['damage', 'Damage / Tag issue', 'Mark damaged, request a new tag', 'DAMAGE_MARK', 'warning-outline'] ] },
  { key: 'yout', title: 'Yard-Out', sub: 'Empty pallets leaving the yard · scan the pallet QR', icon: 'log-out-outline', grad: ['#14b8a6', '#0f766e'], items: [
    ['mvprod', 'Empty pallets to Production', 'Pallet Yard → Production', ['MOVE_TO_PRODUCTION', MV], 'construct-outline'],
    ['mvpackE', 'Empty pallets to Packing', 'Pallet Yard → Packing', ['YARD_TO_PACKING', MV], 'cube-outline'],
    ['yardret', 'Empty pallets to other plants', 'Load on the empty-return challan', 'EMPTY_RETURN', 'return-up-back-outline', 'yardret'] ] },
  { key: 'fg', title: 'FGWH · Central FG', sub: 'All finished goods pass through FGWH · pallet card', icon: 'business-outline', grad: ['#8b5cf6', '#6d28d9'], items: [
    ['mvfg', 'Production → FGWH', 'Loaded pallets from the line', ['MOVE_TO_FGWH', MV], 'arrow-forward-outline'],
    ['receipt', 'Other-plant material', 'At FGWH · challan endorsed at Gate-In', 'PLANT_RECEIPT', 'download-outline', 'chm'],
    ['mvmain', 'FGWH → Main Dispatch', 'Pallet card', ['MOVE_TO_DISPATCH', MV], 'arrow-redo-outline'],
    ['mvpk', 'FGWH → Packing', 'Pallet card', ['MOVE_TO_PACKING', MV], 'arrow-redo-outline'] ] },
  { key: 'md', title: 'Main Dispatch', sub: 'Ships parts to customers · pallet card', icon: 'car-outline', grad: ['#0ea5e9', '#0369a1'], items: [
    ['dock', 'Dispatch preparation', 'Pallet cards against the GCS', 'DOCK_SCAN', 'clipboard-outline', 'dock'],
    ['pdi', 'PDI Check', 'Pallet card OK / reject → EBS', 'PDI_CHECK', 'shield-checkmark-outline', 'pdi'] ] },
  { key: 'pk', title: 'Packing · Dispatch', sub: 'Ships parts to customers · pallet card', icon: 'cube-outline', grad: ['#ec4899', '#be185d'], items: [
    ['dockP', 'Dispatch preparation', 'Pallet cards against the GCS', 'PACK_DISPATCH', 'clipboard-outline', 'dock'],
    ['pdiP', 'PDI Check', 'Pallet card OK / reject → EBS', 'PACK_PDI', 'shield-checkmark-outline', 'pdi'] ] },
  { key: 'gout', title: 'Security · Loading & Gate-Out', sub: 'Every vehicle going out is endorsed here', icon: 'exit-outline', grad: ['#3b82f6', '#4338ca'], items: [
    ['load', 'Vehicle loading', 'Each pallet QR into the vehicle · FGWH / Packing', 'VEHICLE_LOAD', 'car-outline'],
    ['gateout', 'OUT Gate', 'Challan QR only · Yard empties · FGWH & Packing material', 'OUT_GATE_SCAN', 'exit-outline'] ] },
  { key: 'oth', title: 'Others', sub: 'Look up, alerts, sync', icon: 'apps-outline', grad: ['#64748b', '#334155'], items: [
    ['lookup', 'Pallet / LPN Lookup', 'Status, loaded / empty, zone', null, 'search-outline'],
    ['misses', 'Missed Scans', 'Open scan alerts', null, 'alert-circle-outline'],
    ['pending', 'Pending & Sync', 'Outbox, last sync, errors', null, 'cloud-upload-outline', 'pending'] ] },
];

async function counts() {
  const d = await openDb();
  const one = async (sql, ...a) => (await d.getFirstAsync(sql, ...a))?.c || 0;
  const today = new Date(); today.setHours(0, 0, 0, 0); const t0 = today.toISOString();
  return {
    dock: await one("SELECT COUNT(*) c FROM picklists WHERE status='OPEN' AND (load_point IS NULL OR load_point<>'YARD')"),
    yardret: await one("SELECT COUNT(*) c FROM picklists WHERE status='OPEN' AND load_point='YARD'"),
    pdi: await one("SELECT COUNT(*) c FROM picklists WHERE status='PDI_PENDING'"),
    slipsCust: await one("SELECT COUNT(*) c FROM slips WHERE status<>'CLOSED' AND mode NOT IN ('CHL','CHM')"),
    chm: await one("SELECT COUNT(*) c FROM slips WHERE status<>'CLOSED' AND mode='CHM'"),
    slipsChl: await one("SELECT COUNT(*) c FROM slips WHERE status<>'CLOSED' AND mode='CHL'"),
    pending: await one("SELECT COUNT(*) c FROM outbox WHERE status='PENDING'"),
    rejected: await one("SELECT COUNT(*) c FROM outbox WHERE status='REJECTED' AND created_at>=?", t0),
    scansToday: await one("SELECT COUNT(*) c FROM outbox WHERE created_at>=? AND event_type<>'HEARTBEAT'", t0),
    lastScan: (await d.getFirstAsync("SELECT local_ts t FROM outbox WHERE event_type<>'HEARTBEAT' ORDER BY local_ts DESC LIMIT 1"))?.t || null,
  };
}

export default function Home({ me, sync, nav, onLogout, onLookup }) {
  const perms = me.perms || []; const benchMode = (me.picklist_source || 'BENCH') === 'BENCH';
  const [n, setN] = useState({}); const [upd, setUpd] = useState(null);
  useEffect(() => { let on = true; const load = () => counts().then(x => on && setN(x)).catch(() => { }); load(); const t = setInterval(load, 15000); return () => { on = false; clearInterval(t); }; }, [sync.lastSync, sync.pending]);
  useEffect(() => { if (sync.online) checkUpdate().then(u => u && u.newer && setUpd(u)); }, [sync.online]);
  const col = !sync.online ? C.warn : sync.pending ? C.amber : C.ok;
  const srv = (getActiveServer() || '').replace(/^https?:\/\//, '');
  const allowed = (it) => (!it[3] || [].concat(it[3]).some((x) => perms.includes(x))) && !(benchMode && (it[0] === 'pdi' || it[0] === 'pdiP'));
  const group = (g) => <ButtonGroup key={g.key} g={g} items={g.items.filter(allowed)} n={n} nav={nav} />;
  return (<Screen>
    <Header logo below={<UserChip me={me} onLogout={onLogout} />} />
    <TouchableOpacity onPress={() => nav('pending')} style={{ backgroundColor: col, paddingVertical: 7, paddingHorizontal: 14, marginHorizontal: 14, marginTop: 10, borderRadius: 999, flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start', maxWidth: '92%' }}>
      <Ionicons name={sync.online ? 'wifi' : 'cloud-offline-outline'} size={14} color="#fff" /><Text style={{ color: '#fff', fontWeight: '700', fontSize: 12.5 }} numberOfLines={1}>{sync.online ? 'ONLINE' : 'OFFLINE'} · {sync.pending} pending{sync.syncing ? ' · syncing…' : ''}{sync.lastSync ? ' · synced ' + fTime(sync.lastSync) : ''}{sync.lastError && sync.lastError !== 'LOGIN' ? ' · ' + sync.lastError : ''}</Text></TouchableOpacity>
    <Page>
      {upd ? <TouchableOpacity onPress={() => openUpdate(upd)} style={[S.card, { borderLeftWidth: 5, borderLeftColor: upd.required ? C.warn : C.accent, flexDirection: 'row', alignItems: 'center', gap: 10 }]}><Ionicons name="cloud-download-outline" size={24} color={upd.required ? C.warn : C.accent} /><View style={{ flex: 1 }}><Text style={{ fontWeight: '700', color: C.fg }}>AssetTrack app v{upd.version} available{upd.required ? ' - update required' : ''}</Text><Text style={S.mute}>Tap to download, then open the file to install.</Text></View></TouchableOpacity> : null}
      <View style={[S.card, { flexDirection: 'row', justifyContent: 'space-around', paddingVertical: 10 }]}>
        {[[n.scansToday || 0, 'scans today', C.accent], [n.pending || 0, 'to sync', n.pending ? C.amber : C.ok], [n.rejected || 0, 'rejected today', n.rejected ? C.warn : C.ok], [n.lastScan ? fTime(n.lastScan) : '—', 'last scan', C.mute]].map(([v, l, c]) => (
          <View key={l} style={{ alignItems: 'center' }}><Text style={{ fontSize: Math.round(22 * T.scale), fontWeight: '800', color: c }}>{v}</Text><Text style={[S.mute, { fontSize: 11 }]}>{l}</Text></View>))}
      </View>
      <View style={[S.card, { paddingVertical: 10 }]}><Text style={[S.mute, { marginBottom: 4 }]}>Quick lookup - scan any pallet, tag or LPN</Text><ScanInput autoFocus={false} placeholder="Scan to look up" onScan={(code) => onLookup && onLookup(code)} /></View>
      {GROUPS.map(group)}
      <TouchableOpacity onPress={() => nav('settings')} style={{ marginTop: 16 }}><Text style={[S.mute, { textAlign: 'center' }]}>Settings · Printer · Sound · Full resync</Text></TouchableOpacity>
      <Footer />
    </Page></Screen>);
}
