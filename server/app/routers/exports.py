"""Excel / PDF download of any table shown on the web: the page posts the columns and rows it displays and gets an
.xlsx (formatted, filter, frozen heading) or a PDF (A4 landscape, AIS logo, repeated heading, page X of Y).
Dates are shown dd-mmm-yy. Developed by DT
"""
import io, os, re
from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .. import config
from ..security import current_user, Principal

router = APIRouter(prefix="/api/v1/export", tags=["export"])
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?)?$")


class TableIn(BaseModel):
    title: str = "AssetTrack"
    columns: list[str]
    rows: list[list]
    subtitle: str | None = None


def _val(v):
    """Numbers stay numbers; ISO dates become real dates (shown dd-mmm-yy)."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if ISO.match(s):
        try:
            return datetime.fromisoformat(s.replace(" ", "T")[:19])
        except ValueError:
            return s
    t = s.replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", t) and not (len(t) > 1 and t.startswith("0") and "." not in t) and len(t) < 15:
        return float(t) if "." in t else int(t)
    return s


def _name(title, ext):
    return f"{re.sub(r'[^A-Za-z0-9]+', '_', title).strip('_')[:60] or 'AssetTrack'}_{datetime.now():%d-%b-%y_%H%M}.{ext}"


@router.post("/xlsx")
def to_xlsx(body: TableIn, p: Principal = Depends(current_user)):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook(); ws = wb.active; ws.title = re.sub(r"[\[\]\*\?/\\:]", "", body.title)[:31] or "Data"
    ws.cell(row=1, column=1, value=f"AIS AssetTrack - {body.title}").font = Font(bold=True, size=13, color="1E3A8A")
    ws.cell(row=2, column=1, value=(body.subtitle or "") + f"  Downloaded {datetime.now():%d-%b-%y %H:%M} by {p.user_id}").font = Font(italic=True, color="64748B")
    hdr = 4
    for c, h in enumerate(body.columns, 1):
        cell = ws.cell(row=hdr, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="1E3A8A")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = [len(str(h)) + 2 for h in body.columns]
    for r, row in enumerate(body.rows, hdr + 1):
        for c, v in enumerate(row[:len(body.columns)], 1):
            val = _val(v); cell = ws.cell(row=r, column=c, value=val)
            if isinstance(val, datetime):
                cell.number_format = "dd-mmm-yy hh:mm" if (val.hour or val.minute) else "dd-mmm-yy"
            widths[c - 1] = max(widths[c - 1], min(50, len(str(v)) + 2))
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = max(9, w)
    ws.freeze_panes = ws.cell(row=hdr + 1, column=1)
    if body.columns:
        ws.auto_filter.ref = f"A{hdr}:{get_column_letter(len(body.columns))}{hdr + max(1, len(body.rows))}"
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{_name(body.title, "xlsx")}"'})


@router.post("/pdf")
def to_pdf(body: TableIn, p: Principal = Depends(current_user)):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    buf = io.BytesIO()
    n = max(1, len(body.columns))
    fs = 8 if n <= 8 else 7 if n <= 12 else 6
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=fs, leading=fs + 1.5)
    head = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=fs, leading=fs + 1.5, textColor=colors.white, alignment=1)

    def show(v):
        val = _val(v)
        if isinstance(val, datetime):
            return val.strftime("%d-%b-%y %H:%M") if (val.hour or val.minute) else val.strftime("%d-%b-%y")
        return str(v if v is not None else "")
    data = [[Paragraph(str(h), head) for h in body.columns]] + [[Paragraph(show(v).replace("&", "&amp;").replace("<", "&lt;"), cell) for v in r[:n]] for r in body.rows]
    W = landscape(A4)[0] - 20 * mm
    lens = [max([len(str(body.columns[i]))] + [len(show(r[i])) for r in body.rows[:300] if i < len(r)]) for i in range(n)]
    tot = sum(min(40, max(4, x)) for x in lens) or 1
    cw = [W * min(40, max(4, x)) / tot for x in lens]
    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#94A3B8")),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    logo = os.path.join(str(config.BASE_DIR), "app", "static", "print-logo.png")
    when = f"{datetime.now():%d-%b-%y %H:%M}"

    def deco(c, doc):
        Wp, Hp = landscape(A4)
        if os.path.exists(logo):
            c.drawImage(logo, 10 * mm, Hp - 19 * mm, 22 * mm, 15 * mm, preserveAspectRatio=True, mask="auto")
        c.setFont("Helvetica-Bold", 13); c.setFillColor(colors.HexColor("#1E3A8A")); c.drawString(36 * mm, Hp - 11 * mm, body.title)
        c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#64748B"))
        c.drawString(36 * mm, Hp - 16 * mm, (body.subtitle or "") + f"  ·  {len(body.rows)} rows  ·  downloaded {when} by {p.user_id}")
        c.drawString(10 * mm, 7 * mm, f"AIS AssetTrack v{config.APP_VERSION}")
        c.drawRightString(Wp - 10 * mm, 7 * mm, f"Page {doc.page}")
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=23 * mm, bottomMargin=12 * mm,
                            title=body.title, author="AIS AssetTrack")
    doc.build([t] if body.rows else [Paragraph("No rows", cell)], onFirstPage=deco, onLaterPages=deco)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{_name(body.title, "pdf")}"'})
