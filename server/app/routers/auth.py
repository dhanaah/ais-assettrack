"""Sign-in, password change, supervisor PIN, link tickets.
Developed by DT"""
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, config
from ..db import get_db
from ..security import check_pw, hash_pw, make_token, make_ticket, current_user, Principal, load_perms, audit, require_client_version, pin_in_use, pw_rule

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    user_id: str
    password: str
    device_id: str | None = None
    app_version: str | None = None


class ChangePwIn(BaseModel):
    old_password: str
    new_password: str


class SetPinIn(BaseModel):
    pin: str


_DUMMY = hash_pw("not-a-user-password")


@router.post("/ticket")
def ticket(p: Principal = Depends(current_user)):
    """2-minute ticket for a print / download link opened in a new tab."""
    return {"ticket": make_ticket(p.user)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.user_id == body.user_id.strip().lower()).first()
    if not u or not u.active:
        check_pw(body.password, _DUMMY)            # same time as a real check: user names cannot be guessed from the reply time
        raise HTTPException(401, "Invalid user or password")
    if body.device_id:
        require_client_version(body.app_version)
    if u.locked_until and u.locked_until > datetime.utcnow():
        raise HTTPException(423, f"Account locked until {u.locked_until:%H:%M} UTC")
    if u.customer_code:
        raise HTTPException(403, "Customer staff sign in on the customer HHT (paired by AIS) only")
    if not check_pw(body.password, u.password_hash):
        u.failed_logins += 1
        if u.failed_logins >= config.MAX_FAILED_LOGINS:
            u.locked_until = datetime.utcnow() + timedelta(minutes=config.LOCK_MINUTES)
            u.failed_logins = 0
        db.commit()
        raise HTTPException(401, "Invalid user or password")
    if (u.must_change_pw and u.user_id == config.BOOTSTRAP_ADMIN_USER and body.password == config.BOOTSTRAP_ADMIN_PASS
            and (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost", "testclient")):
        # the documented first password works only on the server PC itself, so nobody on the network can take the admin first
        raise HTTPException(403, "First admin sign-in only on the server PC (http://localhost:8001) - set a new password there")
    u.failed_logins = 0; u.locked_until = None; u.last_login = datetime.utcnow()
    if body.device_id:
        if u.device_id and u.device_id != body.device_id:
            raise HTTPException(403, f"User is bound to device {u.device_id}")
        d = db.get(models.Device, body.device_id)
        if d and d.blocked:
            raise HTTPException(403, "Device is blocked by admin")
        if not d:
            d = models.Device(device_id=body.device_id, plant_code=u.plant_code)
            db.add(d)
        d.last_seen = datetime.utcnow(); d.last_user = u.user_id; d.app_version = body.app_version
        if u.plant_code:
            d.plant_code = u.plant_code
    perms = load_perms(db, u)
    audit(db, Principal(u, perms), "LOGIN", "user", u.user_id, request=request)
    db.commit()
    from ..security import allowed_plants
    pls = allowed_plants(db, u)
    names = {x.code: x.name for x in db.query(models.Plant).filter(models.Plant.code.in_(pls)).all()} if pls else {}
    return {"token": make_token(u), "user_id": u.user_id, "name": u.full_name, "plant": u.plant_code,
            "plants": [{"code": x, "name": names.get(x, x)} for x in pls],
            "roles": u.role_codes, "perms": sorted(perms), "supervisor": u.supervisor_allowed,
            "must_change_pw": u.must_change_pw, "server_version": config.APP_VERSION, "min_client": config.API_MIN_CLIENT,
            "picklist_source": config.PICKLIST_SOURCE}


@router.get("/me")
def me(p: Principal = Depends(current_user)):
    u = p.user
    return {"user_id": u.user_id, "name": u.full_name, "plant": u.plant_code, "roles": u.role_codes,
            "perms": sorted(p.perms), "supervisor": u.supervisor_allowed, "must_change_pw": u.must_change_pw, "picklist_source": config.PICKLIST_SOURCE}


@router.post("/change-password")
def change_pw(body: ChangePwIn, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(models.User, p.user.id)
    if not check_pw(body.old_password, u.password_hash):
        raise HTTPException(400, "Old password wrong")
    pw_rule(body.new_password)
    u.password_hash = hash_pw(body.new_password); u.must_change_pw = False
    audit(db, p, "CHANGE_PASSWORD", "user", u.user_id)
    db.commit()
    return {"ok": True, "token": make_token(u)}        # old sign-ins stop; this browser continues with the new token


_SETPIN_TRIES: dict[int, list[float]] = {}


@router.post("/set-pin")
def set_pin(body: SetPinIn, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(models.User, p.user.id)
    if not u.supervisor_allowed:
        raise HTTPException(403, "Not a supervisor")
    now = time.time()
    tries = [t for t in _SETPIN_TRIES.get(u.id, []) if now - t < 600]
    if len(tries) >= 5:                       # stops trying PIN after PIN to find other supervisors' PINs
        raise HTTPException(429, "Too many PIN changes - try again in 10 minutes")
    _SETPIN_TRIES[u.id] = tries + [now]
    if not body.pin.isdigit() or len(body.pin) < 6:
        raise HTTPException(400, "PIN must be at least 6 digits")
    if len(set(body.pin)) < 3 or body.pin in "01234567890" or body.pin in "09876543210":
        raise HTTPException(400, "PIN too simple - avoid repeated or running digits")
    if pin_in_use(db, u.plant_code, body.pin, u.id):
        raise HTTPException(400, "PIN not accepted - choose a different PIN")
    u.supervisor_pin_hash = hash_pw(body.pin)
    audit(db, p, "SET_PIN", "user", u.user_id)
    db.commit()
    return {"ok": True}
