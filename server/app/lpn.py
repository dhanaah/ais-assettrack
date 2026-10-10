"""FG part flow: WMS stock, LPN reservation, dock scan (LPN <-> pallet), PDI, EBS sub-inventory transfer
with double confirmation, SO after PDI, loaded/empty pallet state and missed-scan detection.
Developed by DT
"""
from datetime import timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import models, services, integration
from .models import utcnow
from .services import RuleError

PART_TYPES = ("CUSTOMER", "STOCK_TRANSFER")
IN_PROCESS = ("PICKED", "PDI_OK")                 # owned by AssetTrack; WMS upload never changes these
SCAN_POINT_ROLE = {"DOCK_SCAN": "FGWH", "OUT_GATE": "SEC_OUT", "RETURN_SLIP": "SEC_IN", "YARD_IN": "YARD", "PDI": "QA",
                   "MOVE_YARD_PRODUCTION": "YARD", "MOVE_PRODUCTION_FGWH": "FGWH", "MOVE_PRODUCTION_PACKING": "FGWH",
                   "MOVE_FGWH_PACKING": "FGWH", "MOVE_PACKING_YARD": "YARD"}

# ---------------------------------------------------------------- in-plant zones
ZONES = ("YARD", "PRODUCTION", "FGWH", "PACKING")
MOVES = {("YARD", "PRODUCTION"), ("PRODUCTION", "FGWH"), ("PRODUCTION", "PACKING"), ("FGWH", "PACKING"), ("PACKING", "YARD")}
MOVE_LOAD = {"PRODUCTION": "EMPTY", "FGWH": "LOADED", "PACKING": "LOADED", "YARD": "EMPTY"}   # default load after arriving
DISPATCH_ZONES = ("FGWH", "PACKING")
RECEIPT_ZONES = ("FGWH", "PACKING")        # other-plant material is received here (never at the empty-only Yard)


def receive_from_plant(db: Session, pal: models.Pallet, zone: str, plant: str, *, user_id=None, device_id=None, event_id=None,
                       ref: str | None = None) -> tuple[str, list[str]]:
    """Loaded pallet from another AIS plant (stock transfer) -> FGWH / Packing. Pallet goes IN_WIP (material being used);
    once emptied it moves Packing -> Yard (HELD) and leaves on an Empty Return challan to its home plant."""
    zone = zone.upper()
    if zone not in RECEIPT_ZONES:
        raise RuleError("Other-plant material is received at FGWH or Packing only")
    if pal.home_plant == plant:
        raise RuleError(f"{pal.pallet_no} is our own pallet - use Yard in-ward / internal move")
    alerts = []
    if pal.status in ("HELD", "IN_WIP") and pal.location_plant == plant:
        return f"{pal.pallet_no} already received ({pal.zone})", alerts
    if pal.status not in ("AT_CUSTOMER", "IN_TRANSIT"):
        alerts.append(record_miss(db, pallet=pal, plant=plant, detected_at=f"RECEIPT_{zone}", missed_point="OUT_GATE",
                                  expected="dispatched by home plant", action="ALERT", user_id=user_id, device_id=device_id, current_ref=ref,
                                  message=f"{pal.pallet_no} received from {pal.home_plant} but its dispatch was not scanned there (was {pal.status})"))
    elif pal.customer_code not in (plant, None):
        alerts.append(record_miss(db, pallet=pal, plant=plant, detected_at=f"RECEIPT_{zone}", missed_point="WRONG_DESTINATION",
                                  expected=f"dispatched to {plant}", action="ALERT", user_id=user_id, device_id=device_id, current_ref=ref,
                                  message=f"{pal.pallet_no} was dispatched to {pal.customer_code} but arrived at {plant}"))
    src = pal.challan_ref
    services.move(db, pal, "IN_WIP", event_type=f"PLANT_RECEIPT_{zone}", user_id=user_id, device_id=device_id, event_id=event_id,
                  plant=plant, ref=ref or src, remarks=f"from {pal.home_plant}", force=True)
    pal.customer_code = None
    set_zone(pal, zone)
    set_load(db, pal, "LOADED", f"from {pal.home_plant} {src or ''}".strip())
    return f"{pal.pallet_no} received at {zone} from {pal.home_plant} (LOADED, in WIP)", alerts


def _route(frm: str, to: str) -> list[tuple[str, str]] | None:
    """Shortest chain of allowed moves frm -> to (BFS)."""
    if frm == to:
        return []
    seen, q = {frm}, [(frm, [])]
    while q:
        cur, path = q.pop(0)
        for a, b in MOVES:
            if a == cur and b not in seen:
                np = path + [(a, b)]
                if b == to:
                    return np
                seen.add(b); q.append((b, np))
    return None


def set_zone(pal: models.Pallet, zone: str | None):
    pal.zone = zone
    pal.zone_at = utcnow()


def zone_check(db: Session, pal: models.Pallet, expected: tuple, plant: str, detected_at: str, *, user_id=None, device_id=None, ref=None) -> list[str]:
    """Scan point expects the pallet in one of `expected` zones. Record each skipped internal move."""
    cur = pal.zone or "YARD"
    if cur in expected:
        return []
    best = None
    for z in expected:
        r = _route(cur, z)
        if r is not None and (best is None or len(r) < len(best)):
            best = r
    alerts = []
    for a, b in (best or [(cur, expected[0])]):
        alerts.append(record_miss(db, pallet=pal, plant=plant, detected_at=detected_at, missed_point=f"MOVE_{a}_{b}",
                                  expected=f"zone {'/'.join(expected)}", action="AUTO_CORRECTED", user_id=user_id, device_id=device_id,
                                  current_ref=ref, message=f"{pal.pallet_no} shown in {cur}; move {a} -> {b} was not scanned"))
    set_zone(pal, (best[-1][1] if best else expected[0]))
    return alerts


