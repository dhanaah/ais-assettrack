@echo off
set "HERE=%~dp0"
rem Run the server (dev, SQLite, auto-reload on code change). Close this window to stop.
call "%HERE%_common.bat"
cd /d "%ROOT%\server"
if not exist .setup_ok ( echo Run START_ASSETTRACK.bat or server_setup.bat first. & pause & exit /b 1 )
set PALLET_PORT=%PORT%
set PALLET_HOST=0.0.0.0
if "%PALLET_INTEGRATION_MODE%"=="" set PALLET_INTEGRATION_MODE=STUB
echo.
echo  AIS AssetTrack server  -  http://localhost:%PORT%   (login admin / Admin@123)
echo  Integration mode: %PALLET_INTEGRATION_MODE%
echo  HHT devices on the LAN: use this PC address, e.g. http://%COMPUTERNAME%:%PORT%
echo  Keep this window open while using AssetTrack.
echo.
start "" http://localhost:%PORT%
%PYTHON% -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload
echo.
echo Server stopped.
pause
