"""Dispatch Planning Bench link (pull) - all customers (formerly HMIL Planning Bench, Hyundai only).
The Bench owns trip planning, LPN reservation, PDI and sub-inventory moves. AssetTrack pulls each Bench dispatch + its
picked LPNs and creates a pick list (DB-<plant>-<dispatch_id>; older ones HB-...) on which the HHT binds pallets to the
picked LPNs, then challan, gate and the pallet return cycle continue in AssetTrack.
Two ways to read the Bench (setting bench_source):
  API - the Bench web server: POST /api/auth/login, GET /api/dispatches/recent, GET /api/picks (portable / SQLite Bench).
  SQL - read-only straight from the Bench's SQL Server database, through two fixed views the Bench publishes
        (assettrack_trips, assettrack_trip_cards - see server/sql/bench_views_contract.sql). If the SQL read fails and
        the API is set up, the API is used for that pull.
Both feed the same pull below. Card PDI result: OK, HOLD (rework, may become OK - not loadable meanwhile) or REJECT
(final - the card is off the trip; a scan of it at loading is stopped).
Developed by DT
"""
import logging, threading, time
from datetime import datetime
from sqlalchemy.orm import Session
from . import models
from .models import utcnow

log = logging.getLogger("bench")
import re
from datetime import timedelta
from sqlalchemy import text

KEYS = ["bench_enabled", "bench_url", "bench_user", "bench_password", "bench_plant", "bench_plant_map", "bench_customer_map", "bench_interval_sec", "bench_days",
        "bench_source", "bench_sql_server", "bench_sql_database", "bench_sql_user", "bench_sql_password", "bench_sql_url",
        "bench_sql_trips_view", "bench_sql_cards_view"]
SECRET_KEYS = ("bench_password", "bench_sql_password")
TRIPS_VIEW, CARDS_VIEW = "dbo.assettrack_trips", "dbo.assettrack_trip_cards"
_token = {"v": None}
_state = {"last_run": None, "last_ok": None, "last_error": None, "created": 0, "updated": 0, "lpns": 0, "source": None}


def get_settings(db: Session) -> dict:
    out = {k: None for k in KEYS}
    for s in db.query(models.Setting).filter(models.Setting.key.in_(KEYS)).all():
        out[s.key] = s.value
    out["bench_enabled"] = (out["bench_enabled"] or "0") == "1"
    out["bench_interval_sec"] = max(10, int(out["bench_interval_sec"] or 30))
    out["bench_days"] = int(out["bench_days"] or 3)
    out["bench_source"] = (out["bench_source"] or "API").upper()
    out["bench_sql_trips_view"] = out["bench_sql_trips_view"] or TRIPS_VIEW
    out["bench_sql_cards_view"] = out["bench_sql_cards_view"] or CARDS_VIEW
    return out


def save_settings(db: Session, data: dict):
    for k in KEYS:
        if k not in data or (k in SECRET_KEYS and not data[k]):
            continue
        v = data[k]
        v = ("1" if v else "0") if k == "bench_enabled" else (None if v in (None, "") else str(v))
        row = db.get(models.Setting, k)
        if not row:
            row = models.Setting(key=k); db.add(row)
        row.value = v
    _token["v"] = None
    _engines.clear()


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


# ---------------------------------------------------------------- SQL read (Bench on SQL Server)
_engines: dict = {}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}(\.[A-Za-z_][A-Za-z0-9_]{0,63})?$")


def api_ready(cfg) -> bool:
    return bool(cfg.get("bench_url") and cfg.get("bench_user"))


def _odbc_driver() -> str:
    try:
        import pyodbc
        have = pyodbc.drivers()
        for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
            if d in have:
                return d
    except Exception:
        pass
    return "ODBC Driver 18 for SQL Server"


