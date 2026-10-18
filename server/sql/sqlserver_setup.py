r"""Prepare SQL Server for AssetTrack - run by iis\Setup_IIS.ps1 (or by hand). Developed by DT

  python sql\sqlserver_setup.py --server SQLSRV01\PALLET --database PalletDB --driver "ODBC Driver 18 for SQL Server"
                                [--app-login "IIS APPPOOL\AssetTrack"] [--sql-user pallet_app --sql-password ...]

Connects to the SQL Server with the Windows login of the person running it (an SQL admin), then - only what is missing:
  1. creates the database (same settings as create_db.sql: read-committed snapshot, snapshot isolation),
  2. Windows login for the IIS app pool (--app-login) or an SQL login (--sql-user / --sql-password),
     as a user of the database with db_owner (AssetTrack creates and extends its own tables).
Nothing existing is dropped or changed. A DBA can do the same with create_db.sql instead.
"""
import argparse
import sys
import urllib.parse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--database", default="PalletDB")
    ap.add_argument("--driver", default="ODBC Driver 18 for SQL Server")
    ap.add_argument("--app-login", default="")
    ap.add_argument("--sql-user", default="")
    ap.add_argument("--sql-password", default="")
    ap.add_argument("--admin-user", default="", help="SQL admin login (default: your Windows login)")
    ap.add_argument("--admin-password", default="")
    a = ap.parse_args()
    import pyodbc
    auth = f"UID={a.admin_user};PWD={a.admin_password}" if a.admin_user else "Trusted_Connection=yes"
    cs = f"DRIVER={{{a.driver}}};SERVER={a.server};DATABASE=master;{auth};TrustServerCertificate=yes"
    try:
        cn = pyodbc.connect(cs, autocommit=True, timeout=15)
    except pyodbc.Error as e:
        sys.exit(f"Cannot connect to SQL Server {a.server} as an administrator: {e}")
    cur = cn.cursor()
    db = a.database.replace("]", "")
    if not cur.execute("SELECT 1 FROM sys.databases WHERE name = ?", a.database).fetchone():
        cur.execute(f"CREATE DATABASE [{db}]")
        print(f"database {a.database} created")
    else:
        print(f"database {a.database} exists - kept")
    cur.execute(f"ALTER DATABASE [{db}] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE")
    cur.execute(f"ALTER DATABASE [{db}] SET ALLOW_SNAPSHOT_ISOLATION ON")

    def grant(login: str, windows: bool, password: str = ""):
        lg = login.replace("]", "")
        if not cur.execute("SELECT 1 FROM sys.server_principals WHERE name = ?", login).fetchone():
            if windows:
                cur.execute(f"CREATE LOGIN [{lg}] FROM WINDOWS")
            else:
                pw = password.replace("'", "''")          # CREATE LOGIN takes no parameters: quote the password
                cur.execute(f"CREATE LOGIN [{lg}] WITH PASSWORD = N'{pw}', CHECK_POLICY = ON")
            print(f"login {login} created")
        cur.execute(f"USE [{db}]")
        if not cur.execute("SELECT 1 FROM sys.database_principals WHERE name = ?", login).fetchone():
            cur.execute(f"CREATE USER [{lg}] FOR LOGIN [{lg}]")
        cur.execute(f"ALTER ROLE db_owner ADD MEMBER [{lg}]")
        cur.execute("USE master")
        print(f"{login}: db_owner on {a.database}")

    if a.app_login:
        grant(a.app_login, windows=True)
    if a.sql_user:
        if not a.sql_password:
            sys.exit("--sql-password is needed with --sql-user")
        grant(a.sql_user, windows=False, password=a.sql_password)
    cn.close()
    drv = urllib.parse.quote_plus(a.driver)
    print("OK - SQL Server ready. Connection used by AssetTrack:")
    if a.sql_user:
        print(f"  mssql+pyodbc://{a.sql_user}:***@{a.server}/{a.database}?driver={drv}&TrustServerCertificate=yes")
    else:
        print(f"  mssql+pyodbc://@{a.server}/{a.database}?driver={drv}&trusted_connection=yes&TrustServerCertificate=yes")


if __name__ == "__main__":
    main()
