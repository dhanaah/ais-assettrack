"""Business rules: pallet state machine, tag resolution, sequences.
Developed by DT"""
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
    """Atomic: one UPDATE ... RETURNING takes the write lock first, so two requests at the same moment never get the
    same number (the second waits until the first commits)."""
    from sqlalchemy import update, insert
    from sqlalchemy.exc import IntegrityError
    t = models.Sequence.__table__
    for _ in range(3):
        v = db.execute(update(t).where(t.c.key == key).values(value=t.c.value + 1).returning(t.c.value)).scalar()
        if v is not None:
            return int(v)
        try:
            with db.begin_nested():
                db.execute(insert(t).values(key=key, value=1))
            return 1
        except IntegrityError:
            continue                     # created by another request just now: take the next number
    raise RuleError(f"Could not take the next number for {key}")


def doc_number(db: Session, plant: str, kind: str, device: str | None = None) -> str:
    """Server series: CHN-PL-000123. Device-created numbers come from HHT and are kept as-is."""
    n = next_seq(db, f"{plant}:{kind}")
    return f"{plant}-{kind}-{n:06d}"


# ---------------------------------------------------------------- AIS pallet QR
# The pallet label QR holds a JSON record:
#   {"uniquePalletID":"AIS-AAB-ANF-00001-0000001","ownerPlant":"AAB","palletType":"ANF","typeSerial":"00001",
#    "globalSerial":"0000001","mfgDate":"2026-08-27"}
# uniquePalletID = AIS-<owner plant>-<pallet type>-<type serial>-<global serial>. A plain ID string is accepted too.
import re as _re
PALLET_ID_RE = _re.compile(r"^AIS-([A-Z0-9]{2,6})-([A-Z0-9]{1,8})-(\d{3,8})-(\d{4,10})$")   # type may be 1 letter (F)


def short_ref(pallet_no: str | None) -> str:
    """AIS-CHN-F-02948-0000100 -> F-02948 (type + serial); other numbers unchanged."""
    m = PALLET_ID_RE.match(str(pallet_no or "").upper())
    return f"{m.group(2)}-{m.group(3)}" if m else str(pallet_no or "")


_REF_RE = _re.compile(r"^([A-Z0-9]*?[A-Z])[.\- ]?0*(\d+)$")


def pallet_from_ref(db: Session, ref: str | None, plant: str | None = None, cache: dict | None = None) -> str | None:
    """ERP pallet reference 'F.2948' / 'NF7944' = pallet type + type serial (part of the pallet QR
    AIS-<owner>-<type>-<serial>-<global>). Returns the pallet_no, preferring pallets owned by `plant`."""
    m = _REF_RE.match(str(ref or "").strip().upper())
    if not m:
        return None
    t, n = m.group(1), int(m.group(2))
    key = (t, n, plant)
    if cache is not None and key in cache:
        return cache[key]
    hits = []
    for (pno, home) in db.query(models.Pallet.pallet_no, models.Pallet.home_plant).filter(models.Pallet.pallet_no.like(f"AIS-%-{t}-%{n}-%")).all():
        mm = PALLET_ID_RE.match(pno)
        if mm and mm.group(2) == t and int(mm.group(3)) == n:
            hits.append((home != plant, pno))
    res = sorted(hits)[0][1] if hits else None
    if cache is not None:
        cache[key] = res
    return res


def parse_pallet_qr(scanned: str) -> dict | None:
    """Returns {"pallet_no", "owner_plant", "pallet_type", "mfg_date", "raw"} for an AIS pallet QR / ID, else None."""
    s = (scanned or "").strip()
    if not s:
        return None
    if s.startswith("{"):
        import json
        try:
            d = json.loads(s)
        except ValueError:
            return None
        pid = str(d.get("uniquePalletID") or d.get("palletID") or d.get("pallet_no") or "").strip().upper()
        if not pid:
            return None
        m = PALLET_ID_RE.match(pid)
        mfg = None
        try:
            mfg = datetime.strptime(str(d.get("mfgDate"))[:10], "%Y-%m-%d") if d.get("mfgDate") else None
        except ValueError:
            mfg = None
        return {"pallet_no": pid, "owner_plant": str(d.get("ownerPlant") or (m.group(1) if m else "")).upper() or None,
                "pallet_type": str(d.get("palletType") or (m.group(2) if m else "")).upper() or None, "mfg_date": mfg, "raw": d}
    m = PALLET_ID_RE.match(s.upper())
    if m:
        return {"pallet_no": s.upper(), "owner_plant": m.group(1), "pallet_type": m.group(2), "mfg_date": None, "raw": None}
    return None


