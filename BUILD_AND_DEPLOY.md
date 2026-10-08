# AIS AssetTrack — Build & Deploy Guide (v1.3.0)
Developed by DT · Asahi India Glass Ltd.

## Package contents
| Path | What |
|---|---|
| `server/` | FastAPI API + admin web UI + print pages + external customer API. `README.md` inside has the full API map and env vars |
| `hht/` | Android HHT app (Expo / React Native). `README.md` inside has screens, offline design, build commands |
| `docs/` | Flow charts (PDF + HTML), management deck, master-upload Excel template, sample challan / return slip, screen mock-ups |
| `.github/workflows/build.yml` | CI: server smoke test + automatic APK build (artifact on every push; attached to a Release on `hht-v*` tags) |
| `server/sql/create_db.sql` | SQL Server database creation (snapshot isolation) |
| `server/web.config` | IIS HttpPlatformHandler config |
| `server/scheduler.ps1` | 5-minute retry job for EBS / GCS queue |

## 1. Server — development / pilot (SQLite, 5 minutes)
```
cd server
pip install -r requirements.txt
python run.py                     # http://localhost:8001
```
Login `admin` / `Admin@123` → change password → Masters → Import → upload `docs/Pallet_Tracking_Master_Template_v0.4.xlsx` (filled).

## 2. Server — production (Windows Server + IIS + SQL Server)
1. Install Python 3.11 x64, **ODBC Driver 18 for SQL Server**, IIS + **HttpPlatformHandler**.
2. Run `server/sql/create_db.sql` on SQL Server.
3. Copy `server/` to `C:\inetpub\pallet_server`, run `pip install -r requirements.txt`.
4. Edit `web.config`: `processPath` (python.exe), `PALLET_DB_URL`, `PALLET_JWT_SECRET` (long random), `PALLET_INTEGRATION_MODE` (`STUB` until endpoints are live, then `LIVE`), EBS URLs.
5. IIS → new site → physical path = that folder → HTTPS binding. Start. Check `https://server/api/v1/health`.
6. Task Scheduler → `scheduler.ps1` every 5 minutes.
7. DMZ / reverse proxy: publish **only** `/api/ext/v1/*` to the internet.
8. Backups: SQL Server full nightly + 15-min log backups (or Always On Basic AG on a second instance).

## 3. HHT app — build the APK
Option A (no local toolchain): push to GitHub → Actions builds `AIS_AssetTrack_HHT_*.apk` → download from the workflow artifacts (or Releases on an `hht-v*` tag).

Option B (local, Node 20 + JDK 17 + Android SDK):
```
cd hht
npm install
npx expo prebuild -p android
npx expo run:android            # debug build on a connected device
# or: cd android && ./gradlew assembleRelease  → android/app/build/outputs/apk/release/app-release.apk
```
Option C (Expo cloud): `npx eas build -p android --profile preview`.

Install the APK on the HHT, open the app, set the server URL (e.g. `http://10.10.5.20:8001` or the edge service), log in with a plant user.
Bluetooth printer: pair in Android settings → Settings in app → List paired printers → select.

## 4. Go-live checklist (Chennai, target 30 Nov 2026)
- [ ] Plants / users / customers / transporters / tag batches imported (template)
- [ ] Tags fixed on all Chennai pallets, census imported (sheet 6_Pallets) — opening stock correct
- [ ] Customer API key issued to HMIL (Masters → Customers → API key) and shared securely
- [ ] EBS SO + challan endpoints and GCS endpoint configured; `PALLET_INTEGRATION_MODE=LIVE`
- [ ] HHTs registered (first login binds device), supervisors set their PIN
- [ ] "Pull the cable" test passed: scans offline → sync → no loss, no duplicates
- [ ] Parallel run 17–28 Nov; day-end check green 3 days running
