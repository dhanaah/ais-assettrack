"""HHT sync: event push (idempotent) + reference pull + monitor.

Event types handled in Phase 1/2:
  PALLET_SCAN_DOCK   {picklist_no, scanned}            -> ALLOCATED, picklist line
  PALLET_UNSCAN_DOCK {picklist_no, scanned}            -> AVAILABLE
  PALLET_SCAN_YARD   {slip_no, scanned, accept_foreign, damaged} -> AVAILABLE / HELD / DAMAGED + slip line
  DAMAGE_MARK        {scanned, remarks}                -> DAMAGED
  TAG_REPLACE_REQ    {scanned, remarks}                -> logged only
  PALLET_MOVE        {scanned, to_zone, load?}         -> in-plant move YARD/PRODUCTION/FGWH/PACKING
  PLANT_RECEIPT      {scanned, zone}                   -> other-plant loaded pallet received at FGWH/PACKING
  PDI_MARK           {picklist_no, scanned, result, remarks} -> LPN PDI OK / REJECT
  HEARTBEAT          {pending}                         -> device status
Dock scan accepts LPN or pallet (optional second scan `pallet`). Missed scans found on the way are recorded
(scan_misses) and returned as EXCEPTION with the alert text so the HHT shows it.
Any other type is stored with status EXCEPTION for review (forward compatible).
"""
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, services, lpn as lpnsvc
from ..db import get_db
from ..security import current_user, Principal, need, require_hht
from ..models import utcnow

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


class EventIn(BaseModel):
    event_id: str
    device_id: str
    event_type: str
    payload: dict
    local_ts: datetime
    offline: bool = False
    app_version: str | None = None


class PushIn(BaseModel):
    events: list[EventIn]


