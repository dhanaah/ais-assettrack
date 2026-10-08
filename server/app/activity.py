"""Activity logger - one row per action, from every channel (WEB, HHT, EXT API, SYSTEM).
Captured by middleware for all state-changing requests + logins + prints + exports; the HHT
also reports its on-device actions (screen opens, offline scans, prints) through /sync/activity.
Developed by DT"""
import json, time
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import jwt
from .db import Base, SessionLocal
from .models import utcnow
from . import config


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(8), index=True)          # WEB HHT EXT SYSTEM
    user_id: Mapped[str | None] = mapped_column(String(40), index=True)
    plant_code: Mapped[str | None] = mapped_column(String(10), index=True)
    device_id: Mapped[str | None] = mapped_column(String(60), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)         # e.g. PICKLIST_CREATE, SYNC_PUSH, LOGIN, PRINT_CHALLAN
    entity: Mapped[str | None] = mapped_column(String(30))
    ref: Mapped[str | None] = mapped_column(String(80), index=True)     # document / pallet number
    method: Mapped[str | None] = mapped_column(String(8))
    path: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[int | None] = mapped_column(Integer)                 # HTTP status or 0 for device-local
    result: Mapped[str | None] = mapped_column(String(300))             # short outcome / error detail
    detail: Mapped[str | None] = mapped_column(Text)                    # request body (secrets stripped)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(45))
    app_version: Mapped[str | None] = mapped_column(String(15))


Index("ix_activity_user_ts", ActivityLog.user_id, ActivityLog.ts)

# path -> (action, entity) naming for readable log lines
ACTIONS = [
    ("POST", "/api/v1/auth/login", "LOGIN", "user"), ("POST", "/api/v1/auth/change-password", "CHANGE_PASSWORD", "user"), ("POST", "/api/v1/auth/set-pin", "SET_PIN", "user"),
    ("POST", "/api/v1/plants", "PLANT_SAVE", "plant"), ("POST", "/api/v1/roles", "ROLE_SAVE", "role"), ("POST", "/api/v1/users", "USER_SAVE", "user"),
    ("POST", "/api/v1/customers", "CUSTOMER_SAVE", "customer"), ("POST", "/api/v1/transporters", "TRANSPORTER_SAVE", "transporter"),
    ("POST", "/api/v1/tag-batches", "TAG_BATCH", "tag_batch"), ("POST", "/api/v1/pallets", "PALLET_REGISTER", "pallet"),
    ("POST", "/api/v1/import/masters", "IMPORT_MASTERS", "file"), ("POST", "/api/v1/sync/push", "SYNC_PUSH", "events"), ("GET", "/api/v1/sync/pull", "SYNC_PULL", "cache"),
    ("POST", "/api/v1/picklists", "PICKLIST_CREATE", "picklist"), ("POST", "/api/v1/slips", "RETURN_SLIP_CREATE", "slip"),
    ("POST", "/api/ext/v1/return-slip", "EXT_RETURN_SLIP", "slip"), ("POST", "/api/ext/v1/validate", "EXT_VALIDATE", "tags"), ("GET", "/api/ext/v1/holding", "EXT_HOLDING", "ledger"),
    ("GET", "/print/challan/", "PRINT_CHALLAN", "picklist"), ("GET", "/print/slip/", "PRINT_SLIP", "slip"), ("GET", "/api/v1/reports/export/", "EXPORT", "report"),
    ("POST", "/api/v1/reports/integration/retry", "INTEGRATION_RETRY", "queue"), ("POST", "/api/v1/jobs/retry", "JOB_RETRY", "queue"),
]
SUB = {"confirm": "PICKLIST_CONFIRM", "challan": "CHALLAN_CREATE", "approve": "LOGISTICS_APPROVE", "gate-out": "GATE_OUT", "reduce-qty": "PICKLIST_REDUCE_QTY",
       "gate-in": "GATE_IN", "close": "SLIP_CLOSE", "resolve": "EXCEPTION_RESOLVE", "assign-tag": "TAG_ASSIGN", "status": "PALLET_STATUS", "unlock": "USER_UNLOCK",
       "block": "DEVICE_BLOCK", "api-key": "CUSTOMER_API_KEY"}
