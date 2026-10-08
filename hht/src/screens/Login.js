import React, { useState, useEffect } from 'react';
import { View, Text, TextInput, Image } from 'react-native';
import { S, Btn, Page, useToast, Toast, C } from '../ui/kit';
import { login, setServer, getServer, APP_VERSION } from '../lib/api';
import { kv } from '../lib/db';

export default function Login({ onDone, deviceId }) {
  const [u, setU] = useState(''); const [p, setP] = useState(''); const [srv, setSrv] = useState(getServer() || ''); const [busy, setBusy] = useState(false); const [msg, toast] = useToast();
  useEffect(() => { kv.get('last_user').then(x => x && setU(x)); }, []);
  const go = async () => {
    setBusy(true);
    try { await setServer(srv); const r = await login(u.trim().toLowerCase(), p, deviceId); await kv.set('last_user', r.user_id); if (!r.plant) throw new Error('HHT login needs a plant user'); onDone(r); }
    catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  return (<View style={{ flex: 1, backgroundColor: C.bg }}><Page>
    <View style={{ alignItems: 'center', marginTop: 60, marginBottom: 20 }}><Image source={require('../../assets/logo.png')} style={{ width: 240, height: 148, resizeMode: 'contain', marginBottom: 8 }} /><Text style={S.mute}>TRACK · MONITOR · CONTROL · v{APP_VERSION}</Text></View>
    <View style={S.card}>
      <Text style={S.mute}>Server URL</Text><TextInput style={S.input} value={srv} onChangeText={setSrv} autoCapitalize="none" placeholder="http://server:8001" />
      <Text style={S.mute}>User ID</Text><TextInput style={S.input} value={u} onChangeText={setU} autoCapitalize="none" />
      <Text style={S.mute}>Password</Text><TextInput style={S.input} value={p} onChangeText={setP} secureTextEntry onSubmitEditing={go} />
      <Btn title={busy ? 'Signing in…' : 'Sign in'} onPress={go} disabled={busy} />
      <Text style={[S.mute, { marginTop: 10, textAlign: 'center' }]}>Device {deviceId}</Text>
    </View>
    <Text style={[S.mute, { textAlign: 'center' }]}>Developed by DT · AIS Glass</Text>
  </Page><Toast msg={msg} /></View>);
}
