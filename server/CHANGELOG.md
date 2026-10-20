# Changelog — AIS AssetTrack Server
## Server 1.35.0 - 2026-10-20 (HHT unchanged 2.23.0) - Bench link with almost no input (requested by DT)
- *Read the Bench from* = **Automatic** (new default): the Bench tables when AssetTrack runs on SQL Server, otherwise the Bench web server. The page shows which way it uses now.
- **Plants from the Bench:** the Bench plant list (`ais_plants`, default plant) gives the plant of `AIS_DPB_MASTER`; `AIS_DPB_<PLANT>` gives the others. No default plant to choose.
- **No login to type:** `server/sql/bench_reader.sql` now gives AssetTrack's own login (IIS app pool) read rights in every Bench database, and it is safe to run again for a new plant. Fixed: its CREATE USER line could not run on SQL Server.
- Bench link page: only **Auto pull ON** + **Read the Bench from**; everything else is under *Advanced settings - normally not needed* (closed), each with a hint.
- CI runs `bench_reader.sql` on SQL Server 2022: reads every AIS_DPB_* database, cannot write, cannot open other databases, re-run harmless.

## Server 1.34.0 - 2026-10-20 (HHT unchanged 2.23.0) - read the Bench tables directly (decided by DT)
- The SQL way now reads the Dispatch Planning Bench's own tables directly, read only - `picklist_dispatch`, `pick_log`, `pdi_inspections`, `part_master` - in every plant database (`AIS_DPB_*`). The `vw_AT_*` views are no longer needed.
- Whole rows are read, so a column the Bench has not added yet (customer, section, SO number, inspector) is simply empty - never an error.
- Plant from the database: `AIS_DPB_MASTER` = the *Default AIS plant*, `AIS_DPB_ASP` = ASP (plant map still applies).
- Card PDI = the last decision in `pdi_inspections` (none = Pending); a card re-picked away keeps its last decision and reason; the customer part no is turned into the AIS code through the Bench part master.
- New `server/sql/bench_reader.sql`: read-only login `ais_assettrack_reader` with db_datareader in every Bench plant database (finds them by itself). Test SQL read shows each database with its plant.
- Bench link page: the three view fields are replaced by one *Schema* field (dbo); hints updated. IIS guide section 7 updated. Same trip numbers as before - nothing is created twice.

## Server 1.33.0 - 2026-10-19 (HHT unchanged 2.23.0) - SQL read uses the Bench's own views (Bench 10.2.0)
- The SQL way now reads the three views the Dispatch Planning Bench 10.2.0 creates itself in every plant database - `vw_AT_PickList`, `vw_AT_PickedPallets`, `vw_AT_PDIResults` - with the Bench's read-only login `ais_assettrack_reader` (Bench script `deploy_iis/assettrack_readonly.sql`). The two-view draft contract of 1.32.0 is withdrawn.
- **All plants at once:** *Bench SQL databases* = `AIS_DPB_*` reads every plant database the login can open (`AIS_DPB_MASTER`, `AIS_DPB_ASP` ...), or give a list. Test SQL read shows one line per plant database.
- **Same trip number as the API way** (`DB-<plant>-<picklist_id>`), so switching API → SQL never doubles a trip.
- **PDI status from the Bench:** Accepted loads; **Pending** (not inspected yet) is new - stays on the trip, stopped at loading ("PDI not done yet") and blocks challan / QR while invoiced, like Hold; Rejected is final. A card the Bench re-picked away (after Reject or Hold) leaves the trip with its last decision and reason from `vw_AT_PDIResults`; a scan of it gives STOP with that reason. PDI sign of the trip = inspector from the views.
- Bench link page: fields and helper hints for the three views, the plant databases and the read-only login. IIS guide section 7 rewritten for IT.

## Server 1.32.1 - 2026-10-19 (HHT unchanged 2.23.0) - helper hints on the web pages (requested by DT)
- Form fields can now carry a short helper line under the field and an ⓘ tip on the label, kept small and grey so the page stays clean. First used on the Dispatch Bench link page (every setting says what it is for and when to leave it blank) and on the PDI match buttons (Refresh match, Request link, Unlink).
- Forms with helper lines are top-aligned, so fields line up; the Bench page intro is shorter. Contents otherwise as 1.32.0.

## Server 1.32.0 - 2026-10-19 (HHT unchanged 2.23.0) - read the Dispatch Planning Bench from SQL Server (requested by DT)
- **Second way to read the Bench:** when the Bench runs on SQL Server, AssetTrack reads it directly, **read only**, from two fixed views the Bench publishes (`assettrack_trips`, `assettrack_trip_cards`). Column contract and the read-rights script: `server/sql/bench_views_contract.sql`. The Bench can change its own tables freely; only the two views stay fixed.
- Same SQL Server as AssetTrack, separate database: only the Bench database name is needed (same login). Another server / SQL login can be given too.
- **The Bench API stays** (portable / SQLite Bench) and is the automatic **fallback**: if the SQL read fails, that pull uses the API and the page shows why.
- **Card PDI result OK / HOLD / REJECT:** OK goes on the vehicle; **HOLD** (rework) stays on the trip, is reserved, but is **stopped at loading** and blocks challan / QR if it is invoiced - once the Bench reworks it to OK it loads normally; a HOLD card not in the GCS stays back and does not block. **REJECT** is final: kept on record with its reason, never reserved, a scan gives STOP with the reject reason.
- Web: Dispatch Bench link page - *Read the Bench from* (API / SQL), SQL database / server / login, view names, **Test SQL read**; last pull shows which way was used. PDI match panel shows HOLD and the reject / hold reason.
- Same check suites run the SQL read against real views on SQLite and on SQL Server 2022 (CI).

## Server 1.31.0 / HHT 2.23.0 - 2026-10-19 - strict Bench PDI check sheet ↔ GCS (FTP) matching (requested by DT)
- **Match by part cards only.** A GCS is linked to a Dispatch Planning Bench trip automatically only when EVERY part card in the GCS is on exactly one open Bench trip's PDI check sheet. The old "same vehicle" automatic link is removed.
- **PDI result = OK or Reject.** Cards on the Bench trip are PDI passed. When the Bench rejects a card and adds an alternate, AssetTrack sees the new card list on the next Bench pull and keeps the removed card on record.
- **Removed card / pallet scanned at loading = STOP + alert** (counted as a miss, PDI_CHECK, blocked).
- **PDI done, not invoiced** (Bench card not in the GCS), a card in the GCS that is not PDI OK, or item / qty different: shown in red, and **no challan push to Oracle and no QR gate pass** until fixed (no override). A re-issued GCS or a Bench change is matched again automatically.
- **One GCS can carry several invoices**; one Bench trip has one GCS.
- **GCS with no matching Bench trip = HARD STOP** for loading.
- **Vehicle-only link** (GCS without part cards): a supervisor raises a link request (trip + reason) in GCS inbox → 🔎 PDI match; an admin with "GCS link approve" (PADMIN / CADMIN) approves it - not the same person. Item totals are then still compared with the invoice lines. Admins can unlink while nothing is loaded.
- Web: GCS inbox → **🔎 PDI match** per sheet (card table, counts, block reason, link requests); link requests list with Approve / Reject.
- HHT 2.23.0: Vehicle loading shows "⛔ PDI / GCS check not clean" on the list and a red card on the loading screen.

