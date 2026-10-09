@echo off
set "HERE=%~dp0"
rem Run the server (dev, SQLite, auto-reload on code change). Ctrl+C to stop.
call "%HERE%_common.bat"
cd /d "%ROOT%\server"
if not exist .venv ( echo Run server_setup.bat first. & pause & exit /b 1 )
call .venv\Scripts\activate.bat
set PALLET_PORT=%PORT%
set PALLET_HOST=0.0.0.0
if "%PALLET_INTEGRATION_MODE%"=="" set PALLET_INTEGRATION_MODE=STUB
echo.
echo  AIS AssetTrack server  -  http://localhost:%PORT%   (login admin / Admin@123)
echo  Integration mode: %PALLET_INTEGRATION_MODE%    DB: %PALLET_DB_URL%
echo  HHT devices on the LAN: use this PC's IP, e.g. http://%COMPUTERNAME%:%PORT%
echo.
start "" http://localhost:%PORT%
uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload
