// Small UI kit + ScanInput (hardware scanner wedge + camera). Developed by DT
import React, { useEffect, useRef, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Modal, Vibration, ScrollView, Image, RefreshControl, ActivityIndicator } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { THEMES } from './theme';
import { feedback } from '../lib/feedback';

export const C = { ...THEMES.glass.C };
export const GRAD = { ...THEMES.glass.GRAD };
export const T = { key: 'glass', dark: false, blur: 40, blurTint: 'light', scale: 1 };
const sc = (n) => Math.round(n * T.scale);
export const S = {};
const makeStyles = () => StyleSheet.create({
  screen: { flex: 1 },
  pad: { padding: sc(14) },
  card: { backgroundColor: C.card, borderRadius: 18, padding: sc(14), marginBottom: 12, borderWidth: 1, borderColor: C.line, shadowColor: T.dark ? '#000' : '#312e81', shadowOpacity: T.dark ? 0.4 : 0.12, shadowRadius: 16, shadowOffset: { width: 0, height: 8 }, elevation: 3, overflow: 'hidden' },
  h1: { fontSize: sc(20), fontWeight: '700', color: C.fg, marginBottom: 6 },
  h2: { fontSize: sc(15), fontWeight: '700', color: C.fg, marginBottom: 6 },
  mute: { color: C.mute, fontSize: sc(12.5) },
  input: { backgroundColor: C.input, borderWidth: 1, borderColor: C.inputBorder, borderRadius: 12, padding: sc(11), fontSize: sc(15), color: C.fg, marginBottom: 8 },
  btn: { borderRadius: 14, paddingVertical: sc(13), alignItems: 'center', marginTop: 6, overflow: 'hidden', shadowColor: '#7c2d8f', shadowOpacity: 0.3, shadowRadius: 10, shadowOffset: { width: 0, height: 6 }, elevation: 4 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: sc(15) },
  btnS: { backgroundColor: C.input, borderWidth: 1, borderColor: C.accent, borderRadius: 14, paddingVertical: sc(11), alignItems: 'center', marginTop: 6 },
  btnSText: { color: C.accent, fontWeight: '600', fontSize: sc(14) },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: { paddingHorizontal: 9, paddingVertical: 2, borderRadius: 999, fontSize: 11, fontWeight: '700', overflow: 'hidden' },
  big: { fontSize: sc(34), fontWeight: '800', color: C.fg },
  body: { color: C.fg, fontSize: sc(14) },
});
/** Switch theme: copies values into C / GRAD / S in place; caller re-renders (App bumps a key). */
export function applyTheme(key, scale) {
  const th = THEMES[key] || THEMES.glass;
  Object.assign(C, th.C); Object.assign(GRAD, th.GRAD); Object.assign(T, { key: THEMES[key] ? key : 'glass', dark: th.dark, blur: th.blur, blurTint: th.blurTint, scale: scale || T.scale || 1 });
  Object.assign(S, makeStyles());
}
applyTheme('glass');



const gradFor = (color) => color === C.ok ? GRAD.ok : color === C.amber ? GRAD.amber : color === C.violet || color === C.warn ? GRAD.red : GRAD.btn;
export const Btn = ({ title, onPress, secondary, color, disabled, icon, busy }) => secondary ? (
  <TouchableOpacity disabled={disabled || busy} onPress={onPress} activeOpacity={0.75} style={[S.btnS, { minHeight: sc(46), justifyContent: 'center' }, disabled ? { opacity: 0.5 } : null]}>
    <View style={S.row}>{busy ? <ActivityIndicator size="small" color={C.accent} /> : icon ? <Ionicons name={icon} size={sc(16)} color={C.accent} /> : null}<Text style={S.btnSText}>{title}</Text></View></TouchableOpacity>) : (
  <TouchableOpacity disabled={disabled || busy} onPress={onPress} activeOpacity={0.85} style={[S.btn, { minHeight: sc(50), justifyContent: 'center' }, disabled ? { opacity: 0.5 } : null]}>
    <LinearGradient colors={gradFor(color)} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} />
    <View style={S.row}>{busy ? <ActivityIndicator size="small" color="#fff" /> : icon ? <Ionicons name={icon} size={sc(17)} color="#fff" /> : null}<Text style={S.btnText}>{title}</Text></View></TouchableOpacity>);

