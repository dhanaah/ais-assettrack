"""Shared masters from the Dispatch Planning Bench (server 1.37.0). Run:
    PYTHONPATH=. python3 tests/bench_masters_check.py
Developed by DT"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from testdb import fresh_db_url  # noqa: E402
os.environ["PALLET_DB_URL"] = fresh_db_url("bmast")
os.environ["PALLET_INTEGRATION_MODE"] = "STUB"
os.environ["PALLET_BENCH_SCHEDULER"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app.main import app
from app import models, bench, benchmasters
from app.db import SessionLocal

FAILS = []
def check(ok, what):
    print(("  ok - " if ok else "FAIL: ") + what)
    if not ok: FAILS.append(what)

SHARED = {"plants": [{"code": "AAC", "name": "Chennai", "org_code": "CL1", "active": 1}, {"code": "ASP", "name": "Pune", "org_code": "", "active": 1}],
          "customers": [{"code": "HMIL", "name": "Hyundai Motor India", "oracle_cust_no": "10234", "ctype": "OEM", "gstin": "33AAACH1234B1Z9",
                         "address": "Irungattukottai", "city": "Chennai", "state": "TN", "active": 1, "plants": ["AAC"]},
                        {"code": "MSIL", "name": "Maruti", "oracle_cust_no": "", "active": 1, "plants": ["AAC", "ASP"]}]}
def fetch(path):
    if path.startswith("/api/masters/shared"): return SHARED
    if path.startswith("/api/dispatches/recent"):
        return {"dispatches": [{"id": 77, "trip_id": 5, "customer_code": "HMIL", "ais_plant": "AAC", "dispatch_status": "Acknowledged", "sent_at": ""}]}
    if path.startswith("/api/picks"): return {"picks": [{"picked_lpn": "P1.P100001", "item_code": "AIS-1", "qty": 10, "pdi_status": "Pending"}]}
    raise RuntimeError(path)

app.router.on_startup.clear() if hasattr(app.router, "on_startup") else None
with TestClient(app):
    with SessionLocal() as db:
        db.add(models.Plant(code="AAC", name="old name", ebs_org_id=None)); db.flush()
        db.add(models.Customer(code="HMIL", name="Hyundai old", plant_code="AAC", email_to="stores@hmil.com", holding_limit_days=45)); db.commit()
        r = bench.pull(db, fetch=fetch)
        ms = bench.status()["masters"]; print(ms)
        check(ms["ok"] and ms["customers"] == 1 and ms["missing_oracle_no"] == ["MSIL"], "masters copied; customer without Oracle no. listed")
        p = db.get(models.Plant, "AAC"); check(p.name == "Chennai" and p.from_bench and p.ebs_org_id == "CL1", "plant name from Bench, org filled once")
        check(db.get(models.Plant, "ASP") is not None, "new Bench plant created")
        c = db.query(models.Customer).filter_by(code="10234", plant_code="AAC").first()
        check(c is not None and c.bench_code == "HMIL" and c.name == "Hyundai Motor India" and c.gstin == "33AAACH1234B1Z9" and c.address == "Irungattukottai",
              "old HMIL row re-coded to Oracle no. with Bench fields")
        check(c.email_to == "stores@hmil.com" and c.holding_limit_days == 45, "AssetTrack-only fields kept")
        check(not db.query(models.Customer).filter_by(code="HMIL").first(), "no duplicate under the short code")
        pk = db.query(models.PickList).filter_by(ext_ref="77").first()
        check(pk is not None and pk.customer_code == "10234", "Bench pick list gets the Oracle customer no. automatically")
        # edit lock
        vals = {"name": "hacked", "email_to": "new@x.com", "active": False}
        dropped = benchmasters.strip_locked(c, vals, "customers")
        check(set(dropped) == {"name", "active"} and vals == {"email_to": "new@x.com"}, "Bench fields dropped from an AssetTrack edit")
        # second pull: idempotent
        bench.pull(db, fetch=fetch); check(bench.status()["masters"]["changed"] == 0, "second pull: nothing changed")
        # Bench renames
        SHARED["customers"][0]["name"] = "HMIL Ltd"; bench.pull(db, fetch=fetch)
        db.expire_all(); check(db.query(models.Customer).filter_by(code="10234").first().name == "HMIL Ltd", "Bench rename flows to AssetTrack")
        # Bench unreachable for masters: dispatch pull still runs
        def f2(path):
            if path.startswith("/api/masters/shared"): raise RuntimeError("old Bench")
            return fetch(path)
        r = bench.pull(db, fetch=f2); check(bench.status()["masters"]["ok"] is False and r["updated"] >= 0, "old Bench without shared masters: pull continues")
        # removed in the Bench -> released (lock off, can be deleted); partial list -> nothing released (DT, 30-Oct)
        SHARED["customers"].append({"code": "TATA", "name": "Tata", "oracle_cust_no": "20001", "active": 1, "plants": ["AAC", "ASP"]})
        bench.pull(db, fetch=fetch); db.expire_all()
        check(all(x.from_bench for x in db.query(models.Customer).filter_by(code="20001").all()), "new Bench customer locked at both plants")
        SHARED["customers"][-1]["plants"] = ["AAC"]; SHARED["complete"] = False
        bench.pull(db, fetch=fetch); db.expire_all()
        check(db.query(models.Customer).filter_by(code="20001", plant_code="ASP").first().from_bench, "partly read Bench list: nothing released")
        SHARED["complete"] = True
        bench.pull(db, fetch=fetch); db.expire_all()
        a = db.query(models.Customer).filter_by(code="20001", plant_code="ASP").first(); b = db.query(models.Customer).filter_by(code="20001", plant_code="AAC").first()
        check(not a.from_bench and "can be deleted" in (a.notes or "") and b.from_bench, "customer dropped for ASP in the Bench: ASP row released, AAC row still locked")
        check(bench.status()["masters"]["released"] == 1, "status counts the released record")
        SHARED["plants"] = [x for x in SHARED["plants"] if x["code"] != "ASP"]
        bench.pull(db, fetch=fetch); db.expire_all()
        check(not db.get(models.Plant, "ASP").from_bench and db.get(models.Plant, "AAC").from_bench, "plant removed in the Bench: released")
print("\nALL BENCH MASTER CHECKS PASSED" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