def internal_move(db: Session, pal: models.Pallet, to_zone: str, plant: str, *, load: str | None = None,
                  user_id=None, device_id=None, event_id=None, remarks=None) -> tuple[str, list[str]]:
    to_zone = to_zone.upper()
    if to_zone not in ZONES:
        raise RuleError(f"Zone must be one of {', '.join(ZONES)}")
    alerts: list[str] = []
    st = pal.status
    if st in ("DISCONTINUED", "DAMAGED", "UNDER_REPAIR"):
        raise RuleError(f"{pal.pallet_no} is {st}")
    if st == "ALLOCATED":
        raise RuleError(f"{pal.pallet_no} is on pick list {pal.picklist_no} - remove it at dock first")
    # arriving from outside the plant
    if pal.location_plant != plant or st in ("AT_CUSTOMER", "IN_RETURN", "IN_TRANSIT"):
        foreign = pal.home_plant != plant
        if foreign and st in ("AT_CUSTOMER", "IN_TRANSIT") and (pal.customer_code in (plant, None)):
            if to_zone not in RECEIPT_ZONES:
                raise RuleError(f"{pal.pallet_no} is other-plant material ({pal.home_plant}) - receive it at FGWH or Packing")
            msg, al = receive_from_plant(db, pal, to_zone, plant, user_id=user_id, device_id=device_id, event_id=event_id)
            return msg, al
        missed = "RETURN_SLIP" if st == "AT_CUSTOMER" else "YARD_IN"
        alerts.append(record_miss(db, pallet=pal, plant=plant, detected_at=f"MOVE_{to_zone}", missed_point=missed, expected=f"at {plant}",
                                  action="AUTO_CORRECTED", user_id=user_id, device_id=device_id,
                                  message=f"{pal.pallet_no} was {st} at {pal.location_plant or pal.customer_code or '-'}; inward not scanned"))
        services.move(db, pal, "HELD" if foreign else "AVAILABLE", event_type="AUTO_RECEIVE_MISSED_SCAN", user_id=user_id,
                      device_id=device_id, plant=plant, remarks=alerts[-1], force=True)
        set_load(db, pal, "EMPTY"); set_zone(pal, "YARD")
    frm = pal.zone or "YARD"
    if frm == to_zone:
        return f"{pal.pallet_no} already in {to_zone}", alerts
    if (frm, to_zone) not in MOVES:
        r = _route(frm, to_zone)
        if r:
            for a, b in r[:-1]:
                alerts.append(record_miss(db, pallet=pal, plant=plant, detected_at=f"MOVE_{to_zone}", missed_point=f"MOVE_{a}_{b}",
                                          expected=f"zone {r[-1][0]}", action="AUTO_CORRECTED", user_id=user_id, device_id=device_id,
                                          message=f"{pal.pallet_no} shown in {frm}; move {a} -> {b} was not scanned"))
            frm = r[-1][0]
    live = db.query(models.Lpn).filter(models.Lpn.pallet_no == pal.pallet_no, models.Lpn.status.in_(["AVAILABLE", "RESERVED", "PICKED", "PDI_OK"])).all()
    new_load = (load or MOVE_LOAD[to_zone]).upper()
    if to_zone == "YARD":
        if any(l.status in ("PICKED", "PDI_OK") for l in live):
            raise RuleError(f"{pal.pallet_no} carries picked LPNs - cannot go to Pallet Yard")
        if load == "LOADED":
            raise RuleError("Pallet Yard takes EMPTY pallets only - unload first")
        for l in live:          # parts were unloaded in packing; drop the stale link
            l.pallet_no = None
        if live:
            alerts.append(f"{len(live)} LPN unlinked from {pal.pallet_no} (Yard = empty only)")
        new_load = "EMPTY"
    if to_zone != "YARD" and pal.home_plant != plant and pal.status == "HELD":
        services.move(db, pal, "IN_WIP", event_type="MOVE_TO_WIP", user_id=user_id, device_id=device_id, plant=plant, force=True)
    if to_zone == "YARD" and pal.status == "IN_WIP":
        services.move(db, pal, "HELD", event_type="WIP_EMPTY_BACK", user_id=user_id, device_id=device_id, plant=plant, force=True)
    db.add(models.PalletHistory(pallet_no=pal.pallet_no, event_type=f"MOVE_{frm}_{to_zone}", from_status=pal.status, to_status=pal.status,
                                plant_code=plant, user_id=user_id, device_id=device_id, event_id=event_id, remarks=remarks))
    set_zone(pal, to_zone)
    if new_load == "LOADED" and live:
        refresh_load_from_lpns(db, pal)
    else:
        set_load(db, pal, new_load, pal.load_ref if new_load == "LOADED" else None)
    return f"{pal.pallet_no}: {frm} -> {to_zone} ({pal.load_state})", alerts


# ---------------------------------------------------------------- loaded / empty
def set_load(db: Session, pal: models.Pallet, state: str, ref: str | None = None):
    if pal is None:
        return
    if pal.load_state != state or (ref and pal.load_ref != ref):
        pal.load_state = state
        pal.load_ref = (ref or "")[:60] or None
        pal.load_changed_at = utcnow()


def refresh_load_from_lpns(db: Session, pal: models.Pallet):
    """Pallet is LOADED while any live LPN sits on it, otherwise EMPTY."""
    db.flush()
    live = db.query(models.Lpn).filter(models.Lpn.pallet_no == pal.pallet_no,
                                       models.Lpn.status.in_(["AVAILABLE", "RESERVED", "PICKED", "PDI_OK"])).all()
    if live:
        parts = sorted({l.part_no for l in live})
        set_load(db, pal, "LOADED", f"{','.join(parts)[:40]} x{sum(l.qty for l in live)} ({len(live)} LPN)")
    elif pal.load_state == "LOADED" and pal.status in ("AVAILABLE", "ALLOCATED"):
        set_load(db, pal, "EMPTY")


