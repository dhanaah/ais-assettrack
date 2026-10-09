@echo off
rem AIS AssetTrack - ONE CLICK START. First time: installs the server (2-3 min), then starts it. Developed by DT
set "AT=%~dp0"
cd /d "%AT%"
if not exist "%AT%server\.venv\Scripts\activate.bat" call "%AT%scripts\server_setup.bat"
if not exist "%AT%server\.venv\Scripts\activate.bat" ( echo Setup failed - see %AT%scripts\server_setup.log & pause & exit /b 1 )
call "%AT%scripts\server_run.bat"
