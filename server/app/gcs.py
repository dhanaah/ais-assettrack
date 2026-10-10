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
    "invoice_no": ["invoice_no", "invoice no", "invoice number", "invoice", "inv no"],
    "invoice_date": ["invoice_date", "invoice date", "inv date"],
    "so_number": ["so_number", "so no", "sale order", "sales order", "order no"],
    "part_no": ["part_no", "part no", "item", "item code", "part"],
    "part_qty": ["part_qty", "qty", "quantity", "invoice qty"],
    "pallets": ["pallets", "pallet qty", "no of pallets", "pallet count"],
    "transporter": ["transporter", "transporter code", "transporter name"],
    "to_plant": ["to_plant", "to plant", "dest plant", "destination plant"],
    "dispatch_type": ["dispatch_type", "type", "order type"],
    "ewaybill_no": ["ewaybill_no", "e-way bill", "eway bill", "ewb no", "e way bill no"],
    "plant": ["plant", "plant code", "org", "from plant"],
}


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


def apply_gcs(db: Session, plant: str, f: dict, source_file: str | None = None) -> tuple[str, models.PickList | None]:
    """Create / refresh the loading sheet for one GCS. Returns ('created'|'updated'|'skipped', picklist)."""
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
    pk.invoice_no = str(f.get("invoice_no") or pk.invoice_no or "") or None
    pk.so_number = str(f.get("so_number") or pk.so_number or "") or None
    pk.part_no = str(f.get("part_no") or pk.part_no or "")[:40] or None
    pk.ewaybill_no = str(f.get("ewaybill_no") or pk.ewaybill_no or "")[:20] or None
    pk.transporter_code = str(f.get("transporter") or pk.transporter_code or "")[:20] or None
    try:
        pk.part_qty = int(float(f.get("part_qty"))) if f.get("part_qty") not in (None, "") else pk.part_qty
    except ValueError:
        pass
    try:
        pk.qty = int(float(f.get("pallets"))) if f.get("pallets") not in (None, "") else pk.qty
    except ValueError:
        pass
    if f.get("invoice_date"):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
            try:
                pk.invoice_date = datetime.strptime(str(f["invoice_date"])[:11].strip(), fmt); break
            except ValueError:
                continue
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
            for fields in parse_file(name, data):
                what, _ = apply_gcs(db, plant, fields, name)
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
