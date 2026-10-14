"""Checks for the 1.26 process rules (Gate-In endorsement, Yard = pallet QR, FGWH / Packing = pallet card, Security vehicle
loading, OUT gate by challan only, one permission per HHT button). Run:
    PYTHONPATH=. PALLET_BENCH_SCHEDULER=0 PALLET_PICKLIST_SOURCE=APP python3 tests/process_rules_check.py
Developed by DT"""
import os, sys, uuid, tempfile
from datetime import datetime, timezone

DB = os.path.join(tempfile.gettempdir(), f"at_rules_{uuid.uuid4().hex[:6]}.db")
os.environ["PALLET_DB_URL"] = f"sqlite:///{DB}"
os.environ["PALLET_INTEGRATION_MODE"] = "STUB"
os.environ["PALLET_BENCH_SCHEDULER"] = "0"
os.environ.setdefault("PALLET_PICKLIST_SOURCE", "APP")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app.main import app
from app import models
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
        for i in range(1, 10):
            db.add(models.Pallet(pallet_no=f"CHN-P{i:03d}", home_plant="CHN", location_plant="CHN", status="AVAILABLE", zone="YARD", load_state="EMPTY"))
        # P005..P007 loaded at FGWH with pallet cards
        for i, card in ((5, "PC-5"), (6, "PC-6"), (7, "PC-7")):
            db.add(models.Lpn(lpn_no=card, plant_code="CHN", part_no="WS-1", qty=10, status="AVAILABLE", pallet_no=f"CHN-P{i:03d}"))
        # other-plant material: Pune pallets sent to Chennai on stock transfer challan ST-1 with cards
        for i, card in ((1, "PUN-C1"), (2, "PUN-C2")):
            db.add(models.Pallet(pallet_no=f"PUN-P{i:03d}", home_plant="PUN", status="AT_CUSTOMER", customer_code="CHN", challan_ref="ST-1", load_state="LOADED"))
            db.add(models.Lpn(lpn_no=card, plant_code="PUN", part_no="WS-9", qty=5, status="DISPATCHED", pallet_no=f"PUN-P{i:03d}"))
        db.add(models.PickList(picklist_no="PUN-ST-1", plant_code="PUN", customer_code="CHN", to_plant="CHN", dispatch_type="STOCK_TRANSFER", qty=2,
                               status="DISPATCHED", challan_no="ST-1"))
        for uid, roles in (("chn", ["FGWH", "QA", "LOG", "SEC_OUT", "SEC_IN", "YARD", "PACK", "PADMIN"]), ("yardonly", []), ("master", ["MASTER"])):
            u = models.User(user_id=uid, full_name=uid, plant_code=None if uid == "master" else "CHN", password_hash=hash_pw("x"), must_change_pw=False,
                            supervisor_allowed=True, supervisor_pin_hash=hash_pw("1234"))
            u.roles = [models.UserRole(role_code=r) for r in roles]
            if uid == "yardonly":
                u.perms_override = "YARD_SCAN"
            db.add(u); db.flush()
        db.commit()


def tok(c, u):
    r = c.post("/api/v1/auth/login", json={"user_id": u, "password": "x"}); assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "X-Device": "HHT", "X-Device-Id": "HHT-RULES"}


