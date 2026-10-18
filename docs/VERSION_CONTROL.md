# AIS AssetTrack — Version Control & Release Policy
Developed by DT · Asahi India Glass Ltd.

## 1. Repository
- One Git repository on GitHub (private): `server/`, `hht/`, `docs/`, CI in `.github/workflows/build.yml`.
- **`main` is always releasable.** Every commit on `main` passes all tests in CI and produces installable builds.
- No passwords, keys, databases or logs are committed (`.gitignore` excludes `*.db`, `secret.key`, `job.key`, `settings.env`, `logs/`, `node_modules/`, build output). The only password in the source is the documented first-run admin default, which the server forces to be changed at first login.

## 2. Version numbers (Semantic Versioning `MAJOR.MINOR.PATCH`)
| Part | Raise when | Example |
|---|---|---|
| MAJOR | a change needs a data migration or HHTs/servers that are not compatible with the old one | 1.x → 2.0.0 |
| MINOR | a new screen, function or report (compatible) | 1.28.4 → 1.29.0 |
| PATCH | a fix only, no new function | 1.28.3 → 1.28.4 |

Server and HHT have **separate** version numbers, because many releases change only one of them.

| Component | Where the version lives |
|---|---|
| Server | `server/app/config.py` → `APP_VERSION` |
| HHT | `hht/app.json` → `version` and `android.versionCode` (+1 every HHT release); `hht/package.json` → `version` |

The server tells HHTs below `PALLET_MIN_CLIENT` to update.

## 3. Tags and GitHub releases (made by CI)
| Tag | Contents |
|---|---|
| `server-vX.Y.Z` | `AIS_AssetTrack_Server_Portable.zip`, `AIS_AssetTrack_Server_EXE.zip` |
| `hht-vX.Y.Z` | `AIS_AssetTrack_HHT_X.Y.Z.apk` and the fixed-name `AIS_AssetTrack_HHT.apk` (latest link) |

A tag is never moved or reused. A wrong release is fixed by the next PATCH version.

## 4. Change log
`server/CHANGELOG.md` holds the history of **both** components, newest first. Each heading names the versions and date, e.g.
`## Server 1.29.0 + HHT 2.22.0 - 2026-10-18 - <short title>`, followed by what changed in plain words for users and IT
(who reported it, if a user reported it). `hht/CHANGELOG.md` is kept only for the early HHT 1.x history.

## 5. Branches
| Branch | Use |
|---|---|
| `main` | releasable code; CI builds and publishes from here |
| `fix/<topic>` | a bug fix, merged to `main` when tests pass |
| `feat/<topic>` | a new function |
| `release/<topic>` | a group of changes reviewed together before release |
| `ui/<topic>-sample`, `preview/<topic>` | screen samples shown for approval before building; **delete after the decision** |

Merged and sample branches are deleted after use (GitHub → Branches). Current leftovers to delete by the repository owner: `fix/*`, `preview/*`, `ui/*-sample`.

## 6. Dependencies
- Server libraries are pinned to exact versions in `server/requirements.txt`; build tools in `server/requirements-build.txt`.
- HHT libraries are fixed by `hht/package-lock.json`; CI installs with `npm ci`.
- Before each MINOR release run `pip-audit -r server/requirements.txt` and `npm audit --omit=dev` in `hht/`. A library is upgraded only together with a full test run, and noted in the CHANGELOG.

## 7. How to make a release (checklist)
1. Make the change on a branch.
2. Run the checks:
   ```
   cd server
   PALLET_BENCH_SCHEDULER=0 python -m pytest -q tests
   PALLET_PICKLIST_SOURCE=APP PYTHONPATH=. PALLET_BENCH_SCHEDULER=0 python tests/test_parts_flow.py
   PYTHONPATH=. PALLET_BENCH_SCHEDULER=0 python tests/process_rules_check.py
   PYTHONPATH=. PALLET_BENCH_SCHEDULER=0 python tests/audit_fixes_check.py
   ```
3. Raise the version(s) (section 2) and add the CHANGELOG entry (section 4).
4. Merge to `main` and push. CI tests, builds and publishes `server-v…` / `hht-v…`.
5. Check that the GitHub release has its files, then install (Portable zip over the AssetTrack folder; APK on HHTs).
6. Keep the previous zip / APK until the new one is confirmed in use (rollback = install the previous release; the database is upgraded only by adding columns, so an older server still starts).
