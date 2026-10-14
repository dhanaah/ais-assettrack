// Home: live status strip, what is waiting (counts from the local cache), quick lookup, functions grouped by area (Gate-In,
// Yard-In, Internal Move, Yard-Out / Dispatch, Gate-Out, Others) and by access right. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { S, C, Page, Header, Footer, Screen, ScanInput, T, UserChip } from '../ui/kit';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { openDb, kv } from '../lib/db';
import { checkUpdate, openUpdate } from '../lib/update';
import { getActiveServer } from '../lib/api';
import { fTime } from '../lib/when';

// Functions grouped by where the work happens, in the order a pallet moves: Gate-In -> Yard-In -> Internal move ->
// Yard-Out / dispatch -> Gate-Out, then Others. [key, title, sub, permission, icon, badge key]. Same screens as before.
const GROUPS = [
  { key: 'gin', title: 'Gate-In', sub: 'Vehicles coming in', icon: 'enter-outline', grad: ['#c026d3', '#a21caf'], items: [
    ['gatein', 'IN Gate', 'Return slip QR · other-plant challan QR', 'IN_GATE_SCAN', 'enter-outline'],
    ['slip', 'Return Slip (Option B)', 'Customer without slip: count + document photo', 'RETURN_SLIP_B', 'document-text-outline'] ] },
  { key: 'yin', title: 'Yard-In', sub: 'Empty pallets received at the pallet yard', icon: 'layers-outline', grad: ['#10b981', '#047857'], items: [
    ['yard', 'Customer returns', 'Return slips Option A / B - scan & reconcile', 'YARD_SCAN', 'people-outline', 'slipsCust'],
    ['yardchl', 'Empty pallets from other plants', 'Our pallets back on an AIS plant challan', 'YARD_SCAN', 'business-outline', 'slipsChl'],
    ['damage', 'Damage / Tag issue', 'Mark damaged, request a new tag', 'DAMAGE_MARK', 'warning-outline'] ] },
  { key: 'mov', title: 'Internal Move', sub: 'Inside the plant', icon: 'swap-horizontal-outline', grad: ['#22c55e', '#15803d'], items: [
    ['move', 'Internal Movement', 'Yard · Production · FGWH · Packing', 'INTERNAL_MOVE', 'swap-horizontal-outline'],
    ['receipt', 'Other-plant Receipt (loaded)', 'Loaded pallets from other plants at FGWH / Packing', 'PLANT_RECEIPT', 'download-outline'] ] },
  { key: 'yout', title: 'Yard-Out / Dispatch', sub: 'Loading vehicles', icon: 'cube-outline', grad: ['#0ea5e9', '#2563eb'], items: [
    ['dock', 'Vehicle Loading (GCS)', 'Scan pallets / part cards against the GCS', 'DOCK_SCAN', 'cube-outline', 'dock'],
    ['pdi', 'PDI Check', 'LPN OK / reject → EBS', 'PDI_CHECK', 'shield-checkmark-outline', 'pdi'],
    ['yardret', 'Empty pallets to other plants', "Other plants' pallets from the Yard → challan", 'EMPTY_RETURN', 'return-up-back-outline', 'yardret'] ] },
  { key: 'gout', title: 'Gate-Out', sub: 'Vehicles going out', icon: 'exit-outline', grad: ['#6366f1', '#4338ca'], items: [
    ['gateout', 'OUT Gate', 'Scan GCS / challan QR', 'OUT_GATE_SCAN', 'exit-outline'] ] },
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
    slipsCust: await one("SELECT COUNT(*) c FROM slips WHERE status<>'CLOSED' AND mode<>'CHL'"),
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
  const allowed = (it) => (!it[3] || perms.includes(it[3])) && !(benchMode && it[0] === 'pdi');
  const row = (it, g, last) => { const badge = it[5] ? n[it[5]] : 0;
    return (<TouchableOpacity key={it[0]} onPress={() => nav(it[0])} activeOpacity={0.75} style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: Math.round(11 * T.scale), borderBottomWidth: last ? 0 : 1, borderBottomColor: C.line }}>
      <View style={{ width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: g.grad[0] + '22' }}><Ionicons name={it[4]} size={20} color={g.grad[0]} /></View>
      <View style={{ flex: 1 }}><Text style={{ fontWeight: '700', fontSize: Math.round(14.5 * T.scale), color: C.fg }}>{it[1]}</Text><Text style={[S.mute, { fontSize: Math.round(11.5 * T.scale), marginTop: 1 }]} numberOfLines={2}>{it[2]}</Text></View>
      {badge ? <View style={{ backgroundColor: it[0] === 'pending' ? C.amber : g.grad[0], borderRadius: 999, minWidth: 26, height: 24, paddingHorizontal: 8, alignItems: 'center', justifyContent: 'center' }}><Text style={{ color: '#fff', fontWeight: '800', fontSize: 12.5 }}>{badge}</Text></View> : null}
      <Ionicons name="chevron-forward" size={18} color={C.mute} /></TouchableOpacity>); };
  const group = (g) => { const items = g.items.filter(allowed); if (!items.length) return null;
    const waiting = items.reduce((a, it) => a + (it[5] && it[0] !== 'pending' ? (n[it[5]] || 0) : 0), 0);
    return (<View key={g.key} style={[S.card, { paddingVertical: 10 }]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingBottom: 6 }}>
        <LinearGradient colors={g.grad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ width: 30, height: 30, borderRadius: 10, alignItems: 'center', justifyContent: 'center' }}><Ionicons name={g.icon} size={17} color="#fff" /></LinearGradient>
        <View style={{ flex: 1 }}><Text style={{ fontWeight: '800', fontSize: Math.round(15.5 * T.scale), color: C.fg, letterSpacing: 0.3 }}>{g.title.toUpperCase()}</Text><Text style={[S.mute, { fontSize: 11 }]}>{g.sub}</Text></View>
        {waiting ? <Text style={{ color: g.grad[0], fontWeight: '800', fontSize: 12 }}>{waiting} waiting</Text> : null}
      </View>
      {items.map((it, k) => row(it, g, k === items.length - 1))}</View>); };
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
