@echo off
set "AT=%~dp0"
rem AIS AssetTrack Server - tray application using installed Python (no EXE needed). Developed by DT
rem Same as AssetTrack_Server.exe: tray icon, port 8001, data in server\pallet.db, log server\assettrack_server.log
cd /d "%AT%server"
set "LOG=%AT%scripts\server_app.log"
echo === %date% %time% === > "%LOG%"
python -c "import pystray, PIL" 1>nul 2>nul
if errorlevel 1 (
  echo Installing tray libraries ^(one time^)...
  python -m pip install --user pystray pillow >> "%LOG%" 2>&1
)
python -c "import pystray, PIL, uvicorn, app.main" >> "%LOG%" 2>&1
if errorlevel 1 ( echo SERVER APP CHECK FAILED - see scripts\server_app.log & pause & exit /b 1 )
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%P"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%AT%server\tray_app.py"
echo started >> "%LOG%"
echo AssetTrack Server started - look for the AIS icon near the clock. This window closes now.
timeout /t 3 >nul
