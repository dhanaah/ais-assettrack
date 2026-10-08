# AIS AssetTrack — Server v1.0.0
Developed by DT · Returnable pallet tracking for AIS Glass (15 plants)

## What is in this drop (Phase 1 + Phase 2 skeleton)
| Area | Status |
|---|---|
| Masters: Plants, Roles (permission matrix), Users (plant-scoped), Customers, Transporters, Pallets, Tags, Tag batches | ✅ |
| Excel import of `Pallet_Tracking_Master_Template_v0.4.xlsx` | ✅ |
| Security: JWT login, lockout after 5 failures, forced password change, supervisor PIN, device binding/blocking, audit log | ✅ |
| Pallet state machine + pallet history + tag change history | ✅ |
| HHT sync: idempotent event push (`/sync/push`), reference pull (`/sync/pull`), sync monitor | ✅ |
| Pick List → SO post (stub) → dock scan → Pick List Control → Challan (ORACLE/APP switch) → Logistics approve → GCS out (stub) → gate out | ✅ |
| Return slip (A / B1 / B2) → gate in (GCS-IN stub) → yard scan with other-plant checkbox → reconcile → close with PIN | ✅ |
| External customer API (`/api/ext/v1`, X-API-Key) for Mode A push from outside the network | ✅ |
| Reports: availability, customer holding/aging, overdue, pallet history, tag history, tag stock, Excel export | ✅ |
| Integration retry queue + scheduler hook | ✅ (STUB / OFF / LIVE modes) |
| Android HHT app, plant edge service, reminder mails, live EBS/GCS adapters | next drops |

## Quick start (dev, SQLite)
```
pip install -r requirements.txt
python run.py            # http://localhost:8001  (admin / Admin@123 — change at first login)
```
Swagger: http://localhost:8001/docs

## Production (Windows Server + IIS + SQL Server)
1. Install Python 3.11 (64-bit), ODBC Driver 18 for SQL Server, IIS with **HttpPlatformHandler**.
2. `sql/create_db.sql` on SQL Server (creates PalletDB with snapshot isolation).
3. Copy this folder to `C:\inetpub\pallet_server`, `pip install -r requirements.txt`.
4. Edit `web.config`: python path, `PALLET_DB_URL`, `PALLET_JWT_SECRET`.
5. IIS: new site → physical path = this folder → binding :443 with certificate.
   For 4 workers create 4 sites/app pools (ports are assigned by IIS) behind an ARR server farm, or run one site first (handles 50 users easily).
6. Task Scheduler: `scheduler.ps1` every 5 minutes (EBS/GCS retry queue).
7. Expose **only** `/api/ext/v1/*` to the internet (DMZ reverse proxy rule); everything else LAN only.

## Environment variables
| Var | Default | Meaning |
|---|---|---|
| PALLET_DB_URL | sqlite:///pallet.db | SQLAlchemy URL (see config.py for SQL Server forms) |
| PALLET_JWT_SECRET | change-me | token signing secret |
| PALLET_INTEGRATION_MODE | STUB | STUB (fake success) · OFF (simulate outage, queues) · LIVE |
| PALLET_EBS_SO_URL / PALLET_EBS_CHALLAN_URL / PALLET_EBS_AUTH | – | EBS endpoints (LIVE) |
| PALLET_ADMIN_USER / PALLET_ADMIN_PASS | admin / Admin@123 | bootstrap admin (first run only) |

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
