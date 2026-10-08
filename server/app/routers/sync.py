"""HHT sync: event push (idempotent) + reference pull + monitor.

Event types handled in Phase 1/2:
  PALLET_SCAN_DOCK   {picklist_no, scanned}            -> ALLOCATED, picklist line
  PALLET_UNSCAN_DOCK {picklist_no, scanned}            -> AVAILABLE
  PALLET_SCAN_YARD   {slip_no, scanned, accept_foreign, damaged} -> AVAILABLE / HELD / DAMAGED + slip line
  DAMAGE_MARK        {scanned, remarks}                -> DAMAGED
  TAG_REPLACE_REQ    {scanned, remarks}                -> logged only
  HEARTBEAT          {pending}                         -> device status
Any other type is stored with status EXCEPTION for review (forward compatible).
"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, services
from ..db import get_db
from ..security import current_user, Principal, need
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
        if t == "PALLET_SCAN_DOCK":
            p.require("DOCK_SCAN")
            pk = db.get(models.PickList, pl["picklist_no"])
            if not pk or pk.plant_code != plant:
                raise services.RuleError("Pick list not found for this plant")
            if pk.status not in ("OPEN", "SO_PENDING"):
                raise services.RuleError(f"Pick list is {pk.status}")
            pal = services.validate_scan_for_dispatch(db, pl["scanned"], plant)
            if db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no).count() >= pk.qty:
                raise services.RuleError("Pick list quantity already reached")
            services.move(db, pal, "ALLOCATED", event_type="DOCK_SCAN", user_id=p.user_id, device_id=e.device_id,
                          event_id=e.event_id, plant=plant, ref=pk.picklist_no)
            pal.picklist_no = pk.picklist_no
            db.add(models.PickListLine(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no, user_id=p.user_id, device_id=e.device_id))
            return "APPLIED", pal.pallet_no
        if t == "PALLET_UNSCAN_DOCK":
            p.require("DOCK_SCAN")
            tag, pal = services.resolve_tag(db, pl["scanned"])
            if not pal or pal.picklist_no != pl["picklist_no"] or pal.status != "ALLOCATED":
                raise services.RuleError("Pallet not on this pick list")
            pk = db.get(models.PickList, pl["picklist_no"])
            if pk.status not in ("OPEN", "SO_PENDING"):
                raise services.RuleError(f"Pick list is {pk.status}; cannot remove")
            db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no, pallet_no=pal.pallet_no).delete()
            services.move(db, pal, "AVAILABLE", event_type="DOCK_UNSCAN", user_id=p.user_id, device_id=e.device_id, event_id=e.event_id, plant=plant, ref=pk.picklist_no)
            return "APPLIED", pal.pallet_no
        if t == "PALLET_SCAN_YARD":
            p.require("YARD_SCAN")
            slip = db.get(models.ReturnSlip, pl["slip_no"]) if pl.get("slip_no") else None
            if slip and slip.plant_code != plant:
                raise services.RuleError("Slip belongs to another plant")
            tag, pal = services.resolve_tag(db, pl["scanned"])
            if not pal:
                if slip:
                    db.add(models.ReturnSlipLine(slip_no=slip.slip_no, pallet_no=pl["scanned"], declared=False, received=True, exception="UNKNOWN"))
                return "EXCEPTION", f"Unknown tag {pl['scanned']} quarantined"
            if pal.home_plant != plant:
                if not pl.get("accept_foreign"):
                    raise services.RuleError(f"Foreign pallet {pal.pallet_no} ({pal.home_plant}) - not accepted")
                services.move(db, pal, "HELD", event_type="YARD_SCAN_FOREIGN", user_id=p.user_id, device_id=e.device_id,
                              event_id=e.event_id, plant=plant, ref=slip.slip_no if slip else None, force=True)
                if slip:
                    db.add(models.ReturnSlipLine(slip_no=slip.slip_no, pallet_no=pal.pallet_no, declared=False, received=True, exception="FOREIGN"))
                return "EXCEPTION", f"{pal.pallet_no} HELD for {pal.home_plant}"
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
            if pl.get("damaged") and slip:
                db.query(models.ReturnSlipLine).filter_by(slip_no=slip.slip_no, pallet_no=pal.pallet_no).update({"exception": "DAMAGED"})
            return ("EXCEPTION" if exc or pl.get("damaged") else "APPLIED"), f"{pal.pallet_no} {to}" + (f" ({exc})" if exc else "")
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
def push(body: PushIn, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
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
        sp = db.begin_nested()
        status, msg = _apply(db, p, e)
        if status == "REJECTED":
            sp.rollback()
        else:
            sp.commit()
        db.add(models.Event(event_id=e.event_id, device_id=e.device_id, user_id=p.user_id, plant_code=p.plant, event_type=e.event_type,
                            payload=json.dumps(e.payload, default=str), local_ts=e.local_ts, app_version=e.app_version,
                            offline=e.offline, status=status, result=msg[:300]))
        results.append({"event_id": e.event_id, "status": status, "result": msg})
        if not dev:
            dev = models.Device(device_id=e.device_id, plant_code=p.plant); db.add(dev)
        dev.last_seen = utcnow(); dev.last_user = p.user_id; dev.app_version = e.app_version
        if e.event_type == "HEARTBEAT":
            dev.pending_reported = int(e.payload.get("pending", 0))
        db.commit()
    return {"results": results, "server_time": utcnow().isoformat()}


@router.get("/pull")
def pull(since: datetime | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Reference cache for the HHT. `since` = last pull time -> delta of pallets; masters always full (small)."""
    if not p.plant:
        raise HTTPException(400, "Only plant users pull")
    pq = db.query(models.Pallet).filter((models.Pallet.home_plant == p.plant) | (models.Pallet.location_plant == p.plant))
    if since:
        pq = pq.filter(models.Pallet.updated_at >= since)
    pallets = [{"pallet_no": x.pallet_no, "tag": x.current_tag, "home": x.home_plant, "type": x.pallet_type, "status": x.status,
                "customer": x.customer_code, "picklist": x.picklist_no} for x in pq.all()]
    tags = [] if since else [{"tag": t.tag_no, "pallet": t.pallet_no, "status": t.status} for t in db.query(models.Tag).filter_by(plant_code=p.plant).all()]
    picklists = [{"picklist_no": k.picklist_no, "customer": k.customer_code, "type": k.pallet_type, "qty": k.qty, "status": k.status,
                  "scanned": db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).count()}
                 for k in db.query(models.PickList).filter(models.PickList.plant_code == p.plant, models.PickList.status.in_(["OPEN", "SO_PENDING", "READY"])).all()]
    slips = [{"slip_no": sl.slip_no, "customer": sl.customer_code, "mode": sl.mode, "qty": sl.declared_qty, "status": sl.status,
              "pallets": [l.pallet_no for l in db.query(models.ReturnSlipLine).filter_by(slip_no=sl.slip_no, declared=True).all()]}
             for sl in db.query(models.ReturnSlip).filter(models.ReturnSlip.plant_code == p.plant, models.ReturnSlip.status != "CLOSED").all()]
    customers = [{"code": c.code, "name": c.name, "return_mode": c.return_mode} for c in db.query(models.Customer).filter_by(plant_code=p.plant, active=True).all()]
    plant = db.get(models.Plant, p.plant)
    return {"server_time": utcnow().isoformat(), "full": since is None, "plant": {"code": plant.code, "name": plant.name,
            "accept_other_plant_default": plant.accept_other_plant_default, "challan_source": plant.challan_source},
            "pallets": pallets, "tags": tags, "picklists": picklists, "slips": slips, "customers": customers}


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
