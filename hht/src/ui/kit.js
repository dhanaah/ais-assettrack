// Small UI kit + ScanInput (hardware scanner wedge + camera). Developed by DT
import React, { useEffect, useRef, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, Alert, StyleSheet, Modal, Vibration, ScrollView, Image, RefreshControl, ActivityIndicator, Animated, Easing, LayoutAnimation, Platform, UIManager } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { THEMES } from './theme';
import { feedback } from '../lib/feedback';
import { kv } from '../lib/db';
import { onHardwareScan, scannerAvailable } from '../lib/scanner';

export const C = { ...THEMES.glass.C };
if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) UIManager.setLayoutAnimationEnabledExperimental(true);
const ND = Platform.OS !== 'web';   // native driver for transforms / opacity on the device

/** Confirm dialog that also works on web (Alert.alert is silent there). Last button = yes. */
export function ask(title, msg, buttons) {
  if (Platform.OS === 'web') {
    const yes = buttons[buttons.length - 1], no = buttons[0];
    if (typeof window !== 'undefined' && window.confirm(`${title}\n\n${msg}`)) { yes.onPress && yes.onPress(); }
    else if (no !== yes) { no.onPress && no.onPress(); }
    return;
  }
  Alert.alert(title, msg, buttons);
}

/** Screen entry: each screen fades in and slides a little from the right (or from below for home). */
export function Enter({ children, from = 'right' }) {
  const a = useRef(new Animated.Value(0)).current;
  useEffect(() => { Animated.timing(a, { toValue: 1, duration: 260, easing: Easing.out(Easing.cubic), useNativeDriver: ND }).start(); }, []);
  const t = from === 'right' ? [{ translateX: a.interpolate({ inputRange: [0, 1], outputRange: [36, 0] }) }] : [{ translateY: a.interpolate({ inputRange: [0, 1], outputRange: [18, 0] }) }];
  return <Animated.View style={{ flex: 1, opacity: a, transform: t }}>{children}</Animated.View>;
}

/** Group button: rises and fades in (staggered by its position), squeezes slightly while pressed. */
function GroupBtn({ k, wide, onPress, style, children }) {
  const a = useRef(new Animated.Value(0)).current; const p = useRef(new Animated.Value(1)).current;
  useEffect(() => { Animated.spring(a, { toValue: 1, delay: 40 + k * 55, friction: 7, tension: 70, useNativeDriver: ND }).start(); }, []);
  const press = (v) => Animated.spring(p, { toValue: v, friction: 5, tension: 160, useNativeDriver: ND }).start();
  return (<Animated.View style={{ width: wide ? '100%' : '48.5%', opacity: a, transform: [{ translateY: a.interpolate({ inputRange: [0, 1], outputRange: [22, 0] }) }, { scale: Animated.multiply(p, a.interpolate({ inputRange: [0, 1], outputRange: [0.92, 1] })) }] }}>
    <TouchableOpacity onPress={onPress} onPressIn={() => press(0.95)} onPressOut={() => press(1)} activeOpacity={0.9} style={style}>{children}</TouchableOpacity></Animated.View>);
}
export const GRAD = { ...THEMES.glass.GRAD };
export const T = { key: 'glass', dark: false, blur: 40, blurTint: 'light', scale: 1, glow: null };
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
  Object.assign(C, th.C); Object.assign(GRAD, th.GRAD); Object.assign(T, { key: THEMES[key] ? key : 'glass', dark: th.dark, blur: th.blur, blurTint: th.blurTint, scale: scale || T.scale || 1, glow: th.glow || null });
  Object.assign(S, makeStyles());
  if (T.glow) {          // neon: cards and buttons give off a soft glow in the accent colour
    Object.assign(S, StyleSheet.create({
      card: { ...StyleSheet.flatten(S.card), shadowColor: T.glow, shadowOpacity: 0.28, shadowRadius: 14, shadowOffset: { width: 0, height: 0 }, elevation: 6 },
      btn: { ...StyleSheet.flatten(S.btn), shadowColor: T.glow, shadowOpacity: 0.75, shadowRadius: 16, shadowOffset: { width: 0, height: 0 }, elevation: 10 },
      btnS: { ...StyleSheet.flatten(S.btnS), shadowColor: T.glow, shadowOpacity: 0.35, shadowRadius: 10, shadowOffset: { width: 0, height: 0 } },
    }));
  }
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
export const Pill = ({ s, label }) => { const [bg, fg] = pillColors()[s] || (T.dark ? ['#1f2937', '#d1d5db'] : ['#e5e7eb', '#374151']); return <Text style={[S.pill, { backgroundColor: bg, color: fg }]}>{label || s}</Text>; };

