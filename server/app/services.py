"""Business rules: pallet state machine, tag resolution, sequences."""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from . import models
from .models import utcnow


class RuleError(Exception):
    """Validation failure that is reported to the user (not a server error)."""


# pallet statuses
AVAILABLE, ALLOCATED, AT_CUSTOMER, IN_RETURN, HELD, DAMAGED, UNDER_REPAIR, DISCONTINUED = (
    "AVAILABLE", "ALLOCATED", "AT_CUSTOMER", "IN_RETURN", "HELD", "DAMAGED", "UNDER_REPAIR", "DISCONTINUED")

IN_WIP, IN_TRANSIT = "IN_WIP", "IN_TRANSIT"     # foreign pallet issued to line; empty pallet going back to origin plant

TRANSITIONS = {
    AVAILABLE:    {ALLOCATED, DAMAGED, UNDER_REPAIR, DISCONTINUED, HELD},
    ALLOCATED:    {AVAILABLE, AT_CUSTOMER, HELD, IN_TRANSIT},
    AT_CUSTOMER:  {IN_RETURN, AVAILABLE, HELD, DAMAGED},
    IN_RETURN:    {AVAILABLE, HELD, DAMAGED, AT_CUSTOMER},
    HELD:         {AVAILABLE, DISCONTINUED, IN_WIP, ALLOCATED},
    IN_WIP:       {HELD, ALLOCATED},
    IN_TRANSIT:   {AVAILABLE, HELD, DAMAGED},
    DAMAGED:      {UNDER_REPAIR, AVAILABLE, DISCONTINUED},
    UNDER_REPAIR: {AVAILABLE, DAMAGED, DISCONTINUED},
    DISCONTINUED: set(),
}


def next_seq(db: Session, key: str) -> int:
    row = db.get(models.Sequence, key, with_for_update=True) if db.bind.dialect.name != "sqlite" else db.get(models.Sequence, key)
    if not row:
        row = models.Sequence(key=key, value=0)
        db.add(row)
        db.flush()
    row.value += 1
    db.flush()
    return row.value


def doc_number(db: Session, plant: str, kind: str, device: str | None = None) -> str:
    """Server series: CHN-PL-000123. Device-created numbers come from HHT and are kept as-is."""
    n = next_seq(db, f"{plant}:{kind}")
    return f"{plant}-{kind}-{n:06d}"


def resolve_tag(db: Session, scanned: str) -> tuple[models.Tag | None, models.Pallet | None]:
    """Scanned value may be a tag_no or a pallet_no (QR on pallet)."""
    s = scanned.strip()
    tag = db.get(models.Tag, s)
    if tag:
        pallet = db.get(models.Pallet, tag.pallet_no) if tag.pallet_no else None
        return tag, pallet
    pallet = db.get(models.Pallet, s)
    if pallet:
        tag = db.get(models.Tag, pallet.current_tag) if pallet.current_tag else None
        return tag, pallet
    return None, None


def validate_scan_for_dispatch(db: Session, scanned: str, plant: str) -> models.Pallet:
    tag, pallet = resolve_tag(db, scanned)
    if tag is None and pallet is None:
        raise RuleError(f"Unknown tag {scanned}")
    if tag is not None and tag.status == "RETIRED":
        raise RuleError(f"Tag {tag.tag_no} is retired")
    if pallet is None:
        raise RuleError(f"Tag {scanned} not assigned to any pallet")
    if pallet.home_plant != plant:
        raise RuleError(f"Foreign pallet: {pallet.pallet_no} belongs to {pallet.home_plant}")
    if pallet.status != AVAILABLE:
        raise RuleError(f"Pallet {pallet.pallet_no} is {pallet.status}" + (f" ({pallet.picklist_no})" if pallet.picklist_no else ""))
    return pallet


def move(db: Session, pallet: models.Pallet, to_status: str, *, event_type: str, user_id: str | None = None,
         device_id: str | None = None, event_id: str | None = None, plant: str | None = None,
         customer: str | None = None, ref: str | None = None, remarks: str | None = None, force: bool = False):
    if not force and to_status not in TRANSITIONS.get(pallet.status, set()) and to_status != pallet.status:
        raise RuleError(f"{pallet.pallet_no}: cannot go {pallet.status} -> {to_status}")
    frm = pallet.status
    pallet.status = to_status
    if plant is not None:
        pallet.location_plant = plant
    if to_status == AT_CUSTOMER:
        pallet.customer_code = customer
        if frm == ALLOCATED or pallet.dispatch_date is None:
            pallet.dispatch_date = utcnow()        # real dispatch; a short-return keeps the original aging
        pallet.location_plant = None
        if ref:
            pallet.challan_ref = ref
    elif to_status in (AVAILABLE, HELD, DAMAGED, UNDER_REPAIR):
        if frm in (AT_CUSTOMER, IN_RETURN):
            pallet.customer_code = None
            pallet.dispatch_date = None
        if to_status == AVAILABLE:
            pallet.picklist_no = None
    if to_status == DISCONTINUED:
        pallet.discontinued_at = utcnow()
    db.add(models.PalletHistory(pallet_no=pallet.pallet_no, event_type=event_type, from_status=frm, to_status=to_status,
                                plant_code=plant or pallet.location_plant, customer_code=customer or pallet.customer_code,
                                ref_doc=ref, user_id=user_id, device_id=device_id, event_id=event_id, remarks=remarks))