# ---------------------------------------------------------------- missed scan
def record_miss(db: Session, *, pallet: models.Pallet | None = None, lpn_no: str | None = None, plant: str | None,
                detected_at: str, missed_point: str, expected: str, action: str, message: str,
                user_id: str | None = None, device_id: str | None = None, current_ref: str | None = None) -> str:
    db.add(models.ScanMiss(plant_code=plant, pallet_no=pallet.pallet_no if pallet else None, lpn_no=lpn_no,
                           detected_at=detected_at, missed_point=missed_point, found_status=pallet.status if pallet else None,
                           expected_status=expected, last_ref=(pallet.challan_ref or pallet.picklist_no) if pallet else None,
                           current_ref=current_ref, action=action, message=message[:300], user_id=user_id, device_id=device_id,
                           responsible_role=SCAN_POINT_ROLE.get(missed_point)))
    return f"MISSED SCAN ({missed_point}): {message}"


def check_dock(db: Session, pal: models.Pallet, plant: str, *, user_id, device_id, ref) -> str | None:
    """Dock expects an AVAILABLE pallet in the home yard. Infer what was skipped; auto-correct when safe."""
    st = pal.status
    if st in ("AT_CUSTOMER", "IN_RETURN", "IN_TRANSIT") and pal.home_plant == plant:
        missed = "RETURN_SLIP" if st == "AT_CUSTOMER" else "YARD_IN"
        where = f"customer {pal.customer_code}" if st == "AT_CUSTOMER" else ("another plant" if st == "IN_TRANSIT" else "return slip")
        msg = record_miss(db, pallet=pal, plant=plant, detected_at="DOCK", missed_point=missed, expected="AVAILABLE",
                          action="AUTO_CORRECTED", user_id=user_id, device_id=device_id, current_ref=ref,
                          message=f"{pal.pallet_no} was {st} ({where}) but is physically at dock - return not scanned; received now")
        services.move(db, pal, "AVAILABLE", event_type="AUTO_RECEIVE_MISSED_SCAN", user_id=user_id, device_id=device_id,
                      plant=plant, ref=ref, remarks=msg, force=True)
        set_load(db, pal, "EMPTY"); set_zone(pal, "YARD")
        return msg
    if st == "ALLOCATED" and pal.picklist_no:
        old = db.get(models.PickList, pal.picklist_no)
        if old and old.status in ("DISPATCHED", "CANCELLED"):
            msg = record_miss(db, pallet=pal, plant=plant, detected_at="DOCK", missed_point="OUT_GATE" if old.status == "DISPATCHED" else "DOCK_SCAN",
                              expected="AVAILABLE", action="AUTO_CORRECTED", user_id=user_id, device_id=device_id, current_ref=ref,
                              message=f"{pal.pallet_no} still ALLOCATED to {old.picklist_no} ({old.status}); released")
            services.move(db, pal, "AVAILABLE", event_type="AUTO_RELEASE_MISSED_SCAN", user_id=user_id, device_id=device_id,
                          plant=plant, ref=ref, remarks=msg, force=True)
            return msg
    return None


def check_yard(db: Session, pal: models.Pallet, plant: str, slip, *, user_id, device_id) -> tuple[str | None, bool]:
    """Yard expects IN_RETURN (slip) or AT_CUSTOMER (B2 qty slip). Returns (alert, block)."""
    st = pal.status
    ref = slip.slip_no if slip else None
    if st == "ALLOCATED":
        pk = db.get(models.PickList, pal.picklist_no) if pal.picklist_no else None
        if pk and pk.status in ("APPROVED", "CHALLANED", "READY"):
            return record_miss(db, pallet=pal, plant=plant, detected_at="YARD", missed_point="OUT_GATE", expected="IN_RETURN",
                               action="BLOCKED", user_id=user_id, device_id=device_id, current_ref=ref,
                               message=f"{pal.pallet_no} is on {pk.picklist_no} ({pk.status}) - not gated out yet; check vehicle"), True
    if st == "AT_CUSTOMER" and not slip:
        return record_miss(db, pallet=pal, plant=plant, detected_at="YARD", missed_point="RETURN_SLIP", expected="IN_RETURN",
                           action="AUTO_CORRECTED", user_id=user_id, device_id=device_id,
                           message=f"{pal.pallet_no} came back from {pal.customer_code} without return slip / IN-gate scan"), False
    if st == "AT_CUSTOMER" and slip and slip.mode in ("A", "B1"):
        listed = db.query(models.ReturnSlipLine).filter_by(slip_no=slip.slip_no, pallet_no=pal.pallet_no, declared=True).first()
        if not listed:
            return record_miss(db, pallet=pal, plant=plant, detected_at="YARD", missed_point="RETURN_SLIP", expected="IN_RETURN",
                               action="ALERT", user_id=user_id, device_id=device_id, current_ref=ref,
                               message=f"{pal.pallet_no} received but not scanned on slip {slip.slip_no}"), False
    if st == "IN_TRANSIT" and pal.home_plant != plant:
        return record_miss(db, pallet=pal, plant=plant, detected_at="YARD", missed_point="EMPTY_RETURN_DEST", expected=f"home {pal.home_plant}",
                           action="ALERT", user_id=user_id, device_id=device_id, current_ref=ref,
                           message=f"{pal.pallet_no} was sent to {pal.home_plant} but arrived at {plant}"), False
    return None, False


def check_return_slip(db: Session, pal: models.Pallet, plant: str, slip_no: str, customer: str, *, user_id) -> str | None:
    if pal.status in ("AVAILABLE", "ALLOCATED"):
        return record_miss(db, pallet=pal, plant=plant, detected_at="RETURN_SLIP", missed_point="OUT_GATE", expected="AT_CUSTOMER",
                           action="AUTO_CORRECTED", user_id=user_id, current_ref=slip_no,
                           message=f"{pal.pallet_no} returned by {customer} but ledger shows {pal.status} - dispatch was never scanned")
    return None


# ---------------------------------------------------------------- WMS stock
def wms_last(db: Session, plant: str):
    return db.query(models.WmsUpload).filter_by(plant_code=plant).order_by(models.WmsUpload.ts.desc()).first()