/** Glass card: translucent frosted panel (no native blur module needed); use for highlighted panels. */
export const Glass = ({ children, style, tint = 'light' }) => (
  <View style={[S.card, { padding: 0, backgroundColor: 'transparent' }, style]}>
    <View style={{ ...StyleSheet.absoluteFillObject, backgroundColor: T.blur ? (T.dark ? 'rgba(17,24,39,0.66)' : 'rgba(255,255,255,0.66)') : C.card }} />
    <View style={{ padding: 14 }}>{children}</View></View>);

/** Counter with a coloured ring — for "7 / 10", received / short / excess. */
export const Ring = ({ value, label, color = C.accent, size = 84 }) => (
  <View style={{ alignItems: 'center' }}>
    <View style={{ width: size, height: size, borderRadius: size / 2, borderWidth: 6, borderColor: color, alignItems: 'center', justifyContent: 'center', backgroundColor: T.dark ? 'rgba(17,24,39,0.6)' : 'rgba(255,255,255,0.7)', shadowColor: color, shadowOpacity: 0.35, shadowRadius: 10, elevation: 3 }}>
      <Text style={{ fontSize: size * 0.34, fontWeight: '800', color }}>{value}</Text></View>
    <Text style={[S.mute, { marginTop: 6, fontWeight: '600' }]}>{label}</Text></View>);

const pillColor = { AVAILABLE: ['#d1fae5', C.ok], AT_CUSTOMER: ['#e0f2fe', '#0369a1'], ALLOCATED: ['#fef3c7', C.amber], IN_RETURN: ['#fef3c7', C.amber], HELD: ['#fee2e2', C.warn], DAMAGED: ['#fee2e2', C.warn], OPEN: ['#e0f2fe', '#0369a1'], READY: ['#fef3c7', C.amber], PENDING: ['#fef3c7', C.amber], APPLIED: ['#d1fae5', C.ok], REJECTED: ['#fee2e2', C.warn], EXCEPTION: ['#fef3c7', C.amber], DONE: ['#d1fae5', C.ok], FAILED: ['#fee2e2', C.warn], LOADED: ['#e0f2fe', '#0369a1'], EMPTY: ['#d1fae5', C.ok], OK: ['#d1fae5', C.ok], REJECT: ['#fee2e2', C.warn], PDI_PENDING: ['#fef3c7', C.amber], IN_WIP: ['#fef3c7', C.amber], IN_TRANSIT: ['#fef3c7', C.amber], CUSTOMER: ['#e0f2fe', '#0369a1'], STOCK_TRANSFER: ['#ede9fe', '#6d28d9'], EMPTY_RETURN: ['#fef3c7', C.amber], RESERVED: ['#fef3c7', C.amber], PICKED: ['#e0f2fe', '#0369a1'] };
export const Pill = ({ s }) => { const [bg, fg] = pillColors()[s] || (T.dark ? ['#1f2937', '#d1d5db'] : ['#e5e7eb', '#374151']); return <Text style={[S.pill, { backgroundColor: bg, color: fg }]}>{s}</Text>; };

export const Toast = ({ msg }) => msg ? (
  <View style={{ position: 'absolute', bottom: 24, left: 16, right: 16, backgroundColor: msg.err ? 'rgba(185,28,28,0.97)' : msg.warn ? 'rgba(180,83,9,0.97)' : 'rgba(4,120,87,0.97)', padding: sc(13), borderRadius: 14, flexDirection: 'row', alignItems: 'center', gap: 10, shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 12, elevation: 8 }}>
    <Ionicons name={msg.err ? 'close-circle' : msg.warn ? 'alert-circle' : 'checkmark-circle'} size={sc(26)} color="#fff" />
    <Text style={{ color: '#fff', fontWeight: '700', fontSize: sc(15), flex: 1 }}>{msg.text}</Text></View>) : null;

export function useToast() {
  const [msg, setMsg] = useState(null); const t = useRef();
  const show = (text, kind) => { clearTimeout(t.current); setMsg({ text, err: kind === 'err', warn: kind === 'warn' }); feedback(kind === 'err' ? 'err' : kind === 'warn' ? 'warn' : kind === 'done' ? 'done' : 'ok'); t.current = setTimeout(() => setMsg(null), kind === 'err' ? 4000 : 1800); };
  return [msg, show];
}

