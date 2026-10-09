"""
AIS Pallet Asset Tracking - Server configuration
Developed by DT
"""
import os
from pathlib import Path

APP_NAME = "AIS AssetTrack"
APP_VERSION = "1.4.0"
API_MIN_CLIENT = "1.0.0"          # HHT app must be >= this
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
JWT_SECRET = os.getenv("PALLET_JWT_SECRET", "change-me-in-production-" + APP_NAME)
JWT_ALGO = "HS256"
TOKEN_HOURS = int(os.getenv("PALLET_TOKEN_HOURS", "12"))
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 30

# Defaults -----------------------------------------------------------------
DEFAULT_HOLDING_DAYS = 30
EVENT_RETENTION_DAYS = 730

# Admin bootstrap (created on first run if no users exist)
BOOTSTRAP_ADMIN_USER = os.getenv("PALLET_ADMIN_USER", "admin")
BOOTSTRAP_ADMIN_PASS = os.getenv("PALLET_ADMIN_PASS", "Admin@123")
