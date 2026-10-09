import React from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { S, C, Page, Header, Footer, GRAD, Screen } from '../ui/kit';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';

const TILES = [
  ['dock', 'Dock Out-ward Scan', 'Scan pallets to a pick list', 'DOCK_SCAN', ['#0ea5e9', '#2563eb'], 'cube-outline'],
  ['gateout', 'OUT Gate', 'Scan GCS / challan QR', 'OUT_GATE_SCAN', ['#6366f1', '#4338ca'], 'exit-outline'],
  ['slip', 'Return Slip (B1 / B2)', 'Create slip at IN gate', 'RETURN_SLIP_B', ['#a855f7', '#7e22ce'], 'document-text-outline'],
  ['gatein', 'IN Gate', 'Scan return slip QR', 'IN_GATE_SCAN', ['#c026d3', '#a21caf'], 'enter-outline'],
  ['yard', 'Yard In-ward Scan', 'Receive pallets, reconcile', 'YARD_SCAN', ['#10b981', '#047857'], 'layers-outline'],
  ['damage', 'Damage / Tag issue', 'Mark damaged, request tag', 'DAMAGE_MARK', ['#f59e0b', '#d97706'], 'warning-outline'],
  ['lookup', 'Pallet Lookup', 'Status of any tag', null, ['#64748b', '#334155'], 'search-outline'],
  ['pending', 'Pending & Sync', 'Outbox, last sync, errors', null, ['#ec4899', '#be185d'], 'cloud-upload-outline'],
];

export default function Home({ me, sync, nav, onLogout }) {
  const perms = me.perms || [];
  const col = !sync.online ? C.warn : sync.pending ? C.amber : C.ok;
  return (<Screen>
    <Header logo sub={`${me.name} · ${me.plant} · ${me.roles.join(', ')}`} right={<TouchableOpacity onPress={onLogout}><Text style={{ color: '#fff' }}>Logout</Text></TouchableOpacity>} />
    <TouchableOpacity onPress={() => nav('pending')} style={{ backgroundColor: col, paddingVertical: 7, paddingHorizontal: 14, marginHorizontal: 14, marginTop: 10, borderRadius: 999, flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start' }}>
      <Ionicons name={sync.online ? 'wifi' : 'cloud-offline-outline'} size={14} color="#fff" /><Text style={{ color: '#fff', fontWeight: '700', fontSize: 12.5 }}>{sync.online ? 'ONLINE' : 'OFFLINE'} · {sync.pending} pending{sync.syncing ? ' · syncing…' : ''}{sync.lastSync ? ' · last sync ' + sync.lastSync.slice(11, 16) : ''}{sync.lastError && sync.lastError !== 'LOGIN' ? ' · ' + sync.lastError : ''}</Text></TouchableOpacity>
    <Page>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
        {TILES.filter(t => !t[3] || perms.includes(t[3])).map(t => (
          <TouchableOpacity key={t[0]} onPress={() => nav(t[0])} activeOpacity={0.8} style={[S.card, { width: '47.5%', marginBottom: 0, minHeight: 118 }]}>
            <LinearGradient colors={t[4]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', marginBottom: 8, shadowColor: t[4][1], shadowOpacity: 0.4, shadowRadius: 8, elevation: 3 }}><Ionicons name={t[5]} size={22} color="#fff" /></LinearGradient>
            <Text style={{ fontWeight: '700', fontSize: 14, color: C.fg }}>{t[1]}</Text><Text style={[S.mute, { marginTop: 3, fontSize: 11.5 }]}>{t[2]}</Text></TouchableOpacity>))}
      </View>
      <TouchableOpacity onPress={() => nav('settings')} style={{ marginTop: 16 }}><Text style={[S.mute, { textAlign: 'center' }]}>Settings · Printer · Full resync</Text></TouchableOpacity>
      <Footer />
    </Page></Screen>);
}