/** ScanInput: hardware scanners act as a keyboard and send Enter; the field keeps focus and clears after each read.
 *  The camera button opens a barcode/QR scanner for phones. */
export function ScanInput({ onScan, placeholder = 'Scan tag / QR', autoFocus = true, disabled }) {
  const [v, setV] = useState(''); const [cam, setCam] = useState(false); const [focused, setFocused] = useState(false); const [last, setLast] = useState(null); const [kb, setKb] = useState(false); const ref = useRef(); const busy = useRef(false);
  const submit = async (val) => {
    const s = (val ?? v).trim(); if (!s || busy.current) return;
    busy.current = true; setV(''); setLast({ s: s.length > 34 ? s.slice(0, 32) + '…' : s, t: new Date() });
    try { await onScan(s); } finally { busy.current = false; setTimeout(() => ref.current?.focus(), 50); }
  };
  useEffect(() => { if (autoFocus) setTimeout(() => ref.current?.focus(), 200); }, []);
  useEffect(() => { if (!cam && autoFocus) setTimeout(() => ref.current?.focus(), 300); }, [cam]);
  return (
    <View>
      <View style={S.row}>
        <View style={{ flex: 1 }}>
          <TextInput ref={ref} value={v} onChangeText={setV} onSubmitEditing={() => submit()} blurOnSubmit={false} placeholder={placeholder} editable={!disabled} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
            style={[S.input, { marginBottom: 0, fontSize: sc(17), borderColor: focused ? C.ok : C.accent, borderWidth: 2, paddingRight: 34 }]} autoCapitalize="characters" autoCorrect={false} showSoftInputOnFocus={kb} returnKeyType="done" />
          <View style={{ position: 'absolute', right: 10, top: 0, bottom: 0, justifyContent: 'center' }}><View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: focused ? C.ok : C.warn }} /></View>
        </View>
        <TouchableOpacity onPress={() => { setKb(k => !k); setTimeout(() => { ref.current?.blur(); ref.current?.focus(); }, 30); }} style={[S.btnS, { paddingHorizontal: 12, marginTop: 0, backgroundColor: kb ? C.accent : undefined }]}><Ionicons name="keypad-outline" size={sc(20)} color={kb ? '#fff' : C.accent} /></TouchableOpacity>
        <TouchableOpacity onPress={() => setCam(true)} style={[S.btn, { paddingHorizontal: 14, marginTop: 0, paddingVertical: sc(11) }]}><LinearGradient colors={GRAD.btn} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} /><Ionicons name="camera-outline" size={sc(22)} color="#fff" /></TouchableOpacity>
      </View>
      <Text style={[S.mute, { marginTop: 4, fontSize: sc(11.5) }]}>{focused ? '● Scanner ready' : '○ Tap the field to activate the scanner'}{last ? `  ·  last: ${last.s} ${last.t.toTimeString().slice(0, 8)}` : ''}</Text>
      <CameraScanner visible={cam} onClose={() => setCam(false)} onScan={(d) => { setCam(false); submit(d); }} />
    </View>);
}

