"""Pick lists (dispatch) and return slips (return) - document level operations.
EBS SO posting and GCS calls are stubs behind integration.py; they queue for retry."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, services, integration
from ..db import get_db
from ..security import current_user, need, Principal, audit, verify_supervisor_pin
from ..models import utcnow

router = APIRouter(prefix="/api/v1", tags=["documents"])


def row(o):
    return {c.name: getattr(o, c.name) for c in o.__table__.columns}


# ---------------------------------------------------------------- pick lists
class PickListIn(BaseModel):
    customer_code: str
    qty: int
    pallet_type: str | None = None
    transporter_code: str | None = None
    picklist_no: str | None = None     # device-generated number allowed (offline)
    remarks: str | None = None


@router.get("/picklists")
def list_picklists(status: str | None = None, plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.PickList).order_by(models.PickList.created_at.desc())
    pl = p.scope_plant(plant)
    if pl:
        q = q.filter(models.PickList.plant_code == pl)
    if status:
        q = q.filter(models.PickList.status == status)
    out = []
    for k in q.limit(500).all():
        d = row(k); d["scanned"] = db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).count(); out.append(d)
    return out


@router.get("/picklists/{no}")
def get_picklist(no: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    lines = db.query(models.PickListLine).filter_by(picklist_no=no).order_by(models.PickListLine.scanned_at).all()
    return {"picklist": row(k), "lines": [row(l) for l in lines]}


@router.post("/picklists")
def create_picklist(body: PickListIn, request: Request, p: Principal = Depends(need("PICKLIST_CREATE")), db: Session = Depends(get_db)):
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    cust = db.query(models.Customer).filter_by(code=body.customer_code, plant_code=p.plant, active=True).first()
    if not cust:
        raise HTTPException(400, "Customer not mapped to this plant")
    if body.qty <= 0:
        raise HTTPException(400, "Qty must be > 0")
    avail = db.query(models.Pallet).filter_by(home_plant=p.plant, status="AVAILABLE")
    if body.pallet_type:
        avail = avail.filter_by(pallet_type=body.pallet_type)
    n_av = avail.count()
    if n_av < body.qty:
        raise HTTPException(400, f"Only {n_av} pallets available" + (f" of type {body.pallet_type}" if body.pallet_type else ""))
    no = body.picklist_no or services.doc_number(db, p.plant, "PL")
    if db.get(models.PickList, no):
        raise HTTPException(400, "Pick list number exists")
    k = models.PickList(picklist_no=no, plant_code=p.plant, customer_code=cust.code, transporter_code=body.transporter_code,
                        pallet_type=body.pallet_type, qty=body.qty, created_by=p.user_id, remarks=body.remarks, status="SO_PENDING")
    db.add(k); db.flush()
    ok, so, msg = integration.post_sale_order(db, k)
    if ok:
        k.so_number = so; k.status = "OPEN"
    else:
        integration.queue_retry(db, "EBS_SO", k.picklist_no, msg)
    audit(db, p, "PICKLIST_CREATE", "picklist", no, None, body.model_dump(), request)
    db.commit()
    return row(k) | {"so_message": msg}


class QtyIn(BaseModel):
    qty: int
    reason: str
    supervisor_pin: str


@router.post("/picklists/{no}/reduce-qty")
def reduce_qty(no: str, body: QtyIn, request: Request, p: Principal = Depends(need("PICKLIST_CREATE")), db: Session = Depends(get_db)):
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    sup = verify_supervisor_pin(db, k.plant_code, body.supervisor_pin)
    if not sup:
        raise HTTPException(403, "Supervisor PIN invalid")
    scanned = db.query(models.PickListLine).filter_by(picklist_no=no).count()
    if body.qty < scanned or body.qty <= 0:
        raise HTTPException(400, f"Qty cannot be below scanned ({scanned})")
    old = k.qty; k.qty = body.qty
    integration.queue_retry(db, "EBS_SO_UPDATE", no, f"qty {old}->{body.qty}: {body.reason}")
    audit(db, p, "PICKLIST_REDUCE_QTY", "picklist", no, {"qty": old}, {"qty": body.qty, "reason": body.reason, "supervisor": sup.user_id}, request)
    db.commit()
    return row(k)


@router.post("/picklists/{no}/confirm")
def confirm_picklist(no: str, request: Request, p: Principal = Depends(need("DOCK_SCAN")), db: Session = Depends(get_db)):
    """Pick List Control: scanned count must equal qty; freeze list -> READY."""
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    if k.status not in ("OPEN", "SO_PENDING"):
        raise HTTPException(400, f"Pick list is {k.status}")
    scanned = db.query(models.PickListLine).filter_by(picklist_no=no).count()
    if scanned != k.qty:
        raise HTTPException(400, f"Pick List Control failed: scanned {scanned} vs qty {k.qty}")
    if k.status == "SO_PENDING":
        raise HTTPException(400, "Sale order not yet confirmed by EBS (retry pending)")
    k.status = "READY"
    audit(db, p, "PICKLIST_CONFIRM", "picklist", no, request=request)
    db.commit()
    return row(k)


@router.post("/picklists/{no}/challan")
def challan(no: str, request: Request, p: Principal = Depends(need("CHALLAN_REQUEST")), db: Session = Depends(get_db)):
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    if k.status != "READY":
        raise HTTPException(400, f"Challan Control: pick list is {k.status}, must be READY")
    if k.challan_no:
        raise HTTPException(400, f"Challan Control: already challaned ({k.challan_no})")
    plant = db.get(models.Plant, k.plant_code)
    cust = db.query(models.Customer).filter_by(code=k.customer_code, plant_code=k.plant_code).first()
    source = (cust.challan_source_override if cust and cust.challan_source_override else plant.challan_source).upper()
    if source == "ORACLE":
        ok, cno, msg = integration.create_oracle_challan(db, k)
        if not ok:
            raise HTTPException(502, f"Oracle challan failed: {msg}")
    else:
        cno = f"{plant.app_challan_series or plant.code + '/'}{services.next_seq(db, plant.code + ':CH'):05d}"
    k.challan_no = cno; k.status = "CHALLANED"
    for l in db.query(models.PickListLine).filter_by(picklist_no=no).all():
        pal = db.get(models.Pallet, l.pallet_no)
        if pal:
            pal.challan_ref = cno
    audit(db, p, "CHALLAN_CREATE", "picklist", no, None, {"challan_no": cno, "source": source}, request)
    db.commit()
    return row(k) | {"source": source}


class ApproveIn(BaseModel):
    vehicle_no: str
    transporter_code: str | None = None
    driver: str | None = None


@router.post("/picklists/{no}/approve")
def approve(no: str, body: ApproveIn, request: Request, p: Principal = Depends(need("LOGISTICS_APPROVE")), db: Session = Depends(get_db)):
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    if k.status != "CHALLANED":
        raise HTTPException(400, f"Pick list is {k.status}, challan required first")
    k.vehicle_no = body.vehicle_no.upper().replace(" ", "")
    if body.transporter_code:
        k.transporter_code = body.transporter_code
    ok, gcs, msg = integration.create_gcs_outward(db, k)
    k.gcs_no = gcs if ok else None
    if not ok:
        integration.queue_retry(db, "GCS_OUT", no, msg)
    k.status = "APPROVED"
    audit(db, p, "LOGISTICS_APPROVE", "picklist", no, None, body.model_dump() | {"gcs": gcs, "gcs_msg": msg}, request)
    db.commit()
    return row(k) | {"gcs_message": msg}


class GateOutIn(BaseModel):
    scanned: str                        # GCS QR or challan no
    manual_override: bool = False
    supervisor_pin: str | None = None
    remarks: str | None = None


@router.post("/picklists/{no}/gate-out")
def gate_out(no: str, body: GateOutIn, request: Request, p: Principal = Depends(need("OUT_GATE_SCAN")), db: Session = Depends(get_db)):
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    if k.status != "APPROVED":
        raise HTTPException(400, f"Vehicle not approved by logistics (status {k.status})")
    sc = body.scanned.strip()
    if sc not in (k.gcs_no, k.challan_no):
        if not body.manual_override:
            raise HTTPException(400, "Scanned QR does not match this pick list's GCS/challan - hold vehicle")
        if not body.supervisor_pin or not verify_supervisor_pin(db, k.plant_code, body.supervisor_pin):
            raise HTTPException(403, "Supervisor PIN required for manual override")
    for l in db.query(models.PickListLine).filter_by(picklist_no=no).all():
        pal = db.get(models.Pallet, l.pallet_no)
        services.move(db, pal, "AT_CUSTOMER", event_type="GATE_OUT", user_id=p.user_id, plant=None, customer=k.customer_code, ref=k.challan_no)
    k.status = "DISPATCHED"
    if k.gcs_no:
        integration.approve_gcs_outward(db, k)
    audit(db, p, "GATE_OUT" + ("_OVERRIDE" if body.manual_override else ""), "picklist", no, None, body.model_dump(exclude={"supervisor_pin"}), request)
    db.commit()
    return row(k)


# ---------------------------------------------------------------- return slips
class SlipIn(BaseModel):
    customer_code: str
    mode: str                           # A | B1 | B2
    vehicle_no: str | None = None
    pallets: list[str] = []             # scanned tags / pallet nos (A, B1)
    declared_qty: int | None = None     # B2
    slip_no: str | None = None          # device-generated number allowed
    customer_challan_no: str | None = None
    driver_name: str | None = None
    driver_mobile: str | None = None
    remarks: str | None = None


@router.get("/slips")
def list_slips(status: str | None = None, plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.ReturnSlip).order_by(models.ReturnSlip.created_at.desc())
    pl = p.scope_plant(plant)
    if pl:
        q = q.filter(models.ReturnSlip.plant_code == pl)
    if status:
        q = q.filter(models.ReturnSlip.status == status)
    return [row(x) for x in q.limit(500).all()]


@router.get("/slips/{no}")
def get_slip(no: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    sl = db.get(models.ReturnSlip, no)
    if not sl:
        raise HTTPException(404, "Not found")
    p.require_plant(sl.plant_code)
    lines = db.query(models.ReturnSlipLine).filter_by(slip_no=no).all()
    return {"slip": row(sl), "lines": [row(l) for l in lines]}


@router.post("/slips")
def create_slip(body: SlipIn, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    mode = body.mode.upper()
    if mode.startswith("B"):
        p.require("RETURN_SLIP_B")
    elif mode != "A":
        raise HTTPException(400, "mode must be A, B1 or B2")
    cust = db.query(models.Customer).filter_by(code=body.customer_code, plant_code=p.plant).first()
    if not cust:
        raise HTTPException(400, "Customer not mapped to this plant")
    no = body.slip_no or services.doc_number(db, p.plant, "RTS")
    if db.get(models.ReturnSlip, no):
        raise HTTPException(400, "Slip number exists")
    sl = models.ReturnSlip(slip_no=no, plant_code=p.plant, customer_code=cust.code, mode=mode, vehicle_no=body.vehicle_no,
                           customer_challan_no=body.customer_challan_no, driver_name=body.driver_name, driver_mobile=body.driver_mobile,
                           source="WEB" if request.headers.get("x-device", "WEB") == "WEB" else "HHT", created_by=p.user_id, remarks=body.remarks)
    warnings = []
    if mode == "B2":
        if not body.declared_qty:
            raise HTTPException(400, "declared_qty required for B2")
        sl.declared_qty = body.declared_qty; sl.status = "PENDING_VERIFICATION"
    else:
        if not body.pallets:
            raise HTTPException(400, "pallet list required")
        seen = set()
        for scv in body.pallets:
            tag, pal = services.resolve_tag(db, scv)
            if not pal:
                warnings.append(f"{scv}: unknown tag, listed as declared"); pno = scv
            else:
                pno = pal.pallet_no
                if pal.customer_code != cust.code or pal.status != "AT_CUSTOMER":
                    warnings.append(f"{pno}: ledger shows {pal.status} {pal.customer_code or ''}")
                else:
                    services.move(db, pal, "IN_RETURN", event_type="RETURN_SLIP", user_id=p.user_id, ref=no, customer=cust.code)
            if pno in seen:
                continue
            seen.add(pno)
            db.add(models.ReturnSlipLine(slip_no=no, pallet_no=pno, declared=True))
        sl.declared_qty = len(seen); sl.status = "OPEN"
    db.add(sl)
    audit(db, p, "RETURN_SLIP_CREATE", "slip", no, None, body.model_dump(), request)
    db.commit()
    return row(sl) | {"warnings": warnings}


@router.post("/slips/{no}/gate-in")
def gate_in(no: str, request: Request, p: Principal = Depends(need("IN_GATE_SCAN")), db: Session = Depends(get_db)):
    sl = db.get(models.ReturnSlip, no)
    if not sl:
        raise HTTPException(404, "Slip not found - create Mode B slip")
    p.require_plant(sl.plant_code)
    if sl.status not in ("OPEN", "PENDING_VERIFICATION"):
        raise HTTPException(400, f"Slip is {sl.status}")
    ok, gcs, msg = integration.create_gcs_inward(db, sl)
    sl.gcs_in_no = gcs if ok else None
    if not ok:
        integration.queue_retry(db, "GCS_IN", no, msg)
    sl.status = "IN_GATE" if sl.mode != "B2" else "PENDING_VERIFICATION"
    audit(db, p, "GATE_IN", "slip", no, None, {"gcs": gcs, "msg": msg}, request)
    db.commit()
    return row(sl) | {"gcs_message": msg}


class CloseIn(BaseModel):
    supervisor_pin: str | None = None
    remarks: str | None = None


@router.post("/slips/{no}/close")
def close_slip(no: str, body: CloseIn, request: Request, p: Principal = Depends(need("RECONCILE_CLOSE")), db: Session = Depends(get_db)):
    sl = db.get(models.ReturnSlip, no)
    if not sl:
        raise HTTPException(404, "Not found")
    p.require_plant(sl.plant_code)
    if sl.status == "CLOSED":
        raise HTTPException(400, "Already closed")
    lines = db.query(models.ReturnSlipLine).filter_by(slip_no=no).all()
    short = [l for l in lines if l.declared and not l.received]
    exc = [l for l in lines if l.exception and not l.resolved]
    for l in short:
        l.exception = l.exception or "SHORT"
        pal = db.get(models.Pallet, l.pallet_no)
        if pal and pal.status == "IN_RETURN":
            services.move(db, pal, "AT_CUSTOMER", event_type="RETURN_SHORT", user_id=p.user_id, customer=sl.customer_code, ref=no, remarks="not received", force=True)
            pal.dispatch_date = pal.dispatch_date  # keep original aging
    open_exc = short + exc
    if open_exc:
        if not body.supervisor_pin or not verify_supervisor_pin(db, sl.plant_code, body.supervisor_pin):
            raise HTTPException(403, f"{len(open_exc)} open exception(s): supervisor PIN required to close")
    received = sum(1 for l in lines if l.received)
    sl.status = "CLOSED"; sl.closed_at = utcnow()
    if sl.gcs_in_no:
        integration.close_gcs_inward(db, sl, received)
    audit(db, p, "RETURN_SLIP_CLOSE", "slip", no, None, {"received": received, "short": len(short), "exceptions": len(exc), "remarks": body.remarks}, request)
    db.commit()
    return row(sl) | {"received": received, "short": [l.pallet_no for l in short], "exceptions": [(l.pallet_no, l.exception) for l in exc]}


@router.post("/slips/{no}/resolve/{pallet_no}")
def resolve_line(no: str, pallet_no: str, remarks: str | None = None, request: Request = None, p: Principal = Depends(need("RECONCILE_CLOSE")), db: Session = Depends(get_db)):
    l = db.query(models.ReturnSlipLine).filter_by(slip_no=no, pallet_no=pallet_no).first()
    if not l:
        raise HTTPException(404, "Line not found")
    l.resolved = True
    audit(db, p, "EXCEPTION_RESOLVE", "slip_line", f"{no}/{pallet_no}", None, {"remarks": remarks}, request)
    db.commit()
    return {"ok": True}
