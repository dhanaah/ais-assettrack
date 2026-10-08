import React from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { S, C, Page, Header, Footer } from '../ui/kit';

const TILES = [
  ['dock', 'Dock Out-ward Scan', 'Scan pallets to a pick list', 'DOCK_SCAN', '#0ea5e9'],
  ['gateout', 'OUT Gate', 'Scan GCS / challan QR', 'OUT_GATE_SCAN', '#6366f1'],
  ['slip', 'Return Slip (B1 / B2)', 'Create slip at IN gate', 'RETURN_SLIP_B', '#8b5cf6'],
  ['gatein', 'IN Gate', 'Scan return slip QR', 'IN_GATE_SCAN', '#a855f7'],
  ['yard', 'Yard In-ward Scan', 'Receive pallets, reconcile', 'YARD_SCAN', '#10b981'],
  ['damage', 'Damage / Tag issue', 'Mark damaged, request tag', 'DAMAGE_MARK', '#f59e0b'],
  ['lookup', 'Pallet Lookup', 'Status of any tag', null, '#64748b'],
  ['pending', 'Pending & Sync', 'Outbox, last sync, errors', null, '#ec4899'],
];

export default function Home({ me, sync, nav, onLogout }) {
  const perms = me.perms || [];
  const col = !sync.online ? C.warn : sync.pending ? C.amber : C.ok;
  return (<View style={{ flex: 1 }}>
    <Header logo sub={`${me.name} · ${me.plant} · ${me.roles.join(', ')}`} right={<TouchableOpacity onPress={onLogout}><Text style={{ color: '#fff' }}>Logout</Text></TouchableOpacity>} />
    <TouchableOpacity onPress={() => nav('pending')} style={{ backgroundColor: col, paddingVertical: 6, paddingHorizontal: 14 }}>
      <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12.5 }}>{sync.online ? 'ONLINE' : 'OFFLINE'} · {sync.pending} pending{sync.syncing ? ' · syncing…' : ''}{sync.lastSync ? ' · last sync ' + sync.lastSync.slice(11, 16) : ''}{sync.lastError && sync.lastError !== 'LOGIN' ? ' · ' + sync.lastError : ''}</Text></TouchableOpacity>
    <Page>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
        {TILES.filter(t => !t[3] || perms.includes(t[3])).map(t => (
          <TouchableOpacity key={t[0]} onPress={() => nav(t[0])} style={[S.card, { width: '47.5%', marginBottom: 0, borderLeftWidth: 5, borderLeftColor: t[4], minHeight: 96 }]}>
            <Text style={{ fontWeight: '700', fontSize: 14.5, color: C.fg }}>{t[1]}</Text><Text style={[S.mute, { marginTop: 4 }]}>{t[2]}</Text></TouchableOpacity>))}
      </View>
      <TouchableOpacity onPress={() => nav('settings')} style={{ marginTop: 16 }}><Text style={[S.mute, { textAlign: 'center' }]}>Settings · Printer · Full resync</Text></TouchableOpacity>
      <Footer />
    </Page></View>);
}
