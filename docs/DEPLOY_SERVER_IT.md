# AIS AssetTrack – server deployment guide (for IT)

AssetTrack is a single Windows program (`AssetTrack_Server.exe`, no installer, no admin rights) that serves the web
application and the HHT (handheld scanner) API on HTTP. During the pilot it runs on a planning PC with a local SQLite
database. For production across plants it should run on a server with SQL Server. This page lists what IT needs to
provide. Developed by DT.

## 1. What we need from IT

| Item | Request | Why |
|---|---|---|
| Server / VM | Windows Server 2019+ (or Windows 10/11), 2 vCPU, 4 GB RAM, 20 GB disk, always on | runs the service |
| DNS name | `assettrack` (and `assettrack.aisglass.local`) → the server's IP | HHTs connect by name, never by IP |
| Firewall | inbound TCP **80, 8001, 8002, 8003** from all plant networks and the plant Wi-Fi used by HHTs | web + HHT API (several ports = fail-over) |
| SQL Server | database `PalletDB`, login `pallet_app` with `db_owner` on it (or the IIS app-pool / service Windows account) - script `server\sql\create_db.sql` | production database |
| ODBC driver | "ODBC Driver 18 for SQL Server" on the server | the program talks to SQL Server through it |
| Service account | a Windows account that stays logged in, or a scheduled task "at start-up" that runs the EXE | keeps the server running after reboot |
| Backup | nightly backup of the SQL database (SQLite: the `backups` folder next to the EXE) | recovery |
| Outbound | SMTP relay access (customer reminder emails); HTTPS to the Oracle EBS API host | emails, EBS integration |
| Optional | IIS with an AIS certificate on 443 (see `DEPLOY_IIS_SQLSERVER.md`) | HTTPS inside the AIS network |
| Customer sites | a **restricted SSL-VPN account** (FortiClient) that can reach only the AssetTrack server, port 8001 | customer HHTs reach AIS over VPN - nothing is published to the internet |

## 2. Install

1. Create `D:\AssetTrack\` and unzip the `server-exe` package into it (`AssetTrack_Server.exe` + `_internal`).
2. Copy `settings.env.example` to `settings.env` in the same folder and set `PALLET_DB_URL` (SQL Server), `PUBLIC_NAME`,
   SMTP and EBS values. Keep `PALLET_HHT_ONLY=1`.
3. Double-click `AssetTrack_Server.exe`. A blue AT icon appears near the clock; the browser opens `http://localhost:8001`.
   First login `admin / Admin@123` **on the server PC itself** (http://localhost:8001) – the server forces a new password at once. From any other PC this first password is refused.
4. The program creates all tables on first start. To move pilot data from SQLite, run from the pilot PC:
   `python server\sql\migrate_sqlite_to_mssql.py` (see that file) – or re-import the masters from the Excel template.
5. Autostart: Task Scheduler → Create Task → "Run whether user is logged on or not", trigger *At startup*, action
   `D:\AssetTrack\AssetTrack_Server.exe`, start in `D:\AssetTrack`.

## 3. Checks

* `http://assettrack/api/v1/health` returns `"db":"ok"` and the list of ports.
* From an HHT on plant Wi-Fi: Settings → server name `assettrack` → login works.
* Tray icon → *About* shows the name, the live ports and the data folder.

## 4. Operations

* **Logs:** `assettrack_server.log` next to the EXE (rotates by size).
* **Updates:** stop (tray → Stop server, admin password) → replace the EXE folder → start. Data and settings stay.
* **Backups (SQLite only):** `backups\pallet-YYYYMMDD.db`, 14 days, plus tray → *Backup database now*.
* **Second instance:** a second start is refused with a message, so a scheduled task and a manual start cannot clash.
* **Customer API** for customer IT teams: `docs/Customer_Return_Slip_API.md` (reached over the AIS VPN only).
* **IIS + SQL Server** (production option instead of the EXE): `docs/DEPLOY_IIS_SQLSERVER.md`.
