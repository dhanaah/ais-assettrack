"""Integration adapters: Oracle EBS and GCS.

Phase 1: stubs controlled by PALLET_INTEGRATION_MODE
  STUB  (default) - returns success with generated numbers, so the full flow can be tested
  OFF             - every call fails => documents queue for retry (tests contingency path)
  LIVE            - real HTTP calls (fill in the endpoints below in Phase 3/4)
Every call is logged in integration_log for the Sync Monitor / retry job.
"""
import os, json
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base
from .models import utcnow

MODE = os.getenv("PALLET_INTEGRATION_MODE", "STUB").upper()
EBS_SO_URL = os.getenv("PALLET_EBS_SO_URL", "")
EBS_CHALLAN_URL = os.getenv("PALLET_EBS_CHALLAN_URL", "")
EBS_SUBINV_URL = os.getenv("PALLET_EBS_SUBINV_URL", "")        # POST sub-inventory transfer of an LPN
EBS_ONHAND_URL = os.getenv("PALLET_EBS_ONHAND_URL", "")        # GET  ?lpn=  -> {subinventory, qty}   (2nd confirmation)
EBS_INVOICE_URL = os.getenv("PALLET_EBS_INVOICE_URL", "")      # GET  ?so=   -> {invoice_no, invoice_date}
EBS_RETURN_CHALLAN_URL = os.getenv("PALLET_EBS_RETURN_CHALLAN_URL", "")   # POST empty-pallet challan -> {challan_no, ewaybill_no}
EBS_WMS_STOCK_URL = os.getenv("PALLET_EBS_WMS_STOCK_URL", "")  # GET  ?org=   -> [{lpn, part_no, qty, subinventory, locator, pallet_no}]
EBS_AUTH = os.getenv("PALLET_EBS_AUTH", "")          # "user:pass"
TIMEOUT = int(os.getenv("PALLET_INTEGRATION_TIMEOUT", "20"))


class IntegrationLog(Base):
    __tablename__ = "integration_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    system: Mapped[str] = mapped_column(String(20), index=True)      # EBS GCS
    op: Mapped[str] = mapped_column(String(30))
    ref: Mapped[str] = mapped_column(String(60), index=True)
    ok: Mapped[int] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(String(500))
    request: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)


class RetryQueue(Base):
    __tablename__ = "retry_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)     # EBS_SO EBS_SO_UPDATE GCS_OUT GCS_IN ...
    ref: Mapped[str] = mapped_column(String(60), index=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="PENDING", index=True)   # PENDING DONE FAILED


def _log(db, system, op, ref, ok, message, req=None, resp=None):
    db.add(IntegrationLog(system=system, op=op, ref=ref, ok=1 if ok else 0, message=(message or "")[:500],
                          request=json.dumps(req, default=str) if req else None, response=json.dumps(resp, default=str) if resp else None))


def queue_retry(db: Session, kind: str, ref: str, error: str):
    q = db.query(RetryQueue).filter_by(kind=kind, ref=ref, status="PENDING").first()
    if not q:
        q = RetryQueue(kind=kind, ref=ref); db.add(q)
    q.last_error = (error or "")[:500]


