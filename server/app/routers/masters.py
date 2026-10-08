"""Masters CRUD: plants, roles, users, customers, transporters, pallets, tags, tag batches."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_
from .. import models, services
from ..db import get_db
from ..security import current_user, need, Principal, audit, hash_pw, PERMS

router = APIRouter(prefix="/api/v1", tags=["masters"])


def row(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in ("password_hash", "supervisor_pin_hash")}


# ---------------------------------------------------------------- plants
@router.get("/plants")
def list_plants(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.Plant).order_by(models.Plant.code)
    if p.plant:
        q = q.filter(models.Plant.code == p.plant)
    return [row(x) for x in q.all()]


class PlantIn(BaseModel):
    code: str
    name: str
    city: str | None = None
    state: str | None = None
    gstin: str | None = None
    address: str | None = None
    pallet_prefix: str | None = None
    tag_from: int | None = None
    tag_to: int | None = None
    challan_source: str = "APP"
    app_challan_series: str | None = None
    accept_other_plant_default: bool = True
    ebs_org_id: str | None = None
    gcs_endpoint: str | None = None
    holding_days_default: int = 30
    active: bool = True
    notes: str | None = None


@router.post("/plants")
def upsert_plant(body: PlantIn, request: Request, p: Principal = Depends(need("GLOBAL_MASTERS")), db: Session = Depends(get_db)):
    code = body.code.strip().upper()
    obj = db.get(models.Plant, code)
    old = row(obj) if obj else None
    if not obj:
        obj = models.Plant(code=code); db.add(obj)
    for k, v in body.model_dump(exclude={"code"}).items():
        setattr(obj, k, v)
    audit(db, p, "PLANT_UPSERT", "plant", code, old, body.model_dump(), request)
    db.commit()
    return row(obj)


# ---------------------------------------------------------------- roles
@router.get("/roles")
def list_roles(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for r in db.query(models.Role).order_by(models.Role.code).all():
        out.append({"code": r.code, "name": r.name, "scope": r.scope, "perms": sorted(x.perm for x in r.permissions)})
    return {"perms": PERMS, "roles": out}


class RoleIn(BaseModel):
    code: str
    name: str
    scope: str = "PLANT"
    perms: list[str]


@router.post("/roles")
def upsert_role(body: RoleIn, request: Request, p: Principal = Depends(need("INTEGRATION_CONFIG")), db: Session = Depends(get_db)):
    bad = [x for x in body.perms if x not in PERMS]
    if bad:
        raise HTTPException(400, f"Unknown permissions: {bad}")
    r = db.get(models.Role, body.code.upper())
    old = sorted(x.perm for x in r.permissions) if r else None
    if not r:
        r = models.Role(code=body.code.upper()); db.add(r)
    r.name = body.name; r.scope = body.scope
    r.permissions = [models.RolePermission(role_code=r.code, perm=x) for x in sorted(set(body.perms))]
    audit(db, p, "ROLE_UPSERT", "role", r.code, old, body.perms, request)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- users
@router.get("/users")
def list_users(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("PLANT_USERS_ADMIN") or p.has("INTEGRATION_CONFIG")):
        raise HTTPException(403, "Admin only")
    q = db.query(models.User).order_by(models.User.plant_code, models.User.user_id)
    if p.plant:
        q = q.filter(models.User.plant_code == p.plant)
    out = []
    for u in q.all():
        d = row(u); d["roles"] = u.role_codes; d["has_pin"] = bool(u.supervisor_pin_hash); out.append(d)
    return out


class UserIn(BaseModel):
    user_id: str
    full_name: str
    plant_code: str | None = None
    roles: list[str]
    password: str | None = None          # required on create
    email: str | None = None
    mobile: str | None = None
    supervisor_allowed: bool = False
    device_id: str | None = None
    active: bool = True
    notes: str | None = None


@router.post("/users")
def upsert_user(body: UserIn, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("PLANT_USERS_ADMIN") or p.has("INTEGRATION_CONFIG")):
        raise HTTPException(403, "Admin only")
    uid = body.user_id.strip().lower()
    roles = [r.upper() for r in body.roles]
    role_objs = {r.code: r for r in db.query(models.Role).filter(models.Role.code.in_(roles)).all()}
    missing = [r for r in roles if r not in role_objs]
    if missing:
        raise HTTPException(400, f"Unknown roles {missing}")
    all_scope = any(role_objs[r].scope == "ALL" for r in roles)
    plant = body.plant_code.upper() if body.plant_code else None
    if p.plant:   # plant admin: own plant only, no central roles
        if plant != p.plant:
            raise HTTPException(403, "Plant admin can create users for own plant only")
        if all_scope:
            raise HTTPException(403, "Plant admin cannot grant central roles")
    if not all_scope and not plant:
        raise HTTPException(400, "Plant_Code required for plant roles")
    if plant and not db.get(models.Plant, plant):
        raise HTTPException(400, f"Plant {plant} not found")
    u = db.query(models.User).filter(models.User.user_id == uid).first()
    old = (row(u) | {"roles": u.role_codes}) if u else None
    if not u:
        if not body.password:
            raise HTTPException(400, "Password required for new user")
        u = models.User(user_id=uid, password_hash=hash_pw(body.password), must_change_pw=True)
        db.add(u)
    elif body.password:
        u.password_hash = hash_pw(body.password); u.must_change_pw = True
    u.full_name = body.full_name; u.plant_code = None if all_scope and not plant else plant
    u.email = body.email; u.mobile = body.mobile; u.supervisor_allowed = body.supervisor_allowed
    u.device_id = body.device_id; u.active = body.active; u.notes = body.notes
    u.roles = [models.UserRole(role_code=r) for r in roles]
    audit(db, p, "USER_UPSERT", "user", uid, old, body.model_dump(exclude={"password"}), request)
    db.commit()
    return {"ok": True, "user_id": uid}


@router.post("/users/{user_id}/unlock")
def unlock(user_id: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not (p.has("PLANT_USERS_ADMIN") or p.has("INTEGRATION_CONFIG")):
        raise HTTPException(403, "Admin only")
    u = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not u:
        raise HTTPException(404, "No such user")
    p.require_plant(u.plant_code)
    u.locked_until = None; u.failed_logins = 0
    audit(db, p, "USER_UNLOCK", "user", user_id)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- customers / transporters
@router.get("/customers")
def list_customers(plant: str | None = None, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.Customer).order_by(models.Customer.plant_code, models.Customer.code)
    pl = p.scope_plant(plant)
    if pl:
        q = q.filter(models.Customer.plant_code == pl)
    return [row(x) for x in q.all()]


class CustomerIn(BaseModel):
    code: str; name: str; plant_code: str
    ctype: str | None = None; ship_to: str | None = None; city: str | None = None; state: str | None = None
    gstin: str | None = None; email_to: str | None = None; email_cc: str | None = None
    contact_name: str | None = None; contact_mobile: str | None = None
    holding_limit_days: int | None = None; reminder_every_days: int | None = None; escalation_days: int | None = None
    chargeable: bool = True; return_mode: str = "B"; challan_source_override: str | None = None
    active: bool = True; notes: str | None = None


@router.post("/customers")
def upsert_customer(body: CustomerIn, request: Request, p: Principal = Depends(need("GLOBAL_MASTERS")), db: Session = Depends(get_db)):
    obj = db.query(models.Customer).filter_by(code=body.code, plant_code=body.plant_code.upper()).first()
    old = row(obj) if obj else None
    if not obj:
        obj = models.Customer(code=body.code, plant_code=body.plant_code.upper()); db.add(obj)
    for k, v in body.model_dump(exclude={"code", "plant_code"}).items():
        setattr(obj, k, v)
    audit(db, p, "CUSTOMER_UPSERT", "customer", f"{body.code}@{body.plant_code}", old, body.model_dump(), request)
    db.commit()
    return row(obj)


@router.get("/transporters")
def list_transporters(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.Transporter).order_by(models.Transporter.code)
    if p.plant:
        q = q.filter(or_(models.Transporter.plant_codes.like(f"%{p.plant}%"), models.Transporter.plant_codes.is_(None)))
    return [row(x) for x in q.all()]


class TransporterIn(BaseModel):
    code: str; name: str
    gstin: str | None = None; contact_name: str | None = None; contact_mobile: str | None = None
    email: str | None = None; plant_codes: str | None = None; vehicles: str | None = None
    active: bool = True; notes: str | None = None


@router.post("/transporters")
def upsert_transporter(body: TransporterIn, request: Request, p: Principal = Depends(need("GLOBAL_MASTERS")), db: Session = Depends(get_db)):
    obj = db.get(models.Transporter, body.code)
    old = row(obj) if obj else None
    if not obj:
        obj = models.Transporter(code=body.code); db.add(obj)
    for k, v in body.model_dump(exclude={"code"}).items():
        setattr(obj, k, v)
    audit(db, p, "TRANSPORTER_UPSERT", "transporter", body.code, old, body.model_dump(), request)
    db.commit()
    return row(obj)


# ---------------------------------------------------------------- pallets
@router.get("/pallets")
def list_pallets(plant: str | None = None, status: str | None = None, customer: str | None = None,
                 q: str | None = None, limit: int = Query(500, le=5000), offset: int = 0,
                 p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    qry = db.query(models.Pallet)
    pl = p.scope_plant(plant)
    if pl:
        qry = qry.filter(or_(models.Pallet.home_plant == pl, models.Pallet.location_plant == pl))
    if status:
        qry = qry.filter(models.Pallet.status == status)
    if customer:
        qry = qry.filter(models.Pallet.customer_code == customer)
    if q:
        qry = qry.filter(or_(models.Pallet.pallet_no.like(f"%{q}%"), models.Pallet.current_tag.like(f"%{q}%")))
    total = qry.count()
    items = [row(x) for x in qry.order_by(models.Pallet.pallet_no).offset(offset).limit(limit).all()]
    return {"total": total, "items": items}


@router.get("/pallets/{pallet_no}")
def get_pallet(pallet_no: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    tag, pal = services.resolve_tag(db, pallet_no)
    if not pal:
        raise HTTPException(404, "Pallet not found")
    hist = db.query(models.PalletHistory).filter_by(pallet_no=pal.pallet_no).order_by(models.PalletHistory.ts.desc()).limit(200).all()
    tags = db.query(models.TagHistory).filter_by(pallet_no=pal.pallet_no).order_by(models.TagHistory.ts.desc()).all()
    return {"pallet": row(pal), "history": [row(h) for h in hist], "tag_history": [row(t) for t in tags]}


class PalletIn(BaseModel):
    pallet_no: str | None = None       # None => generate from plant prefix
    home_plant: str
    pallet_type: str | None = None
    size: str | None = None
    tare_kg: float | None = None
    tag_no: str | None = None          # assign on create
    purchase_date: datetime | None = None
    notes: str | None = None


@router.post("/pallets")
def create_pallet(body: PalletIn, request: Request, p: Principal = Depends(need("GLOBAL_MASTERS")), db: Session = Depends(get_db)):
    plant = db.get(models.Plant, body.home_plant.upper())
    if not plant:
        raise HTTPException(400, "Unknown plant")
    no = body.pallet_no
    if not no:
        no = f"{plant.pallet_prefix or plant.code + '-'}{services.next_seq(db, plant.code + ':PALLET'):06d}"
    if db.get(models.Pallet, no):
        raise HTTPException(400, f"Pallet {no} already exists (numbers are never reused)")
    pal = models.Pallet(pallet_no=no, home_plant=plant.code, pallet_type=body.pallet_type, size=body.size, tare_kg=body.tare_kg,
                        purchase_date=body.purchase_date, notes=body.notes, status="AVAILABLE", location_plant=plant.code)
    db.add(pal); db.flush()
    db.add(models.PalletHistory(pallet_no=no, event_type="REGISTER", to_status="AVAILABLE", plant_code=plant.code, user_id=p.user_id))
    try:
        if body.tag_no:
            services.assign_tag(db, pal, body.tag_no, p.user_id)
    except services.RuleError as e:
        db.rollback(); raise HTTPException(400, str(e))
    audit(db, p, "PALLET_CREATE", "pallet", no, None, body.model_dump(), request)
    db.commit()
    return row(pal)


class TagAssignIn(BaseModel):
    tag_no: str
    reason: str = "ASSIGN"


@router.post("/pallets/{pallet_no}/assign-tag")
def assign_tag(pallet_no: str, body: TagAssignIn, request: Request, p: Principal = Depends(need("GLOBAL_MASTERS")), db: Session = Depends(get_db)):
    pal = db.get(models.Pallet, pallet_no)
    if not pal:
        raise HTTPException(404, "Pallet not found")
    try:
        services.assign_tag(db, pal, body.tag_no.strip(), p.user_id, body.reason)
    except services.RuleError as e:
        raise HTTPException(400, str(e))
    audit(db, p, "TAG_ASSIGN", "pallet", pallet_no, None, body.model_dump(), request)
    db.commit()
    return row(pal)


class StatusIn(BaseModel):
    status: str
    remarks: str | None = None
    supervisor_pin: str | None = None


@router.post("/pallets/{pallet_no}/status")
def set_status(pallet_no: str, body: StatusIn, request: Request, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    pal = db.get(models.Pallet, pallet_no)
    if not pal:
        raise HTTPException(404, "Pallet not found")
    p.require_plant(pal.home_plant)
    to = body.status.upper()
    if to == "DISCONTINUED":
        p.require("DISCONTINUE_PALLET")
        from ..security import verify_supervisor_pin
        if not body.supervisor_pin or not verify_supervisor_pin(db, pal.home_plant, body.supervisor_pin):
            raise HTTPException(403, "Supervisor PIN required to discontinue a pallet")
    elif to in ("DAMAGED", "UNDER_REPAIR", "AVAILABLE"):
        if not (p.has("DAMAGE_MARK") or p.has("GLOBAL_MASTERS")):
            raise HTTPException(403, "DAMAGE_MARK permission required")
    else:
        raise HTTPException(400, "Only DAMAGED / UNDER_REPAIR / AVAILABLE / DISCONTINUED can be set manually")
    try:
        services.move(db, pal, to, event_type="MANUAL_STATUS", user_id=p.user_id, plant=pal.location_plant or pal.home_plant, remarks=body.remarks)
    except services.RuleError as e:
        raise HTTPException(400, str(e))
    audit(db, p, "PALLET_STATUS", "pallet", pallet_no, None, body.model_dump(exclude={"supervisor_pin"}), request)
    db.commit()
    return row(pal)


# ---------------------------------------------------------------- tags
@router.get("/tag-batches")
def list_batches(p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.TagBatch).order_by(models.TagBatch.plant_code, models.TagBatch.batch_no)
    if p.plant:
        q = q.filter(models.TagBatch.plant_code == p.plant)
    out = []
    for b in q.all():
        d = row(b)
        counts = {}
        for s, c in db.query(models.Tag.status, models.Tag.tag_no).filter(models.Tag.batch_no == b.batch_no).all():
            counts[s] = counts.get(s, 0) + 1
        d["counts"] = counts; out.append(d)
    return out


class BatchIn(BaseModel):
    batch_no: str; plant_code: str; tag_from: int; tag_to: int
    vendor: str | None = None; received_date: datetime | None = None; notes: str | None = None


@router.post("/tag-batches")
def create_batch(body: BatchIn, request: Request, p: Principal = Depends(need("TAG_SERIES")), db: Session = Depends(get_db)):
    plant = db.get(models.Plant, body.plant_code.upper())
    if not plant:
        raise HTTPException(400, "Unknown plant")
    if body.tag_to < body.tag_from or body.tag_to - body.tag_from > 10000:
        raise HTTPException(400, "Bad range (max 10,000 tags per batch)")
    if plant.tag_from and plant.tag_to and (body.tag_from < plant.tag_from or body.tag_to > plant.tag_to):
        raise HTTPException(400, f"Range outside plant series {plant.tag_from}-{plant.tag_to}")
    if db.get(models.TagBatch, body.batch_no):
        raise HTTPException(400, "Batch exists")
    existing = db.query(models.Tag.tag_no).filter(models.Tag.tag_no.in_([str(i) for i in range(body.tag_from, body.tag_to + 1)])).count()
    if existing:
        raise HTTPError(400, f"{existing} tags of this range already exist")
    b = models.TagBatch(batch_no=body.batch_no, plant_code=plant.code, tag_from=body.tag_from, tag_to=body.tag_to,
                        vendor=body.vendor, received_date=body.received_date, received_by=p.user_id, notes=body.notes)
    db.add(b)
    db.bulk_save_objects([models.Tag(tag_no=str(i), plant_code=plant.code, batch_no=b.batch_no) for i in range(body.tag_from, body.tag_to + 1)])
    audit(db, p, "TAG_BATCH_CREATE", "tag_batch", body.batch_no, None, body.model_dump(), request)
    db.commit()
    return row(b)


HTTPError = HTTPException


@router.get("/tags/{tag_no}")
def get_tag(tag_no: str, p: Principal = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(models.Tag, tag_no)
    if not t:
        raise HTTPException(404, "Tag not found")
    return row(t)