export const Toast = ({ msg }) => msg ? (
  <View style={{ position: 'absolute', bottom: 24, left: 16, right: 16, backgroundColor: msg.err ? 'rgba(185,28,28,0.97)' : msg.warn ? 'rgba(180,83,9,0.97)' : 'rgba(4,120,87,0.97)', padding: sc(13), borderRadius: 14, flexDirection: 'row', alignItems: 'center', gap: 10, shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 12, elevation: 8 }}>
    <Ionicons name={msg.err ? 'close-circle' : msg.warn ? 'alert-circle' : 'checkmark-circle'} size={sc(26)} color="#fff" />
    <Text style={{ color: '#fff', fontWeight: '700', fontSize: sc(15), flex: 1 }}>{msg.text}</Text></View>) : null;

export function useToast() {
  const [msg, setMsg] = useState(null); const t = useRef();
  const show = (text, kind) => { clearTimeout(t.current); setMsg({ text, err: kind === 'err', warn: kind === 'warn' }); feedback(kind === 'err' ? 'err' : kind === 'warn' ? 'warn' : kind === 'done' ? 'done' : 'ok'); t.current = setTimeout(() => setMsg(null), kind === 'err' ? 4000 : 1800); };
  return [msg, show];
}

/** Scan mode for every scan field: 'native' = the device's built-in scanner (keyboard wedge, sends Enter) or
 *  'camera' = phone camera. Switch on any scan field or in Settings, so any Android device can do every task. */
export const SCAN = { mode: 'native', listeners: new Set() };
export async function loadScanMode() { try { const m = await kv.get('scan_mode'); if (m) { SCAN.mode = m; SCAN.listeners.forEach((f) => f(m)); } } catch (e) { } }
export async function setScanMode(m) { SCAN.mode = m; SCAN.listeners.forEach((f) => f(m)); try { await kv.set('scan_mode', m); } catch (e) { } }
export function useScanMode() { const [m, setM] = useState(SCAN.mode); useEffect(() => { SCAN.listeners.add(setM); setM(SCAN.mode); return () => { SCAN.listeners.delete(setM); }; }, []); return m; }

function ScanModeSwitch({ mode }) {
  const opt = (k, icon, label) => <TouchableOpacity key={k} onPress={() => setScanMode(k)} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, backgroundColor: mode === k ? C.accent : 'transparent' }}><Ionicons name={icon} size={sc(13)} color={mode === k ? '#fff' : C.mute} /><Text style={{ fontSize: sc(11.5), fontWeight: '700', color: mode === k ? '#fff' : C.mute }}>{label}</Text></TouchableOpacity>;
  return <View style={{ flexDirection: 'row', alignSelf: 'flex-end', borderWidth: 1, borderColor: C.line, borderRadius: 999, padding: 2, marginBottom: 6 }}>{opt('native', 'barcode-outline', 'Scanner')}{opt('camera', 'camera-outline', 'Camera')}</View>;
}

/** ScanInput - no keyboard at all: the device's own scanner (trigger button) or the camera reads the code.
 *  Scanner mode: the hardware scanner sends the barcode to the app directly (Android broadcast - see lib/scanner.js);
 *  there is no text field, so nothing can be typed and no keyboard ever opens. Camera mode: the camera reads it. */
