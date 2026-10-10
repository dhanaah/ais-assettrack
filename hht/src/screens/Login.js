// Sign in / unlock. Server name only (ports tried automatically); "Test connection" shows version and response time. Developed by DT
import React, { useState, useEffect } from 'react';
import { View, Text, TextInput, Image, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { S, C, Btn, Page, useToast, Toast, Footer, Screen } from '../ui/kit';
import { login, setServer, getServer, APP_VERSION, api, getActiveServer } from '../lib/api';
import { kv } from '../lib/db';

export default function Login({ onDone, deviceId, locked, user }) {
  const [u, setU] = useState(user || ''); const [p, setP] = useState(''); const [srv, setSrv] = useState(getServer() || ''); const [busy, setBusy] = useState(false); const [test, setTest] = useState(null); const [showPw, setShowPw] = useState(false); const [msg, toast] = useToast();
  useEffect(() => { if (!user) kv.get('last_user').then(x => x && setU(x)); }, []);
  const go = async () => {
    if (!u.trim() || !p) return toast('Enter user ID and password', 'warn');
    setBusy(true);
    try { await setServer(srv); const r = await login(u.trim().toLowerCase(), p, deviceId); await kv.set('last_user', r.user_id); if (!r.plant) throw new Error('HHT login needs a plant user'); toast('Signed in', 'done'); onDone(r); }
    catch (e) { toast(e.status === 426 ? e.message : e.offline ? `Cannot reach "${srv}" - check Wi-Fi and the server name` : e.message, 'err'); } finally { setBusy(false); }
  };
  const testConn = async () => {
    setTest({ busy: true });
    try { await setServer(srv); const t0 = Date.now(); const h = await api('/health', { auth: false, timeout: 8000 }); setTest({ ok: true, text: `${h.app} v${h.version} · ${Date.now() - t0} ms · ${(getActiveServer() || '').replace(/^https?:\/\//, '')}` }); toast('Server reachable', 'ok'); }
    catch (e) { setTest({ ok: false, text: e.offline ? 'No answer - check Wi-Fi, server name and that the server is running' : e.message }); toast('Server not reachable', 'err'); }
  };
  return (<Screen><Page>
    <View style={{ alignItems: 'center', marginTop: locked ? 30 : 50, marginBottom: 16 }}><Image source={require('../../assets/icon.png')} style={{ width: 100, height: 100, resizeMode: 'contain' }} /><Image source={require('../../assets/wordmark.png')} style={{ width: 250, height: 76, resizeMode: 'contain' }} /><Text style={S.mute}>v{APP_VERSION} · device {deviceId}</Text></View>
    {locked ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.amber, flexDirection: 'row', alignItems: 'center', gap: 10 }]}><Ionicons name="lock-closed-outline" size={22} color={C.amber} /><Text style={[S.body, { flex: 1 }]}>Locked after a period without use. Enter your password to continue - nothing was lost.</Text></View> : null}
    <View style={S.card}>
      {!locked ? <View><Text style={S.mute}>Server name</Text>
        <View style={S.row}><TextInput style={[S.input, { flex: 1, marginBottom: 0 }]} value={srv} onChangeText={(t) => { setSrv(t); setTest(null); }} autoCapitalize="none" autoCorrect={false} placeholder="assettrack" /><TouchableOpacity onPress={testConn} style={[S.btnS, { marginTop: 0, paddingHorizontal: 12, minHeight: 44, justifyContent: 'center' }]}><Text style={S.btnSText}>{test?.busy ? '…' : 'Test'}</Text></TouchableOpacity></View>
        {test && !test.busy ? <Text style={[S.mute, { color: test.ok ? C.ok : C.warn, marginTop: 4 }]}>{test.ok ? '✓ ' : '✗ '}{test.text}</Text> : <Text style={[S.mute, { marginTop: 4 }]}>Ports 80 / 8001 / 8002 / 8003 are tried automatically.</Text>}
        <View style={{ height: 10 }} /></View> : null}
      <Text style={S.mute}>User ID</Text><TextInput style={S.input} value={u} onChangeText={setU} autoCapitalize="none" autoCorrect={false} editable={!locked} returnKeyType="next" />
      <Text style={S.mute}>Password</Text>
      <View style={S.row}><TextInput style={[S.input, { flex: 1 }]} value={p} onChangeText={setP} secureTextEntry={!showPw} onSubmitEditing={go} returnKeyType="go" autoFocus={!!locked} /><TouchableOpacity onPress={() => setShowPw(s => !s)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} style={{ marginBottom: 8 }}><Ionicons name={showPw ? 'eye-off-outline' : 'eye-outline'} size={22} color={C.mute} /></TouchableOpacity></View>
      <Btn title={locked ? 'Unlock' : 'Sign in'} icon={locked ? 'lock-open-outline' : 'log-in-outline'} onPress={go} busy={busy} />
    </View>
    <Footer />
  </Page><Toast msg={msg} /></Screen>);
}
