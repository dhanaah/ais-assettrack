AIS AssetTrack - complete package  (Developed by DT)
====================================================
One download with everything: the server (two ways to run it), the HHT app and the guides.
Version: see VERSION.txt

What is inside
  START_ASSETTRACK.bat, Restart_AssetTrack_Server.bat   way A - tray server (portable)
  python\  server\                                       the server itself (Python included - nothing to install)
  iis\                                                   way B - IIS + SQL Server installer
  HHT\AIS_AssetTrack_HHT.apk                             Android app for the HHTs
  docs\                                                  guides for users and IT, master-data Excel template

Choose ONE way to run the server
--------------------------------
A) Tray server on a Windows PC, data in SQLite  (no admin rights, no install)
   1. Unzip into e.g. E:\AssetTrack (unzipping over an older version keeps your data).
   2. Double-click START_ASSETTRACK.bat - the AT icon appears near the clock, the web page opens.
   3. First sign-in on this PC: admin / Admin@123, then set a new password.
   Update: unzip the new package over the same folder, then Restart_AssetTrack_Server.bat.
   Guide: docs\PORTABLE_SERVER.txt

B) IIS + SQL Server on a Windows server  (IT, administrator)
   1. Unzip into a folder of its own, e.g. C:\AssetTrack_IIS (not the folder of way A).
   2. PowerShell as Administrator in that folder:
        powershell -ExecutionPolicy Bypass -File iis\Setup_IIS.ps1 -SqlServer SQLSRV01\PALLET -CreateDatabase
   3. Data of a tray server (once): iis\Migrate_SQLite_to_SQLServer.ps1 -SQLiteFile E:\AssetTrack\server\pallet.db
   Update: unzip the new package over C:\AssetTrack_IIS, run Setup_IIS.ps1 again (no options).
   Guide: docs\DEPLOY_IIS_SQLSERVER.md and iis\README_IIS.txt

Use one server for daily work and point every HHT at it.

HHT app
-------
   1. Copy HHT\AIS_AssetTrack_HHT.apk to the HHT (or download it from the server web page) and install it.
   2. On the server: tray icon > HHT setup QR (way A), or http://<server>/hht-setup (way B).
   3. On the HHT: Setup > 1. Server > Scan server QR, then sign in.
   Customer HHTs: pair from the web page Masters > Customers > HHT (docs\CUSTOMER_HHT_ACCESS.md).

Keep safe: server\secret.key (signs every QR and sign-in) with the database backup.
AssetTrack stays inside the AIS network - nothing is published to the internet.
