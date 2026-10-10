"""Print-ready documents (A4): pallet challan and return slip, with AIS logo and QR.
Open in browser -> Print / Save as PDF. Token passed as ?tok= so the page can be opened in a new tab."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import jwt
from .. import models, config, services
from ..db import get_db
from ..security import Principal, load_perms

router = APIRouter(prefix="/print", tags=["print"])


def _auth(tok: str, db: Session) -> Principal:
    try:
        data = jwt.decode(tok, config.JWT_SECRET, algorithms=[config.JWT_ALGO])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    u = db.get(models.User, data.get("uid"))
    if not u or not u.active:
        raise HTTPException(401, "User inactive")
    return Principal(u, load_perms(db, u))


CSS = """
@page{size:A4;margin:12mm} body{font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#111;margin:0}
.top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #1e3a8a;padding-bottom:8px;margin-bottom:8px}
.top img.logo{height:64px}.top img.wm{height:30px}.co{font-size:11.5px;line-height:1.4}
.title{text-align:center;font-weight:800;font-size:15px;letter-spacing:1px;margin:8px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}.box{border:1px solid #333;padding:6px 8px;min-height:38px}.box b{display:block;font-size:10.5px;color:#1e3a8a;letter-spacing:.5px}
table{width:100%;border-collapse:collapse;font-size:11.5px}th,td{border:1px solid #333;padding:4px 6px;text-align:left}th{background:#eef2ff}
.sig{display:flex;justify-content:space-between;margin-top:30px;font-size:11px}.sig div{border-top:1px solid #333;padding-top:4px;width:30%;text-align:center}
.foot{font-size:10px;color:#666;margin-top:12px}.qr{width:96px;height:96px}
.btn{position:fixed;bottom:16px;right:16px;background:#1e3a8a;color:#fff;border:none;padding:8px 14px;border-radius:6px;font-size:13px;cursor:pointer}@media print{.btn{display:none}}
"""


def _qr(data: str) -> str:
    """Inline SVG QR via a tiny pure-python encoder (segno if available, else text fallback)."""
    try:
        import segno
        return segno.make(data, error="m").svg_inline(scale=3, border=1)
    except Exception:
        return f'<div style="border:1px solid #333;padding:6px;font-size:10px;word-break:break-all;width:120px">{data}</div>'


def _head(plant: models.Plant, doc_title: str, qr_data: str) -> str:
    return f"""<div class="top"><div style="display:flex;gap:12px;align-items:flex-start"><img class="logo" src="/static/print-logo.png" alt="Asahi India Glass Ltd." style="height:62px;width:auto">
      <div class="co"><b style="font-size:13px">{plant.name}</b><br>{plant.address or ''}<br>GSTIN {plant.gstin or ''}</div></div>
      <div style="text-align:right"><img class="wm" src="/static/wordmark.png" alt="AssetTrack"><div style="margin-top:6px">{_qr(qr_data)}</div></div></div>
      <div class="title">{doc_title}</div>"""


@router.get("/challan/{no}", response_class=HTMLResponse)
def challan(no: str, tok: str = Query(...), db: Session = Depends(get_db)):
    p = _auth(tok, db)
    k = db.get(models.PickList, no)
    if not k or not k.challan_no:
        raise HTTPException(404, "Challan not found")
    p.require_plant(k.plant_code)
    plant = db.get(models.Plant, k.plant_code)
    cust = db.query(models.Customer).filter_by(code=k.customer_code, plant_code=k.plant_code).first()
    tr = db.get(models.Transporter, k.transporter_code) if k.transporter_code else None
    lines = db.query(models.PickListLine).filter_by(picklist_no=no).order_by(models.PickListLine.scanned_at).all()
    rows = ""
    for i, l in enumerate(lines, 1):
        pal = db.get(models.Pallet, l.pallet_no)
        rows += f"<tr><td>{i}</td><td>{l.pallet_no}</td><td>{pal.current_tag if pal else ''}</td><td>{(pal.pallet_type if pal else '') or ''} {(pal.size if pal else '') or ''}</td><td>1</td></tr>"
    hold = (cust.holding_limit_days if cust and cust.holding_limit_days else plant.holding_days_default)
    dt = k.dispatch_type or "PALLET_ONLY"
    lpn_rows = db.query(models.PickListLpn).filter(models.PickListLpn.picklist_no == no,
                                                   (models.PickListLpn.pdi_result == "OK") | models.PickListLpn.pdi_result.is_(None)).all()
    lpn_by = {}
    for r in lpn_rows:
        lpn_by.setdefault(r.pallet_no, []).append(r)
    if lpn_rows:
        rows = ""
        for i, l in enumerate(lines, 1):
            pal = db.get(models.Pallet, l.pallet_no)
            ls = lpn_by.get(l.pallet_no, [])
            rows += (f"<tr><td>{i}</td><td>{l.pallet_no}</td><td>{pal.current_tag if pal else ''}</td>"
                     f"<td>{'<br>'.join(f'{x.lpn_no} · {x.part_no} × {x.qty}' for x in ls)}</td><td>{sum(x.qty for x in ls)}</td></tr>")
    to_plant = db.get(models.Plant, k.to_plant) if k.to_plant else None
    if dt == "EMPTY_RETURN":
        title, consignee = "DELIVERY CHALLAN — RETURN OF EMPTY RETURNABLE PALLETS", f"{to_plant.name if to_plant else k.to_plant} ({k.to_plant})<br>{(to_plant.address or '') if to_plant else ''}<br>GSTIN {(to_plant.gstin or '') if to_plant else ''}"
        purpose = f"Return of empty returnable pallets (owned by AIS {k.to_plant}) after consumption of material. Not a sale."
    else:
        title = "DELIVERY CHALLAN — RETURNABLE PALLETS (Rule 55, CGST Rules)" + (" · STOCK TRANSFER" if dt == "STOCK_TRANSFER" else "")
        consignee = (f"{to_plant.name} ({k.to_plant})<br>GSTIN {to_plant.gstin or ''}" if dt == "STOCK_TRANSFER" and to_plant else
                     f"{cust.name if cust else k.customer_code} ({k.customer_code})<br>{(cust.ship_to or '') if cust else ''} {(cust.city or '') if cust else ''}<br>GSTIN {(cust.gstin or '') if cust else ''}")
        purpose = (f"Supply of returnable packing material (pallets) for transport of finished glass. Not a sale. "
                   f"Pallets to be returned within <b>{hold} days</b>; overdue or damaged pallets are chargeable as per agreement.")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Challan {k.challan_no}</title><style>{CSS}</style></head><body>
    <button class="btn" onclick="window.print()">Print / Save PDF</button>
    {_head(plant, title, f'CHL|{k.challan_no}|{k.picklist_no}|{len(lines)}')}
    <div class="grid">
      <div class="box"><b>CHALLAN NO / DATE</b>{k.challan_no} · {k.updated_at:%d-%m-%Y %H:%M}</div>
      <div class="box"><b>PICK LIST / SO</b>{k.picklist_no} · {('SO ' + (k.so_number or 'pending')) if dt != 'EMPTY_RETURN' else 'Empty return'}{f' · PO {k.po_number}' if k.po_number else ''}</div>
      <div class="box"><b>CONSIGNEE</b>{consignee}</div>
      <div class="box"><b>TRANSPORT</b>Vehicle {k.vehicle_no or '—'} · {tr.name if tr else (k.transporter_code or '')}<br>GCS {k.gcs_no or '—'}</div>
      <div class="box"><b>INVOICE</b>{(k.invoice_no + ' · ' + (k.invoice_date.strftime('%d-%m-%Y') if k.invoice_date else '')) if k.invoice_no else '—'}</div>
      <div class="box"><b>E-WAY BILL</b>{k.ewaybill_no or ('with invoice' if k.invoice_no else '—')}</div>
    </div>
    <table><tr><th>#</th><th>Pallet No</th><th>Tag</th><th>{'LPN · part × qty' if lpn_rows else 'Type / size'}</th><th>Qty</th></tr>{rows}
    <tr><th colspan="4" style="text-align:right">TOTAL PALLETS {len(lines)}{f' · PART {k.part_no} QTY' if lpn_rows else ''}</th><th>{sum(x.qty for x in lpn_rows) if lpn_rows else len(lines)}</th></tr></table>
    <div style="margin-top:8px;font-size:11px"><b>Purpose:</b> {purpose}</div>
    <div class="sig"><div>Prepared by (FG Warehouse)</div><div>Approved by (Logistics)</div><div>Received by (Customer / Driver)</div></div>
    <div class="foot">AIS AssetTrack · Developed by DT · printed {datetime.now():%d-%m-%Y %H:%M} by {p.user_id}</div></body></html>"""
    return HTMLResponse(html)


def slip_html(db, s, printed_by: str) -> str:
    """Pallet Return Slip - the A4 pattern shown in the approval deck. Used by AIS (web/HHT) and by the customer API."""
    plant = db.get(models.Plant, s.plant_code)
    cust = db.query(models.Customer).filter_by(code=s.customer_code, plant_code=s.plant_code).first()
    lines = db.query(models.ReturnSlipLine).filter_by(slip_no=s.slip_no).all()
    rows = "".join(f"<tr><td>{i}</td><td>{l.pallet_no}</td><td>{'✓' if l.declared else ''}</td><td>{'✓' if l.received else ''}</td><td>{l.exception or ''}</td></tr>" for i, l in enumerate(lines, 1))
    qr = services.slip_qr(s, signed=s.source != "HHT")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Return slip {s.slip_no}</title><style>{CSS}</style></head><body>
    <button class="btn" onclick="window.print()">Print / Save PDF</button>
    {_head(plant, 'PALLET RETURN SLIP', qr)}
    <div class="grid">
      <div class="box"><b>SLIP NO / DATE</b>{s.slip_no} · {s.created_at:%d-%m-%Y %H:%M} · mode {s.mode} · {s.status}</div>
      <div class="box"><b>CUSTOMER</b>{cust.name if cust else s.customer_code} ({s.customer_code})</div>
      <div class="box"><b>VEHICLE / DRIVER</b>{s.vehicle_no or '—'} · {s.driver_name or ''} {s.driver_mobile or ''}</div>
      <div class="box"><b>CUSTOMER CHALLAN / GCS-IN</b>{s.customer_challan_no or '—'} {f'· {s.customer_challan_date:%d-%m-%Y}' if s.customer_challan_date else ''} · GCS {s.gcs_in_no or '—'}</div>
    </div>
    <table><tr><th>#</th><th>Pallet No</th><th>Declared</th><th>Received</th><th>Exception</th></tr>{rows or '<tr><td colspan=5>Quantity-only slip (B2) — pallets identified at yard scan</td></tr>'}
    <tr><th colspan="4" style="text-align:right">DECLARED QTY</th><th>{s.declared_qty}</th></tr></table>
    <div class="sig"><div>Security (IN gate)</div><div>Driver</div><div>Pallet yard in-charge</div></div>
    <div class="foot">AIS AssetTrack · Developed by DT · printed {datetime.now():%d-%m-%Y %H:%M} by {printed_by}</div></body></html>"""


@router.get("/gcs/{no}", response_class=HTMLResponse)
def gcs_print(no: str, tok: str = Query(...), db: Session = Depends(get_db)):
    """GCS (gate pass) print with the signed QR the OUT gate scans. no = pick list or GCS number."""
    from .. import gcs as gcssvc
    p = _auth(tok, db)
    k = db.get(models.PickList, no) or db.query(models.PickList).filter(models.PickList.gcs_no == no).order_by(models.PickList.created_at.desc()).first()
    if not k or not k.gcs_no:
        raise HTTPException(404, "GCS not found")
    p.require_plant(k.plant_code)
    plant = db.get(models.Plant, k.plant_code)
    cust = db.query(models.Customer).filter_by(code=k.customer_code, plant_code=k.plant_code).first()
    lines = db.query(models.PickListLine).filter_by(picklist_no=k.picklist_no).order_by(models.PickListLine.scanned_at).all()
    lpn_by = {}
    for r in db.query(models.PickListLpn).filter_by(picklist_no=k.picklist_no).all():
        lpn_by.setdefault(r.pallet_no, []).append(r)
    rows = "".join(f"<tr><td>{i}</td><td><b>{gcssvc.short_pallet(l.pallet_no)}</b></td><td>{'<br>'.join(f'{x.lpn_no} · {x.part_no} × {x.qty}' for x in lpn_by.get(l.pallet_no, [])) or '—'}</td><td>{l.scanned_at:%d-%m %H:%M}</td><td>{l.user_id or ''}</td></tr>" for i, l in enumerate(lines, 1))
    qr = gcssvc.gcs_qr(k, len(lines))
    RED = ' style="color:#c8102e;font-weight:700"'
    items = gcssvc.items_loaded(db, k.picklist_no); has_cards = any(lpn_by.values())
    invs = list(dict.fromkeys(i["invoice_no"] for i in items if i["invoice_no"]))
    fn = lambda v, d=0: "" if v in (None, "") else (f"{v:,.{d}f}" if d else f"{v:,}")
    tot = lambda key: sum((i.get(key) or 0) for i in items)
    item_tbl = ("<table><tr><th>Sl</th><th>Inv No.</th><th>Inv Date</th><th>Item Code</th><th>Cust Part No</th><th>No of Case</th><th>Qty/Case</th><th>Act Qty</th><th>Line Amount</th><th>Pallet Type</th></tr>"
                + "".join(f"<tr><td>{n}</td><td>{i['invoice_no'] or ''}</td><td>{i['invoice_date'].strftime('%d/%m/%Y') if i['invoice_date'] else ''}</td>"
                          f"<td><b>{i['part_no'] or ''}</b></td><td>{i['cust_part'] or ''}</td><td>{fn(i['cases'])}</td><td>{fn(i['qty_per_case'])}</td>"
                          f"<td>{fn(i['qty'])}</td><td>{fn(i.get('amount'), 2)}</td><td>{i.get('pallet_type') or ''}</td></tr>" for n, i in enumerate(items, 1))
                + f"<tr><th colspan='5' style='text-align:right'>Total:</th><th>{fn(tot('cases'))}</th><th>{fn(tot('qty_per_case'))}</th><th>{tot('qty'):,.2f}</th><th>{fn(tot('amount'), 2) if tot('amount') else ''}</th><th></th></tr></table>") if items else ""
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>GCS {k.gcs_no}</title><style>{CSS} .big{{font-size:22px;font-weight:800;letter-spacing:1px}}</style></head><body>
    <button class="btn" onclick="window.print()">Print / Save PDF</button>
    {_head(plant, "GATE CUM SECURITY PASS (OUTWARD) · VEHICLE LOADING RECORD", qr)}
    <div class="grid">
      <div class="box"><b>GCS NO</b><span class="big">{k.gcs_no}</span></div>
      <div class="box"><b>VEHICLE</b><span class="big">{k.vehicle_no or '—'}</span><br>{k.vehicle_type or ''}{' · ' if k.vehicle_type else ''}{k.transporter_name or k.transporter_code or ''}</div>
      <div class="box"><b>CONSIGNEE · CUSTOMER LOCATION</b>{cust.name if cust else k.customer_code} ({k.customer_code})<br>{('to plant ' + k.to_plant) if k.to_plant else (k.customer_location or ', '.join(x for x in ((cust.ship_to or '') if cust else '', (cust.city or '') if cust else '') if x) or '—')}</div>
      <div class="box"><b>INVOICES / E-WAY BILL</b>{(str(len(invs)) + ' invoice(s) · ' + str(len(items)) + ' line(s)') if items else (k.invoice_no or '—')}<br>e-way bill {k.ewaybill_no or '—'}</div>
      <div class="box"><b>CHALLAN (RETURNABLE PALLETS)</b>{k.challan_no or 'pending'}</div>
      <div class="box"><b>STATUS</b>{k.status} · loaded {len(lines)} pallet(s)</div>
    </div>
    {item_tbl}
    <table><tr><th>#</th><th>Pallet</th><th>Part cards (LPN)</th><th>Loaded at</th><th>By</th></tr>{rows}
    <tr><th colspan="4" style="text-align:right">TOTAL PALLETS LOADED</th><th>{len(lines)}</th></tr></table>
    <div style="margin-top:8px;font-size:11px"><b>OUT gate:</b> scan the QR at the top right. The gate accepts only a QR printed by AssetTrack for this GCS and vehicle.</div>
    <div class="sig"><div>PDI (Planning Bench)<br><b>{k.pdi_sign or '—'}</b></div><div>Logistics (Shift supervisor, Planning Bench)<br><b>{k.supervisor_sign or '—'}</b></div><div>Security (loading verified)<br><b>{p.user.full_name} ({p.user_id})</b></div></div>
    <div class="foot">AIS AssetTrack · Developed by DT · printed {datetime.now():%d-%m-%Y %H:%M} by {p.user_id}</div></body></html>"""
    return HTMLResponse(html)


@router.get("/slip/{no}", response_class=HTMLResponse)
def slip(no: str, tok: str = Query(...), db: Session = Depends(get_db)):
    p = _auth(tok, db)
    s = db.get(models.ReturnSlip, no)
    if not s:
        raise HTTPException(404, "Slip not found")
    p.require_plant(s.plant_code)
    return HTMLResponse(slip_html(db, s, p.user_id))
