"""Customer's manual return document (photo read on the HHT) -> pallet numbers, matched to the AIS ledger.

The HHT reads the text from the photo (on-device text recognition). Here the text is turned into pallet references
and matched with the pallets the ledger shows at that customer, allowing for the usual reading mistakes:
  * full QR number   AIS-CHN-F-02948-0010001
  * type + serial    F-2948, F.2948, F 02948, NF7944, RW-1392   (the ERP / short form)
  * number only      2948 (matched when only one pallet at the customer has that serial)
  * reading slips    O/0, I/1, S/5, B/8, Z/2, G/6 in numbers; one wrong digit -> "probable" (to be confirmed at the yard)
Optional, for handwriting and unusual layouts: an AI vision reading of the photo on the server (only when IT sets
PALLET_AI_API_KEY; the photo then goes to that AI service) - its pallet list is merged with the HHT's text.
Option B stays a count; the matched list is kept with the slip and compared at pallet-yard receiving. Developed by DT
Developed by DT"""
import base64, logging, os, re
from sqlalchemy.orm import Session
from . import models, services

_DIG = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})
_FULL = re.compile(r"AIS\s*[-. ]?\s*[A-Z]{2,6}\s*[-. ]\s*([A-Z]{1,8})\s*[-. ]\s*([0-9OILSBZG]{3,8})")
_TYPED = re.compile(r"(?<![A-Z0-9])([A-Z]{1,4})\s*[-./ ]?\s*([0-9][0-9OILSBZG]{2,6}|[OILSBZG][0-9][0-9OILSBZG]{1,5})(?![0-9])")
_LABELS = {"NO", "DC", "DN", "INV", "BILL", "PO", "SO", "QTY", "NOS", "TOTAL", "DATE", "DT", "VEH", "PH", "MOB", "CELL", "TEL", "GST", "PIN",
           "CODE", "REF", "CH", "CHL", "GP", "LR", "RS", "AMT", "KG", "KGS", "WT", "SL", "SR", "S", "SNO", "PAGE", "PG"}
_NUM = re.compile(r"(?<![A-Z0-9])(\d{3,7})(?![0-9])")


def type_aliases(db: Session) -> dict[str, str]:
    """Words a customer may write for a pallet type -> type code: the code itself (F, NF, RW) and the
    description from the pallet type master ("FLAT", "NON FLAT", "RACK WINDSHIELD")."""
    al = {}
    codes = {k[0] for k in (_key(p.pallet_no) for p in db.query(models.Pallet.pallet_no).all()) if k}
    for c in codes:
        al[c] = c
    for pt in db.query(models.PalletType).all():
        code = (pt.code or "").upper()
        if not code:
            continue
        al[code] = code
        d = re.sub(r"[^A-Z ]+", " ", (pt.description or "").upper())
        d = re.sub(r"\b(PALLETS?|PLTS?|TYPE|RETURNABLE|EMPTY)\b", " ", d)
        d = re.sub(r"\s+", " ", d).strip()
        if len(d) >= 3:
            al[d] = code
    return al