## Server 1.30.3 - 2026-10-18 (HHT unchanged 2.22.0) - complete release in one step
- The build now publishes each GitHub release once, with all its files (Package, Portable, EXE), and only after every check has passed (SQLite, SQL Server, IIS, EXE, portable, APK). Releases 1.30.1 and 1.30.2 were left incomplete by the old step-by-step publishing - use 1.30.3. Contents as 1.30.2.

## Server 1.30.2 - 2026-10-18 (HHT unchanged 2.22.0) - EXE inside the package (requested by DT)
- `AIS_AssetTrack_Package.zip` now also carries the EXE build in `EXE\AssetTrack_Server` (way C, optional - for PCs where IT has whitelisted it). `README_FIRST.txt` explains the three ways; way A (portable, no EXE) stays the recommended one on AIS PCs.

## Server 1.30.1 - 2026-10-18 (HHT unchanged 2.22.0) - one complete package (requested by DT)
- New download **`AIS_AssetTrack_Package.zip`** on every server release: the portable server (way A, tray + SQLite), the IIS + SQL Server installer (way B, `iis` folder), the HHT app (`HHT\AIS_AssetTrack_HHT.apk`), the guides and the master-data template (`docs`), `README_FIRST.txt` (which way to choose, step by step) and `VERSION.txt`.
- Unzipping the package over an existing installation keeps its data and settings (database, `secret.key`, `settings.env`, IIS `web.config` are never in it).
- The separate Portable zip, EXE zip and APK downloads stay as before.

## Server 1.30.0 - 2026-10-18 (HHT unchanged 2.22.0) - IIS + SQL Server as a second way to host (requested by DT)
The tray / portable server with SQLite is **unchanged** and stays supported. The same portable zip can now also be installed on IIS with SQL Server:
- **`iis\Setup_IIS.ps1`** (IT, as Administrator, in a folder of its own such as `C:\AssetTrack_IIS`): checks IIS (adds it if missing) and the IIS module (HttpPlatformHandler or the ASP.NET Core Module), the ODBC driver, creates the SQL Server database and login (`-CreateDatabase`), writes `server\web.config`, makes the app pool (always running, never idle-stopped) and the site, sets folder rights and the firewall rule, starts it and checks the health. Running it again after unzipping a new version = update; `web.config` with the settings is kept (not in the zip any more).
- **`iis\Migrate_SQLite_to_SQLServer.ps1`**: copies all data of the tray server into SQL Server (row counts compared), with `secret.key`, so printed QRs and HHT sign-ins stay valid. A SQL database that already holds data is never overwritten; the SQLite file is only read.
- On IIS the 5-minute job (EBS / GCS retries, reminders) runs inside the server (`PALLET_RETRY_JOB=1`) - no Task Scheduler entry needed; `PALLET_SERVER_PORTS` sets the ports in the HHT setup QR.
- SQL Server fixes found by running every check on SQL Server 2022: text columns hold any character (NVARCHAR), an over-long text is cut to its column instead of failing the save, and four queries that SQL Server refuses were rewritten (yard zone view, GCS lookup, plant list of the GCS inbox, WMS-missing filter).
- Uploads sent without a size (IIS can forward them so) are limited to 30 MB like the others.
- Proven in the build: all checks on SQL Server 2022; the portable zip installed on IIS + SQL Server Express with both IIS modules, then signed in, password changed, plant added, site restarted (data kept), update run, migration refusal.
- Guide for IT: `docs/DEPLOY_IIS_SQLSERVER.md` and `iis\README_IIS.txt` in the zip.

## Server 1.29.1 - 2026-10-18 (HHT unchanged 2.22.0) - remaining review points
- Web sign-in no longer tells whether a user name belongs to customer staff before the password is right.
- Dashboard chart tips show customer / plant names as plain text (names from GCS files can never run as page code).
- Uploads must state their size (a body without it could bypass the 30 MB limit).

## Server 1.29.0 + HHT 2.22.0 - 2026-10-18 - approval review (security, logic, clean-up, version control)
Full review before management / IT approval: security, vulnerabilities, logic, unwanted code, documentation and version control.

