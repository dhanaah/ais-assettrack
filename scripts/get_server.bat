@echo off
set "HERE=%~dp0"
rem Downloads the AssetTrack Server application into ..\AssetTrack_Server (safe swap: unpack to a new folder, check, then replace). Developed by DT
cd /d "%HERE%"
set "LOG=%HERE%get_server.log"
echo === %date% %time% === > "%LOG%"
if not exist server_url.txt ( echo server_url.txt missing - ask Claude for a fresh link. & pause & exit /b 1 )
set /p URL=<server_url.txt
del server_url.txt
curl -L --fail -sS -o "%HERE%..\server-exe.zip" "%URL%" 2>> "%LOG%"
if errorlevel 1 ( echo DOWNLOAD FAILED - see get_server.log & pause & exit /b 1 )
if exist "%HERE%..\AssetTrack_Server_new" rmdir /s /q "%HERE%..\AssetTrack_Server_new"
powershell -NoProfile -Command "try { Expand-Archive -Force '%HERE%..\server-exe.zip' '%HERE%..\AssetTrack_Server_new' -ErrorAction Stop } catch { $_ | Out-File -Append '%LOG%'; exit 1 }"
if errorlevel 1 ( echo UNPACK FAILED - see get_server.log & pause & exit /b 1 )
if not exist "%HERE%..\AssetTrack_Server_new\AssetTrack_Server.exe" ( echo AssetTrack_Server.exe missing after unpack - antivirus? see get_server.log & echo exe missing after unpack >> "%LOG%" & pause & exit /b 1 )
if exist "%HERE%..\AssetTrack_Server\pallet.db" copy /y "%HERE%..\AssetTrack_Server\pallet.db*" "%HERE%..\AssetTrack_Server_new\" >> "%LOG%"
if exist "%HERE%..\AssetTrack_Server_old" rmdir /s /q "%HERE%..\AssetTrack_Server_old"
if exist "%HERE%..\AssetTrack_Server" ren "%HERE%..\AssetTrack_Server" AssetTrack_Server_old
ren "%HERE%..\AssetTrack_Server_new" AssetTrack_Server
del "%HERE%..\server-exe.zip"
echo OK >> "%LOG%"
start "" explorer "%HERE%..\AssetTrack_Server"
