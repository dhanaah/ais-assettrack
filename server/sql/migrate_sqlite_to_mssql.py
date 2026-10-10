"""Copy the pilot SQLite database into SQL Server (one time, before go-live). Developed by DT
Usage (on the pilot PC, server stopped):
  set PALLET_DB_URL=mssql+pyodbc://...            (the target, as in settings.env)
  python sql\migrate_sqlite_to_mssql.py pallet.db
Tables are created on the target if missing; existing target rows are NOT deleted (run on an empty database)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sqlalchemy import create_engine, text
from app.db import Base, engine as target   # target = PALLET_DB_URL
from app import models, integration, reminders  # noqa: register all tables

src_path = sys.argv[1] if len(sys.argv) > 1 else "pallet.db"
if target.dialect.name == "sqlite":
    sys.exit("PALLET_DB_URL must point to SQL Server (target), e.g. set PALLET_DB_URL=mssql+pyodbc://...")
src = create_engine(f"sqlite:///{src_path}")
Base.metadata.create_all(bind=target)
with src.connect() as s, target.begin() as t:
    for table in Base.metadata.sorted_tables:
        rows = [dict(r._mapping) for r in s.execute(table.select())]
        if not rows:
            continue
        if target.dialect.name == "mssql" and any(c.autoincrement is True and c.primary_key for c in table.columns):
            t.execute(text(f"SET IDENTITY_INSERT {table.name} ON"))
        t.execute(table.insert(), rows)
        if target.dialect.name == "mssql" and any(c.autoincrement is True and c.primary_key for c in table.columns):
            t.execute(text(f"SET IDENTITY_INSERT {table.name} OFF"))
        print(f"{table.name}: {len(rows)} rows")
print("done - start AssetTrack_Server.exe with the same PALLET_DB_URL in settings.env")
