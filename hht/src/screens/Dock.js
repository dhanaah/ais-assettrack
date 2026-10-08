// Dock out-ward scan: pick list → scan each tag → Pick List Control → confirm (online). Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, FlatList, Alert } from 'react-native';
import { S, C, Btn, Page, Header, ScanInput, Pill, useToast, Toast } from '../ui/kit';
import { listPicklists, enqueue, addLocalScan, localScans, removeLocalScan, setPalletLocal } from '../lib/db';
import { validateDockScan } from '../lib/rules';
import { api } from '../lib/api';
import { state as sync, syncNow } from '../lib/sync';

export default function Dock({ onBack }) {
  const [lists, setLists] = useState([]); const [pk, setPk] = useState(null); const [scans, setScans] = useState([]); const [msg, toast] = useToast();
  const load = async () => setLists(await listPicklists());
  useEffect(() => { load(); }, []);
  const open = async (k) => { setPk(k); setScans(await localScans(k.picklist_no)); };

  const onScan = async (code) => {
    const v = await validateDockScan(pk.picklist_no, code);
    if (!v.ok) { toast(v.msg, v.dup ? 'warn' : 'err'); return; }
    await addLocalScan(pk.picklist_no, v.pallet.pallet_no);
    await setPalletLocal(v.pallet.pallet_no, { status: 'ALLOCATED', picklist: pk.picklist_no });
    await enqueue('PALLET_SCAN_DOCK', { picklist_no: pk.picklist_no, scanned: code }, !sync.online);
    setScans(await localScans(pk.picklist_no)); toast(`${v.pallet.pallet_no}  ${v.count}/${v.qty}`);
    if (sync.online) syncNow().catch(() => {});
  };
  const remove = (p) => Alert.alert('Remove pallet', p.pallet_no + ' from this list?', [{ text: 'Cancel' }, { text: 'Remove', style: 'destructive', onPress: async () => {
    await removeLocalScan(pk.picklist_no, p.pallet_no); await setPalletLocal(p.pallet_no, { status: 'AVAILABLE', picklist: null });
    await enqueue('PALLET_UNSCAN_DOCK', { picklist_no: pk.picklist_no, scanned: p.pallet_no }, !sync.online); setScans(await localScans(pk.picklist_no)); } }]);
  const confirm = async () => {
    if (scans.length !== pk.qty) return toast(`Pick List Control: ${scans.length} scanned vs qty ${pk.qty}`, 'err');
    if (!sync.online) return toast('Confirm needs the server (offline). Scans are saved; confirm when online.', 'warn');
    try { await syncNow(); const r = await api(`/picklists/${pk.picklist_no}/confirm`, { method: 'POST' }); toast(`${pk.picklist_no} is ${r.status}`); setPk(null); await syncNow(); load(); }
    catch (e) { toast(e.message, 'err'); }
  };

  if (!pk) return (<View style={{ flex: 1 }}><Header title="Dock Out-ward Scan" sub="Select a pick list" onBack={onBack} /><Page>
    {lists.length === 0 ? <Text style={S.mute}>No open pick lists in cache. Create one on the web app, then sync.</Text> : null}
    {lists.map(k => <TouchableOpacity key={k.picklist_no} style={S.card} onPress={() => open(k)}>
      <View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{k.picklist_no}</Text><Pill s={k.status} /></View>
      <Text style={S.mute}>Customer {k.customer} · {k.type || 'any type'} · qty {k.qty} · scanned {k.scanned}</Text></TouchableOpacity>)}
    <Btn title="Refresh" secondary onPress={async () => { await syncNow(); load(); }} /></Page><Toast msg={msg} /></View>);

  return (<View style={{ flex: 1 }}><Header title={pk.picklist_no} sub={`Customer ${pk.customer} · ${pk.type || 'any'}`} onBack={() => setPk(null)} />
    <View style={[S.pad, { paddingBottom: 0 }]}>
      <View style={[S.card, { alignItems: 'center' }]}><Text style={S.big}>{scans.length} / {pk.qty}</Text><Text style={S.mute}>pallets scanned</Text></View>
      <ScanInput onScan={onScan} placeholder="Scan pallet tag" />
    </View>
    <FlatList style={{ flex: 1, paddingHorizontal: 14, marginTop: 8 }} data={scans} keyExtractor={x => x.pallet_no} renderItem={({ item, index }) => (
      <TouchableOpacity onLongPress={() => remove(item)} style={[S.card, { paddingVertical: 8, marginBottom: 6, flexDirection: 'row' }]}><Text style={{ flex: 1, fontWeight: '600' }}>{index + 1}. {item.pallet_no}</Text><Text style={S.mute}>{item.ts.slice(11, 19)}</Text></TouchableOpacity>)} />
    <View style={S.pad}><Btn title="Confirm load list (Pick List Control)" onPress={confirm} color={scans.length === pk.qty ? C.ok : C.accent} /><Text style={[S.mute, { textAlign: 'center', marginTop: 4 }]}>Long-press a row to remove</Text></View>
    <Toast msg={msg} /></View>);
}
