// Customer HHT - VPN into the AIS network (FortiClient VPN app on the HHT, AIS SSL-VPN account given by AIS IT).
// AssetTrack does not hold the VPN itself: it sees whether a VPN is up and opens FortiClient with one tap.
// Developed by DT
import { Linking } from 'react-native';
import { requireOptionalNativeModule } from 'expo-modules-core';

const Native = requireOptionalNativeModule('AisScanner');
export const VPN_APPS = ['com.fortinet.forticlient_vpn', 'com.fortinet.forticlient'];   // FortiClient VPN (free), FortiClient (EMS)

export const vpnActive = () => { try { return !!(Native && Native.isVpnActive()); } catch (e) { return false; } };

/** Opens FortiClient. Returns 'opened', 'store' (not installed - Play Store page opened) or 'none'. */
export async function openVpnApp() {
  try { if (Native && Native.openApp(VPN_APPS)) return 'opened'; } catch (e) {}
  for (const u of [`market://details?id=${VPN_APPS[0]}`, `https://play.google.com/store/apps/details?id=${VPN_APPS[0]}`]) {
    try { await Linking.openURL(u); return 'store'; } catch (e) {}
  }
  return 'none';
}
