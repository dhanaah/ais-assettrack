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
