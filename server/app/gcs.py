"""GCS inbox: gate-pass documents created after invoicing (in the Bench / GCS system) are dropped on an FTP folder.
AssetTrack reads them and opens a LOADING SHEET per GCS (pick list GCS-<plant>-<gcs no>, source GCS). At the vehicle the
HHT scans pallets or part cards (LPN) against it; "Finish loading" makes the challan and the GCS print with a signed QR;
the OUT gate scans that QR. Settings (web > Masters > GCS inbox): host, port, user, password, folder, file pattern,
done folder, interval. Files: .json / .csv / .txt / .pdf - fields found by name (GCS no, vehicle, customer, invoice, ...).
Developed by DT
"""
import io, json, logging, re, threading, time, csv
from datetime import datetime
from ftplib import FTP
from sqlalchemy.orm import Session
from . import models, config, services
from .models import utcnow

log = logging.getLogger("gcs")
KEYS = ["gcs_enabled", "gcs_host", "gcs_port", "gcs_user", "gcs_password", "gcs_folder", "gcs_pattern", "gcs_done_folder",
        "gcs_interval_sec", "gcs_plant", "gcs_tls"]
_state = {"last_run": None, "last_ok": None, "last_error": None, "files": 0, "created": 0, "updated": 0, "skipped": 0}
_lock = threading.Lock()

# field name variants we accept in JSON keys / CSV headers / "Label: value" lines of a text or PDF document
FIELDS = {
    "gcs_no": ["gcs_no", "gcs no", "gcs number", "gcs", "gate pass no", "gate pass", "gatepass no", "gp no"],
    "vehicle_no": ["vehicle_no", "vehicle no", "vehicle", "truck no", "truck", "lorry no"],
    "customer_code": ["customer_code", "customer code", "customer", "consignee code", "ship to code", "ship_to"],
    "customer_name": ["customer_name", "customer name", "consignee", "ship to"],
    "invoice_no": ["invoice_no", "invoice no", "invoice number", "invoice", "inv no", "inv number"],
    "invoice_date": ["invoice_date", "invoice date", "inv date"],
    "so_number": ["so_number", "so no", "sale order", "sales order", "order no"],
    "part_no": ["part_no", "part no", "item", "item code", "item no", "part"],
    "part_desc": ["part_desc", "item description", "description", "item desc", "part name", "part description"],
    "part_qty": ["part_qty", "total qty", "total quantity", "qty", "quantity", "invoice qty"],
    "cust_part": ["cust_part", "cust part", "customer part", "customer part no", "cust part no", "customer part number"],
    "cases": ["cases", "case", "no of cases", "no of case", "case count"],
    "qty_per_case": ["qty_per_case", "qty case", "qty per case", "std pack", "pack qty", "standard pack"],
    "pallets": ["pallets", "pallet qty", "no of pallets", "pallet count"],
    "transporter": ["transporter", "transporter code", "transporter name"],
    "to_plant": ["to_plant", "to plant", "dest plant", "destination plant"],
    "dispatch_type": ["dispatch_type", "type", "order type"],
    "ewaybill_no": ["ewaybill_no", "e-way bill", "eway bill", "ewb no", "e way bill no"],
    "plant": ["plant", "plant code", "org", "from plant"],
    "pdi_sign": ["pdi_sign", "pdi by", "pdi", "pdi user", "pdi checked by", "qc by", "quality by", "pdi name"],
    "supervisor_sign": ["supervisor_sign", "shift supervisor", "supervisor", "shift incharge", "shift in-charge", "planned by", "bench user", "created by"],
    "pdi_login": ["pdi login", "pdi id", "pdi user id"],
    "supervisor_login": ["supervisor login", "supervisor id", "shift supervisor id", "bench login"],
}


def sign(name, login) -> str | None:
    name = str(name or "").strip(); login = str(login or "").strip()
    if not name and not login:
        return None
    return f"{name} ({login})" if name and login and login.lower() not in name.lower() else (name or login)


def _norm(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(k or "").lower()).strip()