def _http_get(url, params):
    import httpx
    auth = tuple(EBS_AUTH.split(":", 1)) if EBS_AUTH else None
    r = httpx.get(url, params=params, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _http_post(url, payload):
    import httpx
    auth = tuple(EBS_AUTH.split(":", 1)) if EBS_AUTH else None
    r = httpx.post(url, json=payload, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- Oracle EBS
def post_sale_order(db: Session, pk) -> tuple[bool, str | None, str]:
    from . import models
    if pk.part_no:      # FG part dispatch: blanket order is the master for PO / schedule
        bo = db.get(models.BlanketOrder, pk.blanket_id) if pk.blanket_id else None
        lpns = db.query(models.PickListLpn).filter(models.PickListLpn.picklist_no == pk.picklist_no,
                                                   models.PickListLpn.pdi_result == "OK").all()
        plant = db.get(models.Plant, pk.plant_code)
        payload = {"org_id": plant.ebs_org_id if plant else None, "order_type": "INTERNAL" if pk.dispatch_type == "STOCK_TRANSFER" else "STANDARD",
                   "customer": pk.customer_code, "to_plant": pk.to_plant, "blanket_no": bo.blanket_no if bo else None,
                   "po_number": pk.po_number, "item": pk.part_no, "customer_item": bo.customer_part_no if bo else None,
                   "qty": pk.part_qty, "picklist_no": pk.picklist_no, "lpns": [{"lpn": l.lpn_no, "qty": l.qty} for l in lpns],
                   "pallets": pk.qty}
    else:
        payload = {"org_id": None, "customer": pk.customer_code, "item": pk.pallet_type or "PALLET", "qty": pk.qty,
                   "picklist_no": pk.picklist_no, "returnable": True}
    if MODE == "OFF":
        _log(db, "EBS", "SO_CREATE", pk.picklist_no, False, "integration OFF", payload); return False, None, "EBS unavailable (OFF) - queued"
    if MODE == "STUB":
        so = f"SO{int(utcnow().timestamp()) % 10_000_000}"
        _log(db, "EBS", "SO_CREATE", pk.picklist_no, True, "stub", payload, {"so": so}); return True, so, f"stub SO {so}"
    try:
        resp = _http_post(EBS_SO_URL, payload)
        so = str(resp.get("so_number") or resp.get("ORDER_NUMBER"))
        _log(db, "EBS", "SO_CREATE", pk.picklist_no, True, "ok", payload, resp); return True, so, "ok"
    except Exception as e:
        _log(db, "EBS", "SO_CREATE", pk.picklist_no, False, str(e), payload); return False, None, str(e)


def create_oracle_challan(db: Session, pk) -> tuple[bool, str | None, str]:
    payload = {"so_number": pk.so_number, "picklist_no": pk.picklist_no}
    if MODE == "OFF":
        _log(db, "EBS", "CHALLAN", pk.picklist_no, False, "OFF", payload); return False, None, "EBS unavailable"
    if MODE == "STUB":
        c = f"ORC-{pk.plant_code}-{int(utcnow().timestamp()) % 100000:05d}"
        _log(db, "EBS", "CHALLAN", pk.picklist_no, True, "stub", payload, {"challan": c}); return True, c, "stub"
    try:
        resp = _http_post(EBS_CHALLAN_URL, payload)
        c = str(resp.get("challan_no")); _log(db, "EBS", "CHALLAN", pk.picklist_no, True, "ok", payload, resp); return True, c, "ok"
    except Exception as e:
        _log(db, "EBS", "CHALLAN", pk.picklist_no, False, str(e), payload); return False, None, str(e)


def subinv_transfer(db: Session, t) -> tuple[bool, str | None, str]:
    """Confirmation 1: EBS accepts the LPN sub-inventory transfer and returns its transaction id."""
    payload = {"lpn": t.lpn_no, "org": t.plant_code, "from_subinv": t.from_subinv, "to_subinv": t.to_subinv,
               "to_locator": t.to_locator, "qty": t.qty, "reason": t.reason, "ref": t.picklist_no}
    if MODE == "OFF":
        _log(db, "EBS", "SUBINV_XFER", t.lpn_no, False, "OFF", payload); return False, None, "EBS unavailable - queued"
    if MODE == "STUB":
        tid = f"MTL{t.id or 0:07d}"
        _log(db, "EBS", "SUBINV_XFER", t.lpn_no, True, "stub", payload, {"txn_id": tid}); return True, tid, "stub"
    try:
        resp = _http_post(EBS_SUBINV_URL, payload)
        if str(resp.get("status", "S")).upper() not in ("S", "SUCCESS", "OK"):
            raise RuntimeError(resp.get("message") or f"EBS status {resp.get('status')}")
        tid = str(resp.get("txn_id") or resp.get("TRANSACTION_ID"))
        _log(db, "EBS", "SUBINV_XFER", t.lpn_no, True, "ok", payload, resp); return True, tid, "ok"
    except Exception as e:
        _log(db, "EBS", "SUBINV_XFER", t.lpn_no, False, str(e), payload); return False, None, str(e)


def verify_lpn_onhand(db: Session, t) -> tuple[bool, str | None, str]:
    """Confirmation 2: read back EBS on-hand and check the LPN really sits in the target sub-inventory."""
    if MODE == "OFF":
        _log(db, "EBS", "ONHAND_VERIFY", t.lpn_no, False, "OFF"); return False, None, "EBS unavailable"
    if MODE == "STUB":
        _log(db, "EBS", "ONHAND_VERIFY", t.lpn_no, True, "stub", None, {"subinventory": t.to_subinv}); return True, t.to_subinv, "stub"
    try:
        resp = _http_get(EBS_ONHAND_URL, {"lpn": t.lpn_no, "org": t.plant_code})
        sub = str(resp.get("subinventory") or resp.get("SUBINVENTORY_CODE") or "")
        ok = sub.upper() == (t.to_subinv or "").upper()
        _log(db, "EBS", "ONHAND_VERIFY", t.lpn_no, ok, "ok" if ok else f"EBS shows {sub}", None, resp)
        return ok, sub, "ok" if ok else f"EBS on-hand shows {sub or 'nothing'}, expected {t.to_subinv}"
    except Exception as e:
        _log(db, "EBS", "ONHAND_VERIFY", t.lpn_no, False, str(e)); return False, None, str(e)


def fetch_invoice(db: Session, pk) -> tuple[bool, str | None, datetime | None, str]:
    if MODE == "OFF":
        _log(db, "EBS", "INVOICE_FETCH", pk.picklist_no, False, "OFF"); return False, None, None, "EBS unavailable"
    if MODE == "STUB":
        inv = f"INV{pk.plant_code}{int(utcnow().timestamp()) % 1_000_000:06d}"
        _log(db, "EBS", "INVOICE_FETCH", pk.picklist_no, True, "stub", {"so": pk.so_number}, {"invoice_no": inv}); return True, inv, utcnow(), "stub"
    try:
        resp = _http_get(EBS_INVOICE_URL, {"so": pk.so_number})
        inv = resp.get("invoice_no") or resp.get("TRX_NUMBER")
        if not inv:
            _log(db, "EBS", "INVOICE_FETCH", pk.picklist_no, False, "not yet invoiced", {"so": pk.so_number}, resp)
            return False, None, None, f"Invoice not yet generated in EBS for SO {pk.so_number}"
        dt = resp.get("invoice_date") or resp.get("TRX_DATE")
        dt = datetime.fromisoformat(str(dt)[:19]) if dt else utcnow()
        _log(db, "EBS", "INVOICE_FETCH", pk.picklist_no, True, "ok", {"so": pk.so_number}, resp); return True, str(inv), dt, "ok"
    except Exception as e:
        _log(db, "EBS", "INVOICE_FETCH", pk.picklist_no, False, str(e)); return False, None, None, str(e)


def create_return_challan(db: Session, pk, pallets: list) -> tuple[bool, str | None, str | None, str]:
    """Empty pallets back to origin plant: EBS creates the delivery challan AND the e-way bill."""
    from . import models
    fp, tp = db.get(models.Plant, pk.plant_code), db.get(models.Plant, pk.to_plant)
    payload = {"from_org": fp.ebs_org_id if fp else pk.plant_code, "to_org": tp.ebs_org_id if tp else pk.to_plant,
               "from_gstin": fp.gstin if fp else None, "to_gstin": tp.gstin if tp else None, "picklist_no": pk.picklist_no,
               "vehicle": pk.vehicle_no, "transporter": pk.transporter_code, "qty": len(pallets), "pallets": pallets,
               "purpose": "RETURN OF EMPTY RETURNABLE PALLETS", "ewaybill": True}
    if MODE == "OFF":
        _log(db, "EBS", "RETURN_CHALLAN", pk.picklist_no, False, "OFF", payload); return False, None, None, "EBS unavailable"
    if MODE == "STUB":
        n = int(utcnow().timestamp()) % 100000
        c, ewb = f"ORC-RT-{pk.plant_code}-{n:05d}", f"{n:012d}"[-12:]
        _log(db, "EBS", "RETURN_CHALLAN", pk.picklist_no, True, "stub", payload, {"challan_no": c, "ewaybill_no": ewb}); return True, c, ewb, "stub"
    try:
        resp = _http_post(EBS_RETURN_CHALLAN_URL, payload)
        c, ewb = resp.get("challan_no"), resp.get("ewaybill_no") or resp.get("EWB_NO")
        if not c or not ewb:
            raise RuntimeError(resp.get("message") or "EBS did not return challan / e-way bill number")
        _log(db, "EBS", "RETURN_CHALLAN", pk.picklist_no, True, "ok", payload, resp); return True, str(c), str(ewb), "ok"
    except Exception as e:
        _log(db, "EBS", "RETURN_CHALLAN", pk.picklist_no, False, str(e), payload); return False, None, None, str(e)


def pull_wms_stock(db: Session, plant_code: str) -> tuple[bool, list | None, str]:
    from . import models
    pl = db.get(models.Plant, plant_code)
    if MODE == "OFF":
        _log(db, "EBS", "WMS_PULL", plant_code, False, "OFF"); return False, None, "EBS unavailable - upload the WMS Excel instead"
    if MODE == "STUB":   # stub: EBS returns what we already hold (keeps test data stable)
        rows = [{"lpn": l.lpn_no, "part_no": l.part_no, "qty": l.qty, "subinventory": l.wms_subinv or l.subinventory, "locator": l.locator,
                 "pallet_no": l.pallet_no, "desc": l.part_desc}
                for l in db.query(models.Lpn).filter(models.Lpn.plant_code == plant_code, models.Lpn.status.in_(["AVAILABLE", "RESERVED", "PICKED", "PDI_OK"])).all()]
        _log(db, "EBS", "WMS_PULL", plant_code, True, f"stub {len(rows)} rows"); return True, rows, "stub"
    try:
        resp = _http_get(EBS_WMS_STOCK_URL, {"org": pl.ebs_org_id if pl else plant_code})
        rows = resp if isinstance(resp, list) else resp.get("rows", [])
        _log(db, "EBS", "WMS_PULL", plant_code, True, f"{len(rows)} rows"); return True, rows, "ok"
    except Exception as e:
        _log(db, "EBS", "WMS_PULL", plant_code, False, str(e)); return False, None, str(e)


# ---------------------------------------------------------------- GCS
def _gcs(db, plant_code):
    from . import models
    pl = db.get(models.Plant, plant_code)
    return pl.gcs_endpoint if pl else None


def create_gcs_outward(db: Session, pk) -> tuple[bool, str | None, str]:
    payload = {"challan_no": pk.challan_no, "vehicle": pk.vehicle_no, "qty": pk.qty, "customer": pk.customer_code, "transporter": pk.transporter_code}
    if MODE == "OFF":
        _log(db, "GCS", "OUT_CREATE", pk.picklist_no, False, "OFF", payload); return False, None, "GCS unavailable - manual gate-pass mode"
    if MODE == "STUB":
        g = f"GCS-O-{pk.plant_code}-{int(utcnow().timestamp()) % 100000:05d}"
        _log(db, "GCS", "OUT_CREATE", pk.picklist_no, True, "stub", payload, {"gcs": g}); return True, g, "stub"
    try:
        resp = _http_post(_gcs(db, pk.plant_code) + "/outward", payload)
        g = str(resp.get("gcs_no")); _log(db, "GCS", "OUT_CREATE", pk.picklist_no, True, "ok", payload, resp); return True, g, "ok"
    except Exception as e:
        _log(db, "GCS", "OUT_CREATE", pk.picklist_no, False, str(e), payload); return False, None, str(e)


def approve_gcs_outward(db: Session, pk):
    if MODE == "LIVE":
        try:
            _http_post(_gcs(db, pk.plant_code) + f"/outward/{pk.gcs_no}/approve", {})
            _log(db, "GCS", "OUT_APPROVE", pk.picklist_no, True, "ok"); return
        except Exception as e:
            _log(db, "GCS", "OUT_APPROVE", pk.picklist_no, False, str(e)); queue_retry(db, "GCS_OUT_APPROVE", pk.picklist_no, str(e)); return
    _log(db, "GCS", "OUT_APPROVE", pk.picklist_no, MODE == "STUB", MODE.lower())


def create_gcs_inward(db: Session, sl) -> tuple[bool, str | None, str]:
    payload = {"slip_no": sl.slip_no, "vehicle": sl.vehicle_no, "qty": sl.declared_qty, "customer": sl.customer_code}
    if MODE == "OFF":
        _log(db, "GCS", "IN_CREATE", sl.slip_no, False, "OFF", payload); return False, None, "GCS unavailable - manual gate-pass mode"
    if MODE == "STUB":
        g = f"GCS-I-{sl.plant_code}-{int(utcnow().timestamp()) % 100000:05d}"
        _log(db, "GCS", "IN_CREATE", sl.slip_no, True, "stub", payload, {"gcs": g}); return True, g, "stub"
    try:
        resp = _http_post(_gcs(db, sl.plant_code) + "/inward", payload)
        g = str(resp.get("gcs_no")); _log(db, "GCS", "IN_CREATE", sl.slip_no, True, "ok", payload, resp); return True, g, "ok"
    except Exception as e:
        _log(db, "GCS", "IN_CREATE", sl.slip_no, False, str(e), payload); return False, None, str(e)


def close_gcs_inward(db: Session, sl, received: int):
    if MODE == "LIVE":
        try:
            _http_post(_gcs(db, sl.plant_code) + f"/inward/{sl.gcs_in_no}/close", {"qty": received})
            _log(db, "GCS", "IN_CLOSE", sl.slip_no, True, "ok"); return
        except Exception as e:
            _log(db, "GCS", "IN_CLOSE", sl.slip_no, False, str(e)); queue_retry(db, "GCS_IN_CLOSE", sl.slip_no, str(e)); return
    _log(db, "GCS", "IN_CLOSE", sl.slip_no, MODE == "STUB", f"{MODE.lower()} qty={received}")


# ---------------------------------------------------------------- retry job
def run_retries(db: Session, max_attempts: int = 50) -> dict:
    from . import models
    done = failed = 0
    from . import lpn as lpnsvc
    lpnsvc.process_pending_txns(db)
    try:
        from .routers.sync import purge_old_events
        purge_old_events(db)
    except Exception as e:
        _log(db, "APP", "PURGE_EVENTS", None, False, str(e)[:200])
    for q in db.query(RetryQueue).filter_by(status="PENDING").all():
        q.attempts += 1
        ok = False; msg = ""
        if q.kind == "EBS_SO":
            pk = db.get(models.PickList, q.ref)
            if pk and pk.status == "SO_PENDING":
                ok, so, msg = post_sale_order(db, pk)
                if ok:
                    lpnsvc.on_so_created(db, pk, so)
            else:
                ok = True
        elif q.kind == "GCS_OUT":
            pk = db.get(models.PickList, q.ref)
            if pk:
                ok, g, msg = create_gcs_outward(db, pk)
                if ok:
                    pk.gcs_no = g
                    if pk.status == "DISPATCHED":
                        approve_gcs_outward(db, pk)
        elif q.kind == "GCS_IN":
            sl = db.get(models.ReturnSlip, q.ref)
            if sl:
                ok, g, msg = create_gcs_inward(db, sl)
                if ok:
                    sl.gcs_in_no = g
        else:
            ok, msg = (MODE != "OFF"), "noted"
        if ok:
            q.status = "DONE"; done += 1
        else:
            q.last_error = msg[:500]
            if q.attempts >= max_attempts:
                q.status = "FAILED"; failed += 1
    db.commit()
    return {"done": done, "failed": failed}
