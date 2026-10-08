"""Activity log API: filtered query, summary, Excel export, HHT device-activity intake."""
from datetime import datetime, timedelta
from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from ..db import get_db
from ..security import current_user, Principal
from ..activity import ActivityLog, record
from ..models import utcnow

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


def _allowed(p: Principal):
    if not (p.has("AUDIT_LOG") or p.has("REPORTS_ALL") or p.has("PLANT_USERS_ADMIN") or p.has("REPORTS_PLANT")):
        raise HTTPException(403, "Activity log: admin or reports permission required")


def _query(db, p, user, plant, device, action, source, ref, q, frm, to, status):
    qry = db.query(ActivityLog)
    pl = p.scope_plant(plant)
    if pl:
        qry = qry.filter(or_(ActivityLog.plant_code == pl, ActivityLog.plant_code.is_(None) & ActivityLog.user_id.is_(None)))
        if not p.has("REPORTS_ALL") and not p.has("AUDIT_LOG"):
            qry = qry.filter(ActivityLog.plant_code == pl)
    if user: qry = qry.filter(ActivityLog.user_id == user)
    if device: qry = qry.filter(ActivityLog.device_id == device)
    if action: qry = qry.filter(ActivityLog.action == action)
    if source: qry = qry.filter(ActivityLog.source == source)
    if ref: qry = qry.filter(ActivityLog.ref.like(f"%{ref}%"))
    if q: qry = qry.filter(or_(ActivityLog.result.like(f"%{q}%"), ActivityLog.detail.like(f"%{q}%"), ActivityLog.ref.like(f"%{q}%"), ActivityLog.user_id.like(f"%{q}%")))
    if frm: qry = qry.filter(ActivityLog.ts >= frm)
    if to: qry = qry.filter(ActivityLog.ts < to + timedelta(days=1))
    if status == "ok": qry = qry.filter(ActivityLog.status < 400)
    if status == "error": qry = qry.filter(or_(ActivityLog.status >= 400, ActivityLog.status == 0))
    return qry


@router.get("")
def list_activity(user: str | None = None, plant: str | None = None, device: str | None = None, action: str | None = None, source: str | None = None,
                  ref: str | None = None, q: str | None = None, frm: datetime | None = None, to: datetime | None = None, status: str | None = None,
                  limit: int = Query(300, le=5000), offset: int = 0, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _allowed(p)
    qry = _query(db, p, user, plant, device, action, source, ref, q, frm, to, status)
    total = qry.count()
    rows = qry.order_by(ActivityLog.ts.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows]}


@router.get("/summary")
def summary(days: int = 7, plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _allowed(p)
    since = utcnow() - timedelta(days=days)
    base = _query(db, p, None, plant, None, None, None, None, None, since, None, None)
    by_action = base.with_entities(ActivityLog.action, func.count()).group_by(ActivityLog.action).order_by(func.count().desc()).all()
    by_user = base.with_entities(ActivityLog.user_id, func.count(), func.max(ActivityLog.ts)).group_by(ActivityLog.user_id).order_by(func.count().desc()).limit(25).all()
    by_device = base.filter(ActivityLog.device_id.isnot(None)).with_entities(ActivityLog.device_id, func.count(), func.max(ActivityLog.ts)).group_by(ActivityLog.device_id).order_by(func.count().desc()).limit(25).all()
    errors = base.filter(or_(ActivityLog.status >= 400, ActivityLog.status == 0)).count()
    by_source = base.with_entities(ActivityLog.source, func.count()).group_by(ActivityLog.source).all()
    return {"days": days, "total": base.count(), "errors": errors, "by_source": dict(by_source),
            "by_action": [{"action": a, "count": c} for a, c in by_action],
            "by_user": [{"user": u, "count": c, "last": t} for u, c, t in by_user],
            "by_device": [{"device": d, "count": c, "last": t} for d, c, t in by_device]}


@router.get("/actions")
def actions(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _allowed(p)
    return sorted(a for (a,) in db.query(ActivityLog.action).distinct().all())


@router.get("/export.xlsx")
def export(user: str | None = None, plant: str | None = None, device: str | None = None, action: str | None = None, source: str | None = None,
           ref: str | None = None, q: str | None = None, frm: datetime | None = None, to: datetime | None = None, status: str | None = None,
           p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _allowed(p)
    from openpyxl import Workbook
    rows = _query(db, p, user, plant, device, action, source, ref, q, frm, to, status).order_by(ActivityLog.ts.desc()).limit(50000).all()
    wb = Workbook(); ws = wb.active; ws.title = "Activity"
    cols = ["ts", "source", "user_id", "plant_code", "device_id", "action", "entity", "ref", "status", "result", "duration_ms", "ip", "app_version", "detail"]
    ws.append(cols)
    for r in rows:
        ws.append([getattr(r, c) for c in cols])
    bio = BytesIO(); wb.save(bio); bio.seek(0)
    record(db, source="WEB", user_id=p.user_id, plant_code=p.plant, action="EXPORT", entity="activity", ref=f"{len(rows)} rows", status=200, result="ok")
    db.commit()
    return StreamingResponse(bio, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": "attachment; filename=activity_log.xlsx"})


class DeviceActivity(BaseModel):
    ts: datetime
    action: str                 # SCREEN_OPEN, SCAN_OFFLINE, PRINT_SLIP, PRINT_CHALLAN, LOGIN_LOCAL, SYNC, ERROR ...
    ref: str | None = None
    result: str | None = None
    detail: str | None = None


class DeviceActivityIn(BaseModel):
    device_id: str
    app_version: str | None = None
    items: list[DeviceActivity]


@router.post("/device")
def device_activity(body: DeviceActivityIn, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """HHT reports its on-device actions (works offline; batched on sync)."""
    n = 0
    for it in body.items[:1000]:
        record(db, ts=it.ts, source="HHT", user_id=p.user_id, plant_code=p.plant, device_id=body.device_id, action=it.action[:60], entity="device",
               ref=(it.ref or "")[:80] or None, status=0, result=(it.result or "")[:300] or None, detail=(it.detail or "")[:4000] or None, app_version=body.app_version)
        n += 1
    db.commit()
    return {"accepted": n}
