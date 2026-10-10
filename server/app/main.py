"""
AIS Pallet Asset Tracking - API server
Developed by DT
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from . import config, models, integration, bench, reminders  # noqa: F401 (reminders registers email_log)
from .db import engine, Base, SessionLocal, add_missing_columns
from .security import ROLE_SEED, NEW_PERMS, hash_pw
from .routers import auth, masters, imports, sync, documents, reports, external, prints, activity, parts, integrations
from .activity import ActivityMiddleware

log = logging.getLogger("pallet")


def seed(db: Session):
    for code, (name, scope, perms) in ROLE_SEED.items():
        r = db.get(models.Role, code)
        if not r:
            r = models.Role(code=code, name=name, scope=scope); db.add(r)
            r.permissions = [models.RolePermission(role_code=code, perm=x) for x in perms]
        else:   # upgrade: add permissions introduced in newer versions (never removes admin edits)
            have = {x.perm for x in r.permissions}
            for x in perms:
                if x not in have and x in NEW_PERMS:
                    r.permissions.append(models.RolePermission(role_code=code, perm=x))
    if db.query(models.User).count() == 0:
        u = models.User(user_id=config.BOOTSTRAP_ADMIN_USER, full_name="Central Admin", password_hash=hash_pw(config.BOOTSTRAP_ADMIN_PASS),
                        plant_code=None, supervisor_allowed=True, must_change_pw=True)
        u.roles = [models.UserRole(role_code="CADMIN")]
        db.add(u)
        log.warning("Bootstrap admin '%s' created - change the password at first login", config.BOOTSTRAP_ADMIN_USER)
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    add_missing_columns()
    with SessionLocal() as db:
        seed(db)
        # HMIL Planning Bench became the Dispatch Planning Bench (all customers)
        db.query(models.PickList).filter(models.PickList.source == "HMIL_BENCH").update({"source": "DISPATCH_BENCH"}, synchronize_session=False)
        db.commit()
    import os
    if os.getenv("PALLET_BENCH_SCHEDULER", "1") == "1":
        bench.start_scheduler(SessionLocal)
    yield


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan,
              description=f"{config.DEVELOPER} · Returnable pallet asset tracking for AIS Glass")
from .routers import dashboard, reminders as reminders_router
for r in (auth, masters, imports, sync, documents, reports, external, prints, activity, parts, integrations, dashboard, reminders_router):
    app.include_router(r.router)
app.include_router(external.admin)
app.add_middleware(ActivityMiddleware)

static_dir = config.BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_dir / "index.html")


@app.get("/api/v1/health")
def health():
    try:
        with SessionLocal() as db:
            db.execute(models.Plant.__table__.select().limit(1))
        db_ok = True
    except Exception:
        db_ok = False
    return {"app": config.APP_NAME, "version": config.APP_VERSION, "developer": config.DEVELOPER, "db": "ok" if db_ok else "error",
            "integration_mode": integration.MODE, "ports": config.SERVER_PORTS, "min_client": config.API_MIN_CLIENT}


@app.post("/api/v1/jobs/retry")
def job_retry():
    """Called by the scheduler every 5 min (or manually). No auth: bind to localhost in IIS/nginx."""
    with SessionLocal() as db:
        return integration.run_retries(db)
