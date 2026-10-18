AIS AssetTrack on IIS + SQL Server  (Developed by DT)
=====================================================
The same AssetTrack server as the tray / portable one, hosted by IIS with its data in SQL Server.
The tray / portable server is NOT changed: it keeps running from its own folder (e.g. E:\AssetTrack) with SQLite.

Needs on the IIS server (IT, once):
  - IIS (the script adds it if missing) and Microsoft HttpPlatformHandler
    (httpPlatformHandler_amd64.msi from https://www.iis.net/downloads/microsoft/httpplatformhandler - put it in this folder,
     the script installs it) - or the ASP.NET Core Module if IT already has it
  - Microsoft ODBC Driver 18 for SQL Server
  - a SQL Server (any edition, 2016 or newer) reachable from the IIS server
No Python install: the python folder of this zip is used.

1. Unzip AIS_AssetTrack_Server_Portable.zip into a folder of its own, e.g. C:\AssetTrack_IIS
2. PowerShell as Administrator, in that folder:
     powershell -ExecutionPolicy Bypass -File iis\Setup_IIS.ps1 -SqlServer SQLSRV01\PALLET -CreateDatabase
   Options:
     -SqlUser pallet_app -SqlPassword "..."   SQL login instead of the Windows login of the IIS app pool
     -CreateDatabase                         make the database + login with your Windows login (needs SQL admin);
                                             without it the DBA runs server\sql\create_db.sql first
     -Port 8080 / -HostName assettrack        if port 80 is taken; DNS name of the site
     -StopDefaultSite                        stop IIS's "Default Web Site" so AssetTrack can use port 80
     -PublicName assettrack                  name the HHTs use (put in the HHT setup QR)
     -IntegrationMode LIVE                   when the EBS / GCS links are ready (default STUB)
3. Data from the tray server (once): stop the tray server, then
     powershell -ExecutionPolicy Bypass -File iis\Migrate_SQLite_to_SQLServer.ps1 -SQLiteFile E:\AssetTrack\server\pallet.db
   (copies every row + secret.key, so printed QRs and sign-ins stay valid; the SQLite file is only read)
4. Open http://localhost on the IIS server, sign in, then http://<server>/hht-setup and scan the QR on each HHT.

Update to a new version: unzip the new zip over C:\AssetTrack_IIS, run Setup_IIS.ps1 again (no options needed -
server\web.config with your settings is not in the zip and is kept).
Backups: SQL Server backup of PalletDB + server\secret.key + server\web.config.
Details: docs\DEPLOY_IIS_SQLSERVER.md
