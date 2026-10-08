# AIS AssetTrack — Returnable Pallet Tracking
**TRACK · MONITOR · CONTROL** · Asahi India Glass Ltd. · Developed by DT

| Folder | What | Version |
|---|---|---|
| `server/` | FastAPI + SQL Server/SQLite API, admin web UI, external customer API, IIS deployment | 1.1.0 |
| `hht/` | Android HHT app (React Native / Expo): offline outbox, scanner + Bluetooth print | 1.1.0 |
| `docs/` | Flow charts (overview, 8 process flows, management view) as PDF + HTML source | v0.4 |

## Versioning
- Semantic versions, one tag per release: `server-v1.1.0`, `hht-v1.1.0`.
- `server/CHANGELOG.md`, `hht/CHANGELOG.md` and `hht/app.json` (`version` + `versionCode`) are bumped on every release.
- Branches: `main` = releasable; feature work on `feat/<name>`, merged by PR.

## Quick start
See `server/README.md` and `hht/README.md`.
