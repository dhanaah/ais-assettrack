"""Customer reminder / escalation emails: preview, run now, log. Developed by DT"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from .. import reminders, models
from ..db import get_db
from ..security import current_user, Principal, audit

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])


def _rep(p: Principal):
    if not (p.has("REPORTS_PLANT") or p.has("REPORTS_ALL")):
        raise HTTPException(403, "Reports permission required")


@router.get("")
def preview(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    pl = p.scope_plant(plant)
    items = reminders.build(db, pl)
    smtp = {"configured": reminders.configured(), "host": reminders.SMTP["host"] or None, "sender": reminders.SMTP["sender"] or None,
            "run_hour": reminders.RUN_HOUR}
    last = db.get(models.Setting, "reminders_last_run")
    return {"smtp": smtp, "last_run": last.value if last else None,
            "items": [{k: v for k, v in i.items() if k != "pallets"} | {"pallet_list": [r["pallet_no"] for r in i["pallets"] if r["overdue"]][:50]} for i in items]}


@router.get("/preview/{plant}/{customer}", response_class=HTMLResponse)
def preview_mail(plant: str, customer: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p); p.require_plant(plant)
    for i in reminders.build(db, plant, force=True):
        if i["customer"] == customer:
            return HTMLResponse(reminders.render(i))
    raise HTTPException(404, "Nothing due for this customer")


@router.post("/run")
def run_now(request: Request, plant: str | None = None, force: bool = False, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("INTEGRATION_CONFIG") or p.has("PLANT_USERS_ADMIN") or p.has("LOGISTICS_APPROVE")):
        raise HTTPException(403, "Admin / logistics permission required")
    pl = p.scope_plant(plant)
    res = reminders.run(db, pl, force=force)
    audit(db, p, "REMINDERS_RUN", "reminders", pl or "ALL", None, res, request); db.commit()
    return res


@router.get("/log")
def email_log(plant: str | None = None, limit: int = 200, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    pl = p.scope_plant(plant)
    q = db.query(reminders.EmailLog).order_by(reminders.EmailLog.ts.desc())
    if pl:
        q = q.filter(reminders.EmailLog.plant_code == pl)
    return [{c.name: getattr(x, c.name) for c in x.__table__.columns if c.name != "body"} for x in q.limit(min(limit, 1000)).all()]


@router.get("/log/{id}", response_class=HTMLResponse)
def email_body(id: int, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _rep(p)
    x = db.get(reminders.EmailLog, id)
    if not x:
        raise HTTPException(404, "Not found")
    p.require_plant(x.plant_code)
    return HTMLResponse(x.body or "<p>(no body)</p>")
