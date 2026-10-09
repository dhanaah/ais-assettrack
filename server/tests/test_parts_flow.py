"""End-to-end regression for v1.4: WMS stock, blanket, LPN<->pallet dock scan, PDI + double-confirmed sub-inventory
transfer, SO after PDI, invoice + challan, loaded/empty, internal moves, other-plant receipt, empty return + e-way bill,
missed-scan detection. Run:  python -m tests.test_parts_flow   (from server/, uses a temp SQLite db)"""
import os, sys, uuid, tempfile
from datetime import datetime
DB = os.getenv("KEEP") or os.path.join(tempfile.gettempdir(), f"at_test_{uuid.uuid4().hex[:6]}.db")
os.environ["PALLET_DB_URL"] = f"sqlite:///{DB}"
os.environ["PALLET_INTEGRATION_MODE"] = "STUB"
from fastapi.testclient import TestClient
from app.main import app
from app import models
from app.db import SessionLocal
from app.security import hash_pw

ok_n = 0
def check(cond, msg):
    global ok_n
    if not cond:
        print("FAIL:", msg); sys.exit(1)
    ok_n += 1; print("  ok -", msg)


def setup():
    with SessionLocal() as db:
        db.add_all([models.Plant(code="CHN", name="Chennai", gstin="33AAA", reject_subinv="REJ", wms_stale_hours=4),
                    models.Plant(code="PUN", name="Pune", gstin="27AAA")])
        db.flush()
        db.add(models.Customer(code="HMIL", name="Hyundai", plant_code="CHN"))
        for i in range(1, 8):
            db.add(models.Pallet(pallet_no=f"CHN-P{i:03d}", home_plant="CHN", location_plant="CHN", status="AVAILABLE"))
        for i in range(1, 4):
            db.add(models.Pallet(pallet_no=f"PUN-P{i:03d}", home_plant="PUN", location_plant=None, status="AT_CUSTOMER", customer_code="CHN",
                                 challan_ref="PUN-ST-1", dispatch_date=datetime.utcnow()))
        for uid, plant, roles in (("chn", "CHN", ["FGWH", "QA", "LOG", "SEC_OUT", "SEC_IN", "YARD", "PACK", "PADMIN"]), ("pun", "PUN", ["YARD", "FGWH"]),
                                  ("master", None, ["MASTER"])):
            u = models.User(user_id=uid, full_name=uid, plant_code=plant, password_hash=hash_pw("x"), must_change_pw=False,
                            supervisor_allowed=True, supervisor_pin_hash=hash_pw("1234"))
            u.roles = [models.UserRole(role_code=r) for r in roles]
            db.add(u); db.flush()
        db.commit()


