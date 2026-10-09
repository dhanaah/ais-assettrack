# Changelog — AIS AssetTrack Server
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