def _lookup(d: dict) -> dict:
    nd = {_norm(k): (v if not isinstance(v, str) else v.strip()) for k, v in d.items()}
    out = {}
    for field, names in FIELDS.items():
        for n in names:
            if _norm(n) in nd and nd[_norm(n)] not in (None, ""):
                out[field] = nd[_norm(n)]; break
    return out


def parse_text(text: str) -> dict:
    """'Label : value' pairs on lines (also 'Label value' when the label is known), e.g. from a PDF or TXT gate pass."""
    d = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z][A-Za-z .\-/]{1,30}?)\s*[:#\-]\s*(.+?)\s*$", line)
        if m:
            d.setdefault(m.group(1), m.group(2))
    out = _lookup(d)
    if "gcs_no" not in out:
        m = re.search(r"\b(GCS[-/ ]?[A-Z0-9][A-Z0-9\-/]{3,})\b", text, re.I)
        if m:
            out["gcs_no"] = m.group(1).replace(" ", "")
    if "vehicle_no" not in out:
        m = re.search(r"\b([A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,3}\s?\d{3,4})\b", text)
        if m:
            out["vehicle_no"] = m.group(1)
    return out


def parse_file(name: str, data: bytes) -> list[dict]:
    """One file may hold one GCS (json/txt/pdf) or many (csv, json list). Returns a list of field dicts."""
    low = name.lower()
    if low.endswith(".json"):
        j = json.loads(data.decode("utf-8-sig"))
        if isinstance(j, dict) and _lookup(j).get("gcs_no") and isinstance(j.get("items") or j.get("lines"), list):
            head = {k: v for k, v in j.items() if not isinstance(v, (list, dict))}      # one GCS with its invoice lines
            return [_lookup({**head, **r}) for r in (j.get("items") or j.get("lines")) if isinstance(r, dict)]
        rows = j if isinstance(j, list) else (j.get("gcs") or j.get("items") or j.get("rows") or [j])
        return [_lookup(r) for r in rows if isinstance(r, dict)]
    if low.endswith(".csv") or low.endswith(".txt") and b"," in data.split(b"\n", 1)[0]:
        rd = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        return [_lookup(r) for r in rd]
    if low.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)
        except Exception as e:
            raise RuntimeError(f"cannot read PDF ({e}) - install pypdf or drop a JSON/CSV next to it")
        return [parse_text(text)]
    return [parse_text(data.decode("utf-8", "replace"))]


def get_settings(db: Session) -> dict:
    out = {k: None for k in KEYS}
    for s in db.query(models.Setting).filter(models.Setting.key.in_(KEYS)).all():
        out[s.key] = s.value
    out["gcs_enabled"] = (out["gcs_enabled"] or "0") == "1"
    out["gcs_tls"] = (out["gcs_tls"] or "0") == "1"
    out["gcs_port"] = int(out["gcs_port"] or 21)
    out["gcs_interval_sec"] = max(15, int(out["gcs_interval_sec"] or 60))
    out["gcs_pattern"] = out["gcs_pattern"] or r".*\.(json|csv|txt|pdf)$"
    out["gcs_folder"] = out["gcs_folder"] or "/"
    return out


def save_settings(db: Session, data: dict):
    for k in KEYS:
        if k not in data or (k == "gcs_password" and not data[k]):
            continue
        v = data[k]
        v = ("1" if v else "0") if k in ("gcs_enabled", "gcs_tls") else (None if v in (None, "") else str(v))
        row = db.get(models.Setting, k) or models.Setting(key=k)
        row.value = v; db.add(row)


def _int(v):
    try:
        return int(float(str(v).replace(",", ""))) if v not in (None, "") else None
    except ValueError:
        return None


def _date(v):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(v)[:11].strip(), fmt)
        except ValueError:
            continue
    return None


def _line_qty(r):
    """Total qty of an invoice line; when only cases x qty/case are given, their product."""
    q = _int(r.get("part_qty"))
    if q is None and _int(r.get("cases")) and _int(r.get("qty_per_case")):
        q = _int(r.get("cases")) * _int(r.get("qty_per_case"))
    return q