def tok(c, u):
    r = c.post("/api/v1/auth/login", json={"user_id": u, "password": "x"}); assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def ev(c, h, t, payload):
    r = c.post("/api/v1/sync/push", headers=h, json={"events": [{"event_id": str(uuid.uuid4()), "device_id": "HHT-T", "event_type": t,
                                                                  "payload": payload, "local_ts": datetime.utcnow().isoformat()}]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


with TestClient(app) as c:
    setup()
    H, M, P = tok(c, "chn"), tok(c, "master"), tok(c, "pun")
    print("1. masters")
    b = c.post("/api/v1/blankets", headers=M, json={"plant_code": "CHN", "customer_code": "HMIL", "part_no": "WS-1", "blanket_no": "BL-9",
                                                    "po_number": "PO-123", "schedule_qty": 100}).json()
    check(b["id"], "blanket saved")
    c.post("/api/v1/subinv-rules", headers=M, json={"plant_code": "CHN", "customer_code": "HMIL", "part_no": "WS-1", "ok_subinv": "HMIL-FG", "reject_subinv": "REJ"})
    print("2. WMS freshness gate")
    r = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "CUSTOMER", "blanket_id": b["id"], "part_qty": 30, "qty": 3})
    check(r.status_code == 400 and "WMS" in r.text, "release blocked until WMS stock uploaded")
    csv = "LPN,PART_NO,QTY,SUBINVENTORY,PALLET_NO\nL1,WS-1,10,FG,CHN-P001\nL2,WS-1,10,FG,CHN-P001\nL3,WS-1,10,FG,CHN-P002\nL4,WS-1,10,FG,\nL5,WS-1,10,FG,\n"
    r = c.post("/api/v1/wms/upload", headers=H, files={"file": ("wms.csv", csv, "text/csv")}).json()
    check(r["new"] == 5, f"WMS upload 5 LPN ({r['batch_id']})")
    pal = c.get("/api/v1/pallets/CHN-P001", headers=H).json()
    check((pal.get("pallet") or pal).get("load_state") == "LOADED", "pallet with 2 LPN shows LOADED")
    print("3. release + reservation")
    r = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "CUSTOMER", "blanket_id": b["id"], "part_qty": 200, "qty": 3})
    check(r.status_code == 400 and "open" in r.text, "blanket schedule qty enforced")
    pk = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "CUSTOMER", "blanket_id": b["id"], "part_qty": 30, "qty": 3}).json()
    no = pk["picklist_no"]
    check(len(pk["reserved_lpns"]) == 3 and pk["so_number"] is None and pk["po_number"] == "PO-123", f"{no}: 3 LPN reserved, PO from blanket, no SO yet")
    print("4. internal moves + zone")
    r = c.post("/api/v1/moves", headers=H, json={"scanned": ["CHN-P001"], "to_zone": "FGWH"}).json()[0]
    check(r["ok"] and r["alerts"] and "YARD -> PRODUCTION" in r["alerts"][0], "Yard->FGWH skips Production: missed move recorded")
    r = c.post("/api/v1/moves", headers=H, json={"scanned": ["CHN-P005"], "to_zone": "YARD", "load": "LOADED"}).json()[0]
    check(not r["ok"] or "already" in r["message"], "Yard refuses loaded pallet")
    print("5. dock: pallet scan fetches all its LPNs; LPN scan fetches its pallet")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": no, "scanned": "CHN-P001"})
    check(e["status"] in ("APPLIED", "EXCEPTION") and "L1" in e["result"] and "L2" in e["result"], f"pallet scan -> {e['result']}")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": no, "scanned": "L3"})
    check(e["status"] == "EXCEPTION" and "MOVE_" in e["result"], "LPN scan fetched CHN-P002 + missed internal move alert")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": no, "scanned": "L4", "pallet": "CHN-P003"})
    check(e["status"] == "REJECTED" and "exceeds" in e["result"], "over-pick rejected")
    r = c.post(f"/api/v1/picklists/{no}/confirm", headers=H).json()
    check(r["status"] == "PDI_PENDING", "pick list control -> PDI_PENDING (no SO yet)")
    print("6. PDI with a reject")
    e = ev(c, H, "PDI_MARK", {"picklist_no": no, "scanned": "L5", "result": "OK"})
    check(e["status"] == "REJECTED" and "never dock-scanned" in e["result"], "LPN not dock-scanned caught at PDI")
    for l, res in (("L1", "OK"), ("L2", "REJECT"), ("L3", "OK")):
        c.post(f"/api/v1/picklists/{no}/pdi", headers=H, json={"scanned": l, "result": res, "remarks": "scratch" if res == "REJECT" else None})
    r = c.post(f"/api/v1/picklists/{no}/pdi-complete", headers=H).json()
    check(r["status"] == "OPEN" and r["rejected"] == ["L2"], "reject -> back to OPEN for replacement")
    l2 = c.get("/api/v1/lpns/L2", headers=H).json()
    check(l2["lpn"]["subinventory"] == "REJ" and l2["txns"][0]["status"] == "CONFIRMED" and l2["txns"][0]["ack_at"] and l2["txns"][0]["verified_at"],
          "rejected LPN -> REJ sub-inv, double confirmed")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": no, "scanned": "L4", "pallet": "CHN-P001"})
    check(e["status"] in ("APPLIED", "EXCEPTION"), f"replacement L4 linked to CHN-P001: {e['result']}")
    c.post(f"/api/v1/picklists/{no}/confirm", headers=H)
    c.post(f"/api/v1/picklists/{no}/pdi", headers=H, json={"scanned": "L4", "result": "OK"})
    r = c.post(f"/api/v1/picklists/{no}/pdi-complete", headers=H).json()
    check(r["status"] == "READY" and r["so_number"], f"PDI OK -> sub-inv confirmed -> SO {r['so_number']} -> READY")
    l1 = c.get("/api/v1/lpns/L1", headers=H).json()["lpn"]
    check(l1["subinventory"] == "HMIL-FG" and l1["txn_state"] == "CONFIRMED", "OK LPN moved to customer/part sub-inventory")
    bl = [x for x in c.get("/api/v1/blankets", headers=H).json() if x["id"] == b["id"]][0]
    check(bl["released_qty"] == 30 and bl["open_qty"] == 70, "blanket released 30, open 70")
    print("7. invoice + challan + gate")
    r = c.post(f"/api/v1/picklists/{no}/challan", headers=H).json()
    check(r["invoice_no"] and r["challan_no"], f"invoice {r['invoice_no']} fetched, challan {r['challan_no']}")
    c.post(f"/api/v1/picklists/{no}/approve", headers=H, json={"vehicle_no": "TN01AB1234"})
    k = c.get(f"/api/v1/picklists/{no}", headers=H).json()["picklist"]
    r = c.post(f"/api/v1/picklists/{no}/gate-out", headers=H, json={"scanned": k["gcs_no"]}).json()
    check(r["status"] == "DISPATCHED", "dispatched")
    p1 = c.get("/api/v1/pallets/CHN-P001", headers=H).json(); p1 = p1.get("pallet") or p1
    check(p1["status"] == "AT_CUSTOMER" and p1["load_state"] == "LOADED", "pallet AT_CUSTOMER and LOADED")
    pr = c.get(f"/print/challan/{no}?tok=" + H["Authorization"][7:])
    check(pr.status_code == 200 and "L1" in pr.text and r["invoice_no"] in pr.text, "challan print shows LPN lines + invoice")
    print("8. missed scans on return")
    r = c.post("/api/v1/slips", headers=H, json={"customer_code": "HMIL", "mode": "A", "pallets": ["CHN-P001", "CHN-P006"]}).json()
    check(any("MISSED SCAN (OUT_GATE)" in w for w in r["warnings"]), "returned pallet never dispatched -> missed OUT_GATE recorded")
    pk2 = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "CUSTOMER", "blanket_id": b["id"], "part_qty": 10, "qty": 1})
    check(pk2.status_code == 200, "second release ok")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": pk2.json()["picklist_no"], "scanned": "L5", "pallet": "CHN-P002"})
    check(e["status"] == "EXCEPTION" and "RETURN_SLIP" in e["result"] or "YARD_IN" in e["result"], f"pallet still at customer scanned at dock -> auto received: {e['result'][:90]}")
    print("9. other-plant material -> FGWH/Packing -> Yard -> empty return with e-way bill")
    r = c.post("/api/v1/plant-receipts", headers=H, json={"scanned": ["PUN-P001", "PUN-P002"], "zone": "FGWH", "ref": "PUN-ST-1"}).json()
    check(all(x["ok"] for x in r), "PUN pallets received at FGWH (LOADED, IN_WIP)")
    e = ev(c, H, "PALLET_SCAN_YARD", {"scanned": "PUN-P003", "accept_foreign": True})
    check(e["status"] == "REJECTED" and "FGWH" in e["result"], "loaded other-plant pallet refused at Yard")
    r = c.post("/api/v1/moves", headers=H, json={"scanned": ["PUN-P001"], "to_zone": "PACKING"}).json()[0]
    r = c.post("/api/v1/moves", headers=H, json={"scanned": ["PUN-P001", "PUN-P002"], "to_zone": "YARD"}).json()
    check(all(x["ok"] for x in r), "emptied -> Packing -> Yard (PUN-P002 skipped Packing -> recorded)")
    rt = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "EMPTY_RETURN", "to_plant": "PUN", "qty": 2}).json()
    rno = rt["picklist_no"]
    for pn in ("PUN-P001", "PUN-P002"):
        e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": rno, "scanned": pn})
        check(e["status"] in ("APPLIED", "EXCEPTION"), f"{pn} scanned on empty return")
    c.post(f"/api/v1/picklists/{rno}/confirm", headers=H)
    r = c.post(f"/api/v1/picklists/{rno}/challan", headers=H).json()
    check(r["challan_no"] and r["ewaybill_no"] and not r.get("so_number"), f"EBS challan {r['challan_no']} + e-way bill {r['ewaybill_no']}, no SO")
    c.post(f"/api/v1/picklists/{rno}/approve", headers=H, json={"vehicle_no": "TN02X1"})
    k = c.get(f"/api/v1/picklists/{rno}", headers=H).json()["picklist"]
    c.post(f"/api/v1/picklists/{rno}/gate-out", headers=H, json={"scanned": k["challan_no"]})
    e = ev(c, P, "PALLET_SCAN_YARD", {"scanned": "PUN-P001"})
    p = c.get("/api/v1/pallets/PUN-P001", headers=P).json(); p = p.get("pallet") or p
    check(p["status"] == "AVAILABLE" and p["load_state"] == "EMPTY" and p["zone"] == "YARD", "PUN yard receives its empty pallet")
    print("10. WMS re-upload protects in-process LPNs")
    r = c.post("/api/v1/wms/upload", headers=H, files={"file": ("w.csv", "LPN,PART_NO,QTY,SUBINVENTORY\nL5,WS-1,99,XX\nL9,WS-1,10,FG\n", "text/csv")}).json()
    l5 = c.get("/api/v1/lpns/L5", headers=H).json()["lpn"]
    check(r["protected"] == 1 and l5["qty"] == 10 and l5["status"] == "PICKED", "picked LPN protected from WMS overwrite")
    pk3 = c.post("/api/v1/picklists", headers=H, json={"dispatch_type": "CUSTOMER", "blanket_id": b["id"], "part_qty": 10, "qty": 1})
    check(pk3.status_code == 200 and pk3.json()["reserved_lpns"] == ["L9"], "L9 reserved")
    r = c.post("/api/v1/wms/upload", headers=H, files={"file": ("w.csv", "LPN,PART_NO,QTY,SUBINVENTORY\nL10,WS-1,10,FG\n", "text/csv")}).json()
    l9 = c.get("/api/v1/lpns/L9", headers=H).json()["lpn"]
    check(r["missing"] >= 1 and l9["status"] == "RESERVED" and l9["wms_missing"], "reserved LPN absent from WMS -> kept reserved + flagged")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": pk3.json()["picklist_no"], "scanned": "L9", "pallet": "CHN-P007"})
    check(e["status"] == "REJECTED" and "WMS" in e["result"], "flagged LPN blocked at dock")
    res = c.get("/api/v1/reservations", headers=H).json()
    check(len(res) >= 1, f"reservation control lists {len(res)} pick list(s)")
    print("11. missed-scan register")
    ms = c.get("/api/v1/scan-misses", headers=H).json()
    pts = sorted({m["missed_point"] for m in ms})
    check(len(ms) >= 5, f"{len(ms)} missed scans recorded: {pts}")
    r = c.post(f"/api/v1/scan-misses/{ms[0]['id']}/resolve", headers=H, json={"resolution": "briefed security"}).json()
    check(r["resolved"], "missed scan resolved")
    z = c.get("/api/v1/zones", headers=H).json()
    check("FGWH" in z["zones"], f"zone view: {z['zones']}")
print(f"\nALL {ok_n} CHECKS PASSED")
os.remove(DB) if os.path.exists(DB) and not os.getenv("KEEP") else print("db kept:", DB)