export function ScanInput({ onScan, placeholder = 'Scan tag / QR', autoFocus = true, disabled }) {
  const mode = useScanMode(); const camMode = mode === 'camera';
  const [cam, setCam] = useState(false); const [last, setLast] = useState(null); const busy = useRef(false);
  // scans that arrive while the previous one is still being checked wait in line (first in, first out) - none is dropped
  const queue = useRef([]); const live = useRef(true); const onScanRef = useRef(onScan); onScanRef.current = onScan;
  useEffect(() => { live.current = true; return () => { live.current = false; queue.current = []; }; }, []);
  const submit = async (val) => {
    const s = String(val ?? '').trim(); if (!s || disabled) return;
    if (queue.current.length >= 50) return;                        // runaway guard
    queue.current.push(s); if (busy.current) return;
    busy.current = true;
    try {
      while (queue.current.length && live.current) {
        const x = queue.current.shift(); setLast({ s: x.length > 34 ? x.slice(0, 32) + '…' : x, t: new Date() });
        try { await onScanRef.current(x); } catch (e) { }
        await new Promise((r) => setTimeout(r, 0));               // let the screen re-render (latest onScan / state) before the next one
      }
    } finally { busy.current = false; }
  };
  const ref = useRef(submit); ref.current = submit;
  useEffect(() => { if (camMode || disabled) return undefined; return onHardwareScan((code) => ref.current(code)); }, [camMode, disabled]);
  const hw = scannerAvailable();
  return (
    <View>
      <ScanModeSwitch mode={mode} />
      {camMode ? <TouchableOpacity disabled={disabled} onPress={() => setCam(true)} style={[S.btn, { marginTop: 0, marginBottom: 8, paddingVertical: sc(18), flexDirection: 'row', justifyContent: 'center', gap: 10 }]}><LinearGradient colors={GRAD.btn} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} /><Ionicons name="camera-outline" size={sc(26)} color="#fff" /><Text style={[S.btnText, { fontSize: sc(17) }]}>Tap to scan</Text></TouchableOpacity> : null}
      <View style={S.row}>
        {!camMode ? <View style={[S.input, { flex: 1, marginBottom: 0, borderWidth: 2, borderColor: hw ? C.ok : C.warn, flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: sc(52) }]}>
          <Ionicons name="barcode-outline" size={sc(24)} color={hw ? C.ok : C.warn} />
          <Text style={{ flex: 1, fontSize: sc(15), fontWeight: '600', color: C.fg }} numberOfLines={2}>{hw ? `${placeholder} - press the scanner trigger` : 'No hardware scanner on this device - use Camera'}</Text>
        </View> : <View style={{ flex: 1 }} />}
        {!camMode ? <TouchableOpacity onPress={() => setCam(true)} style={[S.btn, { paddingHorizontal: 14, marginTop: 0, paddingVertical: sc(11) }]}><LinearGradient colors={GRAD.btn} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} /><Ionicons name="camera-outline" size={sc(22)} color="#fff" /></TouchableOpacity> : null}
      </View>
      <Text style={[S.mute, { marginTop: 4, fontSize: sc(11.5) }]}>{camMode ? '📷 Camera mode' : hw ? '● Scanner ready (no keyboard)' : '○ Scanner not available'}{last ? `  ·  last: ${last.s} ${last.t.toTimeString().slice(0, 8)}` : ''}</Text>
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

