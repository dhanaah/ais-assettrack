"""Returnable pallet DELIVERY CHALLAN (GST Rule 55) as PDF - same look as the gate pass (gcsprint.py).
One PDF holds every copy: ORIGINAL FOR CONSIGNEE / DUPLICATE FOR TRANSPORTER / TRIPLICATE FOR CONSIGNOR (plant master
"Challan copies", default 3). Multi-page: summary by pallet type (HSN, qty, declared value), then every pallet number
(4 columns, full ID), purpose / return clause, signs. Font size follows the plant "GCS font size %" (default 88).
Developed by DT
"""
import io, os
from datetime import datetime
from sqlalchemy.orm import Session
from . import models, config

COPY_TITLES = ["ORIGINAL FOR CONSIGNEE", "DUPLICATE FOR TRANSPORTER", "TRIPLICATE FOR CONSIGNOR"]


def build_challan_pdf(db: Session, pk: models.PickList, user: models.User | None = None, scale: float | None = None,
                      copies: int | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    import segno, math
    from .gcsprint import amount_in_words
    plant = db.get(models.Plant, pk.plant_code)
    cust = db.query(models.Customer).filter_by(code=pk.customer_code, plant_code=pk.plant_code).first()
    to_plant = db.get(models.Plant, pk.to_plant) if pk.to_plant else None
    lines = db.query(models.PickListLine).filter_by(picklist_no=pk.picklist_no).order_by(models.PickListLine.scanned_at).all()
    pals = {p.pallet_no: p for p in db.query(models.Pallet).filter(models.Pallet.pallet_no.in_([l.pallet_no for l in lines])).all()} if lines else {}
    dt = pk.dispatch_type or "PALLET_ONLY"
    holding = (cust.holding_limit_days if cust and cust.holding_limit_days else (plant.holding_days_default if plant else 30))
    if dt in ("EMPTY_RETURN", "STOCK_TRANSFER") and to_plant:
        c_name, c_addr, c_gstin, c_state = to_plant.name, to_plant.address or to_plant.city or "", to_plant.gstin or "", to_plant.state or ""
    else:
        c_name = (cust.name if cust else (pk.customer_name or pk.customer_code))
        c_addr = ", ".join(x for x in ((cust.ship_to if cust else None), (cust.city if cust else None)) if x) or (pk.customer_location or "")
        c_gstin, c_state = (cust.gstin or "") if cust else "", (cust.state or "") if cust else ""
    if dt == "EMPTY_RETURN":
        title = "Delivery Challan - Return of Empty Pallets"
        purpose = (f"Return of empty returnable pallets owned by AIS {pk.to_plant} after unloading of material. "
                   f"Not a sale - no consideration involved.")
    else:
        title = "Delivery Challan - Returnable Pallets"
        purpose = (f"Returnable packing material (pallets) sent with finished glass{' (stock transfer)' if dt == 'STOCK_TRANSFER' else ''}. "
                   f"Not a sale - no consideration involved. To be returned within {holding} days; pallets not returned in time "
                   f"or returned damaged are chargeable as per agreement.")
    def_hsn = (plant.pallet_hsn if plant else None) or ""
    # summary by pallet type - description / HSN / value per pallet from the Pallet Type master
    by_type = {}
    for l in lines:
        t = (pals.get(l.pallet_no).pallet_type if pals.get(l.pallet_no) else None) or (l.pallet_no.split("-")[2] if l.pallet_no.count("-") == 4 else "PALLET")
        by_type[t.upper()] = by_type.get(t.upper(), 0) + 1
    tm = {x.code: x for x in db.query(models.PalletType).filter(models.PalletType.code.in_(list(by_type))).all()} if by_type else {}
    summary = []
    for t, q in sorted(by_type.items()):
        m = tm.get(t)
        v = m.value if m and m.value is not None else None
        spec = []
        if m and (m.length_mm or m.width_mm or m.height_mm):
            spec.append(f"{m.length_mm or '-'}x{m.width_mm or '-'}x{m.height_mm or '-'} mm")
        if m and m.weight_kg:
            spec.append(f"{m.weight_kg:g} kg")
        if m and m.colour:
            spec.append(m.colour)
        summary.append(((f"{(m.description if m and m.description else 'Returnable pallet')} - {t}", "  ·  ".join(spec)), (m.hsn if m and m.hsn else def_hsn), t, q, v, (v * q) if v is not None else None))
    has_val = any(r[4] is not None for r in summary)
    total_val = sum(r[5] or 0 for r in summary)
    missing_val = [r[2] for r in summary if r[4] is None]
    kg = [(tm[t].weight_kg * q) if tm.get(t) and tm[t].weight_kg else None for t, q in sorted(by_type.items())]
    total_kg = sum(x for x in kg if x) if any(kg) else None
    invs = [i.invoice_no for i in db.query(models.PickListItem).filter_by(picklist_no=pk.picklist_no).all() if i.invoice_no]
    invs = list(dict.fromkeys(invs))
    n_copies = max(1, min(3, copies or (plant.challan_copies if plant and plant.challan_copies else 3)))
    F = scale or (max(70, min(110, int(getattr(plant, "gcs_font_pct", None) or 88))) / 100)
    W, H = A4
    ink = (0.16, 0.2, 0.32); grey = (0.82, 0.84, 0.87); red = (0.78, 0.06, 0.18)
    qr_text = f"CHL|{pk.challan_no}|{pk.picklist_no}|{len(lines)}"
    qpng = io.BytesIO(); segno.make(qr_text, error="m").save(qpng, kind="png", scale=6, border=1); qbytes = qpng.getvalue()
    logo = os.path.join(str(config.BASE_DIR), "app", "static", "print-logo.png")      # AIS diamond + "Asahi India Glass Ltd."
    if not os.path.exists(logo):
        logo = os.path.join(str(config.BASE_DIR), "app", "static", "icon-192.png")
    x0, tw = 12 * mm, W - 24 * mm
    BOTTOM = 22 * mm
    RH, PRH = 5.0 * mm * F, 4.4 * mm * F
    cdate = pk.gp_date or pk.updated_at or datetime.now()
    who = f"{user.full_name} ({user.user_id})" if user else "—"
    now = datetime.now()

    def render(total):
        buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4)
        st = {"page": 1, "copy": 0}

        def txt(x, y, t, size=9, bold=False, color=(0, 0, 0), align="l"):
            c.setFillColorRGB(*color); c.setFont("Helvetica-Bold" if bold else "Helvetica", size * F)
            {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[align](x, y, str(t))
            c.setFillColorRGB(0, 0, 0)

        def fit(t, size, bold, width):
            while size > 5.5 and stringWidth(str(t), "Helvetica-Bold" if bold else "Helvetica", size * F) > width:
                size -= 0.5
            return size

        def page_top(first):
            y = H - 11 * mm
            txt(x0 + 2 * mm, y, f"Challan number: {pk.challan_no or 'pending'}", 11)
            txt(x0 + tw / 2 + 10 * mm, y, COPY_TITLES[st["copy"]], 9, True, color=red, align="c")
            txt(x0 + tw - 2 * mm, y, f"{st['page']} of {total or '?'}", 11, align="r")
            hh = 34 * mm if first else 22 * mm
            top = y - 2.5 * mm
            c.setStrokeColorRGB(*ink); c.setLineWidth(1.6); c.rect(x0, top - hh, tw, hh)
            c.setLineWidth(0.6); c.rect(x0 + 1.5 * mm, top - hh + 1.5 * mm, tw - 3 * mm, hh - 3 * mm)
            lw, qw = (46 * mm, 32 * mm) if first else (30 * mm, 22 * mm)
            c.line(x0 + 1.5 * mm + lw, top - 1.5 * mm, x0 + 1.5 * mm + lw, top - hh + 1.5 * mm)
            c.line(x0 + tw - 1.5 * mm - qw, top - 1.5 * mm, x0 + tw - 1.5 * mm - qw, top - hh + 1.5 * mm)
            ls = (hh - 12 * mm) if first else (hh - 6 * mm)
            if os.path.exists(logo):          # logo fills its cell (keeps proportions); it already carries the company name
                bw, bh_ = lw - 6 * mm, hh - 3 * mm - 6 * mm
                iw, ih = ImageReader(logo).getSize()
                f = min(bw / iw, bh_ / ih); dw, dh = iw * f, ih * f
                c.drawImage(logo, x0 + 1.5 * mm + (lw - dw) / 2, top - 1.5 * mm - (hh - 3 * mm + dh) / 2, dw, dh, mask="auto")
            mid = x0 + 1.5 * mm + lw + (tw - 3 * mm - lw - qw) / 2
            if first:
                txt(mid, top - 9 * mm, "Asahi India Glass Ltd", 17, align="c")
                txt(mid, top - 15.5 * mm, title, 12.5, True, align="c")
                addr = ((plant.address or plant.name) if plant else pk.plant_code)
                maxw = tw - 3 * mm - lw - qw - 4 * mm; al, cur = [], ""
                for wd in addr.split():
                    t = (cur + " " + wd).strip()
                    if stringWidth(t, "Helvetica", 8.5 * F) <= maxw:
                        cur = t
                    else:
                        al.append(cur); cur = wd
                al.append(cur)
                for li, ln in enumerate(al[:2]):
                    txt(mid, top - 20.5 * mm - li * 3.8 * mm, ln, 8.5, align="c")
                g = f"GSTIN {(plant.gstin or '—') if plant else '—'}   ·   Rule 55 CGST Rules - Returnable, Not for Sale"
                txt(mid, top - 29.5 * mm, g, fit(g, 8.5, True, maxw), True, align="c")
            else:
                txt(mid, top - 9 * mm, f"{title}  (continued)", 11, True, align="c")
                txt(mid, top - 15 * mm, f"Vehicle {pk.vehicle_no or '—'}   ·   To M/s {c_name}"[:80], 8.5, align="c")
            qs = qw - 5 * mm
            c.drawImage(ImageReader(io.BytesIO(qbytes)), x0 + tw - 1.5 * mm - qw + 2.5 * mm, top - 2.5 * mm - qs, qs, qs)
            if first:
                txt(x0 + tw - 1.5 * mm - qw / 2, top - hh + 3 * mm, "Challan QR", 6.5, align="c")
            return top - hh - 3 * mm

        def details(y):
            left = [("Challan No:", pk.challan_no or "pending"), ("Challan Date:", f"{cdate:%d/%m/%Y %H:%M}"),
                    ("To M/s:", c_name), ("Address:", c_addr), ("GSTIN:", c_gstin), ("Place of Supply:", c_state or (pk.customer_location or ""))]
            right = [("Gate Pass No:", pk.gcs_no or ""), ("Vehicle No:", pk.vehicle_no or ""), ("Vehicle Type:", pk.vehicle_type or ""),
                     ("Transporter:", pk.transporter_name or pk.transporter_code or ""), ("Invoice(s):", (", ".join(invs) if invs else (pk.invoice_no or ""))),
                     ("E-way Bill:", pk.ewaybill_no or "")]
            rows = max(len(left), len(right))
            h = rows * 5.6 * mm * F + 5 * mm
            c.setStrokeColorRGB(*ink); c.setLineWidth(1.6); c.rect(x0, y - h, tw, h)
            c.setLineWidth(0.6); c.rect(x0 + 1.5 * mm, y - h + 1.5 * mm, tw - 3 * mm, h - 3 * mm)
            yy = y - 6.5 * mm
            for k in range(rows):
                lab, val = left[k]
                txt(x0 + 5 * mm, yy, lab, 9.5, color=(0.25, 0.25, 0.25))
                v = str(val).upper() if lab == "To M/s:" else str(val)
                txt(x0 + 35 * mm, yy, v, fit(v, 10, True, 76 * mm), True, color=red if lab == "Challan No:" else (0, 0, 0))
                lab, val = right[k]
                txt(x0 + 118 * mm, yy, lab, 9.5, color=(0.25, 0.25, 0.25))
                txt(x0 + 145 * mm, yy, val, fit(val, 10, True, 38 * mm), True)
                yy -= 5.6 * mm * F
            return y - h - 4 * mm

        cw = [10, 66, 22, 24, 18, 22, 24]          # Sl, Description, HSN, Pallet Type, Qty, Value/Pallet, Total Value = 186
        heads = [("Sl", ""), ("Description of Goods", ""), ("HSN", "Code"), ("Pallet", "Type"), ("Qty", "(Nos)"), ("Value /", "Pallet (Rs)"), ("Total", "Value (Rs)")]
        right = {0, 4, 5, 6}

        def table_head(y):
            hh = 9 * mm * F; x = x0
            c.setFillColorRGB(*grey); c.rect(x0, y - hh, tw, hh, fill=1, stroke=0)
            c.setStrokeColorRGB(*ink); c.setLineWidth(0.8); c.rect(x0, y - hh, tw, hh)
            for k, (a, b) in enumerate(heads):
                w = cw[k] * mm
                if k:
                    c.line(x, y, x, y - hh)
                xx, al = (x + w - 1.5 * mm, "r") if k in right else (x + 1.5 * mm, "l")
                txt(xx, y - 4 * mm * F, a, 8, True, align=al)
                if b:
                    txt(xx, y - 7.7 * mm * F, b, 8, True, align=al)
                x += w
            return y - hh

        def table_row(y, vals, bold=False):
            """A cell value may be (main text, second line) - e.g. description + L x W x H / weight / colour."""
            two = any(isinstance(v, tuple) and v[1] for v in vals)
            rh = RH * (1.75 if two else 1)
            x = x0
            c.setStrokeColorRGB(*ink); c.setLineWidth(0.5)
            for k, v in enumerate(vals):
                w = cw[k] * mm
                c.line(x, y, x, y - rh)
                sub = ""
                if isinstance(v, tuple):
                    v, sub = v
                base = y - RH + 1.5 * mm * F if two else y - rh + 1.5 * mm * F
                if v != "":
                    size = fit(v, 8.5, bold, w - 2.5 * mm)
                    if k in right or (bold and k == 3):
                        txt(x + w - 1.5 * mm, base, v, size, bold, align="r")
                    else:
                        txt(x + 1.5 * mm, base, v, size, bold)
                if sub:
                    txt(x + 1.5 * mm, base - 3.6 * mm * F, sub, fit(sub, 7, False, w - 2.5 * mm), color=(0.35, 0.35, 0.35))
                x += w
            c.line(x0 + tw, y, x0 + tw, y - rh); c.line(x0, y - rh, x0 + tw, y - rh)
            return y - rh

        def footer():
            txt(x0, 13.5 * mm, f"AIS AssetTrack v{config.APP_VERSION} · Developed by DT · pick list {pk.picklist_no} · printed {now:%d-%m-%Y %H:%M}", 6.8, color=(0.4, 0.4, 0.4))
            txt(x0 + tw, 13.5 * mm, f"Page {st['page']} of {total or '?'}", 8, True, align="r")
            txt(x0, 9.5 * mm, "Returnable packing material - property of Asahi India Glass Ltd. Not for sale.", 6.8, color=red)

        def new_page():
            footer(); c.showPage(); st["page"] += 1
            return page_top(False)

        money = lambda v: "" if v is None else f"{v:,.2f}"
        for cp in range(n_copies):
            st["copy"] = cp
            if cp:
                c.showPage(); st["page"] = 1          # every copy is numbered 1 .. N
            y = page_top(True)
            y = details(y)
            y = table_head(y)
            for k, (desc, hsn, t, q, v, tv) in enumerate(summary):
                if y - RH * 1.75 < BOTTOM:
                    y = table_head(new_page())
                y = table_row(y, [str(k + 1), desc, hsn, t, str(q), money(v), money(tv)])
            y = table_row(y, ["", "", "", "Total:", str(len(lines)), "", money(total_val) if has_val else ""], bold=True)
            if missing_val:
                y -= 4.5 * mm
                txt(x0 + 2 * mm, y, f"Value not set in the Pallet Type master for: {', '.join(missing_val)}", 7.5, color=red)
            if has_val:
                y -= 6 * mm
                txt(x0 + 2 * mm, y, "Value (In Words):", 9.5, color=(0.25, 0.25, 0.25))
                txt(x0 + 35 * mm, y, "Rupees " + amount_in_words(total_val), 9.5, True)
            if total_kg:
                y -= 5 * mm
                txt(x0 + 2 * mm, y, "Total Pallet Weight:", 9.5, color=(0.25, 0.25, 0.25))
                txt(x0 + 35 * mm, y, f"{total_kg:,.1f} kg" + ("   (weight missing in the master for some types)" if not all(kg) else ""), 9.5, True)
            y -= 6 * mm
            # purpose (wrapped)
            words, cur, plines = purpose.split(), "", []
            for wd in words:
                t = (cur + " " + wd).strip()
                if stringWidth(t, "Helvetica", 8.5 * F) <= tw - 22 * mm:
                    cur = t
                else:
                    plines.append(cur); cur = wd
            plines.append(cur)
            txt(x0 + 2 * mm, y, "Purpose:", 8.5, True)
            for li, ln in enumerate(plines):
                txt(x0 + 18 * mm, y - li * 4 * mm * F, ln, 8.5)
            y -= len(plines) * 4 * mm * F + 4 * mm
            # every pallet number (4 columns, full ID)
            ncol, colw = 4, tw / 4

            def pal_head(y, cont=False):
                c.setFillColorRGB(*grey); c.rect(x0, y - 6 * mm * F, tw, 6 * mm * F, fill=1, stroke=0)
                c.setStrokeColorRGB(*ink); c.setLineWidth(0.8); c.rect(x0, y - 6 * mm * F, tw, 6 * mm * F)
                txt(x0 + 2 * mm, y - 4.2 * mm * F, f"PALLET NUMBERS ({len(lines)})" + ("  (continued)" if cont else ""), 8.5, True)
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
                    txt(x + 8 * mm, yy, i + j + 1, 7.5, color=(0.45, 0.45, 0.45), align="r")
                    txt(x + 10 * mm, yy, l.pallet_no, 7.8, True)
                    c.setStrokeColorRGB(0.88, 0.88, 0.88); c.setLineWidth(0.25); c.line(x, y - (ri + 1) * PRH, x + colw, y - (ri + 1) * PRH)
                c.setStrokeColorRGB(*ink); c.setLineWidth(0.5); c.rect(x0, y - rows * PRH, tw, rows * PRH)
                for ci in range(1, ncol):
                    c.line(x0 + ci * colw, y, x0 + ci * colw, y - rows * PRH)
                i += len(chunk); y -= rows * PRH
                if i < n:
                    y = pal_head(new_page(), True)
            y -= 6 * mm
            sh = 28 * mm * max(F, 0.85)
            if y - sh < BOTTOM:
                y = new_page()
            signs = [("PREPARED BY", "Logistics · AssetTrack login", who, f"{cdate:%d/%m/%Y %H:%M}"),
                     ("SECURITY", "Checked at OUT gate", "", ""),
                     ("RECEIVED BY", "Consignee / driver - name & seal", "", "")]
            sw = tw / 3
            for k, (label, sub, name, when) in enumerate(signs):
                x = x0 + k * sw
                c.setStrokeColorRGB(*ink); c.setLineWidth(0.8); c.rect(x, y - sh, sw, sh)
                txt(x + 2 * mm, y - 4.5 * mm, label, 8.5, True)
                txt(x + 2 * mm, y - 8 * mm, sub, 6.5, color=(0.4, 0.4, 0.4))
                if name:
                    txt(x + 2 * mm, y - 13.5 * mm, name[:40], 8.5)
                if when:
                    txt(x + 2 * mm, y - 17.5 * mm, when, 8)
                txt(x + 2 * mm, y - sh + 3.5 * mm, "Sign: ______________________", 8)
            footer()
        c.showPage(); c.save()
        return buf.getvalue(), st["page"]             # pages of one copy

    _, pages = render(None)
    data, _ = render(pages)
    return data