def type_counts(text: str, aliases: dict[str, str]) -> tuple[dict[str, int], str]:
    """Pallets written by type only: 'F - 4', 'NF:2 NOS', 'RW x 3', 'FLAT PALLET 6', '4 NOS F'.
    Returns ({type: qty}, text with those parts blanked so they are not read as serial numbers)."""
    t = (text or "").upper()
    if not aliases:
        return {}, t
    alt = "|".join(re.escape(a).replace("\\ ", "\\s*") for a in sorted(aliases, key=len, reverse=True))
    unit = r"(?:NOS?\.?|PCS\.?|PALLETS?|PLTS?)"
    fwd = re.compile(rf"(?<![A-Z0-9])({alt})(?:\s*(?:PALLETS?|PLTS?|TYPE))?\s*[-:=X*×]?\s*(\d{{1,3}})\s*({unit})?(?![0-9A-Z/.-])")
    rev = re.compile(rf"(?<![0-9A-Z/.-])(\d{{1,3}})\s*{unit}?\s*(?:OF\s*)?({alt})(?:\s*(?:PALLETS?|PLTS?))?(?![A-Z0-9])")
    out: dict[str, int] = {}
    spans = []
    for m in fwd.finditer(t):
        name, n, u = m.group(1), int(m.group(2)), m.group(3)
        if (len(m.group(2)) <= 2 or u) and 0 < n < 500:      # 3+ digits without "nos" = a serial number
            code = aliases.get(re.sub(r"\s+", " ", name).strip())
            if code:
                out[code] = out.get(code, 0) + n; spans.append(m.span())
    for m in rev.finditer(t):
        if any(a <= m.start() < b for a, b in spans):
            continue
        n, name = int(m.group(1)), m.group(2)
        code = aliases.get(re.sub(r"\s+", " ", name).strip())
        if code and 0 < n < 500 and re.search(rf"\d\s*{unit}", m.group(0)) or (code and re.search(r"PALLETS?|PLTS?", m.group(0))):
            out[code] = out.get(code, 0) + n; spans.append(m.span())
    for a, b in sorted(spans, reverse=True):
        t = t[:a] + " " * (b - a) + t[b:]
    return out, t


def _key(pallet_no: str):
    m = services.PALLET_ID_RE.match(pallet_no or "")
    return (m.group(2), int(m.group(3))) if m else None


