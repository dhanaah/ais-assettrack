"""Integration settings & manual triggers (Dispatch Planning Bench pull - all customers). Developed by DT"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import bench, gcs, models
from ..db import get_db
from ..security import need, Principal, audit, current_user

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


class BenchIn(BaseModel):
    bench_enabled: bool = False
    bench_url: str | None = None
    bench_user: str | None = None
    bench_password: str | None = None       # blank = keep current
    bench_plant_map: str | None = None
    bench_plant: str | None = None
    bench_customer_map: str | None = None
    bench_interval_sec: int | None = 60
    bench_days: int | None = 3
    bench_source: str | None = "API"            # API (Bench web server) | SQL (read-only from the Bench SQL Server views)
    bench_sql_server: str | None = None         # blank = the SQL Server AssetTrack itself uses (same login)
    bench_sql_database: str | None = None
    bench_sql_user: str | None = None           # blank = Windows login (IIS app pool / tray user)
    bench_sql_password: str | None = None       # blank = keep current
    bench_sql_schema: str | None = None          # schema of the Bench tables (dbo)


@router.get("/dispatch-bench")
@router.get("/hmil-bench", include_in_schema=False)          # old name kept
def get_bench(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("INTEGRATION_CONFIG") or p.has("REPORTS_ALL") or p.has("REPORTS_PLANT")):
        raise HTTPException(403, "Not allowed")
    cfg = bench.get_settings(db)
    for key in bench.SECRET_KEYS:
        cfg[key] = "••••••" if cfg.get(key) else ""
    cfg.pop("bench_sql_url", None)
    return {"settings": cfg, "status": bench.status()}


@router.post("/dispatch-bench")
@router.post("/hmil-bench", include_in_schema=False)
def save_bench(body: BenchIn, request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    d = body.model_dump()
    if d.get("bench_plant"):
        d["bench_plant"] = d["bench_plant"].upper()
    d["bench_source"] = (d.get("bench_source") or "API").upper()
    if d["bench_source"] not in ("API", "SQL"):
        raise HTTPException(400, "Bench source must be API or SQL")
    if d.get("bench_sql_schema"):
        try:
            bench._schema(d)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    if d.get("bench_sql_database"):
        try:
            bench.db_list(d)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    bench.save_settings(db, d)
    audit(db, p, "BENCH_SETTINGS", "settings", "dispatch-bench", None, body.model_dump(exclude=set(bench.SECRET_KEYS)), request)
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


@router.post("/dispatch-bench/test-sql")
def test_sql(p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    """Can AssetTrack read the two Bench views with the saved settings? (read only)"""
    try:
        return bench.sql_test(bench.get_settings(db))
    except Exception as e:
        raise HTTPException(502, f"Bench SQL read failed: {str(e)[:300]}")


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
    ps = gcs.plant_status()
    q = db.query(models.Plant).filter((models.Plant.active == True) | (models.Plant.active.is_(None)))  # noqa: E712  old DBs: active may be NULL; = 1 for SQL Server
    if p.plant:
        q = q.filter(models.Plant.code == p.plant)
    plants = [{"code": x.code, "name": x.name, "gcs_enabled": bool(x.gcs_enabled), "gcs_folder": x.gcs_folder, "gcs_done_folder": x.gcs_done_folder,
               "gcs_host": x.gcs_host, "gcs_port": x.gcs_port, "gcs_user": x.gcs_user, "has_password": bool(x.gcs_password),
               "status": ps.get(x.code, {})} for x in q.order_by(models.Plant.code).all()]
    return {"settings": cfg, "status": gcs.status(), "plants": plants}


class PlantFtpIn(BaseModel):
    plant: str
    gcs_enabled: bool = False
    gcs_folder: str | None = None
    gcs_done_folder: str | None = None
    gcs_host: str | None = None
    gcs_port: int | None = None
    gcs_user: str | None = None
    gcs_password: str | None = None      # blank = keep


@router.post("/gcs-inbox/plant")
def save_plant_ftp(body: PlantFtpIn, request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    pl = db.get(models.Plant, body.plant.upper())
    if not pl:
        raise HTTPException(404, "Unknown plant")
    p.require_plant(pl.code)
    if body.gcs_enabled and not (body.gcs_folder or "").strip():
        raise HTTPException(400, "Set the FTP folder for this plant first")
    for k in ("gcs_enabled", "gcs_folder", "gcs_done_folder", "gcs_host", "gcs_port", "gcs_user"):
        v = getattr(body, k)
        setattr(pl, k, (v.strip() or None) if isinstance(v, str) else v)
    if body.gcs_password:
        pl.gcs_password = body.gcs_password
    audit(db, p, "GCS_PLANT_FTP", "plant", pl.code, None, body.model_dump(exclude={"gcs_password"}), request)
    db.commit()
    return {"ok": True}


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
def pull_gcs(request: Request, plant: str | None = None, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    try:
        res = gcs.pull(db, plant=plant or p.plant)
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
