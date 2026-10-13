"""
AIS Pallet Asset Tracking - Server configuration
Developed by DT
"""
import os
from pathlib import Path

APP_NAME = "AIS AssetTrack"
APP_VERSION = "1.24.0"
API_MIN_CLIENT = os.getenv("PALLET_MIN_CLIENT", "1.6.0")   # HHT app must be >= this (settings.env PALLET_MIN_CLIENT) - older apps are told to update
DEVELOPER = "Developed by DT"

BASE_DIR = Path(__file__).resolve().parent.parent

# Database -----------------------------------------------------------------
# Dev / pilot default: SQLite file next to the project.
# SQL Server (production):
#   DB_URL="mssql+pyodbc://user:pass@SERVER\\INSTANCE/PalletDB?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
# Windows auth:
#   DB_URL="mssql+pyodbc://@SERVER/PalletDB?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes"
DB_URL = os.getenv("PALLET_DB_URL", f"sqlite:///{BASE_DIR / 'pallet.db'}")

# Security -----------------------------------------------------------------
LEGACY_SECRET = "change-me-in-production-" + APP_NAME          # the old built-in secret (public on GitHub): verification only
from datetime import datetime as _dt
LEGACY_CUTOFF = _dt(2026, 10, 11)    # old-secret labels accepted only for slips / GCS made before this (per-install secret since 10-Oct-2026)


def _load_secret() -> str:
    """Server secret for login tokens and return-slip QR check codes.
    Order: PALLET_JWT_SECRET env -> secret.key next to the database (made once, random) -> legacy default (dev only)."""
    env = os.getenv("PALLET_JWT_SECRET")
    if env:
        if "CHANGE-ME" in env.upper() or len(env) < 24:
            import logging
            logging.getLogger("assettrack").warning("PALLET_JWT_SECRET is the web.config placeholder / too short - set a long random value (labels must be reprinted after a change)")
        return env
    try:
        db_url = os.getenv("PALLET_DB_URL", "")
        folder = Path(db_url[len("sqlite:///"):]).parent if db_url.startswith("sqlite:///") else BASE_DIR
        f = folder / "secret.key"
        if f.exists():
            v = f.read_text(encoding="utf-8").strip()
            if len(v) >= 32:
                return v
        import secrets
        v = secrets.token_urlsafe(48)
        f.write_text(v, encoding="utf-8")
        return v
    except Exception as e:
        import logging
        logging.getLogger("assettrack").error("secret.key could not be read or written (%s) - using the built-in secret: QR check codes are NOT safe. Give the server folder write access.", e)
        return LEGACY_SECRET


JWT_SECRET = _load_secret()


def _job_key() -> str:
    """Key for the 5-minute retry job (scheduler.ps1 sends it). Written to server\\job.key for the scheduler to read."""
    import hmac, hashlib
    k = hmac.new(JWT_SECRET.encode(), b"JOBKEY", hashlib.sha256).hexdigest()[:32]
    try:
        f = BASE_DIR / "job.key"
        if not f.exists() or f.read_text(encoding="utf-8").strip() != k:
            f.write_text(k, encoding="utf-8")
    except Exception:
        pass
    return k


JOB_KEY = _job_key()
JWT_ALGO = "HS256"
TOKEN_HOURS = int(os.getenv("PALLET_TOKEN_HOURS", "12"))
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 30

# Operations policy ---------------------------------------------------------
# 1 = every physical transaction (scan, move, PDI, gate, return slip, confirm) must come from the HHT app.
#     The web/server is for masters, uploads, reports, dashboard, monitoring, live view and printing.
HHT_ONLY = os.getenv("PALLET_HHT_ONLY", "1") == "1"

# Defaults -----------------------------------------------------------------
DEFAULT_HOLDING_DAYS = 30
EVENT_RETENTION_DAYS = 730

# Admin bootstrap (created on first run if no users exist)
BOOTSTRAP_ADMIN_USER = os.getenv("PALLET_ADMIN_USER", "admin")
BOOTSTRAP_ADMIN_PASS = os.getenv("PALLET_ADMIN_PASS", "Admin@123")

# Where dispatch pick lists come from. BENCH (default): only the Dispatch Planning Bench creates them (pulled every few
# seconds); AssetTrack itself creates only Empty Pallet Returns. APP: AssetTrack can also release part / pallet pick lists.
PICKLIST_SOURCE = os.getenv("PALLET_PICKLIST_SOURCE", "BENCH").upper()

PUBLIC_API_URL = os.getenv("PALLET_PUBLIC_API_URL", "").strip().rstrip("/")   # internet address of the customer API (IT reverse proxy), e.g. https://assettrack.aisglass.com
SERVER_PORTS = []   # filled by the tray app: every port the server listens on (HHT failover)
