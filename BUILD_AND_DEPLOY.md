# AIS AssetTrack — Build & Deploy Guide
Developed by DT · Asahi India Glass Ltd.

Versions are not repeated here: the server version is `APP_VERSION` in `server/app/config.py`, the HHT version is in `hht/app.json`. What changed in each release is in `server/CHANGELOG.md`.

## 1. Rules that always apply
- **One AssetTrack server for all plants.** All HHTs and web users connect to it.
- **Inside the AIS network only.** Nothing is published to the internet. Customer HHTs use the AIS SSL-VPN (FortiClient) restricted to the AssetTrack server port (default 8001).
- **Back up** `pallet.db` (SQLite) **and** `secret.key` together, every day. Without `secret.key`, printed QR labels and signed-in HHTs are no longer valid.
- Change the bootstrap admin password at first login (the server forces it).

## 2. Server on an AIS PC — Portable zip (recommended)
For PCs without Python, without admin rights, or with antivirus that removes self-built EXE files. The zip contains only the official, signed python.org runtime and the server source.
1. From release `server-v<version>` download `AIS_AssetTrack_Server_Portable.zip`.
2. Unzip into the AssetTrack folder (e.g. `E:\AssetTrack`). Existing data (`server\pallet.db`, `server\secret.key`, `server\settings.env`) is not in the zip and is kept.
3. Run `START_ASSETTRACK.bat`. The AT tray icon appears and the web page opens at `http://localhost:8001`.
4. **Update:** unzip the new zip over the same folder, then run `Restart_AssetTrack_Server.bat`.
5. Start with Windows: put a shortcut to `START_ASSETTRACK.bat` in `shell:startup`.

Details: `docs/PORTABLE_SERVER.txt`. The `AIS_AssetTrack_Server_EXE.zip` is an alternative; it is unsigned, so strict antivirus may remove it unless IT whitelists it.

## 3. Server on Windows Server + IIS + SQL Server (IT)
See `docs/DEPLOY_IIS_SQLSERVER.md` (Python 3.12 x64, ODBC Driver 18, HttpPlatformHandler, `server/sql/create_db.sql`, `web.config`, `scheduler.ps1` every 5 minutes).

## 4. Settings
Copy `server/settings.env.example` to `server/settings.env` and set what is needed (database URL, integration mode `STUB` / `OFF` / `LIVE`, EBS URLs, SMTP, port). Restart the server after a change. The full list is in `server/README.md`.

## 5. HHT app
- **Install:** download `AIS_AssetTrack_HHT.apk` from the latest GitHub release (or from the server's HHT download page) and install it on the HHT.
- **Connect:** on the server PC, tray icon → *HHT setup QR*; scan it on the HHT (Setup → 1. Server). Log in with a plant user.
- **Customer HHT:** pair from the web page Masters → Customers → 📱 HHT. See `docs/CUSTOMER_HHT_ACCESS.md`.
- Bluetooth printer: pair in Android settings, then select it in the app Settings.

## 6. Building from source (developers)
The CI on GitHub builds everything; local builds are only for development.

Server (Python 3.12):
```
cd server
pip install -r requirements.txt -r requirements-build.txt
python run.py                                   # http://localhost:8001
PALLET_BENCH_SCHEDULER=0 python -m pytest -q tests
```
HHT (Node 20, JDK 17, Android SDK):
```
cd hht
npm ci
npx expo prebuild -p android
cd android && ./gradlew assembleRelease
```

## 7. CI and releases
`.github/workflows/build.yml` runs on every push to `main`:
1. Server tests (end-to-end flow, process rules, review fixes, pytest). **Nothing is built if a test fails.**
2. Server Windows EXE and Portable zip → GitHub release `server-v<APP_VERSION>`.
3. HHT APK → GitHub release `hht-v<version>` and the fixed latest link.

How to cut a release: `docs/VERSION_CONTROL.md`.
