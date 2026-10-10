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

GCS CSV ON THE FTP (ERP export - one row per case / LPN)
--------------------------------------------------------
Columns as exported by the ERP (file name e.g. 20261009_154526_FGCHN2627_12823.csv):
GATE_PASS_NUMBER, GATE_PASS_DATE, SALES_TYPE, CUSTOMER_NAME, LOCATION, INVOICE_NO, INVOICE_DATE, VEHICLE_NUM, VEHICLE_TYPE,
TRANSPORTER_NAME, TRANSPORT_MODE, ENTRY_TIME, ITEM_CODE, CUST_ITEM_NUMBER, NO_OF_CASES, QUANTITY_PER_CASE, LINE_QUANTITY,
LINE_AMOUNT, GR_NUMBER, PALLET_TYPE, PACKAGE_TYPE, STATUS, REMARKS, APPROVAL_TIME, DRIVER_CONTACT_NO, SUBINVENTORY,
CANCELLED_REMARKS, CANCELLED_DATE, PLANT_NAME, LPN_NUMBER
- Rows of the same GATE_PASS_NUMBER make ONE loading sheet; rows of the same invoice + item are added up into one gate pass
  line (cases, quantity, amount).
- LPN_NUMBER (e.g. F.2948.P10266528972) = pallet F.2948 (pallet type F + serial 2948 = pallet QR AIS-CHN-F-02948-...)
  + part card P10266528972. Scanning the pallet QR picks its part cards; a pallet of another GCS is refused. the HHT knows every part card of the GCS,
  refuses a part card that belongs to another GCS ("wrong vehicle"), warns on one not in the file, and "Finish loading"
  shows part cards not scanned. Expected pallets = number of different pallets in LPN_NUMBER.
- Customer: matched to the customer master by CUSTOMER_NAME (add the customer with exactly that name), else REMARKS as code.
- CANCELLED_DATE / STATUS "CANCELLED": the loading sheet is cancelled (if nothing was loaded yet).
- "-" in a cell is treated as empty.
