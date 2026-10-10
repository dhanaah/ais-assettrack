AIS AssetTrack Server  (Developed by DT)
=======================================
1. Copy the AssetTrack_Server folder to E:\AssetTrack\ (or any folder you can write to). No admin rights needed.
2. Double-click AssetTrack_Server.exe. The AIS icon appears in the system tray and the browser opens
   http://localhost:8001  (first login: admin / Admin@123, then change the password).
3. HHTs connect to the address shown under tray icon > "About / HHT address".
4. Data: pallet.db and assettrack_server.log stay in this folder. On first start, an existing
   ..\server\pallet.db (from the earlier START_ASSETTRACK setup) is copied in, so your data carries over.
5. Stop: tray icon > Stop server (needs the central admin password).
Options (optional files next to the EXE):
   port.txt      -> a different port, e.g. 8002
   settings.env  -> KEY=VALUE lines, e.g. PALLET_INTEGRATION_MODE=LIVE, PALLET_EBS_SO_URL=..., PALLET_HHT_ONLY=1
Auto-start with Windows: put a shortcut to AssetTrack_Server.exe in  shell:startup  (Win+R, type shell:startup).

GCS AUTO PRINT (plant printer)
------------------------------
Masters > Plants: set "GCS auto print" and the printer.
 - Windows printer: the printer's name exactly as in Windows (shared printers like \\PRINTSRV\FGWH-LASER work too).
   Most reliable: put the portable SumatraPDF.exe (free, no install) into a "tools" folder next to AssetTrack_Server.exe.
   Without it, Windows uses the PDF app registered on the server PC.
 - Printer IP, direct: the printer's IP (port 9100); most network laser printers print the PDF directly.
Every finished loading prints the GCS PDF (QR + challan number + security sign). The PDFs are kept in gcs_docs\.