def assign_tag(db: Session, pallet: models.Pallet, tag_no: str, user_id: str, reason: str = "ASSIGN"):
    tag = db.get(models.Tag, tag_no)
    if not tag:
        raise RuleError(f"Tag {tag_no} not in Tag Master")
    if tag.status != "IN_STOCK":
        raise RuleError(f"Tag {tag_no} is {tag.status}")
    if tag.plant_code != pallet.home_plant:
        raise RuleError(f"Tag {tag_no} belongs to plant {tag.plant_code}")
    if pallet.status == DISCONTINUED:
        raise RuleError("Pallet discontinued")
    old = pallet.current_tag
    if old:
        ot = db.get(models.Tag, old)
        if ot:
            ot.status = "RETIRED"; ot.retired_at = utcnow()
    tag.status = "ASSIGNED"; tag.pallet_no = pallet.pallet_no; tag.assigned_at = utcnow()
    pallet.current_tag = tag_no
    db.add(models.TagHistory(pallet_no=pallet.pallet_no, old_tag=old, new_tag=tag_no, reason=reason, user_id=user_id))


def availability(db: Session, plant: str | None = None):
    q = db.query(models.Pallet.home_plant, models.Pallet.status, func.count()).group_by(models.Pallet.home_plant, models.Pallet.status)
    if plant:
        q = q.filter(models.Pallet.home_plant == plant)
    out: dict[str, dict[str, int]] = {}
    for p, s, c in q.all():
        out.setdefault(p, {})[s] = c
    # pallets of other plants physically held here
    hq = db.query(models.Pallet.location_plant, func.count()).filter(models.Pallet.status == HELD).group_by(models.Pallet.location_plant)
    if plant:
        hq = hq.filter(models.Pallet.location_plant == plant)
    for p, c in hq.all():
        if p:
            out.setdefault(p, {})["HELD_FROM_OTHER"] = c
    return out


def customer_holding(db: Session, plant: str | None = None):
    now = utcnow()
    q = db.query(models.Pallet).filter(models.Pallet.status == AT_CUSTOMER)
    if plant:
        q = q.filter(models.Pallet.home_plant == plant)
    res: dict[tuple, dict] = {}
    for p in q.all():
        key = (p.home_plant, p.customer_code)
        r = res.setdefault(key, {"plant": p.home_plant, "customer": p.customer_code, "qty": 0, "b0_30": 0, "b31_60": 0, "b61": 0, "max_days": 0})
        days = (now - p.dispatch_date).days if p.dispatch_date else 0
        r["qty"] += 1
        r["b0_30" if days <= 30 else "b31_60" if days <= 60 else "b61"] += 1
        r["max_days"] = max(r["max_days"], days)
    return list(res.values())


# ---------------------------------------------------------------- return slip QR (v1)
# AIS1|RS|<slip_no>|<plant>|<customer>|<vehicle>|<qty>|<yyMMddHHmm>|<sig8>
# sig8 = first 8 hex of HMAC-SHA256(server secret, everything before it). Slips made on the HHT offline carry "-".
def _sig(body: str, secret: str | None = None) -> str:
    import hmac, hashlib
    from . import config
    return hmac.new((secret or config.JWT_SECRET).encode(), body.encode(), hashlib.sha256).hexdigest()[:8].upper()


def _sig_ok(body: str, sig: str) -> bool:
    """Current secret, else the legacy built-in one (labels printed before the secret was made still scan)."""
    from . import config
    import hmac
    s = (sig or "").upper()
    return hmac.compare_digest(s, _sig(body)) or hmac.compare_digest(s, _sig(body, config.LEGACY_SECRET))


def slip_qr(sl, signed: bool = True) -> str:
    ts = (sl.created_at or utcnow()).strftime("%y%m%d%H%M")
    body = f"AIS1|RS|{sl.slip_no}|{sl.plant_code}|{sl.customer_code}|{sl.vehicle_no or ''}|{sl.declared_qty or 0}|{ts}"
    return f"{body}|{_sig(body) if signed else '-'}"


def label_token(slip_no: str, secret: str | None = None) -> str:
    return _sig("LABEL|" + slip_no, secret) + _sig("LABEL2|" + slip_no, secret)


def label_token_ok(slip_no: str, t: str | None) -> bool:
    import hmac
    from . import config
    t = t or ""
    return hmac.compare_digest(t, label_token(slip_no)) or hmac.compare_digest(t, label_token(slip_no, config.LEGACY_SECRET))


def parse_slip_qr(code: str) -> dict:
    """Accepts AIS1|RS|... (verifies check code) or legacy RTS|slip|plant|cust|qty or a bare slip number."""
    s = (code or "").strip()
    if s.startswith("AIS1|RS|"):
        parts = s.split("|")
        if len(parts) != 9:
            return {"slip_no": None, "error": "QR format not recognised"}
        body, sig = "|".join(parts[:8]), parts[8]
        ok = sig != "-" and _sig_ok(body, sig)
        return {"slip_no": parts[2], "plant": parts[3], "customer": parts[4], "vehicle": parts[5], "qty": int(parts[6] or 0),
                "signed": sig != "-", "valid": ok or sig == "-", "error": None if (ok or sig == "-") else "QR check code invalid - label altered or not issued by AssetTrack"}
    if s.startswith("RTS|"):
        return {"slip_no": s.split("|")[1], "signed": False, "valid": True, "error": None}
    return {"slip_no": s, "signed": False, "valid": True, "error": None}
