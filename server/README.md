# AIS AssetTrack — Server
(version: `APP_VERSION` in `app/config.py`; history: `CHANGELOG.md`)
Developed by DT · Returnable pallet tracking for AIS Glass (15 plants)

## Main functions
| Area | Status |
|---|---|
| Masters: Plants, Roles (permission matrix), Users (plant-scoped), Customers, Transporters, Pallets, Tags, Tag batches | ✅ |
| Excel import of masters (template from the web Masters page) | ✅ |
| Security: JWT login, lockout after 5 failures, forced password change, supervisor PIN, device binding/blocking, audit log | ✅ |
| Pallet state machine + pallet history + tag change history | ✅ |
| HHT sync: idempotent event push (`/sync/push`), reference pull (`/sync/pull`), sync monitor | ✅ |
| Pick List → SO post (stub) → dock scan → Pick List Control → Challan (ORACLE/APP switch) → Logistics approve → GCS out (stub) → gate out | ✅ |
| Return slip (A / B1 / B2) → gate in (GCS-IN stub) → yard scan with other-plant checkbox → reconcile → close with PIN | ✅ |
| External customer API (`/api/ext/v1`, X-API-Key) for Mode A push from outside the network | ✅ |
| Reports: availability, customer holding/aging, overdue, pallet history, tag history, tag stock, Excel export | ✅ |
| Integration retry queue + scheduler hook | ✅ (STUB / OFF / LIVE modes) |

## Quick start (dev, SQLite)
```
pip install -r requirements.txt
python run.py            # http://localhost:8001  (admin / Admin@123 — change at first login)
```
API documentation (Swagger): set `PALLET_API_DOCS=1` in `settings.env`, then http://localhost:8001/docs (off by default)

## Production on IIS + SQL Server
Installed from the portable zip with `iis\Setup_IIS.ps1` (IIS app pool + site, `web.config`, SQL Server database and login,
folder rights, health check). Guide: `docs/DEPLOY_IIS_SQLSERVER.md`. The tray / portable server is the other way and stays supported.

## Environment variables
| Var | Default | Meaning |
|---|---|---|
| PALLET_DB_URL | sqlite:///pallet.db | SQLAlchemy URL (see config.py for SQL Server forms) |
| PALLET_JWT_SECRET | random, saved once in `secret.key` | token / QR signing secret (back up `secret.key` with the database) |
| PALLET_INTEGRATION_MODE | STUB | STUB (fake success) · OFF (simulate outage, queues) · LIVE |
| PALLET_EBS_SO_URL / PALLET_EBS_CHALLAN_URL / PALLET_EBS_AUTH | – | EBS endpoints (LIVE) |
| PALLET_ADMIN_USER / PALLET_ADMIN_PASS | admin / Admin@123 | bootstrap admin (first run only; the first sign-in works only on the server PC and forces a new password) |
| PALLET_API_DOCS | 0 | 1 = show Swagger at /docs |
| PALLET_RETRY_JOB | 0 | 1 = run the 5-minute job (EBS / GCS retries, reminders) inside the server - set on IIS |
| PALLET_SERVER_PORTS | (tray fills it) | ports the HHT setup QR offers, e.g. `80` on IIS |

## API map (all under /api/v1 unless stated)
- `POST auth/login` `{user_id,password,device_id,app_version}` → token, perms, plant
- `GET plants` `POST plants` · `GET roles` `POST roles` · `GET users` `POST users` `POST users/{id}/unlock`
- `GET customers` `POST customers` · `POST customers/{plant}/{code}/api-key` (issue) `DELETE …/api-key`
- `GET transporters` `POST transporters` · `GET tag-batches` `POST tag-batches` · `GET tags/{tag}`
- `GET pallets?plant&status&customer&q` `GET pallets/{no}` `POST pallets` `POST pallets/{no}/assign-tag` `POST pallets/{no}/status`
- `POST import/masters` (multipart xlsx)
- `POST sync/push` `{events:[{event_id,device_id,event_type,payload,local_ts,offline,app_version}]}` → per-event APPLIED/REJECTED/EXCEPTION
- `GET sync/pull?since=` reference cache for HHT · `GET sync/monitor` · `POST sync/devices/{id}/block`
- `GET/POST picklists` · `POST picklists/{no}/confirm|challan|approve|gate-out|reduce-qty`
- `GET/POST slips` · `POST slips/{no}/gate-in|close` · `POST slips/{no}/resolve/{pallet}`
- `GET reports/availability|customer-holding|overdue|tag-history|tag-stock|audit|integration` · `GET reports/pallet-history/{no}` · `GET reports/export/pallets.xlsx`
- External: `GET /api/ext/v1/holding` · `POST /api/ext/v1/validate` · `POST /api/ext/v1/return-slip` · `GET /api/ext/v1/return-slip/{no}` (header `X-API-Key`)

## Event types accepted by sync/push
`PALLET_SCAN_DOCK {picklist_no, scanned}` · `PALLET_UNSCAN_DOCK` · `PALLET_SCAN_YARD {slip_no, scanned, accept_foreign, damaged}` · `DAMAGE_MARK {scanned, remarks}` · `TAG_REPLACE_REQ` · `HEARTBEAT {pending}`
Unknown types are stored as EXCEPTION for review (forward compatible with newer HHT builds).

## Pallet states
AVAILABLE → ALLOCATED (dock scan) → AT_CUSTOMER (gate out) → IN_RETURN (slip) → AVAILABLE (yard scan)
Side: HELD (other plant), DAMAGED, UNDER_REPAIR, DISCONTINUED (never reused)
