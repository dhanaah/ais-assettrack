@echo off
set "AT=%~dp0"
rem Restarts the AssetTrack tray server (after an update, or if the tray menu is stuck). Developed by DT
echo Stopping AssetTrack server...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tray_app.py*' -or $_.Name -eq 'AssetTrack_Server.exe' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('  stopped process ' + $_.ProcessId) }"
timeout /t 3 >nul
echo Starting AssetTrack server...
call "%AT%AssetTrack_Server_App.bat"
