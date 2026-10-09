@echo off
rem AIS AssetTrack - shared settings for the .bat helpers. Developed by DT
rem Edit these if your paths differ. Leave PYTHON empty to use "python" from PATH.
set "ROOT=%~dp0.."
set "PYTHON="
set "PORT=8001"
set "NODE_OPTIONS=--max-old-space-size=4096"
if "%PYTHON%"=="" set "PYTHON=python"
