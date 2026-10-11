// Customer document photo: camera for a page, and a viewer for the photos kept on the server (yard receiving).
// Developed by DT
import React, { useEffect, useRef, useState } from 'react';
import { View, Text, TouchableOpacity, Modal, ScrollView, Image, ActivityIndicator, Dimensions } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Ionicons } from '@expo/vector-icons';
import { S, C, Btn } from './kit';
import { serverImage } from '../lib/api';

/** Full-screen camera for one document page. onShot(uri) */
export function DocCamera({ visible, onClose, onShot }) {
  const [perm, req] = useCameraPermissions(); const cam = useRef(null); const [torch, setTorch] = useState(false); const [busy, setBusy] = useState(false);
  useEffect(() => { if (visible && perm && !perm.granted) req(); }, [visible]);
  if (!visible) return null;
  const shoot = async () => {
    if (!cam.current || busy) return; setBusy(true);
    try { const p = await cam.current.takePictureAsync({ quality: 0.8, skipProcessing: false }); onShot(p.uri); } catch (e) { } finally { setBusy(false); }
  };
  const pill = { backgroundColor: 'rgba(255,255,255,0.92)', paddingHorizontal: 20, paddingVertical: 12, borderRadius: 999, flexDirection: 'row', alignItems: 'center', gap: 6 };
  return (<Modal visible animationType="slide" onRequestClose={onClose}>
    <View style={{ flex: 1, backgroundColor: '#000' }}>
      {perm?.granted ? <CameraView ref={cam} style={{ flex: 1 }} enableTorch={torch} /> : <Text style={{ color: '#fff', padding: 20 }}>Camera permission needed</Text>}
      <View style={{ position: 'absolute', top: '8%', bottom: '20%', left: '5%', right: '5%', borderWidth: 2, borderColor: '#22d3ee', borderRadius: 10, borderStyle: 'dashed' }} />
      <Text style={{ position: 'absolute', top: '3%', alignSelf: 'center', color: '#fff', fontWeight: '700', textAlign: 'center' }}>Whole page inside the frame · flat · good light</Text>
      <View style={{ position: 'absolute', bottom: 28, left: 0, right: 0, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 14 }}>
        <TouchableOpacity onPress={() => setTorch(t => !t)} style={[pill, torch ? { backgroundColor: '#fde047' } : null]}><Ionicons name={torch ? 'flashlight' : 'flashlight-outline'} size={18} color="#111" /></TouchableOpacity>
        <TouchableOpacity onPress={shoot} style={{ width: 76, height: 76, borderRadius: 38, borderWidth: 5, borderColor: '#fff', backgroundColor: busy ? '#94a3b8' : '#ef4444', alignItems: 'center', justifyContent: 'center' }}>{busy ? <ActivityIndicator color="#fff" /> : <Ionicons name="camera" size={30} color="#fff" />}</TouchableOpacity>
        <TouchableOpacity onPress={onClose} style={pill}><Text style={{ fontWeight: '700' }}>Close</Text></TouchableOpacity>
      </View>
    </View></Modal>);
}

/** Photos of the customer's document kept with a slip on the server. */
export function DocPhotos({ visible, slipNo, count, onClose }) {
  const [zoom, setZoom] = useState(1);
  if (!visible) return null;
  const w = Dimensions.get('window').width - 20;
  return (<Modal visible animationType="slide" onRequestClose={onClose}>
    <View style={{ flex: 1, backgroundColor: '#111' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', padding: 12, paddingTop: 40, gap: 8 }}>
        <Text style={{ color: '#fff', fontWeight: '700', flex: 1 }}>Customer document · {slipNo} · {count} photo(s)</Text>
        {[1, 2, 3].map(z => <TouchableOpacity key={z} onPress={() => setZoom(z)} style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: zoom === z ? C.accent : '#334155' }}><Text style={{ color: '#fff', fontWeight: '700' }}>{z}×</Text></TouchableOpacity>)}
      </View>
      <ScrollView horizontal={zoom > 1} contentContainerStyle={{ padding: 10 }}>
        <ScrollView>{Array.from({ length: count }, (_, i) => <Image key={i} source={serverImage(`/slips/${encodeURIComponent(slipNo)}/doc-photo/${i + 1}`)} style={{ width: w * zoom, height: w * 1.41 * zoom, resizeMode: 'contain', marginBottom: 10, backgroundColor: '#222' }} />)}</ScrollView>
      </ScrollView>
      <View style={{ padding: 12 }}><Btn title="Close" onPress={onClose} /></View>
    </View></Modal>);
}

/** Pallets read from the document: chips by result. */
export function DocResult({ res, customer }) {
  if (!res) return null;
  const chip = (x, bg, fg, sub) => <View key={x.pallet_no || x} style={{ backgroundColor: bg, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, marginRight: 6, marginBottom: 6 }}><Text style={{ color: fg, fontWeight: '700', fontSize: 12 }}>{x.ref || x}</Text>{sub ? <Text style={{ color: fg, fontSize: 10 }}>{sub}</Text> : null}</View>;
  return (<View>
    <Text style={[S.body, { fontWeight: '700', marginTop: 6 }]}>{res.read} pallet number(s) read{res.stated_total ? ` · customer wrote total ${res.stated_total}` : ''}{res.ai ? ' · AI reading ✓' : ''}</Text>
    {res.matched.length ? <><Text style={[S.mute, { marginTop: 6 }]}>✓ At {customer} as per ledger ({res.matched.length})</Text><View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 }}>{res.matched.map(x => chip(x, '#dcfce7', '#166534', x.how === 'exact' ? null : 'by number'))}</View></> : null}
    {res.probable.length ? <><Text style={[S.mute, { marginTop: 4 }]}>? Probable - check at the yard ({res.probable.length})</Text><View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 }}>{res.probable.map(x => chip(x, '#fef3c7', '#92400e', `read "${x.raw}"`))}</View></> : null}
    {res.other.length ? <><Text style={[S.mute, { marginTop: 4 }]}>⚠ AIS pallet, ledger shows elsewhere ({res.other.length})</Text><View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 }}>{res.other.map(x => chip(x, '#fee2e2', '#991b1b', `${x.status} ${x.customer || ''}`))}</View></> : null}
    {res.unread.length ? <><Text style={[S.mute, { marginTop: 4 }]}>Not recognised ({res.unread.length})</Text><View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 }}>{res.unread.map(x => chip(x, '#e2e8f0', '#334155'))}</View></> : null}
  </View>);
}
