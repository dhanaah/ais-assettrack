"""Auth, roles, plant scoping."""
from datetime import datetime, timedelta
import bcrypt, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from . import config, models
from .db import get_db

PERMS = [
    "PICKLIST_CREATE", "DOCK_SCAN", "CHALLAN_REQUEST", "LOGISTICS_APPROVE", "OUT_GATE_SCAN",
    "RETURN_SLIP_B", "IN_GATE_SCAN", "YARD_SCAN", "RECONCILE_CLOSE", "DAMAGE_MARK", "PDI_CHECK",
    "TAG_REPLACE_REQUEST", "PLANT_USERS_ADMIN", "GLOBAL_MASTERS", "TAG_SERIES", "DISCONTINUE_PALLET",
    "INTEGRATION_CONFIG", "REPORTS_PLANT", "REPORTS_ALL", "AUDIT_LOG",
    "WMS_UPLOAD", "BLANKET_MASTER", "EMPTY_RETURN", "INTERNAL_MOVE", "PLANT_RECEIPT",
    "MOVE_TO_PRODUCTION", "MOVE_TO_FGWH", "MOVE_TO_PACKING", "MOVE_TO_YARD", "USER_ADMIN",
    "CUST_RECEIVE", "CUST_RETURN", "TRANSPORTER_MASTER",
    "YARD_IN_PLANT", "YARD_TO_PACKING", "PACK_RECEIPT", "PACK_DISPATCH", "PACK_PDI", "VEHICLE_LOAD",
    "MOVE_TO_DISPATCH", "MOVE_FG_TO_PRODUCTION",
]
# What a central admin can switch on/off per user (grouped for the screen)
# HHT groups = the button groups on the HHT home screen (one permission per button)
PERM_GROUPS = {
    "HHT - Security · Gate-In": ["IN_GATE_SCAN", "RETURN_SLIP_B"],
    "HHT - Yard-In (pallet QR)": ["YARD_SCAN", "YARD_IN_PLANT", "MOVE_TO_YARD", "RECONCILE_CLOSE", "DAMAGE_MARK", "TAG_REPLACE_REQUEST"],
    "HHT - Yard-Out (pallet QR)": ["MOVE_TO_PRODUCTION", "YARD_TO_PACKING", "EMPTY_RETURN"],
    "HHT - FGWH · Central FG (pallet card)": ["MOVE_TO_FGWH", "PLANT_RECEIPT", "MOVE_TO_DISPATCH", "MOVE_TO_PACKING", "MOVE_FG_TO_PRODUCTION"],
    "HHT - Main Dispatch (pallet card)": ["DOCK_SCAN", "PDI_CHECK"],
    "HHT - Packing · Dispatch (pallet card)": ["PACK_DISPATCH", "PACK_PDI", "PACK_RECEIPT"],
    "HHT - Security · Loading & Gate-Out": ["VEHICLE_LOAD", "OUT_GATE_SCAN"],
    "HHT - all internal moves (old, covers every move)": ["INTERNAL_MOVE"],
    "Web - documents": ["PICKLIST_CREATE", "CHALLAN_REQUEST", "LOGISTICS_APPROVE", "WMS_UPLOAD"],
    "Web - masters & admin": ["GLOBAL_MASTERS", "TRANSPORTER_MASTER", "BLANKET_MASTER", "TAG_SERIES", "DISCONTINUE_PALLET", "PLANT_USERS_ADMIN", "USER_ADMIN", "INTEGRATION_CONFIG"],
    "Web - reports": ["REPORTS_PLANT", "REPORTS_ALL", "AUDIT_LOG"],
    "Customer HHT (customer staff)": ["CUST_RECEIVE", "CUST_RETURN"],
}
NEW_PERMS = {"WMS_UPLOAD", "BLANKET_MASTER", "EMPTY_RETURN", "PDI_CHECK", "INTERNAL_MOVE", "PLANT_RECEIPT", "CHALLAN_REQUEST",
             "MOVE_TO_PRODUCTION", "MOVE_TO_FGWH", "MOVE_TO_PACKING", "MOVE_TO_YARD", "USER_ADMIN", "TRANSPORTER_MASTER"}   # added to existing roles on upgrade
