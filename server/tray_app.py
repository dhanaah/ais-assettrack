"""AIS AssetTrack Server - Windows tray application (portable, no admin, no Python needed).
Double-click AssetTrack_Server.exe -> server starts on port 8001 (all network cards), tray icon appears.
Data (pallet.db, logs) is kept next to the EXE. Developed by DT
"""
import os, sys, shutil, socket, threading, time, traceback, webbrowser, datetime, subprocess

if "--ask-password" in sys.argv:          # helper process: shows only the password box, prints the answer
    import tkinter as tk
    from tkinter import simpledialog
    r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
    pw = simpledialog.askstring("Stop AssetTrack server", "Central admin password to stop the server:", show="*", parent=r)
    r.destroy()
    if pw:
        sys.stdout.write(pw); sys.stdout.flush()
    sys.exit(0)

BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
os.chdir(BASE_DIR)
LOG = os.path.join(BASE_DIR, "assettrack_server.log")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


def read_ports():
    """port.txt may hold one port or a list, e.g. 80,8001,8002,8003 (default; 80 = address without port number). The server listens on every free one."""
    try:
        txt = open(os.path.join(BASE_DIR, "port.txt")).read()
        ports = [int(x) for x in txt.replace(";", ",").replace(" ", ",").split(",") if x.strip().isdigit()]
        if ports:
            return ports
    except Exception:
        pass
    return [80, 8001, 8002, 8003]


PORTS = read_ports()          # wanted ports
LIVE = []                     # ports actually listening
PORT = PORTS[0]
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


def _u(host, port):
    return f"http://{host}" + ("" if port == 80 else f":{port}")


def public_name():
    """Name the HHTs should use instead of an IP: PUBLIC_NAME in settings.env (e.g. assettrack - a DNS name IT points
    to this PC), else this PC's own network name."""
    return os.environ.get("PUBLIC_NAME", "").strip() or socket.gethostname()


def urls():
    return [_u(public_name(), PORT)] + [_u(ip, PORT) for ip in ips()]


def bind_ports():
    """Open a socket on each wanted port; a busy / blocked port is skipped (logged), the rest keep working."""
    global PORT
    socks = []
    for p in PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
            s.bind(("0.0.0.0", p)); s.listen(2048); s.set_inheritable(True)
            socks.append(s); LIVE.append(p)
        except OSError as e:
            s.close(); log(f"port {p} not available ({e}) - skipped")
    if LIVE:
        PORT = LIVE[0]
    return socks


def run_server():
    global server
    try:
        socks = bind_ports()
        if not socks:
            log(f"no free port in {PORTS} - is AssetTrack already running?"); return
        config.SERVER_PORTS = list(LIVE)
        log(f"starting {config.APP_NAME} v{config.APP_VERSION} on ports {LIVE}  db={os.environ['PALLET_DB_URL']}")
        cfg = uvicorn.Config(app, log_config=None, access_log=False)
        server = uvicorn.Server(cfg)
        server.run(sockets=socks)
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
    """Password box in a separate process - a Tk window opened from the tray thread freezes on Windows."""
    try:
        cmd = [sys.executable, "--ask-password"] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__), "--ask-password"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip() or None
    except Exception as e:
        log(f"password box: {e}"); return None


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
    """Windows message box (safe from any thread); runs in the background so the tray never hangs."""
    def show():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, "AIS AssetTrack Server", 0x40 | 0x40000)   # info icon, topmost
        except Exception:
            log(text)
    threading.Thread(target=show, daemon=True).start()


_MUTEX = None


def live_port():
    import urllib.request, json
    for p in PORTS:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/v1/health", timeout=1.5) as r:
                if json.loads(r.read()).get("app") == config.APP_NAME:
                    return p
        except Exception:
            pass
    return None


def already_running():
    """True if another AssetTrack server is running: Windows named mutex (same PC) or a live /health on our ports."""
    global _MUTEX
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            _MUTEX = k.CreateMutexW(None, False, "Local\\AIS_AssetTrack_Server")
            if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
                return True
        except Exception as e:
            log(f"mutex: {e}")
    return live_port() is not None


def show_and_wait(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "AIS AssetTrack Server", 0x40 | 0x40000)
    except Exception:
        print(text)


def main():
    import pystray
    if already_running():
        log("second start refused - server already running")
        show_and_wait("AIS AssetTrack Server is already running.\n\nLook for the AIS icon near the clock (click ^ if hidden).\nThe web page opens now.")
        p = live_port()
        if p:
            webbrowser.open(_u("localhost", p))
        return
    try:
        open(os.path.join(BASE_DIR, "server.pid"), "w").write(str(os.getpid()))
    except Exception:
        pass
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=retry_job, daemon=True).start()
    time.sleep(2)
    if not LIVE:
        info_box(f"AssetTrack Server could not open any port {PORTS}.\nIt is probably already running - look for the AIS icon near the clock.")
        return

    def on_open(icon, item):
        webbrowser.open(_u("localhost", PORT))

    def on_about(icon, item):
        info_box(f"{config.APP_NAME} v{config.APP_VERSION}\n{config.DEVELOPER}\n\nHHT / web address (use the name, not the IP):\n" + urls()[0] + "\n\nIP fallback:\n" + "\n".join(urls()[1:]) +
                 f"\n\nListening on ports: {', '.join(map(str, LIVE))} (HHT switches automatically if one is slow)\n\nData folder:\n{BASE_DIR}\nIntegration mode: {integration.MODE}\n\nIf HHTs cannot connect, ask IT to allow ports {', '.join(map(str, LIVE))} in Windows Firewall.")

    def on_copy(icon, item):
        try:
            subprocess.run("clip", input=urls()[0], text=True, shell=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            log(f"copy: {e}")

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
    webbrowser.open(_u("localhost", PORT))
    icon.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"fatal: {e}\n{traceback.format_exc()}")
        raise
