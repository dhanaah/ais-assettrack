"""Pick lists (dispatch) and return slips (return) - document level operations.
EBS SO posting and GCS calls are stubs behind integration.py; they queue for retry."""
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, services, integration, lpn as lpnsvc
from ..db import get_db
from ..security import current_user, need, hht, require_hht, Principal, audit, verify_supervisor_pin
from ..models import utcnow

router = APIRouter(prefix="/api/v1", tags=["documents"])


def row(o):
    return {c.name: getattr(o, c.name) for c in o.__table__.columns}


# ---------------------------------------------------------------- pick lists
class PickListIn(BaseModel):
    customer_code: str | None = None
    qty: int                           # pallets
    dispatch_type: str = "CUSTOMER"    # CUSTOMER | STOCK_TRANSFER | EMPTY_RETURN | PALLET_ONLY
    blanket_id: int | None = None      # CUSTOMER / STOCK_TRANSFER: blanket order is the SO master
    part_qty: int | None = None
    to_plant: str | None = None        # EMPTY_RETURN destination (pallet home plant)
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
def create_picklist(body: PickListIn, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Release. Part dispatch: WMS stock must be fresh, blanket controls PO + schedule, LPNs reserved FIFO.
    SO is NOT pushed here - only after PDI passes and sub-inventory transfers are confirmed."""
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    dt = (body.dispatch_type or "CUSTOMER").upper()
    from .. import config
    if config.PICKLIST_SOURCE == "BENCH" and dt != "EMPTY_RETURN":
        raise HTTPException(400, "Dispatch pick lists are planned in the Dispatch Planning Bench and pulled automatically - "
                                 "AssetTrack only creates Empty Pallet Returns (HHT > Empty Pallet Return at the Yard)")
    if body.qty <= 0:
        raise HTTPException(400, "Pallet qty must be > 0")
    no = body.picklist_no or services.doc_number(db, p.plant, "RT" if dt == "EMPTY_RETURN" else "PL")
    if db.get(models.PickList, no):
        raise HTTPException(400, "Pick list number exists")
    try:
        if dt == "EMPTY_RETURN":
            p.require("EMPTY_RETURN")
            to = (body.to_plant or "").upper()
            if not db.get(models.Plant, to) or to == p.plant:
                raise services.RuleError("Select the origin (home) plant of the pallets")
            n = db.query(models.Pallet).filter(models.Pallet.home_plant == to, models.Pallet.location_plant == p.plant,
                                               models.Pallet.status.in_(["HELD", "IN_WIP"])).count()
            if n < body.qty:
                raise services.RuleError(f"Only {n} pallets of {to} held here")
            k = models.PickList(picklist_no=no, plant_code=p.plant, customer_code=to, to_plant=to, dispatch_type=dt, qty=body.qty,
                                transporter_code=body.transporter_code, created_by=p.user_id, remarks=body.remarks, status="OPEN")
            db.add(k)
            audit(db, p, "EMPTY_RETURN_CREATE", "picklist", no, None, body.model_dump(), request)
            db.commit()
            return row(k)
        p.require("PICKLIST_CREATE")
        if dt == "PALLET_ONLY":
            cust = db.query(models.Customer).filter_by(code=body.customer_code, plant_code=p.plant, active=True).first()
            if not cust:
                raise services.RuleError("Customer not mapped to this plant")
            avail = db.query(models.Pallet).filter_by(home_plant=p.plant, status="AVAILABLE")
            if body.pallet_type:
                avail = avail.filter_by(pallet_type=body.pallet_type)
            if avail.count() < body.qty:
                raise services.RuleError(f"Only {avail.count()} pallets available")
            k = models.PickList(picklist_no=no, plant_code=p.plant, customer_code=cust.code, transporter_code=body.transporter_code, dispatch_type=dt,
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
        if dt not in lpnsvc.PART_TYPES:
            raise services.RuleError("dispatch_type must be CUSTOMER, STOCK_TRANSFER, EMPTY_RETURN or PALLET_ONLY")
        lpnsvc.require_fresh_wms(db, p.plant)
        bo = db.get(models.BlanketOrder, body.blanket_id) if body.blanket_id else None
        if not bo:
            raise services.RuleError("Select the blanket order (part / PO)")
        if not body.part_qty or body.part_qty <= 0:
            raise services.RuleError("Part qty must be > 0")
        if bo.dispatch_type != dt:
            raise services.RuleError(f"Blanket {bo.blanket_no} is for {bo.dispatch_type}")
        lpnsvc.validate_blanket(db, bo, p.plant, bo.customer_code, body.part_qty)
        if dt == "CUSTOMER" and not db.query(models.Customer).filter_by(code=bo.customer_code, plant_code=p.plant, active=True).first():
            raise services.RuleError("Customer not mapped to this plant")
        avail = db.query(models.Pallet).filter_by(home_plant=p.plant, status="AVAILABLE").count()
        if avail < body.qty:
            raise services.RuleError(f"Only {avail} pallets available")
        k = models.PickList(picklist_no=no, plant_code=p.plant, customer_code=bo.customer_code, transporter_code=body.transporter_code,
                            dispatch_type=dt, to_plant=bo.to_plant if dt == "STOCK_TRANSFER" else None, blanket_id=bo.id,
                            part_no=bo.part_no, part_qty=body.part_qty, po_number=bo.po_number, pallet_type=body.pallet_type,
                            qty=body.qty, created_by=p.user_id, remarks=body.remarks, status="OPEN")
        db.add(k); db.flush()
        reserved = lpnsvc.reserve(db, k)
    except services.RuleError as ex:
        db.rollback()
        raise HTTPException(400, str(ex))
    audit(db, p, "PICKLIST_CREATE", "picklist", no, None, body.model_dump() | {"reserved": reserved}, request)
    db.commit()
    return row(k) | {"reserved_lpns": reserved}


@router.post("/picklists/{no}/cancel")
def cancel_picklist(no: str, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    p.require_any("PICKLIST_CREATE", "EMPTY_RETURN")
    if k.status not in ("OPEN", "SO_PENDING", "PDI_PENDING"):
        raise HTTPException(400, f"Cannot cancel at {k.status}" + (" - SO already in EBS, cancel there first" if k.so_number else ""))
    for line in db.query(models.PickListLine).filter_by(picklist_no=no).all():
        pal = db.get(models.Pallet, line.pallet_no)
        if pal and pal.status == "ALLOCATED":
            services.move(db, pal, "HELD" if pal.home_plant != k.plant_code else "AVAILABLE", event_type="PICKLIST_CANCEL",
                          user_id=p.user_id, plant=k.plant_code, ref=no, force=True)
    for r in db.query(models.PickListLpn).filter_by(picklist_no=no).all():
        db.delete(r)
    n = lpnsvc.release_reservations(db, no, only_unpicked=False)
    k.status = "CANCELLED"
    audit(db, p, "PICKLIST_CANCEL", "picklist", no, None, {"released_lpns": n}, request)
    db.commit()
    return row(k)


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


# ---------------------------------------------------------------- empty return loaded at the Pallet Yard (HHT)
class YardReturnIn(BaseModel):
    to_plant: str                      # owner (home) plant of the pallets
    vehicle_no: str | None = None
    transporter_code: str | None = None
    remarks: str | None = None


def _yard_return_stock(db: Session, plant: str) -> dict:
    """Other plants' pallets that can be sent back from here: {owner plant: count}."""
    out = {}
    for pal in db.query(models.Pallet).filter(models.Pallet.location_plant == plant, models.Pallet.home_plant != plant,
                                              models.Pallet.status.in_(["HELD", "IN_WIP"])).all():
        out[pal.home_plant] = out.get(pal.home_plant, 0) + 1
    return out


@router.get("/picklists/yard-return/options")
def yard_return_options(p: Principal = Depends(hht("EMPTY_RETURN")), db: Session = Depends(get_db)):
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    stock = _yard_return_stock(db, p.plant)
    names = {x.code: x.name for x in db.query(models.Plant).all()}
    return [{"plant": k, "name": names.get(k, k), "pallets": v} for k, v in sorted(stock.items())]


@router.post("/picklists/yard-return")
def yard_return_create(body: YardReturnIn, request: Request, p: Principal = Depends(hht("EMPTY_RETURN")), db: Session = Depends(get_db)):
    """Start loading empty pallets back to their owner plant at the Pallet Yard. Quantity = what is scanned."""
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    to = (body.to_plant or "").upper()
    if not db.get(models.Plant, to) or to == p.plant:
        raise HTTPException(400, "Select the owner plant of the pallets")
    if not _yard_return_stock(db, p.plant).get(to):
        raise HTTPException(400, f"No pallets of {to} held here")
    no = services.doc_number(db, p.plant, "RT")
    k = models.PickList(picklist_no=no, plant_code=p.plant, customer_code=to, to_plant=to, dispatch_type="EMPTY_RETURN", qty=0,
                        load_point="YARD", vehicle_no=(body.vehicle_no or "").upper().replace(" ", "") or None,
                        transporter_code=body.transporter_code, created_by=p.user_id, remarks=body.remarks, status="OPEN")
    db.add(k)
    audit(db, p, "YARD_RETURN_CREATE", "picklist", no, None, body.model_dump(), request)
    db.commit()
    return row(k) | {"scanned": 0}


class GcsOpenIn(BaseModel):
    gcs_no: str
    vehicle_no: str | None = None
    customer_code: str | None = None
    invoice_no: str | None = None


@router.post("/picklists/gcs-open")
def gcs_open(body: GcsOpenIn, request: Request, p: Principal = Depends(hht("DOCK_SCAN")), db: Session = Depends(get_db)):
    """HHT: scan / type the GCS number at the vehicle. Returns the loading sheet (from the FTP inbox) or opens one from the
    details typed by the operator when the file has not arrived yet."""
    from .. import gcs as gcssvc
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    q = gcssvc.parse_gcs_qr(body.gcs_no)
    no = (q["gcs_no"] if q and q.get("gcs_no") else body.gcs_no).strip().upper()
    if q and not q.get("valid"):
        raise HTTPException(400, q["error"])
    k = db.query(models.PickList).filter(models.PickList.plant_code == p.plant, models.PickList.gcs_no == no).first()
    if not k:
        if not (body.vehicle_no and body.customer_code):
            raise HTTPException(404, f"GCS {no} not received from the inbox yet - enter vehicle and customer to open it manually")
        what, k = gcssvc.apply_gcs(db, p.plant, {"gcs_no": no, "vehicle_no": body.vehicle_no, "customer_code": body.customer_code, "invoice_no": body.invoice_no}, "HHT manual")
        audit(db, p, "GCS_OPEN_MANUAL", "picklist", k.picklist_no, None, body.model_dump(), request)
    db.commit()
    return row(k) | {"scanned": db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).count()}