def sql_url(cfg):
    """Where the Bench database is. bench_sql_url (full SQLAlchemy URL) wins; else the AssetTrack SQL Server with the
    Bench database name (same server, same login - only the database differs); else server / database / login given."""
    from sqlalchemy.engine import URL, make_url
    if cfg.get("bench_sql_url"):
        return make_url(cfg["bench_sql_url"])
    dbn = (cfg.get("bench_sql_database") or "").strip()
    if not dbn:
        raise RuntimeError("Bench SQL database name not set")
    server = (cfg.get("bench_sql_server") or "").strip()
    from .config import DB_URL
    if not server and DB_URL.startswith("mssql"):
        return make_url(DB_URL).set(database=dbn)
    if not server:
        raise RuntimeError("Bench SQL Server name not set (AssetTrack itself is not on SQL Server)")
    q = {"driver": _odbc_driver(), "TrustServerCertificate": "yes"}
    if cfg.get("bench_sql_user"):
        return URL.create("mssql+pyodbc", username=cfg["bench_sql_user"], password=cfg.get("bench_sql_password") or "", host=server, database=dbn, query=q)
    return URL.create("mssql+pyodbc", host=server, database=dbn, query={**q, "trusted_connection": "yes"})


def _engine(cfg):
    from sqlalchemy import create_engine
    url = sql_url(cfg)
    key = url.render_as_string(hide_password=False)
    if key not in _engines:
        _engines[key] = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2) if url.get_backend_name() != "sqlite" else create_engine(url)
    return _engines[key]


def _view(cfg, key) -> str:
    v = (cfg.get(key) or "").strip()
    if not _IDENT.match(v):
        raise RuntimeError(f"Bench SQL view name not valid: {v!r}")
    return v


def _iso(v):
    return v.isoformat(sep=" ") if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def _s(v):
    return None if v is None else str(v).strip()


def sql_fetch(cfg):
    """Read the Bench views once per pull and answer the same two questions as the Bench API, so the pull below is the
    same for both ways. Trips read: changed (trip or any of its cards) within the look-back days."""
    eng, tv, cv = _engine(cfg), _view(cfg, "bench_sql_trips_view"), _view(cfg, "bench_sql_cards_view")
    since = datetime.now() - timedelta(days=cfg["bench_days"] + 1)
    cards: dict = {}

    def fetch(path):
        if path.startswith("/api/dispatches/recent"):
            with eng.connect() as c:
                trips = c.execute(text(f"SELECT * FROM {tv} WHERE updated_at >= :s OR trip_id IN (SELECT trip_id FROM {cv} WHERE updated_at >= :s)"),
                                  {"s": since}).mappings().all()
                rows = c.execute(text(f"SELECT * FROM {cv} WHERE trip_id IN (SELECT trip_id FROM {tv} WHERE updated_at >= :s) "
                                      f"OR trip_id IN (SELECT trip_id FROM {cv} WHERE updated_at >= :s)"), {"s": since}).mappings().all()
            for r in rows:
                r = {k.lower(): v for k, v in r.items()}
                cards.setdefault(_s(r.get("trip_id")), []).append({
                    "picked_lpn": _s(r.get("lpn_no")), "item_code": _s(r.get("part_no")), "qty": r.get("qty") or 0, "sub_inv": _s(r.get("sub_inv")),
                    "pdi_status": _s(r.get("pdi_status")), "pdi_reason": _s(r.get("pdi_reason"))})
            out = []
            for t in trips:
                t = {k.lower(): v for k, v in t.items()}
                out.append({"id": _s(t.get("trip_id")), "trip_id": _s(t.get("trip_no")), "plant_code": _s(t.get("plant_code")),
                            "section": _s(t.get("section")), "customer_code": _s(t.get("customer_code")), "segment": _s(t.get("segment")),
                            "shift_name": _s(t.get("shift_name")), "vehicle": _s(t.get("vehicle_no")), "dispatch_status": _s(t.get("trip_status")),
                            "pdi_by": _s(t.get("pdi_by")), "pdi_login": _s(t.get("pdi_login")), "supervisor": _s(t.get("supervisor")),
                            "supervisor_login": _s(t.get("supervisor_login")), "sent_at": _iso(t.get("planned_at")), "so_no": _s(t.get("so_no"))})
            return {"dispatches": out}
        if path.startswith("/api/picks"):
            return {"picks": cards.get(path.split("dispatch_id=", 1)[-1], [])}
        raise RuntimeError(f"not a Bench read: {path}")
    return fetch


