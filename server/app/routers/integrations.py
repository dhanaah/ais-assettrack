"""Integration settings & manual triggers (Dispatch Planning Bench pull - all customers). Developed by DT"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import bench, gcs
from ..db import get_db
from ..security import need, Principal, audit, current_user

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


class BenchIn(BaseModel):
    bench_enabled: bool = False
    bench_url: str | None = None
    bench_user: str | None = None
    bench_password: str | None = None       # blank = keep current
    bench_plant: str | None = None
    bench_customer_map: str | None = None
    bench_interval_sec: int | None = 60
    bench_days: int | None = 3


@router.get("/dispatch-bench")
@router.get("/hmil-bench", include_in_schema=False)          # old name kept
def get_bench(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("INTEGRATION_CONFIG") or p.has("REPORTS_ALL") or p.has("REPORTS_PLANT")):
        raise HTTPException(403, "Not allowed")
    cfg = bench.get_settings(db)
    cfg["bench_password"] = "••••••" if cfg.get("bench_password") else ""
    return {"settings": cfg, "status": bench.status()}


@router.post("/dispatch-bench")
@router.post("/hmil-bench", include_in_schema=False)
def save_bench(body: BenchIn, request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    d = body.model_dump()
    if d.get("bench_plant"):
        d["bench_plant"] = d["bench_plant"].upper()
    bench.save_settings(db, d)
    audit(db, p, "BENCH_SETTINGS", "settings", "dispatch-bench", None, body.model_dump(exclude={"bench_password"}), request)
    db.commit()
    return {"ok": True}


@router.post("/dispatch-bench/pull")
@router.post("/hmil-bench/pull", include_in_schema=False)
def pull_now(request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    try:
        res = bench.pull(db)
    except Exception as e:
        bench._state["last_error"] = str(e)[:300]
        raise HTTPException(502, f"Dispatch Bench pull failed: {e}")
    audit(db, p, "BENCH_PULL", "settings", "dispatch-bench", None, res, request)
    db.commit()
    return res


# ---------------------------------------------------------------- GCS inbox (FTP)
class GcsIn(BaseModel):
    gcs_enabled: bool = False
    gcs_host: str | None = None
    gcs_port: int | None = 21
    gcs_user: str | None = None
    gcs_password: str | None = None         # blank = keep current
    gcs_folder: str | None = "/"
    gcs_pattern: str | None = None
    gcs_done_folder: str | None = None
    gcs_interval_sec: int | None = 60
    gcs_plant: str | None = None
    gcs_tls: bool = False


@router.get("/gcs-inbox")
def get_gcs(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("INTEGRATION_CONFIG") or p.has("REPORTS_ALL") or p.has("LOGISTICS_APPROVE")):
        raise HTTPException(403, "Not allowed")
    cfg = gcs.get_settings(db)
    cfg["gcs_password"] = "••••••" if cfg.get("gcs_password") else ""
    return {"settings": cfg, "status": gcs.status()}


@router.post("/gcs-inbox")
def save_gcs(body: GcsIn, request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    d = body.model_dump()
    if d.get("gcs_plant"):
        d["gcs_plant"] = d["gcs_plant"].upper()
    gcs.save_settings(db, d)
    audit(db, p, "GCS_SETTINGS", "settings", "gcs-inbox", None, body.model_dump(exclude={"gcs_password"}), request)
    db.commit()
    return {"ok": True}


@router.post("/gcs-inbox/pull")
def pull_gcs(request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    try:
        res = gcs.pull(db)
    except Exception as e:
        gcs._state["last_error"] = str(e)[:300]
        raise HTTPException(502, f"GCS inbox pull failed: {e}")
    audit(db, p, "GCS_PULL", "settings", "gcs-inbox", None, res, request)
    db.commit()
    return res


@router.post("/gcs-inbox/upload")
async def upload_gcs(request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Drop a GCS file by hand (same formats as the FTP inbox) - for testing or when FTP is down."""
    if not (p.has("INTEGRATION_CONFIG") or p.has("LOGISTICS_APPROVE") or p.has("CHALLAN_REQUEST")):
        raise HTTPException(403, "Not allowed")
    form = await request.form()
    f = form.get("file")
    if f is None:
        raise HTTPException(400, "file required")
    plant = p.plant or (form.get("plant") or "").upper()
    if not plant:
        raise HTTPException(400, "plant required")
    data = await f.read()
    out = {"created": 0, "updated": 0, "skipped": 0, "cancelled": 0, "gcs": []}
    for head, items in gcs.group_rows(gcs.parse_file(f.filename, data)):
        what, k = gcs.apply_gcs(db, plant, head, f.filename, items)
        out[what] += 1
        if k:
            out["gcs"].append(k.gcs_no)
    audit(db, p, "GCS_UPLOAD", "settings", "gcs-inbox", None, {"file": f.filename} | {k: v for k, v in out.items() if k != "gcs"}, request)
    db.commit()
    return out