def wms_status(db: Session, plant: str) -> dict:
    pl = db.get(models.Plant, plant)
    last = wms_last(db, plant)
    hours = pl.wms_stale_hours if pl and pl.wms_stale_hours else 4
    age = (utcnow() - last.ts).total_seconds() / 3600 if last else None
    return {"plant": plant, "last_upload": last.ts if last else None, "source": last.source if last else None,
            "age_hours": round(age, 1) if age is not None else None, "limit_hours": hours,
            "stale": age is None or age > hours, "batch_id": last.batch_id if last else None}


def require_fresh_wms(db: Session, plant: str):
    st = wms_status(db, plant)
    if st["stale"]:
        when = "never uploaded" if st["age_hours"] is None else f"last uploaded {st['age_hours']} h ago (limit {st['limit_hours']} h)"
        raise RuleError(f"WMS stock is {when}. Upload the latest WMS stock before releasing a pick list.")


def _norm_row(r: dict) -> dict | None:
    k = {str(a).strip().upper().replace(" ", "_"): b for a, b in r.items() if a is not None}

    def g(*names):
        for n in names:
            if n in k and k[n] not in (None, ""):
                return k[n]
        return None
    lpn = g("LPN", "LPN_NO", "LICENSE_PLATE_NUMBER", "LPN_NUMBER")
    part = g("PART_NO", "ITEM", "ITEM_CODE", "SEGMENT1", "PART")
    if not lpn or not part:
        return None
    try:
        qty = int(float(g("QTY", "QUANTITY", "ONHAND", "ON_HAND_QTY", "PRIMARY_QUANTITY") or 0))
    except Exception:
        qty = 0
    s = lambda v: (str(v).strip() or None) if v is not None else None
    return {"lpn": s(lpn), "part_no": s(part), "qty": qty, "subinventory": s(g("SUBINVENTORY", "SUBINV", "SUBINVENTORY_CODE")),
            "locator": s(g("LOCATOR", "LOCATOR_CODE")), "pallet_no": s(g("PALLET_NO", "PALLET", "PALLET_NUMBER")),
            "desc": s(g("PART_DESC", "DESCRIPTION", "ITEM_DESCRIPTION"))}


def apply_wms_snapshot(db: Session, plant: str, raw_rows: list[dict], source: str, user_id: str | None) -> dict:
    """Full on-hand snapshot for one plant. In-process LPNs (picked / PDI / txn pending) are protected:
    only their WMS view is recorded, never their status. Reserved LPNs keep their reservation."""
    rows, bad = {}, 0
    for r in raw_rows:
        n = _norm_row(r) if not {"lpn", "part_no"} <= set(r) else _norm_row({("LPN" if a == "lpn" else a): b for a, b in r.items()})
        if not n:
            bad += 1; continue
        rows[n["lpn"]] = n
    if not rows:
        raise RuleError("No valid rows - need at least LPN and PART_NO columns")
    batch = f"WMS-{plant}-{utcnow():%y%m%d}-{services.next_seq(db, plant + ':WMS'):05d}"
    now = utcnow()
    new = upd = prot = 0
    warnings = []
    existing = {l.lpn_no: l for l in db.query(models.Lpn).filter_by(plant_code=plant).all()}
    for lpn_no, r in rows.items():
        l = existing.get(lpn_no)
        if l is None:
            other = db.get(models.Lpn, lpn_no)
            if other:     # LPN known under another plant
                warnings.append(f"{lpn_no}: belongs to plant {other.plant_code}, skipped"); continue
            l = models.Lpn(lpn_no=lpn_no, plant_code=plant, part_no=r["part_no"], status="AVAILABLE")
            db.add(l); new += 1
        else:
            upd += 1
        l.wms_batch, l.wms_seen_at, l.wms_missing, l.wms_subinv = batch, now, False, r["subinventory"]
        if l.status in IN_PROCESS or l.txn_state in ("PENDING", "SENT"):
            prot += 1
            if l.part_no != r["part_no"] or l.qty != r["qty"]:
                warnings.append(f"{lpn_no}: in process ({l.status}) - WMS shows {r['part_no']} x{r['qty']}, app keeps {l.part_no} x{l.qty}")
            continue
        if l.status in ("DISPATCHED", "REJECTED") and l.txn_state == "CONFIRMED":
            if l.status == "DISPATCHED":
                warnings.append(f"{lpn_no}: dispatched in app but still in WMS stock ({r['subinventory']})")
            l.subinventory = r["subinventory"]; continue
        if l.status == "RESERVED" and l.part_no != r["part_no"]:
            warnings.append(f"{lpn_no}: reserved for {l.reserved_for} but WMS now shows part {r['part_no']} - reservation released")
            l.status, l.reserved_for, l.reserved_at = "AVAILABLE", None, None
        if l.status == "MISSING":
            l.status = "AVAILABLE"
        l.part_no, l.qty, l.subinventory, l.locator = r["part_no"], r["qty"], r["subinventory"], r["locator"]
        if r["desc"]:
            l.part_desc = r["desc"]
        if r["pallet_no"]:
            if l.pallet_no and l.pallet_no != r["pallet_no"]:
                warnings.append(f"{lpn_no}: pallet changed {l.pallet_no} -> {r['pallet_no']}")
            l.pallet_no = r["pallet_no"]
        if l.qty <= 0 and l.status == "AVAILABLE":
            l.status = "MISSING"
    missing = 0
    for lpn_no, l in existing.items():
        if lpn_no in rows:
            continue
        if l.status == "AVAILABLE":
            l.status = "MISSING"; missing += 1
        elif l.status == "RESERVED":
            l.wms_missing = True; missing += 1
            warnings.append(f"{lpn_no}: RESERVED for {l.reserved_for} but not in WMS stock - check before picking")
        elif l.status in IN_PROCESS:
            l.wms_missing = True
            warnings.append(f"{lpn_no}: {l.status} on {l.picklist_no} but not in WMS stock")
    db.flush()
    # pallets carrying stock = LOADED
    for pno in {r["pallet_no"] for r in rows.values() if r["pallet_no"]}:
        pal = db.get(models.Pallet, pno)
        if pal:
            refresh_load_from_lpns(db, pal)
    up = models.WmsUpload(batch_id=batch, plant_code=plant, source=source, rows=len(rows), new_lpns=new, updated=upd,
                          missing=missing, protected=prot, user_id=user_id, summary="\n".join(warnings[:500]))
    db.add(up)
    return {"batch_id": batch, "rows": len(rows), "bad_rows": bad, "new": new, "updated": upd, "missing": missing,
            "protected": prot, "warnings": warnings[:200]}


