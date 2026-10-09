# AIS AssetTrack HHT — Android app v1.1.0
Developed by DT · React Native / Expo · works on rugged Android HHTs (keyboard-wedge scanners) and ordinary phones (camera)

## Screens (shown by role permission)
| Tile | Permission | Offline? |
|---|---|---|
| Dock Out-ward Scan | DOCK_SCAN | Yes – scans validated against local cache, queued; **Confirm** (Pick List Control) needs server |
| OUT Gate | OUT_GATE_SCAN | No (gate documents are online-only; manual override + supervisor PIN) |
| Return Slip B1/B2 | RETURN_SLIP_B | Yes – device-series slip number, prints PROVISIONAL, replayed on sync |
| IN Gate | IN_GATE_SCAN | No |
| Yard In-ward Scan | YARD_SCAN | Yes – accept-other-plant switch, damaged switch; **Reconcile & close** needs server |
| Damage / Tag issue | DAMAGE_MARK | Yes |
| Pallet Lookup | – | Yes (history when online) |
| Pending & Sync | – | shows outbox, errors, offline docs, Sync now |
| Settings | – | server URL, Bluetooth printer, full resync |

## Offline design
- Every scan → `outbox` row (UUID event_id) in local SQLite **before** anything else; status bar shows ONLINE/OFFLINE and pending count.
- Sync engine (`src/lib/sync.js`): replays offline documents → pushes events in order (server is idempotent) → heartbeat → pulls reference delta. Runs every 60 s, on reconnect, and right after each scan when online.
- Local rules (`src/lib/rules.js`) mirror the server: unknown/retired tag, foreign pallet, not AVAILABLE, duplicate, qty reached.
- Rejected events stay visible in Pending & Sync with the server's reason.

## Scanning
`ScanInput` keeps focus and clears after Enter, so Zebra/Honeywell/Urovo keyboard-wedge scanners work with no SDK. The 📷 button opens the camera for phones (QR, Code128, Code39, EAN13, DataMatrix).
Slip QR payload: `RTS|slip_no|plant|customer|qty`. Challan QR: `CHL|challan_no|picklist_no|qty`.

## Bluetooth printing
Optional native module `react-native-bluetooth-escpos-printer` (ESC/POS 2"/3"). It is not in the default build (keeps CI green); add it with `npm i react-native-bluetooth-escpos-printer` before `expo prebuild` when a printer is in use — the app detects it automatically and falls back to on-screen slips without it. Pair the printer in Android Bluetooth settings, then Settings → List paired printers → tap to select. Without the native module (Expo Go) the slip text is shown on screen instead.

## Build
```
npm install
npx expo prebuild -p android          # generates android/ with the printer native module
npx expo run:android                   # debug APK on a connected device
# or cloud build:
npx eas build -p android --profile preview   # produces an installable APK
```
Set the server URL on the login screen (e.g. `http://10.10.5.20:8001`, or the plant edge service address when deployed).
First login requires network; afterwards the app works offline with the cached session until the token expires (12 h default, `PALLET_TOKEN_HOURS` on server).

## Device identity
`device_id` is generated once per device (`HHT-<androidId tail>`) and stored; it stamps every event and appears in the Sync Monitor. Admin can block a device from the web app.