/** Connection state shown on every screen: set by the app (sync / customer route), read by the header dot. */
export const NET = { state: null, pending: 0, text: '', listeners: new Set() };   // state: 'online' | 'offline' | 'syncing' | null
export function setNet(part) { Object.assign(NET, part); NET.listeners.forEach((f) => f({ ...NET })); }
export function useNet() { const [n, setN] = useState({ ...NET }); useEffect(() => { NET.listeners.add(setN); setN({ ...NET }); return () => { NET.listeners.delete(setN); }; }, []); return n; }
export function NetBadge({ onPress }) {
  const n = useNet(); if (!n.state) return null;
  const col = n.state === 'online' ? '#22c55e' : n.state === 'syncing' ? '#f59e0b' : '#ef4444';
  const txt = n.state === 'online' ? 'Online' : n.state === 'syncing' ? 'Syncing' : 'Offline';
  return (<TouchableOpacity onPress={onPress} disabled={!onPress} style={{ flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: 'rgba(0,0,0,0.22)', paddingHorizontal: 9, paddingVertical: 4, borderRadius: 999, marginLeft: 6 }}>
    <View style={{ width: 9, height: 9, borderRadius: 5, backgroundColor: col, borderWidth: 1, borderColor: '#fff' }} />
    <Text style={{ color: '#fff', fontWeight: '700', fontSize: sc(11) }}>{txt}{n.pending ? ` · ${n.pending}` : ''}</Text></TouchableOpacity>);
}

export const Header = ({ title, sub, onBack, right, logo, below }) => (
  <LinearGradient colors={GRAD.header} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={{ paddingTop: 42, paddingBottom: below ? 58 : 14, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', borderBottomLeftRadius: 18, borderBottomRightRadius: 18, shadowColor: '#312e81', shadowOpacity: 0.3, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 6 }}>
    {onBack ? <TouchableOpacity onPress={onBack} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }} style={{ paddingRight: 12, paddingVertical: 4 }}><Ionicons name="chevron-back" size={26} color="#fff" /></TouchableOpacity> : null}
    {logo ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginRight: 10 }}><AisLogo size={38} onDark /><Wordmark height={26} onDark /></View> : null}
    <View style={{ flex: 1 }}>{title ? <Text style={{ color: '#fff', fontWeight: '700', fontSize: sc(17) }}>{title}</Text> : null}{sub ? <Text style={{ color: 'rgba(255,255,255,0.85)', fontSize: sc(12) }}>{sub}</Text> : null}</View>
    {right}<NetBadge />
    {below ? <View style={{ position: 'absolute', left: 14, right: 14, bottom: 10 }}>{below}</View> : null}
  </LinearGradient>);

/** Signed-in user, compact: initials, name on one line, plant and number of roles (tap = full role list). */
export function UserChip({ me, onLogout }) {
  const ini = String(me.name || me.user_id || '?').replace(/\(.*\)/g, '').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  const roles = me.roles || [];
  return (<View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: 'rgba(255,255,255,0.14)', borderRadius: 14, paddingVertical: 6, paddingHorizontal: 8 }}>
    <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: 'rgba(255,255,255,0.92)', alignItems: 'center', justifyContent: 'center' }}><Text style={{ color: '#312e81', fontWeight: '800', fontSize: 13 }}>{ini}</Text></View>
    <TouchableOpacity style={{ flex: 1 }} activeOpacity={0.7} onPress={() => Alert.alert(me.name || me.user_id, `Plant ${me.plant || '-'}\nRoles: ${roles.join(', ') || '-'}`)}>
      <Text style={{ color: '#fff', fontWeight: '700', fontSize: sc(14) }} numberOfLines={1}>{me.name || me.user_id}</Text>
      <Text style={{ color: 'rgba(255,255,255,0.8)', fontSize: sc(11.5) }} numberOfLines={1}>{me.plant || 'All plants'} · {roles.length} role{roles.length === 1 ? '' : 's'} ›</Text>
    </TouchableOpacity>
    {onLogout ? <TouchableOpacity onPress={onLogout} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 5, borderRadius: 999, backgroundColor: 'rgba(0,0,0,0.18)' }}><Ionicons name="log-out-outline" size={16} color="#fff" /><Text style={{ color: '#fff', fontSize: 12, fontWeight: '600' }}>Logout</Text></TouchableOpacity> : null}
  </View>);
}

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
export const ListRow = ({ title, sub, right, onLongPress, onPress, index, big }) => (   // big: large title (pallet number at vehicle loading)
  <TouchableOpacity activeOpacity={onLongPress || onPress ? 0.7 : 1} onLongPress={onLongPress} onPress={onPress} style={[S.card, { paddingVertical: sc(9), marginBottom: 6, flexDirection: 'row', alignItems: 'center', gap: 8 }]}>
    {index != null ? <Text style={[S.mute, { width: 24, textAlign: 'right', fontWeight: '700' }]}>{index}</Text> : null}
    <View style={{ flex: 1, minWidth: 0 }}><Text style={[S.body, { fontWeight: big ? '800' : '600' }, big ? { fontSize: sc(24), letterSpacing: 0.6 } : null]} numberOfLines={1}>{title}</Text>{sub ? <Text style={S.mute} numberOfLines={2}>{sub}</Text> : null}</View>
    {right}
  </TouchableOpacity>);

