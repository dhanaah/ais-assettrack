// Home: live status strip, what is waiting (counts from the local cache), quick lookup, tiles by access right. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { S, C, Page, Header, Footer, Screen, ScanInput, T } from '../ui/kit';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { openDb, kv } from '../lib/db';
import { checkUpdate, openUpdate } from '../lib/update';
import { getActiveServer } from '../lib/api';

const TILES = [
  ['dock', 'Vehicle Loading (GCS)', 'Scan pallets / part cards against the GCS', 'DOCK_SCAN', ['#0ea5e9', '#2563eb'], 'cube-outline', 'dock'],
  ['pdi', 'PDI Check', 'LPN OK / reject → EBS', 'PDI_CHECK', ['#14b8a6', '#0f766e'], 'shield-checkmark-outline', 'pdi'],
  ['move', 'Internal Movement', 'Yard · Production · FGWH · Packing', 'INTERNAL_MOVE', ['#22c55e', '#15803d'], 'swap-horizontal-outline'],
  ['receipt', 'Other-plant Receipt', 'Loaded pallets at FGWH / Packing', 'PLANT_RECEIPT', ['#8b5cf6', '#6d28d9'], 'download-outline'],
  ['yardret', 'Empty Pallet Return', "Other plants' pallets at Yard → challan", 'EMPTY_RETURN', ['#84cc16', '#4d7c0f'], 'return-up-back-outline', 'yardret'],
  ['gateout', 'OUT Gate', 'Scan GCS / challan QR', 'OUT_GATE_SCAN', ['#6366f1', '#4338ca'], 'exit-outline'],
  ['slip', 'Return Slip (B1 / B2)', 'Create slip at IN gate', 'RETURN_SLIP_B', ['#a855f7', '#7e22ce'], 'document-text-outline'],
  ['gatein', 'IN Gate', 'Scan return slip QR', 'IN_GATE_SCAN', ['#c026d3', '#a21caf'], 'enter-outline'],
  ['yard', 'Yard In-ward Scan', 'Receive pallets, reconcile', 'YARD_SCAN', ['#10b981', '#047857'], 'layers-outline', 'slips'],
  ['damage', 'Damage / Tag issue', 'Mark damaged, request tag', 'DAMAGE_MARK', ['#f59e0b', '#d97706'], 'warning-outline'],
  ['lookup', 'Pallet / LPN Lookup', 'Status, loaded / empty, zone', null, ['#64748b', '#334155'], 'search-outline'],
  ['misses', 'Missed Scans', 'Open scan alerts', null, ['#ef4444', '#b91c1c'], 'alert-circle-outline'],
  ['pending', 'Pending & Sync', 'Outbox, last sync, errors', null, ['#ec4899', '#be185d'], 'cloud-upload-outline', 'pending'],
];

