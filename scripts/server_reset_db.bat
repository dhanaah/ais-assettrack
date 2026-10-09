@echo off
set "HERE=%~dp0"
rem Delete the dev SQLite database (fresh admin user + roles on next start). DEV ONLY.
call "%HERE%_common.bat"
cd /d "%ROOT%\server"
set /p OK=This deletes server\pallet.db (dev data). Type YES to continue: 
if /i not "%OK%"=="YES" exit /b 0
del /q pallet.db pallet.db-wal pallet.db-shm 2>nul
echo Database removed. Start server_run.bat to recreate it.
pause
