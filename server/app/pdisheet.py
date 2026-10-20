"""PDI check sheet PDF in the Dispatch Planning Bench layout ("AIS Glass - Picklist / PDI Check Sheet"), built live
from AssetTrack each time it is opened: every part card of the Bench trip - planned (not picked yet), picked, PDI result,
inspector, check points / reason - plus what only AssetTrack knows: the pallet number, the GCS invoice and whether the
pallet is already scanned / loaded on the vehicle. Rows grouped by invoice like the Bench sheet. Developed by DT
"""
import io
import re
from datetime import datetime
from sqlalchemy.orm import Session
from . import models, config, services

PDI_TEXT = {"OK": "Accepted", "PENDING": "Pending", "HOLD": "Hold", "REJECT": "Rejected", "PLANNED": ""}
PDI_COLOR = {"Accepted": (0.08, 0.50, 0.24), "Rejected": (0.73, 0.11, 0.11), "Removed": (0.73, 0.11, 0.11), "Hold": (0.71, 0.33, 0.04),
             "Pending": (0.11, 0.31, 0.85), "no Bench trip": (0.73, 0.11, 0.11)}


def sheet_rows(db: Session, k: models.PickList):
    """(head, rows) for the sheet of a loading record (Bench trip or GCS)."""
    from . import gcs as gp
    t = gp.trip_of(db, k)
    recs = [x for x in {k.picklist_no, k.linked_picklist, t.picklist_no if t else None} if x]
    g = next((y for y in (db.get(models.PickList, x) for x in recs) if y is not None and (y.source or "") == "GCS"), None)
    gcs_rows = []
    for x in recs:
        gcs_rows = gcs_rows or db.query(models.GcsLpn).filter_by(picklist_no=x).all()
    gl = {r.lpn_no: r for r in gcs_rows}
    lines = [ln for x in recs for ln in db.query(models.PickListLine).filter_by(picklist_no=x).all()]
    loaded = {ln.pallet_no: ln for ln in lines}
    bound = {b.lpn_no: b.pallet_no for x in recs for b in db.query(models.PickListLpn).filter_by(picklist_no=x).all() if b.pallet_no}
    cards = {c.lpn_no: c for c in db.query(models.BenchTripCard).filter_by(trip_no=t.picklist_no).all()} if t else {}
    cache, rows = {}, []
    for lpn in list(dict.fromkeys(list(cards) + list(gl))):
        c, r = cards.get(lpn), gl.get(lpn)
        ref = (r.pallet_ref if r else None) or (c.pallet_ref if c else None)
        pno = (r.pallet_no if r else None) or bound.get(lpn) or services.pallet_from_ref(db, ref, k.plant_code, cache)
        st = (c.pdi_status or "OK") if c else None
        if c is None:
            pdi = "no Bench trip" if t is None else "not on sheet"
        elif c.removed_at is not None:
            pdi = "Rejected" if st == "REJECT" else "Removed"
        else:
            pdi = PDI_TEXT.get(st, st)
        ln = loaded.get(pno) if pno else None
        rows.append({"item": (c.part_no if c else None) or (r.part_no if r else "") or "", "seg": (c.segment if c else None) or "",
                     "lpn": lpn, "ref": ref or "", "pallet": pno or "", "picked": "" if (c and st == "PLANNED") else ("Yes" if c else ""),
                     "pdi": pdi, "insp": (c.inspector if c else None) or "",
                     "checks": " | ".join(x for x in ((c.checks if c else None), (c.pdi_reason if c else None)) if x),
                     "invoice": (r.invoice_no if r else None) or "", "qty": (c.qty if c else None) or (r.qty if r else None) or "",
                     "loaded": (ln.loaded_at.strftime("%H:%M") if ln and ln.loaded_at else ("scanned" if ln else ""))})
    rows.sort(key=lambda x: (x["invoice"] == "", x["invoice"], x["item"], x["lpn"]))
    trip = t or k
    head = {"bench_no": trip.ext_ref if t else None, "trip": ("Trip " + _m.group(1)) if (t and (_m := re.search(r"Bench trip (\S+)", trip.remarks or ""))) else "", "vehicle": k.vehicle_no or trip.vehicle_no,
            "customer": k.customer_code or trip.customer_code, "gcs": (g.gcs_no if g else None) or k.gcs_no, "status": k.status,
            "so": (trip.so_number if t else None) or k.so_number, "plant": k.plant_code, "picklist": k.picklist_no,
            "segment": next((x["seg"] for x in rows if x["seg"]), "")}
    return head, rows