def register_from_qr(db: Session, info: dict, plant: str, *, user_id=None, device_id=None, event_id=None) -> models.Pallet | None:
    """First scan of a new AIS pallet label: create the pallet master row from the QR (owner plant must exist).
    Own pallet -> AVAILABLE in the Yard; another plant's pallet -> HELD here."""
    owner = info.get("owner_plant")
    if not owner or not db.get(models.Plant, owner) or db.get(models.Pallet, info["pallet_no"]):
        return None
    own = owner == plant
    pal = models.Pallet(pallet_no=info["pallet_no"], home_plant=owner, pallet_type=info.get("pallet_type"), status=AVAILABLE if own else HELD,
                        location_plant=plant, zone="YARD", load_state="EMPTY", purchase_date=info.get("mfg_date"),
                        notes="registered from pallet QR at " + plant)
    db.add(pal); db.flush()
    db.add(models.PalletHistory(pallet_no=pal.pallet_no, event_type="QR_REGISTER", from_status=None, to_status=pal.status, plant_code=plant,
                                user_id=user_id, device_id=device_id, event_id=event_id, remarks=f"new pallet label scanned (owner {owner}, type {pal.pallet_type})"))
    return pal


def resolve_tag(db: Session, scanned: str) -> tuple[models.Tag | None, models.Pallet | None]:
    """Scanned value may be a tag_no, a pallet_no, or the AIS pallet QR (JSON with uniquePalletID)."""
    s = scanned.strip()
    q = parse_pallet_qr(s) if s.startswith("{") else None
    if q:
        s = q["pallet_no"]
    tag = db.get(models.Tag, s)
    if tag:
        pallet = db.get(models.Pallet, tag.pallet_no) if tag.pallet_no else None
        return tag, pallet
    pallet = db.get(models.Pallet, s)
    if pallet:
        tag = db.get(models.Tag, pallet.current_tag) if pallet.current_tag else None
        return tag, pallet
    return None, None


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


SLIP_STALE_DAYS = 3


def still_with_customer():
    """Filter: pallets the customer still holds - AT_CUSTOMER, and IN_RETURN pallets whose return slip never reached AIS
    within SLIP_STALE_DAYS (a slip alone must not hide overdue pallets from holding and reminders)."""
    from datetime import timedelta as _td
    return (models.Pallet.status == AT_CUSTOMER) | ((models.Pallet.status == IN_RETURN) & (models.Pallet.updated_at < utcnow() - _td(days=SLIP_STALE_DAYS)))


def customer_holding(db: Session, plant: str | None = None):
    now = utcnow()
    q = db.query(models.Pallet).filter(still_with_customer())
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


def _sig_ok(body: str, sig: str) -> bool | str:
    """True for the current secret; "legacy" for the old built-in one (public on GitHub) - the caller accepts that only
    for a record created before config.LEGACY_CUTOFF (labels printed long ago still scan, new forgeries do not)."""
    from . import config
    import hmac
    s = (sig or "").upper()
    if hmac.compare_digest(s, _sig(body)):
        return True
    return "legacy" if hmac.compare_digest(s, _sig(body, config.LEGACY_SECRET)) else False


def legacy_ok(created) -> bool:
    from . import config
    return bool(created) and created < config.LEGACY_CUTOFF


