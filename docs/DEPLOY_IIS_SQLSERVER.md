# AIS AssetTrack on IIS + SQL Server (for IT)
Developed by DT · Asahi India Glass Ltd.

AssetTrack can be hosted two ways. **Both stay supported; this guide adds the second without changing the first.**

| | Tray / portable server (current) | IIS + SQL Server (this guide) |
|---|---|---|
| Runs as | tray app on a Windows PC (`START_ASSETTRACK.bat`) | IIS site on a Windows server, always running |
| Database | SQLite file `server\pallet.db` | SQL Server database `PalletDB` |
| Folder | e.g. `E:\AssetTrack` | a folder of its own, e.g. `C:\AssetTrack_IIS` |
| Same zip | `AIS_AssetTrack_Server_Portable.zip` | the same zip (it carries the `iis` folder) |
| Python | inside the zip | inside the zip (nothing installed) |
| 5-minute job (EBS / GCS retries, reminders) | inside the tray app | inside the server (`PALLET_RETRY_JOB=1`) |
| Backups | daily copy of `pallet.db` (tray) | SQL Server backup of `PalletDB` |

Everything stays inside the AIS network - nothing is published to the internet. HHTs connect to whichever server
their setup QR names; customer HHTs use the AIS FortiClient VPN as before.

## 1. What IT prepares (once)
| Item | Note |
|---|---|
| Windows Server 2016 or newer with IIS | `Setup_IIS.ps1` adds the Web Server role if it is missing |
| IIS module: **HttpPlatformHandler v1.2** (`httpPlatformHandler_amd64.msi`) **or** the **ASP.NET Core Module V2** (.NET Hosting Bundle) | either one; put the HttpPlatformHandler msi in the `iis` folder and the script installs it |
| **Microsoft ODBC Driver 18 for SQL Server** (17 also works) | on the IIS server |
| SQL Server 2016 or newer (any edition, Express works for one site) | can be the same or another server |
| DNS name, e.g. `assettrack` → the IIS server | the HHTs and browsers use it |
| Firewall: port 80 (or the chosen port) from plant networks / plant Wi-Fi / the FortiClient VPN pool | `Setup_IIS.ps1` opens it on the Windows firewall |

## 2. Install
1. Unzip `AIS_AssetTrack_Server_Portable.zip` (GitHub release `server-v…`) into **`C:\AssetTrack_IIS`**.
   Do not use the folder of the tray server.
2. Open **PowerShell as Administrator** in `C:\AssetTrack_IIS` and run one of:

   Windows login of the IIS app pool, database made by the script (you need SQL admin rights):
   ```
   powershell -ExecutionPolicy Bypass -File iis\Setup_IIS.ps1 -SqlServer SQLSRV01\PALLET -CreateDatabase -HostName assettrack -PublicName assettrack
   ```
   SQL login made by the DBA with `server\sql\create_db.sql` (change its password first):
   ```
   powershell -ExecutionPolicy Bypass -File iis\Setup_IIS.ps1 -SqlServer SQLSRV01\PALLET -SqlUser pallet_app -SqlPassword "<password>" -HostName assettrack
   ```
3. The script checks or does, in order:
   IIS and the module → ODBC driver → database and login (`-CreateDatabase`) → `server\web.config` →
   app pool `AssetTrack` (no .NET, always running, never stopped when idle, one process) → site `AssetTrack` →
   folder rights for the app pool → firewall rule → start → `/api/v1/health` must answer with `"db":"ok"`.
   It ends with `READY - AIS AssetTrack <version> on IIS, database: SQL Server`, or shows the server log if something is wrong.

| Option | Meaning |
|---|---|
| `-SqlServer` | SQL Server name, with instance if any (`SQLSRV01\PALLET`, `.\SQLEXPRESS`) |
| `-Database` | default `PalletDB` |
| `-SqlUser` / `-SqlPassword` | SQL login instead of the app pool's Windows login |
| `-CreateDatabase` | create the database (read-committed snapshot on) and the login, using your Windows login |
| `-Port` / `-HostName` | default port 80, any host name; use another port if 80 is taken |
| `-StopDefaultSite` | stop IIS's "Default Web Site" so AssetTrack can use port 80 |
| `-PublicName` | name the HHT setup QR gives the HHTs (e.g. `assettrack`) |
| `-IntegrationMode` | `STUB` (default) until the EBS / GCS links are live, then `LIVE` |
| `-Reconfigure` | write `web.config` again from these options (the old one is kept as `.bak`) |
| `-UseSQLite` | test installation without SQL Server |

