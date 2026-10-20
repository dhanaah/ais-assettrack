"""Shared masters from the Dispatch Planning Bench (1.37.0 · Developed by DT).
The Bench OWNS Plant and Customer identity; AssetTrack copies them one way on every Bench pull:
  Plant    : code (AIS code, e.g. AAC) + name                      -> plants (from_bench = 1)
  Customer : Oracle customer no. = AssetTrack customer code, name, type, GSTIN, address, city, state, active,
             one row per AIS plant that serves the customer         -> customers (from_bench = 1, bench_code = HMIL ...)
AssetTrack-only fields (mail ids, holding / reminder days, return mode, chargeable, challan / tag series, GCS settings)
are never touched. A Bench customer without an Oracle customer no. is skipped and listed in the status.
Bench-owned fields cannot be edited / uploaded in AssetTrack (see LOCKED_*)."""
from sqlalchemy.orm import Session
from . import models

LOCKED_PLANT = ("name",)
LOCKED_CUSTOMER = ("name", "ctype", "gstin", "address", "city", "state", "active")
CTYPES = ("OEM", "OES", "AFM", "EXP")


def sync(db: Session, fetch) -> dict:
    from . import bench
    data = fetch("/api/masters/shared")
    plants = [p for p in (data.get("plants") or []) if (p.get("code") or "").strip()]
    custs = data.get("customers") or []
    changed = 0; missing = []
    for p in plants:
        code = p["code"].strip().upper()[:10]
        obj = db.get(models.Plant, code)
        if not obj:
            obj = models.Plant(code=code, name=p.get("name") or code, active=bool(int(p.get("active", 1) or 0))); db.add(obj)
        if obj.name != (p.get("name") or obj.name) or not obj.from_bench:
            changed += 1
        obj.name = (p.get("name") or obj.name or code)[:100]
        obj.from_bench = True
        if not obj.ebs_org_id and p.get("org_code"):
            obj.ebs_org_id = p["org_code"][:20]              # Oracle org: filled once, AssetTrack may refine it
    db.flush()
    omap = {}
    for c in custs:
        bcode = (c.get("code") or "").strip().upper()
        ora = (c.get("oracle_cust_no") or "").strip()
        if not ora:
            missing.append(bcode); continue
        omap[bcode] = ora
        ctype = (c.get("ctype") or "").upper()
        vals = {"name": (c.get("name") or ora)[:120], "ctype": ctype if ctype in CTYPES else None,
                "gstin": (c.get("gstin") or None), "address": (c.get("address") or None),
                "city": (c.get("city") or None), "state": (c.get("state") or None), "active": bool(int(c.get("active", 1) or 0))}
        for pl in c.get("plants") or []:
            pl = (pl or "").upper()
            if not db.get(models.Plant, pl):
                continue
            obj = db.query(models.Customer).filter_by(code=ora, plant_code=pl).first()
            if not obj and bcode != ora:            # an earlier AssetTrack row under the Bench short code -> renamed to the Oracle no.
                old = db.query(models.Customer).filter_by(code=bcode, plant_code=pl).first()
                if old and not db.query(models.PickList).filter_by(plant_code=pl, customer_code=bcode).first():
                    old.code = ora; obj = old
            if not obj:
                obj = models.Customer(code=ora, plant_code=pl, return_mode="B", chargeable=True); db.add(obj)
            if any(getattr(obj, k) != v for k, v in vals.items()) or not obj.from_bench or obj.bench_code != bcode:
                changed += 1
            for k, v in vals.items():
                setattr(obj, k, v)
            obj.bench_code, obj.from_bench = bcode, True
    db.flush()
    bench._cust_oracle.clear(); bench._cust_oracle.update(omap)
    return {"ok": True, "plants": len(plants), "customers": len(omap), "changed": changed, "missing_oracle_no": missing}


def strip_locked(obj, vals: dict, kind: str) -> list:
    """Remove Bench-owned fields from an edit of a Bench record. Returns the fields that were changed and dropped."""
    if not obj or not getattr(obj, "from_bench", False):
        return []
    lock = LOCKED_PLANT if kind == "plants" else LOCKED_CUSTOMER if kind == "customers" else ()
    dropped = [k for k in lock if k in vals and vals[k] != getattr(obj, k)]
    for k in lock:
        vals.pop(k, None)
    return dropped
