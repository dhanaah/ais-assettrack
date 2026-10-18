r"""Copy an AssetTrack SQLite database (the portable / tray server) into SQL Server - one time, before going live on SQL.
Developed by DT

Easiest: run iis\Migrate_SQLite_to_SQLServer.bat (it uses the portable Python and asks for the paths).
By hand (server stopped, run from the server folder):
  set PALLET_DB_URL=mssql+pyodbc://...                         (the target SQL Server database)
  python sql\migrate_sqlite_to_mssql.py E:\AssetTrack\server\pallet.db [target server folder]

- Tables are created on the target. The target must be EMPTY (refused otherwise - nothing is ever overwritten).
- Every row is copied in dependency order; row counts are compared at the end.
- secret.key (and job.key) are copied from the SQLite server folder to the target server folder when given, so every
  QR already printed (slips, GCS) and every HHT sign-in stays valid on the new server.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sqlalchemy import create_engine, func, select, text  # noqa: E402
from app.db import Base, engine as target  # noqa: E402  (target = PALLET_DB_URL)
from app import models, integration, reminders  # noqa: E402, F401 (imported to register all tables)
from app import activity  # noqa: E402, F401

CHUNK = 500
BUSINESS = ("plants", "pallets", "picklists", "return_slips", "lpns")    # any row here = real data: never overwritten


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else "pallet.db"
    target_dir = sys.argv[2] if len(sys.argv) > 2 else None
    if target.dialect.name != "mssql":
        sys.exit("PALLET_DB_URL must point to the SQL Server database (target), e.g. mssql+pyodbc://...")
    if not os.path.exists(src_path):
        sys.exit(f"SQLite database not found: {src_path}")
    src = create_engine(f"sqlite:///{src_path}")
    Base.metadata.create_all(bind=target)
    with target.connect() as t:
        filled = [tb.name for tb in Base.metadata.sorted_tables if t.execute(select(func.count()).select_from(tb)).scalar()]
        business = [n for n in BUSINESS if t.execute(select(func.count()).select_from(Base.metadata.tables[n])).scalar()]
    fresh_start = bool(filled) and not business
    if business:
        sys.exit("Target SQL Server database already holds AssetTrack data (" + ", ".join(business) + ") - use a new, empty database. Nothing was copied.")
    if fresh_start:
        # the new server was started once (IIS setup check): only its first-start rows (roles, admin, settings) - replaced by the copy
        with target.begin() as t:
            for tb in reversed(Base.metadata.sorted_tables):
                t.execute(tb.delete())
        print("Target held only the first-start rows of a new server - cleared, copying now.")
    q = target.dialect.identifier_preparer
    total = 0
    with src.connect() as s, target.begin() as t:
        src_tables = set(src.dialect.get_table_names(s))
        for table in Base.metadata.sorted_tables:
            if table.name not in src_tables:
                continue
            have = {c["name"] for c in src.dialect.get_columns(s, table.name)}
            cols = [c for c in table.columns if c.name in have]       # older SQLite files may miss newer columns (stay NULL / default)
            rows = [dict(r._mapping) for r in s.execute(select(*cols))]
            if not rows:
                continue
            ident = table.autoincrement_column is not None          # an IDENTITY column on SQL Server: keep the ids as they are
            if ident:
                t.execute(text(f"SET IDENTITY_INSERT {q.format_table(table)} ON"))
            for i in range(0, len(rows), CHUNK):
                t.execute(table.insert(), rows[i:i + CHUNK])
            if ident:
                t.execute(text(f"SET IDENTITY_INSERT {q.format_table(table)} OFF"))
            total += len(rows)
            print(f"{table.name}: {len(rows)} rows")
    bad = []
    with src.connect() as s, target.connect() as t:
        src_tables = set(src.dialect.get_table_names(s))
        for table in Base.metadata.sorted_tables:
            if table.name in src_tables:
                a = s.execute(select(func.count()).select_from(table)).scalar()
                b = t.execute(select(func.count()).select_from(table)).scalar()
                if a != b:
                    bad.append(f"{table.name}: SQLite {a} / SQL Server {b}")
    if bad:
        sys.exit("ROW COUNTS DIFFER:\n  " + "\n  ".join(bad))
    print(f"\n{total} rows copied - row counts match on every table.")
    if target_dir:
        src_dir = os.path.dirname(os.path.abspath(src_path))
        for k in ("secret.key", "job.key"):
            a, b = os.path.join(src_dir, k), os.path.join(target_dir, k)
            if os.path.exists(a) and (not os.path.exists(b) or fresh_start):
                if os.path.exists(b):
                    shutil.copy2(b, b + ".first-start")        # the new server's own first key, kept aside
                shutil.copy2(a, b)
                print(f"{k} copied to {target_dir} (printed QRs and HHT sign-ins stay valid) - restart the server now")
            elif os.path.exists(a) and os.path.exists(b) and open(a).read().strip() != open(b).read().strip():
                print(f"WARNING: {b} already exists and differs from the SQLite server's {k} - printed QRs need the old one.")
    print("Done - start the SQL Server installation (IIS site or tray with the same PALLET_DB_URL).")


if __name__ == "__main__":
    main()
