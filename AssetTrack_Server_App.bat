@echo off
set "AT=%~dp0"
rem AIS AssetTrack Server - tray application using installed Python (no EXE needed). Developed by DT
rem Same as AssetTrack_Server.exe: tray icon, port 8001, data in server\pallet.db, log server\assettrack_server.log
rem On a new PC the libraries are installed once (for this Windows user, no admin rights needed).
cd /d "%AT%server"
set "LOG=%AT%scripts\server_app.log"
echo === %date% %time% === > "%LOG%"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo PYTHON IS NOT INSTALLED on this PC.
  echo Install Python 3.11 or newer from python.org - tick "Add python.exe to PATH" - then run this again.
  pause & exit /b 1
)

python -c "import pystray, PIL, uvicorn, fastapi, sqlalchemy, jwt, bcrypt, multipart, openpyxl, httpx, segno, pypdf, reportlab" 1>nul 2>nul
if errorlevel 1 (
  echo Installing server libraries - one time on this PC, needs internet, 1-3 minutes...
  python -m pip install --user --disable-pip-version-check -r "%AT%server\requirements.txt" pystray pillow >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo   normal install failed - trying again without the optional database driver...
    python -m pip install --user --disable-pip-version-check fastapi "uvicorn[standard]" sqlalchemy pydantic PyJWT bcrypt python-multipart openpyxl httpx segno pypdf reportlab pystray pillow >> "%LOG%" 2>&1
  )
)

python -c "import pystray, PIL, uvicorn, app.main" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo SERVER APP CHECK FAILED - the reason is below ^(also in scripts\server_app.log^):
  echo ------------------------------------------------------------
  powershell -NoProfile -Command "Get-Content -Path '%LOG%' -Tail 12"
  echo ------------------------------------------------------------
  echo If it says "No module named ..." or pip could not connect: this PC has no internet / proxy for pip.
  echo   Then use the server EXE instead ^(no Python needed^) - ask for the server EXE link.
  pause & exit /b 1
)
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%P"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%AT%server\tray_app.py"
echo started >> "%LOG%"
echo AssetTrack Server started - look for the AT icon near the clock. This window closes now.
timeout /t 3 >nul
