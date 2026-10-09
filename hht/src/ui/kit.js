// Small UI kit + ScanInput (hardware scanner wedge + camera). Developed by DT
import React, { useEffect, useRef, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Modal, Vibration, ScrollView, Image } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { LinearGradient } from 'expo-linear-gradient';
import { BlurView } from 'expo-blur';
import { Ionicons } from '@expo/vector-icons';

export const C = { bg: '#eef2ff', card: 'rgba(255,255,255,0.62)', fg: '#0f172a', mute: '#475569', accent: '#1e3a8a', violet: '#dc2626', ok: '#059669', warn: '#dc2626', amber: '#d97706', line: 'rgba(255,255,255,0.75)', sky: '#0ea5e9' };
export const GRAD = { screen: ['#e0e7ff', '#ecfeff', '#fdf2f8'], header: ['#1e3a8a', '#7c2d8f', '#dc2626'], btn: ['#1e3a8a', '#dc2626'], ok: ['#059669', '#10b981'], amber: ['#d97706', '#f59e0b'], red: ['#dc2626', '#f43f5e'] };

export const S = StyleSheet.create({
  screen: { flex: 1 },
  pad: { padding: 14 },
  card: { backgroundColor: C.card, borderRadius: 18, padding: 14, marginBottom: 12, borderWidth: 1, borderColor: 'rgba(255,255,255,0.8)', shadowColor: '#312e81', shadowOpacity: 0.12, shadowRadius: 16, shadowOffset: { width: 0, height: 8 }, elevation: 3, overflow: 'hidden' },
  h1: { fontSize: 20, fontWeight: '700', color: C.fg, marginBottom: 6 },
  h2: { fontSize: 15, fontWeight: '700', color: C.fg, marginBottom: 6 },
  mute: { color: C.mute, fontSize: 12.5 },
  input: { backgroundColor: 'rgba(255,255,255,0.85)', borderWidth: 1, borderColor: 'rgba(30,58,138,0.15)', borderRadius: 12, padding: 11, fontSize: 15, color: C.fg, marginBottom: 8 },
  btn: { borderRadius: 14, paddingVertical: 13, alignItems: 'center', marginTop: 6, overflow: 'hidden', shadowColor: '#7c2d8f', shadowOpacity: 0.3, shadowRadius: 10, shadowOffset: { width: 0, height: 6 }, elevation: 4 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  btnS: { backgroundColor: 'rgba(255,255,255,0.75)', borderWidth: 1, borderColor: 'rgba(30,58,138,0.35)', borderRadius: 14, paddingVertical: 11, alignItems: 'center', marginTop: 6 },
  btnSText: { color: C.accent, fontWeight: '600' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: { paddingHorizontal: 9, paddingVertical: 2, borderRadius: 999, fontSize: 11, fontWeight: '700', overflow: 'hidden' },
  big: { fontSize: 34, fontWeight: '800', color: C.fg },
});

const gradFor = (color) => color === C.ok ? GRAD.ok : color === C.amber ? GRAD.amber : color === C.violet || color === C.warn ? GRAD.red : GRAD.btn;
export const Btn = ({ title, onPress, secondary, color, disabled, icon }) => secondary ? (
  <TouchableOpacity disabled={disabled} onPress={onPress} style={[S.btnS, disabled ? { opacity: 0.5 } : null]}>
    <View style={S.row}>{icon ? <Ionicons name={icon} size={16} color={C.accent} /> : null}<Text style={S.btnSText}>{title}</Text></View></TouchableOpacity>) : (
  <TouchableOpacity disabled={disabled} onPress={onPress} activeOpacity={0.85} style={[S.btn, disabled ? { opacity: 0.5 } : null]}>
    <LinearGradient colors={gradFor(color)} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} />
    <View style={S.row}>{icon ? <Ionicons name={icon} size={17} color="#fff" /> : null}<Text style={S.btnText}>{title}</Text></View></TouchableOpacity>);

/** Glass card: frosted blur + translucent white; use for highlighted panels (counters, scan box). */
export const Glass = ({ children, style, tint = 'light' }) => (
  <View style={[S.card, { padding: 0, backgroundColor: 'transparent' }, style]}>
    <BlurView intensity={40} tint={tint} style={{ ...StyleSheet.absoluteFillObject }} />
    <View style={{ ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(255,255,255,0.55)' }} />
    <View style={{ padding: 14 }}>{children}</View></View>);

/** Counter with a coloured ring — for "7 / 10", received / short / excess. */
export const Ring = ({ value, label, color = C.accent, size = 84 }) => (
  <View style={{ alignItems: 'center' }}>
    <View style={{ width: size, height: size, borderRadius: size / 2, borderWidth: 6, borderColor: color, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.7)', shadowColor: color, shadowOpacity: 0.35, shadowRadius: 10, elevation: 3 }}>
      <Text style={{ fontSize: size * 0.34, fontWeight: '800', color }}>{value}</Text></View>
    <Text style={[S.mute, { marginTop: 6, fontWeight: '600' }]}>{label}</Text></View>);

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
          style={[S.input, { flex: 1, marginBottom: 0, fontSize: 17, borderColor: 'rgba(30,58,138,0.35)', borderWidth: 1.5 }]} autoCapitalize="characters" autoCorrect={false} showSoftInputOnFocus={false} returnKeyType="done" />
        <TouchableOpacity onPress={() => ref.current?.focus()} style={[S.btnS, { paddingHorizontal: 12, marginTop: 0 }]}><Ionicons name="keypad-outline" size={20} color={C.accent} /></TouchableOpacity>
        <TouchableOpacity onPress={() => setCam(true)} style={[S.btn, { paddingHorizontal: 14, marginTop: 0, paddingVertical: 11 }]}><LinearGradient colors={GRAD.btn} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} /><Ionicons name="camera-outline" size={22} color="#fff" /></TouchableOpacity>
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

export const AisLogo = ({ size = 34 }) => <Image source={require('../../assets/icon.png')} style={{ width: size, height: size, borderRadius: 8, backgroundColor: '#fff' }} />;
export const Wordmark = ({ height = 30 }) => <Image source={require('../../assets/wordmark.png')} style={{ height, width: height * 3.5, resizeMode: 'contain' }} />;

export const Header = ({ title, sub, onBack, right, logo }) => (
  <LinearGradient colors={GRAD.header} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={{ paddingTop: 42, paddingBottom: 14, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', borderBottomLeftRadius: 18, borderBottomRightRadius: 18, shadowColor: '#312e81', shadowOpacity: 0.3, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 6 }}>
    {onBack ? <TouchableOpacity onPress={onBack} style={{ paddingRight: 12 }}><Text style={{ color: '#fff', fontSize: 22 }}>‹</Text></TouchableOpacity> : null}
    {logo ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginRight: 10 }}><AisLogo size={36} /><View style={{ backgroundColor: '#fff', borderRadius: 7, paddingHorizontal: 6, paddingVertical: 2 }}><Wordmark height={26} /></View></View> : null}
    <View style={{ flex: 1 }}>{title ? <Text style={{ color: '#fff', fontWeight: '700', fontSize: 17 }}>{title}</Text> : null}{sub ? <Text style={{ color: 'rgba(255,255,255,0.85)', fontSize: 12 }}>{sub}</Text> : null}</View>
    {right}
  </LinearGradient>);

export const Footer = () => (
  <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 14 }}>
    <AisLogo size={18} /><Text style={{ color: C.mute, fontSize: 11.5 }}>Asahi India Glass Ltd. · AssetTrack · Developed by DT</Text></View>);

export const Backdrop = () => (
  <View style={{ ...StyleSheet.absoluteFillObject }} pointerEvents="none">
    <LinearGradient colors={GRAD.screen} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} />
    <View style={{ position: 'absolute', top: -80, left: -60, width: 260, height: 260, borderRadius: 130, backgroundColor: 'rgba(99,102,241,0.18)' }} />
    <View style={{ position: 'absolute', top: 220, right: -90, width: 240, height: 240, borderRadius: 120, backgroundColor: 'rgba(14,165,233,0.16)' }} />
    <View style={{ position: 'absolute', bottom: -70, left: 40, width: 220, height: 220, borderRadius: 110, backgroundColor: 'rgba(244,114,182,0.16)' }} />
  </View>);
export const Page = ({ children }) => <View style={{ flex: 1 }}><Backdrop /><ScrollView style={S.screen} contentContainerStyle={S.pad} keyboardShouldPersistTaps="handled">{children}</ScrollView></View>;
export const Screen = ({ children }) => <View style={{ flex: 1 }}><Backdrop />{children}</View>;
