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


def _http_post(url, payload):
    import httpx
    auth = tuple(EBS_AUTH.split(":", 1)) if EBS_AUTH else None
    r = httpx.post(url, json=payload, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- Oracle EBS
def post_sale_order(db: Session, pk) -> tuple[bool, str | None, str]:
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
    for q in db.query(RetryQueue).filter_by(status="PENDING").all():
        q.attempts += 1
        ok = False; msg = ""
        if q.kind == "EBS_SO":
            pk = db.get(models.PickList, q.ref)
            if pk and pk.status == "SO_PENDING":
                ok, so, msg = post_sale_order(db, pk)
                if ok:
                    pk.so_number = so; pk.status = "OPEN"
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
