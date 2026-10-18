@echo off
rem AIS AssetTrack - zip the server folder for deployment (IIS). Developed by DT
rem Never packs data or keys: database, secret.key, job.key, settings.env, logs, backups, documents, APKs, caches.
set "HERE=%~dp0"
call "%HERE%_common.bat"
cd /d "%ROOT%"
for /f "tokens=2 delims==\"" %%v in ('findstr /c:"APP_VERSION" server\app\config.py') do set VER=%%v
set OUT=%ROOT%\AIS_AssetTrack_Server_v%VER%.zip
if exist "%OUT%" del "%OUT%"
powershell -NoProfile -Command "Compress-Archive -Path 'server\*' -DestinationPath '%OUT%' -Force; Add-Type -AssemblyName System.IO.Compression.FileSystem; $z=[IO.Compression.ZipFile]::Open('%OUT%','Update'); $bad='(^|[\\/])(\.venv|logs|backups|gcs_docs|slip_docs|apk|tests|__pycache__|dist|build)([\\/]|$)|\.pyc$|(^|[\\/])(pallet\.db.*|secret\.key|job\.key|settings\.env|server\.pid)$'; @($z.Entries) | ? { $_.FullName -match $bad } | % { $_.Delete() }; $z.Dispose()"
echo Created %OUT%
pause
