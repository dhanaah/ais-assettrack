# AIS AssetTrack — Returnable Pallet Tracking
**TRACK · MONITOR · CONTROL** · Asahi India Glass Ltd. · Developed by DT

AssetTrack tracks AIS returnable pallets from production through dispatch, the customer and back to the yard.
It has one central server (web admin + API) and an Android app for hand-held terminals (HHTs).

| Folder | What | Current version |
|---|---|---|
| `server/` | Python FastAPI server: API, admin web pages, print pages, customer API, Windows tray app. SQLite (portable / tray) or SQL Server (IIS) | see `server/app/config.py` (`APP_VERSION`) |
| `iis/` | Install the same server on IIS + SQL Server (`Setup_IIS.ps1`, data copy from SQLite) | – |
| `hht/` | Android HHT app (Expo / React Native): offline outbox, scanner and camera, Bluetooth printing, customer HHT mode | see `hht/app.json` (`version`, `versionCode`) |
| `docs/` | Process flows, management deck, deployment guides for IT, master-data Excel template, sample documents | – |
| `.github/workflows/build.yml` | CI: tests, server EXE + portable zip, HHT APK, GitHub releases | – |

The release history of **both** server and HHT is in [`server/CHANGELOG.md`](server/CHANGELOG.md).

## Network rule
AssetTrack runs **inside the AIS network only. Nothing is published to the internet.**
Customer HHTs reach the server over the AIS SSL-VPN (FortiClient, restricted account that can reach only the AssetTrack server port).
See [`docs/DEPLOY_SERVER_IT.md`](docs/DEPLOY_SERVER_IT.md).

## Where to start
| You want to… | Read |
|---|---|
| Install / update the server on an AIS PC | [`BUILD_AND_DEPLOY.md`](BUILD_AND_DEPLOY.md), [`docs/PORTABLE_SERVER.txt`](docs/PORTABLE_SERVER.txt) |
| Install on IIS + SQL Server (second way to host; the portable server stays as it is) | [`docs/DEPLOY_IIS_SQLSERVER.md`](docs/DEPLOY_IIS_SQLSERVER.md), `iis\README_IIS.txt` |
| Connect customer HHTs | [`docs/CUSTOMER_HHT_ACCESS.md`](docs/CUSTOMER_HHT_ACCESS.md) |
| Understand server settings and the API | [`server/README.md`](server/README.md) |
| Build or install the HHT app | [`hht/README.md`](hht/README.md) |
| Make a release / version rules | [`docs/VERSION_CONTROL.md`](docs/VERSION_CONTROL.md) |

## Downloads (GitHub releases)
- HHT APK, always the newest: `releases/latest/download/AIS_AssetTrack_HHT.apk`
- Server: release `server-v<version>` → `AIS_AssetTrack_Server_Portable.zip` (recommended on AIS PCs, no self-built EXE; the same zip installs on IIS) or `AIS_AssetTrack_Server_EXE.zip`.
