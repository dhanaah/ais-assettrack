// Yard in-ward: scan slip → scan each pallet (accept other-plant checkbox, damaged) → close. Option B slips: the
// pallets read from the customer's document are the expected list, and the document photo can be viewed here. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, FlatList, Switch, TextInput } from 'react-native';
import { S, C, Btn, Page, Header, ScanInput, Pill, useToast, Toast, Ring, Glass, Screen } from '../ui/kit';
import { listSlips, getSlip, enqueue, addLocalScan, localScans, setPalletLocal, kv } from '../lib/db';
import { validateYardScan } from '../lib/rules';
import { logActivity } from '../lib/db';
import { api } from '../lib/api';
import { state as sync, syncNow } from '../lib/sync';
import { DocPhotos } from '../ui/docs';

export default function Yard({ onBack }) {
  const [slips, setSlips] = useState([]); const [slip, setSlip] = useState(null); const [scans, setScans] = useState([]); const [accept, setAccept] = useState(false); const [damaged, setDamaged] = useState(false); const [pin, setPin] = useState(''); const [msg, toast] = useToast();
  useEffect(() => { listSlips().then(setSlips); kv.get('plant').then(p => setAccept(!!p?.accept_other_plant_default)); }, []);
  const [docs, setDocs] = useState({}); const [showDoc, setShowDoc] = useState(false);
  useEffect(() => { kv.get('slip_docs').then(d => setDocs(d || {})); }, [slips]);
  const open = async (s) => { setSlip(s); setScans(await localScans(s.slip_no)); setDocs((await kv.get('slip_docs')) || {}); };
  const onSlipScan = async (code) => { const no = code.startsWith('AIS1|RS|') ? code.split('|')[2] : code.startsWith('RTS|') ? code.split('|')[1] : code; const s = await getSlip(no); if (!s) return toast('Slip not in cache: ' + no, 'err'); open(s); };
  const onScan = async (code) => {
    const v = await validateYardScan(slip, code, accept);
    if (!v.ok) { logActivity('SCAN_REJECTED_LOCAL', slip.slip_no, v.msg, { scanned: code }); return toast(v.msg, v.dup ? 'warn' : 'err'); }
    const pno = v.pallet ? v.pallet.pallet_no : v.newPallet ? v.newPallet.pallet_no : code.slice(0, 40);
    await addLocalScan(slip.slip_no, pno);
    if (v.pallet) await setPalletLocal(pno, { status: v.exception === 'FOREIGN' ? 'HELD' : damaged ? 'DAMAGED' : 'AVAILABLE', customer: null, zone: 'YARD', load: 'EMPTY' });
    await enqueue('PALLET_SCAN_YARD', { slip_no: slip.slip_no, scanned: code, accept_foreign: accept, damaged }, !sync.online); logActivity(sync.online ? 'SCAN_YARD' : 'SCAN_YARD_OFFLINE', slip.slip_no, v.msg, { accept, damaged });
    setScans(await localScans(slip.slip_no)); toast(v.msg + (damaged ? ' (DAMAGED)' : ''), v.exception ? 'warn' : undefined); setDamaged(false);
    if (sync.online) syncNow().catch(() => {});
  };
  const doc = slip ? docs[slip.slip_no] : null; const qtyOnly = slip && slip.mode !== 'A' && slip.mode !== 'B1';
  const declared = slip ? (qtyOnly ? (doc?.doc || []) : JSON.parse(slip.pallets || '[]')) : [];
  const received = new Set(scans.map(s => s.pallet_no));
  const short = declared.filter(p => !received.has(p)); const extra = qtyOnly && !declared.length ? [] : scans.filter(s => !declared.includes(s.pallet_no));
  const sref = (p) => { const m = /^AIS-[A-Z0-9]+-([A-Z0-9]+)-(\d+)-\d+$/.exec(p || ''); return m ? `${m[1]}-${m[2]}` : p; };
  const close = async () => {
    if (!sync.online) return toast('Closing needs the server; scans are saved and will sync.', 'warn');
    try { await syncNow(); const r = await api(`/slips/${slip.slip_no}/close`, { method: 'POST', body: { supervisor_pin: pin || null } }); toast(`Closed: received ${r.received}, short ${r.short.length}`); logActivity('SLIP_CLOSE', slip.slip_no, `received ${r.received}, short ${r.short.length}`); setSlip(null); await syncNow(); setSlips(await listSlips()); }
    catch (e) { toast(e.message, 'err'); }
  };

  if (!slip) return (<Screen><Header title="Yard In-ward Scan" sub="Scan slip QR or pick from list" onBack={onBack} /><Page>
    <View style={S.card}><ScanInput onScan={onSlipScan} placeholder="Scan return slip QR" /></View>
    {slips.map(s => <TouchableOpacity key={s.slip_no} style={S.card} onPress={() => open(s)}><View style={S.row}><Text style={[S.h2, { flex: 1, marginBottom: 0 }]}>{s.slip_no}</Text><Pill s={s.status} /></View><Text style={S.mute}>Customer {s.customer} · mode {s.mode} · declared {s.qty}</Text></TouchableOpacity>)}
    <Btn title="Refresh" secondary icon="refresh" onPress={async () => { await syncNow(); setSlips(await listSlips()); }} /></Page><Toast msg={msg} /></Screen>);

  return (<Screen><Header title={slip.slip_no} sub={`Customer ${slip.customer} · mode ${slip.mode} · declared ${slip.qty}`} onBack={() => setSlip(null)} />
    <View style={[S.pad, { paddingBottom: 0 }]}>
      <Glass><View style={{ flexDirection: 'row', justifyContent: 'space-around' }}>
        <Ring value={qtyOnly ? `${scans.length}/${doc?.total || slip.qty}` : scans.length} label={qtyOnly ? 'received / count' : 'received'} color={qtyOnly && scans.length !== slip.qty ? C.amber : C.ok} size={76} />
        <Ring value={short.length} label={qtyOnly ? 'on doc, not yet' : 'short'} color={short.length ? C.warn : C.ok} size={76} />
        <Ring value={extra.length} label={qtyOnly ? 'not on doc' : 'excess/other'} color={extra.length ? C.amber : C.accent} size={76} />
      </View></Glass>
      <View style={{ flexDirection: 'row', gap: 8, marginBottom: 4 }}>
        {[['accept', accept, setAccept, 'Accept other-plant', C.accent], ['dmg', damaged, setDamaged, 'Next scan = DAMAGED', C.warn]].map(([k, v, set, l, c]) => <TouchableOpacity key={k} onPress={() => set(!v)} activeOpacity={0.8} style={[S.btnS, { flex: 1, marginTop: 0, minHeight: 44, justifyContent: 'center', backgroundColor: v ? c : undefined, borderColor: v ? c : C.accent }]}><Text style={[S.btnSText, v ? { color: '#fff' } : null]}>{v ? '✓ ' : ''}{l}</Text></TouchableOpacity>)}
      </View>
      {doc ? <TouchableOpacity onPress={() => doc.photos ? setShowDoc(true) : null} style={[S.btnS, { marginTop: 0, marginBottom: 6, alignItems: 'center' }]}><Text style={S.btnSText}>📄 Customer document{doc.doc.length ? ` · ${doc.doc.length} pallet no.` : ''}{doc.total ? ` · total ${doc.total}` : ''}{doc.photos ? ` · view ${doc.photos} photo(s)` : ' · photo not uploaded yet'}</Text>
        {Object.keys(doc.types || {}).length ? <Text style={[S.mute, { marginTop: 2 }]}>By type: {Object.entries(doc.types).map(([t, q]) => `${t} ${scans.filter(x => (/^AIS-[A-Z0-9]+-([A-Z0-9]+)-/.exec(x.pallet_no) || [])[1] === t).length}/${q}`).join('  ·  ')}</Text> : null}</TouchableOpacity> : qtyOnly ? <Text style={[S.mute, { marginBottom: 6 }]}>Option B count only, no customer document photo - scan every pallet.</Text> : null}
      <ScanInput onScan={onScan} placeholder="Scan pallet tag" />
    </View>
    <FlatList style={{ flex: 1, paddingHorizontal: 14, marginTop: 8 }} data={[...scans].reverse()} keyExtractor={x => String(x.id)} renderItem={({ item }) => (
      <View style={[S.card, { paddingVertical: 8, marginBottom: 6, flexDirection: 'row' }]}><Text style={{ flex: 1, fontWeight: '600' }}>{item.pallet_no}</Text>{declared.includes(item.pallet_no) ? (qtyOnly ? <Text style={{ color: C.ok, fontWeight: '700' }}>✓ on doc</Text> : null) : (qtyOnly && !declared.length ? null : <Pill s="EXCEPTION" />)}</View>)}
      ListFooterComponent={short.length ? <View style={[S.card, { borderLeftWidth: 4, borderLeftColor: C.warn }]}><Text style={S.h2}>{qtyOnly ? 'On customer document, not yet received' : 'Not yet received'}</Text><Text style={S.mute}>{short.map(sref).join('  ·  ')}</Text></View> : null} />
    <View style={S.pad}><View style={S.row}><TextInput style={[S.input, { flex: 1, marginBottom: 0 }]} value={pin} onChangeText={setPin} placeholder="Supervisor PIN (if exceptions)" secureTextEntry keyboardType="number-pad" /><Btn title="Reconcile & close" icon="git-compare-outline" onPress={close} color={short.length || extra.length ? C.amber : C.ok} /></View></View>
    <DocPhotos visible={showDoc} slipNo={slip.slip_no} count={doc?.photos || 0} onClose={() => setShowDoc(false)} />
    <Toast msg={msg} /></Screen>);
}