export function CameraScanner({ visible, onClose, onScan }) {
  const [perm, req] = useCameraPermissions(); const lock = useRef(false); const [torch, setTorch] = useState(false);
  useEffect(() => { if (visible && perm && !perm.granted) req(); if (visible) lock.current = false; }, [visible]);
  if (!visible) return null;
  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: '#000' }}>
        {perm?.granted ? <CameraView style={{ flex: 1 }} enableTorch={torch} barcodeScannerSettings={{ barcodeTypes: ['qr', 'code128', 'code39', 'ean13', 'datamatrix', 'pdf417'] }}
          onBarcodeScanned={({ data }) => { if (lock.current) return; lock.current = true; feedback('ok'); onScan(data); }} /> : <Text style={{ color: '#fff', padding: 20 }}>Camera permission needed</Text>}
        <View style={{ position: 'absolute', top: '30%', left: '10%', right: '10%', height: 220, borderWidth: 3, borderColor: '#22d3ee', borderRadius: 14 }} />
        <Text style={{ position: 'absolute', top: '30%', marginTop: 232, alignSelf: 'center', color: '#fff', fontWeight: '600' }}>Hold the code inside the frame</Text>
        <View style={{ position: 'absolute', bottom: 30, left: 0, right: 0, flexDirection: 'row', justifyContent: 'center', gap: 14 }}>
          <TouchableOpacity onPress={() => setTorch(t => !t)} style={{ backgroundColor: torch ? '#fde047' : 'rgba(255,255,255,0.9)', paddingHorizontal: 22, paddingVertical: 12, borderRadius: 999, flexDirection: 'row', alignItems: 'center', gap: 6 }}><Ionicons name={torch ? 'flashlight' : 'flashlight-outline'} size={18} color="#111" /><Text style={{ fontWeight: '700' }}>Torch</Text></TouchableOpacity>
          <TouchableOpacity onPress={onClose} style={{ backgroundColor: 'rgba(255,255,255,0.9)', paddingHorizontal: 30, paddingVertical: 12, borderRadius: 999 }}><Text style={{ fontWeight: '700' }}>Close</Text></TouchableOpacity>
        </View>
      </View></Modal>);
}

export const AisLogo = ({ size = 34, onDark }) => <Image source={onDark ? require('../../assets/icon_on_dark.png') : require('../../assets/icon.png')} style={{ width: size, height: size, resizeMode: 'contain' }} />;
export const pillColors = () => T.dark ? { AVAILABLE: ['#064e3b', '#6ee7b7'], AT_CUSTOMER: ['#0c4a6e', '#7dd3fc'], ALLOCATED: ['#78350f', '#fcd34d'], HELD: ['#7f1d1d', '#fca5a5'], DAMAGED: ['#7f1d1d', '#fca5a5'], REJECTED: ['#7f1d1d', '#fca5a5'], APPLIED: ['#064e3b', '#6ee7b7'], DONE: ['#064e3b', '#6ee7b7'], PENDING: ['#78350f', '#fcd34d'], EXCEPTION: ['#78350f', '#fcd34d'], OPEN: ['#0c4a6e', '#7dd3fc'], READY: ['#78350f', '#fcd34d'], IN_RETURN: ['#78350f', '#fcd34d'], FAILED: ['#7f1d1d', '#fca5a5'], LOADED: ['#0c4a6e', '#7dd3fc'], EMPTY: ['#064e3b', '#6ee7b7'], OK: ['#064e3b', '#6ee7b7'], REJECT: ['#7f1d1d', '#fca5a5'], PDI_PENDING: ['#78350f', '#fcd34d'], IN_WIP: ['#78350f', '#fcd34d'], CUSTOMER: ['#0c4a6e', '#7dd3fc'], STOCK_TRANSFER: ['#4c1d95', '#c4b5fd'], EMPTY_RETURN: ['#78350f', '#fcd34d'] } : pillColor;
export const Wordmark = ({ height = 30, onDark }) => <Image source={onDark ? require('../../assets/wordmark_on_dark.png') : require('../../assets/wordmark.png')} style={{ height, width: height * 3.5, resizeMode: 'contain' }} />;

export const Header = ({ title, sub, onBack, right, logo }) => (
  <LinearGradient colors={GRAD.header} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={{ paddingTop: 42, paddingBottom: 14, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', borderBottomLeftRadius: 18, borderBottomRightRadius: 18, shadowColor: '#312e81', shadowOpacity: 0.3, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 6 }}>
    {onBack ? <TouchableOpacity onPress={onBack} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }} style={{ paddingRight: 12, paddingVertical: 4 }}><Ionicons name="chevron-back" size={26} color="#fff" /></TouchableOpacity> : null}
    {logo ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginRight: 10 }}><AisLogo size={38} onDark /><Wordmark height={26} onDark /></View> : null}
    <View style={{ flex: 1 }}>{title ? <Text style={{ color: '#fff', fontWeight: '700', fontSize: sc(17) }}>{title}</Text> : null}{sub ? <Text style={{ color: 'rgba(255,255,255,0.85)', fontSize: sc(12) }}>{sub}</Text> : null}</View>
    {right}
  </LinearGradient>);