**Security**
- The server never falls back to the old public secret: if `secret.key` cannot be written it stops with a clear message, and a `PALLET_JWT_SECRET` shorter than 32 characters is refused.
- Every sign-in token must carry the password version (tokens without it are refused).
- Print / Excel link tickets (2 minutes) only open a link: they cannot change anything, make new tickets or act as a sign-in.
- The FTP password of a plant is never sent to the web / HHT (shown as "••••" only); old audit entries that held it are cleaned on the first start.
- Nobody can give access they do not have: a user admin cannot make itself central admin or reset a stronger admin's password; only the central admin changes roles.
- New and reset passwords: at least 8 characters with letters and digits. Web users with a first / reset password must change it before anything else works.
- First admin sign-in with the documented first password works only on the server PC itself (http://localhost:8001).
- Supervisor PIN: at least 6 digits, simple PINs (111111, 123456) refused, PIN changes limited to 5 in 10 minutes, and the reply no longer tells whether another supervisor uses that PIN. Existing PINs keep working.
- Excel downloads: text starting with "=" (e.g. a customer DC number) stays text and is never run as a formula.
- Browser protections on every page (content security policy, no framing by other sites, no sniffing, no referrer). Swagger API pages are off unless `PALLET_API_DOCS=1`.
- A blocked HHT is refused by its own device id, whatever the events carry.
- Another plant's pallet can be looked up, but its history (users, remarks) is not shown.
- Libraries pinned to exact tested versions; PyJWT 2.15.0 and pypdf 6.21.1 fix known vulnerabilities (pip-audit clean).

**Logic**
- OUT gate: any manual override now needs a supervisor PIN, also when the challan is right but Security has not loaded every pallet.
- IN gate / close of another plant's challan with "/" in its number (e.g. PUN/00009) works from the HHT.
- Pallets returned to Production (rejection / damage / lot-out) with part cards still on them cannot be made "empty" and dispatched; pallets carrying PDI-rejected glass stay LOADED and off vehicles until the glass is taken off (Yard).
- A customer return slip never changes a pallet AIS shows inside the plant (Yard or on a vehicle being loaded) - warning only; the AIS Yard / Gate scan corrects it.
- HHT: Dispatch Bench trips and GCS loads have no pallet-count limit (as on the server).
- A late offline Yard scan no longer takes a pallet off a vehicle Security has already loaded (recorded as exception).
- Every way of receiving another plant's material (pallet card, pallet QR, internal move) needs the IN gate endorsement of its challan.
- A GCS cancelled in the ERP after loading started is held: loading, finish and OUT gate are refused until the admin removes it.
- When the GCS names pallets only by reference (e.g. RW.3101), only those pallets are accepted at loading.
- Pallets on a return slip that never reached AIS (3+ days) still count as held by the customer (holding report and reminders).
- Yard scan keeps DAMAGED / UNDER_REPAIR pallets so (release after repair); Yard scans on a closed slip or closed challan are refused.
- FGWH -> Production needs MOVE_FG_TO_PRODUCTION on every path; a pallet at a customer / in return / on a load cannot be set AVAILABLE by hand.
- Customer receipt only for vehicles already gated out; customer holding uses the same overdue days as the reminders.
- Challan closed short with a PIN records each missing pallet in the missed-scan register.
- Cancelling a GCS does not turn its part cards (known only from the GCS file) into free stock; a trip cancelled in the Dispatch Bench is cancelled in AssetTrack when nothing is loaded; approve keeps the real GCS number of a GCS / Bench load; a dry reminder run no longer delays the first real email.

**Clean-up and documents**
- Unused code removed (server imports / functions, HHT screens that could not be opened, old print and check functions); "Developed by DT" in every source file; code check (ruff) added to the build.
- Portable zip no longer carries build logs, Python caches or developer files; the local packaging script never packs the database, keys or settings.
- Test data anonymised; duplicate and superseded documents removed or moved to `docs/archive`.
- README, build & deploy guide, customer HHT access (VPN only - nothing on the internet) rewritten; new `docs/VERSION_CONTROL.md` (version numbers, tags, branches, release checklist); `LICENSE` (AIS proprietary).

## Server 1.28.4 + HHT 2.21.5 - 2026-10-17 - customer staff sign-in (reported by DT)
- **Customer HHT showed staff as signed in, but AIS kept answering "sign-in required".** This happened when the saved sign-in stopped being valid: the AssetTrack server was reinstalled or replaced (new secret key), the HHT reached the other AIS server, the 30 days ran out, or AIS reset the staff password. The HHT never noticed and stayed on its home screen.
  - The server now says clearly when a sign-in is no longer valid (expired, password changed, made by another server, user disabled or moved to another customer).
  - The customer HHT then signs the staff out by itself and opens the sign-in screen with "Please sign in again" and the reason. Waiting slips and receipts stay queued and are sent after signing in.
  - A password reset by AIS now ends that staff user's older sign-ins on customer HHTs (as it already did on AIS HHTs and the web).

## Server 1.28.3 + HHT 2.21.4 - 2026-10-17 - loading finishes by itself, challan preview
- **Loading finishes by itself:** when the last pallet the GCS names is scanned at Vehicle loading, the loading is finished automatically - challan made and the QR gate pass printed, no button needed. The vehicle then **leaves the pending list** on the HHT (fully loaded vehicles are no longer listed). If finishing fails (e.g. Oracle challan error), the HHT says so and "Finish loading" stays available.
- **Challan PDF on the server:** before loading is finished the challan PDF now opens as a **preview without the QR** ("NO QR - loading not finished - NOT VALID AT THE OUT GATE") instead of "No challan yet"; after finishing it has the QR. Buttons on Pick Lists and GCS inbox: "Challan (no QR)" until then.
- **Expected pallets counted right:** a GCS naming a pallet whose label was never scanned yet (e.g. RW.3101) now counts it, so the loading can't finish early. A pallet registered (e.g. at the Yard) after its GCS file arrived is now accepted at loading instead of "not in GCS".
- **HHT:** pallet numbers on the Vehicle loading screen are shown larger.

## Server 1.28.2 - 2026-10-17 (HHT unchanged 2.21.3) - GCS queue control
- **Remove a queued GCS:** on the GCS inbox page, an OPEN loading sheet now has a **Remove** button (admin / FGWH / integration admin). Pallets already scanned onto it are released, the sheet becomes CANCELLED, and it leaves the HHT loading list. It is recorded in the audit log, and comes back only if its file is dropped again.
- **GCS PDF only after loading:** the QR-coded gate pass PDF is produced only once **Finish loading** is done. Before that, opening the PDF gives a **preview without the gate QR**, marked "NO GATE QR - loading not finished - NOT VALID AT THE OUT GATE", so the admin can still see the GCS but the OUT gate cannot accept it. The web buttons say "PDF (no QR)" until loading is finished.

## Server 1.28.1 - 2026-10-17 (HHT unchanged 2.21.3) - new pallet label at Vehicle loading (reported by DT)
- A brand-new pallet label whose **first-ever scan happens at Vehicle loading** was refused as "Unknown pallet QR". Like the Yard, loading now registers the pallet from its QR (the owner plant must be in the Plant master) and links it to the open GCS lines that name it by type + serial (e.g. RW.3100 → AIS-CHN-RW-3100-…), so the loaded count and the GCS check work. A QR whose owner plant is not in the master is still refused.

## Server 1.28.0 - 2026-10-17 (HHT unchanged 2.21.3) - GCS plant name, FTP settings fixes
- **Plant name in GCS file (column AC):** new field in the Plant master (form and Excel template). The GCS file writes the plant as a name (e.g. "Chennai"), which was nowhere in the master. Each GCS row is now matched to its plant by this field (then by plant code, then by the exact plant name), whatever folder it arrived in; an unknown name keeps the folder's plant. "To plant" on stock transfers is matched the same way.
- **GCS inbox - FTP folder per plant (reported by DT):**
  - Plants whose Active mark was empty after an upgrade from an old version disappeared from this page (and its dropdown) while still showing on the Plants page. They are listed again.
  - When no plant exists yet, the page now says "No plant found - add the plant first" instead of showing an empty dropdown.
  - Neon / dark theme: the opened dropdown lists could show light text on a light panel (choices invisible). Dropdown lists are now always dark text on white, in every theme.

## Server 1.27.4 - 2026-10-17 (HHT unchanged 2.21.3) - antivirus-friendly portable
- The portable zip no longer contains any self-made EXE: the small unsigned helper EXEs that pip puts in (never used by the server) are removed at build time, and the build fails if anything but the signed python.exe / pythonw.exe remains. On AIS PCs use the **Portable** zip; the EXE zip is unsigned and strict antivirus may remove it - ask IT to whitelist it, or use Portable.

## HHT 2.21.3 - 2026-10-16 (server unchanged 1.27.3)
- Customer HHT: a device whose only waiting items are slips **refused by AIS 5+ times** can now be unpaired with an extra "Remove anyway" confirmation. The refused slips are kept stored on the device for checking and the message says plainly that AIS never received them. Slips and receipts still waiting normally must be sent first, as before.

## Server 1.27.3 + HHT 2.21.2 - 2026-10-16 - full runtime & logic check
A full review of the whole application for errors that could happen while running. Two independent reviews (server; HHT + web) found 21 issues; all fixed and re-verified. No process or screen changes.

**Server - a scan can never jam an HHT again:**
- Scanning the same unknown tag (or a foreign pallet) twice on one return slip crashed the server and left that HHT's offline queue stuck forever. Fixed, and any unexpected error in one scan is now stored as a refusal with a clear message - the rest of the batch always goes through.
- Mixed clock formats in one offline batch, or a bad heartbeat value, no longer fail the whole push.
- A smudged or foreign QR at the gates (GCS / slip QR with a bad number) now gives the normal HOLD message instead of a server error.
- A corrupt Excel file on Masters or WMS upload is refused with "Not a valid .xlsx file" instead of a server error; a blank Active cell on an update row keeps the stored value instead of failing the row.
- A missing slip-photo file gives "Photo file missing", not a server error; one bad GCS file from the FTP inbox no longer leaves a half-written loading sheet; two server workers starting at the same moment no longer collide on first-start seeding; customer API: a remark sent together with client_ref is kept.

**HHT (2.21.2) - offline work is never lost:**
- A return slip made offline is no longer dropped after one failed send (e.g. right after a password change): it stays queued, is retried up to 5 times and then shown FAILED in Pending & Sync - never silently lost.
- The app can no longer get stuck on the starting screen (start-up errors are caught; a corrupt saved setting falls back to its default).
- "Create slip & print" ignores a double tap (no duplicate slips).
- Customer HHT: a refused slip or receipt stops auto-retrying after 5 refusals and keeps its error visible; a sign-in problem pauses sending instead of counting as a failure; unpairing is no longer blocked forever.
- A pallet scanned by its printed QR while a sync is running is no longer overwritten by the older server state.
- Vehicle loading: Finish also shows against an older server; confirm dialogs work in the web preview.

**Web:** after logout the next user starts on the Dashboard (never on the previous user's page, and pages a user may not open fall back to the Dashboard); a server restart shows "Try again" instead of a blank stuck page; the self-reload after a server update waits until a half-filled form is finished.

## Server 1.27.2 - 2026-10-14 (HHT unchanged 2.21.1)
- **First login:** the "Set a new password" screen opens by itself right after the first admin login (current password, new password twice); nothing else opens before it is saved. Then the Dashboard shows "Start here: add your first plant".
- **Built-in Ctrl+F5:** the web page is never kept by the browser, and an open page reloads itself when the server is updated to a new version.
- **Plants - add / Excel upload rechecked:**
  - The Excel template now has Tag From / Tag To, WMS Stale After, EBS Org Id, GCS Copies and Challan Copies (as in the form).
  - Uploading the template with only the grey SAMPLE rows now says clearly "nothing saved - type your own codes", instead of looking like nothing happened.
  - Wrong values are reported on their row and not saved: Challan Source (APP / ORACLE), GCS Print Mode (OFF / WINDOWS / RAW9100), Challan Copies (1-3).
  - Editing a plant on the web no longer clears fields that came from Excel (address, sub-inventories, notes). The form now also has Address.

## Server 1.27.1 - 2026-10-14 (HHT unchanged 2.21.1)
- **Add plant** (approved sample): **+ Add plant** button on Masters › Plants opens the plant form with the cursor in Code and the usual defaults filled in; Edit opens the same form filled in; Save adds the plant and closes the form. While no plant exists the form is open and a message says to add the first plant.
- New server: the Dashboard shows **"Start here: add your first plant"** with a + Add plant button (or, before the admin password is changed, a Change password button). It disappears once a plant exists.
- Fixed: empty "Add / edit plant" box at the top of the Masters page.

## HHT 2.21.1 - 2026-10-14 (server unchanged 1.27.0)
- **Dispatch preparation is back** in FGWH · Central FG, for app pick lists without a GCS (permission DOCK_SCAN). GCS loads from the Dispatch Planning Bench still need no preparation.
- New group **Packing Section**: Other-plant material received at Packing by **part card only** (pallet QR refused), on a challan endorsed at Gate-In (permission PACK_RECEIPT).

## Server 1.27.0 + HHT 2.21.0 - 2026-10-14 - FGWH is the centre for all FG, collapsible groups, loading without preparation
**HHT home (approved sample):**
- Groups are **collapsible**: tap a heading to show its buttons, tap again to hide. All start closed; each HHT remembers what was left open. A closed heading still shows "N waiting" and how many buttons it holds.
- **Transitions:** a group opens and closes smoothly with a turning arrow, its buttons rise in one after another, a button squeezes slightly when pressed, and every screen slides in when opened (also on the customer HHT).
- **FGWH · Central FG** (pallet card): Production → FGWH · Other-plant material · FGWH → Packing · **FGWH → Production** (new - reason Rejection / Damage / Lot-out required).
- **PDI Check:** one button for Main Dispatch and Packing Dispatch (PDI_CHECK or PACK_PDI).
- **Dispatch preparation removed** (Main and Packing), and **FGWH → Main Dispatch removed** - the Dispatch Planning Bench handles it.

**Rules (server and HHT):**
- FGWH is the centre: Production → FGWH → Main Dispatch / Packing. **No direct Production → Main Dispatch / Packing, and no Main Dispatch ↔ Packing.**
- FGWH → Production only with a reason (Rejection / Damage / Lot-out), recorded on the move; the pallet stays LOADED and **cannot be dispatched until it is moved back to FGWH**.
- **Vehicle loading without preparation:** Security scans the GCS (opened from the GCS inbox if new), then each pallet QR. The pallet is checked against the GCS file (pallet of another GCS = wrong vehicle, refused) and allocated with its part cards. **Finish loading** makes the challan and prints the gate pass; if fewer pallets than the GCS lists are loaded, Security is asked to confirm. The OUT gate still takes the challan only.
- Loading is checked against the GCS file: a pallet the GCS does not name, or a pallet carrying a part card the GCS does not list (not PDI passed for this vehicle), is **refused - keep it off**. Security loads GCS vehicles only; app pick lists (no GCS) still need FGWH and PDI. Pick lists already prepared before this version can still be loaded.

**User access (server):** new MOVE_TO_DISPATCH, MOVE_FG_TO_PRODUCTION. VEHICLE_LOAD can now open a GCS and finish its loading. At the first start, FGWH users (all internal moves or dispatch preparation) get the new FGWH moves once; Production users do not. New Production role: Production → FGWH only.

## Server 1.26.0 + HHT 2.20.0 - 2026-10-14 - functions grouped by area, process rules, one permission per button
**HHT home (approved samples):** functions are grouped as buttons (gradient fill, picture in the corner), in the order a pallet moves:
- **Security · Gate-In:** IN Gate (slip A QR, other-plant challan - material or empty) · Return Slip (Option B).
- **Yard-In** (empty only, pallet QR): Customer returns · **Empty pallets from other plants** (new) · Empty pallets back to Yard (from Production / FGWH / Packing) · Damage / Tag issue.
- **Yard-Out** (pallet QR): Empty pallets to Production · **Empty pallets to Packing** (new) · Empty pallets to other plants.
- **FGWH · Main Dispatch** (pallet card): Other-plant material · Production → FGWH · Dispatch preparation · PDI Check.
- **Packing · Dispatch** (pallet card, new section): Other-plant material · Production → Packing · Dispatch preparation · PDI Check.
- **Security · Loading & Gate-Out:** **Vehicle loading** (new - each pallet QR into the vehicle, loaded X of Y) · OUT Gate (challan QR only).
- **Others:** Lookup · Missed Scans · Pending & Sync. Customer HHT: Inward · Return to AIS · Others.

**Rules (server and HHT):**
- Yard receives only slips / challans **endorsed at the IN gate**; Yard scans the **pallet QR only** (a pallet card is refused).
- FGWH / Packing moves, other-plant material receipt and dispatch preparation use the **pallet card only**; the pallet is found from the card.
- Other-plant material is received only on a challan endorsed at the IN gate, and closed from the receipt screen. The Yard refuses material challans.
- **No movement between FGWH (Main Dispatch) and Packing** - both ship parts to customers.
- **Security vehicle loading:** only pallets prepared on that GCS are accepted. **OUT gate takes the challan only** and holds the vehicle until every prepared pallet is loaded (supervisor PIN override as before). Loads created before this version are not held.

**User access (server):** one permission per HHT button, set per role or user on the web (Users, grouped like the HHT): new YARD_IN_PLANT, YARD_TO_PACKING, PACK_RECEIPT, PACK_DISPATCH, PACK_PDI, VEHICLE_LOAD. At the first start, users of an old permission get the matching new one once (Vehicle loading only to OUT-gate Security - the person who prepares a load does not verify it). Admin changes afterwards are kept.

## Docs - 2026-10-13 (server 1.25.0, HHT 2.19.0 unchanged)
- New `docs/DEPLOY_IIS_SQLSERVER.md`: step-by-step production install on IIS + SQL Server and how to update from E:\AssetTrack.
- `docs/DEPLOY_SERVER_IT.md`: customer HHTs over the restricted FortiClient VPN account (nothing published to the internet); database name PalletDB as in the SQL script.
- `server/web.config`: placeholder secret removed - the server makes its own random secret.key.

## Server 1.25.0 - 2026-10-13 (HHT unchanged 2.19.0)
- Web application: **Neon** theme (approved sample). Button **◐ Neon** in the top bar switches (◐ Glass switches back); each browser remembers its choice. Near-black glass cards with violet edge and glow, purple header, selected menu with glowing left bar, glowing buttons and inputs. Chart and status colours unchanged.

## HHT 2.19.0 - 2026-10-13 (server unchanged 1.24.0)
- New theme **Neon (dark)** in Settings › Theme (approved sample): near-black glass cards with a faint violet edge and soft violet glow, purple header, glowing violet buttons and selected options. Status colours (OK / warning / error) unchanged. Layout unchanged.

## Server 1.24.0 + HHT 2.18.0 - 2026-10-13 - remaining review items closed
- **Print / Excel links no longer carry the sign-in token.** The web asks for a 2-minute ticket when you open a print or download; an old link is useless after 2 minutes. Sign-in tokens in links are refused.
- **Password change ends older sign-ins** (other browsers / HHTs with the old password must sign in again). Unknown user names take the same time as wrong passwords.
- **IN gate (HHT): "Slip QR will not scan (supervisor)"** - pick the open Option A slip, enter the supervisor PIN, let it in (audit log). Same style as the OUT gate manual override.
- **HHT sync:** a scan made while a sync is running is no longer overwritten by the server's older copy of that pallet (the pallet is pulled again on the next sync).
- **Retry job:** scheduler.ps1 sends the key from server\job.key; a call passed on by IIS / a proxy without the key is refused. The server logs an error if secret.key cannot be written.

## Server 1.23.0 + HHT 2.17.0 - 2026-10-13 - full review: security and logic fixes
Full check of the whole application (security, server logic, HHT app) by separate reviewers. All 226 process checks pass plus 30 new checks (server/tests/audit_fixes_check.py, also run by the build).

**Pallet records (logic)**
- A pallet on an open pick list that is scanned at the Yard is now properly taken off that list - it can no longer go out on two challans. OUT gate holds a vehicle if a pallet is no longer on its load, and only one gate can dispatch a load.
- Cancelling a pick list frees only its own pallets.
- Offline (RO) slip sent after the slip was closed at the yard: the closed slip is not changed; extra pallets are only reported.
- Same pallet twice on an offline slip no longer stops the customer HHT from sending.
- Gate-opened offline slip + later HHT details: short pallet references are matched to the full number (no double lines).
- A customer slip can no longer move another plant's pallet, or a pallet on another customer's load.
- Option B: a pallet already in the plant scanned at the yard is ALREADY_IN and is not counted.
- Document numbers (gate entry, slip, challan...) can no longer repeat when two requests come at the same moment.
- Option B slip sent twice by the gate HHT: the same slip is returned (no error).
- Other-plant stock-transfer challans close when the pallets are received at FGWH / Packing.
- One bad scan no longer blocks a whole sync batch; scans older than the kept history are refused (HHT with a reset clock still OK).
- Supervisor PIN asked once per close (one wrong PIN = one try).

**Security**
- Print pages (slip, challan, GCS) show customer-typed text as text - it can never run as script.
- Built-in admin must change the first password before anything else works (Users page still opens).
- Old public QR secret accepted only for slips / GCS made before 11-Oct-2026; QR vehicle must match the slip.
- Option A slips at the IN gate need the slip QR (or a supervisor PIN - server side ready).
- Customer staff cannot sign in to the AIS system (customer HHT only).
- Too many wrong supervisor PINs at a plant -> PIN use paused 10 minutes.
- Retry job only from the server PC; EBS transfer retry needs Integration permission; damage mark only for own plant's pallets.
- Customer API no longer shows other customers' codes. Uploads above 30 MB refused. GCS PDF file name includes the plant.

**HHT 2.17.0**
- Login token no longer kept in the plain app database; phone backup of app data is off.
- Scans are ignored while AssetTrack is in the background (a scan in another app no longer acts here).
- Scans made while the HHT is busy wait in line - none are dropped.
- Customer HHT: slip / receipt queue can no longer lose a slip; unpairing is refused while slips wait; internet address must be https.
- Offline sign-in (customer staff, plant idle-lock): salted password check kept securely, expires with the sign-in, 5 wrong tries -> 5 min wait. Staff signed in on the old app still sign in offline (moved to the new check).
- Plant switch: sign-in is saved only after the unsynced-scans check passes.
- A scan the server keeps refusing is marked FAILED after 5 tries and undone on the HHT (no longer blocks the queue).
- VPN card refreshes after FortiClient connects; small fixes in pairing QR checks and dock / move rules.

## HHT 2.16.0 - 2026-10-13 (server unchanged 1.22.0)
- Customer HHT: VPN to AIS through FortiClient VPN (installed on the HHT, AIS SSL-VPN account from AIS IT). Approved sample.
  - No connection to AIS: red card "Not connected to AIS" with **Connect VPN** (opens FortiClient; Play Store page if not installed) and **Recheck**.
  - VPN on but server not answering: amber card - ask AIS IT to allow the VPN account to reach AssetTrack.
  - Online: green pill shows "via VPN"; on returning to AssetTrack it rechecks by itself and sends waiting slips / receipts.
  - Same card on the customer staff sign-in screen. Offline signed slips still work as before.

## HHT 2.15.0 - 2026-10-12 (server unchanged 1.22.0)
- Home: the signed-in user is a compact strip under the logo - initials badge, name on one line, "plant · N roles" (tap for the full role list) and a small Logout button. No more wrapped role list beside the logo.

## HHT 2.14.0 - 2026-10-12 (server unchanged 1.22.0)
- **No keyboard on scan fields at all.** The scan field is no longer a text box: nothing can be typed and no keyboard (on-screen or Zebra Enterprise Keyboard) opens.
  - Scanner mode: the device scanner (trigger button) sends the barcode straight to the app through its native broadcast - new built-in scanner module.
  - Zebra: the app creates its own DataWedge profile "AIS AssetTrack" automatically at start (barcode on, broadcast output on, keystroke output OFF). No manual DataWedge setup.
  - Urovo, Newland, iData, Chainway default broadcasts understood; another brand: Setup › 4. Scanner (action + data key, set by IT).
  - Camera mode: the camera reads the code.
- Setup › 4. Scanner: scanner status, test read, "Set up Zebra scanner again".

## HHT 2.13.0 - 2026-10-12 (server unchanged 1.22.0)
- **Scan fields: scanner only, no manual keying** (every place a scan is required):
  - A scan is accepted even when the scanner sends no Enter at the end (Zebra DataWedge default) - the code is taken as soon as the characters stop.
  - Codes typed by hand (key by key, also with Enter) are refused: "Typing is not allowed - scan the code", with error beep. The keyboard button on scan fields is removed; the soft keyboard never opens on a scan field.
  - Camera mode reads the code with the camera; it no longer offers typing.
  - Scanners that do send Enter keep working as before.

## 1.22.0 (HHT 2.12.0) - 2026-10-11
Found while running every process end to end for the process presentation:
- **Vehicle loading (HHT)**: a part card that is not on the GCS now shows "STOP - do PDI" on the HHT itself (before, an unknown card only said "Unknown LPN / tag").
- **Vehicle loading (HHT)**: scanning a pallet now picks its part cards from the GCS on the HHT too, so "Finish loading" shows the right loaded quantity against the invoice.
- **Yard - Option B**: pallets of the customer scanned on an Option B slip are received normally (they were wrongly flagged EXCESS and needed a PIN). Count matching the gate count closes without PIN.
- **Yard - other-plant challan**: at the owner plant the challan registered at the IN gate appears in Yard In-ward; scan each pallet against the challan and close (PIN if short). Web gate register shows it CLOSED.
- **Empty pallet return challan** (Yard loading) now prints automatically on the plant's network printer, same as GCS + challan.
- **Customer document reading**: vehicle numbers (TN 22 BX 7310), DC / invoice numbers after their label and PIN codes are no longer read as pallet numbers.
- HHT: IN gate result card shows the gate entry number; customer pairing screen no longer shows server addresses; customer return scan list shows OK / CHECK; Yard close button fits small screens (PIN field only when needed).

## 1.21.0 (HHT 2.11.0) - 2026-10-11
- **Transporters - template and upload for plant users**: new permission `TRANSPORTER_MASTER`, given to Logistics and Plant Admin (also Master / Central Admin).
  - Masters › Transporters: "Template with sample", "Current data", "Upload", Edit / Delete now also for these plant users.
  - A plant user's upload / edit always keeps their own plant on the transporter and never removes other plants; delete of a shared transporter only removes their plant.
  - Masters › Import: new "Download master template (all sheets)" button.
- **Pallet yard in-ward recognises Option A / Option B** after the RTS is scanned and guides that process:
  - Option A (customer slip with pallet list): scan each pallet - ticked against the slip list - reconcile with the slip - close.
  - Option B (count at the IN gate + document photo): 1 view the customer document photo (scanning starts after it), 2 scan each pallet (matched with the document), 3 check the count - close.
  - Server: an Option B slip closes only when the yard count equals the gate count, or with the supervisor PIN.
  - A slip not yet on the HHT is fetched from the server when scanned.
- Process flow A3 updated.

## 1.20.1 (HHT 2.10.0) - 2026-10-11
- **Printers by job**:
  - Dispatch: no Bluetooth printer. GCS + challan print only on the plant's shared / network printer set in Masters › Plants › GCS printer.
  - The HHT "Print GCS slip (portable printer)" button is removed. "Print GCS + challan again (plant printer)" is always shown after loading.
  - Bluetooth printer is used only for return slips: Option A at the customer, Option B at the IN gate. Setup › Printer says so.
- Process flow A3 updated (Gate pass box: plant network printer; return slips: BT printer).

## 1.20.0 (HHT 2.9.0) - 2026-10-11
- **Option B needs photo proof**: an Option B slip cannot be made without at least one photo of the customer's document.
  - HHT: the gate cannot create or print the slip until the photo is taken (works offline too; the photo uploads when online).
  - Server: Option B without a photo is refused.
  - Pallet yard: an Option B slip cannot be closed until its photo has reached the server (supervisor PIN to override).
- Process flow A3 updated.

## 1.19.0 (HHT 2.8.0) - 2026-10-11
- **Gate inward register**: every inward is registered at the IN gate with one entry number (`<plant>-GE-000123`) and one GCS inward:
  - Option A return slip - registered when its QR is scanned at the gate.
  - Option B return slip - registered when security makes it at the gate.
  - Other AIS plant - registered when its challan is scanned (now also gets a GCS inward).
  - Repeat scans return the same entry, never a second one.
- Web: new page **Operations › Gate Inward Register** (today / 7 / 30 / 90 days) with the pallet-yard status of each entry.
- HHT: the gate entry number is shown after the gate scan and on the Option B slip screen.
- Process flow A3 updated: all three inward routes go through the gate register before pallet-yard receiving.

## 1.18.1 (2026-10-11) — "Developed by DT" only on the login screens (HHT app 2.7.1)
- Shown on the HHT login, the customer staff sign-in and the web login page only; removed from the other HHT screens, the web footer after sign-in, thermal slips, gate pass / challan PDFs, prints, Excel / PDF exports, templates, reminder e-mails, the HHT setup page and the tray About box
## 1.18.0 (2026-10-11) — one server, plant-wise: plant chosen on the HHT, Bench trips served to their own plant (HHT app 2.7.0)
- Users can work for more than one plant: central users (no plant) - any plant; plant users - own plant + "Also works for plants" (web Users, e.g. PUN;TLJ). Login returns the plants allowed
- HHT: after sign-in, a user with more than one plant selects the plant (last used marked); every call carries the plant (X-Plant) and the server checks it is allowed - pick lists, GCS, pallets, slips and scans are those of that plant only; switching plant is refused while scans of the previous plant are not synced; unlock keeps the plant
- Dispatch Bench link plant-wise: each Bench trip goes to its own AIS plant (DB-<plant>-<trip>) from the plant field of the trip (ais_plant / plant_code / from_plant / org_code / warehouse ...), translated by the new "Bench plant -> AIS plant" map (e.g. 3001=CHN;TALOJA=TLJ); the default plant is used only for trips without a plant; trips with no known plant are not taken and are counted in the link status
- GCS inbox was already per plant (FTP folder per plant)
## 1.17.0 (2026-10-11) — Customer Staff role: receive deliveries and return empty pallets on the customer HHT; server address hidden on the HHT (HHT app 2.6.0)
- New role CUST_STAFF "Customer Staff" (web Users: role + customer code; rights CUST_RECEIVE, CUST_RETURN). They sign in with their own user on the paired customer HHT (30 days; again without network if they signed in online on that HHT before); they cannot sign in on an AIS HHT
- Customer HHT > Receive delivery: AIS loads dispatched to the customer (last 20 days, kept on the HHT); scan the gate pass QR or pick the vehicle, scan each pallet while unloading - received / still to scan / extra (not on this delivery); sent to AIS (queued when offline); pallets not received are listed for AIS
- Customer HHT > Return empty pallets (Option A): now done by the signed-in staff (recorded as the slip maker); customer API calls from an HHT need the staff sign-in (system API keys unchanged)
- HHT: the server address / IP is no longer shown anywhere - only Online (green) / Offline (red); server can still be typed once under Setup > "Enter manually"; app version and device ID shown very faint
- Web: Tag batches card explained (pallet tag rolls: first / last tag number, tags count, in stock / on pallets / retired)
## 1.16.0 (2026-10-11) — Dispatch Bench trip and its GCS joined into one record
- When a GCS file arrives, AssetTrack finds the Dispatch Bench trip of the same vehicle by the part cards they share (fallback: vehicle + customer, when exactly one open trip of the last 3 days fits) and joins them
- Trip not loaded yet: loading is done on the GCS sheet; the trip is closed as LINKED, its reserved part cards and the PDI / supervisor names move to the GCS sheet
- Trip already loaded: the trip carries on and takes the GCS number, invoice lines and part-card list (gate pass prints from it); the GCS sheet is LINKED and is not loaded a second time; scanning / opening that GCS number goes to the trip; OUT gate never picks a LINKED record
- Web Pick Lists: link shown as 🔗 with the other number
## 1.15.2 (2026-10-11) — return slip number always automatic; customer DC optional (HHT app 2.5.3)
- Return slip number is generated automatically everywhere (RTS-... by AIS, RO-<plant>-<device>-<seq> when printed without network); the screens say so
- Customer DC number: optional - the customer may or may not have one (customer HHT, customer API and IN-gate Option B)
## 1.15.1 (2026-10-11) — customer DC number mandatory on Option A slips (HHT app 2.5.1)
- Customer HHT / customer API: the customer's delivery challan (DC) number is required again (also for slips printed without network)
- HHT 2.5.2: "Test printer" on the login screen (before sign-in) - prints the test page on the selected Bluetooth printer, or opens Setup › 2. Printer when none is chosen
## 1.15.0 (2026-10-11) — HHT could not reach the server (fixed); login first, Setup; server QR; offline customer slips; online badge (HHT app 2.5.0)
- FIX: the HHT app was not allowed to use http:// (Android blocks it unless the app says so) - the browser on the HHT could open the server but the app could not. Now allowed; the build checks it
- Login screen: user ID + password only, with a line showing the server and whether it answers (green online / red offline, every 15 s); Setup button
- Setup (from login and Settings): 1. Server - Scan server QR or type name / IP, Save & test; 2. Printer; 3. Vehicles (list kept on the HHT, AIS vehicles come from the server)
- Server QR: http://<server>:8001/hht-setup (no login), tray menu "HHT setup QR", link on the web login. The HHT tries every address in it at once and keeps the ones that answer, fastest first; server addresses now leave out 169.254.x and put the full PC name and main IP first
- Online / Offline / Syncing badge on every screen (online = the AssetTrack server answers, not just Wi-Fi); auto-sync keeps retrying when the server was not reachable
- Vehicle pick list on the return slips (customer HHT and IN gate): recent AIS loads and slips + transporter vehicles from the server, plus vehicles added on the HHT; recently used first; works offline
- Customer HHT without network: pick the vehicle, scan pallets, print the slip at once with a QR signed by this HHT (number RO-<plant>-<device>-<seq>); the AIS IN gate accepts it and opens the slip from the QR (pallets from the type + serial list in it); when the HHT is online it sends the slip with the same number and the details are merged.
- Pairing QR and /me give the HHT its offline signing key (older pairings get it on the next connection)
## 1.14.3 (2026-10-11) — AT icon for the HHT app and the browser tab (HHT app 2.4.3)
- HHT app icon (Android launcher, round and square) and the web browser tab / phone home-screen icon are now the AssetTrack "AT" icon; the AIS company logo stays on the login, headers and prints
- brand/build_logos.py builds them from brand/at_icon_source.png
## 1.14.2 (2026-10-11) — new AssetTrack "AT" icon for the server
- Tray icon near the clock and the server program (AssetTrack_Server.exe) use the new blue AT icon with the location pin; messages now say "look for the blue AT icon"
## 1.14.1 (2026-10-11) — customer document written by pallet type only, or total only (HHT app 2.4.2)
- Pallet type with quantity read from the document: "F - 4", "NF : 2 NOS", "RW x 3", "4 Nos F pallets", and type names from the pallet type master ("Flat pallet 6", "Non flat 2"); shown per type against what AIS shows at the customer (warning when the document has more)
- Total only: "Total 9", "No of pallets - 5", "6 pallets", "14 Nos", "Qty 7" - offered as the count; warning when the count entered differs
- Slip keeps type quantities and the customer total; yard receiving shows received / document per type and against the customer total; web slip detail the same
## 1.14.0 (2026-10-11) — Option B: photo of the customer's manual document, read and matched; yard sees it (HHT app 2.4.0)
- IN gate (Option B): security photographs the customer's DC / challan / pallet list (any layout, several pages). The HHT reads the text itself (Google ML Kit, offline) and the server finds the pallet numbers and matches them with the pallets the ledger shows at that customer
- Matching for any customer format: full QR number, type + serial (F-2948, F.2948, NF7944, RW 1392), number only (when unique at the customer); reading slips fixed (O/0, I/1, S/5, B/8, Z/2, G/6); one wrong digit -> "probable"; DC no / invoice / date / vehicle / phone ignored; the customer's written total is picked up ("Total 6 pallets") and offered as the count
- Result on the HHT: matched at the customer, probable (check at yard), AIS pallet that the ledger shows elsewhere, not recognised; warning when the count differs from the document
- Optional AI reading of the photo for handwriting / unusual layouts (server setting PALLET_AI_API_KEY; off by default - the photo then goes to the AI service); merged with the HHT text
- Photos kept on the server with the slip (up to 10 pages; queued and resent when the network is back); offline slips: text matched on the server at sync
- Yard receiving (HHT): for Option B the pallets read from the document are the expected list - received / on document not yet / not on document - and the document photos can be opened (1x-3x zoom) while unloading
- Web slip detail: document vs received comparison and the photos
- HHT 2.4.1: APK built for ARM devices only (all HHTs / phones) - smaller download; on-device text reading uses the Latin model only
## 1.13.1 (2026-10-11) — loading: part card not in the GCS is stopped ("do PDI first"); invoice qty vs loaded qty (HHT app 2.3.1)
- A part card that is not in the GCS file (not PDI passed / invoiced for this vehicle) is refused at loading - on the HHT at once (also offline) and on the server - with "STOP: do PDI first, keep it off the vehicle"; no override. A card of another GCS still shows "wrong vehicle"
- Finish loading compares quantity: invoice (GCS) qty vs qty on the part cards loaded, per item and in total; the HHT shows it before finishing and in the result
## 1.13.0 (2026-10-11) — return slip rules, other-plant returns on challan, any portable printer, scanner / camera switch (HHT app 2.3.0)
- Return slips only by: customer staff on the customer HHT (Option A, pallets scanned) and IN-gate security (Option B, number of pallets only - the pallets are scanned and the slip knocked off at pallet-yard receiving). AIS users can no longer make Option A slips; older HHTs sending B1 lists are kept as a count
- Pallets from another AIS plant: only on that plant's challan - a return slip naming a plant is refused; the IN gate scans the challan QR (or challan number), checks it is addressed to this plant and gated out at the sender, and records the inward; pallets are received at the yard
- Option A slips from the customer HHT now also correct pallets whose dispatch was never scanned (missed OUT gate recorded)
- HHT printing for any portable printer: Bluetooth (paired), Bluetooth LE (scan) or Android print; languages ESC/POS, CPCL (Zebra/Honeywell), ZPL, TSPL; paper 2" / 3" / 4"; logo/QR as raster, old ESC* or the printer's own QR; "Find my printer language" test
- Thermal slip: AssetTrack wordmark smaller under the AIS logo (logo 236 -> 175 dots high); Option B slip shows a large NO. OF PALLETS and "scanned & knocked off at pallet yard receiving"
- HHT scanning: Scanner (built-in / Bluetooth wedge) or Camera on every scan field (switch on the field or in Settings) - any Android phone can do every task
## 1.12.0 (2026-10-11) — customer HHT for Option A return slips (HHT app 2.2.0)
- Customer HHT paired by QR (web: Masters › Customers › 📱 HHT): own device key per HHT (new table customer_devices), removable one by one; list shows last seen, route (AIS network / internet) and app version
- HHT customer mode: new Option A return slip (scan pallets - each checked against the customer's AIS ledger - vehicle, customer DC, driver) -> slip with AIS-signed QR, printed on the portable printer and shown on screen; pallets held at the site (days, overdue); the customer's slips with status and reprint
- Route chosen per call: AIS network addresses first (direct to the AIS server), else the internet address of the customer API (PALLET_PUBLIC_API_URL); no network -> slip kept on the HHT and sent later, never doubled (client reference)
- Customer API: /ping (route test, no key), /me; slips from a customer HHT recorded as source CUST_HHT with the device name
- docs/CUSTOMER_HHT_ACCESS.md: recommended outside access for IT (publish only /api/ext/ through the HTTPS reverse proxy)
## 1.11.1 (2026-10-11) — fix: daily reminder run could not write its integration log entry (empty reference)
## 1.11.0 (2026-10-11) — masters from Excel, delete, auto customers / transporters, clock, auto refresh, dd-mmm-yy, FTP per plant, Excel / PDF everywhere (HHT 2.1.5)
- Customers and transporters: add / edit forms on the web; created automatically from the GCS file when new (customer code = short name in REMARKS when it is part of the name, else from the name; transporter with its vehicles and plant); marked "from GCS"
- Masters from Excel (plants, customers, transporters, pallet types, pallets): template with 2 sample rows + "How to fill" sheet, current data download, upload (adds / updates by code, row errors listed, samples skipped)
- Delete on every master row: removed when never used, otherwise set INACTIVE (pallets: DISCONTINUED; refused while out at a customer) so history stays correct
- Web header: live clock (Sun 11-Oct-26 07:36:49) and "updated hh:mm:ss"; data refreshes every 30 s while the page is untouched (paused while editing, filters set or a detail is open)
- Dates dd-mmm-yy everywhere: web, gate pass, challan, prints, Excel exports, emails, HHT (HHT times now local, not UTC)
- GCS inbox: FTP folder per plant (own server / login optional, else the shared server); each plant read automatically; status per plant; "Read now" per plant
- Every web table has "⬇ Excel" and "⬇ PDF" (A4 landscape with logo, page numbers)
## 1.10.9 (2026-10-10) — GCS pallets linked to the pallet QR (HHT app 2.1.4)
- The pallet part of LPN_NUMBER (F.2948 / NF7944) = pallet type + serial of the pallet QR: matched to AIS-<plant>-F-02948-... (own plant first); part cards linked to their pallet at import
- Scan the pallet QR -> its part cards from the GCS are picked; scan a part card -> its pallet is known (no second scan)
- Pallet listed on another open GCS refused ("wrong vehicle"); pallet not in this GCS -> warning; a mixed pallet loads only this GCS's part cards
- Finish loading also lists pallets in the GCS not loaded and pallets loaded but not in the GCS (HHT result screen + audit)
## 1.10.8 (2026-10-10) — table headings centred on the gate pass and the challan
## 1.10.7 (2026-10-10) — real ERP GCS file format (HHT app 2.1.3)
- GCS CSV as exported by the ERP: GATE_PASS_NUMBER, VEHICLE_NUM, ENTRY_TIME, CUST_ITEM_NUMBER, QUANTITY_PER_CASE, LINE_QUANTITY, GR_NUMBER, LPN_NUMBER, DRIVER_CONTACT_NO, TRANSPORT_MODE, STATUS, CANCELLED_DATE ... recognised; "-" = empty
- One row per case is merged into one gate pass line per invoice + item (cases, qty, amount added up)
- Expected part cards per GCS (new table gcs_lpns) from LPN_NUMBER; part cards pre-registered with item and qty; expected pallets = distinct pallets in LPN_NUMBER
- Loading check: full ERP label or part card number accepted; part card of another GCS refused ("wrong vehicle"); part card not in the file -> warning; Finish loading lists part cards not scanned / extra (HHT result screen + audit)
- Customer matched to the master by CUSTOMER_NAME, else REMARKS as code; customer name from the file printed when not in the master
- GCS cancelled in the ERP (CANCELLED_DATE / STATUS) cancels the loading sheet when nothing was loaded
- Pallet numbers with a 1-letter type (F) recognised (AIS-CHN-F-02948-...); long names shrink to fit on the gate pass
## 1.10.6 (2026-10-10) — returnable pallet challan PDF, Pallet Type master, official AIS logo (HHT app 2.1.2)
- Delivery challan PDF (GST Rule 55) in the gate pass style: ORIGINAL FOR CONSIGNEE / DUPLICATE FOR TRANSPORTER / TRIPLICATE FOR CONSIGNOR in one PDF (plant master "Challan copies"), consignor / consignee GSTIN, place of supply, gate pass / vehicle / vehicle type / transporter / invoices / e-way bill, goods by pallet type with HSN, qty, value per pallet, total value + in words, total pallet weight, purpose / return clause, every pallet number (full ID, 4 columns), Prepared by / Security / Received by; multi-page with page X of Y per copy
- Printed automatically with the gate pass when loading finishes; web Pick Lists "📄 Challan" opens the PDF (also for Yard empty returns: title "Return of Empty Pallets", consignee = owner plant)
- Pallet Type master (Masters > Pallet types): description, HSN, value per pallet, L x W x H (mm), weight (kg), colour, material, active; warning for pallet types in use without a master; the challan takes description / size / weight / colour / HSN / value from it. Plant master keeps only a default HSN
- Official AIS logo everywhere: web icons, header, login, favicon, A4 prints (company name no longer repeated next to the logo), HHT app icon / adaptive icon / splash / screens, thermal printer logo. brand/build_logos.py rebuilds all logo files from brand/ais_logo_source.png
## 1.10.5 (2026-10-10) — gate pass in the ERP layout, multi-page
- Gate pass PDF follows the ERP "Finished Goods Materials Gate Pass": gate pass number + page X of Y, boxed header (logo, title, plant address, Outward Non Returnable), details (GatePass Number, To M/s, Vehicle No, Transporter, Remarks, Date, Location, Time, No of Invoices, GR/LR No, Sales Type, Vehicle Type), invoice table (Sl, Inv No, Inv Date, Item Code, Cust Part No, No of Case, Qty/Case, Act Qty, Line Amount, Pallet Type) with totals and amount in words (lakh / crore)
- AssetTrack additions: OUT-gate QR in the header, pallet challan number, pallets loaded (6 columns, short number ANF-00001), PDI / Logistics / Security signs
- Multi-page: no shrinking - table and pallet list continue on the next page with repeated headings; signs on the last page
- Font size per plant (Masters > Plants > GCS font size %): 88 compact (default), 100, 80
- GCS CSV: new columns Date, Time, Location, Vehicle Type, Transporter, Remarks, GR/LR No, Sales Type, Cust Part No, No of Case, Qty/Case, Act Qty, Line Amount, Pallet Type
## 1.10.4 (2026-10-10) — several invoices per GCS (line level); short pallet numbers; GCS always one A4 sheet
- GCS CSV: one row per invoice line (GCS No, Vehicle, Customer, Invoice No, Invoice Date, SO No, Item Code, Item Description, Qty, Pallets); rows with the same GCS No make ONE loading sheet with all its invoice lines (new table picklist_items); a re-sent file refreshes the lines while the GCS is still open
- Loaded quantity per invoice line from the part cards scanned (same item on several invoices fills the lines in order); short-loaded lines shown in red
- GCS PDF / web print: invoice-lines table (invoice, date, SO, item, description, qty, loaded, pallets) with totals; web Pick Lists "🧾 Invoices"; HHT loading screen shows invoices · lines · qty (tap to expand)
- Pallet numbers on the GCS sheet shortened to pallet type + serial (AIS-CHN-ANF-00001-0000001 → ANF-00001); up to 6 columns; always a single A4 sheet
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
