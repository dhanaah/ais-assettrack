"""Checks for the fixes from the 13-Oct-2026 full review (server 1.23.0). Run:
    PYTHONPATH=. PALLET_BENCH_SCHEDULER=0 PALLET_PICKLIST_SOURCE=APP python3 tests/audit_fixes_check.py
Developed by DT"""
import os, sys, uuid, tempfile, json, base64, threading, time
from datetime import datetime, timezone

DB = os.path.join(tempfile.gettempdir(), f"at_audit_{uuid.uuid4().hex[:6]}.db")
os.environ["PALLET_DB_URL"] = f"sqlite:///{DB}"
os.environ["PALLET_INTEGRATION_MODE"] = "STUB"
os.environ["PALLET_BENCH_SCHEDULER"] = "0"
os.environ.setdefault("PALLET_PICKLIST_SOURCE", "APP")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app.main import app
from app import models, services, config
from app.db import SessionLocal
from app.security import hash_pw

FAILS = []


def check(ok, what):
    print(("  ok - " if ok else "FAIL: ") + what)
    if not ok:
        FAILS.append(what)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def setup():
    with SessionLocal() as db:
        db.add_all([models.Plant(code="CHN", name="Chennai", gstin="33AAA"), models.Plant(code="PUN", name="Pune", gstin="27AAA")]); db.flush()
        db.add(models.Customer(code="HMIL", name="Hyundai", plant_code="CHN"))
        db.add(models.Customer(code="FORD", name="Ford", plant_code="CHN"))
        for i in range(1, 8):
            db.add(models.Pallet(pallet_no=f"CHN-P{i:03d}", home_plant="CHN", location_plant="CHN", status="AVAILABLE", zone="FGWH"))
        db.add(models.Pallet(pallet_no="PUN-P900", home_plant="PUN", location_plant="PUN", status="AVAILABLE", zone="YARD"))
        for i in range(4):
            db.add(models.Pallet(pallet_no=f"AIS-CHN-F-0600{i+1}-009{1000+i}", home_plant="CHN", status="AT_CUSTOMER", customer_code="HMIL", load_state="EMPTY"))
        for uid, plant, roles, cust in (("chn", "CHN", ["FGWH", "QA", "LOG", "SEC_OUT", "SEC_IN", "YARD", "PACK", "PADMIN"], None),
                                        ("master", None, ["MASTER"], None), ("hmil.staff", "CHN", ["CUST_STAFF"], "HMIL")):
            u = models.User(user_id=uid, full_name=uid, plant_code=plant, password_hash=hash_pw("x"), must_change_pw=False,
                            supervisor_allowed=True, supervisor_pin_hash=hash_pw("1234"), customer_code=cust)
            u.roles = [models.UserRole(role_code=r) for r in roles]; db.add(u); db.flush()
        db.commit()


def tok(c, u, hht=True):
    r = c.post("/api/v1/auth/login", json={"user_id": u, "password": "x"}); assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    return h | ({"X-Device": "HHT", "X-Device-Id": "HHT-TEST"} if hht else {})