/** Segmented control: options [[value,label]], one look everywhere (replaces ad-hoc button rows). */
export const Segmented = ({ options, value, onChange, color }) => (
  <View style={{ flexDirection: 'row', gap: 6, marginBottom: 8 }}>
    {options.map(([v, l, c]) => { const on = v === value; const bg = on ? (c || color || C.accent) : undefined;
      return (<TouchableOpacity key={String(v)} onPress={() => onChange(v)} activeOpacity={0.8} style={[S.btnS, { flex: 1, marginTop: 0, backgroundColor: bg, borderColor: on ? bg : C.accent, minHeight: sc(44), justifyContent: 'center' }]}>
        <Text style={[S.btnSText, { textAlign: 'center' }, on ? { color: '#fff' } : null]} numberOfLines={2}>{l}</Text></TouchableOpacity>); })}
  </View>);
/** Labelled switch row with the same look everywhere. */
export const SwitchRow = ({ label, hint, value, onChange, danger }) => (
  <TouchableOpacity activeOpacity={0.8} onPress={() => onChange(!value)} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: sc(8) }}>
    <View style={{ flex: 1 }}><Text style={S.body}>{label}</Text>{hint ? <Text style={S.mute}>{hint}</Text> : null}</View>
    <View style={{ width: 50, height: 28, borderRadius: 14, backgroundColor: value ? (danger ? C.warn : C.ok) : (T.dark ? '#374151' : '#cbd5e1'), justifyContent: 'center', padding: 3 }}>
      <View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: '#fff', alignSelf: value ? 'flex-end' : 'flex-start', elevation: 2 }} /></View>
  </TouchableOpacity>);
/** Empty state for lists. */
export const Empty = ({ icon = 'checkmark-done-circle-outline', text, hint }) => (
  <View style={{ alignItems: 'center', paddingVertical: sc(26) }}><Ionicons name={icon} size={sc(40)} color={C.mute} /><Text style={[S.body, { marginTop: 8, fontWeight: '600' }]}>{text}</Text>{hint ? <Text style={[S.mute, { textAlign: 'center', marginTop: 4 }]}>{hint}</Text> : null}</View>);
/** Row in a list card: left text + right element, long-press action. */
export const ListRow = ({ title, sub, right, onLongPress, index }) => (
  <TouchableOpacity activeOpacity={onLongPress ? 0.7 : 1} onLongPress={onLongPress} style={[S.card, { paddingVertical: sc(9), marginBottom: 6, flexDirection: 'row', alignItems: 'center', gap: 8 }]}>
    {index != null ? <Text style={[S.mute, { width: 24, textAlign: 'right', fontWeight: '700' }]}>{index}</Text> : null}
    <View style={{ flex: 1, minWidth: 0 }}><Text style={[S.body, { fontWeight: '600' }]} numberOfLines={1}>{title}</Text>{sub ? <Text style={S.mute} numberOfLines={2}>{sub}</Text> : null}</View>
    {right}
  </TouchableOpacity>);

export const Footer = () => (
  <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 14 }}>
    <AisLogo size={18} /><Text style={{ color: C.mute, fontSize: 11.5 }}>Asahi India Glass Ltd. · AssetTrack · Developed by DT</Text></View>);

export const Backdrop = () => (
  <View style={{ ...StyleSheet.absoluteFillObject }} pointerEvents="none">
    <LinearGradient colors={GRAD.screen} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} />
    <View style={{ position: 'absolute', top: -80, left: -60, width: 260, height: 260, borderRadius: 130, backgroundColor: GRAD.blobs[0] }} />
    <View style={{ position: 'absolute', top: 220, right: -90, width: 240, height: 240, borderRadius: 120, backgroundColor: GRAD.blobs[1] }} />
    <View style={{ position: 'absolute', bottom: -70, left: 40, width: 220, height: 220, borderRadius: 110, backgroundColor: GRAD.blobs[2] }} />
  </View>);
export const Page = ({ children, refreshing, onRefresh }) => <View style={{ flex: 1 }}><Backdrop /><ScrollView style={S.screen} contentContainerStyle={[S.pad, { paddingBottom: sc(40) }]} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={C.accent} colors={[C.accent]} /> : undefined}>{children}</ScrollView></View>;
export const Screen = ({ children }) => <View style={{ flex: 1 }}><Backdrop />{children}</View>;
