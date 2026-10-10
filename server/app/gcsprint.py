"""GCS (gate pass) PDF: built when loading finishes and printed automatically on the plant's configured printer.
Contents: AIS header, GCS number, vehicle, consignee, invoice LINES (invoice, item, qty, loaded - one GCS may carry several
invoices), e-way bill, CHALLAN NUMBER, the loaded pallets (short number: type + serial) with
their part cards, the signed QR the OUT gate scans, and the SECURITY SIGN box with the login ID and name of the person
who completed the loading. PDFs are kept in gcs_docs/ next to the database (reprint from the web any time).
Printing: plant master -> gcs_print_mode WINDOWS (printer name, shared or network, via the Windows print verb) or
RAW9100 (printer IP, PDF sent directly - most network laser printers accept it) or OFF. Developed by DT
"""
import io, os, socket, subprocess, sys, threading, logging
from datetime import datetime
from sqlalchemy.orm import Session
from . import models, config
from .models import utcnow

log = logging.getLogger("gcsprint")


def docs_dir() -> str:
    url = os.environ.get("PALLET_DB_URL", "")
    base = os.path.dirname(url[len("sqlite:///"):]) if url.startswith("sqlite:///") else str(config.BASE_DIR)
    d = os.path.join(base or ".", "gcs_docs")
    os.makedirs(d, exist_ok=True)
    return d


def pdf_path(pk) -> str:
    import re
    return os.path.join(docs_dir(), f"GCS_{re.sub(r'[^A-Za-z0-9]+', '_', pk.gcs_no or pk.picklist_no)}.pdf")


_ONES = "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen".split()
_TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _words99(n):
    return _ONES[n] if n < 20 else _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])


def _words(n):
    """Indian numbering: crore, lakh, thousand, hundred."""
    if n == 0:
        return "Zero"
    out = []
    for div, name in ((10 ** 7, "Crore"), (10 ** 5, "Lakh"), (1000, "Thousand"), (100, "Hundred")):
        if n >= div:
            q, n = divmod(n, div)
            out.append(f"{_words(q) if q >= 100 else _words99(q)} {name}")
    if n:
        out.append(_words99(n))
    return " ".join(out)


def amount_in_words(v: float) -> str:
    r = int(v); p = int(round((v - r) * 100))
    return f"{_words(r)}" + (f" and paise {_words99(p)}" if p else "") + " only"