export const Footer = ({ credit }) => (
  <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 14 }}>
    <AisLogo size={18} /><Text style={{ color: C.mute, fontSize: 11.5 }}>Asahi India Glass Ltd. · AssetTrack{credit ? ' · Developed by DT' : ''}<Text style={{ opacity: 0.3, fontSize: 9.5 }}>{'  v' + (FOOT.v || '')}</Text></Text></View>);
export const FOOT = { v: '' };

export const Backdrop = () => (
  <View style={{ ...StyleSheet.absoluteFillObject }} pointerEvents="none">
    <LinearGradient colors={GRAD.screen} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ ...StyleSheet.absoluteFillObject }} />
    <View style={{ position: 'absolute', top: -80, left: -60, width: 260, height: 260, borderRadius: 130, backgroundColor: GRAD.blobs[0] }} />
    <View style={{ position: 'absolute', top: 220, right: -90, width: 240, height: 240, borderRadius: 120, backgroundColor: GRAD.blobs[1] }} />
    <View style={{ position: 'absolute', bottom: -70, left: 40, width: 220, height: 220, borderRadius: 110, backgroundColor: GRAD.blobs[2] }} />
  </View>);
export const Page = ({ children, refreshing, onRefresh }) => <View style={{ flex: 1 }}><Backdrop /><ScrollView style={S.screen} contentContainerStyle={[S.pad, { paddingBottom: sc(40) }]} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={C.accent} colors={[C.accent]} /> : undefined}>{children}</ScrollView></View>;
export const Screen = ({ children }) => <View style={{ flex: 1 }}><Backdrop />{children}</View>;

/** Home screens: one group card (coloured heading + "N waiting") with its functions as gradient buttons, two per row
 *  (an odd last button spans the row). g = { key, title, sub, icon, grad }, items = [key, title, sub, perm, icon, badgeKey]. */
