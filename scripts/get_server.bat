@echo off
set "HERE=%~dp0"
rem Downloads the AssetTrack Server application (EXE) into ..\AssetTrack_Server using a short-lived link in server_url.txt. Developed by DT
cd /d "%HERE%"
if not exist server_url.txt ( echo server_url.txt missing - ask Claude for a fresh link, or download server-exe from GitHub Actions. & pause & exit /b 1 )
set /p URL=<server_url.txt
curl -L --fail -sS -o "%HERE%..\server-exe.zip" "%URL%" 2> "%HERE%get_server.log"
if errorlevel 1 ( echo DOWNLOAD FAILED - link may have expired. & del server_url.txt & pause & exit /b 1 )
powershell -NoProfile -Command "Expand-Archive -Force '%HERE%..\server-exe.zip' '%HERE%..\AssetTrack_Server'"
del "%HERE%..\server-exe.zip"
del server_url.txt
start "" explorer "%HERE%..\AssetTrack_Server"
