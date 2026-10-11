// Return slip at IN gate - Option B: number of pallets only (no scan at the gate); the pallets are scanned and the
// slip knocked off at pallet-yard receiving - works offline with device-series number, prints via BT.
// Security can photograph the customer's manual document: the pallet numbers are read and matched with the ledger,
// the photos are kept with the slip on the server and shown to the yard at receiving. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, Modal, ScrollView, Image, ActivityIndicator } from 'react-native';
import { S, C, Btn, Page, Header, useToast, Toast } from '../ui/kit';
import { Screen } from '../ui/kit';
import { listCustomers, enqueueDoc, kv, logActivity } from '../lib/db';
import { api } from '../lib/api';
import { state as sync, syncNow } from '../lib/sync';
import { printSlip, slipText } from '../lib/printer';
import { fDT } from '../lib/when';
import { readPhoto, matchPage, mergeResults, queuePhotos, sendPhotos, ocrAvailable } from '../lib/docscan';
import { DocCamera, DocResult } from '../ui/docs';
import { VehiclePicker } from '../ui/vehicle';
import { usedVehicle } from '../lib/vehicles';

export default function ReturnSlip({ onBack, deviceId }) {
  const [custs, setCusts] = useState([]); const [cust, setCust] = useState(null); const mode = 'B2'; const [veh, setVeh] = useState(''); const [dc, setDc] = useState(''); const [drv, setDrv] = useState(''); const [qty, setQty] = useState('');
  const [done, setDone] = useState(null); const [preview, setPreview] = useState(null); const [msg, toast] = useToast(); const [filter, setFilter] = useState('');
  const [pages, setPages] = useState([]); const [camOn, setCamOn] = useState(false); const [reading, setReading] = useState(false);
  useEffect(() => { listCustomers().then(setCusts); sendPhotos().catch(() => {}); }, []);
  const res = pages.some(p => p.res) ? mergeResults(pages.map(p => p.res)) : null;
  const addPage = async (uri) => {
    setCamOn(false); setReading(true);
    try {
      const pg = await readPhoto(uri); let r = null;
      if (sync.online) { try { r = await matchPage(cust.code, pg); } catch (e) { if (!e.offline) toast(e.message, 'err'); } }
      setPages(ps => [...ps, { ...pg, res: r }]);
      if (!r) toast(pg.text ? 'Text read on the HHT - pallets are matched when the slip reaches the server' : 'Photo kept - no text could be read; it is still saved with the slip', 'warn');
    } catch (e) { toast('Photo failed: ' + e.message, 'err'); } finally { setReading(false); }
  };
  const rematch = async () => { setReading(true); try { const out = []; for (const p of pages) out.push({ ...p, res: p.res || await matchPage(cust.code, p).catch(() => null) }); setPages(out); } finally { setReading(false); } };
  const create = async () => {
    if (!veh.trim()) return toast('Vehicle number required', 'err');
    if (!(+qty > 0)) return toast('Enter the number of pallets', 'err');
    const plant = await kv.get('plant'); usedVehicle(veh).catch(() => {});
    const body = { customer_code: cust.code, mode, vehicle_no: veh.trim().toUpperCase().replace(/\s/g, ''), pallets: [], declared_qty: +qty, customer_challan_no: dc || null, driver_name: drv || null };
    if (pages.length) Object.assign(body, { doc_text: pages.map(p => p.text).join('\n----\n').slice(0, 20000), doc_pallets: res ? [...res.matched, ...res.probable].map(x => x.pallet_no) : [], doc_unread: res ? res.unread : [], doc_read_qty: res ? res.read : null, doc_types: res ? Object.fromEntries((res.type_counts || []).map(t => [t.type, t.doc_qty])) : {}, doc_total: res ? res.stated_total : null });
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
    logActivity(provisional ? 'SLIP_CREATE_OFFLINE' : 'SLIP_CREATE', slip.slip_no, `${mode} ${cust.code} qty ${printable.declared_qty}${pages.length ? ` doc ${pages.length} photo(s), ${res ? res.read : '?'} read` : ''}`);
    if (pages.length) queuePhotos(slip.slip_no, pages.map(p => p.uri)).then(n => { if (n) toast(`Document photo(s) saved on the server`); }).catch(() => {});
    setDone(printable);
    try { const r = await printSlip(printable, plant); if (!r.printed) setPreview(r.text); else toast('Printed 2 copies'); logActivity('PRINT_SLIP', slip.slip_no, r.printed ? 'printed' : 'no printer - shown'); } catch (e) { toast('Print failed: ' + e.message, 'err'); logActivity('PRINT_ERROR', slip.slip_no, e.message); setPreview(slipText(printable, plant)); }
  };
  const reset = () => { setCust(null); setVeh(''); setDc(''); setDrv(''); setQty(''); setDone(null); setPreview(null); setPages([]); };

  if (done) return (<Screen><Header title="Return slip created" onBack={reset} /><Page>
    <View style={[S.card, { alignItems: 'center' }]}><Text style={S.big}>{done.slip_no}</Text><Text style={S.mute}>{done.provisional ? 'PROVISIONAL (offline) - gate entry made when it syncs' : `Gate entry ${done.gate_entry || 'registered'}`} · {done.declared_qty} pallets</Text></View>
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
      <VehiclePicker value={veh} onChange={setVeh} />
      <TextInput style={S.input} placeholder="Customer challan / DC number (if any)" value={dc} onChangeText={setDc} autoCapitalize="characters" />
      <TextInput style={S.input} placeholder="Driver name / mobile" value={drv} onChangeText={setDrv} />
      <TextInput style={[S.input, { fontSize: 22, fontWeight: '700' }]} placeholder="Number of pallets *" value={qty} onChangeText={setQty} keyboardType="number-pad" />
      {!!res && !!(res.stated_total || res.matched.length + res.probable.length) && String(res.stated_total || res.matched.length + res.probable.length) !== qty ? <Btn title={`Use ${res.stated_total || res.matched.length + res.probable.length} from the document`} secondary icon="checkmark-done-outline" onPress={() => setQty(String(res.stated_total || res.matched.length + res.probable.length))} /> : null}
      {!!res && +qty > 0 && !!res.stated_total && res.stated_total !== +qty ? <Text style={[S.mute, { color: C.warn }]}>Count {qty} differs from the document total {res.stated_total} - count the pallets on the vehicle.</Text> : null}
    </View>
    <View style={S.card}><Text style={S.h2}>Customer document (photo)</Text>
      <Text style={S.mute}>Photograph the customer's DC / challan / pallet list - every page. Pallet numbers, pallet types with quantity (F - 4) or just the total are read and matched with the pallets AIS shows at {cust.code}. The photo is kept with the slip and the yard sees it at receiving.</Text>
      {pages.length ? <ScrollView horizontal style={{ marginTop: 8 }}>{pages.map((p, i) => <View key={p.uri} style={{ marginRight: 8 }}><Image source={{ uri: p.uri }} style={{ width: 70, height: 96, borderRadius: 6, backgroundColor: C.line }} /><TouchableOpacity onPress={() => setPages(pages.filter(x => x !== p))} style={{ position: 'absolute', top: 2, right: 2, backgroundColor: '#0009', borderRadius: 10, paddingHorizontal: 5 }}><Text style={{ color: '#fff' }}>✕</Text></TouchableOpacity><Text style={[S.mute, { textAlign: 'center', fontSize: 10 }]}>page {i + 1}{p.res ? ' ✓' : ''}</Text></View>)}</ScrollView> : null}
      {reading ? <View style={[S.row, { marginTop: 8 }]}><ActivityIndicator color={C.accent} /><Text style={S.mute}>Reading the document…</Text></View> : null}
      <Btn title={pages.length ? `Add page ${pages.length + 1}` : 'Photo of customer document'} secondary icon="camera-outline" busy={reading} onPress={() => setCamOn(true)} />
      {pages.length > 0 && !pages.every(p => p.res) && sync.online ? <Btn title="Match with the ledger now" secondary icon="refresh" busy={reading} onPress={rematch} /> : null}
      {!ocrAvailable() ? <Text style={[S.mute, { color: C.amber }]}>Text reading not in this build - photo kept; the server reads it if AI reading is enabled.</Text> : null}
      <DocResult res={res} customer={cust.code} />
    </View>
    <DocCamera visible={camOn} onClose={() => setCamOn(false)} onShot={addPage} />
    <Btn title="Create slip & print" icon="print-outline" onPress={create} color={C.violet} />
    <Text style={[S.mute, { textAlign: 'center', marginTop: 4 }]}>Return slip number is generated automatically.</Text>
    {!sync.online ? <Text style={[S.mute, { textAlign: 'center', marginTop: 6, color: C.amber }]}>Offline: slip gets a device number and syncs later</Text> : null}
  </Page><Toast msg={msg} /></Screen>);
}
