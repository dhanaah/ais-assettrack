"""Management dashboard data, Excel export of every report, daily exception report (print). Developed by DT"""
from datetime import datetime, timedelta
from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models, services, config, lpn as lpnsvc
from ..db import get_db
from ..security import current_user, Principal
from ..models import utcnow
from . import reports as rep

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

RETURN_EVENTS = ("YARD_SCAN", "RETURN_SLIP", "AUTO_RECEIVE_MISSED_SCAN", "RETURN_SLIP_MISSED_DISPATCH", "YARD_SCAN_FOREIGN")


def _rep(p: Principal):
    if not (p.has("REPORTS_PLANT") or p.has("REPORTS_ALL")):
        raise HTTPException(403, "Reports permission required")


def _week(d: datetime) -> str:
    return (d - timedelta(days=d.weekday())).strftime("%d %b")


@router.get("/dashboard")
def dashboard(plant: str | None = None, weeks: int = 12, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """One call for the management dashboard: KPIs, position by plant, customer holding by age, dispatch / return trend,
    turnaround, missed scans by role, open pick lists. Plant users are fixed to their plant."""
    _rep(p)
    pl = p.scope_plant(plant)
    now = utcnow()
    plants = {x.code: x for x in db.query(models.Plant).filter_by(active=True).all()}
    custs = {(c.plant_code, c.code): c for c in db.query(models.Customer).all()}
    q = db.query(models.Pallet).filter(models.Pallet.status != "DISCONTINUED")
    if pl:
        q = q.filter((models.Pallet.home_plant == pl) | (models.Pallet.location_plant == pl))
    pallets = q.all()

    # ---- position by (home) plant
    pos = {}
    hold_age = {}
    kp = {"total": 0, "home": 0, "at_customer": 0, "overdue": 0, "away_plants": 0, "in_transit": 0, "damaged": 0, "loaded": 0, "empty": 0}
    for x in pallets:
        if pl and x.home_plant != pl:
            continue
        g = pos.setdefault(x.home_plant, {"plant": x.home_plant, "home": 0, "at_customer": 0, "other_plant": 0, "in_transit": 0, "damaged": 0})
        kp["total"] += 1
        kp["loaded" if x.load_state == "LOADED" else "empty"] += 1
        days = (now - x.dispatch_date).days if x.dispatch_date else 0
        if x.status in ("DAMAGED", "UNDER_REPAIR"):
            g["damaged"] += 1; kp["damaged"] += 1
        elif x.status == "IN_TRANSIT" or (x.status == "AT_CUSTOMER" and x.customer_code in plants):
            g["in_transit"] += 1; kp["in_transit"] += 1
        elif x.status in ("AT_CUSTOMER", "IN_RETURN"):
            g["at_customer"] += 1; kp["at_customer"] += 1
            c = custs.get((x.home_plant, x.customer_code))
            lim = c.holding_limit_days if c and c.holding_limit_days else (plants[x.home_plant].holding_days_default if x.home_plant in plants else 30)
            h = hold_age.setdefault((x.home_plant, x.customer_code), {"plant": x.home_plant, "customer": x.customer_code, "name": c.name if c else (x.customer_code or "?"),
                                                                      "b0_30": 0, "b31_60": 0, "b61": 0, "qty": 0, "overdue": 0, "limit": lim, "max_days": 0})
            h["qty"] += 1; h["b0_30" if days <= 30 else "b31_60" if days <= 60 else "b61"] += 1
            h["max_days"] = max(h["max_days"], days)
            if days > lim:
                h["overdue"] += 1; kp["overdue"] += 1
        elif x.location_plant and x.location_plant != x.home_plant:
            g["other_plant"] += 1; kp["away_plants"] += 1
        else:
            g["home"] += 1; kp["home"] += 1
    holding = sorted(hold_age.values(), key=lambda h: (-h["overdue"], -h["qty"]))[:12]

    # ---- trends from pallet history (last N weeks)
    since = now - timedelta(weeks=weeks)
    hq = db.query(models.PalletHistory).filter(models.PalletHistory.ts >= since)
    if pl:
        hq = hq.filter(models.PalletHistory.plant_code == pl)
    weeks_idx = [_week(since + timedelta(weeks=i + 1)) for i in range(weeks)]
    trend = {w: {"week": w, "dispatched": 0, "returned": 0} for w in weeks_idx}
    for h in hq.all():
        w = _week(h.ts)
        if w not in trend:
            continue
        if h.to_status == "AT_CUSTOMER" and h.from_status == "ALLOCATED":
            trend[w]["dispatched"] += 1
        elif h.from_status in ("AT_CUSTOMER", "IN_RETURN", "IN_TRANSIT") and h.to_status in ("AVAILABLE", "HELD", "DAMAGED"):
            trend[w]["returned"] += 1

    # ---- turnaround: days from dispatch (ALLOCATED -> AT_CUSTOMER) to return, by month of return (last 6 months)
    tq = db.query(models.PalletHistory).filter(models.PalletHistory.ts >= now - timedelta(days=270))
    if pl:
        tq = tq.filter(models.PalletHistory.plant_code == pl)
    out_at = {}
    turn = {}
    for h in tq.order_by(models.PalletHistory.ts).all():
        if h.to_status == "AT_CUSTOMER" and h.from_status == "ALLOCATED":
            out_at[h.pallet_no] = h.ts
        elif h.from_status in ("AT_CUSTOMER", "IN_RETURN") and h.to_status in ("AVAILABLE", "HELD", "DAMAGED") and h.pallet_no in out_at:
            d = (h.ts - out_at.pop(h.pallet_no)).days
            m = h.ts.strftime("%b %y")
            t = turn.setdefault(m, {"month": m, "n": 0, "days": 0, "max": 0, "_k": h.ts.strftime("%Y%m")})
            t["n"] += 1; t["days"] += d; t["max"] = max(t["max"], d)
    turnaround = [{"month": t["month"], "cycles": t["n"], "avg_days": round(t["days"] / t["n"], 1), "max_days": t["max"]}
                  for t in sorted(turn.values(), key=lambda t: t["_k"])[-6:]]

    # ---- missed scans: open by responsible role, weekly trend
    mq = db.query(models.ScanMiss).filter(models.ScanMiss.ts >= since)
    if pl:
        mq = mq.filter(models.ScanMiss.plant_code == pl)
    roles = {}
    mtrend = {w: {"week": w, "count": 0} for w in weeks_idx}
    open_miss = 0
    for m in mq.all():
        r = m.responsible_role or "?"
        g = roles.setdefault(r, {"role": r, "open": 0, "total": 0})
        g["total"] += 1
        if not m.resolved:
            g["open"] += 1; open_miss += 1
        w = _week(m.ts)
        if w in mtrend:
            mtrend[w]["count"] += 1

    # ---- documents
    pq = db.query(models.PickList.status, func.count()).filter(models.PickList.status.notin_(["DISPATCHED", "CANCELLED"]))
    if pl:
        pq = pq.filter(models.PickList.plant_code == pl)
    picklists = [{"status": s, "count": c} for s, c in pq.group_by(models.PickList.status).all()]
    sq = db.query(models.ReturnSlip).filter(models.ReturnSlip.status != "CLOSED")
    if pl:
        sq = sq.filter(models.ReturnSlip.plant_code == pl)
    kp["open_picklists"] = sum(x["count"] for x in picklists)
    kp["open_slips"] = sq.count()
    kp["open_misses"] = open_miss
    kp["wms"] = lpnsvc.wms_status(db, pl) if pl else None
    kp["plants"] = len(pos)
    return {"plant": pl, "as_of": now, "kpis": kp, "position": sorted(pos.values(), key=lambda g: g["plant"]), "holding": holding,
            "trend": list(trend.values()), "turnaround": turnaround, "misses_by_role": sorted(roles.values(), key=lambda g: -g["open"]),
            "misses_trend": list(mtrend.values()), "picklists": picklists}


# ---------------------------------------------------------------- Excel export of every report
def _rows_pallets(db, p, pl):
    q = db.query(models.Pallet)
    if pl:
        q = q.filter((models.Pallet.home_plant == pl) | (models.Pallet.location_plant == pl))
    cols = ["pallet_no", "home_plant", "pallet_type", "current_tag", "status", "location_plant", "zone", "load_state", "load_ref",
            "customer_code", "dispatch_date", "challan_ref", "picklist_no", "updated_at"]
    return [{c: getattr(x, c) for c in cols} for x in q.order_by(models.Pallet.pallet_no).all()]


def _rows_misses(db, p, pl):
    q = db.query(models.ScanMiss).order_by(models.ScanMiss.ts.desc())
    if pl:
        q = q.filter(models.ScanMiss.plant_code == pl)
    return [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in q.limit(5000).all()]


def _rows_picklists(db, p, pl):
    q = db.query(models.PickList).order_by(models.PickList.created_at.desc())
    if pl:
        q = q.filter(models.PickList.plant_code == pl)
    out = []
    for k in q.limit(5000).all():
        d = {c.name: getattr(k, c.name) for c in k.__table__.columns}
        d["pallets_scanned"] = db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).count()
        out.append(d)
    return out


