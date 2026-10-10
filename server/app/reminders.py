"""Customer pallet reminders and internal escalation (email).
Nightly (via the retry job) or on demand from the web: every customer holding pallets past its holding limit gets an
email with the pallet list; after escalation_days more, the plant admins are copied. reminder_every_days throttles.
SMTP from settings.env: PALLET_SMTP_HOST, PALLET_SMTP_PORT (587), PALLET_SMTP_USER, PALLET_SMTP_PASS, PALLET_SMTP_FROM,
PALLET_SMTP_TLS (1). Without SMTP_HOST the run is a dry run: emails are prepared and logged, not sent.
Developed by DT
"""
import os, html, logging, smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from sqlalchemy import String, Integer, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base
from . import models, config
from .models import utcnow

log = logging.getLogger("reminders")
SMTP = {"host": os.getenv("PALLET_SMTP_HOST", ""), "port": int(os.getenv("PALLET_SMTP_PORT", "587") or 587),
        "user": os.getenv("PALLET_SMTP_USER", ""), "password": os.getenv("PALLET_SMTP_PASS", ""),
        "sender": os.getenv("PALLET_SMTP_FROM", "") or os.getenv("PALLET_SMTP_USER", ""), "tls": os.getenv("PALLET_SMTP_TLS", "1") == "1"}
RUN_HOUR = int(os.getenv("PALLET_REMINDER_HOUR", "9") or 9)      # local hour of the daily run
DEFAULT_EVERY = 7


class EmailLog(Base):
    __tablename__ = "email_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    plant_code: Mapped[str | None] = mapped_column(String(10), index=True)
    customer_code: Mapped[str | None] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(12))                  # REMINDER | ESCALATION
    to: Mapped[str | None] = mapped_column(String(500))
    cc: Mapped[str | None] = mapped_column(String(500))
    subject: Mapped[str | None] = mapped_column(String(200))
    pallets: Mapped[int] = mapped_column(Integer, default=0)
    overdue: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10))                # SENT | DRY | FAILED | SKIPPED
    error: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)


def configured() -> bool:
    return bool(SMTP["host"] and SMTP["sender"])


def _addrs(s: str | None) -> list[str]:
    return [a.strip() for a in (s or "").replace(",", ";").split(";") if a.strip() and "@" in a]


def plant_admin_emails(db: Session, plant: str) -> list[str]:
    out = []
    for u in db.query(models.User).filter(models.User.plant_code == plant, models.User.active == True).all():
        if u.email and ("PADMIN" in u.role_codes or "LOG" in u.role_codes):
            out.append(u.email)
    return out


def build(db: Session, plant: str | None = None, force: bool = False) -> list[dict]:
    """What would be sent now. One entry per customer that holds overdue pallets."""
    now = utcnow()
    plants = {x.code: x for x in db.query(models.Plant).filter_by(active=True).all()}
    q = db.query(models.Pallet).filter(models.Pallet.status == "AT_CUSTOMER")
    if plant:
        q = q.filter(models.Pallet.home_plant == plant)
    by = {}
    for x in q.all():
        if x.customer_code in plants:            # stock transfer to another AIS plant - not a customer reminder
            continue
        by.setdefault((x.home_plant, x.customer_code), []).append(x)
    out = []
    for (pl, cc), pals in sorted(by.items()):
        c = db.query(models.Customer).filter_by(plant_code=pl, code=cc).first()
        if not c or not c.active:
            continue
        limit = c.holding_limit_days or (plants[pl].holding_days_default if pl in plants else 30)
        every = c.reminder_every_days or DEFAULT_EVERY
        rows = []
        for x in sorted(pals, key=lambda x: x.dispatch_date or now):
            days = (now - x.dispatch_date).days if x.dispatch_date else 0
            rows.append({"pallet_no": x.pallet_no, "tag": x.current_tag, "type": x.pallet_type, "challan": x.challan_ref,
                         "dispatched": x.dispatch_date, "days": days, "overdue": days > limit, "over_by": max(0, days - limit)})
        od = [r for r in rows if r["overdue"]]
        if not od:
            continue
        key = f"reminder_last:{pl}:{cc}"
        last = db.get(models.Setting, key)
        last_dt = datetime.fromisoformat(last.value) if last and last.value else None
        due = force or not last_dt or (now - last_dt).days >= every
        max_over = max(r["over_by"] for r in od)
        escalate = bool(c.escalation_days) and max_over > c.escalation_days
        to = _addrs(c.email_to)
        cc_list = _addrs(c.email_cc) + (plant_admin_emails(db, pl) if escalate else [])
        out.append({"plant": pl, "customer": cc, "name": c.name, "limit": limit, "every": every, "to": to, "cc": sorted(set(cc_list)),
                    "kind": "ESCALATION" if escalate else "REMINDER", "pallets": rows, "overdue": len(od), "total": len(rows),
                    "last_sent": last_dt, "due": due, "contact": c.contact_name,
                    "subject": f"{'ESCALATION - ' if escalate else ''}AIS Glass returnable pallets due for return - {c.name} ({cc}) - {len(od)} pallet(s) overdue"})
    return out


