"""AIS AssetTrack Server - Windows tray application (portable, no admin, no Python needed).
Double-click AssetTrack_Server.exe -> server starts on port 8001 (all network cards), tray icon appears.
Data (pallet.db, logs) is kept next to the EXE. Developed by DT
"""
import os, sys, shutil, socket, threading, time, traceback, webbrowser, datetime

BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
os.chdir(BASE_DIR)
LOG = os.path.join(BASE_DIR, "assettrack_server.log")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


def read_port():
    try:
        return int(open(os.path.join(BASE_DIR, "port.txt")).read().strip())
    except Exception:
        return 8001


PORT = read_port()
DB = os.path.join(BASE_DIR, "pallet.db")
# first start next to an existing AssetTrack folder: take over its database (keeps your data)
if not os.path.exists(DB):
    for cand in (os.path.join(BASE_DIR, "..", "server", "pallet.db"), os.path.join(BASE_DIR, "..", "pallet.db")):
        if os.path.exists(cand):
            shutil.copy2(cand, DB); log(f"copied existing database from {cand}"); break
os.environ.setdefault("PALLET_DB_URL", "sqlite:///" + DB.replace("\\", "/"))
os.environ.setdefault("PALLET_INTEGRATION_MODE", "STUB")
if os.path.exists(os.path.join(BASE_DIR, "settings.env")):          # optional KEY=VALUE overrides
    for line in open(os.path.join(BASE_DIR, "settings.env"), encoding="utf-8"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1); os.environ[k.strip()] = v.strip()

if sys.stdout is None:            # --noconsole build: give uvicorn somewhere to write
    sys.stdout = open(os.devnull, "w"); sys.stderr = open(os.devnull, "w")

import uvicorn
from app.main import app
from app import config, integration
from app.db import SessionLocal

server = None


def ips():
    out = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                out.add(ip)
    except Exception:
        pass
    return sorted(out)


def urls():
    return [f"http://{ip}:{PORT}" for ip in ips()] or [f"http://localhost:{PORT}"]


def run_server():
    global server
    try:
        log(f"starting {config.APP_NAME} v{config.APP_VERSION} on 0.0.0.0:{PORT}  db={os.environ['PALLET_DB_URL']}")
        cfg = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_config=None, access_log=False)
        server = uvicorn.Server(cfg)
        server.run()
        log("server stopped")
    except Exception as e:
        log(f"server crash: {e}\n{traceback.format_exc()}")


def retry_job():
    """EBS / GCS retry queue every 5 minutes (replaces scheduler.ps1)."""
    while True:
        time.sleep(300)
        try:
            with SessionLocal() as db:
                integration.run_retries(db)
        except Exception as e:
            log(f"retry job: {e}")


def make_icon():
    from PIL import Image
    for p in (os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "app", "static", "icon-192.png"), os.path.join(BASE_DIR, "app", "static", "icon-192.png")):
        if os.path.exists(p):
            return Image.open(p).convert("RGBA").resize((64, 64))
    return Image.new("RGBA", (64, 64), (30, 58, 138, 255))


def ask_password():
    try:
        import tkinter as tk
        from tkinter import simpledialog
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        pw = simpledialog.askstring("Stop AssetTrack server", "Central admin password to stop the server:", show="*", parent=r)
        r.destroy(); return pw
    except Exception:
        return None


def admin_ok(pw):
    if not pw:
        return False
    from app import models
    from app.security import check_pw, load_perms
    with SessionLocal() as db:
        for u in db.query(models.User).filter(models.User.active == True, models.User.plant_code.is_(None)).all():
            if check_pw(pw, u.password_hash) and ("INTEGRATION_CONFIG" in load_perms(db, u) or "USER_ADMIN" in load_perms(db, u)):
                return True
    return False


def info_box(text):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        messagebox.showinfo("AIS AssetTrack Server", text, parent=r); r.destroy()
    except Exception:
        pass


def main():
    import pystray
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=retry_job, daemon=True).start()
    time.sleep(2)

    def on_open(icon, item):
        webbrowser.open(f"http://localhost:{PORT}")

    def on_about(icon, item):
        info_box(f"{config.APP_NAME} v{config.APP_VERSION}\n{config.DEVELOPER}\n\nWeb / HHT address:\n" + "\n".join(urls()) +
                 f"\n\nData folder:\n{BASE_DIR}\nIntegration mode: {integration.MODE}\n\nIf HHTs cannot connect, ask IT to allow port {PORT} in Windows Firewall.")

    def on_copy(icon, item):
        try:
            import tkinter as tk
            r = tk.Tk(); r.withdraw(); r.clipboard_clear(); r.clipboard_append(urls()[0]); r.update(); r.destroy()
        except Exception:
            pass

    def on_exit(icon, item):
        if admin_ok(ask_password()):
            log("stopped from tray")
            if server:
                server.should_exit = True
            icon.stop()
        else:
            info_box("Wrong password - server keeps running.")

    menu = pystray.Menu(pystray.MenuItem("Open AssetTrack", on_open, default=True),
                        pystray.MenuItem("Copy network address", on_copy),
                        pystray.MenuItem("About / HHT address", on_about),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("Stop server (admin)", on_exit))
    icon = pystray.Icon("AssetTrack", make_icon(), f"AIS AssetTrack Server v{config.APP_VERSION} - {urls()[0]}", menu)
    webbrowser.open(f"http://localhost:{PORT}")
    icon.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"fatal: {e}\n{traceback.format_exc()}")
        raise
