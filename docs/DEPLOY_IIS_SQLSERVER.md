# AIS AssetTrack - production on IIS + SQL Server (for IT)

Production option instead of the tray EXE / portable server. Same application, same files (folder `server`).
Everything stays inside the AIS network - nothing is published to the internet. Developed by DT

## 1. SQL Server (once)
1. Run `server\sql\create_db.sql` in SQL Server Management Studio: database **PalletDB**, snapshot isolation on,
   login `pallet_app` (change the password in the script first) - or give the IIS app-pool account `db_owner`.
2. Install **ODBC Driver 18 for SQL Server** on the IIS server.
3. Tables are created by AssetTrack on its first start. Pilot data (SQLite): `python server\sql\migrate_sqlite_to_mssql.py`.

## 2. IIS server (once)
1. Install **Python 3.12** (all users) and, from the `server` folder: `python -m pip install -r requirements.txt`.
2. Install the IIS **HttpPlatformHandler** module (Microsoft download).
3. Copy the `server` folder to `C:\inetpub\pallet_server` (or any folder).
4. Edit `server\web.config`:
   * `processPath` = your python.exe, `arguments` = full path of `run.py`, log folder.
   * `PALLET_DB_URL` = the SQL Server connection, e.g.
     `mssql+pyodbc://pallet_app:<password>@SQLSERVER\PALLET/PalletDB?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes`
     or with Windows login: `mssql+pyodbc://@SQLSERVER\PALLET/PalletDB?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes`
   * `PALLET_INTEGRATION_MODE` = `LIVE` when the EBS / GCS links are ready.
5. IIS Manager: new site, physical path = the `server` folder, binding port 80 (and 443 with the AIS certificate),
   host name `assettrack`. App pool: *No Managed Code*, one worker process. Give the app-pool account **Modify** on the folder
   (it writes `secret.key`, `job.key`, logs and GCS PDFs there).
6. DNS: `assettrack` -> the IIS server. Firewall: 80 / 443 (and 8001-8003 if the tray server is also used) from plant networks
   and plant Wi-Fi.

## 3. Scheduled jobs
Task Scheduler, every 5 minutes: `powershell -File C:\inetpub\pallet_server\scheduler.ps1`
(sends the key from `job.key`; retries EBS / GCS postings and customer reminders).

## 4. Check
* `http://assettrack/api/v1/health` -> `"db":"ok"` and the version.
* Web: `http://assettrack` -> sign in `admin / Admin@123` -> change the password at once (nothing else works before that).
* HHT: Setup › Server › `assettrack` -> sign in.

## 5. Updating to a new version
1. Copy the new `server` folder from `E:\AssetTrack\server` (always the latest version) over the IIS folder -
   **keep** `web.config` (your settings), `secret.key` and `job.key`.
2. Recycle the app pool. New tables / columns are added automatically on start.
3. Check `/api/v1/health` shows the new version.

## 6. Keep safe
* `secret.key` signs logins and every QR (slips, GCS). Losing or changing it means printed QRs no longer scan - back it up.
* Nightly SQL Server backup of PalletDB.