export function ButtonGroup({ g, items, n = {}, nav, open = true, onToggle }) {   // onToggle: heading opens / closes the group
  const rot = useRef(new Animated.Value(open ? 1 : 0)).current;
  useEffect(() => { Animated.timing(rot, { toValue: open ? 1 : 0, duration: 240, easing: Easing.out(Easing.cubic), useNativeDriver: ND }).start(); }, [open]);
  if (!items.length) return null;
  const waiting = items.reduce((a, it) => a + (it[5] && it[0] !== 'pending' ? (n[it[5]] || 0) : 0), 0);
  // button: gradient from a light tint to the deep group colour, a large picture (icon) in the bottom-right corner
  const tint = (hex, k) => { const h = hex.replace('#', ''); const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return '#' + c.map((v) => Math.round(v + (255 - v) * k).toString(16).padStart(2, '0')).join(''); };
  const btn = (it, wide, k) => { const badge = it[5] ? n[it[5]] : 0;
    return (<GroupBtn key={it[0]} k={k} wide={wide} onPress={() => nav(it[0])} style={{ flexGrow: 1, borderRadius: 18, overflow: 'hidden', minHeight: Math.round(96 * T.scale), shadowColor: g.grad[1], shadowOpacity: 0.35, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 4 }}>
      <LinearGradient colors={[tint(g.grad[0], 0.35), g.grad[0], g.grad[1]]} locations={[0, 0.45, 1]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ flex: 1, padding: Math.round(12 * T.scale), justifyContent: 'space-between' }}>
        <View style={{ position: 'absolute', right: -14, bottom: -16, opacity: 0.2 }} pointerEvents="none"><Ionicons name={it[4]} size={Math.round(78 * T.scale)} color="#fff" /></View>
        <View style={{ position: 'absolute', top: -30, left: -30, width: 90, height: 90, borderRadius: 45, backgroundColor: 'rgba(255,255,255,0.12)' }} pointerEvents="none" />
        <View style={{ flexDirection: 'row', justifyContent: 'flex-end', minHeight: 24 }}>
          {badge ? <View style={{ backgroundColor: '#fff', borderRadius: 999, minWidth: 26, height: 24, paddingHorizontal: 8, alignItems: 'center', justifyContent: 'center' }}><Text style={{ color: it[0] === 'pending' ? '#b45309' : g.grad[1], fontWeight: '800', fontSize: 12.5 }}>{badge}</Text></View> : null}
        </View>
        <View style={{ marginTop: 6, paddingRight: 10 }}><Text style={{ color: '#fff', fontWeight: '800', fontSize: Math.round(14.5 * T.scale), textShadowColor: 'rgba(0,0,0,0.18)', textShadowRadius: 3 }} numberOfLines={3}>{it[1]}</Text>
          <Text style={{ color: 'rgba(255,255,255,0.88)', fontSize: Math.round(11 * T.scale), marginTop: 2 }} numberOfLines={2}>{it[2]}</Text></View>
      </LinearGradient></GroupBtn>); };
  // open / close: the card resizes smoothly, the arrow turns, the buttons rise in one after another
  // resize only (no create / delete animation): safe on Android while the buttons run their own rise-in animation
  const toggle = () => { LayoutAnimation.configureNext({ duration: 240, update: { type: LayoutAnimation.Types.easeInEaseOut } }); onToggle(); };
  return (<View style={[S.card, { paddingVertical: 10 }]}>
    <TouchableOpacity activeOpacity={onToggle ? 0.7 : 1} onPress={onToggle ? toggle : undefined} disabled={!onToggle} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingBottom: open ? 6 : 0 }}>
      <LinearGradient colors={g.grad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ width: 30, height: 30, borderRadius: 10, alignItems: 'center', justifyContent: 'center' }}><Ionicons name={g.icon} size={17} color="#fff" /></LinearGradient>
      <View style={{ flex: 1 }}><Text style={{ fontWeight: '800', fontSize: Math.round(15.5 * T.scale), color: C.fg, letterSpacing: 0.3 }}>{g.title.toUpperCase()}</Text><Text style={[S.mute, { fontSize: 11 }]}>{g.sub}</Text></View>
      {waiting ? <Text style={{ color: g.grad[0], fontWeight: '800', fontSize: 12 }}>{waiting} waiting</Text> : null}
      {onToggle ? <View style={{ alignItems: 'center' }}><Animated.View style={{ transform: [{ rotate: rot.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '180deg'] }) }] }}><Ionicons name="chevron-down" size={20} color={open ? g.grad[0] : C.mute} /></Animated.View>{!open ? <Text style={{ fontSize: 10, color: C.mute }}>{items.length}</Text> : null}</View> : null}
    </TouchableOpacity>
    {open ? <View style={{ flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 10, marginTop: 4 }}>{items.map((it, k) => btn(it, items.length % 2 === 1 && k === items.length - 1, k))}</View> : null}</View>);
}
