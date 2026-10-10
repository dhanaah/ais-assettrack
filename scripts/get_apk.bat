@echo off
set "HERE=%~dp0"
rem Downloads the latest HHT APK into dist\ using a short-lived link placed in apk_url.txt. Developed by DT
cd /d "%HERE%"
if not exist apk_url.txt ( echo apk_url.txt missing - ask Claude for a fresh link, or download hht-apk from GitHub Actions. & pause & exit /b 1 )
set /p URL=<apk_url.txt
if not exist "..\dist" mkdir "..\dist"
curl -L --fail -sS -o "..\dist\hht-apk.zip" "%URL%" 2> "%HERE%get_apk.log"
if errorlevel 1 ( echo DOWNLOAD FAILED - link may have expired. & del apk_url.txt & pause & exit /b 1 )
powershell -NoProfile -Command "Expand-Archive -Force '..\dist\hht-apk.zip' '..\dist'"
del "..\dist\hht-apk.zip"
if not exist "..\server\apk" mkdir "..\server\apk"
copy /y "..\dist\AIS_AssetTrack_HHT_*.apk" "..\server\apk\" >nul 2>nul
echo APK also placed in server\apk - the HHTs now see "update available" and can download it from the server.
del apk_url.txt
start "" explorer "%HERE%..\dist"