def build_pdf(db: Session, k: models.PickList) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth
    head, rows = sheet_rows(db, k)
    W, H = landscape(A4)
    M = 10 * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(f"PDI check sheet {head['bench_no'] or head['gcs'] or head['picklist']}")
    cols = [("Item", 44), ("Seg", 11), ("LPN (part card)", 30), ("Pallet ref", 20), ("Pallet No (AssetTrack)", 36), ("Picked", 12),
            ("PDI", 19), ("Inspector", 22), ("Check points / reason", 45), ("Invoice", 20), ("Loaded", 18)]
    dark, mute = (0.06, 0.09, 0.16), (0.39, 0.45, 0.55)

    def fit(s, w, size, font="Helvetica"):
        s = str(s or "")
        while s and stringWidth(s, font, size) > w - 2 * mm:
            s = s[:-1]
        return s

    st = {"y": 0, "page": 0}

    def new_page():
        if st["page"]:
            c.showPage()
        st["page"] += 1
        c.setFillColorRGB(*dark); c.setFont("Helvetica-Bold", 16)
        c.drawString(M, H - M - 6 * mm, "AIS Glass — Picklist / PDI Check Sheet")
        if head["so"]:
            c.setLineWidth(1.2); c.rect(W - M - 62 * mm, H - M - 9 * mm, 62 * mm, 10 * mm)
            c.drawString(W - M - 59 * mm, H - M - 6 * mm, f"SO No: {head['so']}")
        c.setFont("Helvetica", 8.5); c.setFillColorRGB(0.2, 0.25, 0.33)
        info = (f"Picklist #{head['bench_no'] or '-'}   {head['trip'] or ''}   Vehicle {head['vehicle'] or '-'}   Customer {head['customer'] or '-'}"
                f"   Segment {head['segment'] or '-'}   Plant {head['plant']}")
        c.drawString(M, H - M - 12 * mm, info)
        c.setFillColorRGB(*mute)
        c.drawString(M, H - M - 16.5 * mm, f"GCS {head['gcs'] or '- (not received yet)'}   AssetTrack {head['picklist']} · {head['status']}"
                                           f"   Live from AssetTrack {datetime.now():%d-%b-%Y %H:%M}")
        y = H - M - 21 * mm
        c.setFillColorRGB(0.12, 0.16, 0.23); c.rect(M, y - 6 * mm, W - 2 * M, 6 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1); c.setFont("Helvetica-Bold", 7.5)
        x = M
        for n, w in cols:
            c.drawString(x + 1.2 * mm, y - 4.2 * mm, fit(n, w * mm, 7.5, "Helvetica-Bold")); x += w * mm
        st["y"] = y - 6.5 * mm

    new_page()
    inv, i = None, 0
    for r in rows:
        key = r["invoice"] or "NOT INVOICED"
        if key != inv:
            inv = key
            if st["y"] - 13 * mm < M + 12 * mm:
                new_page()
            y = st["y"] - 1.5 * mm
            c.setFillColorRGB(1.0, 0.95, 0.78); c.setStrokeColorRGB(0.71, 0.33, 0.04)
            c.rect(M, y - 6.5 * mm, W - 2 * M, 6.5 * mm, fill=1, stroke=1)
            c.setFillColorRGB(0.47, 0.21, 0.06); c.setFont("Helvetica-Bold", 8.5)
            n = sum(1 for x in rows if (x["invoice"] or "NOT INVOICED") == key)
            c.drawString(M + 2 * mm, y - 4.6 * mm, (f"INVOICE {key}" if r["invoice"] else "NOT INVOICED - not on the GCS (yet)") + f"   ·   {n} card(s)")
            st["y"] = y - 7.5 * mm
        h = 5.6 * mm
        if st["y"] - h < M + 12 * mm:
            new_page()
        y = st["y"]
        if i % 2:
            c.setFillColorRGB(0.945, 0.96, 0.976); c.rect(M, y - h, W - 2 * M, h, fill=1, stroke=0)
        x = M
        vals = [r["item"], r["seg"], r["lpn"], r["ref"], r["pallet"], r["picked"], r["pdi"] or ("not picked" if not r["picked"] else ""),
                r["insp"], r["checks"], r["invoice"], r["loaded"]]
        for (n, w), v in zip(cols, vals):
            bold = n in ("LPN (part card)", "PDI", "Pallet No (AssetTrack)")
            col = PDI_COLOR.get(v, dark) if n == "PDI" else ((0.08, 0.50, 0.24) if n == "Loaded" and v and v != "scanned" else dark)
            c.setFillColorRGB(*col); c.setFont("Helvetica-Bold" if bold else "Helvetica", 7.2)
            c.drawString(x + 1.2 * mm, y - 3.9 * mm, fit(v, w * mm, 7.2, "Helvetica-Bold" if bold else "Helvetica")); x += w * mm
        st["y"] = y - h
        i += 1
    if not rows:
        c.setFillColorRGB(*mute); c.setFont("Helvetica", 9); c.drawString(M, st["y"] - 6 * mm, "No part cards yet (Bench trip not picked, GCS without part cards).")
        st["y"] -= 8 * mm
    tot = len(rows); ok = sum(1 for r in rows if r["pdi"] == "Accepted")
    rj = sum(1 for r in rows if r["pdi"] in ("Rejected", "Hold", "Removed"))
    ld = sum(1 for r in rows if r["loaded"] and r["loaded"] != "scanned")
    c.setFillColorRGB(*dark); c.setFont("Helvetica-Bold", 9)
    c.drawString(M, max(st["y"] - 6 * mm, M + 6 * mm),
                 f"Pallets {tot}   PDI OK {ok}   Rejected / Hold {rj}   Waiting {tot - ok - rj}   Loaded on vehicle {ld} / {tot}")
    c.showPage(); c.save()
    return _footer(buf.getvalue())


def _footer(data: bytes) -> bytes:
    """'Page n / m · AIS AssetTrack vX · Developed by DT' on every page (as the Bench sheet)."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    rd, wr = PdfReader(io.BytesIO(data)), PdfWriter()
    n = len(rd.pages)
    for i, pg in enumerate(rd.pages):
        w, h = float(pg.mediabox.width), float(pg.mediabox.height)
        ov = io.BytesIO(); c = canvas.Canvas(ov, pagesize=(w, h))
        c.setFillColorRGB(0.58, 0.64, 0.72); c.setFont("Helvetica", 7)
        c.drawString(10 * mm, 5 * mm, f"Page {i + 1} / {n} · AIS AssetTrack v{config.APP_VERSION} · same layout as the Dispatch Planning Bench sheet · Developed by DT")
        c.save()
        pg.merge_page(PdfReader(io.BytesIO(ov.getvalue())).pages[0]); wr.add_page(pg)
    out = io.BytesIO(); wr.write(out)
    return out.getvalue()