# ---------------------------------------------------------------- blanket + reservation
def blanket_open_qty(db: Session, bo: models.BlanketOrder, exclude_pl: str | None = None) -> int:
    pending = db.query(func.coalesce(func.sum(models.PickList.part_qty), 0)).filter(
        models.PickList.blanket_id == bo.id, models.PickList.so_number.is_(None),
        models.PickList.status.notin_(["CANCELLED"]), models.PickList.picklist_no != (exclude_pl or "")).scalar() or 0
    return (bo.schedule_qty or 0) - (bo.released_qty or 0) - int(pending)


def validate_blanket(db: Session, bo: models.BlanketOrder | None, plant: str, customer: str, qty: int):
    if not bo or not bo.active:
        raise RuleError("Blanket order not found / inactive")
    if bo.plant_code != plant or bo.customer_code != customer:
        raise RuleError("Blanket order is for another plant / customer")
    now = utcnow()
    if (bo.valid_from and now < bo.valid_from) or (bo.valid_to and now > bo.valid_to + timedelta(days=1)):
        raise RuleError(f"Blanket {bo.blanket_no} not valid today")
    open_q = blanket_open_qty(db, bo)
    if qty > open_q:
        raise RuleError(f"Blanket {bo.blanket_no} / PO {bo.po_number}: only {open_q} open against schedule {bo.schedule_qty}")


def reserve(db: Session, pk: models.PickList) -> list[str]:
    """FIFO reserve LPNs of the part up to part_qty (oldest WMS sighting first)."""
    need = pk.part_qty or 0
    got = []
    q = db.query(models.Lpn).filter(models.Lpn.plant_code == pk.plant_code, models.Lpn.part_no == pk.part_no,
                                    models.Lpn.status == "AVAILABLE", models.Lpn.qty > 0).order_by(models.Lpn.wms_seen_at, models.Lpn.lpn_no)
    for l in q.all():
        if need <= 0:
            break
        l.status, l.reserved_for, l.reserved_at = "RESERVED", pk.picklist_no, utcnow()
        got.append(l.lpn_no); need -= l.qty
    if need > 0:
        for n in got:
            x = db.get(models.Lpn, n); x.status, x.reserved_for, x.reserved_at = "AVAILABLE", None, None
        avail = db.query(func.coalesce(func.sum(models.Lpn.qty), 0)).filter(models.Lpn.plant_code == pk.plant_code, models.Lpn.part_no == pk.part_no,
                                                                         models.Lpn.status == "AVAILABLE").scalar()
        raise RuleError(f"Only {avail} of part {pk.part_no} free in WMS stock (needed {pk.part_qty})")
    return got


def release_reservations(db: Session, picklist_no: str, only_unpicked: bool = True) -> int:
    db.flush()
    n = 0
    for l in db.query(models.Lpn).filter_by(reserved_for=picklist_no).all():
        if l.status == "RESERVED" or not only_unpicked:
            if l.status in ("RESERVED", "PICKED"):
                l.status = "AVAILABLE"
            l.reserved_for = l.reserved_at = None
            if not only_unpicked:
                l.picklist_no = None
            n += 1
    return n


# ---------------------------------------------------------------- dock scan (LPN or pallet)
def resolve_any(db: Session, scanned: str, plant: str):
    """Returns ('LPN', lpn, pallet|None) or ('PALLET', None, pallet) or (None, None, None)."""
    s = scanned.strip()
    l = db.get(models.Lpn, s)
    if l:
        return "LPN", l, (db.get(models.Pallet, l.pallet_no) if l.pallet_no else None)
    _, pal = services.resolve_tag(db, s)
    if pal:
        return "PALLET", None, pal
    return None, None, None


def picked_qty(db: Session, pk_no: str) -> int:
    db.flush()
    return int(db.query(func.coalesce(func.sum(models.PickListLpn.qty), 0)).filter(
        models.PickListLpn.picklist_no == pk_no, models.PickListLpn.pdi_result.is_(None) | (models.PickListLpn.pdi_result == "OK")).scalar() or 0)


def _alloc_pallet(db, pk, pal, plant, user_id, device_id, event_id, alerts):
    if pal.status == "ALLOCATED" and pal.picklist_no == pk.picklist_no:
        return
    a = check_dock(db, pal, plant, user_id=user_id, device_id=device_id, ref=pk.picklist_no)
    if a:
        alerts.append(a)
    if pal.status == "AVAILABLE" and pal.home_plant == plant:
        alerts += zone_check(db, pal, DISPATCH_ZONES, plant, "DOCK", user_id=user_id, device_id=device_id, ref=pk.picklist_no)
    if pal.home_plant != plant:
        raise RuleError(f"Foreign pallet: {pal.pallet_no} belongs to {pal.home_plant}")
    if pal.status != "AVAILABLE":
        raise RuleError(f"Pallet {pal.pallet_no} is {pal.status}" + (f" ({pal.picklist_no})" if pal.picklist_no else ""))
    if pal.current_tag:
        t = db.get(models.Tag, pal.current_tag)
        if t and t.status == "RETIRED":
            raise RuleError(f"Tag {t.tag_no} is retired")
    if pk.source != "HMIL_BENCH" and db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no).count() >= pk.qty:
        raise RuleError(f"Pallet quantity {pk.qty} already reached")
    services.move(db, pal, "ALLOCATED", event_type="DOCK_SCAN", user_id=user_id, device_id=device_id, event_id=event_id, plant=plant, ref=pk.picklist_no)
    pal.picklist_no = pk.picklist_no
    db.add(models.PickListLine(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no, user_id=user_id, device_id=device_id))