def ev(c, h, t, payload):
    r = c.post("/api/v1/sync/push", headers=h, json={"events": [{"event_id": str(uuid.uuid4()), "device_id": "HHT-R", "event_type": t, "payload": payload, "local_ts": now()}]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


with TestClient(app, raise_server_exceptions=False) as c:
    setup()
    H, Y = tok(c, "chn"), tok(c, "yardonly")

    print("1. permissions: one per HHT button, existing roles keep access")
    with SessionLocal() as db:
        perms = lambda code: {x.perm for x in db.get(models.Role, code).permissions}
        check({"YARD_IN_PLANT", "YARD_TO_PACKING"} <= perms("YARD"), "Yard role has the new Yard-In / Yard-Out permissions")
        check("VEHICLE_LOAD" in perms("SEC_OUT") and "PACK_PDI" in perms("QA") and {"PACK_RECEIPT", "PACK_DISPATCH"} <= perms("PACK"), "Security / QA / Packing roles have their new permissions")
        check(db.get(models.Setting, "perm_upgrade_1_26") is not None and db.get(models.Setting, "perm_upgrade_1_27") is not None, "one-time upgrades recorded (admin removals are kept afterwards)")
        check({"MOVE_TO_DISPATCH", "MOVE_FG_TO_PRODUCTION"} <= perms("FGWH"), "FGWH role has FGWH -> Main Dispatch and FGWH -> Production")
    pg = c.get("/api/v1/perm-groups", headers={"Authorization": tok(c, "master")["Authorization"]})
    check(pg.status_code == 200 and any("Security · Gate-In" in k for k in (pg.json() if isinstance(pg.json(), dict) else {x.get("group", ""): 1 for x in pg.json()})), "web permission groups follow the HHT groups")

    print("2. Gate-In endorsement: Yard receives only slips / challans registered at the IN gate")
    sl = models.ReturnSlip(slip_no="CHN-RTS-A1", plant_code="CHN", customer_code="HMIL", mode="A", vehicle_no="TN01A1", declared_qty=1, status="OPEN", source="CUST_HHT")
    with SessionLocal() as db:
        db.add(sl); db.add(models.ReturnSlipLine(slip_no="CHN-RTS-A1", pallet_no="CHN-P009", declared=True)); db.commit()
    r = ev(c, H, "PALLET_SCAN_YARD", {"slip_no": "CHN-RTS-A1", "scanned": "CHN-P009"})
    check(r["status"] == "REJECTED" and "IN gate" in r["result"], f"Option A slip not gated in: refused ({r['result'][:60]})")
    pull = c.get("/api/v1/sync/pull", headers=H).json()
    check(not any(s["slip_no"] == "CHN-RTS-A1" for s in pull["slips"]), "slip not gated in is not sent to the Yard HHT")
    r = ev(c, H, "PALLET_SCAN_YARD", {"slip_no": "ST-9", "scanned": "CHN-P009"})
    check(r["status"] == "REJECTED" and "IN gate" in r["result"], "other-plant challan not registered at the gate: refused")
    r = ev(c, Y, "PALLET_SCAN_YARD", {"slip_no": "ST-1", "scanned": "CHN-P009"})
    check(r["status"] == "REJECTED", "user with Customer returns only cannot receive other-plant challans (YARD_IN_PLANT)")

    print("3. Yard = pallet QR only")
    r = ev(c, H, "PALLET_SCAN_YARD", {"scanned": "PC-5"})
    check(r["status"] == "REJECTED" and "pallet QR" in r["result"], "pallet card at the Yard refused")

    print("4. moves: empty = pallet QR, loaded = pallet card, FGWH is the centre (Main Dispatch / Packing / back to Production)")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-6", "to_zone": "PRODUCTION", "strict": 1})
    check(r["status"] == "REJECTED" and "pallet QR" in r["result"], "empty move with a pallet card refused")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "CHN-P001", "to_zone": "PRODUCTION", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"Yard -> Production by pallet QR: {r['result'][:50]}")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "CHN-P002", "to_zone": "PACKING", "load": "EMPTY", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"Yard -> Packing (empty) by pallet QR: {r['result'][:50]}")
    with SessionLocal() as db:
        p2 = db.get(models.Pallet, "CHN-P002")
        check(p2.zone == "PACKING" and p2.load_state == "EMPTY", "pallet at Packing, EMPTY")
        for no in ("CHN-P005", "CHN-P006"):
            x = db.get(models.Pallet, no); x.zone = "PRODUCTION"; x.load_state = "LOADED"
        db.commit()
    r = ev(c, H, "PALLET_MOVE", {"scanned": "CHN-P005", "to_zone": "FGWH", "strict": 1})
    check(r["status"] == "REJECTED" and "pallet card" in r["result"], "loaded move with the pallet QR refused")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-5", "to_zone": "FGWH", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"Production -> FGWH by pallet card: {r['result'][:50]}")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-6", "to_zone": "PACKING", "strict": 1})
    check(r["status"] == "REJECTED" and "FGWH first" in r["result"], "Production -> Packing refused - FGWH is the centre")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-6", "to_zone": "DISPATCH", "strict": 1})
    check(r["status"] == "REJECTED" and "FGWH first" in r["result"], "Production -> Main Dispatch refused - FGWH is the centre")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-6", "to_zone": "FGWH", "strict": 1})
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-5", "to_zone": "DISPATCH", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"FGWH -> Main Dispatch by pallet card: {r['result'][:50]}")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-5", "to_zone": "PACKING", "strict": 1})
    check(r["status"] == "REJECTED" and "Main Dispatch and Packing" in r["result"], "Main Dispatch -> Packing refused")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-6", "to_zone": "PRODUCTION", "load": "LOADED", "strict": 1})
    check(r["status"] == "REJECTED" and "reason" in r["result"], "FGWH -> Production without a reason refused")
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-6", "to_zone": "PRODUCTION", "load": "LOADED", "remarks": "REJECTION", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"FGWH -> Production (rejection) by pallet card: {r['result'][:50]}")
    with SessionLocal() as db:
        check(db.get(models.Pallet, "CHN-P006").zone == "PRODUCTION" and db.get(models.Pallet, "CHN-P006").load_state == "LOADED", "returned pallet at Production, still LOADED")
        x = db.get(models.Pallet, "CHN-P006"); x.zone = "FGWH"; db.commit()
    r = ev(c, H, "PALLET_MOVE", {"scanned": "PC-6", "to_zone": "PACKING", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"FGWH -> Packing by pallet card: {r['result'][:50]}")

    print("5. other-plant material at FGWH / Packing: pallet card on a challan endorsed at the IN gate")
    r = ev(c, H, "PLANT_RECEIPT", {"scanned": "PUN-P001", "zone": "FGWH", "strict": 1})
    check(r["status"] == "REJECTED" and "pallet card" in r["result"], "pallet QR refused - scan the pallet card")
    r = ev(c, H, "PLANT_RECEIPT", {"scanned": "PUN-C1", "zone": "FGWH", "strict": 1})
    check(r["status"] == "REJECTED" and "not endorsed at the IN gate" in r["result"], "challan not at the IN gate yet: HOLD")
    g = c.post("/api/v1/slips/CHL%7CST-1%7CPUN-ST-1%7C2/gate-in", headers=H, json={})
    check(g.status_code == 200 and g.json().get("kind") == "CHALLAN", f"IN gate registers the material challan ({g.status_code})")
    pull = c.get("/api/v1/sync/pull", headers=H).json()
    check(any(s["slip_no"] == "ST-1" and s["mode"] == "CHM" for s in pull["slips"]), "material challan sent to FGWH / Packing (not the Yard list)")
    r = ev(c, H, "PLANT_RECEIPT", {"scanned": "PUN-C1", "zone": "FGWH", "ref": "ST-1", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"received at FGWH by pallet card: {r['result'][:60]}")
    r = ev(c, H, "PLANT_RECEIPT", {"scanned": "PUN-C2", "zone": "FGWH", "ref": "ST-1", "strict": 1})
    check(r["status"] in ("APPLIED", "EXCEPTION"), f"second card received at FGWH: {r['result'][:60]}")

    print("6. dispatch preparation = pallet card; Security loads by pallet QR; OUT gate = challan only")
    with SessionLocal() as db:
        db.add(models.PickList(picklist_no="CHN-PL-9", plant_code="CHN", customer_code="HMIL", dispatch_type="CUSTOMER", qty=2, status="OPEN", gcs_no="GCS-9"))
        db.commit()
    r = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": "CHN-PL-9", "scanned": "CHN-P007", "strict": 1})
    check(r["status"] == "REJECTED" and "pallet card" in r["result"], "dispatch preparation with the pallet QR refused")
    with SessionLocal() as db:   # prepared load: two pallets on the GCS, approved for the gate
        k = db.get(models.PickList, "CHN-PL-9"); k.status = "APPROVED"; k.challan_no = "CH-9"; k.vehicle_no = "TN09X9"
        for no in ("CHN-P007", "CHN-P008"):
            x = db.get(models.Pallet, no); x.status = "ALLOCATED"; x.picklist_no = "CHN-PL-9"
            db.add(models.PickListLine(picklist_no="CHN-PL-9", pallet_no=no))
        db.commit()
    r = c.post("/api/v1/picklists/CHN-PL-9/load", headers=H, json={"scanned": "PC-7"})
    check(r.status_code == 400 and "pallet QR" in r.text, "vehicle loading with the pallet card refused")
    r = c.post("/api/v1/picklists/CHN-PL-9/load", headers=H, json={"scanned": "CHN-P003"})
    check(r.status_code == 400 and "not prepared" in r.text, "pallet not prepared on this GCS: keep it off")
    r = c.post("/api/v1/picklists/CHN-PL-9/load", headers=H, json={"scanned": "CHN-P007"}).json()
    check(r["loaded"] == 1 and r["total"] == 2, "1 of 2 loaded")
    r = c.post("/api/v1/picklists/CHN-PL-9/load", headers=H, json={"scanned": "CHN-P007"}).json()
    check(r["duplicate"], "second scan of the same pallet: already loaded")
    r = c.post("/api/v1/gate-out/scan", headers=H, json={"scanned": "AIS1|GCS|GCS-9|CHN|HMIL|TN09X9|2|2610140000|ABCD1234"})
    check(r.status_code == 400 and "CHALLAN" in r.text, "OUT gate refuses the GCS QR - challan only")
    r = c.post("/api/v1/gate-out/scan", headers=H, json={"scanned": "CHL|CH-9|CHN-PL-9|2"})
    check(r.status_code == 400 and "not loaded by Security" in r.text, "vehicle held: 1 pallet not loaded")
    c.post("/api/v1/picklists/CHN-PL-9/load", headers=H, json={"scanned": "CHN-P008"})
    r = c.post("/api/v1/gate-out/scan", headers=H, json={"scanned": "CHL|CH-9|CHN-PL-9|2"})
    check(r.status_code == 200 and r.json()["status"] == "DISPATCHED", "all loaded: challan QR dispatches the vehicle")
    r = c.get("/api/v1/loading", headers=Y)
    check(r.status_code == 403, "Vehicle loading needs the VEHICLE_LOAD permission")

    print("7. review fixes: incoming cards reach the HHT, material challan closed by FGWH, gate-out route challan only")
    with SessionLocal() as db:   # a second Pune load still on its way in (challan ST-2), registered at the gate
        db.add(models.Pallet(pallet_no="PUN-P003", home_plant="PUN", status="AT_CUSTOMER", customer_code="CHN", challan_ref="ST-2", load_state="LOADED"))
        db.add(models.Lpn(lpn_no="PUN-C3", plant_code="PUN", part_no="WS-9", qty=5, status="DISPATCHED", pallet_no="PUN-P003"))
        db.add(models.PickList(picklist_no="PUN-ST-2", plant_code="PUN", customer_code="CHN", to_plant="CHN", dispatch_type="STOCK_TRANSFER", qty=1, status="DISPATCHED", challan_no="ST-2"))
        db.add(models.PickListLine(picklist_no="PUN-ST-2", pallet_no="PUN-P003")); db.commit()
    c.post("/api/v1/slips/CHL%7CST-2%7CPUN-ST-2%7C1/gate-in", headers=H, json={})
    pull = c.get("/api/v1/sync/pull", headers=H).json()
    check(any(l["lpn"] == "PUN-C3" and l["pallet"] == "PUN-P003" for l in pull["lpns"]), "incoming pallet card of the gated challan sent to the HHT")
    r = ev(c, H, "PALLET_SCAN_YARD", {"slip_no": "ST-2", "scanned": "PUN-P003"})
    check(r["status"] == "REJECTED" and "material" in r["result"], "material challan refused at the Yard")
    ev(c, H, "PLANT_RECEIPT", {"scanned": "PUN-C3", "zone": "FGWH", "ref": "ST-2", "strict": 1})
    r = c.post("/api/v1/slips/ST-2/close", headers=H, json={})
    check(r.status_code == 200 and r.json()["status"] == "CLOSED", f"material challan closed after receipt ({r.status_code} {r.text[:80]})")
    with SessionLocal() as db:
        db.add(models.PickList(picklist_no="CHN-PL-10", plant_code="CHN", customer_code="HMIL", dispatch_type="PALLET_ONLY", qty=1, status="APPROVED", gcs_no="GCS-10", challan_no="CH-10"))
        x = db.get(models.Pallet, "CHN-P009"); x.status = "ALLOCATED"; x.picklist_no = "CHN-PL-10"
        db.add(models.PickListLine(picklist_no="CHN-PL-10", pallet_no="CHN-P009")); db.commit()
    r = c.post("/api/v1/picklists/CHN-PL-10/gate-out", headers=H, json={"scanned": "GCS-10"})
    check(r.status_code == 400 and "CHALLAN" in r.text, "gate-out by GCS number refused - challan only")
    r = c.post("/api/v1/picklists/CHN-PL-10/gate-out", headers=H, json={"scanned": "CH-10"})
    check(r.status_code == 200, "gate-out by challan works")

print()
print("ALL PROCESS RULE CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