def build_pdf(db: Session, pk: models.PickList, user: models.User | None, qr_text: str, scale: float | None = None) -> bytes:
    """Same layout as the ERP 'Finished Goods Materials Gate Pass' (header, details block, invoice table with totals and
    amount in words) plus AssetTrack: OUT-gate QR, returnable pallet challan, the pallets loaded (6 columns, short number)
    and the PDI / Logistics / Security signs. Multi-page: table and pallet list continue with repeated headers, 'X of Y'."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    import segno, math
    from . import gcs as gcssvc
    plant = db.get(models.Plant, pk.plant_code)
    cust = db.query(models.Customer).filter_by(code=pk.customer_code, plant_code=pk.plant_code).first()
    lines = db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no).order_by(models.PickListLine.scanned_at).all()
    items = gcssvc.items_loaded(db, pk.picklist_no)
    invs = list(dict.fromkeys(i["invoice_no"] for i in items if i["invoice_no"]))
    to_plant = db.get(models.Plant, pk.to_plant) if pk.to_plant else None
    to_name = (to_plant.name if to_plant else None) or (cust.name if cust else None) or pk.customer_code
    loc = pk.customer_location or ((to_plant.city if to_plant and getattr(to_plant, "city", None) else None)
                                   or ((cust.city or cust.ship_to) if cust else None) or "")
    sales_type = pk.sales_type or {"STOCK_TRANSFER": "Stock Transfer", "CUSTOMER": "Sales"}.get(pk.dispatch_type or "", "")
    gp_dt = pk.gp_date or datetime.now()
    who = f"{user.full_name} ({user.user_id})" if user else "—"
    now = datetime.now()
    W, H = A4
    ink = (0.16, 0.2, 0.32); grey = (0.82, 0.84, 0.87); red = (0.78, 0.06, 0.18)
    qpng = io.BytesIO(); segno.make(qr_text, error="m").save(qpng, kind="png", scale=6, border=1); qbytes = qpng.getvalue()
    logo = os.path.join(str(config.BASE_DIR), "app", "static", "icon-192.png")
    x0, tw = 12 * mm, W - 24 * mm
    BOTTOM = 22 * mm
    # font scale: plant master "GCS font size %" (100 = standard, 90 = compact, 80 = small); row heights follow the font
    F = scale or (max(70, min(110, int(getattr(plant, "gcs_font_pct", None) or 90))) / 100)
    RH, PRH = 5.0 * mm * F, 4.2 * mm * F
    fnum = lambda v, d=0: "" if v in (None, "") else (f"{v:,.{d}f}" if d else f"{v:,}")
    # SI, Inv No, Inv Date, Item Code, Cust Part No, No of Case, Qty/Case, Act Qty, Line Amount, Pallet Type  (mm, sums to 186)
    cw = [8, 21, 18, 40, 26, 12, 12, 15, 22, 12]
    heads = [("Sl", ""), ("Inv No.", ""), ("Inv Date", ""), ("Item Code", ""), ("Cust Part No", ""), ("No of", "Case"),
             ("Qty", "/Case"), ("Act", "Qty"), ("Line Amount", ""), ("Pallet", "Type")]
    right = {0, 1, 2, 5, 6, 7, 8}
    has_amt = any(i.get("amount") for i in items)

    def render(total):
        buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4)
        st = {"page": 1}

        def txt(x, y, t, size=9, bold=False, color=(0, 0, 0), align="l"):
            c.setFillColorRGB(*color); c.setFont("Helvetica-Bold" if bold else "Helvetica", size * F)
            {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[align](x, y, str(t))
            c.setFillColorRGB(0, 0, 0)

        def page_top(first):
            """Gate pass number line + boxed company header (logo | title block | OUT-gate QR)."""
            y = H - 11 * mm
            txt(x0 + 2 * mm, y, f"Gate pass number: {pk.gcs_no}", 11)
            txt(x0 + tw - 2 * mm, y, f"{st['page']} of {total or '?'}", 11, align="r")
            hh = 34 * mm if first else 22 * mm
            top = y - 2.5 * mm
            c.setStrokeColorRGB(*ink); c.setLineWidth(1.6); c.rect(x0, top - hh, tw, hh)
            c.setLineWidth(0.6); c.rect(x0 + 1.5 * mm, top - hh + 1.5 * mm, tw - 3 * mm, hh - 3 * mm)
            lw, qw = (46 * mm, 32 * mm) if first else (30 * mm, 22 * mm)
            c.line(x0 + 1.5 * mm + lw, top - 1.5 * mm, x0 + 1.5 * mm + lw, top - hh + 1.5 * mm)
            c.line(x0 + tw - 1.5 * mm - qw, top - 1.5 * mm, x0 + tw - 1.5 * mm - qw, top - hh + 1.5 * mm)
            ls = (hh - 12 * mm) if first else (hh - 6 * mm)
            if os.path.exists(logo):
                c.drawImage(logo, x0 + 1.5 * mm + (lw - ls) / 2, top - 3 * mm - ls, ls, ls, mask="auto")
            if first:
                txt(x0 + 1.5 * mm + lw / 2, top - hh + 4 * mm, "Asahi India Glass Ltd.", 10, True, align="c")
            mid = x0 + 1.5 * mm + lw + (tw - 3 * mm - lw - qw) / 2
            addr = (plant.address or plant.name) if plant else pk.plant_code
            if first:
                txt(mid, top - 9 * mm, "Asahi India Glass Ltd", 17, align="c")
                txt(mid, top - 15.5 * mm, "Finished Goods Materials Gate Pass", 12.5, True, align="c")
                from reportlab.pdfbase.pdfmetrics import stringWidth
                maxw = tw - 3 * mm - lw - qw - 4 * mm; words = addr.split(); al, cur = [], ""
                for wd in words:                       # wrap the plant address to the middle cell (2 lines max)
                    t = (cur + " " + wd).strip()
                    if stringWidth(t, "Helvetica", 8.5) <= maxw:
                        cur = t
                    else:
                        al.append(cur); cur = wd
                al.append(cur)
                for li, ln in enumerate(al[:2]):
                    txt(mid, top - 20.5 * mm - li * 3.8 * mm, ln, 8.5, align="c")
                txt(mid, top - 30 * mm, "(Outward Non Returnable)", 11, align="c")
            else:
                txt(mid, top - 9 * mm, "Finished Goods Materials Gate Pass  (continued)", 11, True, align="c")
                txt(mid, top - 15 * mm, f"Vehicle {pk.vehicle_no or '—'}{(' (' + pk.vehicle_type + ')') if pk.vehicle_type else ''}   ·   To M/s {to_name}"[:80], 8.5, align="c")
            qs = qw - 5 * mm
            c.drawImage(ImageReader(io.BytesIO(qbytes)), x0 + tw - 1.5 * mm - qw + 2.5 * mm, top - 2.5 * mm - qs, qs, qs)
            if first:
                txt(x0 + tw - 1.5 * mm - qw / 2, top - hh + 3 * mm, "OUT GATE: scan QR", 6.5, align="c")
            return top - hh - 3 * mm

        def details(y):
            """Two-column details block as on the ERP gate pass (+ pallet challan / pallets loaded)."""
            left = [("GatePass Number:", pk.gcs_no), ("To M/s:", to_name), ("Vehicle No:", pk.vehicle_no or ""),
                    ("Transporter:", pk.transporter_name or pk.transporter_code or ""), ("Remarks:", pk.gcs_remarks or ""),
                    ("Pallet Challan No:", pk.challan_no or "pending")]
            rightc = [("Date:", f"{gp_dt:%d/%m/%Y}"), ("Location:", loc), ("Time:", f"{gp_dt:%H:%M:%S}"),
                      ("No of Invoices:", str(len(invs)) if invs else ""), ("GR/LR No.", pk.gr_lr_no or ""), ("Sales Type", sales_type),
                      ]
            rows = max(len(left), len(rightc)) + 1                 # last row: pallets loaded
            h = rows * 5.6 * mm * F + 5 * mm
            c.setStrokeColorRGB(*ink); c.setLineWidth(1.6); c.rect(x0, y - h, tw, h)
            c.setLineWidth(0.6); c.rect(x0 + 1.5 * mm, y - h + 1.5 * mm, tw - 3 * mm, h - 3 * mm)
            yy = y - 6.5 * mm
            for k in range(rows - 1):
                if k < len(left):
                    txt(x0 + 5 * mm, yy, left[k][0], 9.5, color=(0.25, 0.25, 0.25))
                    txt(x0 + 42 * mm, yy, str(left[k][1])[:42].upper() if k == 1 else str(left[k][1])[:42], 10, True,
                        color=red if left[k][0].startswith("Pallet") else (0, 0, 0))
                if k < len(rightc):
                    txt(x0 + 118 * mm, yy, rightc[k][0], 9.5, color=(0.25, 0.25, 0.25))
                    txt(x0 + 150 * mm, yy, str(rightc[k][1])[:22].upper() if k == 1 else str(rightc[k][1])[:22], 10, True)
                yy -= 5.6 * mm * F
            txt(x0 + 5 * mm, yy, "Pallets Loaded:", 9.5, color=(0.25, 0.25, 0.25))
            txt(x0 + 42 * mm, yy, f"{len(lines)}  (returnable)", 10, True)
            txt(x0 + 118 * mm, yy, "Vehicle Type:", 9.5, color=(0.25, 0.25, 0.25))
            txt(x0 + 150 * mm, yy, (pk.vehicle_type or "")[:22], 10, True)
            return y - h - 4 * mm

        def table_head(y):
            hh = 9 * mm * F; x = x0
            c.setFillColorRGB(*grey); c.rect(x0, y - hh, tw, hh, fill=1, stroke=0)
            c.setStrokeColorRGB(*ink); c.setLineWidth(0.8); c.rect(x0, y - hh, tw, hh)
            for k, (a, b) in enumerate(heads):
                w = cw[k] * mm
                if k:
                    c.line(x, y, x, y - hh)
                if k in right:
                    txt(x + w - 1.5 * mm, y - 4 * mm * F, a, 8, True, align="r");
                    if b: txt(x + w - 1.5 * mm, y - 7.7 * mm * F, b, 8, True, align="r")
                else:
                    txt(x + 1.5 * mm, y - 4 * mm * F, a, 8, True)
                    if b: txt(x + 1.5 * mm, y - 7.7 * mm * F, b, 8, True)
                x += w
            return y - hh

        def table_row(y, vals, bold=False, top_rule=False):
            x = x0
            c.setStrokeColorRGB(*ink); c.setLineWidth(0.5)
            for k, v in enumerate(vals):
                w = cw[k] * mm
                c.line(x, y, x, y - RH)
                if v != "":
                    from reportlab.pdfbase.pdfmetrics import stringWidth
                    size = 8.5                              # shrink the font so the text stays inside its cell
                    while size > 5.5 and stringWidth(str(v), "Helvetica-Bold" if bold else "Helvetica", size * F) > w - 2.5 * mm:
                        size -= 0.5
                    if k in right or (bold and k == 4):
                        txt(x + w - 1.5 * mm, y - RH + 1.5 * mm * F, v, size, bold, align="r")
                    else:
                        txt(x + 1.5 * mm, y - RH + 1.5 * mm * F, v, size, bold)
                x += w
            c.line(x0 + tw, y, x0 + tw, y - RH); c.line(x0, y - RH, x0 + tw, y - RH)
            return y - RH

        def footer():
            txt(x0, 13.5 * mm, f"AIS AssetTrack v{config.APP_VERSION} · Developed by DT · pick list {pk.picklist_no} · printed {now:%d-%m-%Y %H:%M}", 6.8, color=(0.4, 0.4, 0.4))
            txt(x0 + tw, 13.5 * mm, f"Page {st['page']} of {total or '?'}", 8, True, align="r")
            txt(x0, 9.5 * mm, "The OUT gate accepts only a QR printed by AssetTrack for this gate pass and vehicle.", 6.8, color=red)

        def new_page():
            footer(); c.showPage(); st["page"] += 1
            return page_top(False)

        y = page_top(True)
        y = details(y)
        # ---- invoice table (continues on the next page with the header repeated)
        if items:
            y = table_head(y)
            for k, it in enumerate(items):
                if y - RH < BOTTOM:
                    y = table_head(new_page())
                y = table_row(y, [str(k + 1), it["invoice_no"] or "", f"{it['invoice_date']:%d/%m/%Y}" if it["invoice_date"] else "",
                                  (it["part_no"] or "")[:30], (it["cust_part"] or "")[:22], fnum(it["cases"]), fnum(it["qty_per_case"]),
                                  fnum(it["qty"]), fnum(it.get("amount"), 2), (it.get("pallet_type") or "")[:6]])
            if y - RH - 9 * mm < BOTTOM:
                y = table_head(new_page())
            tot = lambda k: sum((i.get(k) or 0) for i in items)
            y = table_row(y, ["", "", "", "", "Total:", fnum(tot("cases")), fnum(tot("qty_per_case")), f"{tot('qty'):,.2f}",
                              fnum(tot("amount"), 2) if has_amt else "", ""], bold=True)
            if has_amt:
                y -= 6 * mm
                txt(x0 + 2 * mm, y, "Amount (In Words):", 9.5, color=(0.25, 0.25, 0.25))
                txt(x0 + 35 * mm, y, amount_in_words(tot("amount"))[:95], 9.5, True)
            y -= 7 * mm

        # ---- returnable pallets loaded: 6 columns, short number (type + serial)
        ncol, colw = 6, tw / 6

        def pal_head(y, cont=False):
            c.setFillColorRGB(*grey); c.rect(x0, y - 6 * mm * F, tw, 6 * mm * F, fill=1, stroke=0)
            c.setStrokeColorRGB(*ink); c.setLineWidth(0.8); c.rect(x0, y - 6 * mm * F, tw, 6 * mm * F)
            txt(x0 + 2 * mm, y - 4.2 * mm * F, f"RETURNABLE PALLETS LOADED: {len(lines)}" + ("  (continued)" if cont else "") + f"     ·     Pallet Challan No: {pk.challan_no or 'pending'}", 8.5, True)
            return y - 6 * mm * F

        if y - 6 * mm - PRH < BOTTOM:
            y = new_page()
        y = pal_head(y)
        i, n = 0, len(lines)
        while i < n:
            rows = min(max(1, int((y - BOTTOM) / PRH)), math.ceil((n - i) / ncol))
            chunk = lines[i:i + rows * ncol]
            for j, l in enumerate(chunk):
                ci, ri = divmod(j, rows)
                x = x0 + ci * colw; yy = y - (ri + 1) * PRH + 1.3 * mm * F
                txt(x + 7 * mm, yy, i + j + 1, 7, color=(0.45, 0.45, 0.45), align="r")
                txt(x + 9 * mm, yy, gcssvc.short_pallet(l.pallet_no)[:16], 7.2, True)
                c.setStrokeColorRGB(0.88, 0.88, 0.88); c.setLineWidth(0.25); c.line(x, y - (ri + 1) * PRH, x + colw, y - (ri + 1) * PRH)
            c.setStrokeColorRGB(*ink); c.setLineWidth(0.5)
            c.rect(x0, y - rows * PRH, tw, rows * PRH)
            for ci in range(1, ncol):
                c.line(x0 + ci * colw, y, x0 + ci * colw, y - rows * PRH)
            i += len(chunk); y -= rows * PRH
            if i < n:
                y = pal_head(new_page(), True)
        if not n:
            txt(x0 + 3 * mm, y - 4 * mm, "No pallets scanned", 8.5); y -= 6 * mm
        y -= 6 * mm
        # ---- signs (last page)
        sh = 28 * mm * max(F, 0.85)
        if y - sh < BOTTOM:
            y = new_page()
        signs = [("PDI", "Planning Bench login", pk.pdi_sign or "—", ""),
                 ("LOGISTICS", "Shift supervisor · Planning Bench login", pk.supervisor_sign or "—", ""),
                 ("SECURITY", "Loading verified · HHT login", who, f"{now:%d/%m/%Y %H:%M}")]
        sw = tw / 3
        for k, (label, sub, name, when) in enumerate(signs):
            x = x0 + k * sw
            c.setStrokeColorRGB(*ink); c.setLineWidth(0.8); c.rect(x, y - sh, sw, sh)
            txt(x + 2 * mm, y - 4.5 * mm, label, 8.5, True)
            txt(x + 2 * mm, y - 8 * mm, sub, 6.5, color=(0.4, 0.4, 0.4))
            txt(x + 2 * mm, y - 13.5 * mm, name[:40], 8.5)
            if when:
                txt(x + 2 * mm, y - 17.5 * mm, when, 8)
            txt(x + 2 * mm, y - sh + 3.5 * mm, "Sign: ______________________", 8)
        footer(); c.showPage(); c.save()
        return buf.getvalue(), st["page"]

    _, pages = render(None)             # pass 1 counts pages; pass 2 prints "X of Y"
    data, _ = render(pages)
    return data


# ---------------------------------------------------------------- printing
def print_pdf(path: str, plant: models.Plant) -> tuple[bool, str]:
    mode = (plant.gcs_print_mode or "OFF").upper()
    target = (plant.gcs_printer or "").strip()
    copies = max(1, int(plant.gcs_copies or 1))
    if mode == "OFF" or not target:
        return False, "automatic printing is OFF for this plant (Masters > Plants > GCS printer)"
    try:
        if mode == "RAW9100":
            host, _, port = target.partition(":")
            data = open(path, "rb").read()
            for _ in range(copies):
                with socket.create_connection((host, int(port or 9100)), timeout=20) as s:
                    s.sendall(data)
            return True, f"sent to {target} (raw)"
        if mode == "WINDOWS":
            if sys.platform != "win32":
                return False, "Windows printing only works on the Windows server"
            tools = os.path.join(os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)), "tools", "SumatraPDF.exe")
            tools2 = os.path.join(str(config.BASE_DIR), "tools", "SumatraPDF.exe")
            exe = tools if os.path.exists(tools) else tools2 if os.path.exists(tools2) else None
            if exe:      # most reliable: silent print with the portable SumatraPDF placed in tools\
                for _ in range(copies):
                    subprocess.run([exe, "-print-to", target, "-silent", "-exit-when-done", path], timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return True, f"printed on {target} (SumatraPDF)"
            import ctypes   # fallback: the PDF application registered in Windows prints to the named printer
            for _ in range(copies):
                r = ctypes.windll.shell32.ShellExecuteW(None, "printto", path, f'"{target}"', None, 0)
                if r <= 32:
                    return False, f"Windows could not print (code {r}) - put SumatraPDF.exe in the tools folder or set a default PDF app"
            return True, f"sent to {target} (Windows print)"
        return False, f"unknown print mode {mode}"
    except Exception as e:
        return False, str(e)[:200]


def generate_and_print(SessionLocal, picklist_no: str, user_pk: int | None, qr_text: str, do_print: bool = True) -> dict:
    """Build the PDF now (fast); print in the background so the HHT is not held up."""
    with SessionLocal() as db:
        pk = db.get(models.PickList, picklist_no)
        user = db.get(models.User, user_pk) if user_pk else None
        plant = db.get(models.Plant, pk.plant_code)
        data = build_pdf(db, pk, user, qr_text)
        path = pdf_path(pk)
        with open(path, "wb") as f:
            f.write(data)
        mode = (plant.gcs_print_mode or "OFF").upper(); printer = plant.gcs_printer
    res = {"pdf": os.path.basename(path), "print": "off" if not do_print or mode == "OFF" or not printer else f"queued on {printer}"}
    if do_print and mode != "OFF" and printer:
        def bg():
            with SessionLocal() as db:
                from . import integration
                pl = db.get(models.Plant, pk.plant_code)
                ok, msg = print_pdf(path, pl)
                integration._log(db, "PRINT", "GCS", picklist_no, ok, msg); db.commit()
                log.info("GCS print %s: %s", picklist_no, msg)
        threading.Thread(target=bg, daemon=True).start()
    return res