def slip_qr(sl, signed: bool = True) -> str:
    ts = (sl.created_at or utcnow()).strftime("%y%m%d%H%M")
    body = f"AIS1|RS|{sl.slip_no}|{sl.plant_code}|{sl.customer_code}|{sl.vehicle_no or ''}|{sl.declared_qty or 0}|{ts}"
    return f"{body}|{_sig(body) if signed else '-'}"


def label_token(slip_no: str, secret: str | None = None) -> str:
    return _sig("LABEL|" + slip_no, secret) + _sig("LABEL2|" + slip_no, secret)


def label_token_ok(slip_no: str, t: str | None, created=None) -> bool:
    import hmac
    from . import config
    t = t or ""
    return hmac.compare_digest(t, label_token(slip_no)) or (legacy_ok(created) and hmac.compare_digest(t, label_token(slip_no, config.LEGACY_SECRET)))


def device_sign_key(device_id) -> str:
    """Per customer-HHT secret for slips printed without network (given to the HHT at pairing / on /me)."""
    import hmac, hashlib
    from . import config
    return hmac.new(config.JWT_SECRET.encode(), f"DEVSIGN|{device_id}".encode(), hashlib.sha256).hexdigest()[:32]


def offline_sig(key: str, body: str) -> str:
    import hmac, hashlib
    return hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()[:10].upper()


def safe_int(v, d: int = 0) -> int:
    """A number field of a scanned QR: a smudged / foreign QR gives 0, never a server error."""
    try:
        return int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return d


def parse_slip_qr(code: str) -> dict:
    """Accepts AIS1|RS|... (verifies check code), AIS1|RO|... (slip printed by a customer HHT without network, signed with
    that HHT's own key), legacy RTS|slip|plant|cust|qty or a bare slip number."""
    s = (code or "").strip()
    if s.startswith("AIS1|RO|"):
        parts = s.split("|")
        if len(parts) != 11:
            return {"slip_no": None, "error": "QR format not recognised"}
        body, sig = "|".join(parts[:10]), parts[10]
        dev = parts[8]
        ok = dev.isdigit() and __import__("hmac").compare_digest(sig.upper(), offline_sig(device_sign_key(int(dev)), body))
        return {"slip_no": parts[2], "plant": parts[3], "customer": parts[4], "vehicle": parts[5], "qty": safe_int(parts[6]), "ts": parts[7],
                "device_id": int(dev) if dev.isdigit() else None, "refs": [x for x in parts[9].split(",") if x], "offline": True,
                "signed": True, "valid": ok, "error": None if ok else "QR check code invalid - slip altered or not made by a paired AIS HHT"}
    if s.startswith("AIS1|RS|"):
        parts = s.split("|")
        if len(parts) != 9:
            return {"slip_no": None, "error": "QR format not recognised"}
        body, sig = "|".join(parts[:8]), parts[8]
        ok = sig != "-" and _sig_ok(body, sig)
        return {"slip_no": parts[2], "plant": parts[3], "customer": parts[4], "vehicle": parts[5], "qty": safe_int(parts[6]),
                "signed": sig != "-", "legacy": ok == "legacy", "valid": ok or sig == "-", "error": None if (ok or sig == "-") else "QR check code invalid - label altered or not issued by AssetTrack"}
    if s.startswith("RTS|"):
        parts = s.split("|")
        return {"slip_no": parts[1] if len(parts) > 1 and parts[1] else None, "signed": False, "valid": True,
                "error": None if len(parts) > 1 and parts[1] else "QR format not recognised"}
    return {"slip_no": s, "signed": False, "valid": True, "error": None}


def xl_dates(wb):
    """Every date cell in the workbook shown as dd-mmm-yy (with time when it has one).
    Text that starts with '=' (e.g. a customer DC no "=HYPERLINK(...)") is kept as plain text, never run by Excel as a formula."""
    from datetime import datetime as _dt, date as _d
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f":
                    c.data_type = "s"
                elif isinstance(c.value, _dt):
                    c.number_format = "dd-mmm-yy hh:mm" if (c.value.hour or c.value.minute) else "dd-mmm-yy"
                elif isinstance(c.value, _d):
                    c.number_format = "dd-mmm-yy"
    return wb
