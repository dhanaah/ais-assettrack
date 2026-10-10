from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import DB_URL

connect_args = {}
engine_kwargs = dict(pool_pre_ping=True, future=True)
if DB_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}   # wait up to 30 s for a busy database instead of failing
else:
    engine_kwargs.update(pool_size=10, max_overflow=20, fast_executemany=True)

engine = create_engine(DB_URL, connect_args=connect_args, **engine_kwargs)

if DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns():
    """Light auto-migration: adds new nullable columns to existing tables after an upgrade (SQLite + SQL Server).
    Existing data is never touched."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for t in Base.metadata.sorted_tables:
            if not insp.has_table(t.name):
                continue
            have = {c["name"] for c in insp.get_columns(t.name)}
            for col in t.columns:
                if col.name in have:
                    continue
                ctype = col.type.compile(dialect=engine.dialect)
                default = ""
                d = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                if d is not None:
                    default = f" DEFAULT {int(d) if isinstance(d, bool) else (repr(d) if isinstance(d, str) else d)}"
                    if engine.dialect.name == "mssql":
                        default += " WITH VALUES"
                kw = "ADD" if engine.dialect.name == "mssql" else "ADD COLUMN"
                conn.execute(text(f'ALTER TABLE {t.name} {kw} {col.name} {ctype}{default}'))
