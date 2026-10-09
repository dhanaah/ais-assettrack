from datetime import datetime, timedelta
from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models, services, integration
from ..db import get_db
from ..security import current_user, Principal, need
from ..models import utcnow

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _rep(p: Principal):
    if not (p.has("REPORTS_PLANT") or p.has("REPORTS_ALL")):
        raise HTTPException(403, "Reports permission required")


@router.get("/availability")
def availability(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    return services.availability(db, p.scope_plant(plant))


@router.get("/customer-holding")
def holding(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    rows = services.customer_holding(db, p.scope_plant(plant))
    custs = {(c.plant_code, c.code): c for c in db.query(models.Customer).all()}
    plants = {x.code: x for x in db.query(models.Plant).all()}
    for r in rows:
        c = custs.get((r["plant"], r["customer"]))
        limit = (c.holding_limit_days if c and c.holding_limit_days else plants[r["plant"]].holding_days_default) if r["plant"] in plants else 30
        r["name"] = c.name if c else r["customer"]; r["limit_days"] = limit; r["overdue"] = r["max_days"] > limit
    return sorted(rows, key=lambda r: -r["qty"])


@router.get("/overdue")
def overdue(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    pl = p.scope_plant(plant)
    custs = {(c.plant_code, c.code): c for c in db.query(models.Customer).all()}
    plants = {x.code: x for x in db.query(models.Plant).all()}
    q = db.query(models.Pallet).filter(models.Pallet.status == "AT_CUSTOMER")
    if pl:
        q = q.filter(models.Pallet.home_plant == pl)
    out = []
    now = utcnow()
    for x in q.all():
        c = custs.get((x.home_plant, x.customer_code))
        limit = c.holding_limit_days if c and c.holding_limit_days else plants[x.home_plant].holding_days_default
        days = (now - x.dispatch_date).days if x.dispatch_date else 0
        if days > limit:
            out.append({"pallet_no": x.pallet_no, "plant": x.home_plant, "customer": x.customer_code, "customer_name": c.name if c else None,
                        "days": days, "limit": limit, "challan": x.challan_ref, "chargeable": c.chargeable if c else True})
    return sorted(out, key=lambda r: -r["days"])


@router.get("/pallet-history/{pallet_no}")
def pallet_history(pallet_no: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    tag, pal = services.resolve_tag(db, pallet_no)
    if not pal:
        raise HTTPException(404, "Pallet not found")
    p.require_plant(pal.home_plant) if p.plant and pal.location_plant != p.plant else None
    h = db.query(models.PalletHistory).filter_by(pallet_no=pal.pallet_no).order_by(models.PalletHistory.ts).all()
    return [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in h]


@router.get("/tag-history")
def tag_history(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    pl = p.scope_plant(plant)
    q = db.query(models.TagHistory, models.Pallet.home_plant).join(models.Pallet, models.Pallet.pallet_no == models.TagHistory.pallet_no)
    if pl:
        q = q.filter(models.Pallet.home_plant == pl)
    return [{"pallet_no": t.pallet_no, "ts": t.ts, "old_tag": t.old_tag, "new_tag": t.new_tag, "reason": t.reason, "user": t.user_id, "plant": hp}
            for t, hp in q.order_by(models.TagHistory.ts.desc()).limit(1000).all()]


@router.get("/tag-stock")
def tag_stock(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    pl = p.scope_plant(plant)
    q = db.query(models.Tag.plant_code, models.Tag.status, func.count()).group_by(models.Tag.plant_code, models.Tag.status)
    if pl:
        q = q.filter(models.Tag.plant_code == pl)
    out = {}
    for pc, st, c in q.all():
        out.setdefault(pc, {})[st] = c
    return out


@router.get("/audit")
def audit_log(plant: str | None = None, limit: int = 300, p: Principal = Depends(need("AUDIT_LOG")), db: Session = Depends(get_db)):
    pl = p.scope_plant(plant)
    q = db.query(models.AuditLog).order_by(models.AuditLog.ts.desc())
    if pl:
        q = q.filter(models.AuditLog.plant_code == pl)
    return [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in q.limit(min(limit, 2000)).all()]


@router.get("/integration")
def integration_status(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    pend = db.query(integration.RetryQueue).filter(integration.RetryQueue.status != "DONE").order_by(integration.RetryQueue.created.desc()).limit(200).all()
    log = db.query(integration.IntegrationLog).order_by(integration.IntegrationLog.ts.desc()).limit(100).all()
    return {"mode": integration.MODE,
            "retry_queue": [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in pend],
            "log": [{c.name: getattr(x, c.name) for c in x.__table__.columns if c.name not in ("request", "response")} for x in log]}


@router.post("/integration/retry")
def retry_now(p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    return integration.run_retries(db)


@router.get("/export/pallets.xlsx")
def export_pallets(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    from openpyxl import Workbook
    pl = p.scope_plant(plant)
    q = db.query(models.Pallet)
    if pl:
        q = q.filter((models.Pallet.home_plant == pl) | (models.Pallet.location_plant == pl))
    wb = Workbook(); ws = wb.active; ws.title = "Pallets"
    cols = ["pallet_no", "home_plant", "pallet_type", "current_tag", "status", "location_plant", "customer_code", "dispatch_date", "challan_ref", "picklist_no", "updated_at"]
    ws.append(cols)
    for x in q.order_by(models.Pallet.pallet_no).all():
        ws.append([getattr(x, c) for c in cols])
    bio = BytesIO(); wb.save(bio); bio.seek(0)
    return StreamingResponse(bio, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": "attachment; filename=pallets.xlsx"})


# ---------------------------------------------------------------- plant position (where are MY pallets?)
@router.get("/plant-position")
def plant_position(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """For a plant: own pallets at home (zone x loaded/empty), held at other plants, in transit, at customers,
    damaged / repair; and other plants' pallets held here. Plant admins are fixed to their plant."""
    _rep(p)
    pl = p.scope_plant(plant)
    if not pl:
        raise HTTPException(400, "Select a plant")
    now = utcnow()
    own = db.query(models.Pallet).filter(models.Pallet.home_plant == pl, models.Pallet.status != "DISCONTINUED").all()
    custs = {c.code: c for c in db.query(models.Customer).filter_by(plant_code=pl).all()}
    plant_obj = db.get(models.Plant, pl)
    hold_default = plant_obj.holding_days_default if plant_obj else 30
    at_home = {}
    other_plants, in_transit, at_customer, care, items = {}, {}, {}, {}, []

    def it(x, where, days=None):
        items.append({"pallet_no": x.pallet_no, "tag": x.current_tag, "status": x.status, "where": where, "zone": x.zone,
                      "load": x.load_state, "load_ref": x.load_ref, "ref": x.challan_ref or x.picklist_no,
                      "since": x.dispatch_date or x.updated_at, "days": days})
    for x in own:
        days = (now - x.dispatch_date).days if x.dispatch_date else None
        if x.status in ("DAMAGED", "UNDER_REPAIR"):
            care[x.status] = care.get(x.status, 0) + 1; it(x, x.status); continue
        if x.status == "IN_TRANSIT" or (x.status == "AT_CUSTOMER" and x.customer_code in {q.code for q in db.query(models.Plant).all()}):
            dest = x.customer_code or "?"
            in_transit[dest] = in_transit.get(dest, 0) + 1; it(x, f"in transit -> {dest}", days); continue
        if x.status in ("AT_CUSTOMER", "IN_RETURN"):
            c = custs.get(x.customer_code)
            lim = (c.holding_limit_days if c and c.holding_limit_days else hold_default)
            g = at_customer.setdefault(x.customer_code or "?", {"customer": x.customer_code, "name": c.name if c else "", "qty": 0,
                                                                "in_return": 0, "overdue": 0, "max_days": 0, "limit": lim})
            g["qty"] += 1; g["in_return"] += 1 if x.status == "IN_RETURN" else 0
            g["max_days"] = max(g["max_days"], days or 0); g["overdue"] += 1 if (days or 0) > lim else 0
            it(x, f"customer {x.customer_code}", days); continue
        if x.location_plant and x.location_plant != pl:
            g = other_plants.setdefault(x.location_plant, {"plant": x.location_plant, "qty": 0, "loaded": 0, "empty": 0, "statuses": {}})
            g["qty"] += 1; g["loaded" if x.load_state == "LOADED" else "empty"] += 1
            g["statuses"][x.status] = g["statuses"].get(x.status, 0) + 1
            it(x, f"at plant {x.location_plant}"); continue
        z = x.zone or "YARD"
        g = at_home.setdefault(z, {"zone": z, "LOADED": 0, "EMPTY": 0, "allocated": 0})
        g[x.load_state or "EMPTY"] += 1; g["allocated"] += 1 if x.status == "ALLOCATED" else 0
    foreign = {}
    for x in db.query(models.Pallet).filter(models.Pallet.location_plant == pl, models.Pallet.home_plant != pl).all():
        g = foreign.setdefault(x.home_plant, {"home_plant": x.home_plant, "qty": 0, "loaded_in_wip": 0, "empty_to_return": 0})
        g["qty"] += 1
        g["loaded_in_wip" if x.load_state == "LOADED" else "empty_to_return"] += 1
    summary = {"own_total": len(own), "at_home": sum(v["LOADED"] + v["EMPTY"] for v in at_home.values()),
               "at_other_plants": sum(v["qty"] for v in other_plants.values()), "in_transit": sum(in_transit.values()),
               "at_customers": sum(v["qty"] for v in at_customer.values()),
               "overdue": sum(v["overdue"] for v in at_customer.values()), "damaged_repair": sum(care.values()),
               "other_plants_pallets_here": sum(v["qty"] for v in foreign.values())}
    return {"plant": pl, "summary": summary, "at_home": list(at_home.values()), "at_other_plants": list(other_plants.values()),
            "in_transit": [{"destination": k, "qty": v} for k, v in in_transit.items()],
            "at_customers": sorted(at_customer.values(), key=lambda g: -g["overdue"]), "care": care,
            "other_plants_here": list(foreign.values()), "away_items": sorted(items, key=lambda i: -(i["days"] or 0))[:2000]}


# ---------------------------------------------------------------- live transactions
@router.get("/live")
def live(plant: str | None = None, after_id: int = 0, limit: int = 200, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Latest pallet movements (all channels) for the live view; poll with after_id."""
    _rep(p)
    q = db.query(models.PalletHistory).filter(models.PalletHistory.id > after_id)
    pl = p.scope_plant(plant)
    if pl:
        q = q.filter(models.PalletHistory.plant_code == pl)
    rows = q.order_by(models.PalletHistory.id.desc()).limit(min(limit, 500)).all()
    return [{"id": r.id, "ts": r.ts, "pallet_no": r.pallet_no, "event": r.event_type, "from": r.from_status, "to": r.to_status,
             "plant": r.plant_code, "customer": r.customer_code, "ref": r.ref_doc, "user": r.user_id, "device": r.device_id,
             "remarks": r.remarks} for r in rows]