SECRET_KEYS = {"password", "old_password", "new_password", "pin", "supervisor_pin", "api_key"}


def classify(method: str, path: str):
    for m, pre, act, ent in ACTIONS:
        if method == m and path.startswith(pre):
            ref = path[len(pre):].strip("/").split("?")[0] or None
            return act, ent, ref
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 4 and parts[1] == "v1":
        last = parts[-1]
        if last in SUB:
            return SUB[last], parts[2].rstrip("s"), parts[3]
        if len(parts) >= 5 and parts[-2] == "resolve":
            return "EXCEPTION_RESOLVE", "slip_line", f"{parts[3]}/{parts[-1]}"
    return None, None, None


def _scrub(body: bytes) -> str | None:
    if not body:
        return None
    try:
        j = json.loads(body)
    except Exception:
        return f"<{len(body)} bytes>"
    def walk(o):
        if isinstance(o, dict):
            return {k: ("***" if k in SECRET_KEYS else walk(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(x) for x in o[:50]] + (["…"] if len(o) > 50 else [])
        return o
    return json.dumps(walk(j), default=str)[:4000]


def _who(request: Request):
    """user / plant / device from the JWT (or ext API key prefix) without hitting the DB."""
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("tok")
    if tok:
        try:
            d = jwt.decode(tok, config.JWT_SECRET, algorithms=[config.JWT_ALGO], options={"verify_exp": False})
            return d.get("sub"), None
        except Exception:
            pass
    key = request.headers.get("x-api-key")
    if key:
        return f"EXT:{key[:8]}…", None
    return None, None


def record(db: Session, **kw):
    db.add(ActivityLog(**kw))


class ActivityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method, path = request.method, request.url.path
        action, entity, ref = classify(method, path)
        if not action:
            return await call_next(request)
        body = b""
        if method in ("POST", "PUT", "DELETE") and "multipart" not in request.headers.get("content-type", ""):
            body = await request.body()
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            request = Request(request.scope, receive)
        t0 = time.perf_counter()
        status, result = 500, None
        try:
            response = await call_next(request)
            status = response.status_code
            if status >= 400 and hasattr(response, "body_iterator"):
                chunks = [c async for c in response.body_iterator]
                raw = b"".join(chunks)
                from starlette.responses import Response
                response = Response(content=raw, status_code=status, headers=dict(response.headers), media_type=response.media_type)
                try:
                    result = str(json.loads(raw).get("detail"))[:300]
                except Exception:
                    result = raw[:300].decode(errors="ignore")
            return response
        except Exception as e:
            result = f"{type(e).__name__}: {e}"[:300]
            raise
        finally:
            ms = int((time.perf_counter() - t0) * 1000)
            user, _ = _who(request)
            device = request.headers.get("x-device-id")
            source = "EXT" if path.startswith("/api/ext/") else ("HHT" if (request.headers.get("x-device") == "HHT" or path.startswith("/api/v1/sync/")) else ("SYSTEM" if path.startswith("/api/v1/jobs") else "WEB"))
            detail = _scrub(body)
            if action == "LOGIN":
                try:
                    j = json.loads(body); user = j.get("user_id"); device = j.get("device_id")
                except Exception:
                    pass
            if action == "SYNC_PUSH":
                try:
                    evs = json.loads(body).get("events", [])
                    device = device or (evs[0].get("device_id") if evs else None)
                    result = result or f"{len(evs)} event(s): " + ", ".join(sorted({e.get('event_type', '?') for e in evs}))[:200]
                except Exception:
                    pass
            if result is None and status < 400:
                result = "ok"
            try:
                with SessionLocal() as db:
                    plant = None
                    if user and not user.startswith("EXT:"):
                        from .models import User
                        u = db.query(User.plant_code).filter(User.user_id == user).first()
                        plant = u[0] if u else None
                    record(db, source=source, user_id=user, plant_code=plant, device_id=device, action=action, entity=entity, ref=ref,
                           method=method, path=path[:200], status=status, result=result, detail=detail, duration_ms=ms,
                           ip=request.client.host if request.client else None, app_version=request.headers.get("x-app-version"))
                    db.commit()
            except Exception:
                pass
