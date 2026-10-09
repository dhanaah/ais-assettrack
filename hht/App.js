// AIS Pallet HHT - entry. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, BackHandler } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useKeepAwake } from 'expo-keep-awake';
import * as Application from 'expo-application';
import { openDb, kv, logActivity } from './src/lib/db';
import { applyTheme, T } from './src/ui/kit';
import { loadSession, setToken, me as getMe, hasToken, setApiDevice } from './src/lib/api';
import { state as syncState, subscribe, syncNow, startAutoSync, stopAutoSync, setDeviceId, refreshPending } from './src/lib/sync';
import Login from './src/screens/Login';
import Home from './src/screens/Home';
import Dock from './src/screens/Dock';
import Yard from './src/screens/Yard';
import ReturnSlip from './src/screens/ReturnSlip';
import { GateIn, GateOut, Damage, Lookup, Pending, Settings } from './src/screens/Misc';

export default function App() {
  useKeepAwake();
  const [ready, setReady] = useState(false); const [me, setMe] = useState(null); const [screen, setScreen] = useState('home'); const [sync, setSync] = useState({ ...syncState }); const [deviceId, setDev] = useState('HHT'); const [themeKey, setThemeKey] = useState('glass');

  useEffect(() => {
    (async () => {
      await openDb(); await loadSession();
      const tk = (await kv.get('theme')) || 'glass'; applyTheme(tk); setThemeKey(tk);
      const id = (await kv.get('device_id')) || ('HHT-' + (Application.getAndroidId?.() || Math.random().toString(36).slice(2, 8)).toUpperCase().slice(-8));
      await kv.set('device_id', id); setDev(id); setDeviceId(id); setApiDevice(id);
      const m = await getMe(); if (m && hasToken()) { setMe(m); startAutoSync(); syncNow().catch(() => {}); }
      await refreshPending(); setReady(true);
    })();
    const un = subscribe(s => { setSync(s); if (s.lastError === 'LOGIN') { setMe(null); } });
    return () => { un(); stopAutoSync(); };
  }, []);
  useEffect(() => { const h = BackHandler.addEventListener('hardwareBackPress', () => { if (screen !== 'home') { setScreen('home'); return true; } return false; }); return () => h.remove(); }, [screen]);

  if (!ready) return <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}><Text>Loading…</Text></View>;
  if (!me) return <React.Fragment key={themeKey}><StatusBar style={T.dark ? 'light' : 'dark'} /><Login deviceId={deviceId} onDone={(r) => { logActivity('LOGIN', r.user_id, r.plant); setMe(r); setScreen('home'); startAutoSync(); syncNow({ full: true }).catch(() => {}); }} /></React.Fragment>;

  const go = (sc) => { if (sc !== 'home') logActivity('SCREEN_OPEN', sc); setScreen(sc); };
  const back = () => setScreen('home');
  const logout = async () => { await logActivity('LOGOUT', me?.user_id); await setToken(null); await kv.set('me', null); stopAutoSync(); setMe(null); };
  const screens = {
    home: <Home me={me} sync={sync} nav={go} onLogout={logout} />,
    dock: <Dock onBack={back} />, yard: <Yard onBack={back} />, slip: <ReturnSlip onBack={back} deviceId={deviceId} />,
    gatein: <GateIn onBack={back} />, gateout: <GateOut onBack={back} />, damage: <Damage onBack={back} />, lookup: <Lookup onBack={back} />,
    pending: <Pending onBack={back} />, settings: <Settings onBack={back} deviceId={deviceId} onTheme={setThemeKey} />,
  };
  return <React.Fragment key={themeKey}><StatusBar style="light" />{screens[screen] || screens.home}</React.Fragment>;
}