Windows login and a SQL Server on **another** server: the app pool signs in as the IIS server's computer account
(`AIS\IISSERVER$`); `-CreateDatabase` grants that account. A SQL login (`-SqlUser`) avoids this question.

## 3. Bring over the data of the tray server (once)
1. Stop the tray server (tray icon › **Stop server (admin)**) and leave it stopped until the copy is done, so no scan is missed.
2. On the IIS server, PowerShell as Administrator in `C:\AssetTrack_IIS`:
   ```
   powershell -ExecutionPolicy Bypass -File iis\Migrate_SQLite_to_SQLServer.ps1 -SQLiteFile "\\TRAYPC\E$\AssetTrack\server\pallet.db"
   ```
   - copies every table in order and compares the row counts;
   - copies `secret.key` and `job.key` from next to `pallet.db`, so **every printed QR (slips, GCS) and HHT sign-in stays valid**;
   - refuses a SQL database that already holds plants / pallets / pick lists (nothing is ever overwritten);
   - only reads the SQLite file: the tray server can be started again with its data if ever needed.
3. Open `http://assettrack/hht-setup` and scan the QR on each HHT (Setup › 1. Server). Customer HHTs: pair again from
   the web page Masters › Customers › 📱 HHT if their server address changed.

## 4. Check
- `http://assettrack/api/v1/health` → `"db":"ok"` and the version.
- Web `http://localhost` on the IIS server → first sign-in `admin / Admin@123` (only on the server itself) → new password at once.
- HHT: scan the setup QR, sign in, do one scan.

## 5. Update to a new version
1. Unzip the new `AIS_AssetTrack_Server_Portable.zip` over `C:\AssetTrack_IIS`.
2. Run `powershell -ExecutionPolicy Bypass -File iis\Setup_IIS.ps1` again (no options).
   `server\web.config` (your settings), `secret.key` and the database are not in the zip and are kept;
   new tables / columns are added on start; the script checks the health and the version.

## 6. Keep safe
- Nightly SQL Server backup of `PalletDB` (full) and log backups as per AIS policy.
- Back up `server\secret.key` and `server\web.config` with it. Losing `secret.key` means printed QRs no longer scan.
- Logs: `C:\AssetTrack_IIS\server\logs` (server log and `iis_stdout*`).
- HTTPS: add an HTTPS binding with the AIS internal certificate in IIS Manager (recommended - see the approval report).

## 7. Dispatch Planning Bench on the same SQL Server (read the Bench from SQL)
When the Bench runs on SQL Server, AssetTrack reads the Bench's own tables directly, **read only**:
`picklist_dispatch` (pick lists), `pick_log` (picked LPNs), `pdi_inspections` (PDI decisions), `part_master` (customer part → AIS code).
Plant databases: `AIS_DPB_MASTER` (Bench default plant, e.g. AAC) and `AIS_DPB_<PLANT>` (e.g. `AIS_DPB_ASP` = plant ASP).
1. Run `server\sql\bench_reader.sql` once in SSMS as sysadmin (and again when the Bench gets a new plant database):
   login `ais_assettrack_reader` with **db_datareader** (read only) in every `AIS_DPB_*` database. AssetTrack never writes into the Bench.
2. AssetTrack web page Masters › Dispatch Bench link: *Read the Bench from* = **SQL**; *Bench SQL databases* = `AIS_DPB_*`
   (or a list `AIS_DPB_MASTER;AIS_DPB_ASP`); *Bench SQL Server* blank (same server); *SQL login* `ais_assettrack_reader` + password;
   *Default AIS plant* = the plant of `AIS_DPB_MASTER` › Save › **Test SQL read** (one line per plant database) › **Pull now**.
3. Where a Bench plant code differs from the AssetTrack plant code, fill *Bench plant → AIS plant*.
4. Keep the Bench URL / user filled in: if the SQL read fails, that pull uses the Bench web server and the page shows the error.

Card PDI from the Bench: **Accepted** loads; **Pending** (not inspected) and **Hold** (rework) stay on the trip but are stopped at
loading until Accepted; **Rejected** is off the trip for good (a scan gives STOP with the reason). A card the Bench re-picked away
leaves the trip with its last decision and reason. The trip number stays the same as with the API way (`DB-<plant>-<pick list id>`).
After a Bench update that renames these tables or columns, run **Test SQL read** - a failed read falls back to the API and is shown on the page.

## 8. Running both
The tray server (SQLite) and the IIS server (SQL Server) are independent installations with their own data.
Point each HHT at one of them (setup QR). After the data has been brought over (step 3), use the IIS server for
day-to-day work and keep the tray server stopped, or keep it as a stand-by / training server.