def _return_challan(db: Session, k: models.PickList, p: Principal, request: Request):
    """EMPTY_RETURN: only a challan (no SO / invoice); EBS generates challan + e-way bill. Returns (ok, message)."""
    pallets = [l.pallet_no for l in db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).all()]
    ok, cno, ewb, msg = integration.create_return_challan(db, k, pallets)
    if not ok:
        return False, msg
    k.challan_no, k.ewaybill_no, k.status = cno, ewb, "CHALLANED"
    for pn in pallets:
        pal = db.get(models.Pallet, pn)
        if pal:
            pal.challan_ref = cno
    audit(db, p, "RETURN_CHALLAN_CREATE", "picklist", k.picklist_no, None, {"challan_no": cno, "ewaybill": ewb, "pallets": len(pallets)}, request)
    return True, msg


@router.post("/picklists/{no}/confirm")
def confirm_picklist(no: str, request: Request, p: Principal = Depends(hht()), db: Session = Depends(get_db)):
    """Pick List Control: scanned count must equal qty; freeze list -> READY.
    Yard empty return: 'Finish loading' - qty = scanned pallets, then the EBS challan + e-way bill is made at once."""
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    if k.load_point == "YARD":
        p.require_any("EMPTY_RETURN", "DOCK_SCAN")
    else:
        p.require("DOCK_SCAN")
    if k.status not in ("OPEN", "SO_PENDING"):
        raise HTTPException(400, f"Pick list is {k.status}")
    scanned = db.query(models.PickListLine).filter_by(picklist_no=no).count()
    if k.load_point == "YARD":
        if scanned < 1:
            raise HTTPException(400, "Scan at least one pallet")
        k.qty = scanned; k.status = "READY"
        audit(db, p, "YARD_RETURN_LOADED", "picklist", no, None, {"pallets": scanned}, request)
        ok, msg = _return_challan(db, k, p, request)
        db.commit()
        return row(k) | {"challan_message": None if ok else f"Challan not made yet: {msg} - press Challan on the web Pick Lists page"}
    if lpnsvc.is_gcs(k):
        # Finish loading against a GCS: quantity = what was loaded; challan now; the GCS (made after invoicing) is the gate pass
        if scanned < 1:
            raise HTTPException(400, "Scan at least one pallet")
        if k.qty and scanned != k.qty:
            pass    # GCS said a different pallet count - allowed, recorded in the audit
        k.qty = scanned; k.part_qty = lpnsvc.picked_qty(db, no) or k.part_qty
        plant = db.get(models.Plant, k.plant_code)
        cust = db.query(models.Customer).filter_by(code=k.customer_code, plant_code=k.plant_code).first()
        source = (cust.challan_source_override if cust and cust.challan_source_override else plant.challan_source).upper()
        if not k.challan_no:
            if source == "ORACLE":
                ok, cno, msg = integration.create_oracle_challan(db, k)
                if not ok:
                    raise HTTPException(502, f"Oracle challan failed: {msg}")
            else:
                cno = f"{plant.app_challan_series or plant.code + '/'}{services.next_seq(db, plant.code + ':CH'):05d}"
            k.challan_no = cno
            for l in db.query(models.PickListLine).filter_by(picklist_no=no).all():
                pal = db.get(models.Pallet, l.pallet_no)
                if pal:
                    pal.challan_ref = cno
        k.status = "APPROVED"               # GCS exists and the vehicle is known: ready for the OUT gate
        audit(db, p, "GCS_LOADING_COMPLETE", "picklist", no, None, {"pallets": scanned, "challan_no": k.challan_no, "gcs": k.gcs_no}, request)
        db.commit()
        from .. import gcs as gcssvc, gcsprint
        from ..db import SessionLocal
        qr = gcssvc.gcs_qr(k, scanned)
        try:
            pr = gcsprint.generate_and_print(SessionLocal, no, p.user.id, qr)
        except Exception as e:
            pr = {"pdf": None, "print": f"PDF failed: {e}"[:200]}
        return row(k) | {"gcs_qr": qr, "scanned": scanned, "gcs_pdf": pr.get("pdf"), "gcs_print": pr.get("print")}

    if k.dispatch_type in lpnsvc.PART_TYPES:
        got = lpnsvc.picked_qty(db, no)
        if got != k.part_qty:
            raise HTTPException(400, f"Pick List Control failed: part {k.part_no} picked {got} vs {k.part_qty}")
        if scanned < 1 or (not lpnsvc.is_bench(k) and scanned > k.qty):
            raise HTTPException(400, f"Pick List Control failed: {scanned} pallets vs planned {k.qty}")
        k.qty = scanned
        # Dispatch Bench trips: the Bench already did reservation, PDI and sub-inventory -> straight to READY
        k.status = "READY" if lpnsvc.is_bench(k) else "PDI_PENDING"   # else QA / PDI next; SO only after PDI
        audit(db, p, "PICKLIST_CONFIRM", "picklist", no, request=request)
        db.commit()
        return row(k)
    if scanned != k.qty:
        raise HTTPException(400, f"Pick List Control failed: scanned {scanned} vs qty {k.qty}")
    if k.status == "SO_PENDING":
        raise HTTPException(400, "Sale order not yet confirmed by EBS (retry pending)")
    k.status = "READY"
    audit(db, p, "PICKLIST_CONFIRM", "picklist", no, request=request)
    db.commit()
    return row(k)