def _apply(db: Session, p: Principal, e: EventIn) -> tuple[str, str]:
    """Returns (status, result message). Raises nothing; rule errors become REJECTED."""
    pl = e.payload
    plant = p.plant
    t = e.event_type
    try:
        if t == "HEARTBEAT":
            return "APPLIED", "ok"
        if t in ("PALLET_SCAN_DOCK", "PALLET_UNSCAN_DOCK"):
            pk = db.get(models.PickList, pl["picklist_no"])
            if not pk or pk.plant_code != plant:
                raise services.RuleError("Pick list not found for this plant")
            if pk.load_point == "YARD":          # empty return loaded at the Pallet Yard
                p.require_any("EMPTY_RETURN", "DOCK_SCAN")
            else:
                p.require("DOCK_SCAN")
            if t == "PALLET_UNSCAN_DOCK":
                return "APPLIED", lpnsvc.dock_unscan(db, pk, pl["scanned"], plant, user_id=p.user_id, device_id=e.device_id, event_id=e.event_id)
            msg, alerts = lpnsvc.dock_scan(db, pk, pl["scanned"], plant, pallet_scan=pl.get("pallet"), user_id=p.user_id,
                                           device_id=e.device_id, event_id=e.event_id)
            return ("EXCEPTION" if alerts else "APPLIED"), msg + ("" if not alerts else " | ⚠ " + " | ".join(alerts))
        if t == "PALLET_MOVE":
            p.require_any("INTERNAL_MOVE", "MOVE_TO_" + str(pl.get("to_zone", "")).upper())
            tag, pal = services.resolve_tag(db, pl["scanned"])
            if not pal:
                l = db.get(models.Lpn, pl["scanned"].strip())
                pal = db.get(models.Pallet, l.pallet_no) if l and l.pallet_no else None
            if not pal:
                raise services.RuleError(f"Unknown pallet / LPN {pl['scanned']}")
            msg, alerts = lpnsvc.internal_move(db, pal, pl["to_zone"], plant, load=pl.get("load"), user_id=p.user_id,
                                               device_id=e.device_id, event_id=e.event_id, remarks=pl.get("remarks"))
            return ("EXCEPTION" if alerts else "APPLIED"), msg + ("" if not alerts else " | ⚠ " + " | ".join(alerts))
        if t == "PLANT_RECEIPT":
            p.require("PLANT_RECEIPT")
            tag, pal = services.resolve_tag(db, pl["scanned"])
            if not pal:
                raise services.RuleError(f"Unknown pallet {pl['scanned']}")
            msg, alerts = lpnsvc.receive_from_plant(db, pal, pl.get("zone", "FGWH"), plant, user_id=p.user_id, device_id=e.device_id,
                                                    event_id=e.event_id, ref=pl.get("ref"))
            return ("EXCEPTION" if alerts else "APPLIED"), msg + ("" if not alerts else " | ⚠ " + " | ".join(alerts))
        if t == "PDI_MARK":
            p.require("PDI_CHECK")
            pk = db.get(models.PickList, pl["picklist_no"])
            if not pk or pk.plant_code != plant:
                raise services.RuleError("Pick list not found for this plant")
            msg, alerts = lpnsvc.pdi_mark(db, pk, pl["scanned"], pl.get("result", "OK"), pl.get("remarks"), p.user_id, e.device_id)
            return ("EXCEPTION" if alerts else "APPLIED"), msg
        if t == "PALLET_SCAN_YARD":
            p.require("YARD_SCAN")
            slip = db.get(models.ReturnSlip, pl["slip_no"]) if pl.get("slip_no") else None
            if slip and slip.plant_code != plant:
                raise services.RuleError("Slip belongs to another plant")
            tag, pal = services.resolve_tag(db, pl["scanned"])
            registered = False
            if not pal:
                info = services.parse_pallet_qr(pl["scanned"])
                pal = services.register_from_qr(db, info, plant, user_id=p.user_id, device_id=e.device_id, event_id=e.event_id) if info else None
                registered = pal is not None
            if not pal:
                if slip:
                    db.add(models.ReturnSlipLine(slip_no=slip.slip_no, pallet_no=pl["scanned"][:30], declared=False, received=True, exception="UNKNOWN"))
                info = services.parse_pallet_qr(pl["scanned"])
                why = f" - owner plant {info['owner_plant']} not in Plant master" if info and info.get("owner_plant") else ""
                return "EXCEPTION", f"Unknown tag {pl['scanned'][:40]} quarantined{why}"
            if registered:
                if slip:
                    db.add(models.ReturnSlipLine(slip_no=slip.slip_no, pallet_no=pal.pallet_no, declared=False, received=True, exception=None if pal.home_plant == plant else "FOREIGN"))
                return "EXCEPTION", f"NEW pallet {pal.pallet_no} registered from its QR label ({pal.pallet_type}, owner {pal.home_plant}) -> {pal.status} in Yard"
            if pal.home_plant != plant and pal.status in ("AT_CUSTOMER", "IN_TRANSIT") and pal.customer_code == plant:
                raise services.RuleError(f"{pal.pallet_no} is loaded material from {pal.home_plant} - receive at FGWH / Packing, not Yard")
            live = db.query(models.Lpn).filter(models.Lpn.pallet_no == pal.pallet_no, models.Lpn.status.in_(["PICKED", "PDI_OK"])).count()
            if live and pal.status == "ALLOCATED":
                raise services.RuleError(f"{pal.pallet_no} is LOADED on {pal.picklist_no} - Pallet Yard takes empty pallets only")
            alert, block = lpnsvc.check_yard(db, pal, plant, slip, user_id=p.user_id, device_id=e.device_id)
            if block:
                return "EXCEPTION", "⚠ " + alert
            if pal.home_plant != plant:
                if not pl.get("accept_foreign"):
                    raise services.RuleError(f"Foreign pallet {pal.pallet_no} ({pal.home_plant}) - not accepted")
                services.move(db, pal, "HELD", event_type="YARD_SCAN_FOREIGN", user_id=p.user_id, device_id=e.device_id,
                              event_id=e.event_id, plant=plant, ref=slip.slip_no if slip else None, force=True)
                lpnsvc.set_zone(pal, "YARD"); lpnsvc.set_load(db, pal, "EMPTY")
                if slip:
                    db.add(models.ReturnSlipLine(slip_no=slip.slip_no, pallet_no=pal.pallet_no, declared=False, received=True, exception="FOREIGN"))
                return "EXCEPTION", f"{pal.pallet_no} HELD for {pal.home_plant}" + (f" | ⚠ {alert}" if alert else "")
            exc = None
            if slip:
                line = db.query(models.ReturnSlipLine).filter_by(slip_no=slip.slip_no, pallet_no=pal.pallet_no).first()
                if line:
                    line.received = True
                else:
                    exc = "EXCESS" if pal.customer_code == slip.customer_code or pal.customer_code is None else "CROSS_CUSTOMER"
                    db.add(models.ReturnSlipLine(slip_no=slip.slip_no, pallet_no=pal.pallet_no, declared=False, received=True, exception=exc))
                if slip.status in ("OPEN", "PENDING_VERIFICATION", "IN_GATE"):
                    slip.status = "RECEIVING"
            to = "DAMAGED" if pl.get("damaged") else "AVAILABLE"
            services.move(db, pal, to, event_type="YARD_SCAN", user_id=p.user_id, device_id=e.device_id, event_id=e.event_id,
                          plant=plant, ref=slip.slip_no if slip else None, remarks=pl.get("remarks"), force=pal.status in ("AVAILABLE", "ALLOCATED"))
            lpnsvc.set_zone(pal, "YARD"); lpnsvc.set_load(db, pal, "EMPTY")
            for l in db.query(models.Lpn).filter(models.Lpn.pallet_no == pal.pallet_no, models.Lpn.status.in_(["AVAILABLE", "RESERVED"])).all():
                l.pallet_no = None
            if pl.get("damaged") and slip:
                db.query(models.ReturnSlipLine).filter_by(slip_no=slip.slip_no, pallet_no=pal.pallet_no).update({"exception": "DAMAGED"})
            return ("EXCEPTION" if exc or alert or pl.get("damaged") else "APPLIED"), f"{pal.pallet_no} {to}" + (f" ({exc})" if exc else "") + (f" | ⚠ {alert}" if alert else "")
        if t == "DAMAGE_MARK":
            p.require("DAMAGE_MARK")
            tag, pal = services.resolve_tag(db, pl["scanned"])
            if not pal:
                raise services.RuleError("Unknown tag")
            services.move(db, pal, "DAMAGED", event_type="DAMAGE_MARK", user_id=p.user_id, device_id=e.device_id, event_id=e.event_id, plant=plant, remarks=pl.get("remarks"))
            return "APPLIED", pal.pallet_no
        if t == "TAG_REPLACE_REQ":
            p.require("TAG_REPLACE_REQUEST")
            tag, pal = services.resolve_tag(db, pl["scanned"])
            db.add(models.PalletHistory(pallet_no=pal.pallet_no if pal else pl["scanned"], event_type="TAG_REPLACE_REQ", plant_code=plant,
                                        user_id=p.user_id, device_id=e.device_id, event_id=e.event_id, remarks=pl.get("remarks")))
            return "APPLIED", "request logged"
        return "EXCEPTION", f"Unknown event type {t} stored for review"
    except services.RuleError as ex:
        return "REJECTED", str(ex)
    except HTTPException as ex:
        return "REJECTED", str(ex.detail)
    except KeyError as ex:
        return "REJECTED", f"Missing field {ex}"