# 1.26 (one time, at the first start): whoever had the old permission for a function also gets the new button's permission,
# so nobody loses access when a function is split into its own permission. Admin removals afterwards are kept.
IMPLIED_1_26 = {"YARD_SCAN": ["YARD_IN_PLANT"], "INTERNAL_MOVE": ["YARD_TO_PACKING"], "PLANT_RECEIPT": ["PACK_RECEIPT"],
                "DOCK_SCAN": ["PACK_DISPATCH"], "PDI_CHECK": ["PACK_PDI"], "OUT_GATE_SCAN": ["VEHICLE_LOAD"]}   # loading = Security, never the preparer
IMPLIED_1_27 = {"INTERNAL_MOVE": ["MOVE_TO_DISPATCH", "MOVE_FG_TO_PRODUCTION"], "MOVE_TO_PACKING": ["MOVE_TO_DISPATCH"],
                "MOVE_TO_FGWH": ["MOVE_FG_TO_PRODUCTION"]}      # 1.27: FGWH -> Main Dispatch, FGWH -> Production (return)
UPGRADES = [("perm_upgrade_1_26", IMPLIED_1_26), ("perm_upgrade_1_27", IMPLIED_1_27)]
ROLE_SEED = {
    "SEC_IN":  ("Security - IN Gate", "PLANT", ["RETURN_SLIP_B", "IN_GATE_SCAN", "REPORTS_PLANT"]),
    "CUST_STAFF": ("Customer Staff (customer HHT: receive loaded pallets, return empty pallets)", "PLANT", ["CUST_RECEIVE", "CUST_RETURN"]),
    "SEC_OUT": ("Security - Logistics / OUT Gate", "PLANT", ["VEHICLE_LOAD", "OUT_GATE_SCAN", "REPORTS_PLANT"]),
    "YARD":    ("Pallet Yard In-charge", "PLANT", ["YARD_SCAN", "YARD_IN_PLANT", "MOVE_TO_YARD", "MOVE_TO_PRODUCTION", "YARD_TO_PACKING", "RECONCILE_CLOSE", "DAMAGE_MARK", "TAG_REPLACE_REQUEST", "EMPTY_RETURN", "INTERNAL_MOVE", "REPORTS_PLANT"]),
    "FGWH":    ("FG Warehouse", "PLANT", ["PICKLIST_CREATE", "DOCK_SCAN", "CHALLAN_REQUEST", "WMS_UPLOAD", "EMPTY_RETURN", "INTERNAL_MOVE", "PLANT_RECEIPT", "MOVE_TO_FGWH", "MOVE_TO_DISPATCH", "MOVE_TO_PACKING", "MOVE_FG_TO_PRODUCTION", "REPORTS_PLANT"]),
    "PROD":    ("Production", "PLANT", ["MOVE_TO_FGWH", "MOVE_TO_PACKING", "REPORTS_PLANT"]),
    "PACK":    ("Packing Section", "PLANT", ["MOVE_TO_YARD", "PLANT_RECEIPT", "PACK_RECEIPT", "PACK_DISPATCH", "REPORTS_PLANT"]),
    "QA":      ("QA / PDI", "PLANT", ["PDI_CHECK", "PACK_PDI", "DAMAGE_MARK", "REPORTS_PLANT"]),
    "LOG":     ("Logistics", "PLANT", ["LOGISTICS_APPROVE", "CHALLAN_REQUEST", "EMPTY_RETURN", "TRANSPORTER_MASTER", "REPORTS_PLANT"]),
    "PADMIN":  ("Plant Admin", "PLANT", ["PLANT_USERS_ADMIN", "TRANSPORTER_MASTER", "REPORTS_PLANT", "AUDIT_LOG"]),
    "MASTER":  ("Master Maintenance (central)", "ALL", ["GLOBAL_MASTERS", "TRANSPORTER_MASTER", "BLANKET_MASTER", "TAG_SERIES", "DISCONTINUE_PALLET", "REPORTS_ALL"]),
    "CADMIN":  ("Central Admin", "ALL", PERMS),
    "MGMT":    ("Management (view only)", "ALL", ["REPORTS_ALL"]),
}
SENSITIVE = {"RECONCILE_CLOSE_WITH_EXC", "PICKLIST_REDUCE_QTY", "GCS_OVERRIDE", "DISCONTINUE_PALLET", "HOME_PLANT_CHANGE", "USER_DELETE"}