def tokens(text: str, types: set[str]) -> list[dict]:
    """Pallet references in the text: [{raw, type or None, serial}] (each serial once)."""
    t = (text or "").upper()
    # vehicle numbers (TN 22 BX 7310) and numbers written after a document label (DC No HM/RDC/24518) are not pallets
    t = re.sub(r"\b[A-Z]{2}\s?-?\d{1,2}\s?-?[A-Z]{1,3}\s?-?\d{3,4}\b", " ", t)
    t = re.sub(r"\b(?:PIN|PINCODE)?\s*[-:]?\s*\b\d{3}\s\d{3}\b", " ", t)        # postal PIN code 602 117
    t = re.sub(r"\b(?:DC|D\.C\.|CHALLAN|INVOICE|INV|PO|GP|LR|GR|BILL|REF|GSTIN|PIN|MOB(?:ILE)?|PH(?:ONE)?)\s*(?:NO\.?|NUMBER|#)?\s*[:.\-]?\s*[A-Z0-9/\-]*\d[A-Z0-9/\-]*", " ", t)
    t = re.sub(r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b\d{1,2}[-/. ](JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[-/. ]\d{2,4}\b|\b\d{1,2}:\d{2}(:\d{2})?\b", " ", t)  # dates, times
    out, seen, used = [], set(), []
    for m in _FULL.finditer(t):
        typ, num = m.group(1), m.group(2).translate(_DIG)
        if num.isdigit():
            out.append({"raw": m.group(0).strip(), "type": typ if typ in types else None, "serial": int(num)}); used.append(m.span())
    for m in _TYPED.finditer(t):
        if any(a <= m.start() < b for a, b in used):
            continue
        typ, num = m.group(1), m.group(2).translate(_DIG)
        if not num.isdigit():
            continue
        if typ not in types and typ in _LABELS:   # "DC No 7781", "Inv 2041", "Qty 120": a document field, not a pallet
            used.append(m.span()); continue
        if typ not in types:                      # word in front is not a pallet type: number only
            typ = typ[-2:] if typ[-2:] in types else typ[-1:] if typ[-1:] in types else None
        out.append({"raw": m.group(0).strip(), "type": typ, "serial": int(num)}); used.append(m.span())
    for m in _NUM.finditer(t):
        if any(a <= m.start() < b for a, b in used):
            continue
        out.append({"raw": m.group(1), "type": None, "serial": int(m.group(1))})
    res = []
    for x in out:
        k = (x["type"], x["serial"])
        if k not in seen:
            seen.add(k); res.append(x)
    return res


def _one_off(a: int, b: int) -> bool:
    sa, sb = str(a), str(b)
    if len(sa) == len(sb):
        return sum(1 for x, y in zip(sa, sb) if x != y) == 1
    if abs(len(sa) - len(sb)) == 1:               # one digit dropped / added
        s, l = (sa, sb) if len(sa) < len(sb) else (sb, sa)
        return any(l[:i] + l[i + 1:] == s for i in range(len(l)))
    return False


def match(db: Session, plant: str, customer: str, text: str) -> dict:
    """-> {matched:[{pallet_no, ref, raw, how}], probable:[...], other:[{.., status, customer}], unread:[raw], read:n}"""
    at_cust = [p for p in db.query(models.Pallet).filter_by(customer_code=customer, status="AT_CUSTOMER").all() if _key(p.pallet_no)]
    types = {k[0] for k in (_key(p.pallet_no) for p in db.query(models.Pallet.pallet_no).all()) if k}
    by_key = {_key(p.pallet_no): p for p in at_cust}
    tcount, rest_text = type_counts(text, type_aliases(db))
    toks = tokens(rest_text, types)
    matched, probable, other, unread, taken = [], [], [], [], set()

    def add(lst, p, t, how, **extra):
        taken.add(p.pallet_no)
        lst.append({"pallet_no": p.pallet_no, "ref": services.short_ref(p.pallet_no), "raw": t["raw"], "how": how, **extra})

    rest = []
    for t in toks:                                # 1. exact type + serial at this customer
        p = by_key.get((t["type"], t["serial"])) if t["type"] else None
        if p and p.pallet_no not in taken:
            add(matched, p, t, "exact")
        else:
            rest.append(t)
    rest2 = []
    for t in rest:                                # 2. number only, one pallet at the customer with that serial
        c = [p for p in at_cust if _key(p.pallet_no)[1] == t["serial"] and p.pallet_no not in taken]
        if len(c) == 1:
            add(matched if not t["type"] else probable, c[0], t, "number" if not t["type"] else "type differs")
        else:
            rest2.append(t)
    for t in rest2:                               # 3. own pallet, but the ledger has it elsewhere
        if t["type"]:
            pno = services.pallet_from_ref(db, f"{t['type']}{t['serial']}", plant)
            pal = db.get(models.Pallet, pno) if pno else None
            if pal and pal.pallet_no not in taken:
                taken.add(pal.pallet_no)
                other.append({"pallet_no": pal.pallet_no, "ref": services.short_ref(pal.pallet_no), "raw": t["raw"], "how": "ledger elsewhere",
                              "status": pal.status, "customer": pal.customer_code})
                continue
        # 4. one digit misread -> probable (only when exactly one candidate at the customer)
        c = [p for p in at_cust if p.pallet_no not in taken and (not t["type"] or _key(p.pallet_no)[0] == t["type"]) and _one_off(_key(p.pallet_no)[1], t["serial"])]
        if len(c) == 1:
            add(probable, c[0], t, "one digit differs")
        elif t["type"] or len(str(t["serial"])) >= 4:
            unread.append(t["raw"])
    held = {}
    for p in at_cust:
        held[_key(p.pallet_no)[0]] = held.get(_key(p.pallet_no)[0], 0) + 1
    types_out = [{"type": k, "doc_qty": v, "at_customer": held.get(k, 0)} for k, v in sorted(tcount.items())]
    read = len(matched) + len(probable) + len(other) + len(unread)
    stated = stated_total(rest_text)
    how = "list" if read and not tcount else "types" if tcount and not read else "mixed" if tcount else "total" if stated else "none"
    return {"matched": matched, "probable": probable, "other": other, "unread": unread[:40], "read": read, "at_customer": len(at_cust),
            "type_counts": types_out, "stated_total": stated or (sum(tcount.values()) if tcount else None), "doc_kind": how}


# the count the customer wrote, strongest wording first
_TOTALS = [re.compile(r"TOTAL[^0-9\n]{0,25}?(\d{1,3})(?!\d)"),
           re.compile(r"(?:NO\.?\s*OF\s*)?(?:EMPTY\s*)?(?:PALLETS?|PLTS?|TROLLEYS?|BINS?)\s*(?:QTY|NOS?)?\s*[:=\-]?\s*(\d{1,3})(?![\d/.-])"),
           re.compile(r"(?<![\d/.-])(\d{1,3})\s*(?:NOS\.?|PCS\.?|NUMBERS)?\s*(?:OF\s*)?(?:EMPTY\s*)?(?:PALLETS?|PLTS?|TROLLEYS?|BINS?)\b"),
           re.compile(r"\bQTY\.?\s*[:=\-]?\s*(\d{1,3})(?![\d/.-])"),
           re.compile(r"(?<![\d/.-])(\d{1,3})\s*NOS\b")]


def stated_total(text: str) -> int | None:
    """'Total 6 pallets', 'No of pallets: 12', '14 Nos', 'Qty 6' -> the count the customer wrote."""
    t = (text or "").upper()
    for rx in _TOTALS:
        vals = [int(v) for v in rx.findall(t) if 0 < int(v) < 1000]
        if vals:
            return max(vals)
    return None


AI_PROMPT = ("Photo of a customer's document for returnable pallets sent back to the glass maker AIS (layout differs per customer; "
             "may be printed or handwritten, may be a table). List every PALLET identification written on it, one per line, exactly "
             "as written (examples: F-2948, NF7944, RW 1392, AIS-CHN-F-02948-0010001, or bare numbers in a pallet / trolley / bin "
             "column). Do NOT list document numbers, dates, vehicle numbers, phone numbers, quantities or part numbers. "
             "If a number is unclear, give your best reading. If pallets are written only by type with a quantity (e.g. F - 4, Flat pallet 6), "
             "write one line per type as TYPE QTY NOS. Last line: TOTAL=<pallet count stated on the document, or ?>")
log = logging.getLogger("docread")


def ai_enabled() -> bool:
    return bool(os.getenv("PALLET_AI_API_KEY"))


def ai_text(image: bytes, media_type: str = "image/jpeg") -> str | None:
    """AI vision reading of the photo (Anthropic Messages API format). None when not configured or not reachable."""
    key = os.getenv("PALLET_AI_API_KEY")
    if not key or not image:
        return None
    import httpx
    url = os.getenv("PALLET_AI_URL", "https://api.anthropic.com/v1/messages")
    body = {"model": os.getenv("PALLET_AI_MODEL", "claude-sonnet-5-5"), "max_tokens": 1500,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()}},
                {"type": "text", "text": AI_PROMPT}]}]}
    try:
        r = httpx.post(url, json=body, timeout=45, headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        r.raise_for_status()
        return "\n".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    except Exception as e:                       # never stops the gate: the HHT text is still used
        log.warning("AI document reading failed: %s", e)
        return None


def read(db: Session, plant: str, customer: str, device_text: str, image: bytes | None = None) -> dict:
    """HHT text (+ AI reading of the photo when enabled) -> match; the stated total is taken from either."""
    ai = ai_text(image) if image else None
    ai_total = None
    if ai:
        m = re.search(r"TOTAL\s*=\s*(\d+)", ai.upper()); ai_total = int(m.group(1)) if m else None
        ai = re.sub(r"(?im)^\s*TOTAL\s*=.*$", "", ai)
    text = "\n".join(x for x in (device_text, ai) if x)
    res = match(db, plant, customer, text)
    res.update({"ai": ai is not None, "ai_enabled": ai_enabled(), "stated_total": ai_total or res.get("stated_total"), "text": text[:20000]})
    return res