def ev(c, h, t, payload, ts=None):
    r = c.post("/api/v1/sync/push", headers=h, json={"events": [{"event_id": str(uuid.uuid4()), "device_id": "HHT-T", "event_type": t, "payload": payload, "local_ts": ts or now()}]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def pal(no):
    with SessionLocal() as db:
        p = db.get(models.Pallet, no); return (p.status, p.customer_code, p.picklist_no)


with TestClient(app, raise_server_exceptions=False) as c:
    setup()
    H, M = tok(c, "chn"), tok(c, "master", hht=False)

    print("1. yard scan of a pallet on an open pick list takes it off the list - never dispatched twice")
    n1 = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "PALLET_ONLY", "customer_code": "HMIL", "qty": 1}).json()["picklist_no"]
    n2 = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "PALLET_ONLY", "customer_code": "FORD", "qty": 1}).json()["picklist_no"]
    ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": n1, "scanned": "CHN-P001"})
    r = ev(c, H, "PALLET_SCAN_YARD", {"scanned": "CHN-P001"})
    check("taken off pick list" in r["result"], f"yard says it was taken off {n1}: {r['result'][:90]}")
    with SessionLocal() as db:
        check(db.query(models.PickListLine).filter_by(picklist_no=n1, pallet_no="CHN-P001").count() == 0, "line removed from the first list")
    ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": n2, "scanned": "CHN-P001"})
    for n in (n2,):
        c.post(f"/api/v1/picklists/{n}/confirm", headers=H); c.post(f"/api/v1/picklists/{n}/challan", headers=H)
        c.post(f"/api/v1/picklists/{n}/approve", headers=H, json={"vehicle_no": "TN01X2"})
    with SessionLocal() as db:
        k = db.get(models.PickList, n2); sc = k.challan_no
    r = c.post(f"/api/v1/picklists/{n2}/gate-out", headers=H, json={"scanned": sc})
    check(r.status_code == 200 and pal("CHN-P001")[:2] == ("AT_CUSTOMER", "FORD"), "dispatched once, to FORD")
    r = c.post(f"/api/v1/picklists/{n2}/gate-out", headers=H, json={"scanned": sc})
    check(r.status_code == 400, f"second gate-out of the same load refused ({r.status_code})")

    print("2. gate-out refuses a load whose pallet is no longer on it")
    n3 = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "PALLET_ONLY", "customer_code": "HMIL", "qty": 1}).json()["picklist_no"]
    ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": n3, "scanned": "CHN-P002"})
    c.post(f"/api/v1/picklists/{n3}/confirm", headers=H); c.post(f"/api/v1/picklists/{n3}/challan", headers=H)
    c.post(f"/api/v1/picklists/{n3}/approve", headers=H, json={"vehicle_no": "TN01X3"})
    with SessionLocal() as db:
        p2 = db.get(models.Pallet, "CHN-P002"); p2.status = "AVAILABLE"; p2.picklist_no = None; db.commit()
        k = db.get(models.PickList, n3); sc = k.challan_no
    r = c.post(f"/api/v1/picklists/{n3}/gate-out", headers=H, json={"scanned": sc})
    check(r.status_code == 400 and "HOLD" in r.text, f"HOLD VEHICLE when a pallet left the load ({r.status_code})")

    print("3. offline slip sent after the slip was closed: closed slip unchanged")
    hm = None
    with SessionLocal() as db:
        hm = db.query(models.Customer).filter_by(code="HMIL").first().id
    pr = c.post(f"/api/v1/customers/{hm}/devices", headers=M, json={"label": "gate HHT"}).json()
    raw = pr["pairing"].split("|", 1)[1]; pl2 = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    DK = {"X-API-Key": pl2["k"], "X-Route": "LAN"}
    st = c.post("/api/ext/v1/staff-login", headers=DK, json={"user_id": "hmil.staff", "password": "x"}).json().get("token", "")
    DK |= {"X-Staff-Token": st}
    did, key = pl2["i"], pl2["s"]
    ro = f"RO-CHN-{did}-00001"
    head = f"AIS1|RO|{ro}|CHN|HMIL|TN09AB7777|1|2610111200|{did}|F-06001"
    qr = f"{head}|{services.offline_sig(key, head)}"
    g = c.post("/api/v1/slips/" + qr.replace("|", "%7C") + "/gate-in", headers=H, json={"vehicle_no": "TN09AB7777"})
    check(g.status_code == 200, f"offline slip opened at the gate ({g.status_code})")
    ev(c, H, "PALLET_SCAN_YARD", {"slip_no": ro, "scanned": "AIS-CHN-F-06001-0091000"})
    check(c.post(f"/api/v1/slips/{ro}/close", headers=H, json={}).status_code == 200, "closed at the yard")
    r = c.post("/api/ext/v1/return-slip", headers=DK, json={"slip_no": ro, "pallets": ["AIS-CHN-F-06001-0091000", "AIS-CHN-F-06002-0091001"], "vehicle_no": "TN09AB7777"})
    j = r.json()
    check(r.status_code == 200 and j["status"] == "CLOSED" and j["declared_qty"] == 1, "closed slip keeps its pallets and count")
    check(pal("AIS-CHN-F-06002-0091001")[0] == "AT_CUSTOMER", "extra pallet NOT moved to in-return")
    check(any("already closed" in w for w in j.get("warnings", [])), "warning about the extra pallet")

    print("4. same pallet twice on an offline slip: no server error")
    ro2 = f"RO-CHN-{did}-00002"
    head = f"AIS1|RO|{ro2}|CHN|HMIL|TN09AB7777|1|2610111200|{did}|"
    qr = f"{head}|{services.offline_sig(key, head)}"
    c.post("/api/v1/slips/" + qr.replace("|", "%7C") + "/gate-in", headers=H, json={"vehicle_no": "TN09AB7777"})
    r = c.post("/api/ext/v1/return-slip", headers=DK, json={"slip_no": ro2, "pallets": ["AIS-CHN-F-06003-0091002", "AIS-CHN-F-06003-0091002"], "vehicle_no": "TN09AB7777"})
    check(r.status_code == 200, f"merge with a duplicate pallet accepted ({r.status_code})")

    print("5. customer slip cannot move another plant's pallet")
    r = c.post("/api/ext/v1/return-slip", headers=DK, json={"pallets": ["PUN-P900"], "vehicle_no": "TN09AB1212"}).json()
    check(pal("PUN-P900")[0] == "AVAILABLE", "Pune pallet stays AVAILABLE")

    print("6. print pages escape what customers type")
    r = c.post("/api/ext/v1/return-slip", headers=DK, json={"pallets": ["AIS-CHN-F-06004-0091003"], "vehicle_no": "TN09AB3434",
                                                         "driver_name": "<script>alert(1)</script>", "client_ref": str(uuid.uuid4())}).json()
    t = c.post("/api/v1/auth/ticket", headers=H).json()["ticket"]
    page = c.get(f"/print/slip/{r['slip_no']}?tok={t}").text
    check(c.get(f"/print/slip/{r['slip_no']}?tok=" + H["Authorization"].split()[1]).status_code == 401, "sign-in token in a link is refused (2-minute ticket only)")
    check(c.get("/api/v1/reports/export/pallets.xlsx?tok=" + t).status_code == 200, "ticket opens an Excel download")
    check("<script>alert(1)</script>" not in page and "&lt;script&gt;" in page, "driver name shown as text, not run")

    print("7. Option B slip sent twice by the gate HHT: same slip back")
    body = {"customer_code": "HMIL", "mode": "B2", "declared_qty": 2, "doc_photo_count": 1, "vehicle_no": "TN09AB5555", "slip_no": "CHN-B-DEV-1"}
    r1 = c.post("/api/v1/slips", headers=H, json=body); r2 = c.post("/api/v1/slips", headers=H, json=body)
    check(r1.status_code == 200 and r2.status_code == 200 and r2.json().get("duplicate"), "repeat accepted as the same slip")

    print("8. Option B: pallet already in the yard does not count")
    ev(c, H, "PALLET_SCAN_YARD", {"slip_no": "CHN-B-DEV-1", "scanned": "CHN-P003"})
    with SessionLocal() as db:
        l = db.query(models.ReturnSlipLine).filter_by(slip_no="CHN-B-DEV-1", pallet_no="CHN-P003").first()
        check(l is not None and l.exception == "ALREADY_IN", "marked ALREADY_IN")

    print("9. document numbers never repeat when two requests run together")
    got = []
    def take():
        with SessionLocal() as db:
            got.append(services.doc_number(db, "CHN", "GE")); time.sleep(0.3); db.commit()
    th = [threading.Thread(target=take) for _ in range(4)]; [x.start() for x in th]; [x.join() for x in th]
    check(len(set(got)) == 4, f"4 different numbers {sorted(got)}")

    print("10. customer staff cannot sign in to the AIS system")
    r = c.post("/api/v1/auth/login", json={"user_id": "hmil.staff", "password": "x"})
    check(r.status_code == 403, f"refused ({r.status_code})")

    print("11. old public secret: new slips' label links / QRs made with it are refused")
    with SessionLocal() as db:
        sl = db.query(models.ReturnSlip).filter(models.ReturnSlip.mode == "A").order_by(models.ReturnSlip.created_at.desc()).first()
        no = sl.slip_no
    bad = services.label_token(no, config.LEGACY_SECRET)
    check(c.get(f"/api/ext/v1/return-slip/{no}/label?t={bad}").status_code == 403, "label link made with the old secret refused")
    check(c.get(f"/api/ext/v1/return-slip/{no}/label?t={services.label_token(no)}").status_code == 200, "real label link works")

    print("12. supervisor PIN guessing is stopped")
    from app.security import verify_supervisor_pin, _PIN_FAILS
    _PIN_FAILS.clear()
    codes = []
    with SessionLocal() as db:
        for i in range(10):
            try:
                verify_supervisor_pin(db, "CHN", f"{9000 + i}"); codes.append("no")
            except Exception as e:
                codes.append(getattr(e, "status_code", 0))
        check(429 in codes, f"paused after repeated wrong PINs {codes}")
        try:
            verify_supervisor_pin(db, "CHN", "1234"); check(False, "right PIN also paused during the lock")
        except Exception as e:
            check(getattr(e, "status_code", 0) == 429, "right PIN also paused during the lock")
    _PIN_FAILS.clear()

    print("13. scan older than the kept history is never re-applied")
    keep = config.EVENT_RETENTION_DAYS; config.EVENT_RETENTION_DAYS = 30
    r = ev(c, H, "PALLET_SCAN_YARD", {"scanned": "CHN-P004"}, ts="2026-02-01T00:00:00")
    check(r["status"] == "REJECTED" and "too old" in r["result"], "scan older than the kept history refused")
    r = ev(c, H, "PALLET_SCAN_YARD", {"scanned": "CHN-P005"}, ts="1970-01-01T00:10:00")
    check(r["status"] != "REJECTED", f"scan from an HHT with a reset clock (1970) still applied: {r['status']}")
    config.EVENT_RETENTION_DAYS = keep

    print("14. damage mark only for this plant's pallets")
    r = ev(c, H, "DAMAGE_MARK", {"scanned": "PUN-P900"})
    check(r["status"] == "REJECTED", "Pune pallet cannot be marked damaged at Chennai")

    print("15. Option A slip with a torn QR: supervisor PIN lets it in, typed number alone does not")
    r = c.post("/api/ext/v1/return-slip", headers=DK, json={"pallets": ["CHN-P006"], "vehicle_no": "TN09AB9898", "client_ref": str(uuid.uuid4())}).json()
    sno = r["slip_no"]
    r1 = c.post(f"/api/v1/slips/{sno}/gate-in", headers=H, json={})
    check(r1.status_code == 400 and "supervisor PIN" in r1.text, f"slip number without QR held ({r1.status_code})")
    r2 = c.post(f"/api/v1/slips/{sno}/gate-in", headers=H, json={"supervisor_pin": "1234"})
    check(r2.status_code == 200, f"let in with supervisor PIN ({r2.status_code} {r2.text[:80]})")

    print("16. retry job: key from job.key works; a call passed on by IIS / proxy without it is refused")
    check(c.post("/api/v1/jobs/retry", headers={"X-Forwarded-For": "10.1.2.3"}).status_code == 403, "proxied call without key refused")
    check(c.post("/api/v1/jobs/retry", headers={"X-Forwarded-For": "10.1.2.3", "X-Job-Key": config.JOB_KEY}).status_code == 200, "call with the job key accepted")

    print("17. password change ends older sign-ins")
    W2 = tok(c, "chn", hht=False)
    r = c.post("/api/v1/auth/change-password", headers=W2, json={"old_password": "x", "new_password": "newpass1"})
    check(r.status_code == 200 and r.json().get("token"), "changed, new token given")
    check(c.get("/api/v1/auth/me", headers=H).status_code == 401, "old token refused")
    check(c.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + r.json()["token"]}).status_code == 200, "new token works")

print()
print("ALL AUDIT CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
