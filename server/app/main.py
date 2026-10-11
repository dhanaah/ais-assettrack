"""
AIS Pallet Asset Tracking - API server
Developed by DT
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
from pathlib import Path
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
        from . import gcs
        gcs.start_scheduler(SessionLocal)
    yield


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan,
              description=f"{config.DEVELOPER} · Returnable pallet asset tracking for AIS Glass")
from .routers import dashboard, reminders as reminders_router, masterio, exports
for r in (auth, masters, imports, sync, documents, reports, external, prints, activity, parts, integrations, dashboard, reminders_router, masterio, exports):
    app.include_router(r.router)
app.include_router(external.admin)
app.add_middleware(ActivityMiddleware)

static_dir = config.BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_dir / "index.html")


@app.get("/hht-setup", include_in_schema=False)
def hht_setup():
    """Page with the server QR: on the HHT, Setup > Server > Scan server QR. No login needed (addresses only)."""
    import segno, io, html
    from fastapi.responses import HTMLResponse
    from .routers.external import server_setup_text, _lan_addresses
    t = server_setup_text(); buf = io.BytesIO(); segno.make(t, error="m").save(buf, kind="svg", scale=7, border=3, dark="#0f172a")
    addrs = "".join(f"<li><code>{html.escape(a)}</code></li>" for a in _lan_addresses())
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AssetTrack - HHT setup QR</title><link rel="icon" href="/static/favicon.png"><style>body{{font-family:system-ui,Segoe UI,Arial;margin:0;background:#f1f5f9;color:#0f172a}}
.c{{max-width:560px;margin:24px auto;background:#fff;border-radius:16px;padding:24px;box-shadow:0 6px 24px #0f172a14;text-align:center}}
h1{{font-size:20px;margin:6px 0}}ol,ul{{text-align:left}}.q svg{{width:300px;height:300px}}.m{{color:#64748b;font-size:13px}}</style></head><body><div class="c">
<img src="/static/at-192.png" style="height:64px"><h1>AssetTrack server - HHT setup</h1>
<div class="q">{buf.getvalue().decode()}</div>
<ol><li>On the HHT open AssetTrack - tap <b>Setup</b> (gear on the login screen)</li><li><b>1. Server</b> - <b>Scan server QR</b> - point at this code</li>
<li>The HHT checks every address and keeps the ones that answer - then sign in</li></ol>
<p class="m">Addresses in the code (ports {", ".join(map(str, config.SERVER_PORTS or [80, 8001, 8002, 8003]))}):</p><ul class="m">{addrs}</ul>
<p class="m">The HHT must be on the same network as this server. AIS AssetTrack v{config.APP_VERSION}</p></div></body></html>""")


@app.get("/api/v1/health")
def health():
    try:
        with SessionLocal() as db:
            db.execute(models.Plant.__table__.select().limit(1))
        db_ok = True
    except Exception:
        db_ok = False
    return {"app": config.APP_NAME, "version": config.APP_VERSION, "developer": config.DEVELOPER, "db": "ok" if db_ok else "error",
            "integration_mode": integration.MODE, "ports": config.SERVER_PORTS, "min_client": config.API_MIN_CLIENT, "picklist_source": config.PICKLIST_SOURCE}


APK_DIR = Path(os.environ.get("PALLET_APK_DIR") or (Path(os.environ["PALLET_DB_URL"][10:]).parent / "apk" if os.environ.get("PALLET_DB_URL", "").startswith("sqlite:///") else config.BASE_DIR / "apk"))


def _latest_apk():
    """Newest APK in the apk folder next to the database (name must contain the version, e.g. AIS_AssetTrack_HHT_v1.9.1.apk)."""
    import re
    best = None
    if APK_DIR.exists():
        for f in APK_DIR.glob("*.apk"):
            m = re.search(r"(\d+\.\d+\.\d+)", f.name)
            if not m:
                continue
            v = tuple(int(x) for x in m.group(1).split("."))
            if best is None or v > best[0]:
                best = (v, f)
    return best


@app.get("/api/v1/app/latest")
def app_latest():
    """What the HHT compares itself with: newest APK on this server + the minimum version allowed."""
    b = _latest_apk()
    if not b:
        return {"version": None, "min_client": config.API_MIN_CLIENT}
    return {"version": ".".join(map(str, b[0])), "file": b[1].name, "url": f"/apk/{b[1].name}", "size": b[1].stat().st_size, "min_client": config.API_MIN_CLIENT}


@app.get("/apk/{name}", include_in_schema=False)
def apk_file(name: str):
    f = APK_DIR / Path(name).name
    if not f.exists() or f.suffix.lower() != ".apk":
        from fastapi import HTTPException
        raise HTTPException(404, "APK not found")
    return FileResponse(f, media_type="application/vnd.android.package-archive", filename=f.name)


@app.post("/api/v1/jobs/retry")
def job_retry():
    """Called by the scheduler every 5 min (or manually). No auth: bind to localhost in IIS/nginx."""
    with SessionLocal() as db:
        return integration.run_retries(db)