def _pick_lpn(db, pk, l, pal, user_id):
    if l.plant_code != pk.plant_code:
        raise RuleError(f"LPN {l.lpn_no} belongs to plant {l.plant_code}")
    bench = pk.source == "HMIL_BENCH"
    if bench and l.reserved_for != pk.picklist_no and l.picklist_no != pk.picklist_no:
        raise RuleError(f"LPN {l.lpn_no} is not on HMIL Bench trip {pk.ext_ref}" + (f" (it is on {l.reserved_for})" if l.reserved_for else ""))
    if not bench and l.part_no != pk.part_no:
        raise RuleError(f"LPN {l.lpn_no} is part {l.part_no}; pick list needs {pk.part_no}")
    if l.status == "PICKED" and l.picklist_no == pk.picklist_no:
        return False
    if l.status == "RESERVED" and l.reserved_for != pk.picklist_no:
        raise RuleError(f"LPN {l.lpn_no} is reserved for {l.reserved_for}")
    if l.status not in ("AVAILABLE", "RESERVED"):
        raise RuleError(f"LPN {l.lpn_no} is {l.status}" + (f" ({l.picklist_no})" if l.picklist_no else ""))
    if l.wms_missing:
        raise RuleError(f"LPN {l.lpn_no} not in latest WMS stock - upload WMS / check")
    if picked_qty(db, pk.picklist_no) + l.qty > (pk.part_qty or 0):
        raise RuleError(f"LPN {l.lpn_no} qty {l.qty} exceeds pick list balance ({(pk.part_qty or 0) - picked_qty(db, pk.picklist_no)})")
    if l.status == "AVAILABLE":     # swap: free a not-yet-picked reservation so reserved total stays within need
        over = picked_qty(db, pk.picklist_no) + l.qty + sum(x.qty for x in db.query(models.Lpn).filter_by(reserved_for=pk.picklist_no, status="RESERVED").all()) - (pk.part_qty or 0)
        for x in db.query(models.Lpn).filter_by(reserved_for=pk.picklist_no, status="RESERVED").order_by(models.Lpn.qty).all():
            if over <= 0:
                break
            x.status, x.reserved_for, x.reserved_at = "AVAILABLE", None, None; over -= x.qty
    l.status, l.picklist_no, l.reserved_for = "PICKED", pk.picklist_no, pk.picklist_no
    l.pallet_no = pal.pallet_no
    db.add(models.PickListLpn(picklist_no=pk.picklist_no, lpn_no=l.lpn_no, pallet_no=pal.pallet_no, part_no=l.part_no, qty=l.qty, user_id=user_id))
    return True


def dock_scan(db: Session, pk: models.PickList, scanned: str, plant: str, *, pallet_scan: str | None = None,
              user_id=None, device_id=None, event_id=None) -> tuple[str, list[str]]:
    """Any order: LPN scan fetches its pallet; pallet scan fetches its LPNs. Returns (message, alerts)."""
    alerts: list[str] = []
    if pk.status not in ("OPEN",):
        raise RuleError(f"Pick list is {pk.status}")
    kind, l, pal = resolve_any(db, scanned, plant)
    if pallet_scan:                      # operator scanned both (links LPN to pallet)
        k2, l2, p2 = resolve_any(db, pallet_scan, plant)
        if kind == "PALLET" and k2 == "LPN":
            kind, l, pal = "LPN", l2, pal
        elif k2 == "PALLET":
            if l and l.pallet_no and l.pallet_no != p2.pallet_no:
                alerts.append(f"LPN {l.lpn_no} re-linked {l.pallet_no} -> {p2.pallet_no}")
            pal = p2
    if kind is None:
        raise RuleError(f"Unknown LPN / tag {scanned}")

    if pk.dispatch_type == "EMPTY_RETURN":
        if kind != "PALLET":
            raise RuleError("Empty return: scan the pallet, not an LPN")
        if pal.home_plant != pk.to_plant:
            raise RuleError(f"{pal.pallet_no} belongs to {pal.home_plant}, this return is for {pk.to_plant}")
        if pal.status not in ("HELD", "IN_WIP") or pal.location_plant != plant:
            raise RuleError(f"{pal.pallet_no} is {pal.status} at {pal.location_plant or '-'} - not available for return")
        if pal.load_state == "LOADED":
            live = db.query(models.Lpn).filter(models.Lpn.pallet_no == pal.pallet_no, models.Lpn.status.in_(["AVAILABLE", "RESERVED", "PICKED"])).count()
            if live:
                raise RuleError(f"{pal.pallet_no} still LOADED ({pal.load_ref}) - consume / unload before returning")
            alerts.append(record_miss(db, pallet=pal, plant=plant, detected_at="EMPTY_RETURN", missed_point="WIP_EMPTY", expected="EMPTY",
                                      action="AUTO_CORRECTED", user_id=user_id, device_id=device_id, current_ref=pk.picklist_no,
                                      message=f"{pal.pallet_no} shown LOADED but scanned for empty return - WIP consumption not recorded"))
        if db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no).count() >= pk.qty:
            raise RuleError(f"Pallet quantity {pk.qty} already reached")
        services.move(db, pal, "ALLOCATED", event_type="EMPTY_RETURN_SCAN", user_id=user_id, device_id=device_id, event_id=event_id,
                      plant=plant, ref=pk.picklist_no, force=True)
        pal.picklist_no = pk.picklist_no
        set_load(db, pal, "EMPTY")
        db.add(models.PickListLine(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no, user_id=user_id, device_id=device_id))
        return f"{pal.pallet_no} EMPTY -> {pk.to_plant}", alerts

    if pk.dispatch_type not in PART_TYPES:       # pallet-only (legacy)
        if kind != "PALLET":
            raise RuleError("This pick list is pallet-only; scan the pallet")
        _alloc_pallet(db, pk, pal, plant, user_id, device_id, event_id, alerts)
        return pal.pallet_no, alerts

    if kind == "LPN":
        if pal is None:
            raise RuleError(f"LPN {l.lpn_no} not linked to a pallet - scan the pallet together with the LPN")
        _alloc_pallet(db, pk, pal, plant, user_id, device_id, event_id, alerts)
        _pick_lpn(db, pk, l, pal, user_id)
        refresh_load_from_lpns(db, pal)
        return f"LPN {l.lpn_no} ({l.part_no} x{l.qty}) on {pal.pallet_no}", alerts
    # pallet scanned -> fetch its LPNs
    lq = db.query(models.Lpn).filter(models.Lpn.pallet_no == pal.pallet_no, models.Lpn.status.in_(["AVAILABLE", "RESERVED"]))
    lp = (lq.filter(models.Lpn.reserved_for == pk.picklist_no) if pk.source == "HMIL_BENCH" else lq.filter(models.Lpn.part_no == pk.part_no)).all()
    if not lp:
        others = db.query(models.Lpn).filter(models.Lpn.pallet_no == pal.pallet_no, models.Lpn.status.in_(["AVAILABLE", "RESERVED", "PICKED"])).all()
        if others:
            raise RuleError(f"{pal.pallet_no} carries {', '.join(sorted({o.part_no for o in others}))} - not part {pk.part_no}")
        raise RuleError(f"No LPN linked to {pal.pallet_no} - scan the LPN label (pallet will link)")
    _alloc_pallet(db, pk, pal, plant, user_id, device_id, event_id, alerts)
    done = [x.lpn_no for x in lp if _pick_lpn(db, pk, x, pal, user_id)]
    refresh_load_from_lpns(db, pal)
    return f"{pal.pallet_no}: {len(done)} LPN ({', '.join(done)})", alerts


