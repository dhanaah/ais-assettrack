@echo off
set "HERE=%~dp0"
rem One-time: install HHT app dependencies (needs Node.js 20 LTS). JDK 17 + Android SDK needed only for hht_build_apk.bat
call "%HERE%_common.bat"
cd /d "%ROOT%\hht"
where node >nul 2>nul || ( echo Node.js not found. Install Node 20 LTS from nodejs.org & pause & exit /b 1 )
call npm install --no-audit --no-fund
echo.
echo HHT setup done. Next: hht_run_device.bat (USB device) or hht_build_apk.bat
pause
