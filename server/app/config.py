"""
AIS Pallet Asset Tracking - Server configuration
Developed by DT
"""
import os
from pathlib import Path

APP_NAME = "AIS AssetTrack"
APP_VERSION = "1.8.1"
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


def _load_secret() -> str:
    """Server secret for login tokens and return-slip QR check codes.
    Order: PALLET_JWT_SECRET env -> secret.key next to the database (made once, random) -> legacy default (dev only)."""
    env = os.getenv("PALLET_JWT_SECRET")
    if env:
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
    except Exception:
        return LEGACY_SECRET


JWT_SECRET = _load_secret()
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

SERVER_PORTS = []   # filled by the tray app: every port the server listens on (HHT failover)
