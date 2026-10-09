# scripts/ — one-click helpers (Windows .bat)
Edit `_common.bat` if Python is not on PATH or you want another port.

| Script | Use |
|---|---|
| `server_setup.bat` | once: venv + pip install (no admin needed) |
| `server_run.bat` | run server with auto-reload, opens the browser (admin / Admin@123) |
| `server_run_offline_test.bat` | same, with EBS/GCS set to OFF to rehearse the retry queue |
| `server_smoke_test.bat` | health + login check |
| `server_reset_db.bat` | delete dev SQLite DB (asks YES) |
| `server_package.bat` | zip server for IIS deployment |
| `hht_setup.bat` | once: npm install |
| `hht_run_device.bat` | build+install debug app on USB HHT with hot reload |
| `hht_start_metro.bat` | reload JS changes on an installed debug app |
| `hht_build_apk.bat` | release APK → `dist\AIS_AssetTrack_HHT_v<ver>.apk` |
| `hht_install_apk.bat` | adb install latest APK from `dist\` (or drag an APK onto it) |
| `hht_clean.bat` | wipe generated android/ and caches |
| `git_push.bat "msg"` | commit + push; GitHub Actions builds the APK |
| `git_release_tags.bat` | push version tags (release with APK attached) |

Typical dev loop: `server_run.bat` in one window, `hht_run_device.bat` once, then `hht_start_metro.bat` for JS edits; `git_push.bat` at the end of the day.
