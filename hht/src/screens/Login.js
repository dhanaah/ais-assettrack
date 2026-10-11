// Sign in / unlock: user ID + password. Server, printer and vehicles are in Setup (gear) - the line on top shows the
// server and whether it answers (checked every 15 s). Developed by DT
import React, { useState, useEffect } from 'react';
import { View, Text, TextInput, Image, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { S, C, Btn, Page, useToast, Toast, Footer, Screen, setNet } from '../ui/kit';
import { login, setServer, getServer, APP_VERSION, api, getActiveServer } from '../lib/api';
import { kv } from '../lib/db';

export default function Login({ onDone, deviceId, locked, user, onCustomer, onSetup }) {
  const [u, setU] = useState(user || ''); const [p, setP] = useState(''); const [srv, setSrv] = useState(getServer() || ''); const [busy, setBusy] = useState(false); const [test, setTest] = useState(null); const [showPw, setShowPw] = useState(false); const [msg, toast] = useToast();
  useEffect(() => { if (!user) kv.get('last_user').then(x => x && setU(x)); }, []);
  const [srvOk, setSrvOk] = useState(null);
  useEffect(() => { let on = true; const chk = async () => { if (!getServer()) { on && setSrvOk(false); return; } try { const h = await api('/health', { auth: false, timeout: 6000 }); if (on) { setSrvOk({ v: h.version, at: (getActiveServer() || '').replace(/^https?:\/\//, '') }); setNet({ state: 'online' }); } } catch (e) { if (on) { setSrvOk(false); setNet({ state: 'offline' }); } } };
    chk(); const t = setInterval(chk, 15000); return () => { on = false; clearInterval(t); }; }, []);
  const go = async () => {
    if (!u.trim() || !p) return toast('Enter user ID and password', 'warn');
    setBusy(true);
    try { const r = await login(u.trim().toLowerCase(), p, deviceId); await kv.set('last_user', r.user_id); if (!r.plant) throw new Error('HHT login needs a plant user'); toast('Signed in', 'done'); onDone(r); }
    catch (e) { toast(e.status === 426 ? e.message : e.offline ? `Cannot reach the server "${getServer() || '-'}" - open Setup › 1. Server (scan the server QR)` : e.message, 'err'); } finally { setBusy(false); }
  };
  return (<Screen><Page>
    <View style={{ alignItems: 'center', marginTop: locked ? 30 : 50, marginBottom: 16 }}><Image source={require('../../assets/icon.png')} style={{ width: 100, height: 100, resizeMode: 'contain' }} /><Image source={require('../../assets/wordmark.png')} style={{ width: 250, height: 76, resizeMode: 'contain' }} /><Text style={S.mute}>v{APP_VERSION} · device {deviceId}</Text></View>
    {locked ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.amber, flexDirection: 'row', alignItems: 'center', gap: 10 }]}><Ionicons name="lock-closed-outline" size={22} color={C.amber} /><Text style={[S.body, { flex: 1 }]}>Locked after a period without use. Enter your password to continue - nothing was lost.</Text></View> : null}
    <View style={S.card}>
      {!locked ? <TouchableOpacity onPress={onSetup} style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 12, padding: 10, borderRadius: 12, backgroundColor: srvOk ? '#dcfce7' : srvOk === false ? '#fee2e2' : C.input }}>
        <View style={{ width: 11, height: 11, borderRadius: 6, backgroundColor: srvOk ? '#16a34a' : srvOk === false ? '#dc2626' : '#94a3b8' }} />
        <Text style={{ flex: 1, color: '#0f172a', fontWeight: '600' }} numberOfLines={2}>{srvOk ? `Server online · ${srvOk.at} · v${srvOk.v}` : srvOk === false ? (getServer() ? `Server offline · ${getServer()}` : 'No server set - tap to set up') : 'Checking server…'}</Text>
        <Ionicons name="settings-outline" size={20} color="#334155" /></TouchableOpacity> : null}
      <Text style={S.mute}>User ID</Text><TextInput style={S.input} value={u} onChangeText={setU} autoCapitalize="none" autoCorrect={false} editable={!locked} returnKeyType="next" />
      <Text style={S.mute}>Password</Text>
      <View style={S.row}><TextInput style={[S.input, { flex: 1 }]} value={p} onChangeText={setP} secureTextEntry={!showPw} onSubmitEditing={go} returnKeyType="go" autoFocus={!!locked} /><TouchableOpacity onPress={() => setShowPw(s => !s)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} style={{ marginBottom: 8 }}><Ionicons name={showPw ? 'eye-off-outline' : 'eye-outline'} size={22} color={C.mute} /></TouchableOpacity></View>
      <Btn title={locked ? 'Unlock' : 'Sign in'} icon={locked ? 'lock-open-outline' : 'log-in-outline'} onPress={go} busy={busy} />
    </View>
    {!locked ? <Btn title="Setup · Server · Printer · Vehicles" secondary icon="construct-outline" onPress={onSetup} /> : null}
    {!locked && onCustomer ? <TouchableOpacity onPress={onCustomer} style={[S.card, { flexDirection: 'row', alignItems: 'center', gap: 10 }]}>
      <Ionicons name="storefront-outline" size={22} color={C.accent} /><View style={{ flex: 1 }}><Text style={{ fontWeight: '700', color: C.fg }}>Customer device</Text>
      <Text style={S.mute}>HHT at a customer site for Option A return slips - pair with the QR from AIS</Text></View><Ionicons name="chevron-forward" size={18} color={C.mute} /></TouchableOpacity> : null}
    <Footer />
  </Page><Toast msg={msg} /></Screen>);
}