def dock_unscan(db: Session, pk: models.PickList, scanned: str, plant: str, *, user_id=None, device_id=None, event_id=None) -> str:
    if pk.status != "OPEN":
        raise RuleError(f"Pick list is {pk.status}; cannot remove")
    kind, l, pal = resolve_any(db, scanned, plant)
    if kind == "LPN":
        row = db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no, lpn_no=l.lpn_no).first()
        if not row:
            raise RuleError("LPN not on this pick list")
        db.delete(row)
        l.status, l.picklist_no = "RESERVED", None       # stays reserved for this list
        db.flush()
        if pal and not db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no).count():
            _release_pallet(db, pk, pal, plant, user_id, device_id, event_id)
        return f"LPN {l.lpn_no} removed"
    if kind == "PALLET":
        if pal.picklist_no != pk.picklist_no or pal.status != "ALLOCATED":
            raise RuleError("Pallet not on this pick list")
        for row in db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no).all():
            x = db.get(models.Lpn, row.lpn_no)
            if x:
                x.status, x.picklist_no = "RESERVED", None
            db.delete(row)
        _release_pallet(db, pk, pal, plant, user_id, device_id, event_id)
        return f"{pal.pallet_no} removed"
    raise RuleError("Unknown scan")


def _release_pallet(db, pk, pal, plant, user_id, device_id, event_id):
    db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no).delete()
    back = "HELD" if pal.home_plant != plant else "AVAILABLE"
    services.move(db, pal, back, event_type="DOCK_UNSCAN", user_id=user_id, device_id=device_id, event_id=event_id, plant=plant, ref=pk.picklist_no, force=True)
    pal.picklist_no = None
    refresh_load_from_lpns(db, pal)


# ---------------------------------------------------------------- PDI + sub-inventory transfer
def subinv_rule(db: Session, plant: str, customer: str | None, part: str | None):
    rules = db.query(models.SubInvRule).filter_by(plant_code=plant, active=True).all()
    best, score = None, -1
    for r in rules:
        if r.customer_code and r.customer_code != customer:
            continue
        if r.part_no and r.part_no != part:
            continue
        sc = (2 if r.customer_code else 0) + (1 if r.part_no else 0)
        if sc > score:
            best, score = r, sc
    return best


def pdi_mark(db: Session, pk: models.PickList, lpn_no: str, result: str, remarks: str | None, user_id: str, device_id=None) -> tuple[str, list[str]]:
    alerts = []
    if pk.status != "PDI_PENDING":
        raise RuleError(f"Pick list is {pk.status}, not waiting for PDI")
    result = result.upper()
    if result not in ("OK", "REJECT"):
        raise RuleError("result must be OK or REJECT")
    kind, l, pal = resolve_any(db, lpn_no, pk.plant_code)
    rows = []
    if kind == "LPN":
        rows = db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no, lpn_no=l.lpn_no).all()
    elif kind == "PALLET":
        rows = db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no).all()
    if not rows:
        if kind == "LPN" and l.part_no == pk.part_no:
            alerts.append(record_miss(db, pallet=pal, lpn_no=l.lpn_no, plant=pk.plant_code, detected_at="PDI", missed_point="DOCK_SCAN",
                                      expected="PICKED", action="BLOCKED", user_id=user_id, device_id=device_id, current_ref=pk.picklist_no,
                                      message=f"LPN {l.lpn_no} presented for PDI on {pk.picklist_no} but was never dock-scanned"))
        raise RuleError(f"{lpn_no} is not on pick list {pk.picklist_no}" + (" - " + alerts[0] if alerts else ""))
    for r in rows:
        r.pdi_result, r.pdi_remarks = result, remarks
    return f"{len(rows)} LPN {result}", alerts


