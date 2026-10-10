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


def build_pdf(db: Session, pk: models.PickList, user: models.User | None, qr_text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    import segno
    plant = db.get(models.Plant, pk.plant_code)
    cust = db.query(models.Customer).filter_by(code=pk.customer_code, plant_code=pk.plant_code).first()
    lines = db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no).order_by(models.PickListLine.scanned_at).all()
    lpn_by = {}
    for r in db.query(models.PickListLpn).filter_by(picklist_no=pk.picklist_no).all():
        lpn_by.setdefault(r.pallet_no, []).append(r)
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); W, H = A4
    navy = (0.12, 0.23, 0.54); red = (0.78, 0.06, 0.18)
    qbuf = io.BytesIO(); segno.make(qr_text, error="m").save(qbuf, kind="png", scale=6, border=2); qbuf.seek(0)
    logo = os.path.join(str(config.BASE_DIR), "app", "static", "icon-192.png")

    def header(page_no):
        y = H - 15 * mm
        if os.path.exists(logo):
            c.drawImage(logo, 15 * mm, y - 16 * mm, 18 * mm, 18 * mm, mask="auto")
        c.setFillColorRGB(*navy); c.setFont("Helvetica-Bold", 14); c.drawString(36 * mm, y - 4 * mm, "Asahi India Glass Ltd.")
        c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica", 9)
        c.drawString(36 * mm, y - 9 * mm, f"{plant.name if plant else pk.plant_code}  ·  {(plant.address or '') if plant else ''}")
        c.drawString(36 * mm, y - 13 * mm, f"GSTIN {(plant.gstin or '') if plant else ''}")
        c.drawImage(ImageReader(qbuf), W - 15 * mm - 34 * mm, y - 34 * mm, 34 * mm, 34 * mm)
        c.setFont("Helvetica", 7); c.drawRightString(W - 15 * mm, y - 36.5 * mm, "OUT GATE: scan this QR")
        c.setStrokeColorRGB(*navy); c.setLineWidth(1.5); c.line(15 * mm, y - 19 * mm, W - 52 * mm, y - 19 * mm)
        c.setFillColorRGB(*navy); c.setFont("Helvetica-Bold", 13)
        c.drawString(15 * mm, y - 26 * mm, "GATE CUM SECURITY PASS (OUTWARD)")
        c.setFont("Helvetica", 9); c.setFillColorRGB(0.3, 0.3, 0.3); c.drawString(15 * mm, y - 31 * mm, "Vehicle loading record · returnable pallets")
        c.setFillColorRGB(0, 0, 0)
        if page_no > 1:
            c.setFont("Helvetica", 8); c.drawString(15 * mm, y - 35.5 * mm, f"GCS {pk.gcs_no} · page {page_no}")
        return y - 42 * mm

    def box(x, y, w, h, label, value, big=False):
        c.setStrokeColorRGB(0.75, 0.75, 0.75); c.setLineWidth(0.6); c.rect(x, y - h, w, h)
        c.setFont("Helvetica", 6.5); c.setFillColorRGB(0.35, 0.35, 0.35); c.drawString(x + 2 * mm, y - 3.5 * mm, label)
        c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica-Bold", 14 if big else 9.5)
        for i, ln in enumerate(str(value).split("\n")[:3]):
            c.drawString(x + 2 * mm, y - (9 if big else 7.5) * mm - i * 4 * mm, ln[:60])

    y = header(1)
    cw = (W - 30 * mm) / 3; bh = 13 * mm
    box(15 * mm, y, cw, bh, "GCS NO", pk.gcs_no, big=True)
    box(15 * mm + cw, y, cw, bh, "VEHICLE", pk.vehicle_no or "—", big=True)
    box(15 * mm + 2 * cw, y, cw, bh, "CHALLAN NO (RETURNABLE PALLETS)", pk.challan_no or "pending", big=True)
    y -= bh
    from . import gcs as gcssvc
    items = gcssvc.items_loaded(db, pk.picklist_no)
    has_cards = any(lpn_by.values())
    invs = list(dict.fromkeys(i["invoice_no"] for i in items if i["invoice_no"]))
    box(15 * mm, y, cw, bh, "CONSIGNEE", f"{cust.name if cust else pk.customer_code} ({pk.customer_code})" + (f"\nto plant {pk.to_plant}" if pk.to_plant else ""))
    box(15 * mm + cw, y, cw, bh, "INVOICES / E-WAY BILL", (f"{len(invs)} invoice(s) · {len(items)} line(s)" if items else f"{pk.invoice_no or '—'}") + f"\nEWB {pk.ewaybill_no or '—'}")
    box(15 * mm + 2 * cw, y, cw, bh, "LOADED", f"{len(lines)} pallet(s)" + (f" · qty {sum(r.qty or 0 for v in lpn_by.values() for r in v)}" if has_cards else "") + f"\n{datetime.now():%d-%m-%Y %H:%M}")
    y -= bh + 5 * mm
    import math
    sig_top = 52 * mm                                  # signature block + footer need the bottom 52 mm
    x0, tw = 15 * mm, W - 30 * mm

    def band(text, yy):
        c.setFillColorRGB(0.93, 0.95, 1); c.rect(x0, yy - 5.5 * mm, tw, 5.5 * mm, fill=1, stroke=0)
        c.setFillColorRGB(*navy); c.setFont("Helvetica-Bold", 7.5)
        return yy

    # ---- invoice lines (invoice, item, qty at line level) - one GCS may carry several invoices
    if items:
        n_i = len(items)
        irh = 4.6 * mm if n_i <= 8 else 4.0 * mm if n_i <= 16 else 3.5 * mm
        room = y - sig_top - 8 * mm - 32 * mm         # keep at least 32 mm for the pallet list
        cap_i = max(1, int(room / irh) - 3)
        shown_i = items[:cap_i]
        ifs = 7.5 if irh >= 4.6 * mm else 6.8 if irh >= 4 * mm else 6.2
        cols = [(1.5, "#", "l"), (7, "Invoice no", "l"), (40, "Inv date", "l"), (58, "SO no", "l"), (84, "Item", "l"), (114, "Description", "l"),
                (157, "Qty", "r"), (169, "Loaded", "r"), (178.5, "Pallets", "r")]
        band("", y)
        for xm, t, al in cols:
            (c.drawRightString if al == "r" else c.drawString)(x0 + xm * mm, y - 4 * mm, t)
        y -= 5.5 * mm; c.setFillColorRGB(0, 0, 0)
        for k, it in enumerate(shown_i):
            yy = y - (k + 1) * irh + 1.1 * mm
            short = has_cards and it["qty"] and (it["loaded"] or 0) < it["qty"]
            vals = [str(it["line_no"]), (it["invoice_no"] or "")[:18], f"{it['invoice_date']:%d-%m-%Y}" if it["invoice_date"] else "", (it["so_number"] or "")[:14],
                    (it["part_no"] or "")[:16], (it["part_desc"] or "")[:26], "" if it["qty"] is None else str(it["qty"]),
                    (str(it["loaded"]) if has_cards else "—"), "" if it["pallets"] is None else str(it["pallets"])]
            for (xm, t, al), v in zip(cols, vals):
                c.setFont("Helvetica-Bold" if t in ("Invoice no", "Item") else "Helvetica", ifs)
                if t == "Loaded" and short:
                    c.setFillColorRGB(*red)
                (c.drawRightString if al == "r" else c.drawString)(x0 + xm * mm, yy, v); c.setFillColorRGB(0, 0, 0)
            c.setStrokeColorRGB(0.88, 0.88, 0.88); c.setLineWidth(0.3); c.line(x0, y - (k + 1) * irh, x0 + tw, y - (k + 1) * irh)
        y -= len(shown_i) * irh
        c.setFont("Helvetica-Bold", ifs)
        c.drawString(x0 + 7 * mm, y - 3.6 * mm, f"TOTAL  {len(invs)} invoice(s)" + (f"  (first {len(shown_i)} of {n_i} lines shown - full list on the web)" if len(shown_i) < n_i else ""))
        c.drawRightString(x0 + 157 * mm, y - 3.6 * mm, str(sum(i["qty"] or 0 for i in items)))
        c.drawRightString(x0 + 169 * mm, y - 3.6 * mm, str(sum(i["loaded"] or 0 for i in items)) if has_cards else "—")
        c.drawRightString(x0 + 178.5 * mm, y - 3.6 * mm, str(sum(i["pallets"] or 0 for i in items)) if any(i["pallets"] for i in items) else "")
        y -= 8 * mm

    # ---- pallet list (short number: type + serial) - always ONE A4 sheet, 1..4 columns, rows shrink with the count
    avail = y - sig_top - 5.5 * mm - 10 * mm       # minus column-header band and the total line
    n = len(lines)
    for ncol in (1, 2, 3, 4, 5, 6):                  # short numbers (ANF-00001) allow up to 6 narrow columns
        per_col = max(1, math.ceil(n / ncol))
        if avail / per_col >= (4.4 * mm if ncol < 4 else 3.3 * mm) or ncol == 6:
            break
    rh = max(3.3 * mm, min(5.0 * mm, avail / per_col))
    fs = 8 if rh >= 4.8 * mm else 7 if rh >= 4.0 * mm else 6.2
    cap = max(1, int(avail / rh))
    shown = lines if per_col <= cap else lines[:cap * ncol]
    colw = tw / ncol
    band("", y)
    for ci in range(ncol):
        c.drawString(x0 + ci * colw + 1.5 * mm, y - 4 * mm, "#   Pallet" + ("        part cards (LPN · item × qty)" if ncol == 1 else "        part cards" if ncol < 4 else ""))
    c.setFillColorRGB(0, 0, 0); y -= 5.5 * mm
    per_col = max(1, math.ceil(len(shown) / ncol))
    for i, l in enumerate(shown):
        ci, ri = divmod(i, per_col)
        x = x0 + ci * colw; yy = y - (ri + 1) * rh + 1.2 * mm
        cards = ", ".join(f"{r.lpn_no}·{r.part_no}×{r.qty}" if ncol == 1 else r.lpn_no for r in lpn_by.get(l.pallet_no, []))
        c.setFont("Helvetica", fs); c.drawString(x + 1.5 * mm, yy, f"{i + 1:>3}")
        c.setFont("Helvetica-Bold", fs); c.drawString(x + 8 * mm, yy, gcssvc.short_pallet(l.pallet_no)[:16])
        c.setFont("Helvetica", fs - 0.5)
        if cards and ncol < 4:
            cx = x + 28 * mm
            maxc = int((colw - 29 * mm) / (fs * 0.5))
            c.drawString(cx, yy, cards[:max(6, maxc)])
        c.setStrokeColorRGB(0.88, 0.88, 0.88); c.setLineWidth(0.3); c.line(x, y - (ri + 1) * rh, x + colw, y - (ri + 1) * rh)
    y -= per_col * rh + 2 * mm
    c.setFont("Helvetica-Bold", 9)
    note = f"TOTAL PALLETS LOADED: {n}" + (f"   (first {len(shown)} listed - full list on the web)" if len(shown) < n else "")
    c.drawRightString(W - 15 * mm, y - 4 * mm, note); y = max(y - 10 * mm, sig_top + 2 * mm)
    # signatures
    sw = (W - 30 * mm) / 3; sh = 26 * mm
    who = f"{user.full_name} ({user.user_id})" if user else "—"
    signs = [("PDI", "Planning Bench login", f"{pk.pdi_sign or '—'}\n\nSign: ____________________"),
             ("LOGISTICS", "Shift supervisor · Planning Bench login", f"{pk.supervisor_sign or '—'}\n\nSign: ____________________"),
             ("SECURITY", "loading verified · HHT login", f"{who}\n{datetime.now():%d-%m-%Y %H:%M}\nSign: ____________________")]
    sw = (W - 30 * mm) / len(signs); sh = 30 * mm
    for k, (label, sub, val) in enumerate(signs):
        x = 15 * mm + k * sw
        c.setStrokeColorRGB(0.5, 0.5, 0.5); c.setLineWidth(0.6); c.rect(x, y - sh, sw, sh)
        c.setFont("Helvetica-Bold", 6.5); c.setFillColorRGB(*navy); c.drawString(x + 1.5 * mm, y - 4 * mm, label)
        c.setFont("Helvetica", 6); c.setFillColorRGB(0.4, 0.4, 0.4); c.drawString(x + 1.5 * mm, y - 7.5 * mm, sub)
        c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica", 7.5)
        for i, ln in enumerate(val.split("\n")):
            c.drawString(x + 1.5 * mm, y - 13 * mm - i * 4.2 * mm, ln[:44])
    c.setFont("Helvetica", 7); c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(15 * mm, 15 * mm, f"AIS AssetTrack v{config.APP_VERSION} · Developed by DT · GCS {pk.gcs_no} · pick list {pk.picklist_no} · generated {datetime.now():%d-%m-%Y %H:%M}")
    c.setFillColorRGB(*red); c.drawString(15 * mm, 10.5 * mm, "The OUT gate accepts only a QR printed by AssetTrack for this GCS and vehicle.")
    c.showPage(); c.save()
    return buf.getvalue()


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
