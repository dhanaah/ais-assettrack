"""Integration settings & manual triggers (HMIL Planning Bench pull). Developed by DT"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import bench
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


@router.get("/hmil-bench")
def get_bench(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("INTEGRATION_CONFIG") or p.has("REPORTS_ALL") or p.has("REPORTS_PLANT")):
        raise HTTPException(403, "Not allowed")
    cfg = bench.get_settings(db)
    cfg["bench_password"] = "••••••" if cfg.get("bench_password") else ""
    return {"settings": cfg, "status": bench.status()}


@router.post("/hmil-bench")
def save_bench(body: BenchIn, request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    d = body.model_dump()
    if d.get("bench_plant"):
        d["bench_plant"] = d["bench_plant"].upper()
    bench.save_settings(db, d)
    audit(db, p, "BENCH_SETTINGS", "settings", "hmil-bench", None, body.model_dump(exclude={"bench_password"}), request)
    db.commit()
    return {"ok": True}


@router.post("/hmil-bench/pull")
def pull_now(request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    try:
        res = bench.pull(db)
    except Exception as e:
        bench._state["last_error"] = str(e)[:300]
        raise HTTPException(502, f"HMIL Bench pull failed: {e}")
    audit(db, p, "BENCH_PULL", "settings", "hmil-bench", None, res, request)
    db.commit()
    return res
