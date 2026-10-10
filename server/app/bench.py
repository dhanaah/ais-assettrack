"""HMIL Planning Bench link (pull). The Bench owns trip planning, LPN reservation, PDI and sub-inventory moves.
AssetTrack pulls each Bench dispatch + its picked LPNs and creates a pick list (HB-<plant>-<dispatch_id>) on which the
HHT binds pallets to the picked LPNs, then challan, gate and the pallet return cycle continue in AssetTrack.
Bench endpoints used (no change needed in hmil_server): POST /api/auth/login, GET /api/dispatches/recent, GET /api/picks.
Developed by DT
"""
import json, logging, threading, time
from datetime import datetime
from sqlalchemy.orm import Session
from . import models
from .models import utcnow

log = logging.getLogger("bench")
KEYS = ["bench_enabled", "bench_url", "bench_user", "bench_password", "bench_plant", "bench_customer_map", "bench_interval_sec", "bench_days"]
_token = {"v": None}
_state = {"last_run": None, "last_ok": None, "last_error": None, "created": 0, "updated": 0, "lpns": 0}


def get_settings(db: Session) -> dict:
    out = {k: None for k in KEYS}
    for s in db.query(models.Setting).filter(models.Setting.key.in_(KEYS)).all():
        out[s.key] = s.value
    out["bench_enabled"] = (out["bench_enabled"] or "0") == "1"
    out["bench_interval_sec"] = int(out["bench_interval_sec"] or 60)
    out["bench_days"] = int(out["bench_days"] or 3)
    return out


def save_settings(db: Session, data: dict):
    for k in KEYS:
        if k not in data or (k == "bench_password" and not data[k]):
            continue
        v = data[k]
        v = ("1" if v else "0") if k == "bench_enabled" else (None if v in (None, "") else str(v))
        row = db.get(models.Setting, k)
        if not row:
            row = models.Setting(key=k); db.add(row)
        row.value = v
    _token["v"] = None


def _http(method, url, token=None, body=None):
    import httpx
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = httpx.request(method, url, json=body, headers=h, timeout=20)
    if r.status_code == 401:
        raise PermissionError("401")
    r.raise_for_status()
    return r.json()


def _login(cfg):
    d = _http("POST", cfg["bench_url"].rstrip("/") + "/api/auth/login", body={"username": cfg["bench_user"], "password": cfg["bench_password"]})
    _token["v"] = d["token"]
    return _token["v"]


def _get(cfg, path):
    base = cfg["bench_url"].rstrip("/")
    tok = _token["v"] or _login(cfg)
    try:
        return _http("GET", base + path, tok)
    except PermissionError:
        return _http("GET", base + path, _login(cfg))


def customer_for(cfg, bench_plant: str) -> str:
    """bench_customer_map: 'HVF1=HMIL1;HVF2=HMIL2' (Bench plant -> AssetTrack customer code). Default: same code."""
    m = {}
    for part in (cfg.get("bench_customer_map") or "").replace(",", ";").split(";"):
        if "=" in part:
            a, b = part.split("=", 1); m[a.strip().upper()] = b.strip()
    return m.get((bench_plant or "").upper(), bench_plant or "HMIL")


def pull(db: Session, fetch=None) -> dict:
    """fetch(path) -> json; injectable for tests."""
    cfg = get_settings(db)
    _state["last_run"] = utcnow()
    if not fetch:
        if not cfg["bench_url"] or not cfg["bench_user"]:
            raise RuntimeError("HMIL Bench link not configured (URL / user)")
        fetch = lambda path: _get(cfg, path)
    plant = (cfg["bench_plant"] or "").upper()
    if not db.get(models.Plant, plant):
        raise RuntimeError(f"Set the AIS plant for the Bench link (now '{plant or '-'}')")
    created = updated = n_lpn = 0
    disp = fetch("/api/dispatches/recent?limit=300").get("dispatches", [])
    for d in disp:
        did = str(d.get("id") or d.get("dispatch_id"))
        status = (d.get("dispatch_status") or "").lower()
        if not did or status in ("skipped", "cancelled", "canceled"):
            continue
        sent = d.get("sent_at") or ""
        try:
            if sent and (datetime.now() - datetime.fromisoformat(sent[:19])).days > cfg["bench_days"]:
                continue
        except Exception:
            pass
        no = f"HB-{plant}-{did}"
        pk = db.get(models.PickList, no)
        if pk and pk.status not in ("OPEN",):
            continue                 # already confirmed / dispatched in AssetTrack: frozen
        picks = fetch(f"/api/picks?dispatch_id={did}").get("picks", [])
        lp = {}
        for pr in picks:
            lpn = (pr.get("picked_lpn") or "").strip()
            if lpn:
                lp[lpn] = pr        # last pick wins (repicks replace)
        if not pk:
            pk = models.PickList(picklist_no=no, plant_code=plant, customer_code=customer_for(cfg, d.get("plant")), dispatch_type="CUSTOMER",
                                 source="HMIL_BENCH", ext_ref=did, qty=0, part_qty=0, status="OPEN", created_by="HMIL_BENCH",
                                 remarks=f"Bench trip {d.get('trip_id')} · {d.get('shift_name') or ''} · {d.get('segment') or ''}".strip(" ·"))
            db.add(pk); db.flush(); created += 1
        else:
            updated += 1
        pk.vehicle_no = (d.get("vehicle") or pk.vehicle_no or "").upper().replace(" ", "") or None
        total = 0
        for lpn, pr in lp.items():
            q = int(float(pr.get("qty") or 0)); total += q
            l = db.get(models.Lpn, lpn)
            if not l:
                l = models.Lpn(lpn_no=lpn, plant_code=plant, part_no=pr.get("item_code") or "?", qty=q, status="RESERVED"); db.add(l)
            if l.status in ("AVAILABLE", "RESERVED", "MISSING"):
                l.part_no = pr.get("item_code") or l.part_no; l.qty = q; l.subinventory = pr.get("sub_inv") or l.subinventory
                l.status, l.reserved_for, l.reserved_at, l.wms_missing = "RESERVED", no, utcnow(), False
                n_lpn += 1
        # LPNs the Bench replaced (PDI reject -> repick) are released if not yet bound to a pallet
        for l in db.query(models.Lpn).filter_by(reserved_for=no, status="RESERVED").all():
            if l.lpn_no not in lp:
                l.status, l.reserved_for, l.reserved_at = "AVAILABLE", None, None
        bound = sum(r.qty for r in db.query(models.PickListLpn).filter_by(picklist_no=no).all())
        pk.part_qty = max(total, bound)
        pk.qty = max(pk.qty or 0, db.query(models.PickListLine).filter_by(picklist_no=no).count(), 1)
    db.commit()
    _state.update(last_ok=utcnow(), last_error=None, created=created, updated=updated, lpns=n_lpn)
    return {"dispatches": len(disp), "created": created, "updated": updated, "lpns": n_lpn}


def status() -> dict:
    return dict(_state)


def start_scheduler(SessionLocal):
    def loop():
        while True:
            try:
                with SessionLocal() as db:
                    cfg = get_settings(db)
                    if cfg["bench_enabled"]:
                        pull(db)
                    wait = cfg["bench_interval_sec"]
            except Exception as e:
                _state["last_error"] = str(e)[:300]; log.warning("bench pull: %s", e); wait = 60
            time.sleep(max(20, wait))
    t = threading.Thread(target=loop, name="hmil-bench-pull", daemon=True)
    t.start()
