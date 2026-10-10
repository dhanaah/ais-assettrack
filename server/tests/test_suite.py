"""pytest entry: runs the end-to-end flow script (80+ checks) in a clean SQLite database. Developed by DT"""
import os, subprocess, sys, pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_end_to_end_flow():
    env = os.environ | {"PYTHONPATH": str(HERE.parent), "PALLET_BENCH_SCHEDULER": "0", "PALLET_DB_URL": ""}
    env.pop("PALLET_DB_URL")
    r = subprocess.run([sys.executable, str(HERE / "test_parts_flow.py")], cwd=HERE.parent, env=env, capture_output=True, text=True, timeout=600)
    sys.stdout.write(r.stdout[-4000:])
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "CHECKS PASSED" in r.stdout


def test_health_and_dashboard():
    import tempfile, uuid
    os.environ["PALLET_DB_URL"] = f"sqlite:///{tempfile.gettempdir()}/at_pytest_{uuid.uuid4().hex[:6]}.db"
    os.environ["PALLET_BENCH_SCHEDULER"] = "0"
    sys.path.insert(0, str(HERE.parent))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        h = c.get("/api/v1/health").json()
        assert h["db"] == "ok" and h["version"]
        t = c.post("/api/v1/auth/login", json={"user_id": "admin", "password": "Admin@123"}).json()["token"]
        H = {"Authorization": "Bearer " + t}
        assert c.get("/api/v1/dashboard", headers=H).status_code == 200
        assert c.get("/api/v1/reports/export/pallets.xlsx", headers=H).status_code == 200
        assert c.get("/api/v1/reminders", headers=H).status_code == 200
        r = c.post("/api/v1/auth/login", json={"user_id": "admin", "password": "Admin@123", "device_id": "D1", "app_version": "0.9.0"})
        assert r.status_code == 426, "old HHT app must be told to update"
