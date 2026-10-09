@echo off
set "HERE=%~dp0"
rem Tag the current versions and push tags (hht-v* tag attaches the APK to a GitHub Release)
call "%HERE%_common.bat"
cd /d "%ROOT%"
for /f "tokens=2 delims==\"" %%v in ('findstr /c:"APP_VERSION" server\app\config.py') do set SVER=%%v
for /f "tokens=2 delims=:, " %%v in ('findstr /c:"\"version\"" hht\app.json') do set HVER=%%~v
echo Server %SVER%   HHT %HVER%
git tag -a server-v%SVER% -m "Server %SVER%" 2>nul
git tag -a hht-v%HVER% -m "HHT %HVER%" 2>nul
git push origin --tags
pause
