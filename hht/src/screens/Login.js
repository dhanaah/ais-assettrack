// Sign in / unlock: user ID + password. Server, printer and vehicles are in Setup (gear) - the line on top shows the
// server and whether it answers (checked every 15 s). Developed by DT
import React, { useState, useEffect } from 'react';
import { View, Text, TextInput, Image, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { S, C, Btn, Page, useToast, Toast, Footer, Screen, setNet } from '../ui/kit';
import { login, getServer, APP_VERSION, api, getActiveServer, setPlant, getPlant, saveLogin, me as getMe } from '../lib/api';
import { startAutoSync, stopAutoSync } from '../lib/sync';
import { saveCred, checkCred } from '../lib/localauth';
import { kv, pendingCount } from '../lib/db';
import { canPrint, testPrint } from '../lib/printer';

export default function Login({ onDone, deviceId, locked, user, onCustomer, onSetup }) {
  const [pbusy, setPbusy] = useState(false);
  const [u, setU] = useState(user || ''); const [p, setP] = useState(''); const [busy, setBusy] = useState(false); const [showPw, setShowPw] = useState(false); const [msg, toast] = useToast();
  useEffect(() => { if (!user) kv.get('last_user').then(x => x && setU(x)); }, []);
  const [srvOk, setSrvOk] = useState(null);
  const [choose, setChoose] = useState(null);
  // sign-in not finished (error, other plant refused, cancel): back to the plant used before; a locked session syncs again
  const restore = async (prev) => { await setPlant(prev); if (locked) startAutoSync(); };
  const pickPlant = async (r, code, prev) => {
    const last = await kv.get('last_plant'); const pend = await pendingCount();
    if (last && last !== code && pend > 0) { toast(`${pend} scan(s) of plant ${last} not synced yet - sign in for ${last} and sync first`, 'err'); await restore(prev); return; }
    // plant check passed: only now the token and the user are saved on this HHT
    await setPlant(code === r.plant ? null : code); await kv.set('last_plant', code);
    const me2 = await saveLogin(r, code); await saveCred('plant', r.user_id, p); setChoose(null); toast('Signed in · ' + code, 'done'); onDone(me2);
  };
  // idle lock without network: the password of this user's last online sign-in on this HHT unlocks
  const offlineUnlock = async (prev) => {
    const ok = await checkCred('plant', user, p);
    if (ok === null) throw new Error('Offline - cannot reach the server, and this user has not signed in online on this HHT yet');
    if (!ok) throw new Error('Wrong password');
    await setPlant(prev); const m = await getMe(); toast('Unlocked (no network)', 'done'); onDone(m);
  };
  useEffect(() => { let on = true; const chk = async () => { if (!getServer()) { on && setSrvOk(false); return; } try { const h = await api('/health', { auth: false, timeout: 6000 }); if (on) { setSrvOk({ v: h.version, at: (getActiveServer() || '').replace(/^https?:\/\//, '') }); setNet({ state: 'online' }); } } catch (e) { if (on) { setSrvOk(false); setNet({ state: 'offline' }); } } };
    chk(); const t = setInterval(chk, 15000); return () => { on = false; clearInterval(t); }; }, []);
  const go = async () => {
    if (!u.trim() || !p) return toast('Enter user ID and password', 'warn');
    setBusy(true); const prev = getPlant(); stopAutoSync();     // no sync while the sign-in is half done
    let handed = false;                                          // true once pickPlant / plant choice / offline unlock took over
    try {
      await setPlant(null);                                    // sign in first with the user's own plant, then choose
      const r = await login(u.trim().toLowerCase(), p, deviceId); await kv.set('last_user', r.user_id);
      const pls = r.plants || (r.plant ? [{ code: r.plant, name: r.plant }] : []);
      if (!pls.length) throw new Error('This user has no plant for the HHT - ask the admin');
      if (pls.length === 1) { handed = true; await pickPlant(r, pls[0].code, prev); return; }
      const last = await kv.get('last_plant');
      if (locked && last && pls.some((x) => x.code === last)) { handed = true; await pickPlant(r, last, prev); return; }   // unlock: same plant
      handed = true; setChoose({ r, pls, last, prev });
    }
    catch (e) {
      if (e.offline && locked && user) { try { handed = true; await offlineUnlock(prev); } catch (x) { handed = false; toast(x.message, 'err'); } return; }
      toast(e.status === 426 ? e.message : e.offline ? 'Offline - cannot reach the server. Check Wi-Fi or open Setup › 1. Server' : e.message, 'err');
    } finally { setBusy(false); if (!handed) await restore(prev); }
  };
  if (choose) return (<Screen><Page>
    <View style={[S.card, { marginTop: 50 }]}><Text style={S.h1}>Select plant</Text><Text style={S.mute}>{choose.r.name} - you work for more than one plant. Pick lists, GCS and pallets of the selected plant are shown.</Text></View>
    {choose.pls.map((x) => <TouchableOpacity key={x.code} onPress={() => pickPlant(choose.r, x.code, choose.prev)} style={[S.card, { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: x.code === choose.last ? 2 : 1, borderColor: x.code === choose.last ? C.accent : C.line }]}>
      <Ionicons name="business-outline" size={26} color={C.accent} /><View style={{ flex: 1 }}><Text style={S.h2}>{x.code}</Text><Text style={S.mute}>{x.name}{x.code === choose.last ? ' · last used' : ''}</Text></View><Ionicons name="chevron-forward" size={20} color={C.mute} /></TouchableOpacity>)}
    <Btn title="Cancel" secondary onPress={() => { restore(choose.prev); setChoose(null); }} />
  </Page><Toast msg={msg} /></Screen>);
  return (<Screen><Page>
    <View style={{ alignItems: 'center', marginTop: locked ? 30 : 50, marginBottom: 16 }}><Image source={require('../../assets/icon.png')} style={{ width: 100, height: 100, resizeMode: 'contain' }} /><Image source={require('../../assets/wordmark.png')} style={{ width: 250, height: 76, resizeMode: 'contain' }} /><Text style={S.mute}>v{APP_VERSION} · device {deviceId}</Text></View>
    {locked ? <View style={[S.card, { borderLeftWidth: 5, borderLeftColor: C.amber, flexDirection: 'row', alignItems: 'center', gap: 10 }]}><Ionicons name="lock-closed-outline" size={22} color={C.amber} /><Text style={[S.body, { flex: 1 }]}>Locked after a period without use. Enter your password to continue - nothing was lost.</Text></View> : null}
    <View style={S.card}>
      {!locked ? <TouchableOpacity onPress={onSetup} style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 12, padding: 10, borderRadius: 12, backgroundColor: srvOk ? '#dcfce7' : srvOk === false ? '#fee2e2' : C.input }}>
        <View style={{ width: 11, height: 11, borderRadius: 6, backgroundColor: srvOk ? '#16a34a' : srvOk === false ? '#dc2626' : '#94a3b8' }} />
        <Text style={{ flex: 1, color: '#0f172a', fontWeight: '600' }} numberOfLines={2}>{srvOk ? 'Online' : srvOk === false ? (getServer() ? 'Offline - tap to check Setup' : 'No server set - tap to set up') : 'Checking…'}</Text>
        <Ionicons name="settings-outline" size={20} color="#334155" /></TouchableOpacity> : null}
      <Text style={S.mute}>User ID</Text><TextInput style={S.input} value={u} onChangeText={setU} autoCapitalize="none" autoCorrect={false} editable={!locked} returnKeyType="next" />
      <Text style={S.mute}>Password</Text>
      <View style={S.row}><TextInput style={[S.input, { flex: 1 }]} value={p} onChangeText={setP} secureTextEntry={!showPw} onSubmitEditing={go} returnKeyType="go" autoFocus={!!locked} /><TouchableOpacity onPress={() => setShowPw(s => !s)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} style={{ marginBottom: 8 }}><Ionicons name={showPw ? 'eye-off-outline' : 'eye-outline'} size={22} color={C.mute} /></TouchableOpacity></View>
      <Btn title={locked ? 'Unlock' : 'Sign in'} icon={locked ? 'lock-open-outline' : 'log-in-outline'} onPress={go} busy={busy} />
    </View>
    {!locked ? <Btn title="Setup · Server · Printer · Vehicles" secondary icon="construct-outline" onPress={onSetup} /> : null}
    {!locked ? <Btn title="Test printer" secondary icon="print-outline" busy={pbusy} onPress={async () => {
      if (!(await canPrint())) { toast('No printer selected yet - choose it in Setup › 2. Printer', 'warn'); return onSetup('printer'); }
      setPbusy(true); try { await testPrint(await kv.get('plant')); toast('Test page sent - check the printer', 'done'); } catch (e) { toast('Printer not working: ' + e.message, 'err'); } finally { setPbusy(false); } }} /> : null}
    {!locked && onCustomer ? <TouchableOpacity onPress={onCustomer} style={[S.card, { flexDirection: 'row', alignItems: 'center', gap: 10 }]}>
      <Ionicons name="storefront-outline" size={22} color={C.accent} /><View style={{ flex: 1 }}><Text style={{ fontWeight: '700', color: C.fg }}>Customer device</Text>
      <Text style={S.mute}>HHT at a customer site for Option A return slips - pair with the QR from AIS</Text></View><Ionicons name="chevron-forward" size={18} color={C.mute} /></TouchableOpacity> : null}
    <Footer credit />
  </Page><Toast msg={msg} /></Screen>);
}