def render(item: dict) -> str:
    e = html.escape
    pl = item["plant"]
    rows = "".join(
        f"<tr style='background:{'#fff5f5' if r['overdue'] else '#fff'}'><td>{e(r['pallet_no'])}</td><td>{e(r['type'] or '')}</td><td>{e(r['challan'] or '')}</td>"
        f"<td>{r['dispatched']:%d-%m-%Y}</td><td style='text-align:right'>{r['days']}</td><td style='text-align:right;color:{'#b91c1c' if r['overdue'] else '#555'}'>{r['over_by'] or ''}</td></tr>"
        if r["dispatched"] else "" for r in item["pallets"])
    return f"""<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#222">
<p>Dear {e(item.get('contact') or item['name'])},</p>
<p>As per our records, <b>{item['total']}</b> returnable pallet(s) of AIS Glass plant <b>{e(pl)}</b> are with <b>{e(item['name'])}</b>,
of which <b style="color:#b91c1c">{item['overdue']}</b> have exceeded the agreed holding period of <b>{item['limit']} days</b>.
Kindly arrange their return at the earliest and share the return slip / vehicle details.</p>
<table style="border-collapse:collapse;width:100%" border="1" cellpadding="4">
<tr style="background:#1e3a8a;color:#fff"><th>Pallet</th><th>Type</th><th>Our challan</th><th>Dispatched</th><th>Days</th><th>Over by</th></tr>{rows}</table>
<p>{'<b style="color:#b91c1c">This is an escalation: the plant management is copied.</b>' if item['kind'] == 'ESCALATION' else ''}</p>
<p>Regards,<br>AIS Glass - plant {e(pl)}<br><span style="color:#777;font-size:11px">Automatic message from {e(config.APP_NAME)} · {e(config.DEVELOPER)}</span></p>
</body></html>"""


def _send(item: dict, body: str):
    msg = EmailMessage()
    msg["Subject"] = item["subject"]; msg["From"] = SMTP["sender"]; msg["To"] = ", ".join(item["to"])
    if item["cc"]:
        msg["Cc"] = ", ".join(item["cc"])
    msg.set_content("Please view this message in an HTML capable mail client.")
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP(SMTP["host"], SMTP["port"], timeout=30) as s:
        if SMTP["tls"]:
            s.starttls()
        if SMTP["user"]:
            s.login(SMTP["user"], SMTP["password"])
        s.send_message(msg)


def run(db: Session, plant: str | None = None, force: bool = False, dry: bool | None = None) -> dict:
    """Send what is due. dry=None -> dry when SMTP is not configured."""
    dry = (not configured()) if dry is None else dry
    res = {"sent": 0, "dry": 0, "failed": 0, "skipped": 0, "dry_run": dry}
    for item in build(db, plant, force):
        body = render(item)
        entry = EmailLog(plant_code=item["plant"], customer_code=item["customer"], kind=item["kind"], to=";".join(item["to"]),
                         cc=";".join(item["cc"]), subject=item["subject"], pallets=item["total"], overdue=item["overdue"], body=body)
        if not item["due"]:
            entry.status, entry.error = "SKIPPED", f"sent {item['last_sent']:%d-%m-%Y}, every {item['every']} days"; res["skipped"] += 1
        elif not item["to"]:
            entry.status, entry.error = "SKIPPED", "no email address on the customer master"; res["skipped"] += 1
        elif dry:
            entry.status = "DRY"; res["dry"] += 1
        else:
            try:
                _send(item, body); entry.status = "SENT"; res["sent"] += 1
            except Exception as e:
                entry.status, entry.error = "FAILED", str(e)[:300]; res["failed"] += 1
        if entry.status in ("SENT", "DRY"):
            key = f"reminder_last:{item['plant']}:{item['customer']}"
            row = db.get(models.Setting, key) or models.Setting(key=key)
            row.value = utcnow().isoformat(); db.add(row)
        db.add(entry)
    db.commit()
    return res


def daily_tick(db: Session) -> dict | None:
    """Called every few minutes by the retry job: runs once per day after RUN_HOUR (local time)."""
    now_local = datetime.now()
    if now_local.hour < RUN_HOUR:
        return None
    key = "reminders_last_run"
    row = db.get(models.Setting, key)
    if row and row.value and row.value[:10] == now_local.strftime("%Y-%m-%d"):
        return None
    row = row or models.Setting(key=key)
    row.value = now_local.isoformat(); db.add(row); db.commit()
    res = run(db)
    log.info("daily reminders: %s", res)
    return res
