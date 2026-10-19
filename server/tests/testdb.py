"""Test database for the check scripts: a new SQLite file (default), or a new SQL Server database when
PALLET_TEST_MSSQL is set, e.g.
  PALLET_TEST_MSSQL="mssql+pyodbc://sa:Pass@localhost:1433/{db}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
The same checks then prove the server works on SQL Server exactly as on SQLite. Developed by DT"""
import os
import tempfile
import uuid


def fresh_db_url(tag: str) -> str:
    base = os.getenv("PALLET_TEST_MSSQL", "").strip()
    name = f"at_{tag}_{uuid.uuid4().hex[:6]}"
    if not base:
        return "sqlite:///" + os.path.join(tempfile.gettempdir(), name + ".db")
    from sqlalchemy import create_engine, text
    eng = create_engine(base.format(db="master"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:                  # same settings as sql/create_db.sql
        c.execute(text(f"CREATE DATABASE [{name}]"))
        c.execute(text(f"ALTER DATABASE [{name}] SET READ_COMMITTED_SNAPSHOT ON"))
        c.execute(text(f"ALTER DATABASE [{name}] SET ALLOW_SNAPSHOT_ISOLATION ON"))
    eng.dispose()
    return base.format(db=name)


def bench_trip_for(db, gcs_picklist: str, trip_no: str | None = None):
    """Test helper: the Dispatch Bench PDI check sheet for a GCS - a Bench trip carrying exactly the GCS part cards,
    then the automatic link (every GCS card on the trip). Returns the trip number."""
    from app import models, gcs
    g = db.get(models.PickList, gcs_picklist)
    trip_no = trip_no or f"DB-{g.plant_code}-T{gcs_picklist[-6:]}"
    db.add(models.PickList(picklist_no=trip_no, plant_code=g.plant_code, customer_code=g.customer_code, dispatch_type=g.dispatch_type or "CUSTOMER",
                           source="DISPATCH_BENCH", ext_ref=trip_no, qty=0, part_qty=0, status="OPEN", vehicle_no=g.vehicle_no)); db.flush()
    for x in db.query(models.GcsLpn).filter_by(picklist_no=gcs_picklist).all():
        db.add(models.BenchTripCard(trip_no=trip_no, lpn_no=x.lpn_no, part_no=x.part_no, qty=x.qty))
    db.flush()
    linked = gcs.link_bench_trip(db, g)
    db.commit()
    assert linked == trip_no, f"test Bench trip not linked to {gcs_picklist}"
    return trip_no