async function counts() {
  const d = await openDb();
  const one = async (sql, ...a) => (await d.getFirstAsync(sql, ...a))?.c || 0;
  const today = new Date(); today.setHours(0, 0, 0, 0); const t0 = today.toISOString();
  return {
    dock: await one("SELECT COUNT(*) c FROM picklists WHERE status='OPEN' AND (load_point IS NULL OR load_point<>'YARD')"),
    yardret: await one("SELECT COUNT(*) c FROM picklists WHERE status='OPEN' AND load_point='YARD'"),
    pdi: await one("SELECT COUNT(*) c FROM picklists WHERE status='PDI_PENDING'"),
    slips: await one("SELECT COUNT(*) c FROM slips WHERE status<>'CLOSED'"),
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
  const tile = (t) => {
    const badge = t[6] ? n[t[6]] : 0;
    return (<TouchableOpacity key={t[0]} onPress={() => nav(t[0])} activeOpacity={0.8} style={[S.card, { width: '47.5%', marginBottom: 0, minHeight: Math.round(118 * T.scale) }]}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <LinearGradient colors={t[4]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', marginBottom: 8, shadowColor: t[4][1], shadowOpacity: 0.4, shadowRadius: 8, elevation: 3 }}><Ionicons name={t[5]} size={22} color="#fff" /></LinearGradient>
        {badge ? <View style={{ backgroundColor: t[0] === 'pending' ? C.amber : C.accent, borderRadius: 999, minWidth: 26, height: 26, paddingHorizontal: 8, alignItems: 'center', justifyContent: 'center' }}><Text style={{ color: '#fff', fontWeight: '800', fontSize: 13 }}>{badge}</Text></View> : null}
      </View>
      <Text style={{ fontWeight: '700', fontSize: Math.round(14 * T.scale), color: C.fg }}>{t[1]}</Text><Text style={[S.mute, { marginTop: 3, fontSize: Math.round(11.5 * T.scale) }]}>{t[2]}</Text></TouchableOpacity>);
  };
  return (<Screen>
    <Header logo sub={`${me.name} · ${me.plant} · ${me.roles.join(', ')}`} right={<TouchableOpacity onPress={onLogout} style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}><Ionicons name="log-out-outline" size={18} color="#fff" /><Text style={{ color: '#fff' }}>Logout</Text></TouchableOpacity>} />
    <TouchableOpacity onPress={() => nav('pending')} style={{ backgroundColor: col, paddingVertical: 7, paddingHorizontal: 14, marginHorizontal: 14, marginTop: 10, borderRadius: 999, flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start', maxWidth: '92%' }}>
      <Ionicons name={sync.online ? 'wifi' : 'cloud-offline-outline'} size={14} color="#fff" /><Text style={{ color: '#fff', fontWeight: '700', fontSize: 12.5 }} numberOfLines={1}>{sync.online ? 'ONLINE' : 'OFFLINE'} · {sync.pending} pending{sync.syncing ? ' · syncing…' : ''}{sync.lastSync ? ' · synced ' + sync.lastSync.slice(11, 16) : ''}{srv ? ' · ' + srv : ''}{sync.lastError && sync.lastError !== 'LOGIN' ? ' · ' + sync.lastError : ''}</Text></TouchableOpacity>
    <Page>
      {upd ? <TouchableOpacity onPress={() => openUpdate(upd)} style={[S.card, { borderLeftWidth: 5, borderLeftColor: upd.required ? C.warn : C.accent, flexDirection: 'row', alignItems: 'center', gap: 10 }]}><Ionicons name="cloud-download-outline" size={24} color={upd.required ? C.warn : C.accent} /><View style={{ flex: 1 }}><Text style={{ fontWeight: '700', color: C.fg }}>AssetTrack app v{upd.version} available{upd.required ? ' - update required' : ''}</Text><Text style={S.mute}>Tap to download, then open the file to install.</Text></View></TouchableOpacity> : null}
      <View style={[S.card, { flexDirection: 'row', justifyContent: 'space-around', paddingVertical: 10 }]}>
        {[[n.scansToday || 0, 'scans today', C.accent], [n.pending || 0, 'to sync', n.pending ? C.amber : C.ok], [n.rejected || 0, 'rejected today', n.rejected ? C.warn : C.ok], [n.lastScan ? String(n.lastScan).slice(11, 16) : '—', 'last scan', C.mute]].map(([v, l, c]) => (
          <View key={l} style={{ alignItems: 'center' }}><Text style={{ fontSize: Math.round(22 * T.scale), fontWeight: '800', color: c }}>{v}</Text><Text style={[S.mute, { fontSize: 11 }]}>{l}</Text></View>))}
      </View>
      <View style={[S.card, { paddingVertical: 10 }]}><Text style={[S.mute, { marginBottom: 4 }]}>Quick lookup - scan any pallet, tag or LPN</Text><ScanInput autoFocus={false} placeholder="Scan to look up" onScan={(code) => onLookup && onLookup(code)} /></View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>{TILES.filter(t => (!t[3] || perms.includes(t[3])) && !(benchMode && t[0] === 'pdi')).map(tile)}</View>
      <TouchableOpacity onPress={() => nav('settings')} style={{ marginTop: 16 }}><Text style={[S.mute, { textAlign: 'center' }]}>Settings · Printer · Sound · Full resync</Text></TouchableOpacity>
      <Footer />
    </Page></Screen>);
}
