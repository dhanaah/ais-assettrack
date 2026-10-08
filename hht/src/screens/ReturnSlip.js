// Return slip at IN gate (Mode B1 full scan / B2 qty only) - works offline with device-series number, prints via BT. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, Modal, ScrollView } from 'react-native';
import { S, C, Btn, Page, Header, ScanInput, useToast, Toast } from '../ui/kit';
import { listCustomers, enqueueDoc, kv, logActivity } from '../lib/db';
import { validateReturnPallet } from '../lib/rules';
import { api } from '../lib/api';
import { state as sync, syncNow } from '../lib/sync';
import { printSlip, slipText } from '../lib/printer';

export default function ReturnSlip({ onBack, deviceId }) {
  const [custs, setCusts] = useState([]); const [cust, setCust] = useState(null); const [mode, setMode] = useState('B1'); const [veh, setVeh] = useState(''); const [dc, setDc] = useState(''); const [drv, setDrv] = useState(''); const [qty, setQty] = useState('');
  const [pallets, setPallets] = useState([]); const [done, setDone] = useState(null); const [preview, setPreview] = useState(null); const [msg, toast] = useToast(); const [filter, setFilter] = useState('');
  useEffect(() => { listCustomers().then(setCusts); }, []);
  const onScan = async (code) => {
    const v = await validateReturnPallet(cust.code, code);
    if (pallets.find(p => p.pallet_no === v.pallet_no)) return toast('Already in list', 'warn');
    setPallets([...pallets, { pallet_no: v.pallet_no, warn: v.warn }]); toast(v.warn ? `${v.pallet_no}: ${v.warn}` : v.pallet_no, v.warn ? 'warn' : undefined);
  };
  const create = async () => {
    if (!veh.trim()) return toast('Vehicle number required', 'err');
    if (mode === 'B1' && !pallets.length) return toast('Scan at least one pallet', 'err');
    if (mode === 'B2' && !(+qty > 0)) return toast('Enter declared quantity', 'err');
    const plant = await kv.get('plant');
    const body = { customer_code: cust.code, mode, vehicle_no: veh.trim().toUpperCase().replace(/\s/g, ''), pallets: pallets.map(p => p.pallet_no), declared_qty: mode === 'B2' ? +qty : null, customer_challan_no: dc || null, driver_name: drv || null };
    let slip, provisional = false;
    if (sync.online) {
      try { slip = await api('/slips', { method: 'POST', body }); if (slip.warnings?.length) toast(slip.warnings.join('; '), 'warn'); }
      catch (e) { if (!e.offline) return toast(e.message, 'err'); }
    }
    if (!slip) { // offline: device series number, replayed by sync
      const n = ((await kv.get('rts_seq')) || 0) + 1; await kv.set('rts_seq', n);
      const slip_no = `RTS-${plant.code}-${deviceId.replace(/[^A-Z0-9]/gi, '').slice(-6)}-${String(n).padStart(5, '0')}`;
      await enqueueDoc(slip_no, 'RETURN_SLIP', body); slip = { slip_no, status: 'OPEN', declared_qty: mode === 'B2' ? +qty : pallets.length }; provisional = true;
    }
    const printable = { ...slip, mode, customer_code: cust.code, customer_name: cust.name, vehicle_no: body.vehicle_no, customer_challan_no: dc, driver_name: drv, pallets: body.pallets, declared_qty: slip.declared_qty, date: new Date().toLocaleString(), provisional };
    logActivity(provisional ? 'SLIP_CREATE_OFFLINE' : 'SLIP_CREATE', slip.slip_no, `${mode} ${cust.code} qty ${printable.declared_qty}`);
    setDone(printable);
    try { const r = await printSlip(printable, plant); if (!r.printed) setPreview(r.text); else toast('Printed 2 copies'); logActivity('PRINT_SLIP', slip.slip_no, r.printed ? 'printed' : 'no printer - shown'); } catch (e) { toast('Print failed: ' + e.message, 'err'); logActivity('PRINT_ERROR', slip.slip_no, e.message); setPreview(slipText(printable, plant)); }
  };
  const reset = () => { setCust(null); setPallets([]); setVeh(''); setDc(''); setDrv(''); setQty(''); setDone(null); setPreview(null); };

  if (done) return (<View style={{ flex: 1 }}><Header title="Return slip created" onBack={reset} /><Page>
    <View style={[S.card, { alignItems: 'center' }]}><Text style={S.big}>{done.slip_no}</Text><Text style={S.mute}>{done.provisional ? 'PROVISIONAL (offline) - will sync' : 'Registered on server'} · {done.declared_qty} pallets</Text></View>
    <Btn title="Reprint" secondary onPress={async () => { const plant = await kv.get('plant'); const r = await printSlip(done, plant); if (!r.printed) setPreview(r.text); }} />
    <Btn title="New slip" onPress={reset} />
    <Modal visible={!!preview} onRequestClose={() => setPreview(null)}><ScrollView style={{ padding: 20, paddingTop: 50 }}><Text style={{ fontFamily: 'monospace', fontSize: 13 }}>{preview}</Text><Text style={[S.mute, { marginTop: 12 }]}>No Bluetooth printer connected - this is the slip content. Pair a printer in Settings.</Text><Btn title="Close" onPress={() => setPreview(null)} /></ScrollView></Modal>
  </Page><Toast msg={msg} /></View>);

  if (!cust) return (<View style={{ flex: 1 }}><Header title="Return Slip" sub="Select customer" onBack={onBack} /><Page>
    <TextInput style={S.input} placeholder="Search customer" value={filter} onChangeText={setFilter} />
    {custs.filter(c => !filter || (c.name + c.code).toLowerCase().includes(filter.toLowerCase())).map(c => <TouchableOpacity key={c.code} style={S.card} onPress={() => setCust(c)}><Text style={S.h2}>{c.name}</Text><Text style={S.mute}>{c.code} · return mode {c.return_mode}</Text></TouchableOpacity>)}
  </Page></View>);

  return (<View style={{ flex: 1 }}><Header title={cust.name} sub="Return slip at IN gate" onBack={() => setCust(null)} /><Page>
    <View style={[S.row, { marginBottom: 8 }]}>{['B1', 'B2'].map(m => <TouchableOpacity key={m} onPress={() => setMode(m)} style={[S.btnS, { flex: 1, marginTop: 0, backgroundColor: mode === m ? C.accent : undefined }]}><Text style={[S.btnSText, mode === m ? { color: '#fff' } : null]}>{m === 'B1' ? 'B1 · scan each pallet' : 'B2 · quantity only'}</Text></TouchableOpacity>)}</View>
    <View style={S.card}>
      <TextInput style={S.input} placeholder="Vehicle number *" value={veh} onChangeText={setVeh} autoCapitalize="characters" />
      <TextInput style={S.input} placeholder="Customer challan / DC number" value={dc} onChangeText={setDc} autoCapitalize="characters" />
      <TextInput style={S.input} placeholder="Driver name / mobile" value={drv} onChangeText={setDrv} />
      {mode === 'B2' ? <TextInput style={S.input} placeholder="Declared pallet quantity *" value={qty} onChangeText={setQty} keyboardType="number-pad" /> : null}
    </View>
    {mode === 'B1' ? <View style={S.card}><Text style={S.h2}>Pallets scanned: {pallets.length}</Text><ScanInput onScan={onScan} />
      {pallets.map((p, i) => <View key={p.pallet_no} style={[S.row, { marginTop: 6 }]}><Text style={{ flex: 1 }}>{i + 1}. {p.pallet_no}</Text>{p.warn ? <Text style={{ color: C.amber, fontSize: 11 }}>{p.warn}</Text> : null}<TouchableOpacity onPress={() => setPallets(pallets.filter(x => x !== p))}><Text style={{ color: C.warn }}> ✕ </Text></TouchableOpacity></View>)}</View> : null}
    <Btn title="Create slip & print" onPress={create} color={C.violet} />
    {!sync.online ? <Text style={[S.mute, { textAlign: 'center', marginTop: 6, color: C.amber }]}>Offline: slip gets a device number and syncs later</Text> : null}
  </Page><Toast msg={msg} /></View>);
}