def sql_test(cfg) -> dict:
    """Admin check: can AssetTrack read both views? Row counts and the newest change."""
    eng, tv, cv = _engine(cfg), _view(cfg, "bench_sql_trips_view"), _view(cfg, "bench_sql_cards_view")
    with eng.connect() as c:
        nt = c.execute(text(f"SELECT COUNT(*) FROM {tv}")).scalar()
        nc = c.execute(text(f"SELECT COUNT(*) FROM {cv}")).scalar()
        last = c.execute(text(f"SELECT MAX(updated_at) FROM {tv}")).scalar()
    return {"ok": True, "trips": nt, "cards": nc, "last_change": _iso(last), "database": sql_url(cfg).database}


def card_pdi(pr: dict) -> str:
    """PDI result of a Bench card: OK / HOLD / REJECT. Blank = OK (Bench API without the field: the card is on the trip
    = PDI passed); an unknown word = HOLD (not loaded until the Bench says OK)."""
    v = str(pr.get("pdi_status") or pr.get("pdi_result") or "").strip().upper().replace(" ", "_")
    if not v:
        return "OK"
    return {"OK": "OK", "PASS": "OK", "PASSED": "OK", "ACCEPTED": "OK", "HOLD": "HOLD", "ON_HOLD": "HOLD", "HELD": "HOLD", "REWORK": "HOLD",
            "REJECT": "REJECT", "REJECTED": "REJECT", "NG": "REJECT", "NOK": "REJECT", "NOT_OK": "REJECT"}.get(v, "HOLD")


def bench_customer(d: dict) -> str:
    """Customer of a Bench dispatch: customer_code / customer / plant (older Hyundai-only Bench sends its HMIL plant)."""
    return str(d.get("customer_code") or d.get("customer") or d.get("plant") or "").strip()


def customer_for(cfg, bench_code: str) -> str:
    """bench_customer_map: 'HVF1=HMIL1;MSIL-GGN=MSIL1' (Bench customer / plant code -> AssetTrack customer code).
    Not in the map: the Bench code is used as it is."""
    m = {}
    for part in (cfg.get("bench_customer_map") or "").replace(",", ";").split(";"):
        if "=" in part:
            a, b = part.split("=", 1); m[a.strip().upper()] = b.strip()
    return m.get((bench_code or "").upper(), bench_code or "?")


PLANT_KEYS = ("ais_plant", "aisplant", "plant_code", "from_plant", "source_plant", "dispatch_plant", "ship_from", "org_code", "organization", "warehouse")


def sync_trip_cards(db: Session, trip_no: str, picks: dict) -> bool:
    """Keep the trip's PDI check sheet (BenchTripCard) equal to the Bench: new cards added, cards the Bench took off
    marked removed (PDI reject / alternate), a card put back made active again. Returns True when anything changed."""
    have = {c.lpn_no: c for c in db.query(models.BenchTripCard).filter_by(trip_no=trip_no).all()}
    changed = False
    for lpn, pr in picks.items():
        q = int(float(pr.get("qty") or 0))
        st = card_pdi(pr)
        why = (str(pr.get("pdi_reason")).strip()[:200] or None) if pr.get("pdi_reason") else None
        gone = st == "REJECT"                        # rejected = off the trip for good
        c = have.get(lpn)
        if c is None:
            db.add(models.BenchTripCard(trip_no=trip_no, lpn_no=lpn, part_no=(pr.get("item_code") or None), qty=q, pdi_status=st, pdi_reason=why,
                                        removed_at=utcnow() if gone else None)); changed = True
        elif ((c.removed_at is not None) != gone or c.qty != q or (pr.get("item_code") and c.part_no != pr.get("item_code"))
              or (c.pdi_status or "OK") != st or c.pdi_reason != why):
            c.removed_at = (c.removed_at or utcnow()) if gone else None
            c.qty = q; c.part_no = pr.get("item_code") or c.part_no; c.pdi_status = st; c.pdi_reason = why; changed = True
    for lpn, c in have.items():
        if lpn not in picks and c.removed_at is None:
            c.removed_at = utcnow(); changed = True
    if changed:
        db.flush()
    return changed


