@echo off
rem Downloads the latest HHT APK into dist\ using a short-lived link placed in apk_url.txt. Developed by DT
cd /d "%~dp0"
if not exist apk_url.txt ( echo apk_url.txt missing - ask Claude for a fresh link, or download hht-apk from GitHub Actions. & pause & exit /b 1 )
set /p URL=<apk_url.txt
if not exist "..\dist" mkdir "..\dist"
curl -L --fail -o "..\dist\hht-apk.zip" "%URL%"
if errorlevel 1 ( echo DOWNLOAD FAILED - link may have expired. & del apk_url.txt & pause & exit /b 1 )
powershell -NoProfile -Command "Expand-Archive -Force '..\dist\hht-apk.zip' '..\dist'"
del "..\dist\hht-apk.zip"
del apk_url.txt
start "" explorer "%~dp0..\dist"
