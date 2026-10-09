@echo off
rem AIS AssetTrack - ONE CLICK START. First time: installs the server (2-3 min), then starts it. Developed by DT
cd /d "%~dp0"
if not exist "server\.venv\Scripts\activate.bat" call "scripts\server_setup.bat"
if not exist "server\.venv\Scripts\activate.bat" ( echo Setup failed - see scripts\server_setup.log & pause & exit /b 1 )
call "scripts\server_run.bat"