def _rows_slips(db, p, pl):
    q = db.query(models.ReturnSlip).order_by(models.ReturnSlip.created_at.desc())
    if pl:
        q = q.filter(models.ReturnSlip.plant_code == pl)
    out = []
    for s in q.limit(5000).all():
        d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
        lines = db.query(models.ReturnSlipLine).filter_by(slip_no=s.slip_no).all()
        d["received"] = sum(1 for l in lines if l.received); d["exceptions"] = sum(1 for l in lines if l.exception and not l.resolved)
        out.append(d)
    return out


def _rows_lpns(db, p, pl):
    q = db.query(models.Lpn).order_by(models.Lpn.part_no, models.Lpn.lpn_no)
    if pl:
        q = q.filter(models.Lpn.plant_code == pl)
    return [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in q.limit(20000).all()]


def _rows_history(db, p, pl, days=90):
    q = db.query(models.PalletHistory).filter(models.PalletHistory.ts >= utcnow() - timedelta(days=days)).order_by(models.PalletHistory.ts.desc())
    if pl:
        q = q.filter(models.PalletHistory.plant_code == pl)
    return [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in q.limit(50000).all()]


EXPORTS = {
    "pallets": ("Pallets", _rows_pallets),
    "customer-holding": ("Customer holding", lambda db, p, pl: rep.holding(pl, p, db)),
    "overdue": ("Overdue at customers", lambda db, p, pl: rep.overdue(pl, p, db)),
    "plant-position": ("Plant position", lambda db, p, pl: rep.plant_position(pl, p, db)["away_items"]),
    "missed-scans": ("Missed scans", _rows_misses),
    "picklists": ("Pick lists", _rows_picklists),
    "return-slips": ("Return slips", _rows_slips),
    "lpn-stock": ("LPN stock", _rows_lpns),
    "movements": ("Movements 90 days", _rows_history),
    "dashboard-holding": ("Holding by age", lambda db, p, pl: dashboard(pl, 12, p, db)["holding"]),
}