bearer = HTTPBearer(auto_error=False)


def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def check_pw(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def _pv(user: models.User) -> str:
    """Password version: changes when the password changes, so older sign-ins stop working."""
    return (user.password_hash or "")[-10:]


def make_token(user: models.User) -> str:
    exp = datetime.utcnow() + timedelta(hours=config.TOKEN_HOURS)
    return jwt.encode({"sub": user.user_id, "uid": user.id, "exp": exp, "pv": _pv(user)}, config.JWT_SECRET, algorithm=config.JWT_ALGO)


def make_ticket(user: models.User) -> str:
    """Short ticket (2 min) for opening a print / Excel download in a new tab - the real sign-in token never goes in a link."""
    exp = datetime.utcnow() + timedelta(minutes=2)
    return jwt.encode({"sub": user.user_id, "uid": user.id, "exp": exp, "typ": "tkt", "pv": _pv(user)}, config.JWT_SECRET, algorithm=config.JWT_ALGO)


def decode_user(db: Session, raw: str, ticket: bool):
    """Checks a sign-in token (ticket=False) or a link ticket (ticket=True). Returns the user or raises 401."""
    try:
        data = jwt.decode(raw, config.JWT_SECRET, algorithms=[config.JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Link expired - open it again" if ticket else "Session expired, login again")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if (data.get("typ") == "tkt") != ticket:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = db.get(models.User, data.get("uid"))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    if "pv" in data and data["pv"] != _pv(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Password changed - login again")
    return user


class Principal:
    def __init__(self, user: models.User, perms: set[str]):
        self.user = user
        self.perms = perms
        self.plant = user.plant_code          # None => all plants
        self.user_id = user.user_id

    def has(self, perm: str) -> bool:
        return perm in self.perms

    def can_see_plant(self, plant_code: str | None) -> bool:
        return self.plant is None or plant_code == self.plant

    def require(self, perm: str):
        if perm not in self.perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission {perm} required")

    def require_any(self, *perms: str):
        if not any(x in self.perms for x in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission {' / '.join(perms)} required")

    def require_plant(self, plant_code: str | None):
        if not self.can_see_plant(plant_code):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Plant restriction: not your plant")

    def scope_plant(self, requested: str | None) -> str | None:
        """Return plant filter to use: plant users are forced to their plant."""
        if self.plant is not None:
            return self.plant
        return requested


def load_perms(db: Session, user: models.User) -> set[str]:
    if user.perms_override is not None:          # central admin set this user's access explicitly
        return {x.strip() for x in user.perms_override.split(",") if x.strip()}
    codes = user.role_codes
    if not codes:
        return set()
    rows = db.query(models.RolePermission.perm).filter(models.RolePermission.role_code.in_(codes)).all()
    return {r[0] for r in rows}


def current_user(request: Request, creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> Principal:
    # links opened in a new tab (prints, Excel downloads) carry a 2-minute ticket (?tok=), never the sign-in token
    raw = creds.credentials if creds else request.query_params.get("tok")
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    user = decode_user(db, raw, ticket=not creds)
    if (user.must_change_pw and user.user_id == config.BOOTSTRAP_ADMIN_USER and not request.url.path.startswith("/api/v1/auth/")
            and not (request.method == "GET" and request.url.path in ("/api/v1/roles", "/api/v1/perm-groups", "/api/v1/plants"))):   # Users page (My account) still opens
        # the built-in admin keeps its known first password until it is changed: nothing else works before that
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Change the admin password first (Users > My account)")
    p = Principal(user, load_perms(db, user))
    want = (request.headers.get("x-plant") or "").strip().upper()
    if want and want != (user.plant_code or ""):        # plant selected on the HHT (one server, many plants)
        if want not in allowed_plants(db, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"User {user.user_id} is not allowed for plant {want}")
        p.plant = want
    return p


def allowed_plants(db: Session, user) -> list[str]:
    """Plants a user may work for: central users (no plant) - every active plant; plant users - own plant + extra plants."""
    if user.customer_code:
        return [user.plant_code] if user.plant_code else []
    if not user.plant_code:
        return [x.code for x in db.query(models.Plant).order_by(models.Plant.code).all() if getattr(x, "active", True) is not False]
    extra = [x.strip().upper() for x in (user.extra_plants or "").replace(",", ";").split(";") if x.strip()]
    return [user.plant_code] + [x for x in extra if x != user.plant_code and db.get(models.Plant, x)]


def _ver(v: str) -> tuple:
    try:
        return tuple(int(x) for x in (v or "0").split("-")[0].split("."))
    except ValueError:
        return (0,)


def client_ok(version: str | None) -> bool:
    return not version or _ver(version) >= _ver(config.API_MIN_CLIENT)


UPDATE_MSG = "This AssetTrack app is too old - install the latest APK from the AssetTrack server (version {min} or newer)."


def require_client_version(version: str | None):
    if not client_ok(version):
        raise HTTPException(426, UPDATE_MSG.format(min=config.API_MIN_CLIENT))


HHT_ONLY_MSG = ("Operations are allowed only from the HHT app. The web / server is for masters, uploads, "
                "reports, dashboard, live view and challan printing.")


def is_hht(request: Request) -> bool:
    return (request.headers.get("x-device") or "").upper() == "HHT" and bool(request.headers.get("x-device-id"))


def require_hht(request: Request):
    if config.HHT_ONLY and not is_hht(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, HHT_ONLY_MSG)
    if is_hht(request):
        require_client_version(request.headers.get("x-app-version"))


def hht(perm: str | None = None):
    """Dependency: physical transaction -> HHT only (+ optional permission)."""
    def dep(request: Request, p: "Principal" = Depends(current_user)) -> "Principal":
        require_hht(request)
        if perm:
            p.require(perm)
        return p
    return dep


def need(perm: str):
    def dep(p: Principal = Depends(current_user)) -> Principal:
        p.require(perm)
        return p
    return dep


def audit(db: Session, p: Principal | None, action: str, entity: str | None = None, entity_id: str | None = None,
          old=None, new=None, request: Request | None = None, plant: str | None = None):
    import json
    db.add(models.AuditLog(
        user_id=p.user_id if p else None, plant_code=plant or (p.plant if p else None), action=action,
        entity=entity, entity_id=str(entity_id) if entity_id is not None else None,
        old_value=json.dumps(old, default=str) if old is not None else None,
        new_value=json.dumps(new, default=str) if new is not None else None,
        ip=request.client.host if request and request.client else None))


def pin_in_use(db: Session, plant: str | None, pin: str, except_user_pk: int | None = None) -> models.User | None:
    """Another active supervisor of the same plant (or central) already has this PIN -> it would be ambiguous."""
    q = db.query(models.User).filter(models.User.supervisor_allowed == True, models.User.active == True)
    if plant:
        q = q.filter((models.User.plant_code == plant) | (models.User.plant_code.is_(None)))
    for u in q.all():
        if u.id != except_user_pk and u.supervisor_pin_hash and check_pw(pin, u.supervisor_pin_hash):
            return u
    return None


_PIN_FAILS: dict[str, list[float]] = {}
PIN_MAX_FAILS, PIN_WINDOW, PIN_LOCK = 8, 600, 600       # 8 wrong PINs in 10 min at a plant -> PIN use paused 10 min


def verify_supervisor_pin(db: Session, plant: str | None, pin: str) -> models.User | None:
    """Return the supervisor user whose PIN matches (same plant or central). PINs are unique per plant (see pin_in_use).
    Wrong PINs are counted per plant: after too many, PINs are refused for a while (stops guessing every 4-digit PIN)."""
    import time
    if not pin:
        return None
    key, now = plant or "*", time.time()
    fails = [t for t in _PIN_FAILS.get(key, []) if now - t < max(PIN_WINDOW, PIN_LOCK)]
    if len([t for t in fails if now - t < PIN_WINDOW]) >= PIN_MAX_FAILS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong supervisor PINs - PIN use paused for 10 minutes")
    q = db.query(models.User).filter(models.User.supervisor_allowed == True, models.User.active == True)
    if plant:
        q = q.filter((models.User.plant_code == plant) | (models.User.plant_code.is_(None)))
    for u in q.all():
        if pin and u.supervisor_pin_hash and check_pw(pin, u.supervisor_pin_hash):
            return u
    fails.append(now); _PIN_FAILS[key] = fails[-50:]
    return None
