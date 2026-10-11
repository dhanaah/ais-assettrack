// Return slip at IN gate - Option B: number of pallets only (no scan at the gate); the pallets are scanned and the
// slip knocked off at pallet-yard receiving - works offline with device-series number, prints via BT. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, Modal, ScrollView } from 'react-native';
import { S, C, Btn, Page, Header, useToast, Toast } from '../ui/kit';
import { Screen } from '../ui/kit';
import { listCustomers, enqueueDoc, kv, logActivity } from '../lib/db';
import { api } from '../lib/api';
import { state as sync, syncNow } from '../lib/sync';
import { printSlip, slipText } from '../lib/printer';
import { fDT } from '../lib/when';

export default function ReturnSlip({ onBack, deviceId }) {
  const [custs, setCusts] = useState([]); const [cust, setCust] = useState(null); const mode = 'B2'; const [veh, setVeh] = useState(''); const [dc, setDc] = useState(''); const [drv, setDrv] = useState(''); const [qty, setQty] = useState('');
  const [done, setDone] = useState(null); const [preview, setPreview] = useState(null); const [msg, toast] = useToast(); const [filter, setFilter] = useState('');
  useEffect(() => { listCustomers().then(setCusts); }, []);
  const create = async () => {
    if (!veh.trim()) return toast('Vehicle number required', 'err');
    if (!(+qty > 0)) return toast('Enter the number of pallets', 'err');
    const plant = await kv.get('plant');
    const body = { customer_code: cust.code, mode, vehicle_no: veh.trim().toUpperCase().replace(/\s/g, ''), pallets: [], declared_qty: +qty, customer_challan_no: dc || null, driver_name: drv || null };
    let slip, provisional = false;
    if (sync.online) {
      try { slip = await api('/slips', { method: 'POST', body }); if (slip.warnings?.length) toast(slip.warnings.join('; '), 'warn'); }
      catch (e) { if (!e.offline) return toast(e.message, 'err'); }
    }
    if (!slip) { // offline: device series number, replayed by sync
      const n = ((await kv.get('rts_seq')) || 0) + 1; await kv.set('rts_seq', n);
      const slip_no = `RTS-${plant.code}-${deviceId.replace(/[^A-Z0-9]/gi, '').slice(-6)}-${String(n).padStart(5, '0')}`;
      await enqueueDoc(slip_no, 'RETURN_SLIP', body); slip = { slip_no, status: 'OPEN', declared_qty: +qty }; provisional = true;
    }
    const printable = { ...slip, mode, customer_code: cust.code, customer_name: cust.name, vehicle_no: body.vehicle_no, customer_challan_no: dc, driver_name: drv, pallets: body.pallets, declared_qty: slip.declared_qty, date: fDT(new Date()), provisional };
    logActivity(provisional ? 'SLIP_CREATE_OFFLINE' : 'SLIP_CREATE', slip.slip_no, `${mode} ${cust.code} qty ${printable.declared_qty}`);
    setDone(printable);
    try { const r = await printSlip(printable, plant); if (!r.printed) setPreview(r.text); else toast('Printed 2 copies'); logActivity('PRINT_SLIP', slip.slip_no, r.printed ? 'printed' : 'no printer - shown'); } catch (e) { toast('Print failed: ' + e.message, 'err'); logActivity('PRINT_ERROR', slip.slip_no, e.message); setPreview(slipText(printable, plant)); }
  };
  const reset = () => { setCust(null); setVeh(''); setDc(''); setDrv(''); setQty(''); setDone(null); setPreview(null); };

  if (done) return (<Screen><Header title="Return slip created" onBack={reset} /><Page>
    <View style={[S.card, { alignItems: 'center' }]}><Text style={S.big}>{done.slip_no}</Text><Text style={S.mute}>{done.provisional ? 'PROVISIONAL (offline) - will sync' : 'Registered on server'} · {done.declared_qty} pallets</Text></View>
    <Btn title="Reprint" secondary onPress={async () => { const plant = await kv.get('plant'); const r = await printSlip(done, plant); if (!r.printed) setPreview(r.text); }} />
    <Btn title="New slip" onPress={reset} />
    <Modal visible={!!preview} onRequestClose={() => setPreview(null)}><ScrollView style={{ padding: 20, paddingTop: 50 }}><Text style={{ fontFamily: 'monospace', fontSize: 13 }}>{preview}</Text><Text style={[S.mute, { marginTop: 12 }]}>No Bluetooth printer connected - this is the slip content. Pair a printer in Settings.</Text><Btn title="Close" onPress={() => setPreview(null)} /></ScrollView></Modal>
  </Page><Toast msg={msg} /></Screen>);

  if (!cust) return (<Screen><Header title="Return Slip" sub="Select customer" onBack={onBack} /><Page>
    <TextInput style={S.input} placeholder="Search customer" value={filter} onChangeText={setFilter} />
    {custs.filter(c => !filter || (c.name + c.code).toLowerCase().includes(filter.toLowerCase())).map(c => <TouchableOpacity key={c.code} style={S.card} onPress={() => setCust(c)}><Text style={S.h2}>{c.name}</Text><Text style={S.mute}>{c.code} · return mode {c.return_mode}</Text></TouchableOpacity>)}
  </Page></Screen>);

  return (<Screen><Header title={cust.name} sub="Return slip at IN gate" onBack={() => setCust(null)} /><Page>
    <View style={S.card}><Text style={S.h2}>Option B · number of pallets only</Text><Text style={S.mute}>No pallet scanning at the gate. The pallets are scanned and this slip is knocked off at pallet-yard receiving.</Text></View>
    <View style={S.card}>
      <TextInput style={S.input} placeholder="Vehicle number *" value={veh} onChangeText={setVeh} autoCapitalize="characters" />
      <TextInput style={S.input} placeholder="Customer challan / DC number" value={dc} onChangeText={setDc} autoCapitalize="characters" />
      <TextInput style={S.input} placeholder="Driver name / mobile" value={drv} onChangeText={setDrv} />
      <TextInput style={[S.input, { fontSize: 22, fontWeight: '700' }]} placeholder="Number of pallets *" value={qty} onChangeText={setQty} keyboardType="number-pad" />
    </View>
    <Btn title="Create slip & print" icon="print-outline" onPress={create} color={C.violet} />
    {!sync.online ? <Text style={[S.mute, { textAlign: 'center', marginTop: 6, color: C.amber }]}>Offline: slip gets a device number and syncs later</Text> : null}
  </Page><Toast msg={msg} /></Screen>);
}
