# Changelog — AIS AssetTrack Server
## 1.10.3 (2026-10-10) — three signs on the GCS: PDI (Bench login), Logistics (shift supervisor, Bench login), Security (HHT login)
## 1.10.2 (2026-10-10) — PDI and Shift Supervisor signs on the GCS
- GCS sheet / PDF / print carry the PDI person and the Shift Supervisor logged in on the Planning Bench ("Name (login)"), taken from the GCS CSV (columns PDI By / PDI Login, Shift Supervisor / Supervisor Login - several spellings accepted) or from the Bench dispatch record; five sign boxes: PDI, Shift Supervisor, Security/Logistics (loading, pre-filled with the HHT login), Driver, OUT gate
## 1.10.1 (2026-10-10) — GCS PDF auto print
- GCS PDF (reportlab) built when loading finishes: signed QR, challan number, consignee / invoice / SO / e-way bill, loaded pallets with part cards, SECURITY SIGN box with the login ID and name of the person who completed loading; kept in gcs_docs\
- Automatic print on the plant printer (Masters > Plants: Windows printer name - shared or network - or printer IP port 9100, copies); print result in the integration log; "Print again" on web and HHT; PDF download from Pick Lists / GCS inbox
- FTP inbox documented as CSV (one row per GCS); JSON / TXT / PDF still accepted
## 1.10.0 (2026-10-10) — GCS-driven vehicle loading
- GCS inbox: gate passes created after invoicing (Bench / GCS system) are read from an FTP folder (JSON / CSV / TXT / PDF) and open a loading sheet per GCS (pick list GCS-<plant>-<no>: vehicle, customer, invoice, SO, part, e-way bill); manual file upload and manual open from the HHT when the file is late; Masters > GCS inbox page
- HHT 2.1.0 "Vehicle Loading": scan / type the GCS, then scan pallet tags or part cards (LPN) as they go on the vehicle; "Finish loading" makes the challan (plant / customer challan source) and the signed GCS QR; GCS slip on the portable printer; A4 GCS print with QR on the web
- OUT gate: scans the GCS QR (signature, GCS and vehicle verified) or a GCS / challan number -> dispatched, pallets AT_CUSTOMER, part cards DISPATCHED; forged QR refused
- Challan + GCS QR for empty pallet loads unchanged (finish loading at the Yard -> EBS challan + e-way bill)
## 1.9.1 (2026-10-10) — pick lists only from the Dispatch Planning Bench
- PALLET_PICKLIST_SOURCE=BENCH (default): AssetTrack no longer releases dispatch pick lists; they are planned in the Bench and pulled every 30 s (configurable, min 10 s) and additionally whenever an HHT syncs. AssetTrack creates only Empty Pallet Returns (HHT, Yard)
- Web: Pick Lists page shows the Bench status and "Pull from Bench now" instead of the release form; PDI Status, WMS Stock and Blanket pages hidden (set PALLET_PICKLIST_SOURCE=APP to get the old behaviour back)
- HHT 2.0.1: PDI tile hidden in Bench mode, sync every 30 s, dock wording "Bench trip"
## 1.9.0 (2026-10-10) — HHT 2.0.0 professional release + in-app updates
- Server announces the newest APK placed in server\apk\ (/api/v1/app/latest, /apk/<file>); web header shows "HHT app vX" download; get_apk.bat copies the APK there
- HHT 2.0.0: audio + haptic feedback engine (OK / warning / error tones generated in-app), scanner field with ready indicator and last read, camera torch, home screen with live counts (open pick lists, PDI waiting, open slips, to-sync, scans today) and quick lookup, update banner, idle auto-lock with password unlock, crash guard with copyable details, large-text / glove mode, "Test connection" on login, logout warns about unsynced scans, consistent segmented controls / switches / empty states / busy buttons / pull-to-refresh across all screens
## 1.8.1 (2026-10-10) — AIS pallet QR label
- The pallet label QR (JSON: uniquePalletID AIS-<plant>-<type>-<serial>-<global>, ownerPlant, palletType, mfgDate) is understood at every scan point, on the server and on the HHT (1.9.1)
- First scan of a new label at the Pallet Yard registers the pallet from the QR (own plant -> AVAILABLE, other plant -> HELD here); unknown owner plant -> quarantined with the reason
## 1.8.0 (2026-10-10) — management dashboard, customer reminders, hardening, SQL Server kit
- Dashboard: KPI tiles + charts (pallet position by plant, customer holding by age, dispatched vs returned per week, turnaround days, missed scans per week, by role), plant / window filters, table view per chart; GET /api/v1/dashboard
- Excel export of every report: /api/v1/reports/export/<name>.xlsx (pallets, customer-holding, overdue, plant-position, missed-scans, picklists, return-slips, lpn-stock, movements)
- Daily Exception Report (A4 print) per plant: missed scans, rejected HHT scans, slips with issues, overdue pallets, stuck pick lists, WMS age
- Customer reminders: daily email to customers holding pallets past the limit (customer master: email, limit, every N days, escalation days); escalation copies plant admins / logistics; Monitor > Customer Reminders page with preview, send now, log; dry run until SMTP is set in settings.env
- HHT minimum version (PALLET_MIN_CLIENT): older apps get "update the app" at login / sync; Sync Monitor shows OFFLINE / UPDATE badges per device
- Supervisor PIN must be unique within the plant (no ambiguity about who approved)
- pytest suite (tests/test_suite.py) gates the EXE and APK builds in CI; server log rotates at 5 MB
- Deployment kit for IT: docs/DEPLOY_SERVER_IT.md, settings.env.example, sql/migrate_sqlite_to_mssql.py
- HHT 1.9.0: Bluetooth printing rebuilt for portable ESC/POS printers (SEZNIK DEV 2" set up): ESC/POS bytes built in the app, logo + QR as raster, paper 58/80 mm, Settings > Printer with pair list and Test print
## 1.7.1 (2026-10-10) — review fixes: secret, sync hardening, backup
- Server secret (login tokens, return-slip QR check codes) is now random per installation (secret.key next to the database) instead of the built-in default that is public on GitHub; old labels still verify
- Sync: heartbeats no longer stored as events (was one row per HHT per minute); the same event arriving twice at once is answered from the first result instead of a server error; applied events older than 2 years purged by the retry job; SQLite waits up to 30 s when busy
- Delta pull sends LPNs that became DISPATCHED / REJECTED / MISSING so the HHT cache corrects itself; HHT drops them
- HHT 1.8.1: a dock scan the server rejects is removed from the local list again (count was wrong); shows the server's pallet count when another HHT scans the same list
- Tray server: daily database backup (backups/, 14 days kept) + "Backup database now" in the tray menu
## 1.7.0 (2026-10-10) — Dispatch Planning Bench (all customers), empty pallet return at the Yard
- HMIL Planning Bench renamed Dispatch Planning Bench: now for every customer; customer taken from the Bench dispatch (customer_code / customer / plant), optional code map
- Bench pick lists DB-<plant>-<dispatch> (older HB-... kept, matched by dispatch id - no duplicates); source DISPATCH_BENCH (old HMIL_BENCH converted at start); old /integrations/hmil-bench address still works
- Empty pallet return loaded at the Pallet Yard (HHT 1.8.0 tile "Empty Pallet Return"): pick owner plant + vehicle, scan only that plant's empty pallets, open quantity; "Finish loading" makes the EBS challan + e-way bill at once
- Yard loading: own-plant or loaded pallets refused; pallet not yet moved to Yard -> missed move recorded and corrected
## 1.6.1 (2026-10-10) — multiple ports, name address
- Tray server listens on several ports at once (port.txt, default 80,8001,8002,8003); a busy / blocked port is skipped and logged
- HHT and web use a NAME (PUBLIC_NAME in settings.env, e.g. assettrack, or the PC name) instead of an IP; port 80 means no port in the address
- Single instance: a second start (EXE, tray app or old console server already running) is refused with a message and opens the running one
- Tray Stop password box no longer freezes (own process); Restart_AssetTrack_Server.bat
- /health lists the live ports; HHT 1.7.1 tries the name on every port and switches automatically when one is slow (no double posting of non-repeatable calls)
## 1.6.0 (2026-10-10) — HMIL Planning Bench link
- Pulls HMIL Planning Bench dispatches + picked LPNs every minute (no change in hmil_server); creates pick list HB-<plant>-<dispatch>
- Bench owns reservation, PDI and sub-inventory; AssetTrack binds pallets to the Bench LPNs on the HHT, then challan, gate, return
- Settings page Masters > HMIL Bench link (URL, Workbench login, plant, customer map, interval, Pull now)
- Web: roles as tick chips, KPI cards on one row
## 1.5.0 (2026-10-09) — HHT-only operations, central access control, plant position, customer QR label
- All physical transactions (scans, moves, PDI, gate in/out, return slips, confirm, damage) accepted only from the HHT app (PALLET_HHT_ONLY=1); web keeps masters, uploads, release, challan, approve, reports, live view
- Users created / changed only by the central admin; per-user access rights (movement routes MOVE_TO_PRODUCTION/FGWH/PACKING/YARD and every scan) override role defaults
- Plant-wise users and pallet lists (plant, own-only, loaded/empty, zone filters)
- Plant Position report: own pallets at home by zone, at other plants, in transit, at customers (aging/overdue), damaged; other plants' pallets held here
- Live Transactions page (auto refresh 10 s)
- Customer API: signed QR return-slip label (AIS1|RS|... with server check code), printable 100x75 mm label link; IN gate rejects altered labels and vehicle mismatch
- Transparent AIS logo / reversed header logo
## 1.4.0 (2026-10-09) — FG parts, PDI, WMS, internal movement, missed scans
- Dispatch types: Direct customer / Stock transfer (EBS invoice fetched, printed on challan), Empty return to origin plant (EBS challan + e-way bill, no SO), Pallets only
- Blanket order master (PO number, schedule qty, validity) controls every part release; open qty = schedule - released - pending
- Sale order pushed to EBS only after PDI passes and all sub-inventory transfers are confirmed
- PDI per LPN: OK -> customer/part sub-inventory (rules master), Reject -> reject sub-inventory; rejects re-open the pick list for replacement
- EBS sub-inventory transfer with double confirmation: (1) EBS accepted + txn id, (2) on-hand read-back verified; retried until confirmed
- WMS stock: Excel/CSV upload or EBS pull; release blocked when stock older than plant limit; in-process LPNs protected; reserved LPNs flagged if missing
- LPN reservation (FIFO) with control report, supervisor release, swap on scan
- Dock scan: LPN fetches its pallet, pallet fetches all its LPNs (multiple LPN per pallet), or scan both to link
- Loaded / Empty state on every pallet, set at each scan point
- In-plant zones and internal movement: Yard -> Production -> FGWH / Packing, FGWH -> Packing, Packing -> Yard; Yard = empty only
- Other-plant material received at FGWH / Packing (IN_WIP) -> emptied -> Yard -> empty return
- Missed-scan detection: next scan point infers the skipped scan, alerts, auto-corrects when safe or blocks, records with responsible role; register + resolve
- New roles PROD, PACK; new permissions WMS_UPLOAD, BLANKET_MASTER, EMPTY_RETURN, INTERNAL_MOVE, PLANT_RECEIPT (added to existing roles automatically)
- Automatic database upgrade: new columns added on start, existing data untouched
## 1.3.0 (2026-10-09)
- Activity logger: middleware records every action (WEB/HHT/EXT/SYSTEM) with user, plant, device, IP, result, duration; secrets scrubbed
- Activity page (Monitor menu): filters, summary by action/user/device, Excel export; HHT device-activity intake (/activity/device)
## 1.2.0 (2026-10-08)
- Print-ready A4 challan and return slip with AIS logo, AssetTrack wordmark and QR (/print/challan/{no}, /print/slip/{no}); print buttons in web UI
## 1.1.0 (2026-10-08)
- Product renamed AIS AssetTrack; AIS / AssetTrack logo, favicon and blue-red brand theme
- Repository initialised (monorepo: server + hht), Git tags
## 1.0.2 (2026-10-08)
- Navigation grouped into Dashboard / Operations / Masters / Monitor dropdowns
## 1.0.1 (2026-10-08)
- Admin UI restyled: glassmorphism theme (gradient backdrop, frosted cards, pill nav, colour-coded status chips, dark-mode aware)
- Short-return keeps original dispatch date (aging preserved)
## 1.0.0 (2026-10-08) — Phase 1 drop
- Masters, roles/permission matrix, plant-scoped users, Excel import
- Pallet state machine, tag lifecycle, histories, audit log
- HHT sync (idempotent events, reference pull, monitor, device block)
- Pick list → SO → dock scan → controls → challan switch → logistics → GCS out → gate out
- Return slip A/B1/B2 → gate in → yard scan (other-plant checkbox) → reconcile → PIN close
- External customer API (X-API-Key) for Mode A push from outside the network
- Reports + Excel export; integration STUB/OFF/LIVE with retry queue
Developed by DT