def _new_txn(db, l, pk, reason, to_sub, to_loc, user_id):
    t = models.LpnTxn(lpn_no=l.lpn_no, plant_code=l.plant_code, picklist_no=pk.picklist_no if pk else None, reason=reason,
                      from_subinv=l.subinventory, to_subinv=to_sub, to_locator=to_loc, qty=l.qty, created_by=user_id)
    db.add(t); db.flush()
    l.txn_state = "PENDING"
    return t


def pdi_complete(db: Session, pk: models.PickList, user_id: str) -> dict:
    if pk.status != "PDI_PENDING":
        raise RuleError(f"Pick list is {pk.status}")
    rows = db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no).all()
    pending = [r.lpn_no for r in rows if r.pdi_result is None]
    if pending:
        raise RuleError(f"{len(pending)} LPN not yet checked: {', '.join(pending[:10])}")
    plant = db.get(models.Plant, pk.plant_code)
    rule = subinv_rule(db, pk.plant_code, pk.customer_code, pk.part_no)
    rej = [r for r in rows if r.pdi_result == "REJECT"]
    ok = [r for r in rows if r.pdi_result == "OK"]
    for r in rej:
        l = db.get(models.Lpn, r.lpn_no)
        to = (rule.reject_subinv if rule and rule.reject_subinv else None) or plant.reject_subinv
        if not to:
            raise RuleError("Reject sub-inventory not set (Plant master / Sub-inventory rules)")
        _new_txn(db, l, pk, "PDI_REJECT", to, None, user_id)
        l.status, l.reserved_for, l.picklist_no = "REJECTED", None, pk.picklist_no
        db.delete(r)
    db.flush()
    # pallets left with no LPN go back to the yard
    for line in db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no).all():
        if not db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no, pallet_no=line.pallet_no).count():
            pal = db.get(models.Pallet, line.pallet_no)
            _release_pallet(db, pk, pal, pk.plant_code, user_id, None, None)
    pk.pdi_by, pk.pdi_at = user_id, utcnow()
    if rej:
        pk.status = "OPEN"     # re-pick replacement qty, then confirm -> PDI again for new LPNs only
        process_pending_txns(db, picklist_no=pk.picklist_no)
        return {"status": pk.status, "rejected": [r.lpn_no for r in rej], "message": f"{len(rej)} LPN rejected -> pick replacement qty {pk.part_qty - picked_qty(db, pk.picklist_no)}"}
    if not rule or not rule.ok_subinv:
        raise RuleError(f"No sub-inventory rule for customer {pk.customer_code} / part {pk.part_no} (Masters > Sub-inventory rules)")
    for r in ok:
        l = db.get(models.Lpn, r.lpn_no)
        if l.txn_state == "CONFIRMED" and l.subinventory == rule.ok_subinv:
            continue
        _new_txn(db, l, pk, "PDI_OK", rule.ok_subinv, rule.ok_locator, user_id)
        l.status = "PDI_OK"
    pk.status = "PDI_TXN_PENDING"
    process_pending_txns(db, picklist_no=pk.picklist_no)
    return {"status": pk.status, "rejected": [], "message": "PDI OK - sub-inventory transfers sent to EBS"}


def process_txn(db: Session, t: models.LpnTxn) -> str:
    """Two-step: (1) EBS accepts transfer -> SENT; (2) EBS on-hand read-back matches -> CONFIRMED."""
    l = db.get(models.Lpn, t.lpn_no)
    t.attempts += 1
    if t.status in ("PENDING", "FAILED"):
        ok, tid, msg = integration.subinv_transfer(db, t)
        if not ok:
            t.status, t.message = "FAILED", msg[:300]
            if l: l.txn_state = "FAILED"
            return t.status
        t.status, t.ebs_txn_id, t.ack_at, t.message = "SENT", tid, utcnow(), "EBS accepted"
        if l: l.txn_state = "SENT"
    if t.status == "SENT":
        ok, sub, msg = integration.verify_lpn_onhand(db, t)
        if ok:
            t.status, t.verified_at, t.message = "CONFIRMED", utcnow(), "EBS accepted + on-hand verified"
            if l:
                l.txn_state, l.subinventory = "CONFIRMED", t.to_subinv
                if t.to_locator:
                    l.locator = t.to_locator
        else:
            t.message = f"awaiting verification: {msg}"[:300]
    return t.status


def process_pending_txns(db: Session, picklist_no: str | None = None, max_attempts: int = 50) -> dict:
    q = db.query(models.LpnTxn).filter(models.LpnTxn.status.in_(["PENDING", "SENT", "FAILED"]), models.LpnTxn.attempts < max_attempts)
    if picklist_no:
        q = q.filter(models.LpnTxn.picklist_no == picklist_no)
    res = {}
    db.flush()
    for t in q.all():
        st = process_txn(db, t); res[st] = res.get(st, 0) + 1
    db.flush()
    pls = [picklist_no] if picklist_no else [x.picklist_no for x in db.query(models.PickList).filter_by(status="PDI_TXN_PENDING").all()]
    for no in pls:
        pk = db.get(models.PickList, no)
        if pk and pk.status == "PDI_TXN_PENDING":
            advance_after_txn(db, pk)
    return res


def advance_after_txn(db: Session, pk: models.PickList):
    db.flush()
    open_t = db.query(models.LpnTxn).filter(models.LpnTxn.picklist_no == pk.picklist_no, models.LpnTxn.reason == "PDI_OK",
                                            models.LpnTxn.status != "CONFIRMED").count()
    if open_t:
        return
    pk.status = "SO_PENDING"
    ok, so, msg = integration.post_sale_order(db, pk)
    if ok:
        on_so_created(db, pk, so)
    else:
        integration.queue_retry(db, "EBS_SO", pk.picklist_no, msg)


def on_so_created(db: Session, pk: models.PickList, so: str):
    pk.so_number = so
    if pk.part_no and pk.blanket_id:
        bo = db.get(models.BlanketOrder, pk.blanket_id)
        if bo:
            bo.released_qty = (bo.released_qty or 0) + (pk.part_qty or 0)
    pk.status = "READY" if pk.part_no else "OPEN"
