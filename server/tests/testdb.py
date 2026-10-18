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