@router.post("/picklists/{no}/gcs-print")
def gcs_reprint(no: str, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Rebuild the GCS PDF and print it again on the plant printer (web or HHT)."""
    from .. import gcs as gcssvc, gcsprint
    from ..db import SessionLocal
    k = db.get(models.PickList, no)
    if not k or not k.gcs_no:
        raise HTTPException(404, "GCS not found")
    p.require_plant(k.plant_code)
    if not (p.has("OUT_GATE_SCAN") or p.has("DOCK_SCAN") or p.has("LOGISTICS_APPROVE") or p.has("CHALLAN_REQUEST")):
        raise HTTPException(403, "Not allowed")
    n = db.query(models.PickListLine).filter_by(picklist_no=no).count()
    pr = gcsprint.generate_and_print(SessionLocal, no, p.user.id, gcssvc.gcs_qr(k, n))
    audit(db, p, "GCS_REPRINT", "picklist", no, None, pr, request); db.commit()
    return pr


@router.get("/picklists/{no}/gcs.pdf")
def gcs_pdf(no: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    from .. import gcs as gcssvc, gcsprint
    from fastapi.responses import FileResponse
    k = db.get(models.PickList, no)
    if not k or not k.gcs_no:
        raise HTTPException(404, "GCS not found")
    p.require_plant(k.plant_code)
    path = gcsprint.pdf_path(k)
    if not os.path.exists(path):
        n = db.query(models.PickListLine).filter_by(picklist_no=no).count()
        data = gcsprint.build_pdf(db, k, p.user, gcssvc.gcs_qr(k, n))
        open(path, "wb").write(data)
    return FileResponse(path, media_type="application/pdf", filename=os.path.basename(path))


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
    if k.dispatch_type == "EMPTY_RETURN":     # only a challan (no SO / invoice); EBS generates challan + e-way bill
        ok, msg = _return_challan(db, k, p, request)
        if not ok:
            raise HTTPException(502, f"EBS return challan / e-way bill failed: {msg}")
        db.commit()
        return row(k) | {"source": "ORACLE"}
    if k.dispatch_type in lpnsvc.PART_TYPES and not lpnsvc.is_bench(k):   # challan goes with the EBS invoice
        if not k.so_number:
            raise HTTPException(400, "SO not yet created in EBS")
        if not k.invoice_no:
            ok, inv, invdt, msg = integration.fetch_invoice(db, k)
            if not ok:
                db.commit()
                raise HTTPException(409, f"{msg} - raise the invoice in EBS, then press Challan again")
            k.invoice_no, k.invoice_date = inv, invdt
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


@router.post("/gate-out/scan")
def gate_out_scan(body: GateOutIn, request: Request, p: Principal = Depends(hht("OUT_GATE_SCAN")), db: Session = Depends(get_db)):
    """OUT gate: scan the GCS QR (AIS1|GCS|...), a GCS number or a challan number - the matching approved load is dispatched."""
    from .. import gcs as gcssvc
    sc = body.scanned.strip()
    q = gcssvc.parse_gcs_qr(sc)
    if q:
        if not q.get("valid"):
            audit(db, p, "GATE_OUT_QR_REJECTED", "picklist", q.get("gcs_no"), None, {"qr": sc}, request); db.commit()
            raise HTTPException(400, q["error"] + " - HOLD VEHICLE")
        sc = q["gcs_no"]
    if sc.startswith("CHL|"):
        sc = sc.split("|")[1]
    k = db.query(models.PickList).filter(models.PickList.plant_code == p.plant, (models.PickList.gcs_no == sc) | (models.PickList.challan_no == sc)).order_by(models.PickList.created_at.desc()).first()
    if not k:
        raise HTTPException(404, f"No load found for {sc} - HOLD VEHICLE")
    if q and q.get("vehicle") and k.vehicle_no and q["vehicle"] != k.vehicle_no:
        raise HTTPException(400, f"QR vehicle {q['vehicle']} differs from the load ({k.vehicle_no}) - HOLD VEHICLE")
    return gate_out(k.picklist_no, GateOutIn(scanned=k.gcs_no or k.challan_no, manual_override=body.manual_override, supervisor_pin=body.supervisor_pin, remarks=body.remarks), request, p, db)


@router.post("/picklists/{no}/gate-out")
def gate_out(no: str, body: GateOutIn, request: Request, p: Principal = Depends(hht("OUT_GATE_SCAN")), db: Session = Depends(get_db)):
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    if k.status != "APPROVED":
        raise HTTPException(400, f"Vehicle not approved by logistics (status {k.status})")
    sc = body.scanned.strip()
    from .. import gcs as gcssvc
    q = gcssvc.parse_gcs_qr(sc)
    if q and q.get("valid") and q.get("gcs_no"):
        sc = q["gcs_no"]
    if sc not in (k.gcs_no, k.challan_no):
        if not body.manual_override:
            raise HTTPException(400, "Scanned QR does not match this pick list's GCS/challan - hold vehicle")
        if not body.supervisor_pin or not verify_supervisor_pin(db, k.plant_code, body.supervisor_pin):
            raise HTTPException(403, "Supervisor PIN required for manual override")
    for l in db.query(models.PickListLine).filter_by(picklist_no=no).all():
        pal = db.get(models.Pallet, l.pallet_no)
        if k.dispatch_type == "EMPTY_RETURN":
            services.move(db, pal, "IN_TRANSIT", event_type="GATE_OUT_EMPTY_RETURN", user_id=p.user_id, plant=None, ref=k.challan_no, force=True)
            pal.location_plant = None; pal.customer_code = k.to_plant; pal.challan_ref = k.challan_no
            lpnsvc.set_load(db, pal, "EMPTY"); lpnsvc.set_zone(pal, None)
            continue
        dest = k.to_plant if k.dispatch_type == "STOCK_TRANSFER" else k.customer_code
        services.move(db, pal, "AT_CUSTOMER", event_type="GATE_OUT", user_id=p.user_id, plant=None, customer=dest, ref=k.challan_no)
        lpnsvc.set_zone(pal, None)
        if k.dispatch_type in lpnsvc.PART_TYPES:
            lpns = db.query(models.PickListLpn).filter_by(picklist_no=no, pallet_no=pal.pallet_no).all()
            for r in lpns:
                x = db.get(models.Lpn, r.lpn_no)
                if x:
                    x.status, x.reserved_for = "DISPATCHED", None
            lpnsvc.set_load(db, pal, "LOADED", f"{k.part_no} x{sum(r.qty for r in lpns)} inv {k.invoice_no or ''}")
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
    require_hht(request)
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
                miss = lpnsvc.check_return_slip(db, pal, p.plant, no, cust.code, user_id=p.user_id)
                if miss:
                    warnings.append(miss)
                    services.move(db, pal, "IN_RETURN", event_type="RETURN_SLIP_MISSED_DISPATCH", user_id=p.user_id, ref=no, customer=cust.code, force=True)
                    lpnsvc.set_load(db, pal, "EMPTY")
                elif pal.customer_code != cust.code or pal.status != "AT_CUSTOMER":
                    warnings.append(f"{pno}: ledger shows {pal.status} {pal.customer_code or ''}")
                else:
                    lpnsvc.set_load(db, pal, "EMPTY")
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


class GateInIn(BaseModel):
    qr: str | None = None           # full scanned QR (AIS1|RS|...) - check code and vehicle verified
    vehicle_no: str | None = None   # actual vehicle at gate (optional cross-check)


@router.post("/slips/{no}/gate-in")
def gate_in(no: str, request: Request, body: GateInIn | None = None, p: Principal = Depends(hht("IN_GATE_SCAN")), db: Session = Depends(get_db)):
    if no.startswith("AIS1|") or no.startswith("RTS|"):
        body = body or GateInIn(); body.qr = no
    q = services.parse_slip_qr(body.qr) if body and body.qr else None
    if q:
        if q["error"]:
            audit(db, p, "GATE_IN_QR_REJECTED", "slip", q.get("slip_no"), None, {"qr": body.qr}, request); db.commit()
            raise HTTPException(400, q["error"] + " - HOLD VEHICLE")
        no = q["slip_no"]
    sl = db.get(models.ReturnSlip, no)
    if not sl:
        raise HTTPException(404, "Slip not found - create Mode B slip")
    if q and not q.get("signed") and sl.source == "EXT_API" and (body.qr or "").startswith("AIS1|"):
        raise HTTPException(400, "Customer label without check code - not issued by AssetTrack - HOLD VEHICLE")
    if q and q.get("slip_no") and q.get("plant") and (q["plant"] != sl.plant_code or q.get("customer") != sl.customer_code):
        raise HTTPException(400, "QR does not match the slip record - HOLD VEHICLE")
    if q and q.get("vehicle") and body.vehicle_no and q["vehicle"] != body.vehicle_no.upper().replace(" ", ""):
        raise HTTPException(400, f"Vehicle mismatch: label {q['vehicle']} vs gate {body.vehicle_no} - HOLD VEHICLE")
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
def close_slip(no: str, body: CloseIn, request: Request, p: Principal = Depends(hht("RECONCILE_CLOSE")), db: Session = Depends(get_db)):
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