def plant_for(db: Session, cfg: dict, d: dict) -> str | None:
    """AIS plant of a Bench dispatch (plant-wise planning on one Bench): a plant field of the dispatch, translated by
    bench_plant_map ('3001=CHN;CHENNAI=CHN;TALOJA=TLJ') or taken as it is when it is an AssetTrack plant code; otherwise
    the default plant of the link (bench_plant). None = cannot tell -> the dispatch is not taken."""
    m = {}
    for part in (cfg.get("bench_plant_map") or "").replace(",", ";").split(";"):
        if "=" in part:
            a, b = part.split("=", 1); m[a.strip().upper()] = b.strip().upper()
    for k in PLANT_KEYS:
        v = str(d.get(k) or "").strip().upper()
        if not v:
            continue
        code = m.get(v, v)
        if db.get(models.Plant, code):
            return code
    dflt = (cfg.get("bench_plant") or "").upper()
    return dflt if dflt and db.get(models.Plant, dflt) else None


def pull(db: Session, fetch=None) -> dict:
    """fetch(path) -> json; injectable for tests."""
    cfg = get_settings(db)
    _state["last_run"] = utcnow()
    api = (lambda path: _get(cfg, path)) if api_ready(cfg) else None
    source, note = "TEST", None
    if not fetch:
        if cfg["bench_source"] == "SQL":
            fetch, source = sql_fetch(cfg), "SQL"
        elif api:
            fetch, source = api, "API"
        else:
            raise RuntimeError("Dispatch Bench link not configured (URL / user)")
    created = updated = n_lpn = no_plant = 0; per_plant = {}; changed_trips: set[str] = set()
    try:
        disp = fetch("/api/dispatches/recent?limit=300").get("dispatches", [])
    except Exception as e:
        if source != "SQL" or not api:
            raise
        note = f"SQL read failed, Bench API used: {str(e)[:150]}"   # fallback: the Bench web server
        log.warning("bench: %s", note)
        fetch, source = api, "API (SQL failed)"
        disp = fetch("/api/dispatches/recent?limit=300").get("dispatches", [])
    for d in disp:
        did = str(d.get("id") or d.get("dispatch_id"))
        status = (d.get("dispatch_status") or "").lower()
        if not did:
            continue
        if status in ("skipped", "cancelled", "canceled"):
            # cancelled in the Bench: an AssetTrack trip still OPEN with nothing loaded is cancelled too (cards released)
            for ck in db.query(models.PickList).filter(models.PickList.ext_ref == did, models.PickList.status == "OPEN",
                                                       models.PickList.source.in_(["DISPATCH_BENCH", "HMIL_BENCH"])).all():
                if not db.query(models.PickListLine).filter_by(picklist_no=ck.picklist_no).count():
                    for l in db.query(models.Lpn).filter_by(reserved_for=ck.picklist_no, status="RESERVED").all():
                        l.status, l.reserved_for, l.reserved_at = "AVAILABLE", None, None
                    ck.status = "CANCELLED"; ck.remarks = ((ck.remarks or "") + " · cancelled in the Dispatch Bench")[:250]
            continue
        sent = d.get("sent_at") or ""
        try:
            if sent and (datetime.now() - datetime.fromisoformat(sent[:19])).days > cfg["bench_days"]:
                continue
        except Exception:
            pass
        plant = plant_for(db, cfg, d)                 # plant-wise planning: each trip goes to its own plant
        if not plant:
            no_plant += 1
            continue
        per_plant[plant] = per_plant.get(plant, 0) + 1
        pk = (db.query(models.PickList).filter(models.PickList.plant_code == plant, models.PickList.ext_ref == did,
                                               models.PickList.source.in_(["DISPATCH_BENCH", "HMIL_BENCH"])).first())
        no = pk.picklist_no if pk else f"DB-{plant}-{did}"
        if pk and pk.status in ("DISPATCHED", "CLOSED", "CANCELLED"):
            continue                 # gone out / closed in AssetTrack: frozen
        picks = fetch(f"/api/picks?dispatch_id={did}").get("picks", [])
        lp = {}
        for pr in picks:
            lpn = (pr.get("picked_lpn") or "").strip()
            if lpn:
                lp[lpn] = pr        # last pick wins (repicks replace)
        if pk:
            if sync_trip_cards(db, no, lp):          # the PDI check sheet changed (e.g. reject -> alternate card)
                changed_trips.add(no)
            if pk.status != "OPEN":
                continue             # loaded / linked: the card list is kept current, the rest is frozen
        if not pk:
            pk = models.PickList(picklist_no=no, plant_code=plant, customer_code=customer_for(cfg, bench_customer(d)), dispatch_type="CUSTOMER",
                                 source="DISPATCH_BENCH", ext_ref=did, qty=0, part_qty=0, status="OPEN", created_by="DISPATCH_BENCH",
                                 remarks=" · ".join(x for x in (f"Bench trip {d.get('trip_id')}", d.get("section"), d.get("shift_name"), d.get("segment")) if x))
            db.add(pk); db.flush(); created += 1
        else:
            updated += 1
        pk.vehicle_no = (d.get("vehicle") or pk.vehicle_no or "").upper().replace(" ", "") or None
        pdi = d.get("pdi_by") or d.get("pdi_user") or d.get("qc_by") or d.get("pdi_name")
        sup = d.get("shift_supervisor") or d.get("supervisor") or d.get("supervisor_name") or d.get("created_by_name") or d.get("created_by")
        if pdi:
            pk.pdi_sign = (f"{pdi} ({d['pdi_login']})" if d.get("pdi_login") else str(pdi))[:120]
        if sup:
            pk.supervisor_sign = (f"{sup} ({d['supervisor_login']})" if d.get("supervisor_login") else str(sup))[:120]
        total = 0
        live = {lpn for lpn, pr in lp.items() if card_pdi(pr) != "REJECT"}   # rejected cards are not reserved for the trip
        for lpn, pr in lp.items():
            if lpn not in live:
                continue
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
            if l.lpn_no not in live:
                l.status, l.reserved_for, l.reserved_at = "AVAILABLE", None, None
        if sync_trip_cards(db, no, lp):
            changed_trips.add(no)
        bound = sum(r.qty for r in db.query(models.PickListLpn).filter_by(picklist_no=no).all())
        pk.part_qty = max(total, bound)
        pk.qty = max(pk.qty or 0, db.query(models.PickListLine).filter_by(picklist_no=no).count(), 1)
    db.flush()
    if changed_trips:                                # a new / changed Bench trip may now prove an open GCS (link from both sides)
        from . import gcs as gcssvc
        gcssvc.relink_open(db, plants={db.get(models.PickList, t).plant_code for t in changed_trips if db.get(models.PickList, t)})
    db.commit()
    err = " · ".join(x for x in (note, f"{no_plant} dispatch(es) without a known AIS plant - set the plant map or default plant" if no_plant else None) if x) or None
    _state.update(last_ok=utcnow(), last_error=err, created=created, updated=updated, lpns=n_lpn, plants=per_plant, no_plant=no_plant, source=source)
    return {"dispatches": len(disp), "created": created, "updated": updated, "lpns": n_lpn, "plants": per_plant, "no_plant": no_plant, "source": source}


def status() -> dict:
    return dict(_state)


_lock = threading.Lock()


def pull_if_stale(SessionLocal, max_age_sec: int = 15):
    """Called when an HHT syncs: if the last Bench pull is older than max_age_sec, pull now in the background so the
    HHT gets the newest trips on its very next sync."""
    last = _state.get("last_run")
    if last and (utcnow() - last).total_seconds() < max_age_sec:
        return
    if not _lock.acquire(blocking=False):
        return

    def run():
        try:
            with SessionLocal() as db:
                if get_settings(db)["bench_enabled"]:
                    pull(db)
        except Exception as e:
            _state["last_error"] = str(e)[:300]
        finally:
            _lock.release()
    threading.Thread(target=run, name="bench-pull-on-demand", daemon=True).start()


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
            time.sleep(max(10, wait))
    t = threading.Thread(target=loop, name="dispatch-bench-pull", daemon=True)
    t.start()
