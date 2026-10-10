// AIS Pallet HHT - entry: session, navigation, idle lock, crash guard. Developed by DT
import React, { useEffect, useRef, useState } from 'react';
import { View, Text, BackHandler, Alert, AppState, TouchableOpacity } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useKeepAwake } from 'expo-keep-awake';
import * as Application from 'expo-application';
import * as Clipboard from 'expo-clipboard';
import { openDb, kv, logActivity, pendingCount } from './src/lib/db';
import { applyTheme, T, S, C, Btn, Screen, Page, Header, AisLogo } from './src/ui/kit';
import { loadSession, setToken, me as getMe, hasToken, setApiDevice, APP_VERSION } from './src/lib/api';
import { state as syncState, subscribe, syncNow, startAutoSync, stopAutoSync, setDeviceId, refreshPending } from './src/lib/sync';
import { initFeedback } from './src/lib/feedback';
import Login from './src/screens/Login';
import Home from './src/screens/Home';
import Dock from './src/screens/Dock';
import Yard from './src/screens/Yard';
import ReturnSlip from './src/screens/ReturnSlip';
import { GateIn, GateOut, Damage, Lookup, Pending, Settings } from './src/screens/Misc';
import { Move, Receipt, Pdi, Misses } from './src/screens/Movement';

/** Crash guard: a screen error shows a recovery page instead of a frozen white screen; details can be copied for DT. */
class Guard extends React.Component {
  state = { err: null };
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) { try { logActivity('APP_CRASH', this.props.screen, String(err?.message || err), { stack: String(info?.componentStack || '').slice(0, 1500) }); } catch (e) { } }
  render() {
    if (!this.state.err) return this.props.children;
    const text = `AssetTrack HHT v${APP_VERSION} · screen ${this.props.screen}\n${String(this.state.err?.message || this.state.err)}\n${String(this.state.err?.stack || '').slice(0, 1200)}`;
    return (<Screen><Header title="Something went wrong" sub="The screen hit an error - your scans are safe in the outbox" /><Page>
      <View style={S.card}><Text style={S.body}>{String(this.state.err?.message || this.state.err)}</Text></View>
      <Btn title="Back to Home" icon="home-outline" onPress={() => { this.setState({ err: null }); this.props.onHome(); }} />
      <Btn title="Copy details for DT" secondary icon="copy-outline" onPress={() => Clipboard.setStringAsync(text).catch(() => { })} />
    </Page></Screen>);
  }
}

export default function App() {
  useKeepAwake();
  const [ready, setReady] = useState(false); const [me, setMe] = useState(null); const [screen, setScreen] = useState('home'); const [sync, setSync] = useState({ ...syncState });
  const [deviceId, setDev] = useState('HHT'); const [themeKey, setThemeKey] = useState('glass'); const [uiKey, setUiKey] = useState(0); const [locked, setLocked] = useState(false); const [lookupCode, setLookupCode] = useState(null);
  const lastTouch = useRef(Date.now()); const idleMin = useRef(30);

  useEffect(() => {
    (async () => {
      await openDb(); await loadSession();
      const tk = (await kv.get('theme')) || 'glass'; const scale = (await kv.get('ui_scale')) || 1; applyTheme(tk, scale); setThemeKey(tk);
      idleMin.current = (await kv.get('idle_min')) ?? 30;
      const id = (await kv.get('device_id')) || ('HHT-' + (Application.getAndroidId?.() || Math.random().toString(36).slice(2, 8)).toUpperCase().slice(-8));
      await kv.set('device_id', id); setDev(id); setDeviceId(id); setApiDevice(id);
      initFeedback().catch(() => { });
      const m = await getMe(); if (m && hasToken()) { setMe(m); startAutoSync(); syncNow().catch(() => { }); }
      await refreshPending(); setReady(true);
    })();
    const un = subscribe(s => { setSync(s); if (s.lastError === 'LOGIN') { setMe(null); } });
    return () => { un(); stopAutoSync(); };
  }, []);
  useEffect(() => { const h = BackHandler.addEventListener('hardwareBackPress', () => { if (screen !== 'home') { setScreen('home'); return true; } return false; }); return () => h.remove(); }, [screen]);
  // idle lock: after N minutes without a touch (or when the app comes back from the background after that long) ask for the password again
  useEffect(() => {
    const check = () => { if (me && idleMin.current > 0 && Date.now() - lastTouch.current > idleMin.current * 60000) setLocked(true); };
    const t = setInterval(check, 30000);
    const sub = AppState.addEventListener('change', (st) => { if (st === 'active') check(); });
    return () => { clearInterval(t); sub.remove(); };
  }, [me]);

  if (!ready) return <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#eef2ff' }}><AisLogo size={80} /><Text style={{ marginTop: 12, color: '#475569' }}>AssetTrack is starting…</Text></View>;
  const onLogin = (r) => { logActivity('LOGIN', r.user_id, r.plant); setMe(r); setLocked(false); lastTouch.current = Date.now(); setScreen('home'); startAutoSync(); syncNow({ full: true }).catch(() => { }); };
  if (!me || locked) return <React.Fragment key={themeKey + uiKey}><StatusBar style={T.dark ? 'light' : 'dark'} /><Login deviceId={deviceId} locked={locked && !!me} user={me?.user_id} onDone={onLogin} /></React.Fragment>;

  const go = (sc) => { if (sc !== 'home') logActivity('SCREEN_OPEN', sc); setScreen(sc); };
  const back = () => { setLookupCode(null); setScreen('home'); };
  const logout = async () => {
    const n = await pendingCount();
    const doIt = async () => { await logActivity('LOGOUT', me?.user_id); await setToken(null); await kv.set('me', null); stopAutoSync(); setMe(null); };
    if (n > 0) Alert.alert('Scans not yet synced', `${n} scan(s) are still waiting to reach the server. They stay saved on this device and will sync after the next login. Log out anyway?`, [{ text: 'Stay' }, { text: 'Log out', style: 'destructive', onPress: doIt }]);
    else doIt();
  };
  const refreshUi = () => setUiKey(k => k + 1);
  const screens = {
    home: <Home me={me} sync={sync} nav={go} onLogout={logout} onLookup={(code) => { setLookupCode(code); go('lookup'); }} />,
    dock: <Dock onBack={back} />, yardret: <Dock onBack={back} yard />, yard: <Yard onBack={back} />, slip: <ReturnSlip onBack={back} deviceId={deviceId} />,
    gatein: <GateIn onBack={back} />, gateout: <GateOut onBack={back} />, damage: <Damage onBack={back} />, lookup: <Lookup onBack={back} initial={lookupCode} />,
    move: <Move onBack={back} />, receipt: <Receipt onBack={back} />, pdi: <Pdi onBack={back} />, misses: <Misses onBack={back} />,
    pending: <Pending onBack={back} />, settings: <Settings onBack={back} deviceId={deviceId} onTheme={(k) => { setThemeKey(k); refreshUi(); }} onUi={(opts) => { if (opts.idle_min != null) idleMin.current = opts.idle_min; refreshUi(); }} />,
  };
  return (<View style={{ flex: 1 }} onTouchStart={() => { lastTouch.current = Date.now(); }}>
    <React.Fragment key={themeKey + ':' + uiKey}><StatusBar style="light" /><Guard screen={screen} onHome={back}>{screens[screen] || screens.home}</Guard></React.Fragment>
  </View>);
}
