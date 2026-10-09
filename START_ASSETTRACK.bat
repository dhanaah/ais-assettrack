@echo off
rem AIS AssetTrack - ONE CLICK START. First time: installs the server (2-3 min), then starts it. Developed by DT
set "AT=%~dp0"
cd /d "%AT%"
if not exist "%AT%server\.setup_ok" call "%AT%scripts\server_setup.bat"
call "%AT%scripts\server_run.bat"
