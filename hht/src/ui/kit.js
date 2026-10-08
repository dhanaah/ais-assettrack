// Small UI kit + ScanInput (hardware scanner wedge + camera). Developed by DT
import React, { useEffect, useRef, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Modal, Vibration, ScrollView } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';

export const C = { bg: '#eef2ff', card: 'rgba(255,255,255,0.78)', fg: '#0f172a', mute: '#475569', accent: '#1e3a8a', violet: '#dc2626', ok: '#059669', warn: '#dc2626', amber: '#d97706', line: 'rgba(15,23,42,0.1)' };

export const S = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  pad: { padding: 14 },
  card: { backgroundColor: C.card, borderRadius: 16, padding: 14, marginBottom: 12, borderWidth: 1, borderColor: 'rgba(255,255,255,0.7)', shadowColor: '#1e1b4b', shadowOpacity: 0.08, shadowRadius: 12, elevation: 2 },
  h1: { fontSize: 20, fontWeight: '700', color: C.fg, marginBottom: 6 },
  h2: { fontSize: 15, fontWeight: '700', color: C.fg, marginBottom: 6 },
  mute: { color: C.mute, fontSize: 12.5 },
  input: { backgroundColor: 'rgba(255,255,255,0.9)', borderWidth: 1, borderColor: C.line, borderRadius: 10, padding: 10, fontSize: 15, color: C.fg, marginBottom: 8 },
  btn: { backgroundColor: C.accent, borderRadius: 12, paddingVertical: 13, alignItems: 'center', marginTop: 6 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  btnS: { backgroundColor: 'rgba(255,255,255,0.9)', borderWidth: 1, borderColor: C.accent, borderRadius: 12, paddingVertical: 11, alignItems: 'center', marginTop: 6 },
  btnSText: { color: C.accent, fontWeight: '600' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: { paddingHorizontal: 9, paddingVertical: 2, borderRadius: 999, fontSize: 11, fontWeight: '700', overflow: 'hidden' },
  big: { fontSize: 34, fontWeight: '800', color: C.fg },
});

export const Btn = ({ title, onPress, secondary, color, disabled }) => (
  <TouchableOpacity disabled={disabled} onPress={onPress} style={[secondary ? S.btnS : S.btn, color && !secondary ? { backgroundColor: color } : null, disabled ? { opacity: 0.5 } : null]}>
    <Text style={secondary ? S.btnSText : S.btnText}>{title}</Text></TouchableOpacity>);

const pillColor = { AVAILABLE: ['#d1fae5', C.ok], AT_CUSTOMER: ['#e0f2fe', '#0369a1'], ALLOCATED: ['#fef3c7', C.amber], IN_RETURN: ['#fef3c7', C.amber], HELD: ['#fee2e2', C.warn], DAMAGED: ['#fee2e2', C.warn], OPEN: ['#e0f2fe', '#0369a1'], READY: ['#fef3c7', C.amber], PENDING: ['#fef3c7', C.amber], APPLIED: ['#d1fae5', C.ok], REJECTED: ['#fee2e2', C.warn], EXCEPTION: ['#fef3c7', C.amber], DONE: ['#d1fae5', C.ok], FAILED: ['#fee2e2', C.warn] };
export const Pill = ({ s }) => { const [bg, fg] = pillColor[s] || ['#e5e7eb', '#374151']; return <Text style={[S.pill, { backgroundColor: bg, color: fg }]}>{s}</Text>; };

export const Toast = ({ msg }) => msg ? (
  <View style={{ position: 'absolute', bottom: 24, left: 16, right: 16, backgroundColor: msg.err ? 'rgba(220,38,38,0.95)' : msg.warn ? 'rgba(217,119,6,0.95)' : 'rgba(5,150,105,0.95)', padding: 12, borderRadius: 12 }}>
    <Text style={{ color: '#fff', fontWeight: '600', fontSize: 15 }}>{msg.text}</Text></View>) : null;