@router.get("/reports/export/{name}.xlsx")
def export_report(name: str, plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Any report as an Excel file: /reports/export/<name>.xlsx?plant=  (names: see EXPORTS)."""
    _rep(p)
    if name not in EXPORTS:
        raise HTTPException(404, f"Unknown report. Available: {', '.join(EXPORTS)}")
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    pl = p.scope_plant(plant)
    title, fn = EXPORTS[name]
    rows = fn(db, p, pl)
    wb = Workbook(); ws = wb.active; ws.title = title[:30]
    ws.append([f"{config.APP_NAME} - {title}" + (f" - plant {pl}" if pl else " - all plants"), "", f"as of {utcnow():%d-%m-%Y %H:%M} UTC", "", config.DEVELOPER])
    ws["A1"].font = Font(bold=True, size=12)
    cols = list(rows[0].keys()) if rows else ["(no data)"]
    cols = [c for c in cols if not isinstance(rows[0].get(c), (dict, list))] if rows else cols
    ws.append(cols)
    for cell in ws[2]:
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="1E3A8A")
    for r in rows:
        ws.append([(v.replace(tzinfo=None) if isinstance(v, datetime) else v) for v in (r.get(c) for c in cols)])
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = min(40, max(10, len(str(c)) + 2, *[len(str(r.get(c) or "")) + 2 for r in rows[:200]]))
    ws.freeze_panes = "A3"; ws.auto_filter.ref = f"A2:{get_column_letter(len(cols))}{len(rows) + 2}"
    bio = BytesIO(); wb.save(bio); bio.seek(0)
    fname = f"AssetTrack_{name}_{pl or 'ALL'}_{utcnow():%Y%m%d}.xlsx"
    return StreamingResponse(bio, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})


# ---------------------------------------------------------------- daily exception report (print)
@router.get("/reports/daily-exceptions", response_class=HTMLResponse)
def daily_exceptions(plant: str | None = None, date: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """A4 page for the plant's morning meeting: yesterday's missed scans, rejected HHT events, short / exception return slips,
    overdue customers, stale WMS, pick lists stuck. ?date=YYYY-MM-DD (default: today, covering the last 24 h)."""
    _rep(p)
    pl = p.scope_plant(plant)
    if not pl:
        raise HTTPException(400, "Select a plant")
    try:
        day = datetime.strptime(date, "%Y-%m-%d") if date else utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    frm, to = day - timedelta(days=1), day + timedelta(days=1)
    plant_obj = db.get(models.Plant, pl)
    misses = db.query(models.ScanMiss).filter(models.ScanMiss.plant_code == pl, models.ScanMiss.ts >= frm, models.ScanMiss.ts < to).order_by(models.ScanMiss.ts).all()
    rejected = db.query(models.Event).filter(models.Event.plant_code == pl, models.Event.status == "REJECTED",
                                             models.Event.received_ts >= frm, models.Event.received_ts < to).order_by(models.Event.received_ts).all()
    slips = db.query(models.ReturnSlip).filter(models.ReturnSlip.plant_code == pl, models.ReturnSlip.status != "CLOSED",
                                               models.ReturnSlip.created_at < to).all()
    slip_rows = []
    for s in slips:
        lines = db.query(models.ReturnSlipLine).filter_by(slip_no=s.slip_no).all()
        exc = [l for l in lines if l.exception and not l.resolved]
        short = [l for l in lines if l.declared and not l.received]
        if exc or short or (utcnow() - s.created_at).days >= 2:
            slip_rows.append((s, len(short), len(exc)))
    overdue = [r for r in rep.overdue(pl, p, db)]
    stuck = db.query(models.PickList).filter(models.PickList.plant_code == pl, models.PickList.status.notin_(["DISPATCHED", "CANCELLED"]),
                                             models.PickList.created_at < utcnow() - timedelta(days=2)).all()
    wms = lpnsvc.wms_status(db, pl)
    open_total = db.query(models.ScanMiss).filter(models.ScanMiss.plant_code == pl, models.ScanMiss.resolved == False).count()

    def esc(v):
        import html
        return html.escape("" if v is None else str(v))

    def tbl(head, rows):
        if not rows:
            return "<p class='none'>None</p>"
        return "<table><tr>" + "".join(f"<th>{esc(h)}</th>" for h in head) + "</tr>" + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows) + "</table>"
    css = """@page{size:A4;margin:12mm}body{font-family:Arial,Helvetica,sans-serif;font-size:11.5px;color:#111;margin:0}
h1{font-size:16px;margin:0 0 2px}h2{font-size:13px;margin:14px 0 4px;border-bottom:1px solid #1e3a8a;color:#1e3a8a}
.top{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #1e3a8a;padding-bottom:6px}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #bbb;padding:3px 5px;text-align:left;vertical-align:top}th{background:#eef2ff}
.kpis{display:flex;gap:8px;margin-top:8px}.k{flex:1;border:1px solid #cbd5e1;border-radius:6px;padding:6px;text-align:center}.k b{font-size:18px;display:block}
.k.bad{border-color:#dc2626;background:#fef2f2}.none{color:#666;margin:2px 0}.foot{margin-top:14px;font-size:10px;color:#666;display:flex;justify-content:space-between}
@media print{button{display:none}}"""
    kpi = lambda n, label, bad=False: f"<div class='k{' bad' if bad else ''}'><b>{n}</b>{label}</div>"
    html_out = f"""<!doctype html><html><head><meta charset="utf-8"><title>Daily exceptions {pl} {day:%d-%m-%Y}</title><style>{css}</style></head><body>
<div class="top"><div><h1>{config.APP_NAME} - Daily Exception Report</h1><div>Plant <b>{esc(pl)} {esc(plant_obj.name if plant_obj else '')}</b> · covering {frm:%d-%m-%Y} 00:00 to {to:%d-%m-%Y} 00:00 (UTC)</div></div>
<div><button onclick="print()">Print</button></div></div>
<div class="kpis">{kpi(len(misses), 'missed scans (period)', bool(misses))}{kpi(open_total, 'missed scans still open', open_total > 0)}{kpi(len(rejected), 'HHT scans rejected', bool(rejected))}
{kpi(len(slip_rows), 'return slips with issues', bool(slip_rows))}{kpi(len(overdue), 'pallets overdue at customers', bool(overdue))}{kpi(len(stuck), 'pick lists open > 2 days', bool(stuck))}
{kpi((str(wms['age_hours']) + ' h') if wms['age_hours'] is not None else 'never', 'WMS stock age', wms['stale'])}</div>
<h2>1. Missed scans detected</h2>{tbl(['Time', 'Pallet / LPN', 'Found at', 'Missed point', 'Responsible', 'Action', 'Message', 'Resolved'],
    [(f"{m.ts:%d-%m %H:%M}", m.pallet_no or m.lpn_no, m.detected_at, m.missed_point, m.responsible_role, m.action, m.message, 'yes' if m.resolved else '') for m in misses])}
<h2>2. HHT scans rejected by the server</h2>{tbl(['Time', 'Device', 'User', 'Type', 'Reason'], [(f"{e.received_ts:%d-%m %H:%M}", e.device_id, e.user_id, e.event_type, e.result) for e in rejected])}
<h2>3. Return slips with short / exception lines or open for 2+ days</h2>{tbl(['Slip', 'Customer', 'Mode', 'Status', 'Created', 'Short', 'Exceptions'],
    [(s.slip_no, s.customer_code, s.mode, s.status, f"{s.created_at:%d-%m-%Y}", sh, ex) for s, sh, ex in slip_rows])}
<h2>4. Pallets overdue at customers</h2>{tbl(['Pallet', 'Customer', 'Name', 'Days', 'Limit', 'Challan'], [(r['pallet_no'], r['customer'], r['customer_name'], r['days'], r['limit'], r['challan']) for r in overdue[:150]])}
{('<p class="none">… and ' + str(len(overdue) - 150) + ' more (see Reports > Overdue)</p>') if len(overdue) > 150 else ''}
<h2>5. Pick lists open for more than 2 days</h2>{tbl(['Pick list', 'Type', 'Customer', 'Status', 'Created', 'Pallets'], [(k.picklist_no, k.dispatch_type, k.customer_code, k.status, f"{k.created_at:%d-%m-%Y}", k.qty) for k in stuck])}
<div class="foot"><span>Printed by {esc(p.user_id)} on {utcnow():%d-%m-%Y %H:%M} UTC</span><span>{config.DEVELOPER} · v{config.APP_VERSION}</span></div>
</body></html>"""
    return HTMLResponse(html_out)
