"""End-to-end regression for v1.4: WMS stock, blanket, LPN<->pallet dock scan, PDI + double-confirmed sub-inventory
transfer, SO after PDI, invoice + challan, loaded/empty, internal moves, other-plant receipt, empty return + e-way bill,
missed-scan detection. Run:  python -m tests.test_parts_flow   (from server/, uses a temp SQLite db)"""
import os, sys, uuid, tempfile
from datetime import datetime, timedelta
DB = os.getenv("KEEP") or os.path.join(tempfile.gettempdir(), f"at_test_{uuid.uuid4().hex[:6]}.db")
os.environ["PALLET_DB_URL"] = f"sqlite:///{DB}"
os.environ["PALLET_INTEGRATION_MODE"] = "STUB"
os.environ["PALLET_BENCH_SCHEDULER"] = "0"
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


def tok(c, u, hht=True):
    r = c.post("/api/v1/auth/login", json={"user_id": u, "password": "x"}); assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    if hht:
        h |= {"X-Device": "HHT", "X-Device-Id": "HHT-TEST"}
    return h


def ev(c, h, t, payload):
    r = c.post("/api/v1/sync/push", headers=h, json={"events": [{"event_id": str(uuid.uuid4()), "device_id": "HHT-T", "event_type": t,
                                                                  "payload": payload, "local_ts": datetime.utcnow().isoformat()}]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


with TestClient(app) as c:
    setup()
    H, M, P = tok(c, "chn"), tok(c, "master", hht=False), tok(c, "pun")
    W = tok(c, "chn", hht=False)          # same user on the web
    print("0. HHT-only policy")
    r = c.post("/api/v1/sync/push", headers=W, json={"events": []})
    check(r.status_code == 403 and "HHT" in r.text, "web cannot push scans")
    r = c.post("/api/v1/moves", headers=W, json={"scanned": ["CHN-P001"], "to_zone": "PRODUCTION"})
    check(r.status_code == 403, "web cannot move pallets")
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
    print("10b. customer API + signed QR label")
    with SessionLocal() as db:
        from app.security import hash_pw as _h
        cu = db.query(models.Customer).filter_by(code="HMIL", plant_code="CHN").first(); cu.api_key_hash = _h("ais_testkey_123456"); cu.api_key_prefix = "ais_test"; db.commit()
    K = {"X-API-Key": "ais_testkey_123456"}
    r = c.post("/api/ext/v1/return-slip", headers=K, json={"pallets": ["CHN-P001"], "vehicle_no": "TN 09 AB 1111", "customer_challan_no": "DC-77"}).json()
    check(r["qr_payload"].startswith("AIS1|RS|") and r["label_url"], f"customer slip {r['slip_no']} QR {r['qr_payload']}")
    lab = c.get(r["label_url"]); check(lab.status_code == 200 and "<svg" in lab.text and "TN09AB1111" in lab.text and "PALLET RETURN SLIP" in lab.text, "A4 return slip prints with signed QR")
    check(c.get(r["label_url"][:-3] + "XXX").status_code == 403, "label link cannot be guessed")
    bad = r["qr_payload"].replace("TN09AB1111", "TN09AB9999")
    g = c.post(f"/api/v1/slips/{r['slip_no']}/gate-in", headers=H, json={"qr": bad})
    check(g.status_code == 400 and "check code" in g.text, "altered label rejected at gate")
    g = c.post(f"/api/v1/slips/{r['slip_no']}/gate-in", headers=H, json={"qr": r["qr_payload"], "vehicle_no": "TN09AB1111"})
    check(g.status_code == 200 and g.json()["status"] == "IN_GATE", "genuine label accepted at IN gate")
    print("11. missed-scan register")
    ms = c.get("/api/v1/scan-misses", headers=H).json()
    pts = sorted({m["missed_point"] for m in ms})
    check(len(ms) >= 5, f"{len(ms)} missed scans recorded: {pts}")
    r = c.post(f"/api/v1/scan-misses/{ms[0]['id']}/resolve", headers=H, json={"resolution": "briefed security"}).json()
    check(r["resolved"], "missed scan resolved")
    pp = c.get("/api/v1/reports/plant-position", headers=W).json()
    check(pp["summary"]["own_total"] == 7 and pp["summary"]["at_customers"] >= 1, f"plant position: {pp['summary']}")
    lv = c.get("/api/v1/reports/live", headers=W).json()
    check(len(lv) > 10, f"live feed {len(lv)} rows")
    print("12. user access by central admin only")
    r = c.post("/api/v1/users", headers=W, json={"user_id": "x1", "full_name": "x", "plant_code": "CHN", "roles": ["YARD"], "password": "Abc@1234"})
    check(r.status_code == 403, "plant user cannot create users")
    with SessionLocal() as db:
        u = models.User(user_id="cadm", full_name="central", plant_code=None, password_hash=hash_pw("x"), must_change_pw=False)
        u.roles = [models.UserRole(role_code="CADMIN")]; db.add(u); db.commit()
    A = tok(c, "cadm", hht=False)
    r = c.post("/api/v1/users", headers=A, json={"user_id": "yard1", "full_name": "Yard op", "plant_code": "CHN", "roles": ["YARD"],
                                               "password": "Abc@1234", "perms": ["YARD_SCAN", "MOVE_TO_PRODUCTION"]})
    check(r.status_code == 200, "central admin creates user with exact movement rights")
    with SessionLocal() as db:
        u = db.query(models.User).filter_by(user_id="yard1").first(); u.must_change_pw = False; u.password_hash = hash_pw("x"); db.commit()
    Y = tok(c, "yard1")
    e = ev(c, Y, "PALLET_MOVE", {"scanned": "CHN-P007", "to_zone": "PRODUCTION"})
    check(e["status"] in ("APPLIED", "EXCEPTION"), "allowed route Yard -> Production")
    e = ev(c, Y, "PALLET_MOVE", {"scanned": "CHN-P007", "to_zone": "FGWH"})
    check(e["status"] == "REJECTED" and "MOVE_TO_FGWH" in e["result"], "route not granted -> rejected")
    print("13. Dispatch Planning Bench pull (all customers)")
    from app import bench
    r = c.post("/api/v1/integrations/dispatch-bench", headers=A, json={"bench_enabled": False, "bench_url": "http://bench:8765", "bench_user": "svc",
                                                                   "bench_password": "x", "bench_plant": "CHN", "bench_customer_map": "HVF1=HMIL"})
    check(r.status_code == 200, "bench settings saved by central admin")
    fake = {"/api/dispatches/recent?limit=300": {"dispatches": [{"id": 501, "trip_id": 77, "plant": "HVF1", "vehicle": "TN 22 X 9", "dispatch_status": "Completed", "sent_at": datetime.now().isoformat()},
                                                                   {"id": 502, "trip_id": 78, "customer_code": "MSIL1", "vehicle": "HR55A1", "dispatch_status": "Completed", "sent_at": datetime.now().isoformat()}]},
            "/api/picks?dispatch_id=502": {"picks": []},
            "/api/picks?dispatch_id=501": {"picks": [{"picked_lpn": "BL1", "item_code": "WS-9", "qty": 20, "sub_inv": "HMIL-FG"},
                                                      {"picked_lpn": "BL2", "item_code": "DR-3", "qty": 30, "sub_inv": "HMIL-FG"}]}}
    with SessionLocal() as db:
        res = bench.pull(db, fetch=lambda path: fake[path])
    check(res["created"] == 2 and res["lpns"] == 2, f"bench dispatches 501/502 -> pick lists DB-CHN-501 (2 LPN) and DB-CHN-502 ({res})")
    k2 = c.get("/api/v1/picklists/DB-CHN-502", headers=W).json()["picklist"]
    check(k2["customer_code"] == "MSIL1" and k2["source"] == "DISPATCH_BENCH", "non-Hyundai customer taken from the Bench dispatch")
    with SessionLocal() as db:
        res2 = bench.pull(db, fetch=lambda path: fake[path])
    check(res2["created"] == 0, "second pull updates, no duplicate pick lists")
    check(c.get("/api/v1/integrations/hmil-bench", headers=A).status_code == 200, "old /hmil-bench address still answers")
    pk = c.get("/api/v1/picklists/DB-CHN-501", headers=W).json()["picklist"]
    check(pk["customer_code"] == "HMIL" and pk["part_qty"] == 50 and pk["vehicle_no"] == "TN22X9", "customer map, qty and vehicle from Bench")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": "DB-CHN-501", "scanned": "L10", "pallet": "CHN-P004"})
    check(e["status"] == "REJECTED" and "not on Dispatch Bench trip" in e["result"], "LPN not on the Bench trip refused")
    e1 = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": "DB-CHN-501", "scanned": "BL1", "pallet": "CHN-P004"})
    e2 = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": "DB-CHN-501", "scanned": "BL2", "pallet": "CHN-P004"})
    check(e1["status"] != "REJECTED" and e2["status"] != "REJECTED", f"2 Bench LPN bound to one pallet: {e2['result'][:60]}")
    r = c.post("/api/v1/picklists/DB-CHN-501/confirm", headers=H).json()
    check(r["status"] == "READY", "Bench trip skips AssetTrack PDI/SO -> READY")
    r = c.post("/api/v1/picklists/DB-CHN-501/challan", headers=W).json()
    check(r.get("challan_no"), f"challan {r.get('challan_no')} without EBS invoice wait")
    z = c.get("/api/v1/zones", headers=H).json()
    check("FGWH" in z["zones"], f"zone view: {z['zones']}")
    print("14. Empty pallet return loaded at the Pallet Yard")
    with SessionLocal() as db:
        for pn, zone in (("PUN-P010", "YARD"), ("PUN-P011", "YARD"), ("PUN-P012", "PACKING")):
            db.add(models.Pallet(pallet_no=pn, home_plant="PUN", location_plant="CHN", status="HELD", zone=zone, load_state="EMPTY"))
        db.commit()
    r = c.post("/api/v1/picklists/yard-return", headers=W, json={"to_plant": "PUN"})
    check(r.status_code == 403, "yard loading only from the HHT")
    o = c.get("/api/v1/picklists/yard-return/options", headers=H).json()
    check(any(x["plant"] == "PUN" and x["pallets"] >= 3 for x in o), f"owner plants with pallets held here: {o}")
    k = c.post("/api/v1/picklists/yard-return", headers=H, json={"to_plant": "PUN", "vehicle_no": "tn 09 y 7"}).json()
    yno = k["picklist_no"]
    check(k["load_point"] == "YARD" and k["vehicle_no"] == "TN09Y7" and k["qty"] == 0, f"{yno} started at Yard, open quantity")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": yno, "scanned": "CHN-P005"})
    check(e["status"] == "REJECTED" and "belongs to CHN" in e["result"], "own pallet refused - only the owner plant's pallets")
    for pn in ("PUN-P010", "PUN-P011"):
        e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": yno, "scanned": pn})
        check(e["status"] == "APPLIED", f"{pn} loaded at Yard")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": yno, "scanned": "PUN-P012"})
    check(e["status"] == "EXCEPTION" and "MOVE_PACKING_YARD" in e["result"], f"pallet still shown in Packing -> loaded, missed move recorded: {e['result'][:70]}")
    pull = c.get("/api/v1/sync/pull", headers=H).json()
    check(any(x["picklist_no"] == yno and x["load_point"] == "YARD" for x in pull["picklists"]), "HHT gets the Yard loading list")
    r = c.post(f"/api/v1/picklists/{yno}/confirm", headers=H).json()
    check(r["status"] == "CHALLANED" and r["qty"] == 3 and r["challan_no"] and r["ewaybill_no"], f"Finish loading -> challan {r.get('challan_no')} + e-way bill for 3 pallets")
    p10 = c.get("/api/v1/pallets/PUN-P010", headers=H).json(); p10 = p10.get("pallet") or p10
    check(p10["status"] == "ALLOCATED" and p10["challan_ref"] == r["challan_no"], "pallet carries the challan")
    print("15. sync hardening")
    hb = ev(c, H, "HEARTBEAT", {"pending": 3})
    with SessionLocal() as db:
        n_hb = db.query(models.Event).filter_by(event_type="HEARTBEAT").count()
        dev = db.query(models.Device).filter_by(device_id="HHT-T").first()
    check(hb["status"] == "APPLIED" and n_hb == 0 and dev and dev.pending_reported == 3, "heartbeat updates the device but is not stored as an event")
    eid = str(uuid.uuid4())
    body = {"events": [{"event_id": eid, "device_id": "HHT-T", "event_type": "DAMAGE_MARK", "payload": {"scanned": "CHN-P006"}, "local_ts": datetime.utcnow().isoformat()}]}
    r1 = c.post("/api/v1/sync/push", headers=H, json=body).json()["results"][0]
    r2 = c.post("/api/v1/sync/push", headers=H, json=body).json()["results"][0]
    check(r2.get("duplicate") and r2["status"] == r1["status"], "same event sent twice -> answered from the first result")
    with SessionLocal() as db:
        l = db.get(models.Lpn, "BL1"); l.status = "DISPATCHED"; db.commit()
    d = c.get("/api/v1/sync/pull", headers=H, params={"since": (datetime.utcnow() - timedelta(minutes=5)).isoformat()}).json()
    check(any(x["lpn"] == "BL1" and x["status"] == "DISPATCHED" for x in d["lpns"]), "delta pull reports the LPN that left the live statuses")
    f = c.get("/api/v1/sync/pull", headers=H).json()
    check(not any(x["lpn"] == "BL1" for x in f["lpns"]), "full pull keeps only live LPNs")
    from app.routers.sync import purge_old_events
    with SessionLocal() as db:
        db.query(models.Event).filter_by(event_id=eid).update({"received_ts": datetime.utcnow() - timedelta(days=800)}); db.commit()
        n = purge_old_events(db); db.commit()
    check(n >= 1, f"event purge removed {n} old event(s)")
    from app import config
    check(config.JWT_SECRET != config.LEGACY_SECRET or os.getenv("PALLET_JWT_SECRET"), "server secret is not the public default")
    print("16. AIS pallet QR label (JSON) + auto registration")
    QR = '{"uniquePalletID":"AIS-CHN-ANF-00001-0000001","ownerPlant":"CHN","palletType":"ANF","typeSerial":"00001","globalSerial":"0000001","mfgDate":"2026-08-27"}'
    from app import services
    q = services.parse_pallet_qr(QR)
    check(q and q["pallet_no"] == "AIS-CHN-ANF-00001-0000001" and q["owner_plant"] == "CHN" and q["pallet_type"] == "ANF", "QR JSON parsed")
    e = ev(c, H, "PALLET_SCAN_YARD", {"scanned": QR})
    check(e["status"] == "EXCEPTION" and "registered" in e["result"], f"first scan registers the pallet: {e['result'][:70]}")
    r = c.get("/api/v1/pallets/AIS-CHN-ANF-00001-0000001", headers=H).json(); pal = r.get("pallet") or r
    check(pal["status"] == "AVAILABLE" and pal["pallet_type"] == "ANF" and pal["zone"] == "YARD" and pal["home_plant"] == "CHN", "new pallet AVAILABLE in Yard with type from QR")
    e = ev(c, H, "PALLET_SCAN_YARD", {"scanned": QR})
    check(e["status"] in ("APPLIED", "EXCEPTION") and "registered" not in e["result"], "second scan is a normal yard scan")
    r = c.get("/api/v1/pallets/" + QR.replace("{", "%7B").replace("}", "%7D").replace('"', "%22"), headers=H)
    check(r.status_code == 200, "lookup by scanning the QR works")
    QR2 = QR.replace("CHN", "PUN").replace("0000001", "0000002")
    e = ev(c, H, "PALLET_SCAN_YARD", {"scanned": QR2, "accept_foreign": True})
    r = c.get("/api/v1/pallets/AIS-PUN-ANF-00001-0000002", headers=H).json(); pal = r.get("pallet") or r
    check(pal["home_plant"] == "PUN" and pal["status"] == "HELD" and pal["location_plant"] == "CHN", "other plant's new pallet registered as HELD here")
    QR3 = QR.replace('"CHN"', '"ZZZ"').replace("AIS-CHN", "AIS-ZZZ")
    e = ev(c, H, "PALLET_SCAN_YARD", {"scanned": QR3})
    check(e["status"] == "EXCEPTION" and "not in Plant master" in e["result"], "unknown owner plant -> quarantined with reason")
    e = ev(c, H, "PALLET_MOVE", {"scanned": QR, "to_zone": "PRODUCTION"})
    check(e["status"] in ("APPLIED", "EXCEPTION"), "internal move by scanning the QR")
    print("17. GCS inbox -> loading sheet -> finish loading (challan) -> GCS QR -> OUT gate")
    from app import gcs as gcssvc
    with SessionLocal() as db:
        gcssvc.save_settings(db, {"gcs_enabled": False, "gcs_plant": "CHN", "gcs_host": "ftp.test"}); db.commit()
        for i in (31, 32, 33):
            db.add(models.Pallet(pallet_no=f"CHN-P0{i}", home_plant="CHN", location_plant="CHN", status="AVAILABLE", zone="FGWH", load_state="LOADED"))
        db.commit()
    files = [("GCS-CHN-7781.json", b'{"GCS No":"GCS-CHN-7781","Vehicle":"TN 09 AB 1234","Customer Code":"HMIL","Invoice No":"INV/26/0091","Invoice Date":"2026-10-10","Qty":60,"Item":"WS-1","SO No":"SO-9981"}'),
             ("batch.csv", b"gcs_no,vehicle,customer,invoice no,PDI By,PDI Login,Shift Supervisor,Supervisor Login\nGCS-CHN-7782,KA01ZZ9999,MSIL1,INV/26/0092,Ravi Kumar,ravi.k,Suresh Babu,suresh.b\n"),
             ("gatepass_7783.txt", b"GATE PASS\nGCS No : GCS-CHN-7783\nVehicle : MH 12 CD 4455\nConsignee code : HMIL\nInvoice No : INV/26/0093\n")]
    with SessionLocal() as db:
        res = gcssvc.pull(db, fetch=lambda: files)
    check(res["created"] == 3, f"3 GCS files (json / csv / text) -> 3 loading sheets: {res}")
    k = c.get("/api/v1/picklists/GCS-CHN-GCSCHN7781", headers=W).json()["picklist"]
    check(k["vehicle_no"] == "TN09AB1234" and k["invoice_no"] == "INV/26/0091" and k["customer_code"] == "HMIL" and k["source"] == "GCS", "loading sheet carries vehicle, invoice, customer from the GCS file")
    k2 = c.get("/api/v1/picklists/GCS-CHN-GCSCHN7782", headers=W).json()["picklist"]
    check(k2["pdi_sign"] == "Ravi Kumar (ravi.k)" and k2["supervisor_sign"] == "Suresh Babu (suresh.b)", "PDI and shift supervisor (Bench logins) taken from the CSV")
    pr2 = c.get("/api/v1/picklists/GCS-CHN-GCSCHN7782/gcs.pdf", headers=W)
    t2 = "\n".join(pg.extract_text() for pg in __import__('pypdf').PdfReader(__import__('io').BytesIO(pr2.content)).pages)
    check("Ravi Kumar" in t2 and "Suresh Babu" in t2 and "SHIFT SUPERVISOR" in t2, "PDF shows PDI and Shift Supervisor sign boxes with the Bench names")
    with SessionLocal() as db:
        res = gcssvc.pull(db, fetch=lambda: files)
    check(res["created"] == 0 and res["updated"] == 3, "same files again -> updated, no duplicates")
    r = c.post("/api/v1/picklists/gcs-open", headers=H, json={"gcs_no": "GCS-CHN-7781"}).json()
    check(r["picklist_no"] == "GCS-CHN-GCSCHN7781", "HHT opens the loading sheet by GCS number")
    r = c.post("/api/v1/picklists/gcs-open", headers=H, json={"gcs_no": "GCS-CHN-9999"})
    check(r.status_code == 404, "unknown GCS asks for manual details")
    r = c.post("/api/v1/picklists/gcs-open", headers=H, json={"gcs_no": "GCS-CHN-9999", "vehicle_no": "tn 1 x 1", "customer_code": "HMIL"}).json()
    check(r["gcs_no"] == "GCS-CHN-9999" and r["vehicle_no"] == "TN1X1", "manual GCS opened from the HHT")
    no = "GCS-CHN-GCSCHN7781"
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": no, "scanned": "CHN-P031"})
    check(e["status"] in ("APPLIED", "EXCEPTION"), f"pallet tag loaded on the GCS: {e['result'][:60]}")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": no, "scanned": "PC-000123", "pallet": "CHN-P032"})
    check(e["status"] in ("APPLIED", "EXCEPTION") and "PC-000123" in e["result"], f"unknown part card + pallet loaded: {e['result'][:60]}")
    e = ev(c, H, "PALLET_SCAN_DOCK", {"picklist_no": no, "scanned": "CHN-P033"})
    r = c.post(f"/api/v1/picklists/{no}/confirm", headers=H).json()
    check(r["status"] == "APPROVED" and r["challan_no"] and r["gcs_qr"].startswith("AIS1|GCS|GCS-CHN-7781|CHN|HMIL|TN09AB1234|3|"), f"finish loading -> challan {r.get('challan_no')} + signed GCS QR, ready for the gate")
    qr = r["gcs_qr"]
    pr = c.get(f"/print/gcs/{no}?tok=" + W["Authorization"].split()[1])
    check(pr.status_code == 200 and "GCS-CHN-7781" in pr.text and "TN09AB1234" in pr.text, "GCS print page with QR")
    bad = qr[:-8] + "DEADBEEF"
    r = c.post("/api/v1/gate-out/scan", headers=H, json={"scanned": bad})
    check(r.status_code == 400 and "HOLD" in r.text, "forged GCS QR refused at the gate")
    r = c.post("/api/v1/gate-out/scan", headers=H, json={"scanned": qr}).json()
    check(r["status"] == "DISPATCHED", "OUT gate: GCS QR -> dispatched")
    p31 = c.get("/api/v1/pallets/CHN-P031", headers=H).json(); p31 = p31.get("pallet") or p31
    check(p31["status"] == "AT_CUSTOMER" and p31["customer_code"] == "HMIL" and p31["challan_ref"] == r["challan_no"], "pallets AT_CUSTOMER with the challan")
    with SessionLocal() as db:
        l = db.get(models.Lpn, "PC-000123")
    check(l and l.status == "DISPATCHED", "part card marked dispatched")
    print("18. GCS PDF: QR + challan + security sign; auto print setting")
    with SessionLocal() as db:
        pl = db.get(models.Plant, "CHN"); pl.gcs_print_mode = "RAW9100"; pl.gcs_printer = "127.0.0.1:1"; db.commit()
    r = c.get(f"/api/v1/picklists/{no}/gcs.pdf", headers=W)
    check(r.status_code == 200 and r.content[:4] == b"%PDF", "GCS PDF downloads")
    from pypdf import PdfReader
    import io as _io
    text = "\n".join(pg.extract_text() for pg in PdfReader(_io.BytesIO(r.content)).pages)
    check("GCS-CHN-7781" in text and "CHN/00003" in text and "chn" in text and "SECURITY" in text, "PDF carries GCS no, challan no and the security sign with login ID")
    pr = c.post(f"/api/v1/picklists/{no}/gcs-print", headers=W).json()
    check(pr["pdf"].startswith("GCS_") and "queued" in pr["print"], f"reprint builds the PDF and queues it on the plant printer: {pr}")
    import time as _t; _t.sleep(1.5)
    with SessionLocal() as db:
        from app.integration import IntegrationLog
        lg = db.query(IntegrationLog).filter_by(system="PRINT").order_by(IntegrationLog.id.desc()).first()
    check(lg is not None and not lg.ok, "print attempt logged (test printer unreachable -> failure recorded, not hidden)")
print(f"\nALL {ok_n} CHECKS PASSED")
os.remove(DB) if os.path.exists(DB) and not os.getenv("KEEP") else print("db kept:", DB)
