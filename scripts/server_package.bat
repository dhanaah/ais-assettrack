@echo off
set "HERE=%~dp0"
rem Zip the server for deployment to IIS (excludes venv, db, logs)
call "%HERE%_common.bat"
cd /d "%ROOT%"
for /f "tokens=2 delims==\"" %%v in ('findstr /c:"APP_VERSION" server\app\config.py') do set VER=%%v
set OUT=%ROOT%\AIS_AssetTrack_Server_v%VER%.zip
if exist "%OUT%" del "%OUT%"
powershell -NoProfile -Command "Compress-Archive -Path 'server\*' -DestinationPath '%OUT%' -Force; $z=[IO.Compression.ZipFile]::Open('%OUT%','Update'); $z.Entries | ? { $_.FullName -match '^(\.venv/|logs/|__pycache__|.*\.pyc$|pallet\.db)' } | % { $_.Delete() }; $z.Dispose()"
echo Created %OUT%
pause