@router.post("/push")
def push(body: PushIn, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    require_hht(request)
    if not p.plant:
        raise HTTPException(400, "Only plant users push events")
    results = []
    for e in sorted(body.events, key=lambda x: x.local_ts):
        existing = db.get(models.Event, e.event_id)
        if existing:
            results.append({"event_id": e.event_id, "status": existing.status, "result": existing.result, "duplicate": True})
            continue
        dev = db.get(models.Device, e.device_id)
        if dev and dev.blocked:
            results.append({"event_id": e.event_id, "status": "REJECTED", "result": "device blocked"}); continue
        if not dev:
            dev = models.Device(device_id=e.device_id, plant_code=p.plant); db.add(dev)
        dev.last_seen = utcnow(); dev.last_user = p.user_id; dev.app_version = e.app_version
        if e.event_type == "HEARTBEAT":              # device status only - not stored as an event (one per minute per HHT)
            dev.pending_reported = int(e.payload.get("pending", 0) or 0)
            db.commit()
            results.append({"event_id": e.event_id, "status": "APPLIED", "result": "ok"}); continue
        sp = db.begin_nested()
        status, msg = _apply(db, p, e)
        if status == "REJECTED":
            sp.rollback()
        else:
            sp.commit()
        db.add(models.Event(event_id=e.event_id, device_id=e.device_id, user_id=p.user_id, plant_code=p.plant, event_type=e.event_type,
                            payload=json.dumps(e.payload, default=str), local_ts=e.local_ts, app_version=e.app_version,
                            offline=e.offline, status=status, result=msg[:300]))
        try:
            db.commit()
        except IntegrityError:
            # the same event arrived twice at the same moment (HHT retry on another port): keep the first, answer with its result
            db.rollback()
            existing = db.get(models.Event, e.event_id)
            if existing:
                results.append({"event_id": e.event_id, "status": existing.status, "result": existing.result, "duplicate": True}); continue
            raise
        results.append({"event_id": e.event_id, "status": status, "result": msg})
    return {"results": results, "server_time": utcnow().isoformat()}


def purge_old_events(db: Session, days: int | None = None) -> int:
    """Housekeeping (retry job): applied events older than EVENT_RETENTION_DAYS are deleted; rejected / exception kept 2x longer."""
    from .. import config
    days = days or config.EVENT_RETENTION_DAYS
    cut = utcnow() - timedelta(days=days)
    n = db.query(models.Event).filter(models.Event.received_ts < cut, models.Event.status == "APPLIED").delete(synchronize_session=False)
    n += db.query(models.Event).filter(models.Event.received_ts < utcnow() - timedelta(days=days * 2)).delete(synchronize_session=False)
    return n


@router.get("/pull")
def pull(request: Request, since: datetime | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Reference cache for the HHT. `since` = last pull time -> delta of pallets; masters always full (small)."""
    from ..security import require_client_version
    require_client_version(request.headers.get("x-app-version"))
    if not p.plant:
        raise HTTPException(400, "Only plant users pull")
    try:
        from .. import bench
        from ..db import SessionLocal
        bench.pull_if_stale(SessionLocal)
    except Exception:
        pass
    pq = db.query(models.Pallet).filter((models.Pallet.home_plant == p.plant) | (models.Pallet.location_plant == p.plant))
    if since:
        pq = pq.filter(models.Pallet.updated_at >= since)
    pallets = [{"pallet_no": x.pallet_no, "tag": x.current_tag, "home": x.home_plant, "type": x.pallet_type, "status": x.status,
                "customer": x.customer_code, "picklist": x.picklist_no, "zone": x.zone, "load": x.load_state, "load_ref": x.load_ref,
                "location": x.location_plant} for x in pq.all()]
    lq = db.query(models.Lpn).filter(models.Lpn.plant_code == p.plant)
    if since:        # delta: every LPN that changed, so one that was dispatched / rejected is corrected in the HHT cache
        lq = lq.filter(models.Lpn.updated_at >= since)
    else:            # full: live ones only (keeps the cache small)
        lq = lq.filter(models.Lpn.status.in_(["AVAILABLE", "RESERVED", "PICKED", "PDI_OK"]))
    lpns = [{"lpn": l.lpn_no, "part": l.part_no, "qty": l.qty, "pallet": l.pallet_no, "status": l.status, "reserved_for": l.reserved_for,
             "picklist": l.picklist_no} for l in lq.all()]
    tags = [] if since else [{"tag": t.tag_no, "pallet": t.pallet_no, "status": t.status} for t in db.query(models.Tag).filter_by(plant_code=p.plant).all()]
    picklists = [{"picklist_no": k.picklist_no, "customer": k.customer_code, "type": k.pallet_type, "qty": k.qty, "status": k.status,
                  "dispatch_type": k.dispatch_type, "part_no": k.part_no, "part_qty": k.part_qty, "to_plant": k.to_plant,
                  "source": k.source, "load_point": k.load_point, "vehicle_no": k.vehicle_no, "gcs_no": k.gcs_no, "invoice_no": k.invoice_no,
                  "picked_qty": lpnsvc.picked_qty(db, k.picklist_no),
                  "scanned": db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).count()}
                 for k in db.query(models.PickList).filter(models.PickList.plant_code == p.plant,
                                                           models.PickList.status.in_(["OPEN", "SO_PENDING", "READY", "PDI_PENDING", "PDI_TXN_PENDING"])).all()]
    slips = [{"slip_no": sl.slip_no, "customer": sl.customer_code, "mode": sl.mode, "qty": sl.declared_qty, "status": sl.status,
              "pallets": [l.pallet_no for l in db.query(models.ReturnSlipLine).filter_by(slip_no=sl.slip_no, declared=True).all()]}
             for sl in db.query(models.ReturnSlip).filter(models.ReturnSlip.plant_code == p.plant, models.ReturnSlip.status != "CLOSED").all()]
    customers = [{"code": c.code, "name": c.name, "return_mode": c.return_mode} for c in db.query(models.Customer).filter_by(plant_code=p.plant, active=True).all()]
    plant = db.get(models.Plant, p.plant)
    return {"server_time": utcnow().isoformat(), "full": since is None, "plant": {"code": plant.code, "name": plant.name,
            "accept_other_plant_default": plant.accept_other_plant_default, "challan_source": plant.challan_source,
            "wms": lpnsvc.wms_status(db, p.plant)},
            "pallets": pallets, "lpns": lpns, "tags": tags, "picklists": picklists, "slips": slips, "customers": customers}


@router.get("/monitor")
def monitor(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("AUDIT_LOG") or p.has("REPORTS_ALL") or p.has("PLANT_USERS_ADMIN")):
        raise HTTPException(403, "Admin only")
    pl = p.scope_plant(plant)
    dq = db.query(models.Device)
    eq = db.query(models.Event).filter(models.Event.status != "APPLIED")
    if pl:
        dq = dq.filter(models.Device.plant_code == pl); eq = eq.filter(models.Event.plant_code == pl)
    devices = [{"device_id": d.device_id, "plant": d.plant_code, "last_seen": d.last_seen, "last_user": d.last_user,
                "app_version": d.app_version, "pending": d.pending_reported, "blocked": d.blocked} for d in dq.all()]
    exc = [{"event_id": e.event_id, "ts": e.received_ts, "device": e.device_id, "user": e.user_id, "plant": e.plant_code,
            "type": e.event_type, "status": e.status, "result": e.result, "payload": e.payload}
           for e in eq.order_by(models.Event.received_ts.desc()).limit(300).all()]
    return {"devices": devices, "exceptions": exc}


@router.post("/devices/{device_id}/block")
def block_device(device_id: str, blocked: bool = True, p: Principal = Depends(need("PLANT_USERS_ADMIN")), db: Session = Depends(get_db)):
    d = db.get(models.Device, device_id)
    if not d:
        raise HTTPException(404, "Device not found")
    p.require_plant(d.plant_code)
    d.blocked = blocked
    db.commit()
    return {"ok": True, "blocked": blocked}