def group_rows(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    """CSV / JSON rows -> [(header, invoice lines)] per GCS. One GCS may have many rows (invoice x item)."""
    out, idx = [], {}
    for r in rows:
        g = str(r.get("gcs_no") or "").strip().upper()
        if not g:
            continue
        if g not in idx:
            idx[g] = len(out); out.append((dict(r), []))
        head, items = out[idx[g]]
        for k, v in r.items():                     # header: first non-empty value wins
            head.setdefault(k, v)
        if any(r.get(k) not in (None, "") for k in ("invoice_no", "part_no", "part_qty")):
            items.append(r)
    return out


def apply_gcs(db: Session, plant: str, f: dict, source_file: str | None = None, items: list[dict] | None = None) -> tuple[str, models.PickList | None]:
    """Create / refresh the loading sheet for one GCS with its invoice lines (invoice, item, qty at line level).
    Returns ('created'|'updated'|'skipped', picklist)."""
    if items is None:
        items = [f] if any(f.get(k) not in (None, "") for k in ("invoice_no", "part_no", "part_qty")) else []
    gcs = str(f.get("gcs_no") or "").strip().upper()
    if not gcs:
        return "skipped", None
    no = f"GCS-{plant}-{re.sub(r'[^A-Z0-9]+', '', gcs)[-20:]}"
    pk = db.query(models.PickList).filter(models.PickList.plant_code == plant, models.PickList.gcs_no == gcs).first() or db.get(models.PickList, no)
    cust = str(f.get("customer_code") or f.get("customer_name") or "?").strip()[:20]
    to_plant = (str(f.get("to_plant") or "").strip().upper() or None)
    dt = "STOCK_TRANSFER" if (to_plant and db.get(models.Plant, to_plant)) else "CUSTOMER"
    if not pk:
        pk = models.PickList(picklist_no=no, plant_code=plant, customer_code=cust, dispatch_type=dt, source="GCS", ext_ref=gcs, gcs_no=gcs,
                             qty=0, part_qty=0, status="OPEN", created_by="GCS_INBOX", load_point="VEHICLE")
        db.add(pk); db.flush(); what = "created"
    else:
        if pk.status not in ("OPEN",):
            return "skipped", pk                   # already loaded / dispatched: frozen
        what = "updated"
    pk.gcs_no = gcs; pk.customer_code = cust if cust != "?" else pk.customer_code; pk.to_plant = to_plant or pk.to_plant
    pk.vehicle_no = (str(f.get("vehicle_no") or pk.vehicle_no or "").upper().replace(" ", "") or None)
    pk.ewaybill_no = str(f.get("ewaybill_no") or pk.ewaybill_no or "")[:20] or None
    pk.transporter_code = str(f.get("transporter") or pk.transporter_code or "")[:20] or None
    pk.pdi_sign = (sign(f.get("pdi_sign"), f.get("pdi_login")) or pk.pdi_sign or None)
    pk.supervisor_sign = (sign(f.get("supervisor_sign"), f.get("supervisor_login")) or pk.supervisor_sign or None)
    if items:                                      # line level: replace the invoice lines of this GCS
        db.query(models.PickListItem).filter_by(picklist_no=pk.picklist_no).delete()
        for i, r in enumerate(items, 1):
            db.add(models.PickListItem(picklist_no=pk.picklist_no, line_no=i, invoice_no=(str(r.get("invoice_no") or f.get("invoice_no") or "")[:40] or None),
                                       invoice_date=_date(r.get("invoice_date") or f.get("invoice_date") or ""),
                                       so_number=(str(r.get("so_number") or "")[:40] or None), part_no=(str(r.get("part_no") or "")[:40] or None),
                                       part_desc=(str(r.get("part_desc") or "")[:80] or None), cust_part=(str(r.get("cust_part") or "")[:40] or None),
                                       cases=_int(r.get("cases")), qty_per_case=_int(r.get("qty_per_case")),
                                       qty=_line_qty(r), pallets=_int(r.get("pallets"))))
        invs = list(dict.fromkeys(str(r.get("invoice_no") or f.get("invoice_no") or "") for r in items if (r.get("invoice_no") or f.get("invoice_no"))))
        parts = list(dict.fromkeys(str(r.get("part_no")) for r in items if r.get("part_no")))
        sos = list(dict.fromkeys(str(r.get("so_number")) for r in items if r.get("so_number")))
        # header keeps a summary (first value + count) for lists / HHT; the full detail is in picklist_items
        pk.invoice_no = ((invs[0] + (f" +{len(invs) - 1}" if len(invs) > 1 else ""))[:40]) if invs else pk.invoice_no
        pk.so_number = ((sos[0] + (f" +{len(sos) - 1}" if len(sos) > 1 else ""))[:40]) if sos else pk.so_number
        pk.part_no = ((parts[0] + (f" +{len(parts) - 1}" if len(parts) > 1 else ""))[:40]) if parts else pk.part_no
        q = [_line_qty(r) for r in items]
        pk.part_qty = sum(x for x in q if x) if any(q) else pk.part_qty
        pl = [_int(r.get("pallets")) for r in items]
        hp = _int(f.get("pallets")) if len(items) == 1 else None
        pk.qty = sum(x for x in pl if x) if any(pl) and not hp else (hp or pk.qty)
        d = _date(items[0].get("invoice_date") or f.get("invoice_date") or "")
        pk.invoice_date = d or pk.invoice_date
    else:
        pk.qty = _int(f.get("pallets")) or pk.qty
    pk.remarks = (f"GCS from {source_file}" if source_file else pk.remarks)
    return what, pk


def _ftp(cfg):
    if cfg["gcs_tls"]:
        from ftplib import FTP_TLS
        f = FTP_TLS(); f.connect(cfg["gcs_host"], cfg["gcs_port"], timeout=20); f.login(cfg["gcs_user"] or "anonymous", cfg["gcs_password"] or ""); f.prot_p()
    else:
        f = FTP(); f.connect(cfg["gcs_host"], cfg["gcs_port"], timeout=20); f.login(cfg["gcs_user"] or "anonymous", cfg["gcs_password"] or "")
    return f


def pull(db: Session, fetch=None) -> dict:
    """fetch() -> list of (name, bytes); injectable for tests. Files are moved to the done folder after import."""
    cfg = get_settings(db)
    _state["last_run"] = utcnow()
    plant = (cfg["gcs_plant"] or "").upper()
    if not db.get(models.Plant, plant):
        raise RuntimeError(f"Set the AIS plant for the GCS inbox (now '{plant or '-'}')")
    pat = re.compile(cfg["gcs_pattern"], re.I)
    done_names = []
    if fetch is None:
        if not cfg["gcs_host"]:
            raise RuntimeError("GCS inbox not configured (FTP host)")
        f = _ftp(cfg); f.cwd(cfg["gcs_folder"])
        names = [n for n in f.nlst() if pat.match(n.rsplit("/", 1)[-1])]
        files = []
        for n in names:
            buf = io.BytesIO(); f.retrbinary("RETR " + n, buf.write); files.append((n, buf.getvalue()))
    else:
        f = None; files = [(n, b) for n, b in fetch() if pat.match(n)]
    created = updated = skipped = 0
    for name, data in files:
        try:
            for head, items in group_rows(parse_file(name, data)):
                what, _ = apply_gcs(db, plant, head, name, items)
                created += what == "created"; updated += what == "updated"; skipped += what == "skipped"
            done_names.append(name)
        except Exception as e:
            log.warning("GCS file %s: %s", name, e); _state["last_error"] = f"{name}: {e}"[:300]
    db.commit()
    if f is not None:
        for n in done_names:
            try:
                if cfg["gcs_done_folder"]:
                    f.rename(n, cfg["gcs_done_folder"].rstrip("/") + "/" + n.rsplit("/", 1)[-1])
                else:
                    f.delete(n)
            except Exception as e:
                log.warning("GCS move %s: %s", n, e)
        try:
            f.quit()
        except Exception:
            pass
    _state.update(last_ok=utcnow(), files=len(files), created=created, updated=updated, skipped=skipped)
    if not _state.get("last_error") or done_names:
        _state["last_error"] = None if len(done_names) == len(files) else _state["last_error"]
    return {"files": len(files), "created": created, "updated": updated, "skipped": skipped}


def status() -> dict:
    return dict(_state)


def start_scheduler(SessionLocal):
    def loop():
        while True:
            wait = 60
            try:
                with SessionLocal() as db:
                    cfg = get_settings(db)
                    if cfg["gcs_enabled"]:
                        pull(db)
                    wait = cfg["gcs_interval_sec"]
            except Exception as e:
                _state["last_error"] = str(e)[:300]; log.warning("gcs pull: %s", e)
            time.sleep(max(15, wait))
    threading.Thread(target=loop, name="gcs-inbox", daemon=True).start()


# ---------------------------------------------------------------- signed GCS QR for the print / OUT gate
# AIS1|GCS|<gcs no>|<plant>|<customer>|<vehicle>|<pallets>|<yyMMddHHmm>|<sig8>
def gcs_qr(pk: models.PickList, pallets: int) -> str:
    ts = (pk.updated_at or utcnow()).strftime("%y%m%d%H%M")
    body = f"AIS1|GCS|{pk.gcs_no}|{pk.plant_code}|{pk.customer_code}|{pk.vehicle_no or ''}|{pallets}|{ts}"
    return f"{body}|{services._sig(body)}"


def parse_gcs_qr(code: str) -> dict | None:
    s = (code or "").strip()
    if not s.startswith("AIS1|GCS|"):
        return None
    parts = s.split("|")
    if len(parts) != 9:
        return {"gcs_no": None, "valid": False, "error": "QR format not recognised"}
    body, sig = "|".join(parts[:8]), parts[8]
    ok = services._sig_ok(body, sig)
    return {"gcs_no": parts[2], "plant": parts[3], "customer": parts[4], "vehicle": parts[5], "pallets": int(parts[6] or 0),
            "valid": ok, "error": None if ok else "GCS QR check code invalid - not printed by AssetTrack"}


# ---------------------------------------------------------------- invoice lines with loaded quantity
def items_loaded(db: Session, picklist_no: str) -> list[dict]:
    """Invoice lines of a GCS with the quantity loaded so far (part cards scanned, matched by item; when the same item
    is on several invoices the loaded quantity fills the lines in order)."""
    items = db.query(models.PickListItem).filter_by(picklist_no=picklist_no).order_by(models.PickListItem.line_no).all()
    left = {}
    for r in db.query(models.PickListLpn).filter(models.PickListLpn.picklist_no == picklist_no,
                                                 (models.PickListLpn.pdi_result == "OK") | models.PickListLpn.pdi_result.is_(None)).all():
        k = (r.part_no or "").upper(); left[k] = left.get(k, 0) + (r.qty or 0)
    out = []
    for it in items:
        k = (it.part_no or "").upper(); need = it.qty or 0
        got = min(left.get(k, 0), need) if need else left.get(k, 0)
        left[k] = left.get(k, 0) - got
        out.append({"line_no": it.line_no, "invoice_no": it.invoice_no, "invoice_date": it.invoice_date, "so_number": it.so_number,
                    "part_no": it.part_no, "part_desc": it.part_desc, "cust_part": it.cust_part, "cases": it.cases,
                    "qty_per_case": it.qty_per_case, "qty": it.qty, "pallets": it.pallets, "loaded": got})
    return out


def short_pallet(no: str | None) -> str:
    """AIS-CHN-ANF-00001-0000001 -> ANF-00001 (pallet type + type serial); other numbers unchanged."""
    m = services.PALLET_ID_RE.match(str(no or "").upper())
    return f"{m.group(2)}-{m.group(3)}" if m else str(no or "")
