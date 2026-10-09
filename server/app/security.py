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
]
NEW_PERMS = {"WMS_UPLOAD", "BLANKET_MASTER", "EMPTY_RETURN", "PDI_CHECK", "INTERNAL_MOVE", "PLANT_RECEIPT", "CHALLAN_REQUEST"}   # added to existing roles on upgrade
ROLE_SEED = {
    "SEC_IN":  ("Security - IN Gate", "PLANT", ["RETURN_SLIP_B", "IN_GATE_SCAN", "REPORTS_PLANT"]),
    "SEC_OUT": ("Security - Logistics / OUT Gate", "PLANT", ["OUT_GATE_SCAN", "REPORTS_PLANT"]),
    "YARD":    ("Pallet Yard In-charge", "PLANT", ["YARD_SCAN", "RECONCILE_CLOSE", "DAMAGE_MARK", "TAG_REPLACE_REQUEST", "EMPTY_RETURN", "INTERNAL_MOVE", "REPORTS_PLANT"]),
    "FGWH":    ("FG Warehouse", "PLANT", ["PICKLIST_CREATE", "DOCK_SCAN", "CHALLAN_REQUEST", "WMS_UPLOAD", "EMPTY_RETURN", "INTERNAL_MOVE", "PLANT_RECEIPT", "REPORTS_PLANT"]),
    "PROD":    ("Production", "PLANT", ["INTERNAL_MOVE", "REPORTS_PLANT"]),
    "PACK":    ("Packing Section", "PLANT", ["INTERNAL_MOVE", "PLANT_RECEIPT", "REPORTS_PLANT"]),
    "QA":      ("QA / PDI", "PLANT", ["PDI_CHECK", "DAMAGE_MARK", "REPORTS_PLANT"]),
    "LOG":     ("Logistics", "PLANT", ["LOGISTICS_APPROVE", "CHALLAN_REQUEST", "EMPTY_RETURN", "REPORTS_PLANT"]),
    "PADMIN":  ("Plant Admin", "PLANT", ["PLANT_USERS_ADMIN", "REPORTS_PLANT", "AUDIT_LOG"]),
    "MASTER":  ("Master Maintenance (central)", "ALL", ["GLOBAL_MASTERS", "BLANKET_MASTER", "TAG_SERIES", "DISCONTINUE_PALLET", "REPORTS_ALL"]),
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


def make_token(user: models.User) -> str:
    exp = datetime.utcnow() + timedelta(hours=config.TOKEN_HOURS)
    return jwt.encode({"sub": user.user_id, "uid": user.id, "exp": exp}, config.JWT_SECRET, algorithm=config.JWT_ALGO)


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
    codes = user.role_codes
    if not codes:
        return set()
    rows = db.query(models.RolePermission.perm).filter(models.RolePermission.role_code.in_(codes)).all()
    return {r[0] for r in rows}


def current_user(request: Request, creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> Principal:
    raw = creds.credentials if creds else request.query_params.get("tok")   # ?tok= allows browser downloads / new-tab prints
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    try:
        data = jwt.decode(raw, config.JWT_SECRET, algorithms=[config.JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, login again")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = db.get(models.User, data.get("uid"))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return Principal(user, load_perms(db, user))


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


def verify_supervisor_pin(db: Session, plant: str | None, pin: str) -> models.User | None:
    """Return the supervisor user whose PIN matches (same plant or central)."""
    q = db.query(models.User).filter(models.User.supervisor_allowed == True, models.User.active == True)
    if plant:
        q = q.filter((models.User.plant_code == plant) | (models.User.plant_code.is_(None)))
    for u in q.all():
        if u.supervisor_pin_hash and check_pw(pin, u.supervisor_pin_hash):
            return u
    return None
