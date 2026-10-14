"""Pick lists (dispatch) and return slips (return) - document level operations.
EBS SO posting and GCS calls are stubs behind integration.py; they queue for retry."""
import os
import re
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
import json
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
    from .. import gcs as gcssvc
    lines = db.query(models.PickListLine).filter_by(picklist_no=no).order_by(models.PickListLine.scanned_at).all()
    return {"picklist": row(k), "lines": [row(l) for l in lines], "items": gcssvc.items_loaded(db, no)}


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
        if pal and pal.status == "ALLOCATED" and pal.picklist_no == no:
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
def gcs_open(body: GcsOpenIn, request: Request, p: Principal = Depends(hht()), db: Session = Depends(get_db)):
    """HHT: scan / type the GCS number at the vehicle. Returns the loading sheet (from the FTP inbox) or opens one from the
    details typed by the operator when the file has not arrived yet."""
    p.require_any("DOCK_SCAN", "PACK_DISPATCH", "VEHICLE_LOAD")   # Security opens the GCS at the vehicle (no Dispatch preparation)
    from .. import gcs as gcssvc
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    q = gcssvc.parse_gcs_qr(body.gcs_no)
    no = (q["gcs_no"] if q and q.get("gcs_no") else body.gcs_no).strip().upper()
    if q and not q.get("valid"):
        raise HTTPException(400, q["error"])
    k = db.query(models.PickList).filter(models.PickList.plant_code == p.plant, models.PickList.gcs_no == no).order_by((models.PickList.status == "LINKED").asc()).first()
    if k and k.status == "LINKED" and k.linked_picklist and db.get(models.PickList, k.linked_picklist):
        k = db.get(models.PickList, k.linked_picklist)          # GCS joined with its Bench trip: work on the one record
    if not k:
        if not (body.vehicle_no and body.customer_code):
            raise HTTPException(404, f"GCS {no} not received from the inbox yet - enter vehicle and customer to open it manually")
        what, k = gcssvc.apply_gcs(db, p.plant, {"gcs_no": no, "vehicle_no": body.vehicle_no, "customer_code": body.customer_code, "invoice_no": body.invoice_no}, "HHT manual")
        audit(db, p, "GCS_OPEN_MANUAL", "picklist", k.picklist_no, None, body.model_dump(), request)
    db.commit()
    return row(k) | {"scanned": db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).count(), "items": gcssvc.items_loaded(db, k.picklist_no)}


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
        if lpnsvc.is_gcs(k):
            p.require_any("DOCK_SCAN", "VEHICLE_LOAD")  # Security 'Finish loading' of a GCS at FGWH / Packing
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
        pr = {}
        if ok:                               # challan prints on the plant's network printer (Plant Master), no BT printer
            from .. import gcsprint
            from ..db import SessionLocal
            try:
                pr = gcsprint.print_challan_now(SessionLocal, no, p.user.id)
            except Exception as e:
                pr = {"print": f"PDF failed: {e}"[:200]}
        return row(k) | {"challan_message": None if ok else f"Challan not made yet: {msg} - press Challan on the web Pick Lists page",
                         "challan_print": pr.get("print"), "challan_pdf": pr.get("challan_pdf")}
    if lpnsvc.is_gcs(k):
        # Finish loading against a GCS: quantity = what was loaded; challan now; the GCS (made after invoicing) is the gate pass
        if scanned < 1:
            raise HTTPException(400, "Scan at least one pallet")
        # loading vs the GCS file: part cards listed but not scanned / scanned but not listed (warning, recorded in the audit)
        exp = {g.lpn_no for g in db.query(models.GcsLpn).filter_by(picklist_no=no).all()}
        got = {r.lpn_no for r in db.query(models.PickListLpn).filter_by(picklist_no=no).all()}
        exp_pal = {g.pallet_no for g in db.query(models.GcsLpn).filter_by(picklist_no=no).all() if g.pallet_no}
        got_pal = {l.pallet_no for l in db.query(models.PickListLine).filter_by(picklist_no=no).all()}
        check = {"expected_pallets": k.qty or None, "loaded_pallets": scanned,
                 "missing_lpns": sorted(exp - got) if exp else [], "extra_lpns": sorted(got - exp) if exp else [],
                 "missing_pallets": sorted(services.short_ref(x) for x in exp_pal - got_pal),
                 "extra_pallets": sorted(services.short_ref(x) for x in got_pal - exp_pal) if exp_pal else []}
        # quantity: invoice (GCS) qty vs qty on the part cards loaded, per item and in total
        inv, ld = {}, {}
        for it in db.query(models.PickListItem).filter_by(picklist_no=no).all():
            key = (it.part_no or "").upper(); inv[key] = inv.get(key, 0) + (it.qty or 0)
        for r in db.query(models.PickListLpn).filter_by(picklist_no=no).all():
            key = (r.part_no or "").upper(); ld[key] = ld.get(key, 0) + (r.qty or 0)
        check["invoice_qty"] = sum(inv.values()); check["loaded_qty"] = sum(ld.values())
        check["qty_diff"] = [{"part_no": key or "?", "invoice_qty": inv.get(key, 0), "loaded_qty": ld.get(key, 0), "diff": ld.get(key, 0) - inv.get(key, 0)}
                             for key in sorted(set(inv) | set(ld)) if inv.get(key, 0) != ld.get(key, 0)] if inv else []
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
        audit(db, p, "GCS_LOADING_COMPLETE", "picklist", no, None, {"pallets": scanned, "challan_no": k.challan_no, "gcs": k.gcs_no, "check": check}, request)
        db.commit()
        from .. import gcs as gcssvc, gcsprint
        from ..db import SessionLocal
        qr = gcssvc.gcs_qr(k, scanned)
        try:
            pr = gcsprint.generate_and_print(SessionLocal, no, p.user.id, qr)
        except Exception as e:
            pr = {"pdf": None, "print": f"PDF failed: {e}"[:200]}
        return row(k) | {"gcs_qr": qr, "scanned": scanned, "gcs_pdf": pr.get("pdf"), "gcs_print": pr.get("print"), "gcs_check": check}

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


