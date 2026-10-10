from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, config
from ..db import get_db
from ..security import check_pw, hash_pw, make_token, current_user, Principal, load_perms, audit, require_client_version, pin_in_use

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


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.user_id == body.user_id.strip().lower()).first()
    if not u or not u.active:
        raise HTTPException(401, "Invalid user or password")
    if body.device_id:
        require_client_version(body.app_version)
    if u.locked_until and u.locked_until > datetime.utcnow():
        raise HTTPException(423, f"Account locked until {u.locked_until:%H:%M} UTC")
    if not check_pw(body.password, u.password_hash):
        u.failed_logins += 1
        if u.failed_logins >= config.MAX_FAILED_LOGINS:
            u.locked_until = datetime.utcnow() + timedelta(minutes=config.LOCK_MINUTES)
            u.failed_logins = 0
        db.commit()
        raise HTTPException(401, "Invalid user or password")
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
    return {"token": make_token(u), "user_id": u.user_id, "name": u.full_name, "plant": u.plant_code,
            "roles": u.role_codes, "perms": sorted(perms), "supervisor": u.supervisor_allowed,
            "must_change_pw": u.must_change_pw, "server_version": config.APP_VERSION, "min_client": config.API_MIN_CLIENT}


@router.get("/me")
def me(p: Principal = Depends(current_user)):
    u = p.user
    return {"user_id": u.user_id, "name": u.full_name, "plant": u.plant_code, "roles": u.role_codes,
            "perms": sorted(p.perms), "supervisor": u.supervisor_allowed, "must_change_pw": u.must_change_pw}


@router.post("/change-password")
def change_pw(body: ChangePwIn, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(models.User, p.user.id)
    if not check_pw(body.old_password, u.password_hash):
        raise HTTPException(400, "Old password wrong")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    u.password_hash = hash_pw(body.new_password); u.must_change_pw = False
    audit(db, p, "CHANGE_PASSWORD", "user", u.user_id)
    db.commit()
    return {"ok": True}


@router.post("/set-pin")
def set_pin(body: SetPinIn, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(models.User, p.user.id)
    if not u.supervisor_allowed:
        raise HTTPException(403, "Not a supervisor")
    if not body.pin.isdigit() or len(body.pin) < 4:
        raise HTTPException(400, "PIN must be 4+ digits")
    if pin_in_use(db, u.plant_code, body.pin, u.id):
        raise HTTPException(400, "This PIN is already used by another supervisor of your plant - choose a different one")
    u.supervisor_pin_hash = hash_pw(body.pin)
    audit(db, p, "SET_PIN", "user", u.user_id)
    db.commit()
    return {"ok": True}