export function useToast() {
  const [msg, setMsg] = useState(null); const t = useRef();
  const show = (text, kind) => { clearTimeout(t.current); setMsg({ text, err: kind === 'err', warn: kind === 'warn' }); Vibration.vibrate(kind === 'err' ? [0, 80, 60, 80] : 40); t.current = setTimeout(() => setMsg(null), kind === 'err' ? 3500 : 1800); };
  return [msg, show];
}

/** ScanInput: hardware scanners act as a keyboard and send Enter; the field keeps focus and clears after each read.
 *  The camera button opens a barcode/QR scanner for phones. */
export function ScanInput({ onScan, placeholder = 'Scan tag / QR', autoFocus = true, disabled }) {
  const [v, setV] = useState(''); const [cam, setCam] = useState(false); const ref = useRef();
  const submit = (val) => { const s = (val ?? v).trim(); if (!s) return; setV(''); onScan(s); setTimeout(() => ref.current?.focus(), 50); };
  useEffect(() => { if (autoFocus) setTimeout(() => ref.current?.focus(), 200); }, []);
  return (
    <View>
      <View style={S.row}>
        <TextInput ref={ref} value={v} onChangeText={setV} onSubmitEditing={() => submit()} blurOnSubmit={false} placeholder={placeholder} editable={!disabled}
          style={[S.input, { flex: 1, marginBottom: 0, fontSize: 17 }]} autoCapitalize="characters" autoCorrect={false} showSoftInputOnFocus={false} returnKeyType="done" />
        <TouchableOpacity onPress={() => ref.current?.focus()} onLongPress={() => { }} style={[S.btnS, { paddingHorizontal: 12, marginTop: 0 }]}><Text style={S.btnSText}>⌨</Text></TouchableOpacity>
        <TouchableOpacity onPress={() => setCam(true)} style={[S.btn, { paddingHorizontal: 14, marginTop: 0 }]}><Text style={S.btnText}>📷</Text></TouchableOpacity>
      </View>
      <CameraScanner visible={cam} onClose={() => setCam(false)} onScan={(d) => { setCam(false); submit(d); }} />
    </View>);
}

export function CameraScanner({ visible, onClose, onScan }) {
  const [perm, req] = useCameraPermissions(); const lock = useRef(false);
  useEffect(() => { if (visible && perm && !perm.granted) req(); if (visible) lock.current = false; }, [visible]);
  if (!visible) return null;
  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: '#000' }}>
        {perm?.granted ? <CameraView style={{ flex: 1 }} barcodeScannerSettings={{ barcodeTypes: ['qr', 'code128', 'code39', 'ean13', 'datamatrix'] }}
          onBarcodeScanned={({ data }) => { if (lock.current) return; lock.current = true; Vibration.vibrate(40); onScan(data); }} /> : <Text style={{ color: '#fff', padding: 20 }}>Camera permission needed</Text>}
        <View style={{ position: 'absolute', top: '35%', left: '12%', right: '12%', height: 180, borderWidth: 2, borderColor: '#38bdf8', borderRadius: 12 }} />
        <TouchableOpacity onPress={onClose} style={{ position: 'absolute', bottom: 30, alignSelf: 'center', backgroundColor: 'rgba(255,255,255,0.9)', paddingHorizontal: 30, paddingVertical: 12, borderRadius: 999 }}><Text style={{ fontWeight: '700' }}>Close</Text></TouchableOpacity>
      </View></Modal>);
}

export const Header = ({ title, sub, onBack, right }) => (
  <View style={{ backgroundColor: C.accent, paddingTop: 42, paddingBottom: 12, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center' }}>
    {onBack ? <TouchableOpacity onPress={onBack} style={{ paddingRight: 12 }}><Text style={{ color: '#fff', fontSize: 22 }}>‹</Text></TouchableOpacity> : null}
    <View style={{ flex: 1 }}><Text style={{ color: '#fff', fontWeight: '700', fontSize: 17 }}>{title}</Text>{sub ? <Text style={{ color: 'rgba(255,255,255,0.85)', fontSize: 12 }}>{sub}</Text> : null}</View>
    {right}
  </View>);

export const Page = ({ children }) => <ScrollView style={S.screen} contentContainerStyle={S.pad} keyboardShouldPersistTaps="handled">{children}</ScrollView>;