@router.get("/picklists/{no}/challan.pdf")
def challan_pdf(no: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Returnable pallet delivery challan (Rule 55) - original / duplicate / triplicate in one PDF. Built fresh each time."""
    from .. import gcsprint
    from ..challanprint import build_challan_pdf
    from fastapi.responses import FileResponse
    k = db.get(models.PickList, no)
    if not k or not k.challan_no:
        raise HTTPException(404, "No challan on this pick list yet")
    p.require_plant(k.plant_code)
    path = gcsprint.challan_path(k)
    with open(path, "wb") as f:
        f.write(build_challan_pdf(db, k, p.user))
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
    """OUT gate: Security scans the CHALLAN only (CHL|challan|... QR or the challan number) - customer dispatch, stock
    transfer and empty pallets to other plants alike. The matching approved load is dispatched."""
    sc = body.scanned.strip()
    if sc.startswith("AIS1|GCS|"):
        raise HTTPException(400, "OUT gate: scan the CHALLAN QR, not the GCS")
    if sc.startswith("CHL|"):
        sc = sc.split("|")[1]
    k = db.query(models.PickList).filter(models.PickList.plant_code == p.plant, models.PickList.challan_no == sc,
                                         models.PickList.status != "LINKED").order_by(models.PickList.created_at.desc()).first()
    if not k:
        raise HTTPException(404, f"No load found for challan {sc} - HOLD VEHICLE")
    return gate_out(k.picklist_no, GateOutIn(scanned=k.challan_no, manual_override=body.manual_override, supervisor_pin=body.supervisor_pin, remarks=body.remarks), request, p, db)


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
    if sc.startswith("CHL|"):
        sc = sc.split("|")[1]
    if sc != k.challan_no:                       # OUT gate: challan only
        if not body.manual_override:
            raise HTTPException(400, "Scan the CHALLAN of this vehicle - hold vehicle")
        if not body.supervisor_pin or not verify_supervisor_pin(db, k.plant_code, body.supervisor_pin):
            raise HTTPException(403, "Supervisor PIN required for manual override")
    lines = db.query(models.PickListLine).filter_by(picklist_no=no).all()
    wrong = []
    for l in lines:
        pal = db.get(models.Pallet, l.pallet_no)
        if not pal or pal.status != "ALLOCATED" or pal.picklist_no != no:
            wrong.append(f"{l.pallet_no} ({pal.status if pal else 'unknown'}{' ' + pal.picklist_no if pal and pal.picklist_no and pal.picklist_no != no else ''})")
    if wrong:
        raise HTTPException(400, f"{len(wrong)} pallet(s) on this load are no longer on it: {', '.join(wrong[:5])} - HOLD VEHICLE, check with logistics")
    if needs_loading(db, k) and not body.manual_override:
        notl = [l.pallet_no for l in lines if not l.loaded_at]
        if notl:
            raise HTTPException(400, f"{len(notl)} of {len(lines)} pallet(s) not loaded by Security: {', '.join(services.short_ref(x) for x in notl[:5])} - HOLD VEHICLE")
    # one OUT gate only: the load is claimed in one step (a second gate scanning the same GCS at the same moment gets 'already')
    got = db.query(models.PickList).filter_by(picklist_no=no, status="APPROVED").update({"status": "DISPATCHED"}, synchronize_session=False)
    if not got:
        db.rollback()
        raise HTTPException(400, "Vehicle already gated out")
    for l in lines:
        pal = db.get(models.Pallet, l.pallet_no)
        if k.dispatch_type == "EMPTY_RETURN":
            services.move(db, pal, "IN_TRANSIT", event_type="GATE_OUT_EMPTY_RETURN", user_id=p.user_id, plant=None, ref=k.challan_no, force=True)
            pal.location_plant = None; pal.customer_code = k.to_plant; pal.challan_ref = k.challan_no
            lpnsvc.set_load(db, pal, "EMPTY"); lpnsvc.set_zone(pal, None)
            continue
        dest = k.to_plant if k.dispatch_type == "STOCK_TRANSFER" else k.customer_code
        try:
            services.move(db, pal, "AT_CUSTOMER", event_type="GATE_OUT", user_id=p.user_id, plant=None, customer=dest, ref=k.challan_no)
        except services.RuleError as ex:
            db.rollback()
            raise HTTPException(400, f"{ex} - HOLD VEHICLE")
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


# ---------------------------------------------------------------- Security: vehicle loading (pallet QR into the vehicle)
def needs_loading(db, k) -> bool:
    """FGWH / Packing material dispatches (customer, stock transfer) are loaded by Security pallet by pallet; empty pallets
    loaded at the Pallet Yard are scanned by the Yard itself. Loads made before this rule started are not held."""
    if k.dispatch_type not in lpnsvc.PART_TYPES or k.load_point == "YARD":
        return False
    st = db.get(models.Setting, "vehicle_load_from")
    return not (st and st.value and k.created_at and k.created_at.isoformat() < st.value)


def _loading_row(db, k):
    """Pallets on the vehicle plus, for a GCS, the pallets the GCS file names that are not loaded yet."""
    lines = db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).order_by(models.PickListLine.scanned_at).all()
    pals = [{"pallet_no": l.pallet_no, "short": services.short_ref(l.pallet_no), "loaded": bool(l.loaded_at)} for l in lines]
    have = {l.pallet_no for l in lines}
    exp = sorted({g.pallet_no for g in db.query(models.GcsLpn).filter_by(picklist_no=k.picklist_no).all() if g.pallet_no})
    pals += [{"pallet_no": x, "short": services.short_ref(x), "loaded": False} for x in exp if x not in have]
    loaded = sum(1 for x in pals if x["loaded"])
    expected = len(exp) or (k.qty if not lpnsvc.is_gcs(k) and not lpnsvc.is_bench(k) else 0) or None
    return {"picklist_no": k.picklist_no, "gcs_no": k.gcs_no, "challan_no": k.challan_no, "vehicle_no": k.vehicle_no, "customer_code": k.customer_code,
            "to_plant": k.to_plant, "dispatch_type": k.dispatch_type, "status": k.status, "total": max(len(pals), expected or 0), "loaded": loaded,
            "expected": expected, "can_finish": lpnsvc.is_gcs(k) and k.status == "OPEN" and loaded > 0, "pallets": pals}


@router.get("/loading")
def loading_list(p: Principal = Depends(hht("VEHICLE_LOAD")), db: Session = Depends(get_db)):
    """Vehicles being loaded at FGWH / Packing: prepared pallets and how many Security has scanned into the vehicle."""
    out = []
    for k in db.query(models.PickList).filter(models.PickList.plant_code == p.plant, models.PickList.dispatch_type.in_(lpnsvc.PART_TYPES),
                                              models.PickList.status.notin_(["DISPATCHED", "CANCELLED", "CLOSED", "LINKED"])).order_by(models.PickList.created_at.desc()).limit(200).all():
        if k.load_point == "YARD":
            continue
        r = _loading_row(db, k)
        if r["total"] or (k.status == "OPEN" and lpnsvc.is_gcs(k)):          # GCS / pick list waiting for its first pallet is listed too
            out.append(r)
    return out


class LoadIn(BaseModel):
    scanned: str


@router.post("/picklists/{no}/load")
def load_pallet(no: str, body: LoadIn, request: Request, p: Principal = Depends(hht("VEHICLE_LOAD")), db: Session = Depends(get_db)):
    """Security scans the pallet QR as the pallet goes into the vehicle. There is no Dispatch preparation: while the load is
    OPEN the pallet is checked against the GCS (pallets and part cards in the GCS file) and allocated here with its part cards."""
    k = db.get(models.PickList, no)
    if not k:
        raise HTTPException(404, "Not found")
    p.require_plant(k.plant_code)
    if k.status in ("DISPATCHED", "CANCELLED", "CLOSED"):
        raise HTTPException(400, f"Load is {k.status}")
    if lpnsvc.is_card(db, body.scanned):
        raise HTTPException(400, "Vehicle loading: scan the pallet QR, not the pallet card")
    _t, pal = services.resolve_tag(db, body.scanned.strip())
    if not pal:
        raise HTTPException(400, f"Unknown pallet QR {body.scanned[:40]} - keep it off the vehicle")
    l = db.query(models.PickListLine).filter_by(picklist_no=no, pallet_no=pal.pallet_no).first()
    alerts = []
    if not l and k.status == "OPEN" and lpnsvc.is_gcs(k) and k.dispatch_type in lpnsvc.PART_TYPES and k.load_point != "YARD":
        exp = {g.pallet_no for g in db.query(models.GcsLpn).filter_by(picklist_no=no).all() if g.pallet_no}
        if exp and pal.pallet_no not in exp:      # the GCS file names its pallets: anything else stays off this vehicle
            other = (db.query(models.GcsLpn, models.PickList).join(models.PickList, models.PickList.picklist_no == models.GcsLpn.picklist_no)
                     .filter(models.GcsLpn.pallet_no == pal.pallet_no, models.PickList.status == "OPEN").first())
            raise HTTPException(400, f"Pallet {services.short_ref(pal.pallet_no)} is NOT in GCS {k.gcs_no}" + (f" - it belongs to GCS {other[1].gcs_no}" if other else "") + " - keep it off the vehicle")
        try:
            _m, alerts = lpnsvc.dock_scan(db, k, body.scanned.strip(), k.plant_code, user_id=p.user_id, device_id=None)
        except lpnsvc.RuleError as e:
            db.rollback()
            m = str(e)
            raise HTTPException(400, m if "keep it off" in m or "STOP" in m else f"{m} - keep it off the vehicle")
        db.flush()
        l = db.query(models.PickListLine).filter_by(picklist_no=no, pallet_no=pal.pallet_no).first()
    if not l:
        other = (db.query(models.PickListLine, models.PickList).join(models.PickList, models.PickList.picklist_no == models.PickListLine.picklist_no)
                 .filter(models.PickListLine.pallet_no == pal.pallet_no, models.PickList.status.notin_(["DISPATCHED", "CANCELLED", "CLOSED"])).first())
        raise HTTPException(400, f"{services.short_ref(pal.pallet_no)} is not prepared for this vehicle" + (f" - it belongs to {other[1].gcs_no or other[1].picklist_no}" if other else "") + " - keep it off")
    dup = bool(l.loaded_at)
    if not dup:
        l.loaded_at = utcnow(); l.loaded_by = p.user_id
        audit(db, p, "VEHICLE_LOAD", "picklist", no, None, {"pallet": pal.pallet_no}, request)
        db.commit()
    r = _loading_row(db, k)
    return r | {"pallet_no": pal.pallet_no, "short": services.short_ref(pal.pallet_no), "duplicate": dup, "alerts": [a for a in alerts if a]}


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
    doc_pallets: list[str] = []         # Option B: pallets read from the photo of the customer's document
    doc_unread: list[str] = []
    doc_text: str | None = None
    doc_read_qty: int | None = None
    doc_types: dict[str, int] = {}      # pallets written by type only {F: 4, NF: 2}
    doc_total: int | None = None        # total the customer wrote
    doc_photo_count: int = 0            # Option B: photos of the customer's document taken at the gate (required, min 1)


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
    return {"slip": row(sl), "lines": [row(l) for l in lines], "doc": doc_compare(db, sl)}


@router.post("/slips")
def create_slip(body: SlipIn, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    require_hht(request)
    if not p.plant:
        raise HTTPException(400, "Plant user required")
    # Return slips: Option A only by the customer's own HHT (/api/ext), Option B only by IN-gate security, and it is a
    # count only - the pallets are scanned and the slip knocked off at pallet-yard receiving. Pallets coming back from
    # another AIS plant come on that plant's challan (scan it at the IN gate) - never on a return slip.
    mode = body.mode.upper()
    if mode == "A":
        raise HTTPException(403, "Option A return slips are made only on the customer's HHT")
    if not mode.startswith("B"):
        raise HTTPException(400, "mode must be B")
    p.require("RETURN_SLIP_B")
    if mode == "B1":                    # older HHT apps: keep the count, the yard scans the pallets
        body.declared_qty = body.declared_qty or len(set(body.pallets)); body.pallets = []
    mode = "B2"
    if db.get(models.Plant, body.customer_code):
        raise HTTPException(400, f"{body.customer_code} is an AIS plant - other-plant returns come with that plant's challan only (scan the challan at the IN gate)")
    cust = db.query(models.Customer).filter_by(code=body.customer_code, plant_code=p.plant).first()
    if not cust:
        raise HTTPException(400, "Customer not mapped to this plant")
    no = body.slip_no or services.doc_number(db, p.plant, "RTS")
    if db.get(models.ReturnSlip, no):
        old = db.get(models.ReturnSlip, no)
        if body.slip_no and old.plant_code == p.plant and old.customer_code == body.customer_code and old.mode == mode:
            ge = db.query(models.GateEntry).filter_by(plant_code=p.plant, ref_no=old.slip_no).first()
            return row(old) | {"duplicate": True, "gate_entry": ge.entry_no if ge else None}
        raise HTTPException(400, "Slip number exists")
    sl = models.ReturnSlip(slip_no=no, plant_code=p.plant, customer_code=cust.code, mode=mode, vehicle_no=body.vehicle_no,
                           customer_challan_no=body.customer_challan_no, driver_name=body.driver_name, driver_mobile=body.driver_mobile,
                           source="WEB" if request.headers.get("x-device", "WEB") == "WEB" else "HHT", created_by=p.user_id, remarks=body.remarks)
    warnings = []
    if mode == "B2":
        if not body.declared_qty:
            raise HTTPException(400, "declared_qty required for B2")
        if (body.doc_photo_count or 0) < 1:
            raise HTTPException(400, "Option B needs photo proof - take a photo of the customer's document")
        sl.declared_qty = body.declared_qty; sl.status = "PENDING_VERIFICATION"
        if body.doc_text and not body.doc_pallets:   # read offline on the HHT: match now on the server
            from .. import docread
            dm = docread.match(db, p.plant, cust.code, body.doc_text)
            body.doc_pallets = [x["pallet_no"] for x in dm["matched"] + dm["probable"]]; body.doc_unread = dm["unread"]
            body.doc_read_qty = body.doc_read_qty or dm["read"]
            body.doc_types = body.doc_types or {x["type"]: x["doc_qty"] for x in dm["type_counts"]}; body.doc_total = body.doc_total or dm["stated_total"]
        if body.doc_pallets or body.doc_text or body.doc_types or body.doc_total:
            pals = [x for x in dict.fromkeys(body.doc_pallets) if db.get(models.Pallet, x)][:500]
            sl.doc_pallets = json.dumps(pals); sl.doc_unread = json.dumps(body.doc_unread[:60])
            sl.doc_text = (body.doc_text or "")[:20000]; sl.doc_read_qty = body.doc_read_qty if body.doc_read_qty is not None else len(pals)
            sl.doc_types = json.dumps({str(k).upper()[:15]: int(v) for k, v in (body.doc_types or {}).items() if int(v) > 0}) if body.doc_types else None
            sl.doc_total = body.doc_total or (sum(body.doc_types.values()) if body.doc_types else None) or (sl.doc_read_qty or None)
            if sl.doc_total and sl.doc_total != body.declared_qty:
                warnings.append(f"Customer document says {sl.doc_total} pallet(s), count entered {body.declared_qty}")
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
    # Option B is made at the IN gate itself: the gate entry (and GCS inward) is registered with it
    ge, _ = gate_register(db, p, "SLIP_B", no, cust.code, sl.vehicle_no, sl.declared_qty, request)
    sl.gcs_in_no = ge.gcs_in_no
    db.commit()
    return row(sl) | {"warnings": warnings, "gate_entry": ge.entry_no}


class DocMatchIn(BaseModel):
    customer_code: str
    text: str


@router.post("/slips/doc-match")
def slip_doc_match(body: DocMatchIn, p: Principal = Depends(hht("RETURN_SLIP_B")), db: Session = Depends(get_db)):
    """Text read from the photo of the customer's manual document -> pallet numbers matched to the ledger."""
    from .. import docread
    return docread.match(db, p.plant, body.customer_code, body.text)


@router.post("/slips/doc-read")
async def slip_doc_read(request: Request, customer_code: str = Form(...), device_text: str = Form(""), file: UploadFile | None = File(None),
                        p: Principal = Depends(hht("RETURN_SLIP_B")), db: Session = Depends(get_db)):
    """Photo page of the customer's document: the HHT's text (+ AI reading when enabled) -> pallets matched to the ledger."""
    from .. import docread
    img = await file.read() if file is not None else None
    return docread.read(db, p.plant, customer_code, device_text, img if img and len(img) < 8_000_000 else None)


def _doc_dir():
    from ..gcsprint import docs_dir
    d = os.path.join(os.path.dirname(docs_dir()), "slip_docs"); os.makedirs(d, exist_ok=True); return d


@router.post("/slips/{no}/doc-photo")
async def slip_doc_photo(no: str, request: Request, file: UploadFile = File(...), p: Principal = Depends(hht("RETURN_SLIP_B")), db: Session = Depends(get_db)):
    """Photo of the customer's document kept with the slip (evidence)."""
    sl = db.get(models.ReturnSlip, no)
    if not sl:
        raise HTTPException(404, "Slip not found")
    p.require_plant(sl.plant_code)
    data = await file.read()
    if len(data) > 8_000_000:
        raise HTTPException(400, "Photo too large")
    photos = json.loads(sl.doc_photos or "[]")
    if len(photos) >= 10:
        raise HTTPException(400, "10 photos already kept for this slip")
    name = f"{re.sub(r'[^A-Za-z0-9]+', '_', no)}_{len(photos) + 1}.jpg"
    with open(os.path.join(_doc_dir(), name), "wb") as f:
        f.write(data)
    photos.append(name); sl.doc_photos = json.dumps(photos)
    audit(db, p, "SLIP_DOC_PHOTO", "slip", no, None, {"file": name, "bytes": len(data)}, request)
    db.commit()
    return {"ok": True, "photos": len(photos)}


@router.get("/slips/{no}/doc-photo/{i}")
def slip_doc_photo_get(no: str, i: int, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    sl = db.get(models.ReturnSlip, no)
    if not sl:
        raise HTTPException(404, "Not found")
    p.require_plant(sl.plant_code)
    photos = json.loads(sl.doc_photos or "[]")
    if not 1 <= i <= len(photos):
        raise HTTPException(404, "No such photo")
    return FileResponse(os.path.join(_doc_dir(), photos[i - 1]), media_type="image/jpeg")


def doc_compare(db, sl) -> dict | None:
    """Customer's document vs pallets received at the yard (Option B knock-off): by pallet number when the document
    lists them, by pallet type when it gives type quantities only, and the total."""
    if not (sl.doc_pallets or sl.doc_types or sl.doc_total):
        return None
    doc = json.loads(sl.doc_pallets or "[]")
    got = [l.pallet_no for l in db.query(models.ReturnSlipLine).filter_by(slip_no=sl.slip_no, received=True).all()]
    rtype = {}
    for x in got:
        m = services.PALLET_ID_RE.match(x or "")
        k = m.group(2) if m else "?"
        rtype[k] = rtype.get(k, 0) + 1
    dtype = json.loads(sl.doc_types or "{}")
    return {"doc_qty": sl.doc_read_qty, "doc_total": sl.doc_total, "declared_qty": sl.declared_qty, "received": len(got),
            "by_type": [{"type": k, "doc_qty": dtype.get(k), "received": rtype.get(k, 0)} for k in sorted(set(dtype) | set(rtype))],
            "on_doc_not_received": [services.short_ref(x) for x in doc if x not in got],
            "received_not_on_doc": [services.short_ref(x) for x in got if x not in doc],
            "unread": json.loads(sl.doc_unread or "[]")}


class GateInIn(BaseModel):
    qr: str | None = None           # full scanned QR (AIS1|RS|...) - check code and vehicle verified
    vehicle_no: str | None = None   # actual vehicle at gate (optional cross-check)
    supervisor_pin: str | None = None   # Option A slip whose QR cannot be scanned (torn / smudged): supervisor lets it in


@router.get("/gate-entries")
def gate_entries(plant: str | None = None, days: int = 7, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """IN-gate inward register (slips A / B and other-plant challans) with the pallet-yard status of each."""
    from datetime import timedelta
    pl = p.scope_plant(plant)
    q = db.query(models.GateEntry).filter(models.GateEntry.created_at >= utcnow() - timedelta(days=max(1, min(days, 366))))
    if pl:
        q = q.filter(models.GateEntry.plant_code == pl)
    out = []
    for g in q.order_by(models.GateEntry.created_at.desc()).limit(2000).all():
        r = row(g)
        if g.kind == "CHALLAN":
            r["yard_status"] = "CLOSED" if g.yard_closed_at else "AT GATE / YARD"
        else:
            sl = db.get(models.ReturnSlip, g.ref_no)
            r["yard_status"] = (sl.status if sl else "-")
        out.append(r)
    return out


@router.post("/slips/{no}/gate-in")
def gate_in(no: str, request: Request, body: GateInIn | None = None, p: Principal = Depends(hht("IN_GATE_SCAN")), db: Session = Depends(get_db)):
    if no.startswith("CHL|") or (not no.startswith(("AIS1|", "RTS|")) and not db.get(models.ReturnSlip, no)):
        k = _interplant_challan(db, p, no)
        if k:
            return _gate_in_challan(db, p, k, request)
    if no.startswith("AIS1|") or no.startswith("RTS|"):
        body = body or GateInIn(); body.qr = no
    q = services.parse_slip_qr(body.qr) if body and body.qr else None
    if q:
        if q["error"]:
            audit(db, p, "GATE_IN_QR_REJECTED", "slip", q.get("slip_no"), None, {"qr": body.qr}, request); db.commit()
            raise HTTPException(400, q["error"] + " - HOLD VEHICLE")
        no = q["slip_no"]
    sl = db.get(models.ReturnSlip, no)
    if not sl and q and q.get("offline"):
        sl = _open_offline_slip(db, p, q, request)
    if not sl:
        raise HTTPException(404, "Slip not found - create Mode B slip")
    if q and not q.get("signed") and sl.source == "EXT_API" and (body.qr or "").startswith("AIS1|"):
        raise HTTPException(400, "Customer label without check code - not issued by AssetTrack - HOLD VEHICLE")
    if sl.mode == "A" and sl.source in ("CUST_HHT", "EXT_API", "GATE_RO") and not (q and q.get("signed")):
        if not (body and body.supervisor_pin and verify_supervisor_pin(db, sl.plant_code, body.supervisor_pin)):
            raise HTTPException(400, "Option A slip: scan the QR printed on the slip (check code) - HOLD VEHICLE, or supervisor PIN")
        audit(db, p, "GATE_IN_NO_QR_PIN", "slip", sl.slip_no, None, {"scanned": no}, request)
    if q and q.get("legacy") and not services.legacy_ok(sl.created_at):
        raise HTTPException(400, "QR check code invalid - label altered or not issued by AssetTrack - HOLD VEHICLE")
    if q and q.get("vehicle") and sl.vehicle_no and q["vehicle"] != sl.vehicle_no:
        raise HTTPException(400, f"QR vehicle {q['vehicle']} differs from the slip ({sl.vehicle_no}) - HOLD VEHICLE")
    if q and q.get("slip_no") and q.get("plant") and (q["plant"] != sl.plant_code or q.get("customer") != sl.customer_code):
        raise HTTPException(400, "QR does not match the slip record - HOLD VEHICLE")
    if q and q.get("vehicle") and body.vehicle_no and q["vehicle"] != body.vehicle_no.upper().replace(" ", ""):
        raise HTTPException(400, f"Vehicle mismatch: label {q['vehicle']} vs gate {body.vehicle_no} - HOLD VEHICLE")
    p.require_plant(sl.plant_code)
    if sl.status not in ("OPEN", "PENDING_VERIFICATION"):
        raise HTTPException(400, f"Slip is {sl.status}")
    ge, msg = gate_register(db, p, "SLIP_A" if sl.mode == "A" else "SLIP_B", no, sl.customer_code, sl.vehicle_no, sl.declared_qty, request)
    sl.gcs_in_no = ge.gcs_in_no
    sl.status = "IN_GATE" if sl.mode != "B2" else "PENDING_VERIFICATION"
    audit(db, p, "GATE_IN", "slip", no, None, {"gate_entry": ge.entry_no, "gcs": ge.gcs_in_no, "msg": msg}, request)
    db.commit()
    return row(sl) | {"gcs_message": msg, "gate_entry": ge.entry_no}


def gate_register(db, p, kind, ref, party, vehicle, qty, request=None):
    """One IN-gate register entry + GCS inward per inward vehicle document (repeat scans return the same entry)."""
    ge = db.query(models.GateEntry).filter_by(plant_code=p.plant, ref_no=ref).first()
    if ge:
        return ge, "already registered"
    import types
    doc = types.SimpleNamespace(slip_no=ref, vehicle_no=vehicle, declared_qty=qty, customer_code=party, plant_code=p.plant)
    ok, gcs, msg = integration.create_gcs_inward(db, doc)
    ge = models.GateEntry(entry_no=services.doc_number(db, p.plant, "GE"), plant_code=p.plant, kind=kind, ref_no=ref, from_party=party,
                          vehicle_no=vehicle, qty=qty or 0, gcs_in_no=gcs if ok else None, created_by=p.user_id)
    db.add(ge)
    if not ok:
        integration.queue_retry(db, "GCS_IN_GE", ge.entry_no, msg)
    audit(db, p, "GATE_ENTRY", "gate_entry", ge.entry_no, None, {"kind": kind, "ref": ref, "from": party, "qty": qty, "gcs": gcs, "msg": msg}, request)
    return ge, msg


def _open_offline_slip(db, p, q, request):
    """Customer HHT printed the slip without network (signed with its own key) and the vehicle reached AIS first:
    open the slip from the QR - pallets from the type + serial list on it. The HHT adds the rest when it is online."""
    d = db.get(models.CustomerDevice, q["device_id"]) if q.get("device_id") else None
    cust = db.query(models.Customer).filter_by(code=q["customer"], plant_code=q["plant"]).first()
    if not d or d.revoked_at or not cust or d.customer_id != cust.id:
        raise HTTPException(400, "Slip printed by an HHT that is not paired with this customer - HOLD VEHICLE")
    if q["plant"] != p.plant:
        raise HTTPException(400, f"Slip is for plant {q['plant']} - HOLD VEHICLE")
    sl = models.ReturnSlip(slip_no=q["slip_no"], plant_code=q["plant"], customer_code=cust.code, mode="A", vehicle_no=q["vehicle"] or None,
                           source="GATE_RO", created_by=f"HHT:{cust.code}:{d.label}"[:40], declared_qty=q["qty"], status="OPEN",
                           remarks="printed offline - opened at gate")
    db.add(sl); db.flush()
    seen = set()
    for ref in q.get("refs") or []:
        pno = services.pallet_from_ref(db, ref, p.plant) or ref
        if pno in seen:
            continue
        seen.add(pno)
        pal = db.get(models.Pallet, pno)
        if pal and pal.customer_code == cust.code and pal.status == "AT_CUSTOMER":
            services.move(db, pal, "IN_RETURN", event_type="RETURN_SLIP_OFFLINE", user_id=p.user_id, ref=sl.slip_no, customer=cust.code)
        db.add(models.ReturnSlipLine(slip_no=sl.slip_no, pallet_no=pno[:30], declared=True))
    sl.declared_qty = max(q["qty"], len(seen))
    audit(db, p, "RETURN_SLIP_OFFLINE_OPEN", "slip", sl.slip_no, None, {"device": d.label, "refs": q.get("refs")}, request)
    return sl


def _interplant_challan(db, p, scanned):
    """A challan (CHL|challan|picklist|n or the challan number) of pallets sent by another AIS plant to this plant."""
    sc = scanned.split("|")[1] if scanned.startswith("CHL|") else scanned
    k = db.query(models.PickList).filter((models.PickList.challan_no == sc) | (models.PickList.picklist_no == sc)).order_by(models.PickList.created_at.desc()).first()
    if not k:
        if scanned.startswith("CHL|"):
            raise HTTPException(404, f"Challan {sc} not found - HOLD VEHICLE")
        return None
    if k.dispatch_type not in ("EMPTY_RETURN", "STOCK_TRANSFER") or (k.to_plant or k.customer_code) != p.plant:
        raise HTTPException(400, f"Challan {sc} is not addressed to {p.plant} - HOLD VEHICLE")
    return k


def _gate_in_challan(db, p, k, request):
    """Other-plant return at the IN gate: on the sending plant's challan only. Pallets are received at the yard."""
    if k.status not in ("DISPATCHED", "CLOSED"):
        raise HTTPException(400, f"Challan {k.challan_no} not gated out at {k.plant_code} yet (status {k.status}) - HOLD VEHICLE")
    seen = db.query(models.GateEntry).filter_by(plant_code=p.plant, ref_no=k.challan_no).first()
    qty = db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).count() or k.qty
    ge, msg = gate_register(db, p, "CHALLAN", k.challan_no, k.plant_code, k.vehicle_no, qty, request)
    if not seen:
        audit(db, p, "GATE_IN_CHALLAN", "picklist", k.picklist_no, None, {"challan": k.challan_no, "from": k.plant_code, "qty": qty, "gate_entry": ge.entry_no}, request)
    db.commit()
    return {"kind": "CHALLAN", "slip_no": k.challan_no, "challan_no": k.challan_no, "from_plant": k.plant_code, "customer_code": k.plant_code,
            "vehicle_no": k.vehicle_no, "declared_qty": qty, "status": "IN_GATE", "repeat": bool(seen), "gate_entry": ge.entry_no,
            "gcs_in_no": ge.gcs_in_no, "gcs_message": "Other-plant return on challan - registered at gate, receive the pallets at the pallet yard"}


def _close_challan(db, p, ge, body, request):
    """Other AIS plant's challan: the pallets on it are scanned at the yard (back home, AVAILABLE) and the challan is closed."""
    if ge.yard_closed_at:
        raise HTTPException(400, "Already closed")
    k = db.query(models.PickList).filter_by(challan_no=ge.ref_no).first()
    on = [l.pallet_no for l in db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).all()] if k else []
    st = bool(k and k.dispatch_type == "STOCK_TRANSFER")
    got = [x for x in on if (pal := db.get(models.Pallet, x)) and pal.location_plant == p.plant and
           ((pal.status in ("AVAILABLE", "DAMAGED") and pal.zone == "YARD") or (st and pal.status in ("IN_WIP", "HELD", "AVAILABLE", "ALLOCATED")))]
    short = [x for x in on if x not in got]
    if short and not (body.supervisor_pin and verify_supervisor_pin(db, p.plant, body.supervisor_pin)):
        raise HTTPException(403, f"{len(short)} pallet(s) on the challan not received - supervisor PIN to close")
    ge.yard_closed_at = utcnow()
    audit(db, p, "CHALLAN_YARD_CLOSE", "gate_entry", ge.entry_no, None, {"challan": ge.ref_no, "received": len(got), "short": short, "remarks": body.remarks}, request)
    db.commit()
    return {"slip_no": ge.ref_no, "status": "CLOSED", "received": len(got), "short": short, "exceptions": []}


class CloseIn(BaseModel):
    supervisor_pin: str | None = None
    remarks: str | None = None


@router.post("/slips/{no}/close")
def close_slip(no: str, body: CloseIn, request: Request, p: Principal = Depends(hht()), db: Session = Depends(get_db)):
    sl = db.get(models.ReturnSlip, no)
    if not sl:
        ge = db.query(models.GateEntry).filter_by(plant_code=p.plant, kind="CHALLAN", ref_no=no).first()
        if ge:
            kc = db.query(models.PickList).filter_by(challan_no=ge.ref_no).first()
            if kc and kc.dispatch_type == "STOCK_TRANSFER":     # material challan: closed by FGWH / Packing after receipt
                p.require_any("RECONCILE_CLOSE", "PLANT_RECEIPT", "PACK_RECEIPT")
            else:
                p.require_any("RECONCILE_CLOSE", "YARD_IN_PLANT")
            return _close_challan(db, p, ge, body, request)
        raise HTTPException(404, "Not found")
    p.require("RECONCILE_CLOSE")
    p.require_plant(sl.plant_code)
    if sl.status == "CLOSED":
        raise HTTPException(400, "Already closed")
    prev = sl.status
    if not db.query(models.ReturnSlip).filter(models.ReturnSlip.slip_no == no, models.ReturnSlip.status != "CLOSED").update({"status": "CLOSING"}, synchronize_session=False):
        db.rollback()
        raise HTTPException(400, "Already closed")
    db.refresh(sl); sl.status = prev                       # write lock held; real status kept until the close is complete
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
    pin_ok = bool(body.supervisor_pin) and verify_supervisor_pin(db, sl.plant_code, body.supervisor_pin)
    if sl.mode == "B2" and not json.loads(sl.doc_photos or "[]") and not pin_ok:
        raise HTTPException(403, "Option B photo proof is not on the server yet - let the gate HHT sync, or supervisor PIN to close without it")
    if sl.mode == "B2":                    # Option B: count made at the gate is checked against the pallets scanned at the yard
        got = sum(1 for l in lines if l.received and l.exception != "ALREADY_IN")
        if got != (sl.declared_qty or 0) and not pin_ok:
            raise HTTPException(403, f"Option B count {sl.declared_qty} but {got} pallet(s) scanned at the yard - supervisor PIN to close with the difference")
    if open_exc:
        if not pin_ok:
            raise HTTPException(403, f"{len(open_exc)} open exception(s): supervisor PIN required to close")
    received = sum(1 for l in lines if l.received)
    sl.status = "CLOSED"; sl.closed_at = utcnow()
    if sl.gcs_in_no:
        integration.close_gcs_inward(db, sl, received)
    audit(db, p, "RETURN_SLIP_CLOSE", "slip", no, None, {"received": received, "short": len(short), "exceptions": len(exc), "remarks": body.remarks}, request)
    db.commit()
    return row(sl) | {"received": received, "short": [l.pallet_no for l in short], "exceptions": [(l.pallet_no, l.exception) for l in exc], "doc": doc_compare(db, sl)}


@router.post("/slips/{no}/resolve/{pallet_no}")
def resolve_line(no: str, pallet_no: str, remarks: str | None = None, request: Request = None, p: Principal = Depends(need("RECONCILE_CLOSE")), db: Session = Depends(get_db)):
    l = db.query(models.ReturnSlipLine).filter_by(slip_no=no, pallet_no=pallet_no).first()
    if not l:
        raise HTTPException(404, "Line not found")
    l.resolved = True
    audit(db, p, "EXCEPTION_RESOLVE", "slip_line", f"{no}/{pallet_no}", None, {"remarks": remarks}, request)
    db.commit()
    return {"ok": True}
