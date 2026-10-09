@echo off
rem Commit everything and push to GitHub (CI then builds the APK). Usage: git_push.bat "message"
call "%~dp0_common.bat"
cd /d "%ROOT%"
set MSG=%~1
if "%MSG%"=="" set /p MSG=Commit message: 
git add -A
git commit -m "%MSG%"
git pull --rebase origin main
git push origin main
echo.
echo Pushed. APK will appear under GitHub - Actions - latest run - Artifacts (hht-apk).
pause
